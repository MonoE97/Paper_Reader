"""Installed v3 entrypoint and user-facing analysis boundaries; synthetic inputs only."""
import importlib
import json
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paper_reader.operations.store import artifact_ref
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256

ROOT = Path(__file__).parents[2]


def public_app():
    entry = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['scripts']['paper_reader']
    module, name = entry.split(':')
    return getattr(importlib.import_module(module), name)


def test_installed_entrypoint_declares_v3_and_only_supported_commands():
    runner = CliRunner()
    assert runner.invoke(public_app(), ['--version']).stdout.strip() == '3.0.0'
    for group, commands in {'zotero': ('search', 'inspect', 'collections', 'prepare', 'check-duplicates'),
                            'analysis': ('capture-binding', 'attach-secondary', 'seal'),
                            'plan': ('note', 'import', 'preview', 'approve', 'apply', 'status', 'reconcile', 'retry')}.items():
        result = runner.invoke(public_app(), [group, '--help'])
        assert result.exit_code == 0, result.output
        for name in commands:
            assert name in result.stdout
    for args in (['route'], ['local', 'publish'], ['zotero', 'authorize']):
        result = runner.invoke(public_app(), args)
        assert result.exit_code != 0
        assert json.loads(result.stdout)['schema_version'] == 'paper_reader.command-result.v3'


def test_pdf_smoke_is_offline_and_returns_v3(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('unexpected network'))
    result = CliRunner().invoke(public_app(), ['maintenance', 'extract-pdf', str(ROOT / 'tests/fixtures/minimal.pdf')])
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output['schema_version'] == 'paper_reader.command-result.v3'
    assert output['ok'] and output['data']['extraction']['page_count'] == 1
    assert output['data']['extraction']['pdf_path'] == str((ROOT / 'tests/fixtures/minimal.pdf').resolve())


def seal_args(store, candidate, summary_path=None):
    package = store.load(candidate.sealed_review)
    return ['analysis', 'seal', '--run-root', str(store.root),
            '--coordination-root', str(store.coordination_root), '--prepared', candidate.run_snapshot.path,
            '--summary', summary_path or package.summary.path, '--review', package.review.path]


def test_public_seal_produces_a_bound_candidate_and_full_note(store, note_candidate, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('seal must be offline'))
    result = CliRunner().invoke(public_app(), seal_args(store, note_candidate))
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    assert output['data']['schema_version'] == 'paper_reader.candidate.v3'
    assert output['artifacts'][0]['role'] == 'candidate'
    assert output['data']['gate']['status'] == 'passed'
    assert (store.root / output['data']['note_html']['path']).read_bytes() == store.read_bytes(note_candidate.note_html)


def test_public_seal_reports_quality_blockers_without_publication(store, note_candidate):
    package = store.load(note_candidate.sealed_review)
    summary = store.load(package.summary).model_copy(update={'method': 'Entirely English prose must fail the Chinese-first gate.'})
    review = store.load(package.review).model_copy(update={'summary_sha256': canonical_json_sha256(summary)})
    (store.root / 'summary-input.json').write_bytes(canonical_json_bytes(summary))
    (store.root / 'review-input.json').write_bytes(canonical_json_bytes(review))
    args = seal_args(store, note_candidate, 'summary-input.json')
    args[-1] = 'review-input.json'
    before = {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    result = CliRunner().invoke(public_app(), args)
    assert result.exit_code != 0
    output = json.loads(result.stdout)
    assert output['code'] == 'verification_failed' and output['data']['blockers']
    assert before == {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('schema', ['paper_reader.summary.v2', 'paper_reader.summary.v99', None])
def test_public_seal_rejects_historical_inputs_before_mutation(store, note_candidate, schema):
    package = store.load(note_candidate.sealed_review)
    value = store.load(package.summary).model_dump(mode='json')
    if schema is None:
        value.pop('schema_version')
    else:
        value['schema_version'] = schema
    (store.root / 'historical.json').write_bytes(canonical_json_bytes(value))
    before = {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    result = CliRunner().invoke(public_app(), seal_args(store, note_candidate, 'historical.json'))
    assert result.exit_code != 0
    assert json.loads(result.stdout)['code'] == 'unsupported_artifact_schema'
    assert before == {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
