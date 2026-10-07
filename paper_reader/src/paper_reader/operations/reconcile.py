"""Read-only result discovery; only full note validation can verify a write."""
from paper_reader.note import REQUIRED_SECTIONS, FORBIDDEN_RENDERED_HEADINGS
from paper_reader.contracts import VerificationCheck
from paper_reader.note_hash import note_html_sha256
from paper_reader.official.models import ZoteroGateway
from paper_reader.operations.contracts import Approval, ChangePlan, WorkflowError
from paper_reader.operations.execution_state import NoteBinding, history, needs_reconciliation, record, report, validate_plan
from paper_reader.operations.store import RunStore
from paper_reader.storage import canonical_json_bytes
from paper_reader.zotero_live import _parse_headings
from paper_reader.zotero_note_validation import evaluate_note_content


def observe_note(binding: NoteBinding, *, gateway: ZoteroGateway):
    """Complete readback without journal mutation, reusable for independent peers."""
    op, candidate = binding.operation, binding.candidate
    context = gateway.context
    version = gateway.get_library_version()
    children = gateway.get_children(op.payload.parent_key)
    matches = [child for child in children if child.data.item_type == 'note' and (
        child.key == op.target_key or _parse_headings(child.data.note)[0] == op.payload.title
        or note_html_sha256(child.data.note) == op.payload.content_sha256)]
    # Include a preallocated key moved to a different parent or to the trash.
    if not any(child.key == op.target_key for child in matches) and gateway.item_exists(op.target_key):
        matches.append(gateway.get_item(op.target_key))
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during reconciliation')
    if gateway.context != context:
        raise WorkflowError('instance_changed', 'instance changed during reconciliation')
    checks = ()
    if len(matches) == 1:
        checked = evaluate_note_content(matches[0].raw_json, note_key=op.target_key,
            parent_key=op.payload.parent_key, title=op.payload.title, tags=op.payload.tags,
            required_headings=tuple(REQUIRED_SECTIONS), forbidden_headings=tuple(FORBIDDEN_RENDERED_HEADINGS),
            minimum_content_length=candidate.content_length, content_length=candidate.content_length,
            content_sha256=op.payload.content_sha256)
        deleted = bool(matches[0].raw_json['data'].get('deleted', False))
        checks = (*checked.checks, VerificationCheck(name='not_deleted', passed=not deleted,
            expected=False, actual=deleted, message='readback note is in the trash' if deleted else None))
    proof = {
        'matches': [item.model_dump(mode='json') for item in matches],
        'checks': [check.model_dump(mode='json') for check in checks],
        'library_version': version}
    if checks and all(check.passed for check in checks):
        state, code = 'verified', None
    elif not matches:
        state, code = 'uncertain', 'write_uncertain'
    else:
        state, code = 'blocked', 'duplicate_ambiguous' if len(matches) > 1 else 'verification_failed'
    return proof, state, code


def reconcile_note(plan: ChangePlan, binding: NoteBinding, *, gateway: ZoteroGateway, store: RunStore):
    op = binding.operation
    events = history(plan, op.operation_id, store)
    if not needs_reconciliation(events):
        return
    approval = store.load(events[-1].approval)
    assert isinstance(approval, Approval)  # history has checked the persisted type.
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'plan belongs to another instance/library')
    proof, state, code = observe_note(binding, gateway=gateway)
    if not proof['matches'] and any(e.state == 'verified' for e in events):
        state, code = 'blocked', 'verification_failed'
    readback = store.publish_bytes(canonical_json_bytes(proof), role='readback')
    if (events[-1].state, events[-1].error_code, events[-1].readback) != (state, code, readback):
        record(plan, op.operation_id, approval, store, state=state, stage='readback', readback=readback, error_code=code)


def reconcile_plan(plan: ChangePlan, *, gateway: ZoteroGateway, store: RunStore):
    bindings = validate_plan(plan, store)
    for binding in bindings:
        history(plan, binding.operation.operation_id, store)
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'plan belongs to another instance/library')
    with store.library_lock(plan.context):
        for binding in bindings:
            if history(plan, binding.operation.operation_id, store):
                store.bind_operation(plan, binding.operation.operation_id)
                reconcile_operation(plan, binding, gateway=gateway, store=store)
        result = report(plan, store)
        store.publish(result)
        return result


def reconcile_operation(plan, binding, *, gateway, store):
    if isinstance(binding, NoteBinding):
        return reconcile_note(plan, binding, gateway=gateway, store=store)
    from paper_reader.ingest.execution import observe_import
    op = binding.operation
    events = history(plan, op.operation_id, store)
    if not needs_reconciliation(events):
        return
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'plan belongs to another instance')
    proof, state, code = observe_import(plan, op, gateway, store)
    readback = store.publish_bytes(canonical_json_bytes(proof), role='readback')
    if (events[-1].state, events[-1].error_code, events[-1].readback) != (state, code, readback):
        record(plan, op.operation_id, store.load(events[-1].approval), store,
               state=state, stage='readback', readback=readback, error_code=code)
