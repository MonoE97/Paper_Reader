"""Explicit secondary evidence enrichment; this module never fetches a URL."""
from pathlib import Path

from pydantic import ValidationError
from paper_reader.secondary_projection import SecondaryInventory

from paper_reader.evidence_manifest import BoundEvidence
from paper_reader.analysis.contracts import PreparedPaper
from paper_reader.analysis.evidence import AnalysisEvidence, bind_evidence, check_prepared_inputs, publish_member
from paper_reader.official.models import ZoteroSelection
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.store import RunStore
from paper_reader.secondary_evidence import (BoundSecondaryPlan, SecondaryPlan,
    SecondaryEvidenceFiles, build_secondary_evidence_files, load_secondary_inputs)
from paper_reader.secondary_sources import build_secondary_source_plan, USAGE_BOUNDARY
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256


def secondary_member_role(name: str) -> tuple[str, str]:
    roles = {'secondary-plan.json': ('secondary_plan', 'application/json'),
             'secondary_sources.json': ('secondary_sources', 'application/json'),
             'secondary_context.md': ('secondary_context', 'text/markdown')}
    if name.startswith('secondary/') and name.endswith('.json'):
        return 'secondary_capture', 'application/json'
    return roles[name]


def secondary_files(selection: ZoteroSelection | None, *, run_id: str) -> SecondaryEvidenceFiles:
    binding = None
    title = ''
    if selection is not None:
        data = {**selection.parent.raw_json['data'], 'key': selection.item_key}
        title = selection.parent.data.title
        plan = SecondaryPlan.model_validate_json(canonical_json_bytes(build_secondary_source_plan(data,
            source_snapshot_sha256=selection.parent_snapshot.sha256, finding_anchor_policy='codepoint_sha256_v1')))
        binding = BoundSecondaryPlan(plan, canonical_json_bytes(plan), run_id, canonical_json_sha256(plan))
    return build_secondary_evidence_files(plan_binding=binding, captures={}, canonical_capture_bytes={},
        fallback_inventory={'sources': [], 'warnings': [], 'usage_boundary': USAGE_BOUNDARY}, title=title)


def attach_secondary_captures(prepared: PreparedPaper, capture_dir: Path, *, store: RunStore) -> PreparedPaper:
    """Create a new evidence revision for the same run; previous bytes remain intact."""
    if prepared.selection is None:
        raise WorkflowError('verification_failed', 'local PDF analysis does not accept secondary captures')
    evidence = bind_evidence(prepared.evidence_manifest, store=store)
    validate_secondary_source(prepared, evidence)
    plans = evidence.artifacts_by_role.get('secondary_plan', ())
    if len(plans) != 1:
        raise WorkflowError('verification_failed', 'prepared Zotero evidence requires one secondary plan')
    plan_artifact = plans[0]
    plan = SecondaryPlan.model_validate_json(plan_artifact.raw_bytes)
    if plan.source_snapshot_sha256 != prepared.selection.parent_snapshot.sha256:
        raise WorkflowError('source_changed', 'secondary plan belongs to a different source')
    binding = BoundSecondaryPlan(plan, plan_artifact.raw_bytes, prepared.run_id, plan_artifact.ref.sha256)
    bundle = AnalysisEvidence.model_validate_json(evidence.manifest_bytes)
    check_prepared_inputs(prepared, bundle)
    with load_secondary_inputs(binding, capture_dir) as inputs:
        files = build_secondary_evidence_files(plan_binding=binding, captures=inputs.captures,
            canonical_capture_bytes=inputs.canonical_capture_bytes, fallback_inventory={}, title=prepared.metadata.title)
        inputs.verify()
        members = tuple(member for member in bundle.members if not member.artifact.role.startswith('secondary_'))
        members += tuple(publish_member(store, name, raw, *secondary_member_role(name)) for name, raw in files.files.items())
        manifest = bundle.manifest.model_copy(update={'files': tuple(member.artifact for member in members),
            'degraded': files.degraded or any(check.status == 'degraded' for check in bundle.manifest.resource_checks)})
        changed = bundle.model_copy(update={'manifest': manifest, 'members': members})
        ref = store.publish_bytes(canonical_json_bytes(changed), role='evidence')
        inputs.verify()
    updated = prepared.model_copy(update={'evidence_manifest': ref, 'artifacts': tuple(m.artifact for m in members)})
    store.publish(updated)
    return updated


def validate_secondary_source(prepared: PreparedPaper, evidence: BoundEvidence) -> None:
    """Bind the shared secondary value format to this v3 source, never a legacy plan."""
    expected = secondary_files(prepared.selection, run_id=prepared.run_id)
    plans = evidence.artifacts_by_role.get('secondary_plan', ())
    if prepared.selection is None:
        if plans or evidence.artifacts_by_role.get('secondary_capture'):
            raise WorkflowError('verification_failed', 'local analysis cannot bind secondary plans/captures')
        if evidence.artifacts_by_role['secondary_sources'][0].raw_bytes != expected.files['secondary_sources.json']:
            raise WorkflowError('verification_failed', 'local secondary inventory must remain empty')
    else:
        if len(plans) != 1 or plans[0].raw_bytes != expected.files['secondary-plan.json']:
            raise WorkflowError('verification_failed', 'secondary plan differs from the selected source')
        try:
            SecondaryInventory.model_validate_json(evidence.artifacts_by_role['secondary_sources'][0].raw_bytes)
        except ValidationError:
            raise WorkflowError('verification_failed', 'Zotero secondary inventory must remain versioned') from None
