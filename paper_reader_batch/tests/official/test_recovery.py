from uuid import uuid4

import pytest

from paper_reader_batch.v2_errors import BatchRuntimeError
from test_batch_approval import approve


def test_lost_core_reply_recovers_from_core_without_another_apply(batch):
    refs = approve(batch)
    batch.core.lose_response = True
    request_id = str(uuid4())
    first = batch.driver.apply(refs, request_id=request_id)
    assert [s.status for s in first.subjects] == ['verified', 'skipped', 'uncertain']
    restarted = batch.api.driver.BatchDriver(client=batch.core, run_root=batch.root, manifest=batch.manifest)
    second = restarted.apply(refs, request_id=request_id)
    assert [s.status for s in second.subjects] == ['verified', 'skipped', 'uncertain']
    assert batch.core.sends == ['A', 'C']
    assert sum(a[1] == 'apply' for a in batch.core.calls) == 1


def test_core_done_before_batch_record_can_rebuild_report(batch, monkeypatch):
    refs = approve(batch)
    request_id = str(uuid4())
    original = batch.driver.store.complete
    monkeypatch.setattr(batch.driver.store, 'complete', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError, match='crash'):
        batch.driver.apply(refs, request_id=request_id)
    monkeypatch.setattr(batch.driver.store, 'complete', original)
    restarted = batch.api.driver.BatchDriver(client=batch.core, run_root=batch.root, manifest=batch.manifest)
    assert restarted.apply(refs, request_id=request_id).subjects[0].status == 'verified'
    assert batch.core.sends == ['A', 'C']


def test_apply_request_cannot_be_reused_for_other_approvals(batch):
    refs = approve(batch)
    request_id = str(uuid4())
    batch.driver.apply(refs, request_id=request_id)
    with pytest.raises(BatchRuntimeError, match='idempotency_conflict'):
        batch.driver.apply(refs[:1], request_id=request_id)
    assert batch.core.sends == ['A', 'C']


def test_lost_approval_reply_does_not_automatically_create_new_approval(batch):
    batch.core.approve_loss = True
    request_id = str(uuid4())
    with pytest.raises(BatchRuntimeError): approve(batch, request_id=request_id)
    count = sum(a[1] == 'approve' for a in batch.core.calls)
    with pytest.raises(BatchRuntimeError, match='approval_uncertain'): approve(batch, request_id=request_id)
    assert sum(a[1] == 'approve' for a in batch.core.calls) == count
