from pathlib import Path
import json

import pytest
from typer.testing import CliRunner


def test_inspection_separates_reference_doi_and_binds_real_pdf(import_case):
    w = import_case
    assert w.evidence.source.size_bytes == w.path.stat().st_size
    dois = [(c.value, c.page, c.region) for c in w.evidence.candidates if c.field == 'identifiers']
    assert ('10.1234/ions', 1, 'body') in dois
    assert ('10.5555/cited', 2, 'references') in dois
    assert w.evidence.pages[0].text.startswith('Ion transport in solids')
    assert not w.gateway.calls


def test_directory_inspection_isolated_failures_and_duplicate_paths(import_case):
    w = import_case
    (w.path.parent / 'alias.pdf').symlink_to(w.path)
    (w.path.parent / 'broken.pdf').write_bytes(b'not a PDF')
    (w.path.parent / 'readme.txt').write_text('not an input')
    report = w.api.inspect_inputs(w.path.parent)
    assert sum(e.status == 'inspected' for e in report.entries) == 1
    assert any(e.reason == 'duplicate_path' for e in report.entries)
    assert any(e.reason == 'not_pdf' for e in report.entries)
    assert any(e.status == 'blocked' and Path(e.path).name == 'broken.pdf' for e in report.entries)
    assert len({e.subject_id for e in report.entries}) == len(report.entries)


def test_ingest_cli_publishes_evidence_without_zotero(import_case, monkeypatch):
    from paper_reader import official_cli as cli
    w = import_case
    monkeypatch.setattr(cli, 'connect', lambda *a, **kw: pytest.fail('inspect must be offline'))
    result = CliRunner().invoke(cli.app, ['ingest', 'inspect', str(w.path), '--run-root', str(w.store.root),
        '--coordination-root', str(w.store.coordination_root)])
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert value['ok'] and value['artifacts']
    assert value['data']['entries'][0]['status'] == 'inspected'
    assert w.path.exists() and w.gateway.writes == 0
