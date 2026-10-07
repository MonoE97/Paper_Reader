import pytest
import json
import multiprocessing
from pathlib import Path
import shutil

from conftest import WriteGateway, Credentials

from paper_reader import services
from paper_reader.operations.contracts import WorkflowError
from test_executor import apply


def reconcile(w):
    assert hasattr(services, 'reconcile_plan'), 'T5 reconcile missing'
    return services.reconcile_plan(w.plan, gateway=w.gateway, store=w.store)


def retry(w, *, acknowledge=True, confirmation='synthetic-retry-confirmation'):
    assert hasattr(services, 'retry_operation'), 'T5 explicit retry missing'
    return services.retry_operation(w.plan, operation_id=w.gateway.operation_id,
        acknowledge_no_match=acknowledge, confirmation_ref=confirmation, gateway=w.gateway, store=w.store)


def test_lost_success_is_verified_readonly_and_never_resent(approved_note):
    w = approved_note
    w.gateway.mode = 'lost'
    assert apply(w).operations[0].state == 'uncertain'
    assert reconcile(w).local_status == 'local_verified'
    assert apply(w).local_status == 'local_verified'
    assert len(w.gateway.sent) == 1 and w.credentials.calls == 1


def test_crash_after_started_never_resends_automatically(approved_note, monkeypatch):
    w = approved_note
    original = w.store.append_event
    def crash(event, *, expected_head):
        ref = original(event, expected_head=expected_head)
        if event.state == 'started':
            raise SystemExit('synthetic crash')
        return ref
    monkeypatch.setattr(w.store, 'append_event', crash)
    with pytest.raises(SystemExit):
        apply(w)
    monkeypatch.setattr(w.store, 'append_event', original)
    assert apply(w).operations[0].state == 'uncertain'
    assert not w.gateway.sent
    assert reconcile(w).operations[0].state == 'uncertain'


def test_zero_match_requires_fresh_explicit_retry_then_separate_apply(approved_note):
    w = approved_note
    w.gateway.mode = 'lost_without_write'
    assert apply(w).operations[0].state == 'uncertain'
    for acknowledge, confirmation in [(False, 'ref'), (True, '')]:
        with pytest.raises(WorkflowError):
            retry(w, acknowledge=acknowledge, confirmation=confirmation)
    assert len(w.gateway.sent) == 1
    assert reconcile(w).operations[0].state == 'uncertain'
    report = retry(w)
    assert report.operations[0].state == 'approved'
    assert len(w.gateway.sent) == 1
    w.gateway.mode = 'success'
    assert apply(w).local_status == 'local_verified'
    assert len(w.gateway.sent) == 2
    started = [e for e in w.store.events(w.gateway.operation_id) if e.state == 'started']
    assert len({e.attempt_id for e in started}) == 2
    with pytest.raises(WorkflowError):
        retry(w)


def test_verified_note_removed_is_never_recreated(approved_note):
    w = approved_note
    assert apply(w).local_status == 'local_verified'
    w.gateway.children = tuple(c for c in w.gateway.children if c.key != w.plan.operations[0].target_key)
    assert reconcile(w).operations[0].state == 'blocked'
    assert apply(w).local_status != 'local_verified'
    assert len(w.gateway.sent) == 1
    with pytest.raises(WorkflowError):
        retry(w)


def test_multiple_matching_children_block_reconciliation(approved_note):
    w = approved_note
    w.gateway.mode = 'lost'
    apply(w)
    note = w.gateway.children[-1]
    raw = {**note.raw_json, 'key': 'OTHER123', 'data': {**note.raw_json['data'], 'key': 'OTHER123'}}
    w.gateway.children += (note.model_copy(update={'key': 'OTHER123', 'raw_json': raw}),)
    report = reconcile(w)
    assert report.operations[0].state == 'blocked'
    assert 'duplicate_ambiguous' in report.operations[0].blockers
    assert len(w.gateway.sent) == 1


