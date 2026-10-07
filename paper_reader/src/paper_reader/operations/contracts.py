from __future__ import annotations

import json
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Annotated, Literal, Self, TypeAlias, get_args

from pydantic import Field, TypeAdapter, model_validator

from paper_reader.analysis.contracts import (
    NoteCandidate, PaperMetadata, PdfSource, PreparedPaper, Review, ReviewPackage, Summary,
)
from paper_reader.contracts import (
    ArtifactRef, NonNegativeInt, PortableIdentifier, PositiveInt, Rfc3339Utc, Sha256, StrictContractModel,
)
from paper_reader.ingest.contracts import IdentificationProposal, ImportDetails, ImportItemType
from paper_reader.official.models import ItemKey, JsonObject, LibraryContext, Text

ArtifactRole: TypeAlias = Literal["source", "evidence", "review", "note", "preview", "readback"]
ErrorCode: TypeAlias = Literal[
    "unsupported_artifact_schema", "instance_changed", "plan_stale", "approval_mismatch",
    "dependency_excluded", "metadata_unresolved", "duplicate_ambiguous", "source_changed",
    "attachment_unavailable", "auth_denied", "auth_required", "rate_limited", "write_uncertain",
    "verification_failed", "journal_corrupt", "resource_limit",
]


class WorkflowError(ValueError):
    def __init__(self, code: ErrorCode, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


class BoundArtifactRef(StrictContractModel):
    run_root: Path
    run_id: PortableIdentifier
    artifact: ArtifactRef

    @model_validator(mode="after")
    def require_absolute_root(self) -> Self:
        if not self.run_root.is_absolute():
            raise ValueError("run_root must be absolute")
        return self


class ItemPrecondition(StrictContractModel):
    kind: Literal["existing"]
    key: ItemKey
    version: NonNegativeInt
    snapshot: ArtifactRef


class PredecessorPrecondition(StrictContractModel):
    kind: Literal["predecessor"]
    operation_id: PortableIdentifier


OperationPrecondition: TypeAlias = Annotated[
    ItemPrecondition | PredecessorPrecondition, Field(discriminator="kind"),
]


class ParentPayload(StrictContractModel):
    item_type: ImportItemType
    metadata: PaperMetadata
    collections: tuple[ItemKey, ...]


class CollectionsPayload(StrictContractModel):
    collections: tuple[ItemKey, ...]


class AttachmentPayload(StrictContractModel):
    parent_key: ItemKey
    title: Text
    filename: Text
    source: PdfSource
    content_type: Literal["application/pdf"]
    link_mode: Literal["imported_file"]


class UploadPayload(StrictContractModel):
    source: PdfSource
    filename: Text


class NotePayload(StrictContractModel):
    parent_key: ItemKey
    title: Text
    html: Text
    tags: tuple[str, ...]
    content_sha256: Sha256


class OperationFields(StrictContractModel):
    operation_id: PortableIdentifier
    subject_id: PortableIdentifier
    subject_title: Text
    depends_on: tuple[PortableIdentifier, ...]
    target_key: ItemKey
    before: OperationPrecondition | None
    reason: Text
    blockers: tuple[Text, ...]

    @model_validator(mode="after")
    def require_predecessor_dependency(self) -> Self:
        if not self.reason.strip() or not self.subject_title.strip():
            raise ValueError("subject title and reason must contain text")
        if isinstance(self.before, PredecessorPrecondition) and self.before.operation_id not in self.depends_on:
            raise ValueError("predecessor precondition must name an explicit dependency")
        return self


class CreateParent(OperationFields):
    type: Literal["create_parent"]
    payload: ParentPayload


class AddToCollections(OperationFields):
    type: Literal["add_to_collections"]
    before: OperationPrecondition
    payload: CollectionsPayload


class CreateAttachment(OperationFields):
    type: Literal["create_attachment"]
    payload: AttachmentPayload


class UploadAttachment(OperationFields):
    type: Literal["upload_attachment"]
    before: OperationPrecondition
    payload: UploadPayload


class CreateNote(OperationFields):
    type: Literal["create_note"]
    payload: NotePayload


ChangeOperation: TypeAlias = Annotated[
    CreateParent | AddToCollections | CreateAttachment | UploadAttachment | CreateNote,
    Field(discriminator="type"),
]


class ChangePlan(StrictContractModel):
    schema_version: Literal["paper_reader.zotero-plan.v3"]
    plan_id: PortableIdentifier
    run_id: PortableIdentifier
    context: LibraryContext
    created_at: Rfc3339Utc
    library_version: NonNegativeInt
    operations: tuple[ChangeOperation, ...]
    inputs: tuple[ArtifactRef, ...]
    content: tuple[ArtifactRef, ...]
    import_details: ImportDetails | None = None
    # The plan's own digest belongs to its ArtifactRef/Approval, avoiding self-hashing.

    @model_validator(mode="after")
    def require_operation_graph(self) -> Self:
        ids = {op.operation_id for op in self.operations}
        if (not ids and self.import_details is None) or len(ids) != len(self.operations):
            raise ValueError("plan requires unique operations")
        if self.import_details is not None:
            detail = self.import_details
            if bool(self.operations) != (detail.status == 'ready') or bool(detail.blockers) != (detail.status == 'blocked'):
                raise ValueError("only ready imports may contain operations")
            if any(ref not in self.inputs for ref in (detail.proposal, detail.collection_snapshot,
                    detail.inventory_snapshot, detail.attachment_snapshot)):
                raise ValueError("import details must bind their evidence in plan inputs")
        if any(set(op.depends_on) - ids or len(set(op.depends_on)) != len(op.depends_on)
               for op in self.operations):
            raise ValueError("dependencies must name unique plan operations")
        try:
            tuple(TopologicalSorter({op.operation_id: op.depends_on for op in self.operations}).static_order())
        except CycleError as exc:
            raise ValueError("operation dependency cycle") from exc
        by_id = {op.operation_id: op for op in self.operations}
        creates = [op for op in self.operations if isinstance(op, (CreateParent, CreateAttachment, CreateNote))]
        creators = {op.target_key: op for op in creates}
        if len(creators) != len(creates):
            raise ValueError("create operations must have distinct target keys")
        for op in self.operations:
            parent_key = op.payload.parent_key if isinstance(op, (CreateNote, CreateAttachment)) else None
            before_key = parent_key or op.target_key
            if isinstance(op.before, ItemPrecondition):
                if op.before.key != before_key or op.before.snapshot not in self.inputs:
                    raise ValueError("existing precondition must bind the target and input snapshot")
            if isinstance(op.before, PredecessorPrecondition):
                if by_id[op.before.operation_id].target_key != before_key:
                    raise ValueError("predecessor must produce the required target")
            if parent_key:
                creator = creators.get(parent_key)
                if creator is not None:
                    if not isinstance(creator, CreateParent) or creator.operation_id not in op.depends_on:
                        raise ValueError("child must depend on its parent creation")
                elif not isinstance(op.before, ItemPrecondition):
                    raise ValueError("child requires an existing parent snapshot")
        if any(ref not in self.inputs for ref in self.content):
            raise ValueError("preview content must be bound by plan inputs")
        return self


class Approval(StrictContractModel):
    schema_version: Literal["paper_reader.zotero-approval.v3"]
    approval_id: PortableIdentifier
    run_id: PortableIdentifier
    plan: ArtifactRef
    selected_operation_ids: tuple[PortableIdentifier, ...]
    confirmed_at: Rfc3339Utc
    confirmation_ref: Text

    @model_validator(mode="after")
    def require_explicit_selection(self) -> Self:
        if (not self.selected_operation_ids or len(set(self.selected_operation_ids)) != len(self.selected_operation_ids)
                or not self.confirmation_ref.strip()):
            raise ValueError("approval requires a nonempty unique selection and confirmation reference")
        return self


class PlanPreview(StrictContractModel):
    plan: ArtifactRef
    context: LibraryContext
    operations: tuple[ChangeOperation, ...]
    content: tuple[ArtifactRef, ...]
    import_details: ImportDetails | None = None


OperationStage: TypeAlias = Literal[
    "create", "patch", "upload_authorize", "upload_transfer", "upload_register", "readback",
]
OperationState: TypeAlias = Literal["planned", "approved", "started", "verified", "blocked", "uncertain"]


class OperationEvent(StrictContractModel):
    schema_version: Literal["paper_reader.zotero-event.v3"]
    operation_id: PortableIdentifier
    stage: OperationStage
    seq: PositiveInt
    previous_digest: Sha256 | None
    state: OperationState
    attempt_id: PortableIdentifier
    request_id: PortableIdentifier
    created_at: Rfc3339Utc
    approval: ArtifactRef
    confirmation_ref: Text | None = None
    readback: ArtifactRef | None
    error_code: ErrorCode | None = None


class OperationResult(StrictContractModel):
    operation_id: PortableIdentifier
    state: OperationState
    target_key: ItemKey
    readback: ArtifactRef | None
    blockers: tuple[Text, ...]
    next_steps: tuple[Text, ...]


class ExecutionReport(StrictContractModel):
    schema_version: Literal["paper_reader.zotero-result.v3"]
    run_id: PortableIdentifier
    plan: ArtifactRef
    context: LibraryContext
    created_at: Rfc3339Utc
    operations: tuple[OperationResult, ...]
    local_status: Literal["local_verified", "incomplete", "conflict_needs_review"]
    sync_status: Literal["sync_unobserved", "remote_observed", "conflict_needs_review"]
    remote_observation: ArtifactRef | None

    @model_validator(mode="after")
    def require_observation(self) -> Self:
        if self.sync_status == "remote_observed" and self.remote_observation is None:
            raise ValueError("remote_observed requires independent evidence")
        return self


class DuplicateMatch(StrictContractModel):
    item_keys: tuple[ItemKey, ...]
    relationship: Literal["identical_pdf", "compatible_identifier", "possible_duplicate", "none", "conflict"]
    evidence: tuple[ArtifactRef, ...]
    reasons: tuple[Text, ...]
    conflicting_fields: tuple[Text, ...]


class DuplicateReport(StrictContractModel):
    schema_version: Literal["paper_reader.duplicate-report.v3"]
    report_id: PortableIdentifier
    context: LibraryContext
    created_at: Rfc3339Utc
    matches: tuple[DuplicateMatch, ...]
    scope: Literal["local_instance"]


class CommandResult(StrictContractModel):
    schema_version: Literal["paper_reader.command-result.v3"]
    command: Text
    ok: bool
    code: Literal["ok"] | ErrorCode
    created_at: Rfc3339Utc
    artifacts: tuple[ArtifactRef, ...]
    data: JsonObject | None = None


ContractArtifact: TypeAlias = Annotated[
    PreparedPaper | Summary | Review | ReviewPackage | NoteCandidate | IdentificationProposal
    | ChangePlan | Approval | OperationEvent | ExecutionReport | CommandResult,
    Field(discriminator="schema_version"),
]
ARTIFACT_ADAPTER = TypeAdapter(ContractArtifact)
V3_SCHEMA_MODELS = {
    get_args(model.model_fields["schema_version"].annotation)[0]: model
    for model in get_args(get_args(ContractArtifact)[0])
}


def parse_artifact(content: bytes) -> ContractArtifact:
    """Reject unsupported versions before any store mutation or locking."""
    try:
        value = json.loads(content)
    except (ValueError, UnicodeError) as exc:
        raise WorkflowError("unsupported_artifact_schema", "expected a versioned JSON artifact") from exc
    version = value.get("schema_version") if isinstance(value, dict) else None
    if not isinstance(version, str) or version not in V3_SCHEMA_MODELS:
        raise WorkflowError("unsupported_artifact_schema", "expected a registered v3 schema")
    # JSON mode preserves strict scalar types while decoding tuples/Paths naturally.
    return ARTIFACT_ADAPTER.validate_json(content)
