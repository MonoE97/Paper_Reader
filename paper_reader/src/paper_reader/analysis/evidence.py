"""Map named evidence members to the v3 store's content-addressed files.

Logical member names are only used by the shared evidence algorithms, never
opened as paths. Every byte is read through the RunStore's hash-checked API.
"""
from pathlib import Path
from typing import Literal

from paper_reader.analysis.contracts import PaperMetadata, PdfSource, PreparedPaper
from paper_reader.official.models import ZoteroSelection
from paper_reader.contracts import ArtifactRef, ArtifactPath, Sha256, StrictContractModel
from paper_reader.evidence_manifest import BoundEvidence, EvidenceManifest, VerifiedEvidenceArtifact, validate_evidence_members
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.store import RunStore
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256


class EvidenceMember(StrictContractModel):
    name: ArtifactPath
    artifact: ArtifactRef


class AnalysisEvidence(StrictContractModel):
    format: Literal['paper_reader.analysis-evidence.v3-internal']
    input_digest: Sha256
    manifest: EvidenceManifest
    members: tuple[EvidenceMember, ...]


def publish_member(store: RunStore, name: str, content: bytes, role: str,
                   media_type: str = 'application/json') -> EvidenceMember:
    ref = store.publish_bytes(content, role='evidence').model_copy(update={'role': role, 'media_type': media_type})
    return EvidenceMember(name=name, artifact=ref)


def bind_evidence(ref: ArtifactRef, *, store: RunStore) -> BoundEvidence:
    raw = store.read_bytes(ref)
    bundle = AnalysisEvidence.model_validate_json(raw)
    if canonical_json_bytes(bundle) != raw:
        raise WorkflowError('verification_failed', 'noncanonical analysis evidence')
    if tuple(member.artifact for member in bundle.members) != bundle.manifest.files:
        raise WorkflowError('verification_failed', 'evidence membership differs from manifest')
    validate_evidence_members(bundle.manifest)
    names = [member.name for member in bundle.members]
    if len(names) != len(set(names)):
        raise WorkflowError('verification_failed', 'duplicate logical evidence member')
    by_role = {}
    logical_root = Path('/evidence')
    for member in bundle.members:
        artifact = member.artifact
        value = VerifiedEvidenceArtifact(artifact, logical_root / member.name, store.read_bytes(artifact))
        by_role.setdefault(artifact.role, []).append(value)
    for role in ('metadata', 'extract', 'context', 'section_context', 'secondary_sources'):
        if len(by_role.get(role, ())) != 1:
            raise WorkflowError('verification_failed', 'required evidence role missing or ambiguous')
    return BoundEvidence(bundle.manifest, ref, logical_root / 'evidence.json', raw, ref.sha256,
                         {role: tuple(values) for role, values in by_role.items()})


def input_digest(*, run_id: str, created_at: str, source: PdfSource, metadata: PaperMetadata,
                 selection: ZoteroSelection | None, snapshots: tuple[ArtifactRef, ...]) -> str:
    return canonical_json_sha256(dict(run_id=run_id, created_at=created_at,
        source=source.model_dump(mode='json'), metadata=metadata.model_dump(mode='json'),
        selection=selection.model_dump(mode='json') if selection is not None else None,
        snapshots=[ref.model_dump(mode='json') for ref in snapshots]))


def check_prepared_inputs(prepared: PreparedPaper, bundle: AnalysisEvidence) -> None:
    if bundle.input_digest != input_digest(run_id=prepared.run_id, created_at=prepared.created_at,
            source=prepared.source, metadata=prepared.metadata, selection=prepared.selection,
            snapshots=prepared.source_snapshots):
        raise WorkflowError('source_changed', 'prepared inputs differ from immutable evidence')


def bind_prepared_evidence(prepared: PreparedPaper, *, store: RunStore) -> BoundEvidence:
    """Canonical prepared/source/member closure shared by sealing and planning."""
    evidence = bind_evidence(prepared.evidence_manifest, store=store)
    check_prepared_inputs(prepared, AnalysisEvidence.model_validate_json(evidence.manifest_bytes))
    if (evidence.manifest.run_id != prepared.run_id or evidence.manifest.source_sha256 != prepared.source.sha256
            or evidence.manifest.files != prepared.artifacts or prepared.context not in prepared.artifacts):
        raise WorkflowError('verification_failed', 'analysis evidence/source/run binding mismatch')
    if prepared.selection is not None:
        if store.read_bytes(prepared.selection.parent_snapshot) != canonical_json_bytes(prepared.selection.parent.raw_json):
            raise WorkflowError('source_changed', 'selected parent snapshot changed')
    return evidence
