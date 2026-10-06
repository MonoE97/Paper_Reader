"""Frozen semantics from the released reader, with independently bound v3 inputs."""
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from paper_reader.analysis.contracts import PaperMetadata, Summary, Review
from paper_reader.official.files import fingerprint_pdf
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256
from paper_reader.review_package import ReviewSealError, validate_review_run
from test_v2_review_package import _prepared_run, _write_summary_and_review


@pytest.fixture
def analysis(monkeypatch):
    for name in ('prepare', 'review'):
        assert importlib.util.find_spec(f'paper_reader.analysis.{name}'), f'missing analysis {name}'
    module = importlib.import_module('paper_reader.analysis.prepare')
    monkeypatch.setattr(module, 'rfc3339_utc', lambda: '2026-10-06T00:00:00Z')
    return importlib.import_module('paper_reader.services')


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    import paper_reader.local_lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, 'rfc3339_utc', lambda: '2026-10-06T00:00:00Z')
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    run_dir, digest = _prepared_run(baseline)
    summary, review = _write_summary_and_review(run_dir, digest)
    validated = validate_review_run(run_dir)
    assert not validated.blockers
    return run_dir, summary, review, validated


def inputs(prepared, frozen, **updates):
    _, old_summary, old_review, _ = frozen
    summary = Summary.model_validate_json(canonical_json_bytes({
        **old_summary.model_dump(mode='json'), 'schema_version': 'paper_reader.summary.v3',
        'run_id': prepared.run_id, 'evidence_digest': prepared.evidence_manifest.sha256, **updates}))
    review = Review.model_validate_json(canonical_json_bytes({
        **old_review.model_dump(mode='json'), 'schema_version': 'paper_reader.review.v3',
        'run_id': prepared.run_id, 'summary_sha256': canonical_json_sha256(summary),
        'evidence_digest': prepared.evidence_manifest.sha256}))
    return summary, review


def prepare(analysis, frozen, store):
    run_dir = frozen[0]
    source = fingerprint_pdf(run_dir.parent / 'paper.pdf')
    return analysis.prepare_pdf(source, metadata=PaperMetadata(title='paper', authors=(),
                                year=None, identifiers=()), store=store)


def test_render_and_quality_gates_match_baseline(analysis, frozen, store):
    from paper_reader.note import build_note_labels
    prepared = prepare(analysis, frozen, store)
    summary, review = inputs(prepared, frozen)
    candidate = analysis.seal_analysis(prepared, summary, review, store=store)
    golden = json.loads((Path(__file__).parents[1] / 'fixtures/official-analysis-baseline.json').read_bytes())
    assert store.read_bytes(candidate.note_markdown).decode() == golden['markdown'] == frozen[3].rendered_note
    assert store.read_bytes(candidate.note_html).decode() == golden['html'] == frozen[3].rendered_html
    assert list(candidate.tags) == golden['tags']
    assert candidate.tags == tuple(build_note_labels(frozen[1].model_dump(mode='json')))
    sealed = store.load(candidate.sealed_review)
    assert sealed.schema_version == 'paper_reader.review-package.v3'
    assert sealed.summary_sha256 == canonical_json_sha256(summary)
    assert store.load(sealed.summary) == summary
    assert candidate.gate.status == 'passed'
    assert store.load(candidate.run_snapshot) == prepared


def test_title_markdown_metacharacters_remain_literal(analysis, frozen, store):
    from paper_reader.zotero_live import _parse_headings
    source = fingerprint_pdf(frozen[0].parent / 'paper.pdf')
    prepared = analysis.prepare_pdf(source, metadata=PaperMetadata(title='A *B* [C] <D> & E_1',
        authors=(), year=None, identifiers=()), store=store)
    candidate = analysis.seal_analysis(prepared, *inputs(prepared, frozen), store=store)
    title, _ = _parse_headings(store.read_bytes(candidate.note_html).decode())
    assert title == candidate.note_title
    assert 'A *B* [C] <D> & E_1' in title


