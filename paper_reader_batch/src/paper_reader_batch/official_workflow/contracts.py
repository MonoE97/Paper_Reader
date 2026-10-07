"""Batch-owned contracts and opaque core reference envelopes, never core schemas."""
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, JsonValue, model_validator

from paper_reader_batch.v2_contracts import NonEmptyString, Sha256, StrictModel, UuidString, Rfc3339Utc
from paper_reader_batch.v2_json import canonical_sha256


class CoreArtifactRef(StrictModel):
    role: NonEmptyString
    path: NonEmptyString
    sha256: Sha256
    size_bytes: Annotated[int, Field(ge=0)]
    media_type: str | None = None

    @model_validator(mode='after')
    def relative_path(self) -> Self:
        path = Path(self.path)
        if path.is_absolute() or '..' in path.parts or path.as_posix() != self.path:
            raise ValueError('core artifact paths must be relative and normalized')
        return self


class BoundArtifactRef(StrictModel):
    run_root: Path
    run_id: NonEmptyString
    artifact: CoreArtifactRef

    @model_validator(mode='after')
    def absolute_root(self) -> Self:
        if not self.run_root.is_absolute() or '..' in self.run_root.parts:
            raise ValueError('explicit absolute run root required')
        return self


class BoundApprovalRef(BoundArtifactRef):
    plan: CoreArtifactRef


class CoreCommandResult(StrictModel):
    schema_version: Literal['paper_reader.command-result.v3']
    command: NonEmptyString
    ok: bool
    code: NonEmptyString
    created_at: Rfc3339Utc
    artifacts: tuple[CoreArtifactRef, ...]
    data: dict[str, JsonValue] | None

    @model_validator(mode='after')
    def consistent_status(self) -> Self:
        if self.ok != (self.code == 'ok'):
            raise ValueError('core status and code disagree')
        return self


class BatchManifest(StrictModel):
    schema_version: Literal['paper_reader_batch.manifest.v3']
    batch_id: NonEmptyString
    paper_reader_root: Path
    plan_refs: Annotated[tuple[BoundArtifactRef, ...], Field(min_length=1, max_length=1000)]

    @model_validator(mode='after')
    def unique_plans(self) -> Self:
        if not self.paper_reader_root.is_absolute() or '..' in self.paper_reader_root.parts:
            raise ValueError('explicit absolute core root required')
        if len({(r.run_root, r.artifact.sha256) for r in self.plan_refs}) != len(self.plan_refs):
            raise ValueError('duplicate plan')
        if any(ref.artifact.role != 'zotero-plan' for ref in self.plan_refs):
            raise ValueError('manifest requires plan references')
        return self


class PreviewEntry(StrictModel):
    reference: BoundArtifactRef
    preview: dict[str, JsonValue]


class BatchPreview(StrictModel):
    manifest_sha256: Sha256
    plans: tuple[PreviewEntry, ...]

    @property
    def sha256(self) -> str:
        return canonical_sha256(self)


class PreviewDocument(StrictModel):
    preview: BatchPreview
    preview_sha256: Sha256

    @model_validator(mode='after')
    def digest_matches(self) -> Self:
        if self.preview_sha256 != self.preview.sha256:
            raise ValueError('preview document digest mismatch')
        return self


class SubjectReport(StrictModel):
    subject_id: NonEmptyString
    title: NonEmptyString
    plan: BoundArtifactRef
    status: Literal['verified', 'skipped', 'blocked', 'uncertain']
    sync_status: Literal['sync_unobserved', 'remote_observed', 'conflict_needs_review']
    blockers: tuple[str, ...]
    next_steps: tuple[str, ...]


class BatchReport(StrictModel):
    schema_version: Literal['paper_reader_batch.report.v3']
    manifest_sha256: Sha256
    plan_refs: tuple[BoundArtifactRef, ...]
    subjects: tuple[SubjectReport, ...]


class ApproveRequest(StrictModel):
    command: Literal['approve']
    preview: BatchPreview
    selected_subject_ids: tuple[str, ...]
    confirmation_ref: str


class ApplyRequest(StrictModel):
    command: Literal['apply']
    approval_refs: tuple[BoundApprovalRef, ...]


class BatchEvent(StrictModel):
    schema_version: Literal['paper_reader_batch.event.v3']
    request_id: UuidString
    manifest_sha256: Sha256
    request_fingerprint: Sha256
    request: Annotated[ApproveRequest | ApplyRequest, Field(discriminator='command')]

    @model_validator(mode='after')
    def fingerprint_matches(self) -> Self:
        if self.request_fingerprint != canonical_sha256(self.request):
            raise ValueError('request fingerprint mismatch')
        return self


class BatchState(StrictModel):
    schema_version: Literal['paper_reader_batch.state.v3']
    manifest_sha256: Sha256
    request_id: UuidString
    request_fingerprint: Sha256
    approval_refs: tuple[BoundApprovalRef, ...]
    report: BatchReport | None


class CommandResult(StrictModel):
    schema_version: Literal['paper_reader_batch.command-result.v3']
    command: NonEmptyString
    ok: bool
    code: NonEmptyString
    data: dict[str, JsonValue] | None
