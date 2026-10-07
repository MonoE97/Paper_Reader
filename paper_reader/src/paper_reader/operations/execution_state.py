"""Immutable execution bindings, journal transitions, and report projection."""
from dataclasses import dataclass
import json

from paper_reader.analysis.contracts import NoteCandidate
from paper_reader.contracts import ArtifactRef
from paper_reader.official.models import ItemSnapshot
from paper_reader.operations.contracts import (
    Approval, ChangePlan, CreateNote, ExecutionReport, ItemPrecondition,
    ErrorCode, OperationEvent, OperationResult, OperationStage, OperationState, WorkflowError,
    AddToCollections, UploadAttachment,
)
from paper_reader.operations.planner import _load_candidate
from paper_reader.operations.preview import validate_plan_artifacts
from paper_reader.operations.store import RunStore, artifact_ref
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256, new_random_id, rfc3339_utc


@dataclass(frozen=True)
class NoteBinding:
    operation: CreateNote
    candidate: NoteCandidate
    attachment: ItemSnapshot


def validate_plan(plan: ChangePlan, store: RunStore) -> tuple[NoteBinding, ...]:
    plan = ChangePlan.model_validate_json(canonical_json_bytes(plan))
    validate_plan_artifacts(plan, store)
    if plan.import_details is not None:
        from paper_reader.ingest.execution import bind_import
        return bind_import(plan, store)
    candidates = []
    for ref in plan.inputs:
        if ref.role == 'candidate':
            candidate = store.load(ref)
            if not isinstance(candidate, NoteCandidate):
                raise WorkflowError('verification_failed', 'plan candidate type mismatch')
            _, attachment = _load_candidate(candidate, store)
            candidates.append((candidate, attachment))
    bindings = []
    for op in plan.operations:
        if not isinstance(op, CreateNote) or not isinstance(op.before, ItemPrecondition):
            raise WorkflowError('approval_mismatch', 'T5 only executes notes on existing parents')
        matches = [(c, a) for c, a in candidates if c.run_id == op.subject_id and c.note_title == op.payload.title]
        if len(matches) != 1:
            raise WorkflowError('verification_failed', 'operation must bind exactly one sealed candidate')
        candidate, attachment = matches[0]
        target = candidate.target
        if (target is None or target.context != plan.context or candidate.run_id != plan.run_id
                or op.payload.parent_key != target.item_key or op.before.key != target.item_key
                or op.before.version != target.parent.version or op.before.snapshot != target.parent_snapshot
                or op.payload.tags != candidate.tags or op.payload.content_sha256 != candidate.content_sha256
                or op.payload.html.encode() != store.read_bytes(candidate.note_html)
                or candidate.note_html not in plan.content or candidate.note_markdown not in plan.content
                or any(ref not in plan.inputs for ref in candidate.artifacts)):
            raise WorkflowError('verification_failed', 'operation differs from sealed analysis')
        bindings.append(NoteBinding(op, candidate, attachment))
    return tuple(bindings)


def validate_approval(plan: ChangePlan, approval: Approval, store: RunStore) -> Approval:
    if not isinstance(approval, Approval):
        raise WorkflowError('approval_mismatch', 'an explicit immutable approval is required')
    approval = Approval.model_validate_json(canonical_json_bytes(approval))
    if approval.plan != artifact_ref(plan) or approval.run_id != plan.run_id:
        raise WorkflowError('approval_mismatch', 'approval belongs to another plan')
    selected = set(approval.selected_operation_ids)
    operations = {op.operation_id: op for op in plan.operations}
    if selected - operations.keys():
        raise WorkflowError('approval_mismatch', 'unknown selected operation')
    for operation_id in selected:
        op = operations[operation_id]
        if set(op.depends_on) - selected:
            raise WorkflowError('dependency_excluded', 'approval excludes a dependency')
        if op.blockers:
            raise WorkflowError('approval_mismatch', 'selected operation has blockers')
    if store.load(artifact_ref(approval)) != approval:
        raise WorkflowError('approval_mismatch', 'approval has not been persisted')
    return approval


def attempt_started(events: tuple[OperationEvent, ...]) -> bool:
    return bool(events) and any(e.state == 'started' and e.attempt_id == events[-1].attempt_id for e in events)


def can_send(events: tuple[OperationEvent, ...]) -> bool:
    """A new explicit apply may resume only an approved or definitely unsent attempt."""
    if not events:
        return True
    if any(e.state == 'verified' for e in events):
        return False
    last = events[-1]
    return last.state == 'approved' or (last.state == 'blocked' and last.stage != 'readback' and (
        not attempt_started(events) or last.error_code in ('auth_denied', 'auth_required', 'rate_limited')))


def needs_reconciliation(events: tuple[OperationEvent, ...]) -> bool:
    if not attempt_started(events):
        return False
    last = events[-1]
    expired_permit = last.stage in ('upload_transfer', 'upload_register') and last.error_code == 'attachment_unavailable'
    return last.state != 'blocked' or last.stage == 'readback' or expired_permit


def operation_stages(operation):
    if isinstance(operation, UploadAttachment):
        return ('upload_authorize', 'upload_transfer', 'upload_register')
    return ('patch',) if isinstance(operation, AddToCollections) else ('create',)


def upload_can_resume(events, store):
    """A lost transient permit is replaceable only before uncertain registration."""
    if not events or events[-1].state != 'uncertain' or events[-1].readback is None:
        return False
    attempt = [e for e in events if e.attempt_id == events[-1].attempt_id]
    registration = [e for e in attempt if e.stage == 'upload_register']
    if registration and not (registration[-1].state == 'blocked'
                             and registration[-1].error_code == 'attachment_unavailable'):
        return False
    proof = json.loads(store.read_bytes(events[-1].readback))
    return proof.get('file_absent') is True and proof.get('matches') == []


