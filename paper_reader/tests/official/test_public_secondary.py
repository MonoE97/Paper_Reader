"""Public v3 capture path, using an isolated synthetic CDP server only."""
import hashlib
import json
import os
import subprocess

import pytest
from typer.testing import CliRunner

from paper_reader import services
from paper_reader.analysis.contracts import PreparedPaper, Summary
from paper_reader.analysis.evidence import bind_prepared_evidence
from paper_reader.official.models import ZoteroSelection
from paper_reader.official_cli import app
from paper_reader.operations.store import artifact_ref
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256
from test_capture_secondary_url import MockRawCdpServer, SCRIPT


@pytest.fixture
def prepared_capture(store, zotero_source):
    selection, gateway = zotero_source
    raw = {**gateway.parent.raw_json, 'data': {**gateway.parent.raw_json['data'],
           'extra': 'https://93.184.216.34/article'}}
    gateway.parent = gateway.parent.model_copy(update={'raw_json': raw,
        'data': gateway.parent.data.model_copy(update={'extra': raw['data']['extra']})})
    selection = ZoteroSelection(context=selection.context, item_key=selection.item_key,
        parent=gateway.parent, parent_snapshot=store.publish_bytes(canonical_json_bytes(raw), role='source'))
    return services.prepare_zotero(selection, gateway=gateway, store=store)


def capture(store, prepared, output, *extra):
    server = MockRawCdpServer()
    try:
        result = subprocess.run(['node', str(SCRIPT), '--prepared', artifact_ref(prepared).path,
            '--run-root', str(store.root), '--coordination-root', str(store.coordination_root),
            '--source-id', 'secondary-001', '--output', str(output), '--timeout-ms', '5000',
            '--poll-ms', '10', *extra], text=True, capture_output=True, timeout=20,
            env={**os.environ, 'ZOTERO_PAPER_READER_CDP_WS_ENDPOINT': server.endpoint})
    finally:
        server.close()
    return result, server.commands


def test_public_prepare_capture_attach_and_seal(store, note_candidate, prepared_capture, tmp_path):
    capture_dir = tmp_path / 'captures'
    capture_dir.mkdir()
    output = capture_dir / 'secondary-001.json'
    result, commands = capture(store, prepared_capture, output)
    assert result.returncode == 0, result.stderr
    assert commands and json.loads(result.stdout)['status'] == 'captured'
    raw = output.read_bytes()
    captured = json.loads(raw)
    assert captured['run_id'] == prepared_capture.run_id
    assert captured['source_snapshot_sha256'] == prepared_capture.selection.parent_snapshot.sha256
    assert not (store.root / 'run.json').exists()
    common = ['--run-root', str(store.root), '--coordination-root', str(store.coordination_root)]
    result = CliRunner().invoke(app, ['analysis', 'attach-secondary', *common,
        '--prepared', artifact_ref(prepared_capture).path, '--capture-dir', str(capture_dir)])
    assert result.exit_code == 0, result.output
    updated = PreparedPaper.model_validate_json(json.dumps(json.loads(result.stdout)['data']))
    evidence = bind_prepared_evidence(updated, store=store)
    published_capture = evidence.artifacts_by_role['secondary_capture'][0]
    assert json.loads(published_capture.raw_bytes) == captured
    package = store.load(note_candidate.sealed_review)
    summary = Summary.model_validate_json(canonical_json_bytes({**store.load(package.summary).model_dump(mode='json'), 'run_id': updated.run_id,
        'evidence_digest': updated.evidence_manifest.sha256, 'secondary_cross_checks': [{
            'source_id': 'secondary-001', 'status': 'used', 'reason': '外部材料提供适用条件核对。',
            'findings': [{'text': '外部材料说明条件变化可能影响适用范围。', 'relation': 'extends',
                'target': 'technical_details_item', 'caveats': [], 'anchor': {
                    'capture_sha256': published_capture.ref.sha256, 'start_codepoint': 0,
                    'end_codepoint': 25, 'excerpt_sha256': hashlib.sha256(captured['text'][:25].encode()).hexdigest()}}]}]}))
    review = store.load(package.review).model_copy(update={'run_id': updated.run_id,
        'evidence_digest': updated.evidence_manifest.sha256, 'summary_sha256': canonical_json_sha256(summary)})
    (store.root / 'summary.json').write_bytes(canonical_json_bytes(summary))
    (store.root / 'review.json').write_bytes(canonical_json_bytes(review))
    result = CliRunner().invoke(app, ['analysis', 'seal', *common, '--prepared', artifact_ref(updated).path,
        '--summary', 'summary.json', '--review', 'review.json'])
    assert result.exit_code == 0, result.output
    note = (store.root / json.loads(result.stdout)['data']['note_markdown']['path']).read_text()
    assert '外部交叉核对（补充）' in note


@pytest.mark.parametrize('damage', ['snapshot', 'plan', 'prepared', 'legacy-option'])
def test_public_capture_rejects_bad_binding_before_browser(store, prepared_capture, tmp_path, damage):
    if damage in ('snapshot', 'plan'):
        ref = (prepared_capture.selection.parent_snapshot if damage == 'snapshot' else
               next(ref for ref in prepared_capture.artifacts if ref.role == 'secondary_plan'))
        (store.root / ref.path).write_bytes(b'{}')
    if damage == 'prepared':
        value = prepared_capture.model_dump(mode='json')
        value['schema_version'] = 'paper_reader.run.v2'
        (store.root / artifact_ref(prepared_capture).path).write_bytes(canonical_json_bytes(value))
    before = {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    output = tmp_path / 'capture.json'
    extra = ('--plan', 'source/secondary-plan.json') if damage == 'legacy-option' else ()
    result, commands = capture(store, prepared_capture, output, *extra)
    assert result.returncode != 0
    assert not commands and not output.exists()
    assert json.loads(result.stdout)['status'] == 'error'
    assert before == {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