def test_corrupt_journal_is_rejected_before_auth_or_network(approved_note):
    w = approved_note
    apply(w)
    event = next((w.store.root / 'operations').rglob('00000000000000000001.json'))
    event.write_bytes(b'{}')
    w.gateway.calls.clear()
    calls = w.credentials.calls
    with pytest.raises(WorkflowError):
        apply(w)
    assert w.gateway.calls == [] and w.credentials.calls == calls


class SharedGateway(WriteGateway):
    def __init__(self, gateway, store, directory):
        super().__init__(gateway, store)
        self.directory = Path(directory)
        self.original_children = self.children
        self.operation_id = gateway.operation_id

    def sync(self):
        from paper_reader.official.client import _item
        path = self.directory / 'note.json'
        if path.exists():
            self.children = (*self.original_children, _item(json.loads(path.read_text())))
            self.version = 43

    def get_library_version(self):
        self.sync()
        return super().get_library_version()

    def create_items(self, *args, **kwargs):
        with (self.directory / 'sends.txt').open('a') as stream:
            stream.write('send\n')
        result = super().create_items(*args, **kwargs)
        (self.directory / 'note.json').write_text(json.dumps(self.children[-1].raw_json))
        return result


def concurrent_apply(w, directory, ready, result_queue):
    from paper_reader.operations.store import FileRunStore
    store = FileRunStore(w.store.root, coordination_root=w.store.coordination_root)
    gateway = SharedGateway(w.gateway, store, directory)
    ready.wait(15)
    try:
        report = services.apply_plan(w.plan, w.approval, gateway=gateway, credentials=Credentials(), store=store)
        result_queue.put(report.local_status)
    except Exception as exc:
        result_queue.put(type(exc).__name__)


def test_two_processes_share_one_durable_send(approved_note, tmp_path):
    w = approved_note
    assert hasattr(services, 'apply_plan'), 'T5 executor missing'
    ctx = multiprocessing.get_context('fork')
    ready, results = ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=concurrent_apply, args=(w, tmp_path, ready, results)) for _ in range(2)]
    for process in processes:
        process.start()
    ready.set()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0
    assert sorted(results.get(timeout=5) for _ in processes) == ['local_verified', 'local_verified']
    assert (tmp_path / 'sends.txt').read_text().splitlines() == ['send']


def test_same_operation_cannot_be_rebound_to_a_different_run(approved_note, tmp_path):
    from paper_reader.operations.store import FileRunStore
    w = approved_note
    copied = tmp_path / 'copied-run'
    shutil.copytree(w.store.root, copied)
    w.gateway.mode = 'lost_without_write'
    apply(w)
    w.store = FileRunStore(copied, coordination_root=w.store.coordination_root)
    w.gateway.store = w.store
    with pytest.raises(WorkflowError, match='approval_mismatch'):
        apply(w)
    assert len(w.gateway.sent) == 1


def test_title_and_hash_match_does_not_skip_required_headings():
    from paper_reader.zotero_note_validation import evaluate_note_content
    from paper_reader.note_hash import note_html_sha256
    html = '<h1>标题</h1><p>只有正文。</p>'
    raw = {'key': 'NOTEABCD', 'data': {'key': 'NOTEABCD', 'itemType': 'note',
        'parentItem': 'PARENT01', 'note': html, 'tags': [{'tag': '中文'}]}}
    result = evaluate_note_content(raw, note_key='NOTEABCD', parent_key='PARENT01', title='标题',
        tags=('中文',), required_headings=('30 秒结论',), forbidden_headings=(),
        minimum_content_length=0, content_length=len(html), content_sha256=note_html_sha256(html))
    assert not result.verified
    assert not next(c for c in result.checks if c.name == 'required_headings').passed


