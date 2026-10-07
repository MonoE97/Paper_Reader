from uuid import uuid4

import pytest

from paper_reader_batch.v2_errors import BatchRuntimeError


def approve(batch, selected=('A', 'C'), **overrides):
    preview = batch.driver.preview(batch.refs)
    options = dict(selected_subject_ids=selected, expected_preview_sha256=preview.sha256,
                   confirmation_ref='explicit-test-confirmation', request_id=str(uuid4()))
    options.update(overrides)
    return batch.driver.approve(preview, **options)


def test_excluding_b_produces_no_approval_or_write_for_b(batch):
    refs = approve(batch)
    assert tuple(r.run_id for r in refs) == ('A', 'C')
    report = batch.driver.apply(refs, request_id=str(uuid4()))
    assert batch.core.sends == ['A', 'C']
    assert [(s.subject_id, s.status) for s in report.subjects] == [('A', 'verified'), ('B', 'skipped'), ('C', 'uncertain')]
    assert all(s.sync_status == 'sync_unobserved' for s in report.subjects)
    assert not tuple(batch.refs[1].run_root.glob('approval-*.json'))


def test_all_excluded_is_pure_and_needs_no_confirmation(batch):
    assert approve(batch, (), confirmation_ref='') == ()
    assert not list(batch.root.iterdir())


@pytest.mark.parametrize('kind', ['digest', 'content', 'selection', 'duplicate'])
def test_changed_preview_or_selection_is_rejected_before_approve(batch, kind):
    preview = batch.driver.preview(batch.refs)
    digest = preview.sha256
    selected = ('A',)
    if kind == 'digest': digest = '0' * 64
    if kind == 'content': preview.plans[0].preview['operations'][0]['reason'] = 'Changed text'
    if kind == 'selection': selected = ('unknown',)
    if kind == 'duplicate': selected = ('A', 'A')
    with pytest.raises(BatchRuntimeError):
        batch.driver.approve(preview, selected_subject_ids=selected, expected_preview_sha256=digest,
            confirmation_ref='test', request_id=str(uuid4()))
    assert not any(a[1] == 'approve' for a in batch.core.calls)


def test_parent_excluded_does_not_implicitly_expand_selection(batch):
    batch.previews['A']['operations'].insert(0, dict(operation_id='parent', subject_id='parent_subject',
        subject_title='Parent', type='create_parent', reason='test', blockers=[], depends_on=[], payload={}))
    batch.previews['A']['operations'][1]['depends_on'] = ['parent']
    with pytest.raises(BatchRuntimeError, match='dependency_excluded'):
        approve(batch, ('A',))
    assert batch.core.sends == []


def test_request_replay_binds_selection_and_confirmation(batch):
    request_id = str(uuid4())
    refs = approve(batch, request_id=request_id)
    count = sum(a[1] == 'approve' for a in batch.core.calls)
    assert approve(batch, request_id=request_id) == refs
    assert sum(a[1] == 'approve' for a in batch.core.calls) == count
    with pytest.raises(BatchRuntimeError, match='idempotency_conflict'):
        approve(batch, ('A',), request_id=request_id)
