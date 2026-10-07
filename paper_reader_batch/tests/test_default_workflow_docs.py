"""Paper Reader Batch 3.0 installed contract, without importing the core package."""
import json
import subprocess
import sys
import tomllib
from pathlib import Path
import pytest

from paper_reader_batch.official_workflow.contracts import BatchManifest, BatchState, BatchEvent, BatchReport, CommandResult

BATCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BATCH_ROOT.parent


def read(path):
    return path.read_text(encoding='utf-8')


def test_current_batch_metadata_is_consistent():
    project = tomllib.loads(read(BATCH_ROOT / 'pyproject.toml'))['project']
    assert project['version'] == '3.0.0'
    assert project['scripts'] == {'paper_reader_batch': 'paper_reader_batch.official_workflow.cli:app'}
    assert 'Paper Reader Batch 3.0' in read(BATCH_ROOT / 'agents/openai.yaml')


def test_batch_skill_uses_core_plans_and_explicit_human_selection():
    text = read(BATCH_ROOT / 'SKILL.md')
    for phrase in ('$paper_reader', 'paper_reader_root', 'non-sibling', 'full content', 'human confirmation',
                   'preview', 'approve', 'apply', '--request-id', 'serial', 'sync_unobserved',
                   'no automatic retry', '2.2'):
        assert phrase in text
    for old in ('uv run paper_reader_batch worker', 'uv run paper_reader_batch write',
                'uv run paper_reader_batch local-prepare'):
        assert old not in text


def test_batch_references_preserve_ownership_and_uncertain_outcomes():
    for name in ('batch-workflow.md', 'parallel-dispatch.md', 'worker-result-contract.md'):
        text = read(BATCH_ROOT / 'references' / name)
        assert '$paper_reader' in text
        assert 'Chinese-first' in text
        assert 'secondary' in text
    workflow = read(BATCH_ROOT / 'references/batch-workflow.md')
    for phrase in ('approval_uncertain', 'uncertain', 'same request', 'core', 'no automatic retry'):
        assert phrase in workflow.casefold()


def test_exported_batch_contracts_match_runtime():
    for name, model in [('manifest', BatchManifest), ('state', BatchState), ('event', BatchEvent),
                        ('report', BatchReport), ('command-result', CommandResult)]:
        schema = json.loads(read(BATCH_ROOT / f'references/official-schemas/paper_reader_batch.{name}.v3.schema.json'))
        assert schema == model.model_json_schema(mode='validation')
        assert schema['additionalProperties'] is False


@pytest.mark.parametrize('name', ['README.md', 'README.zh-CN.md'])
def test_root_install_docs_use_explicit_independent_roots(name):
    path = REPO_ROOT / name
    if not path.is_file():
        pytest.skip('root maintenance docs are intentionally absent from a standalone skill')
    text = read(path)
    for phrase in ('3.0.0', 'git archive', 'PAPER_READER_TEST_ROOT', '--release-bundle', 'T9', 'T11'):
        assert phrase in text


def test_portable_validator_runs_without_the_core_package():
    result = subprocess.run([sys.executable, 'scripts/validate-skill.py', '.'], cwd=BATCH_ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