def test_reconcile_before_retry_send_preserves_approved_attempt(approved_note):
    w = approved_note
    w.gateway.mode = 'lost_without_write'
    apply(w)
    retry(w)
    before = w.store.events(w.gateway.operation_id)
    assert reconcile(w).operations[0].state == 'approved'
    assert w.store.events(w.gateway.operation_id) == before
    w.gateway.mode = 'success'
    assert apply(w).local_status == 'local_verified'
    assert len(w.gateway.sent) == 2


def test_trashed_note_is_not_verified_or_recreated(approved_note):
    w = approved_note
    apply(w)
    note = w.gateway.children[-1]
    trashed = note.model_copy(update={'raw_json': {**note.raw_json,
        'data': {**note.raw_json['data'], 'deleted': 1}}})
    w.gateway.children = w.gateway.children[:-1]
    original_get = w.gateway.get_item
    w.gateway.item_exists = lambda key: key == note.key
    w.gateway.get_item = lambda key: trashed if key == note.key else original_get(key)
    assert reconcile(w).operations[0].state == 'blocked'
    assert apply(w).operations[0].state == 'blocked'
    assert len(w.gateway.sent) == 1


@pytest.mark.parametrize('defect', ['wrong_readback', 'reused_confirmation', 'nonzero_matches', 'different_approval'])
def test_replay_rejects_forged_retry_before_any_request(approved_note, defect):
    from paper_reader.operations.contracts import OperationEvent
    from paper_reader.operations.store import artifact_ref
    from paper_reader.storage import canonical_json_bytes, canonical_json_sha256, rfc3339_utc
    w = approved_note
    w.gateway.mode = 'lost_without_write'
    apply(w)
    reconcile(w)
    last = w.store.events(w.gateway.operation_id)[-1]
    approval_ref = last.approval
    proof = last.readback
    confirmation = 'a-new-confirmation'
    if defect == 'wrong_readback':
        proof = w.store.publish_bytes(b'{"matches":[]}', role='readback')
    elif defect == 'reused_confirmation':
        confirmation = w.approval.confirmation_ref
    elif defect == 'nonzero_matches':
        # Structurally valid hash chain, but a false no-match assertion.
        proof = w.store.publish_bytes(b'{"matches":["not-empty"]}', role='readback')
        last = last.model_copy(update={'seq': last.seq + 1, 'previous_digest': canonical_json_sha256(last),
            'readback': proof, 'request_id': 'forged-reconcile'})
        w.store.append_event(last, expected_head=last.previous_digest)
    else:
        other = w.approval.model_copy(update={'approval_id': 'another-approval', 'confirmation_ref': 'other'})
        approval_ref = w.store.publish(other)
    event = OperationEvent(schema_version='paper_reader.zotero-event.v3', operation_id=w.gateway.operation_id,
        stage='create', seq=last.seq + 1, previous_digest=canonical_json_sha256(last), state='approved',
        attempt_id='forged-attempt', request_id='forged-retry', created_at=rfc3339_utc(),
        approval=approval_ref, confirmation_ref=confirmation, readback=proof)
    w.store.append_event(event, expected_head=event.previous_digest)
    w.gateway.calls.clear()
    credential_calls = w.credentials.calls
    with pytest.raises(WorkflowError, match='journal_corrupt'):
        apply(w)
    assert w.gateway.calls == [] and w.credentials.calls == credential_calls
    assert len(w.gateway.sent) == 1


def test_illegal_transition_is_rejected_before_event_publication(approved_note):
    from paper_reader.operations.execution_state import record
    w = approved_note
    record(w.plan, w.gateway.operation_id, w.approval, w.store, state='approved', attempt_id='unused-attempt')
    before = w.store.events(w.gateway.operation_id)
    with pytest.raises(WorkflowError, match='journal_corrupt'):
        record(w.plan, w.gateway.operation_id, w.approval, w.store, state='uncertain', stage='readback',
            error_code='write_uncertain')
    assert w.store.events(w.gateway.operation_id) == before
