"""Seal the shared quality result and publish a v3 immutable note candidate."""
import json

from paper_reader.analysis.contracts import PreparedPaper, Summary, Review, ReviewPackage, NoteCandidate
from paper_reader.analysis.evidence import bind_prepared_evidence
from paper_reader.analysis.quality import validate_analysis_quality
from paper_reader.analysis.secondary import validate_secondary_source
from paper_reader.analysis.rendering import _rewrite_markdown_h1, build_note_title
from paper_reader.contracts import GateState
from paper_reader.evidence_bundle import _verified_pdf_snapshot
from paper_reader.note import build_note_labels, render_note_html
from paper_reader.note_hash import canonicalize_note_html_for_hash, note_html_sha256
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.store import RunStore
from paper_reader.review_package import ReviewSealError
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256, new_random_id, rfc3339_utc
from paper_reader.zotero_live import _parse_headings


def seal_analysis(prepared: PreparedPaper, summary: Summary, review: Review, *, store: RunStore) -> NoteCandidate:
    # Revalidate typed callers as well as every immutable byte before publication.
    prepared = PreparedPaper.model_validate_json(canonical_json_bytes(prepared))
    summary = Summary.model_validate_json(canonical_json_bytes(summary))
    review = Review.model_validate_json(canonical_json_bytes(review))
    evidence = bind_prepared_evidence(prepared, store=store)
    if summary.evidence_digest != evidence.digest:
        raise WorkflowError('verification_failed', 'analysis evidence/source/run binding mismatch')
    validate_secondary_source(prepared, evidence)
    snapshots = {ref.role: store.read_bytes(ref) for ref in prepared.source_snapshots}
    with _verified_pdf_snapshot(prepared.source, run_id=prepared.run_id):
        quality = validate_analysis_quality(run_id=prepared.run_id, created_at=prepared.created_at,
                                           summary=summary, review=review, evidence=evidence)
        if quality.blockers:
            raise ReviewSealError('review_blocked', 'analysis quality validation is blocked', blockers=quality.blockers)
        if quality.rendered_note is None:
            raise ReviewSealError('review_blocked', 'analysis did not render a note')
        notes = []
        if prepared.selection is not None:
            if 'zotero_children' not in snapshots:
                raise WorkflowError('verification_failed', 'Zotero preparation must bind children')
            for child in json.loads(snapshots['zotero_children']):
                if child['data']['item_type'] == 'note':
                    notes.append(child['data']['note'])
        title = build_note_title(prepared.metadata.title, prepared.created_at[:10], notes)
        markdown = _rewrite_markdown_h1(quality.rendered_note.encode(), title)
        html = render_note_html(markdown.decode())
        if _parse_headings(html)[0] != title:
            raise WorkflowError('verification_failed', 'visible note title differs from candidate')
        # All gates finish before the first mutation. Store references form the full sealed closure.
        markdown_ref = store.publish_bytes(markdown, role='note')
        html_ref = store.publish_bytes(html.encode(), role='note')
        summary_ref, review_ref = store.publish(summary), store.publish(review)
        gate = GateState(status='passed', evaluated_at=rfc3339_utc(), checks=(
            'summary_schema', 'review_schema', 'run_binding', 'evidence_binding',
            'locator_membership', 'resolved_render_chinese_prose', 'literal_title'), blockers=())
        package = ReviewPackage(schema_version='paper_reader.review-package.v3',
            review_package_id=new_random_id('review-package'), run_id=prepared.run_id, created_at=rfc3339_utc(),
            summary=summary_ref, review=review_ref, evidence_manifest=prepared.evidence_manifest,
            summary_sha256=canonical_json_sha256(summary), review_sha256=canonical_json_sha256(review),
            evidence_digest=evidence.digest, artifacts=(summary_ref, review_ref, markdown_ref, html_ref,
                prepared.evidence_manifest, *prepared.artifacts), gate=gate)
        sealed_ref = store.publish(package)
        run_ref = store.publish(prepared)
        candidate = NoteCandidate(schema_version='paper_reader.candidate.v3', candidate_id=new_random_id('candidate'),
            run_id=prepared.run_id, created_at=rfc3339_utc(), source=prepared.source, run_snapshot=run_ref,
            target=prepared.selection, evidence_manifest=prepared.evidence_manifest, sealed_review=sealed_ref,
            note_title=title, note_markdown=markdown_ref, note_html=html_ref,
            tags=tuple(build_note_labels(summary.model_dump(mode='json'))), content_sha256=note_html_sha256(html),
            content_length=len(canonicalize_note_html_for_hash(html)),
            artifacts=(run_ref, sealed_ref, *package.artifacts, *prepared.source_snapshots), gate=gate)
        store.publish(candidate)
        return candidate
