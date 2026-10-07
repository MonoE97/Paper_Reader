"""Real installed core process; only its external Zotero service is synthetic."""
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4


def test_non_sibling_real_core_approval_apply_and_lost_response_recovery(api, tmp_path, monkeypatch):
    core_root = Path(os.environ.get('PAPER_READER_TEST_ROOT', str(Path(__file__).parents[3] / 'paper_reader'))).absolute()
    fixture = tmp_path / 'cases.json'
    env = {**os.environ, 'PAPER_READER_BATCH_FIXTURE': str(fixture)}
    built = subprocess.run(['uv', 'run', '--offline', '--locked', 'pytest',
        'tests/official/test_batch_apply.py::test_export_batch_fixture', '-q'], cwd=core_root,
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert built.returncode == 0, built.stdout.decode() + built.stderr.decode()
    cases = json.loads(fixture.read_text())
    c = api.contracts
    refs = tuple(c.BoundArtifactRef.model_validate_json(json.dumps(
        dict(run_root=case['run_root'], run_id=case['run_id'], artifact=case['plan']))) for case in cases)
    root = tmp_path / 'independent-batch-run'
    root.mkdir()
    manifest = c.BatchManifest(schema_version='paper_reader_batch.manifest.v3', batch_id='integration',
                               paper_reader_root=core_root, plan_refs=refs)
    client = api.client.CoreProcessClient(core_root)
    actual_popen = subprocess.Popen
    monkeypatch.setenv('PAPER_READER_BATCH_FIXTURE', str(fixture))
    def synthetic_service(argv, **kwargs):
        argv = list(argv)
        index = argv.index('-m')
        assert argv[index + 1] == 'paper_reader.official_cli'
        argv[index:index + 2] = [str(core_root / 'tests/official/batch_cli_fixture.py')]
        return actual_popen(argv, **kwargs)
    monkeypatch.setattr(api.client.subprocess, 'Popen', synthetic_service)
    driver = api.driver.BatchDriver(client=client, run_root=root, manifest=manifest)
    preview = driver.preview(refs)
    approvals = driver.approve(preview, selected_subject_ids=(refs[0].run_id, refs[2].run_id),
        expected_preview_sha256=preview.sha256, confirmation_ref='synthetic-explicit-confirmation', request_id=str(uuid4()))
    invoke = client.invoke
    def lose_return(args):
        result = invoke(args)
        if args[:2] == ('plan', 'apply'):
            raise api.client.CoreProcessLost('core_process_lost', 'synthetic dropped reply')
        return result
    monkeypatch.setattr(client, 'invoke', lose_return)
    request_id = str(uuid4())
    first = driver.apply(approvals, request_id=request_id)
    assert [s.status for s in first.subjects] == ['verified', 'skipped', 'uncertain']
    restarted = api.driver.BatchDriver(client=api.client.CoreProcessClient(core_root), run_root=root, manifest=manifest)
    second = restarted.apply(approvals, request_id=request_id)
    assert [s.status for s in second.subjects] == ['verified', 'skipped', 'uncertain']
    assert [case['sent'] for case in json.loads(fixture.read_text())] == [1, 0, 1]
    assert not list(Path(cases[1]['run_root']).glob('approvals/*/*.json'))