def _validate_events(plan: ChangePlan, operation_id: str, events: tuple[OperationEvent, ...], store: RunStore) -> None:
    """One transition rule set, shared by pre-publication checks and replay."""
    attempts = set()
    operation = next(o for o in plan.operations if o.operation_id == operation_id)
    stages = operation_stages(operation)
    for index, event in enumerate(events):
        approval = store.load(event.approval)
        if not isinstance(approval, Approval):
            raise WorkflowError('journal_corrupt', 'event is not bound to an approval')
        validate_approval(plan, approval, store)
        if operation_id not in approval.selected_operation_ids:
            raise WorkflowError('journal_corrupt', 'event operation was not selected')
        previous = events[index - 1] if index else None
        if event.state == 'approved':
            if event.attempt_id in attempts or event.stage != stages[0]:
                raise WorkflowError('journal_corrupt', 'attempt approval was reused')
            if previous is not None:
                prefix = events[:index]
                definitely_failed = previous.state == 'blocked' and can_send(prefix)
                explicit_retry = (
                    previous.state == 'uncertain' and previous.stage == 'readback'
                    and event.approval == previous.approval and event.readback is not None
                    and event.readback == previous.readback and event.confirmation_ref is not None
                    and event.confirmation_ref != approval.confirmation_ref
                    and event.confirmation_ref not in {e.confirmation_ref for e in prefix})
                if explicit_retry:
                    proof = json.loads(store.read_bytes(event.readback))
                    explicit_retry = isinstance(proof, dict) and proof.get('matches') == []
                transient_resume = (isinstance(operation, UploadAttachment) and upload_can_resume(prefix, store)
                    and event.approval == previous.approval and event.readback == previous.readback)
                if any(e.state == 'verified' for e in prefix) or not (definitely_failed or explicit_retry or transient_resume):
                    raise WorkflowError('journal_corrupt', 'retry is not authorized')
            attempts.add(event.attempt_id)
        elif previous is None or event.attempt_id != previous.attempt_id or event.approval != previous.approval:
            raise WorkflowError('journal_corrupt', 'event is detached from its attempt')
        elif event.state == 'started':
            sent = [e.stage for e in events[:index] if e.attempt_id == event.attempt_id and e.state == 'started']
            if (previous.state not in ('approved', 'started') or len(sent) >= len(stages)
                    or tuple(sent) != stages[:len(sent)] or event.stage != stages[len(sent)]):
                raise WorkflowError('journal_corrupt', 'attempt cannot be sent again')
        elif event.state in ('verified', 'uncertain'):
                if not attempt_started(events[:index]):
                    raise WorkflowError('journal_corrupt', 'readback without a started attempt')
        elif event.state != 'blocked':
            raise WorkflowError('journal_corrupt', 'invalid execution state')
        if event.state == 'verified' and (event.stage != 'readback' or event.readback is None):
            raise WorkflowError('journal_corrupt', 'verified event requires readback')
        if event.readback is not None:
            store.read_bytes(event.readback)


def history(plan: ChangePlan, operation_id: str, store: RunStore) -> tuple[OperationEvent, ...]:
    events = store.events(operation_id)
    _validate_events(plan, operation_id, events, store)
    return events


def record(plan: ChangePlan, operation_id: str, approval: Approval, store: RunStore, *, state: OperationState,
           stage: OperationStage = 'create', attempt_id: str | None = None, readback: ArtifactRef | None = None,
           error_code: ErrorCode | None = None, confirmation_ref: str | None = None) -> OperationEvent:
    events = history(plan, operation_id, store)
    head = canonical_json_sha256(events[-1]) if events else None
    event = OperationEvent(schema_version='paper_reader.zotero-event.v3', operation_id=operation_id,
        stage=stage, seq=len(events) + 1, previous_digest=head, state=state,
        attempt_id=attempt_id or events[-1].attempt_id, request_id=new_random_id('request'),
        created_at=rfc3339_utc(), approval=artifact_ref(approval), confirmation_ref=confirmation_ref,
        readback=readback, error_code=error_code)
    _validate_events(plan, operation_id, (*events, event), store)
    store.append_event(event, expected_head=head)
    return event


def report(plan: ChangePlan, store: RunStore, *, selected: tuple[str, ...] | None = None) -> ExecutionReport:
    results = []
    for op in plan.operations:
        if selected is not None and op.operation_id not in selected:
            continue
        events = history(plan, op.operation_id, store)
        last = events[-1] if events else None
        state = last.state if last else 'planned'
        if state == 'started':
            state = 'uncertain'
        code = last.error_code if last else None
        if state == 'uncertain':
            code = code or 'write_uncertain'
        results.append(OperationResult(operation_id=op.operation_id, state=state,
            target_key=op.target_key, readback=last.readback if last else None,
            blockers=(code,) if code else op.blockers,
            next_steps=('只读核对；零匹配后需显式确认重试。',) if state == 'uncertain' else ()))
    verified = bool(results) and all(r.state == 'verified' for r in results)
    conflict = any('verification_failed' in r.blockers or 'duplicate_ambiguous' in r.blockers for r in results)
    return ExecutionReport(schema_version='paper_reader.zotero-result.v3', run_id=plan.run_id,
        plan=artifact_ref(plan), context=plan.context, created_at=rfc3339_utc(), operations=tuple(results),
        local_status='local_verified' if verified else 'conflict_needs_review' if conflict else 'incomplete',
        sync_status='sync_unobserved', remote_observation=None)
