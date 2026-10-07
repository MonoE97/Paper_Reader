"""The current install contract, executable examples and safety instructions."""
import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from paper_reader.analysis.contracts import Summary, Review
from paper_reader.operations.contracts import V3_SCHEMA_MODELS

SKILL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_ROOT.parent
CAPTURE_SCRIPT = SKILL_ROOT / 'scripts/capture-secondary-url.mjs'


def read(path):
    return path.read_text(encoding='utf-8')


def json_example_after_heading(text, heading):
    return text.split(heading, 1)[1].split('```json\n', 1)[1].split('\n```', 1)[0]


def test_current_install_metadata_is_consistent():
    project = tomllib.loads(read(SKILL_ROOT / 'pyproject.toml'))['project']
    assert project['version'] == '3.0.0'
    assert project['scripts'] == {'paper_reader': 'paper_reader.official_cli:app'}
    assert 'Paper Reader 3.0' in read(SKILL_ROOT / 'agents/openai.yaml')
    assert 'official local API' in read(SKILL_ROOT / 'SKILL.md')


def test_skill_exposes_only_the_supported_user_workflows():
    body = read(SKILL_ROOT / 'SKILL.md')
    for phrase in ('uv sync --locked', 'skill root', 'explicit PDF import', 'Chinese-first',
                   'plan preview', 'plan approve', 'plan apply', 'full content', 'human confirmation',
                   'Always Allow', 'sync_unobserved', '2.2', 'historical', 'local-only'):
        assert phrase in body
    assert 'uv run paper_reader zotero authorize' not in body
    assert 'uv run paper_reader run init-zotero' not in body


def test_summary_reference_required_fields_and_examples_match_active_models():
    text = read(SKILL_ROOT / 'references/summary-schema.md')
    sections = text.split('## `review.json`', 1)
    for model, section in ((Summary, sections[0]), (Review, sections[1])):
        for field in model.model_json_schema()['required']:
            assert f'`{field}`' in section
    Summary.model_validate_json(json_example_after_heading(text, '## Minimal write-ready example'))
    Review.model_validate_json(json_example_after_heading(text, '## Minimal review example'))
    assert 'analysis seal' in text
    for phrase in ('codepoint_sha256_v1', 'start_codepoint', 'end_codepoint', 'excerpt_sha256', 'PDF-only'):
        assert phrase in text


def test_active_schema_exports_are_exact_and_strict():
    assert 'paper_reader.duplicate-report.v3' in V3_SCHEMA_MODELS
    for name, model in V3_SCHEMA_MODELS.items():
        schema = json.loads(read(SKILL_ROOT / 'references/official-schemas' / f'{name}.schema.json'))
        assert schema == model.model_json_schema(mode='validation')
        assert schema['additionalProperties'] is False


def test_workflow_documents_explicit_approval_and_recovery():
    text = read(SKILL_ROOT / 'references/zotero-workflow.md')
    for phrase in ('analysis seal', 'confirmation-ref', 'operation-id', 'plan-sha256',
                   'plan reconcile', 'plan retry', 'Server ID', 'remember=true', 'full content'):
        assert phrase in text
    pdf = read(SKILL_ROOT / 'references/pdf-path-workflow.md')
    for phrase in ('ingest inspect', 'plan import', 'original filename', 'existing collection', '2.2'):
        assert phrase in pdf


@pytest.mark.parametrize('filename', ['README.md', 'README.zh-CN.md'])
def test_root_readmes_describe_clean_independent_installation(filename):
    path = REPO_ROOT / filename
    if not path.is_file():
        pytest.skip('root maintenance docs are intentionally absent from a standalone skill')
    text = read(path)
    for phrase in ('3.0.0', 'git archive', '--release-bundle', 'PAPER_READER_TEST_ROOT',
                   '2.2', 'T9', 'T11', 'sync_unobserved'):
        assert phrase in text


def test_portable_validator_runs_from_skill_root():
    result = subprocess.run([sys.executable, 'scripts/validate-skill.py', '.'], cwd=SKILL_ROOT,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_capture_secondary_script_is_in_skill_bundle() -> None:
    assert CAPTURE_SCRIPT.exists()
    text = read(CAPTURE_SCRIPT)
    assert "--plan" in text
    assert "--source-id" in text
    assert "paper_reader.secondary-plan.v2-internal" in text
    assert "secondary_context" in text
    assert "secondary_context_unavailable" in text
    assert "request-retries" in text


def test_capture_secondary_prefers_article_title_over_platform_shell_title() -> None:
    text = read(CAPTURE_SCRIPT)

    activity_title = text.index('pick("#activity-name")?.innerText')
    rich_media_title = text.index('pick(".rich_media_title")?.innerText')
    open_graph_title = text.index('meta("og:title")')
    platform_title = text.index("document.title", open_graph_title)

    assert activity_title < platform_title
    assert rich_media_title < platform_title
    assert open_graph_title < platform_title
