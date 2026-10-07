"""Pure plan previews and immutable records of explicit, closed selections."""
from paper_reader.operations.contracts import Approval, ChangePlan, PlanPreview, WorkflowError
from paper_reader.operations.store import RunStore, artifact_ref
from paper_reader.storage import canonical_json_bytes, new_random_id, rfc3339_utc


def preview_plan(plan: ChangePlan) -> PlanPreview:
    plan = ChangePlan.model_validate_json(canonical_json_bytes(plan))
    return PlanPreview(plan=artifact_ref(plan), context=plan.context,
                       operations=plan.operations, content=plan.content, import_details=plan.import_details)


def validate_plan_artifacts(plan: ChangePlan, store: RunStore) -> None:
    """Shared immutable closure check, independent of executable operation types."""
    if store.load(artifact_ref(plan)) != plan:
        raise WorkflowError('approval_mismatch', 'plan differs from its stored artifact')
    for ref in plan.inputs:
        store.read_bytes(ref)


def approve_plan(plan: ChangePlan, *, selected_operation_ids: tuple[str, ...],
                 expected_plan_sha256: str, confirmation_ref: str, store: RunStore) -> Approval:
    preview = preview_plan(plan)
    if preview.plan.sha256 != expected_plan_sha256:
        raise WorkflowError('approval_mismatch', 'plan differs from the preview being confirmed')
    # Validate caller types before converting the selection to a set or touching storage.
    approval = Approval(schema_version='paper_reader.zotero-approval.v3', approval_id=new_random_id('approval'),
        run_id=plan.run_id, plan=preview.plan, selected_operation_ids=selected_operation_ids,
        confirmed_at=rfc3339_utc(), confirmation_ref=confirmation_ref)
    selected = set(approval.selected_operation_ids)
    operations = {op.operation_id: op for op in preview.operations}
    if selected - operations.keys():
        raise WorkflowError('approval_mismatch', 'selection names an unknown operation')
    for operation_id in selected:
        operation = operations[operation_id]
        if set(operation.depends_on) - selected:
            raise WorkflowError('dependency_excluded', 'selection excludes a required dependency')
        if operation.blockers:
            raise WorkflowError('approval_mismatch', 'selected operation has unresolved blockers')
    validate_plan_artifacts(plan, store)
    approval = approval.model_copy(update={'selected_operation_ids': tuple(
        op.operation_id for op in preview.operations if op.operation_id in selected)})
    store.publish(approval)
    return approval
