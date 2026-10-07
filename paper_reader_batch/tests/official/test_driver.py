from uuid import uuid4

import pytest

from paper_reader_batch.v2_errors import BatchRuntimeError


def test_preview_displays_full_content_and_reason_without_mutation(batch):
    preview = batch.driver.preview(batch.refs)
    assert preview.manifest_sha256
    assert '完整笔记' in preview.plans[0].preview['operations'][0]['payload']['html']
    assert preview.plans[0].preview['operations'][0]['reason']
    assert not list(batch.root.iterdir()) and not batch.core.sends


def test_drifted_plan_rejected_before_subprocess_mutation(batch):
    preview = batch.driver.preview(batch.refs)
    (batch.refs[-1].run_root / 'plan.json').write_text('{}')
    with pytest.raises(BatchRuntimeError):
        batch.driver.approve(preview, selected_subject_ids=('A', 'C'), expected_preview_sha256=preview.sha256,
            confirmation_ref='test', request_id=str(uuid4()))
    assert not any(a[1] in ('approve', 'apply') for a in batch.core.calls)


def test_wrong_core_root_rejected(api, tmp_path):
    with pytest.raises(BatchRuntimeError): api.client.CoreProcessClient(tmp_path)


def test_strict_core_envelope_rejects_v2_unknown_fields_and_types(api):
    from pydantic import ValidationError
    import json
    base = dict(schema_version='paper_reader.command-result.v3', command='plan status', ok=True, code='ok',
                created_at='2026-10-07T00:00:00Z', artifacts=[], data={})
    for changes in ({'schema_version': 'paper_reader.command-result.v2'}, {'ok': 1}, {'key': 'sensitive'}, {'ok': False}):
        with pytest.raises(ValidationError):
            api.contracts.CoreCommandResult.model_validate_json(json.dumps({**base, **changes}))


def test_cli_development_preview_returns_one_v3_envelope(batch, monkeypatch):
    import importlib
    from typer.testing import CliRunner
    from paper_reader_batch.v2_json import canonical_json_bytes
    cli = importlib.import_module('paper_reader_batch.official_workflow.cli')
    manifest_path = batch.root.parent / 'manifest-input.json'
    manifest_path.write_bytes(canonical_json_bytes(batch.manifest))
    monkeypatch.setattr(cli, 'CoreProcessClient', lambda root: batch.core)
    result = CliRunner().invoke(cli.app, ['preview', '--manifest', str(manifest_path), '--run-root', str(batch.root)])
    import json
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope['schema_version'] == 'paper_reader_batch.command-result.v3'
    assert envelope['ok'] and len(envelope['data']['preview']['plans']) == 3


def test_report_does_not_claim_success_with_unknown_selected_operations(batch):
    from test_batch_approval import approve
    refs = approve(batch)
    invoke = batch.core.invoke
    def wrong_selection(args):
        result = invoke(args)
        if args[1] == 'status':
            result.data['entries'][0]['selected_operation_ids'] = ['unshown_operation']
        return result
    batch.core.invoke = wrong_selection
    with pytest.raises(BatchRuntimeError):
        batch.driver.apply(refs, request_id=str(uuid4()))
    assert not batch.core.sends


def test_cli_preview_file_round_trip_to_approve(batch, monkeypatch, tmp_path):
    import importlib
    import json
    from typer.testing import CliRunner
    from paper_reader_batch.v2_json import canonical_json_bytes
    cli = importlib.import_module('paper_reader_batch.official_workflow.cli')
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(canonical_json_bytes(batch.manifest))
    monkeypatch.setattr(cli, 'CoreProcessClient', lambda root: batch.core)
    common = ['--manifest', str(manifest), '--run-root', str(batch.root)]
    result = CliRunner().invoke(cli.app, ['preview', *common])
    data = json.loads(result.stdout)['data']
    document = tmp_path / 'preview.json'
    document.write_text(json.dumps(data))
    approved = CliRunner().invoke(cli.app, ['approve', *common, '--preview', str(document),
        '--expected-preview-sha256', data['preview_sha256'], '--confirmation-ref', 'explicit-test',
        '--request-id', str(uuid4()), '--subject-id', 'A', '--subject-id', 'C'])
    assert approved.exit_code == 0, approved.output
    assert [r['run_id'] for r in json.loads(approved.stdout)['data']['approval_refs']] == ['A', 'C']


def test_cli_argument_errors_are_one_json_without_payload(api):
    import importlib
    import json
    from typer.testing import CliRunner
    cli = importlib.import_module('paper_reader_batch.official_workflow.cli')
    result = CliRunner().invoke(cli.app, ['approve', '--unexpected', 'synthetic-sensitive-value'])
    assert result.exit_code != 0
    assert json.loads(result.stdout)['ok'] is False
    assert 'synthetic-sensitive-value' not in result.output


def test_development_schema_exports_match_exact_five_contracts(api):
    import json
    from pathlib import Path
    directory = Path(__file__).parents[2] / 'references/official-schemas'
    models = {'manifest': api.contracts.BatchManifest, 'state': api.contracts.BatchState,
              'event': api.contracts.BatchEvent, 'report': api.contracts.BatchReport,
              'command-result': api.contracts.CommandResult}
    assert {p.name for p in directory.glob('*.json')} == {
        f'paper_reader_batch.{name}.v3.schema.json' for name in models}
    for name, model in models.items():
        assert json.loads((directory / f'paper_reader_batch.{name}.v3.schema.json').read_text()) == model.model_json_schema(mode='validation')
