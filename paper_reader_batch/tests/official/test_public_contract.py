"""Public v3 batch registration, without connecting to a real core or library."""
import importlib
import json
import tomllib
from pathlib import Path
from typer.testing import CliRunner


def public_app():
    root = Path(__file__).parents[2]
    entry = tomllib.loads((root / 'pyproject.toml').read_text())['project']['scripts']['paper_reader_batch']
    module, name = entry.split(':')
    return getattr(importlib.import_module(module), name)


def test_public_batch_version_help_and_legacy_rejection():
    runner = CliRunner()
    assert runner.invoke(public_app(), ['--version']).stdout.strip() == '3.0.0'
    help_result = runner.invoke(public_app(), ['--help'])
    assert help_result.exit_code == 0
    for name in ('preview', 'approve', 'apply'):
        assert name in help_result.stdout
    for name in ('worker', 'write', 'local-prepare', 'run'):
        result = runner.invoke(public_app(), [name])
        assert result.exit_code != 0
        assert json.loads(result.stdout)['schema_version'] == 'paper_reader_batch.command-result.v3'


def test_legacy_manifest_is_rejected_without_allocating_a_batch(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text('{"schema_version":"paper_reader_batch.manifest.v2"}')
    root = tmp_path / 'run'
    root.mkdir()
    result = CliRunner().invoke(public_app(), ['preview', '--manifest', str(manifest), '--run-root', str(root)])
    assert result.exit_code != 0
    assert json.loads(result.stdout)['code'] == 'invalid_artifact'
    assert list(root.iterdir()) == []
