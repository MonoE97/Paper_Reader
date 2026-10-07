import json

import pytest
from test_import_execution import imported, apply, restart
from paper_reader.operations.contracts import WorkflowError


def test_created_attachment_then_no_upload_recovers_without_recreation(imported):
    w = imported()
    w.transport.faults['upload_authorize'] = 401
    result = apply(w)
    assert [r.state for r in result.operations] == ['verified', 'verified', 'blocked']
    assert w.credentials.invalidated == 1
    restart(w)
    assert apply(w).local_status == 'local_verified'
    assert sum(c[0] == 'create' for c in w.transport.calls) == 2


@pytest.mark.parametrize('fault', ['before', 'after', 404])
def test_interrupted_or_expired_transfer_reacquires_permit_after_readback(imported, fault):
    w = imported()
    w.transport.faults['upload_transfer'] = fault
    first = apply(w)
    assert first.local_status == 'incomplete'
    assert not w.transport.files
    restart(w)
    assert apply(w).local_status == 'local_verified'
    assert [c[0] for c in w.transport.calls].count('create') == 2
    assert [c[0] for c in w.transport.calls].count('upload_authorize') == 2
    assert [c[0] for c in w.transport.calls].count('upload_register') == 1


def test_registration_succeeded_but_response_lost_reconciles_without_resend(imported):
    w = imported()
    w.transport.faults['upload_register'] = 'after'
    first = apply(w)
    assert first.local_status == 'incomplete'
    sent = len(w.transport.calls)
    restart(w)
    assert apply(w).local_status == 'local_verified'
    assert len(w.transport.calls) == sent
    artifacts = b'\n'.join(p.read_bytes() for p in w.store.root.rglob('*.json'))
    assert b'temporary0' not in artifacts and b'SECRET-MUST-NOT-LEAK' not in artifacts


def test_registration_zero_match_requires_explicit_retry(imported):
    w = imported()
    w.transport.faults['upload_register'] = 'before'
    assert apply(w).local_status == 'incomplete'
    sent = len(w.transport.calls)
    restart(w)
    assert apply(w).operations[-1].state == 'uncertain'
    assert len(w.transport.calls) == sent
    op = w.plan.operations[-1]
    w.api.retry_operation(w.plan, operation_id=op.operation_id, acknowledge_no_match=True,
        confirmation_ref='explicit-new-retry', gateway=w.live, store=w.store)
    assert len(w.transport.calls) == sent
    assert apply(w).local_status == 'local_verified'
    assert sum(c[0] == 'create' for c in w.transport.calls) == 2


def test_source_replaced_after_transfer_never_registers(imported):
    w = imported()
    def replace(stage, key):
        if stage == 'upload_transfer':
            alternative = w.path.with_suffix('.replacement')
            alternative.write_bytes(w.path.read_bytes())
            alternative.replace(w.path)
    w.transport.hook = replace
    try:
        result = apply(w)
    except WorkflowError as exc:
        assert exc.code == 'source_changed'
    else:
        assert result.local_status != 'local_verified'
    assert 'upload_register' not in [c[0] for c in w.transport.calls]


def test_recovery_file_mismatch_blocks_and_does_not_upload_again(imported):
    w = imported()
    w.transport.faults['upload_register'] = 'after'
    apply(w)
    key = w.plan.operations[-1].target_key
    w.transport.files[key].write_bytes(b'wrong file')
    sent = len(w.transport.calls)
    restart(w)
    result = w.api.reconcile_plan(w.plan, gateway=w.live, store=w.store)
    assert result.operations[-1].state == 'blocked'
    assert len(w.transport.calls) == sent


def test_lost_parent_response_recovers_before_sending_dependent_attachment(imported):
    w = imported()
    w.transport.faults['create'] = 'after'
    first = apply(w)
    assert first.local_status == 'incomplete'
    assert [c[0] for c in w.transport.calls] == ['create']
    restart(w)
    assert apply(w).local_status == 'local_verified'
    assert sum(c[0] == 'create' for c in w.transport.calls) == 2


def test_expired_registration_handle_recovers_without_recreating_attachment(imported):
    w = imported()
    w.transport.faults['upload_register'] = 404
    apply(w)
    restart(w)
    assert apply(w).local_status == 'local_verified'
    assert sum(c[0] == 'create' for c in w.transport.calls) == 2


def test_registration_missing_local_file_but_registered_metadata_stays_uncertain(imported):
    w = imported()
    w.transport.faults['upload_register'] = 'after'
    apply(w)
    key = w.plan.operations[-1].target_key
    w.transport.files.pop(key)
    result = w.api.reconcile_plan(w.plan, gateway=w.live, store=w.store)
    assert result.operations[-1].state == 'uncertain'
    assert 'attachment_unavailable' in result.operations[-1].blockers


def test_target_attachment_changed_before_reacquiring_handle_blocks(imported):
    w = imported()
    w.transport.faults['upload_transfer'] = 'before'
    apply(w)
    key = w.plan.operations[-1].target_key
    w.transport.save(key, {**w.transport.items[key]['data'], 'filename': 'user-edited.pdf'})
    sent = len(w.transport.calls)
    result = apply(w)
    assert result.operations[-1].state == 'blocked'
    assert len(w.transport.calls) == sent
