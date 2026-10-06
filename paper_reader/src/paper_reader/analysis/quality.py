"""Transport- and lifecycle-independent review checks shared by v2 and v3."""
from dataclasses import dataclass
import json

from paper_reader.contracts import GateBlocker, SummaryFields, ReviewFields
from paper_reader.evidence_manifest import BoundEvidence, locator_membership_error
from paper_reader.note import (markdown_table_cell, render_note, render_note_html,
                               validate_note, validate_trusted_summary)
from paper_reader.secondary_projection import SecondaryProjectionError, resolve_secondary_render_summary
from paper_reader.storage import canonical_json_sha256
from paper_reader.summary_lint import lint_summary, lint_rendered_markdown


def _blocker(code, message, artifact_path=None):
    return GateBlocker(code=code, message=message, artifact_path=artifact_path)


@dataclass(frozen=True)
class QualityResult:
    rendered_note: str | None
    rendered_html: str | None
    blockers: tuple[GateBlocker, ...]


def _validate_locator_bindings(
    summary: SummaryFields,
    evidence: BoundEvidence,
    blockers: list[GateBlocker],
) -> None:
    for claim_index, claim in enumerate(summary.evidence_summary):
        for evidence_index, item in enumerate(claim.evidence):
            error = locator_membership_error(item.locator, evidence.manifest)
            if error is not None:
                blockers.append(
                    _blocker(
                        "invalid_evidence_locator",
                        (
                            f"evidence_summary[{claim_index}].evidence[{evidence_index}] "
                            f"failed membership: {error}: {item.locator}"
                        ),
                        "summary.json",
                    )
                )
    for field_name, values in (
        ("author_stated_limitations", summary.author_stated_limitations),
        ("inferred_limits", summary.inferred_limits),
    ):
        for index, item in enumerate(values):
            error = locator_membership_error(item.locator, evidence.manifest)
            if error is not None:
                blockers.append(
                    _blocker(
                        "invalid_evidence_locator",
                        f"{field_name}[{index}] failed membership: {error}: {item.locator}",
                        "summary.json",
                    )
                )
    figure_ids = {item.figure_id for item in evidence.manifest.figures}
    for index, figure in enumerate(summary.key_figures):
        if figure.figure_id not in figure_ids:
            blockers.append(
                _blocker(
                    "figure_not_in_evidence",
                    f"key_figures[{index}] is not a manifest figure member: {figure.figure_id}",
                    "summary.json",
                )
            )


def validate_analysis_quality(*, run_id: str, created_at: str,
                              summary: SummaryFields | None, review: ReviewFields | None,
                              evidence: BoundEvidence | None) -> QualityResult:
    blockers: list[GateBlocker] = []
    summary_sha256 = canonical_json_sha256(summary) if summary is not None else None
    rendered_note = rendered_html = None
    resolved_summary_payload = None
    trusted_secondary_source_links = ()
    if summary is not None:
        if summary.run_id != run_id:
            blockers.append(_blocker("summary_run_mismatch", "summary run_id does not match run.json", "summary.json"))
        if evidence is not None:
            if not evidence.manifest.complete:
                blockers.append(
                    _blocker(
                        "incomplete_evidence",
                        "preview evidence cannot be sealed or used for a candidate",
                        evidence.manifest_ref.path,
                    )
                )
            _validate_locator_bindings(summary, evidence, blockers)
            try:
                resolved_summary_payload = resolve_secondary_render_summary(
                    summary,
                    evidence,
                )
                raw_trusted_links = resolved_summary_payload.pop(
                    "_secondary_trusted_source_links",
                    [],
                )
                if not isinstance(raw_trusted_links, list) or not all(
                    isinstance(item, str) and item for item in raw_trusted_links
                ):
                    raise SecondaryProjectionError(
                        "secondary_evidence_invalid",
                        "resolved secondary source link provenance is invalid",
                    )
                rendered_link_variants: list[str] = []
                for source_link in raw_trusted_links:
                    for variant in (source_link, markdown_table_cell(source_link)):
                        if variant not in rendered_link_variants:
                            rendered_link_variants.append(variant)
                trusted_secondary_source_links = tuple(rendered_link_variants)
            except SecondaryProjectionError as exc:
                blockers.append(_blocker(exc.code, str(exc), "summary.json"))

        summary_payload = summary.model_dump(mode="json")
        for message in validate_trusted_summary(summary_payload):
            blockers.append(_blocker("summary_not_write_ready", message, "summary.json"))
        for issue in lint_summary(summary_payload):
            blockers.append(_blocker(issue["code"], issue["message"], "summary.json"))

    if review is not None:
        if review.run_id != run_id:
            blockers.append(_blocker("review_run_mismatch", "review run_id does not match run.json", "review.json"))
        if summary_sha256 is not None and review.summary_sha256 != summary_sha256:
            blockers.append(
                _blocker(
                    "summary_hash_mismatch",
                    "review summary_sha256 does not match canonical summary.json",
                    "review.json",
                )
            )
        if summary is not None and review.evidence_digest != summary.evidence_digest:
            blockers.append(
                _blocker(
                    "review_evidence_mismatch",
                    "review evidence_digest does not match summary evidence_digest",
                    "review.json",
                )
            )
        if review.review_status not in {"passed", "passed_with_caveats"}:
            blockers.append(_blocker("review_failed", "review_status must pass before sealing", "review.json"))
        if review.needs_improvement:
            blockers.append(
                _blocker("review_needs_improvement", "review still requires improvement", "review.json")
            )
        for index, issue in enumerate(review.review_issues):
            if issue.severity == "blocker":
                blockers.append(
                    _blocker(
                        "review_issue_blocker",
                        f"review_issues[{index}] is marked as a blocker: {issue.issue}",
                        "review.json",
                    )
                )
        if summary is not None and summary.review_status != review.review_status:
            blockers.append(
                _blocker(
                    "review_status_mismatch",
                    "summary and review status do not match",
                    "review.json",
                )
            )

    if summary is not None and evidence is not None and resolved_summary_payload is not None:
        try:
            metadata_artifact = evidence.artifacts_by_role["metadata"][0]
            metadata = json.loads(metadata_artifact.raw_bytes)
            if not isinstance(metadata, dict):
                raise ValueError("metadata must be an object")
            rendered_note = render_note(
                metadata,
                resolved_summary_payload,
                generated_date=created_at[:10],
            )
            rendered_html = render_note_html(rendered_note)
        except Exception as exc:
            blockers.append(_blocker("note_render_failed", f"note rendering failed: {exc}"))
        else:
            for message in validate_note(rendered_note):
                blockers.append(_blocker("invalid_rendered_note", message))
            for issue in lint_rendered_markdown(
                rendered_note,
                trusted_source_links=trusted_secondary_source_links,
            ):
                blockers.append(_blocker(issue["code"], issue["message"], "summary.json"))

    return QualityResult(rendered_note, rendered_html, tuple(blockers))
