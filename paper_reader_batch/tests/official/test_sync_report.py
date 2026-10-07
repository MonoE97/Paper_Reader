"""Batch preserves core observation references, without interpreting their proof."""
from uuid import uuid4

import pytest
from paper_reader_batch.v2_errors import BatchRuntimeError
from test_batch_approval import approve


def test_remote_report_preserves_opaque_readback_evidence(batch):
    refs = approve(batch)
    report = batch.core.report
    evidence = {'role': 'readback', 'path': 'readback/peer.json', 'sha256': 'a' * 64, 'size_bytes': 20}
    def observed(name, plan):
        result = report(name, plan)
        if name == 'A':
            result.update(sync_status='remote_observed', remote_observation=evidence)
        return result
    batch.core.report = observed
    result = batch.driver.apply(refs, request_id=str(uuid4()))
    first = next(s for s in result.subjects if s.subject_id == 'A')
    assert first.status == 'verified' and first.sync_status == 'remote_observed'
    assert first.remote_observation.sha256 == 'a' * 64
    skipped = next(s for s in result.subjects if s.subject_id == 'B')
    assert skipped.remote_observation is None and skipped.sync_status == 'sync_unobserved'


def test_remote_report_rejects_unbound_evidence(batch):
    refs = approve(batch)
    report = batch.core.report
    def invalid(name, plan):
        result = report(name, plan)
        result.update(sync_status='remote_observed', remote_observation=True)
        return result
    batch.core.report = invalid
    with pytest.raises(BatchRuntimeError) as exc:
        batch.driver.apply(refs, request_id=str(uuid4()))
    assert exc.value.code == 'core_response_invalid'