@pytest.mark.parametrize('updates', [
    {'method': 'This fully English method must never pass the rendered Chinese prose gate.'},
    {'one_sentence_summary': 'An English fallback should not become a trusted note.'},
    {'evidence_summary': [{'claim': '正文证据', 'evidence': [{'type': 'text',
        'locator': 'context.md page 999', 'summary': '不属于实际证据的页码。'}], 'confidence': 'medium'}]},
    {'secondary_cross_checks': [{'source_id': 'secondary-001', 'status': 'unavailable',
        'reason': '本地论文不能使用外部证据。', 'findings': []}]},
])
def test_bad_quality_blocks_sealing_without_publication(analysis, frozen, store, updates):
    prepared = prepare(analysis, frozen, store)
    before = {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    with pytest.raises(ReviewSealError):
        analysis.seal_analysis(prepared, *inputs(prepared, frozen, **updates), store=store)
    assert before == {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}


def test_no_zotero_needed_by_prepare_pdf(analysis, store, monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('unexpected network'))
    source = fingerprint_pdf(Path(__file__).parents[1] / 'fixtures/minimal.pdf')
    prepared = analysis.prepare_pdf(source, metadata=PaperMetadata(title='Local title', authors=(),
        year=None, identifiers=()), store=store)
    assert prepared.selection is None
    assert prepared.source == source
    assert b'Full Text' in store.read_bytes(prepared.context)


def test_source_drift_and_evidence_tampering_block_seal(analysis, frozen, store):
    prepared = prepare(analysis, frozen, store)
    (store.root / prepared.context.path).write_bytes(b'tampered')
    with pytest.raises(ValueError):
        analysis.seal_analysis(prepared, *inputs(prepared, frozen), store=store)


def test_review_wrong_hash_and_unpassed_review_block_seal(analysis, frozen, store):
    prepared = prepare(analysis, frozen, store)
    summary, review = inputs(prepared, frozen)
    for changed in (review.model_copy(update={'summary_sha256': '0' * 64}),
                    review.model_copy(update={'needs_improvement': True})):
        with pytest.raises(ReviewSealError):
            analysis.seal_analysis(prepared, summary, changed, store=store)


def test_official_source_extra_and_multiple_pdf_selection(analysis, zotero_source, store):
    from paper_reader.analysis.evidence import bind_evidence
    from paper_reader.operations.contracts import WorkflowError
    selection, gateway = zotero_source
    first = gateway.children[0]
    second = first.model_copy(update={'key': 'ATTACH02'})
    gateway.children = (first, second)
    with pytest.raises(WorkflowError) as error:
        analysis.prepare_zotero(selection, gateway=gateway, store=store)
    assert error.value.code == 'attachment_unavailable'
    prepared = analysis.prepare_zotero(selection, attachment_key='ATTACH01', gateway=gateway, store=store)
    assert prepared.metadata.title == 'Original title'
    assert prepared.metadata.authors == ('A Researcher',)
    assert prepared.metadata.year == 2024
    evidence = bind_evidence(prepared.evidence_manifest, store=store)
    plan = json.loads(evidence.artifacts_by_role['secondary_plan'][0].raw_bytes)
    assert plan['finding_anchor_policy'] == 'codepoint_sha256_v1'
    assert plan['sources'][0]['url'] == 'https://example.org/commentary'
    assert plan['source_snapshot_sha256'] == selection.parent_snapshot.sha256
    assert ('file', 'ATTACH01') in gateway.calls
    assert ('file', 'ATTACH02') not in gateway.calls


def test_changed_parent_and_instance_rejected(analysis, zotero_source, store):
    from paper_reader.operations.contracts import WorkflowError
    selection, gateway = zotero_source
    gateway.parent = gateway.parent.model_copy(update={'version': 9})
    with pytest.raises(WorkflowError) as error:
        analysis.prepare_zotero(selection, gateway=gateway, store=store)
    assert error.value.code == 'plan_stale'
    gateway.context = gateway.context.model_copy(update={'server_id': 'other'})
    with pytest.raises(WorkflowError) as error:
        analysis.prepare_zotero(selection, gateway=gateway, store=store)
    assert error.value.code == 'instance_changed'


def captured(analysis, zotero_source, store, tmp_path):
    import hashlib
    from paper_reader.analysis.evidence import bind_evidence
    selection, gateway = zotero_source
    prepared = analysis.prepare_zotero(selection, gateway=gateway, store=store)
    evidence = bind_evidence(prepared.evidence_manifest, store=store)
    plan = evidence.artifacts_by_role['secondary_plan'][0]
    text = '独立外部材料用于核对论文方法的适用范围。不同数据和条件之间仍存在差异，需要谨慎解释。' * 8
    capture = {'format': 'paper_reader.secondary-capture.v2-internal', 'run_id': prepared.run_id,
        'item_key': selection.item_key, 'source_snapshot_sha256': selection.parent_snapshot.sha256,
        'secondary_plan_sha256': plan.ref.sha256, 'source_id': 'secondary-001',
        'requested_url': 'https://example.org/commentary', 'final_url': 'https://example.org/commentary',
        'captured_at': '2026-10-06T00:00:00Z', 'capture_method': 'chrome_cdp', 'status': 'captured',
        'title': '独立资料标题', 'publisher': '出版者', 'published_at': '', 'description': '',
        'text': text, 'text_length': len(text), 'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'warnings': []}
    capture_dir = tmp_path / 'captures'
    capture_dir.mkdir()
    (capture_dir / 'secondary-001.json').write_bytes(canonical_json_bytes(capture))
    updated = analysis.attach_secondary_captures(prepared, capture_dir, store=store)
    anchor = {'capture_sha256': hashlib.sha256(canonical_json_bytes(capture)).hexdigest(),
              'start_codepoint': 0, 'end_codepoint': 25,
              'excerpt_sha256': hashlib.sha256(text[:25].encode()).hexdigest()}
    return prepared, updated, anchor


def test_secondary_anchor_and_pdf_only_boundaries_preserved(analysis, zotero_source, store, frozen, tmp_path):
    old, prepared, anchor = captured(analysis, zotero_source, store, tmp_path)
    assert prepared.run_id == old.run_id
    assert prepared.evidence_manifest != old.evidence_manifest
    assert store.read_bytes(old.evidence_manifest)
    findings = [{'text': '外部材料指出条件变化会影响方法的适用范围。', 'relation': 'extends',
                 'target': 'technical_details_item', 'caveats': [], 'anchor': anchor}]
    checks = [{'source_id': 'secondary-001', 'status': 'used', 'reason': '外部材料提供独立的适用条件核对。',
               'findings': findings}]
    summary, review = inputs(prepared, frozen, secondary_cross_checks=checks)
    candidate = analysis.seal_analysis(prepared, summary, review, store=store)
    note = store.read_bytes(candidate.note_markdown).decode()
    assert '外部交叉核对（补充）' in note
    assert anchor['excerpt_sha256'] not in note
    assert summary.one_sentence_summary == frozen[1].one_sentence_summary
    assert summary.evidence_summary == frozen[1].evidence_summary
    findings[0]['anchor'] = {**anchor, 'excerpt_sha256': '0' * 64}
    with pytest.raises(ReviewSealError) as error:
        analysis.seal_analysis(prepared, *inputs(prepared, frozen, secondary_cross_checks=checks), store=store)
    assert 'secondary_finding_anchor_invalid' in [b.code for b in error.value.blockers]
    findings[0].pop('anchor')
    with pytest.raises(ReviewSealError) as error:
        analysis.seal_analysis(prepared, *inputs(prepared, frozen, secondary_cross_checks=checks), store=store)
    assert 'secondary_finding_anchor_missing' in [b.code for b in error.value.blockers]


def test_metadata_cannot_change_after_preparation(analysis, frozen, store):
    prepared = prepare(analysis, frozen, store)
    changed = prepared.model_copy(update={'metadata': prepared.metadata.model_copy(update={'title': 'Unrelated paper'})})
    with pytest.raises(ValueError):
        analysis.seal_analysis(changed, *inputs(changed, frozen), store=store)


def test_zero_eligible_urls_still_freezes_anchor_policy(analysis, zotero_source, store):
    from paper_reader.analysis.evidence import bind_evidence
    from paper_reader.official.models import ZoteroSelection
    selection, gateway = zotero_source
    raw = {**gateway.parent.raw_json, 'data': {**gateway.parent.raw_json['data'], 'extra': ''}}
    gateway.parent = gateway.parent.model_copy(update={'raw_json': raw, 'data': gateway.parent.data.model_copy(update={'extra': ''})})
    selection = ZoteroSelection(context=selection.context, item_key=selection.item_key, parent=gateway.parent,
        parent_snapshot=store.publish_bytes(canonical_json_bytes(raw), role='source'))
    prepared = analysis.prepare_zotero(selection, gateway=gateway, store=store)
    evidence = bind_evidence(prepared.evidence_manifest, store=store)
    plan = json.loads(evidence.artifacts_by_role['secondary_plan'][0].raw_bytes)
    assert plan['sources'] == []
    assert plan['finding_anchor_policy'] == 'codepoint_sha256_v1'


def test_v3_rejects_invalid_figure_manifest_membership(analysis, frozen, store):
    from paper_reader.analysis.evidence import AnalysisEvidence, bind_evidence
    from paper_reader.evidence_manifest import EvidenceFigureMember, EvidenceManifestError
    prepared = prepare(analysis, frozen, store)
    bundle = AnalysisEvidence.model_validate_json(store.read_bytes(prepared.evidence_manifest))
    invalid = bundle.model_copy(update={'manifest': bundle.manifest.model_copy(update={'figures': (
        EvidenceFigureMember(figure_id='fake', page=999, artifact_path='absent.png'),)})})
    ref = store.publish_bytes(canonical_json_bytes(invalid), role='evidence')
    with pytest.raises(EvidenceManifestError, match='figure membership'):
        bind_evidence(ref, store=store)


@pytest.mark.parametrize('keep_plan', [False, True])
def test_zotero_cannot_downgrade_secondary_to_bypass_anchor_policy(analysis, zotero_source, frozen, store, keep_plan):
    from paper_reader.analysis.evidence import AnalysisEvidence, publish_member
    from paper_reader.operations.contracts import WorkflowError
    selection, gateway = zotero_source
    prepared = analysis.prepare_zotero(selection, gateway=gateway, store=store)
    bundle = AnalysisEvidence.model_validate_json(store.read_bytes(prepared.evidence_manifest))
    members = tuple(member for member in bundle.members if not member.artifact.role.startswith('secondary_')
                    or (keep_plan and member.artifact.role == 'secondary_plan'))
    members += (publish_member(store, 'secondary_sources.json', b'{"sources":[]}', 'secondary_sources'),)
    manifest = bundle.manifest.model_copy(update={'files': tuple(m.artifact for m in members)})
    changed = bundle.model_copy(update={'manifest': manifest, 'members': members})
    ref = store.publish_bytes(canonical_json_bytes(changed), role='evidence')
    altered = prepared.model_copy(update={'evidence_manifest': ref, 'artifacts': manifest.files})
    with pytest.raises(WorkflowError, match='secondary'):
        analysis.seal_analysis(altered, *inputs(altered, frozen), store=store)


def test_pdf_source_changed_before_sealing_is_rejected(analysis, frozen, store):
    prepared = prepare(analysis, frozen, store)
    path = Path(prepared.source.resolved_path)
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='source'):
        analysis.seal_analysis(prepared, *inputs(prepared, frozen), store=store)


def test_same_day_note_titles_keep_existing_notes(analysis, zotero_source, frozen, store):
    from paper_reader.official.models import ItemData, ItemSnapshot
    selection, gateway = zotero_source
    old_title = '[Codex Summary] Original title - 2026-10-06'
    note = ItemSnapshot(key='OLDNOTE1', version=9,
        data=ItemData(item_type='note', parent_key='PARENT01', note=f'<h1>{old_title}</h1>'),
        raw_json={'key': 'OLDNOTE1', 'version': 9, 'data': {'itemType': 'note', 'parentItem': 'PARENT01',
            'note': f'<h1>{old_title}</h1>'}})
    gateway.children = (*gateway.children, note)
    prepared = analysis.prepare_zotero(selection, gateway=gateway, store=store)
    checks = [{'source_id': 'secondary-001', 'status': 'unavailable', 'reason': '该次没有提供外部抓取结果。', 'findings': []}]
    candidate = analysis.seal_analysis(prepared, *inputs(prepared, frozen, secondary_cross_checks=checks), store=store)
    assert candidate.note_title == old_title + ' (v2)'
    assert gateway.children[-1] == note
