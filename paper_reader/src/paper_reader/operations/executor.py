"""The sole owner of approved note sends; durable intent always precedes HTTP."""
import json
from uuid import uuid4

from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.models import CredentialProvider, ItemCreate, ZoteroGateway
from paper_reader.operations.contracts import Approval, ChangePlan, WorkflowError
from paper_reader.operations.execution_state import can_send, history, record, report, validate_approval, validate_plan
from paper_reader.operations.reconcile import reconcile_note
from paper_reader.operations.store import RunStore
from paper_reader.zotero_live import _parse_headings


def _fresh(plan, binding, gateway):
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'plan belongs to another instance/library')
    op, candidate = binding.operation, binding.candidate
    version = gateway.get_library_version()
    if gateway.get_item(op.payload.parent_key) != candidate.target.parent:
        raise WorkflowError('plan_stale', 'approved parent changed')
    children = gateway.get_children(op.payload.parent_key)
    if binding.attachment not in children:
        raise WorkflowError('plan_stale', 'selected attachment changed')
    if fingerprint_pdf(gateway.get_file_path(binding.attachment.key)) != candidate.source:
        raise WorkflowError('source_changed', 'analyzed PDF changed')
    if gateway.item_exists(op.target_key) or any(
            child.data.item_type == 'note' and _parse_headings(child.data.note)[0] == op.payload.title
            for child in children):
        raise WorkflowError('plan_stale', 'approved note key or title is occupied')
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during preflight')
    return version


def apply_plan(plan: ChangePlan, approval: Approval, *, gateway: ZoteroGateway,
               credentials: CredentialProvider, store: RunStore):
    # Admission is entirely local; even native authorization requires a valid approval.
    approval = validate_approval(plan, approval, store)
    selected_ids = approval.selected_operation_ids
    bindings = validate_plan(plan, store)
    selected = [b for b in bindings if b.operation.operation_id in selected_ids]
    for binding in selected:
        history(plan, binding.operation.operation_id, store)
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'plan belongs to another instance/library')
    with store.library_lock(plan.context):
        for binding in selected:
            op = binding.operation
            events = history(plan, op.operation_id, store)
            store.bind_operation(plan, op.operation_id)
            if not can_send(events):
                reconcile_note(plan, binding, gateway=gateway, store=store)
                continue
            _fresh(plan, binding, gateway)
            attempt_approval = approval
            if not events or events[-1].state == 'blocked':
                record(plan, op.operation_id, approval, store, state='approved', attempt_id=uuid4().hex)
            else:
                # Continue the already approved attempt; re-approval cannot change its identity.
                attempt_approval = store.load(events[-1].approval)
            try:
                key = credentials.get_key(plan.context)
            except WorkflowError as exc:
                record(plan, op.operation_id, attempt_approval, store, state='blocked', error_code=exc.code)
                break  # no additional dialogs for this apply call
            # The native dialog can stay open while the user edits the library.
            for ref in plan.inputs:
                store.read_bytes(ref)
            version = _fresh(plan, binding, gateway)
            started = record(plan, op.operation_id, attempt_approval, store, state='started')
            try:
                results = gateway.create_items((ItemCreate(key=op.target_key, parent_key=op.payload.parent_key,
                    html=op.payload.html, tags=op.payload.tags),), library_version=version,
                    credentials=key, write_token=started.attempt_id)
            except Exception:
                # Once started is durable, no exception can authorize another send.
                record(plan, op.operation_id, attempt_approval, store, state='uncertain', error_code='write_uncertain')
                continue
            finally:
                del key
            if len(results) != 1 or results[0].key != op.target_key or results[0].state == 'unknown':
                record(plan, op.operation_id, attempt_approval, store, state='uncertain', error_code='write_uncertain')
                continue
            result, = results
            if result.state == 'failed':
                record(plan, op.operation_id, attempt_approval, store, state='blocked', error_code=result.error_code)
                if result.error_code in ('auth_required', 'auth_denied'):
                    credentials.invalidate(plan.context)
                if result.error_code in ('auth_required', 'auth_denied', 'rate_limited'):
                    break
                continue
            try:
                reconcile_note(plan, binding, gateway=gateway, store=store)
            except WorkflowError as exc:
                record(plan, op.operation_id, attempt_approval, store, state='uncertain',
                       stage='readback', error_code=exc.code)
        result = report(plan, store, selected=selected_ids)
        store.publish(result)
        return result


def retry_operation(plan: ChangePlan, *, operation_id: str, acknowledge_no_match: bool,
                    confirmation_ref: str, gateway: ZoteroGateway, store: RunStore):
    if acknowledge_no_match is not True or not isinstance(confirmation_ref, str) or not confirmation_ref.strip():
        raise WorkflowError('approval_mismatch', 'retry requires explicit no-match acknowledgement and confirmation')
    bindings = validate_plan(plan, store)
    binding = next((b for b in bindings if b.operation.operation_id == operation_id), None)
    if binding is None:
        raise WorkflowError('approval_mismatch', 'retry names an unknown operation')
    events = history(plan, operation_id, store)
    if not events or any(e.state == 'verified' for e in events):
        raise WorkflowError('approval_mismatch', 'operation has no retryable attempt')
    with store.library_lock(plan.context):
        store.bind_operation(plan, operation_id)
        events = history(plan, operation_id, store)
        if events[-1].state not in ('uncertain', 'started') or any(e.state == 'verified' for e in events):
            raise WorkflowError('approval_mismatch', 'operation is not awaiting no-match retry')
        reconcile_note(plan, binding, gateway=gateway, store=store)
        last = history(plan, operation_id, store)[-1]
        if (last.state != 'uncertain' or last.readback is None
                or json.loads(store.read_bytes(last.readback)).get('matches') != []):
            raise WorkflowError('approval_mismatch', 'latest reconciliation is not a no-match result')
        _fresh(plan, binding, gateway)
        approval = store.load(last.approval)
        if (confirmation_ref == approval.confirmation_ref
                or any(e.confirmation_ref == confirmation_ref for e in events)):
            raise WorkflowError('approval_mismatch', 'retry requires a new confirmation reference')
        record(plan, operation_id, approval, store, state='approved', attempt_id=uuid4().hex,
               readback=last.readback, confirmation_ref=confirmation_ref)
        result = report(plan, store)
        store.publish(result)
        return result


def plan_status(plan: ChangePlan, *, store: RunStore):
    validate_plan(plan, store)
    return report(plan, store)
