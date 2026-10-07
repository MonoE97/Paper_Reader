"""Batch calls the same core executor; all library and credential I/O is synthetic."""
import json
import shutil
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from conftest import WriteGateway
from paper_reader import services, official_cli
from paper_reader.official.auth import NativeCredentialProvider
from paper_reader.official.models import HttpResponse
from paper_reader.operations.store import FileRunStore, artifact_ref


@pytest.fixture
def batch_notes(approved_note, tmp_path):
    notes = []
    for label in 'ABC':
        root = tmp_path / label
        shutil.copytree(approved_note.store.root, root)
        store = FileRunStore(root, coordination_root=approved_note.store.coordination_root)
        gateway = WriteGateway(approved_note.gateway, store)
        plan = services.plan_note(approved_note.candidate, gateway=gateway, store=store)
        gateway.operation_id = plan.operations[0].operation_id
        approval = services.approve_plan(plan, selected_operation_ids=(gateway.operation_id,),
            expected_plan_sha256=artifact_ref(plan).sha256, confirmation_ref='batch-test', store=store)
        ref = dict(run_root=str(root), run_id=plan.run_id,
                   artifact=artifact_ref(approval).model_dump(mode='json'),
                   plan=artifact_ref(plan).model_dump(mode='json'))
        notes.append(SimpleNamespace(store=store, gateway=gateway, plan=plan, approval=approval, ref=ref))
    return notes


def invoke(notes):
    args = ['plan', 'apply', '--coordination-root', str(notes[0].store.coordination_root)]
    for note in notes:
        args += ['--approval', json.dumps(note.ref)]
    return CliRunner().invoke(official_cli.app, args)


def wire(monkeypatch, notes, provider):
    monkeypatch.setattr(official_cli, 'live', lambda p: next(n.gateway for n in notes if n.plan == p))
    calls = []
    def factory():
        calls.append(True)
        return provider
    monkeypatch.setattr(official_cli, 'NativeCredentialProvider', factory)
    return calls


@pytest.mark.parametrize('remember', [True, False])
def test_batch_reuses_remembered_key_in_one_core_process(batch_notes, monkeypatch, capsys, remember):
    notes = batch_notes
    secret = 's' * 32
    class Grants:
        calls = 0
        def request(self, *args, **kwargs):
            self.calls += 1
            return HttpResponse(status=200, headers={'Zotero-Server-ID': notes[0].plan.context.server_id,
                'Zotero-API-Version': '3'}, body=json.dumps({'key': secret, 'remember': remember}).encode())
    class MemoryStore:
        def load(self, context): return None
        def save(self, context, key): pass
    grants = Grants()
    providers = wire(monkeypatch, notes, NativeCredentialProvider(grants, store=MemoryStore()))
    result = invoke(notes)
    assert result.exit_code == 0, result.output
    entries = json.loads(result.stdout)['data']['entries']
    assert len(entries) == 3 and len(providers) == grants.calls == 1
    assert [len(n.gateway.sent) for n in notes] == ([1, 1, 1] if remember else [1, 0, 0])
    assert secret not in result.output + capsys.readouterr().err
    assert all(e['report']['local_status'] == 'local_verified' for e in entries) if remember else True


@pytest.mark.parametrize('mutation', ['digest', 'run_id', 'schema', 'missing', 'duplicate'])
def test_all_references_admitted_before_any_connect(batch_notes, monkeypatch, mutation):
    notes = batch_notes
    monkeypatch.setattr(official_cli, 'live', lambda p: pytest.fail('connected before all admission'))
    monkeypatch.setattr(official_cli, 'NativeCredentialProvider', lambda: pytest.fail('credentials before admission'))
    if mutation == 'digest': notes[-1].ref['plan']['sha256'] = '0' * 64
    if mutation == 'run_id': notes[-1].ref['run_id'] = 'another_run'
    if mutation == 'schema':
        path = notes[-1].store.root / notes[-1].ref['artifact']['path']
        path.write_text('{"schema_version":"paper_reader.zotero-approval.v2"}')
    if mutation == 'missing': notes[-1].ref['run_root'] += '/missing'
    if mutation == 'duplicate': notes.append(notes[0])
    result = invoke(notes)
    assert result.exit_code != 0 and json.loads(result.stdout)['ok'] is False
    assert all(not n.gateway.sent for n in notes)


def test_partial_result_and_restart_never_resend_verified_or_uncertain(batch_notes, approved_note, monkeypatch):
    notes = batch_notes
    notes[-1].gateway.mode = 'lost_without_write'
    wire(monkeypatch, notes, approved_note.credentials)
    first = invoke([notes[0], notes[2]])
    assert first.exit_code == 0, first.output
    assert [e['report']['local_status'] for e in json.loads(first.stdout)['data']['entries']] == ['local_verified', 'incomplete']
    wire(monkeypatch, notes, approved_note.credentials)
    second = invoke([notes[0], notes[2]])
    assert second.exit_code == 0, second.output
    assert [len(n.gateway.sent) for n in notes] == [1, 0, 1]


def test_stale_member_does_not_hide_independent_success(batch_notes, approved_note, monkeypatch):
    notes = batch_notes
    notes[0].gateway.parent = notes[0].gateway.parent.model_copy(update={'version': 99})
    wire(monkeypatch, notes, approved_note.credentials)
    result = invoke(notes)
    assert result.exit_code == 0, result.output
    entries = json.loads(result.stdout)['data']['entries']
    assert entries[0]['code'] == 'plan_stale'
    assert [len(n.gateway.sent) for n in notes] == [0, 1, 1]


def test_export_batch_fixture(tmp_path, context_data, monkeypatch):
    """Optional export for the batch package's real subprocess integration test."""
    import os
    from pathlib import Path
    from conftest import note_candidate as candidate_fixture, zotero_source as source_fixture
    from paper_reader.storage import canonical_json_bytes
    cases = []
    for name in 'ABC':
        work = tmp_path / name
        work.mkdir()
        root = work / 'run'
        root.mkdir()
        store = FileRunStore(root, coordination_root=tmp_path / 'coordination')
        source = source_fixture.__wrapped__(store, context_data)
        candidate = candidate_fixture.__wrapped__(store, source, work, monkeypatch)
        plan = services.plan_note(candidate, gateway=source[1], store=store)
        cases.append({'name': name, 'plan': artifact_ref(plan).model_dump(mode='json'),
            'run_root': str(root), 'run_id': plan.run_id,
            'parent': source[1].parent.model_dump(mode='json'),
            'children': [c.model_dump(mode='json') for c in source[1].children],
            'pdf_path': str(source[1].pdf_path), 'sent': 0})
    target = Path(os.environ.get('PAPER_READER_BATCH_FIXTURE', str(tmp_path / 'batch-fixture.json')))
    target.write_bytes(canonical_json_bytes(cases))
    assert len({case['run_id'] for case in cases}) == 3
