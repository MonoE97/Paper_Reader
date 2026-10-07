import importlib
import json

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli():
    assert importlib.util.find_spec('paper_reader.official_cli'), 'T5 development CLI missing'
    return importlib.import_module('paper_reader.official_cli')


def args(w):
    return ['--run-root', str(w.store.root), '--coordination-root', str(w.store.coordination_root)]


def test_preview_and_status_are_pure_and_operational_stdout_is_one_json(cli, approved_note, monkeypatch):
    w = approved_note
    def forbidden(*a, **kw):
        raise AssertionError('pure command connected to Zotero')
    monkeypatch.setattr(cli, 'connect', forbidden)
    for action in ('preview', 'status'):
        result = CliRunner().invoke(cli.app, ['plan', action, *args(w), '--plan', w.approval.plan.path])
        assert result.exit_code == 0, result.output
        output = json.loads(result.stdout)
        assert output['schema_version'] == 'paper_reader.command-result.v3' and output['ok']
    assert not w.store.coordination_root.exists() and not w.gateway.calls


def test_apply_without_approval_rejected_before_connect(cli, approved_note, monkeypatch):
    w = approved_note
    monkeypatch.setattr(cli, 'connect', lambda *a, **kw: pytest.fail('network before approval'))
    result = CliRunner().invoke(cli.app, ['plan', 'apply', *args(w), '--plan', w.approval.plan.path])
    assert result.exit_code != 0
    output = json.loads(result.stdout)
    assert not output['ok'] and output['code'] == 'approval_mismatch'


def test_legacy_artifact_rejected_before_connect(cli, approved_note, monkeypatch):
    w = approved_note
    (w.store.root / 'legacy.json').write_text('{"schema_version":"paper_reader.zotero-plan.v2"}')
    monkeypatch.setattr(cli, 'connect', lambda *a, **kw: pytest.fail('network before schema validation'))
    result = CliRunner().invoke(cli.app, ['plan', 'apply', *args(w), '--plan', 'legacy.json'])
    assert result.exit_code != 0 and json.loads(result.stdout)['code'] == 'unsupported_artifact_schema'


def test_bad_operational_arguments_still_produce_one_json(cli):
    result = CliRunner().invoke(cli.app, ['plan', 'retry', '--unknown-option'])
    assert result.exit_code != 0
    assert json.loads(result.stdout)['ok'] is False


def test_cli_apply_calls_only_the_controlled_service(cli, approved_note, monkeypatch):
    w = approved_note
    from paper_reader.operations.store import artifact_ref
    monkeypatch.setattr(cli, 'live', lambda plan: w.gateway)
    monkeypatch.setattr(cli, 'NativeCredentialProvider', lambda: w.credentials)
    result = CliRunner().invoke(cli.app, ['plan', 'apply', *args(w), '--plan', w.approval.plan.path,
        '--approval', artifact_ref(w.approval).path])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['data']['local_status'] == 'local_verified'
    assert len(w.gateway.sent) == 1


def test_corrupt_execution_journal_is_rejected_before_cli_connect(cli, approved_note, monkeypatch):
    w = approved_note
    from paper_reader import services
    from paper_reader.operations.store import artifact_ref
    services.apply_plan(w.plan, w.approval, gateway=w.gateway, credentials=w.credentials, store=w.store)
    event = next((w.store.root / 'operations').rglob('00000000000000000001.json'))
    event.write_bytes(b'{"schema_version":"historical"}')
    calls = []
    def unexpected_connect(*args, **kwargs):
        calls.append(True)
        raise ValueError('journal should be rejected locally')
    monkeypatch.setattr(cli, 'connect', unexpected_connect)
    result = CliRunner().invoke(cli.app, ['plan', 'apply', *args(w), '--plan', w.approval.plan.path,
        '--approval', artifact_ref(w.approval).path])
    assert result.exit_code != 0 and json.loads(result.stdout)['ok'] is False
    assert calls == []
