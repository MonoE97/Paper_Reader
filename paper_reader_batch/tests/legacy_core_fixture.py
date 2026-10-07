"""Exercise retained v2 commands in a separate test-only installation."""
import shutil
import subprocess
import tomllib

import pytest


def retained_legacy_core(module, tmp_path_factory):
    source = module.PAPER_READER_ROOT
    project = source / 'pyproject.toml'
    entry = tomllib.loads(project.read_text())['project']['scripts']['paper_reader']
    if entry == 'paper_reader.public_cli:app':
        yield
        return
    assert entry == 'paper_reader.official_cli:app', 'unexpected core installation'
    root = tmp_path_factory.mktemp('retained-v2-core') / 'paper_reader'
    root.mkdir()
    for name in ('src', 'references', 'templates', 'scripts'):
        shutil.copytree(source / name, root / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    (root / 'tests/fixtures').mkdir(parents=True)
    shutil.copyfile(source / 'tests/fixtures/minimal.pdf', root / 'tests/fixtures/minimal.pdf')
    for name in ('SKILL.md', 'uv.lock'):
        shutil.copyfile(source / name, root / name)
    (root / 'pyproject.toml').write_text(project.read_text().replace(
        'paper_reader.official_cli:app', 'paper_reader.public_cli:app'))
    result = subprocess.run(['uv', 'sync', '--locked', '--offline'], cwd=root,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module, 'PAPER_READER_ROOT', root)
        patch.setattr(module, 'FIXTURE_PDF', root / 'tests/fixtures/minimal.pdf')
        patch.setenv('PAPER_READER_LEGACY_TEST_ROOT', str(root))
        yield
