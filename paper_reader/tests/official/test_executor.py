import pytest

from paper_reader import services
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.store import FileRunStore


def apply(w, approval=None):
    assert hasattr(services, 'apply_plan'), 'T5 executor missing'
    return services.apply_plan(w.plan, approval or w.approval, gateway=w.gateway,
                              credentials=w.credentials, store=w.store)


@pytest.mark.parametrize('invalid', ['none', 'digest', 'selection', 'unsaved'])
def test_invalid_approval_causes_zero_gateway_or_credential_requests(approved_note, invalid):
    w = approved_note
    assert hasattr(services, 'apply_plan'), 'T5 executor missing'
    approval = w.approval
    if invalid == 'none':
        approval = None
    elif invalid == 'digest':
        approval = approval.model_copy(update={'plan': approval.plan.model_copy(update={'sha256': 'a' * 64})})
    elif invalid == 'selection':
        approval = approval.model_copy(update={'selected_operation_ids': ('unknown',)})
    else:
        approval = approval.model_copy(update={'confirmation_ref': 'not-published'})
    with pytest.raises((WorkflowError, ValueError)):
        services.apply_plan(w.plan, approval, gateway=w.gateway, credentials=w.credentials, store=w.store)
    assert w.gateway.calls == [] and w.credentials.calls == 0 and w.gateway.sent == []
    assert not w.store.coordination_root.exists()


def test_success_replay_and_restart_send_once(approved_note):
    w = approved_note
    first = apply(w)
    assert first.local_status == 'local_verified' and first.sync_status == 'sync_unobserved'
    result, = first.operations
    assert result.state == 'verified' and result.readback
    assert w.store.read_bytes(result.readback)
    assert [e.state for e in w.store.events(w.gateway.operation_id)] == ['approved', 'started', 'verified']
    w.store = FileRunStore(w.store.root, coordination_root=w.store.coordination_root)
    w.gateway.store = w.store
    assert apply(w).local_status == 'local_verified'
    assert len(w.gateway.sent) == 1 and w.credentials.calls == 1


@pytest.mark.parametrize('change,code', [('instance', 'instance_changed'), ('parent', 'plan_stale'),
    ('occupied', 'plan_stale'), ('pdf', 'source_changed')])
def test_stale_preconditions_never_send(approved_note, change, code, tmp_path):
    w = approved_note
    if change == 'instance':
        w.gateway.context = w.gateway.context.model_copy(update={'server_id': 'replacement'})
    elif change == 'parent':
        w.gateway.parent = w.gateway.parent.model_copy(update={'version': 8})
    elif change == 'occupied':
        w.gateway.item_exists = lambda _: True
    else:
        w.gateway.pdf_path = tmp_path / 'other.pdf'
        w.gateway.pdf_path.write_bytes(b'other')
    with pytest.raises(WorkflowError, match=code):
        apply(w)
    assert not w.gateway.sent


@pytest.mark.parametrize('code', ['auth_denied', 'rate_limited', 'auth_required'])
def test_native_denial_does_not_publish_started(approved_note, code):
    w = approved_note
    w.credentials.code = code
    report = apply(w)
    assert report.local_status == 'incomplete'
    assert not w.gateway.sent
    assert all(e.state != 'started' for e in w.store.events(w.gateway.operation_id))


@pytest.mark.parametrize('mode', ['wrong_tags', 'wrong_parent'])
def test_success_response_requires_complete_readback(approved_note, mode):
    w = approved_note
    w.gateway.mode = mode
    report = apply(w)
    assert report.local_status != 'local_verified'
    assert report.operations[0].state == 'blocked'
    assert 'verification_failed' in report.operations[0].blockers
    assert len(w.gateway.sent) == 1
    assert apply(w).local_status != 'local_verified'
    assert len(w.gateway.sent) == 1


@pytest.mark.parametrize('mode', ['auth_required', 'rate_limited', 'plan_stale'])
def test_definite_http_failure_is_recorded_without_loop(approved_note, mode):
    w = approved_note
    w.gateway.mode = mode
    report = apply(w)
    assert report.operations[0].state == 'blocked'
    assert mode in report.operations[0].blockers
    assert len(w.gateway.sent) == 1 and w.credentials.calls == 1
    if mode == 'auth_required':
        assert w.credentials.invalidated == 1


def test_plan_tampering_cannot_bypass_sealed_candidate(approved_note):
    w = approved_note
    op = w.plan.operations[0]
    w.plan = w.plan.model_copy(update={'operations': (op.model_copy(update={
        'payload': op.payload.model_copy(update={'tags': ('not-reviewed',)})}),)})
    from paper_reader.operations.store import artifact_ref
    w.store.publish(w.plan)
    w.approval = services.approve_plan(w.plan, selected_operation_ids=(op.operation_id,),
        expected_plan_sha256=artifact_ref(w.plan).sha256, confirmation_ref='synthetic', store=w.store)
    with pytest.raises(WorkflowError):
        apply(w)
    assert not w.gateway.calls and w.credentials.calls == 0


def test_explicit_apply_can_resume_authorization_connection_failure(approved_note):
    w = approved_note
    w.credentials.code = 'attachment_unavailable'
    assert apply(w).operations[0].state == 'blocked'
    assert not any(e.state == 'started' for e in w.store.events(w.gateway.operation_id))
    w.credentials.code = None
    assert apply(w).local_status == 'local_verified'
    assert w.credentials.calls == 2 and len(w.gateway.sent) == 1
