"""Wire references and admission for one process executing multiple approved plans."""
from dataclasses import dataclass
from pathlib import Path

from paper_reader import services
from paper_reader.contracts import ArtifactRef
from paper_reader.operations.contracts import Approval, BoundArtifactRef, ChangePlan, WorkflowError
from paper_reader.operations.execution_state import validate_approval
from paper_reader.operations.store import FileRunStore


class BoundApprovalRef(BoundArtifactRef):
    plan: ArtifactRef


@dataclass(frozen=True)
class AdmittedPlan:
    reference: BoundApprovalRef
    plan: ChangePlan
    approval: Approval
    store: FileRunStore


def admit_approvals(references: tuple[BoundApprovalRef, ...], coordination_root: Path) -> tuple[AdmittedPlan, ...]:
    if not references or len({(r.run_root, r.plan.sha256) for r in references}) != len(references):
        raise WorkflowError('approval_mismatch', 'explicit unique plans required')
    admitted = []
    for ref in references:
        store = FileRunStore(ref.run_root, coordination_root=coordination_root)
        plan, approval = store.load(ref.plan), store.load(ref.artifact)
        if not isinstance(plan, ChangePlan) or not isinstance(approval, Approval):
            raise WorkflowError('unsupported_artifact_schema', 'expected plan and approval')
        if plan.run_id != ref.run_id or approval.run_id != ref.run_id:
            raise WorkflowError('approval_mismatch', 'reference belongs to another run')
        validate_approval(plan, approval, store)
        services.plan_status(plan, store=store)
        admitted.append(AdmittedPlan(ref, plan, approval, store))
    return tuple(admitted)


def apply_admitted(admitted: tuple[AdmittedPlan, ...], *, credentials, live) -> dict:
    entries = []
    for item in admitted:
        code = 'ok'
        try:
            report = services.apply_plan(item.plan, item.approval, gateway=live(item.plan),
                                        credentials=credentials, store=item.store)
        except WorkflowError as exc:
            code = exc.code
            report = services.plan_status(item.plan, store=item.store)
        entries.append({'reference': item.reference.model_dump(mode='json'), 'code': code,
                        'selected_operation_ids': list(item.approval.selected_operation_ids),
                        'report': report.model_dump(mode='json')})
    return {'entries': entries}
