"""T4 planning uses real immutable analysis artifacts and read-only fake Zotero."""
import importlib
import re

import pytest

from paper_reader import services
from paper_reader.official.models import ItemData, ItemSnapshot
from paper_reader.operations.contracts import WorkflowError
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256


def files(store):
    return {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in store.root.rglob('*') if p.is_file()}


def test_preview_has_reasons_and_exact_content(note_candidate, zotero_source, store):
    _, gateway = zotero_source
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    plan = services.plan_note(note_candidate, gateway=gateway, store=store)
    preview = services.preview_plan(plan)
    op, = preview.operations
    assert op.subject_title == 'Original title'
    assert op.subject_id == note_candidate.run_id
    assert op.reason.strip() and op.type == 'create_note'
    assert op.before.key == op.payload.parent_key == 'PARENT01'
    assert op.before.version == 7
    assert store.read_bytes(op.before.snapshot) == canonical_json_bytes(gateway.parent.raw_json)
    assert op.payload.html == store.read_bytes(note_candidate.note_html).decode()
    assert op.payload.title == note_candidate.note_title
    assert op.payload.tags == note_candidate.tags
    assert op.payload.content_sha256 == note_candidate.content_sha256
    assert re.fullmatch('[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}', op.target_key)
    assert preview.plan.sha256 == canonical_json_sha256(plan)
    assert store.load(preview.plan) == plan
    assert preview.content == (note_candidate.note_markdown, note_candidate.note_html)
    assert all(store.read_bytes(ref) for ref in preview.content)
    assert plan.library_version == gateway.version
    assert all(ref in plan.inputs for ref in note_candidate.artifacts)
    assert ('exists', op.target_key) in gateway.calls


def test_preview_never_authorizes_or_writes(note_candidate, zotero_source, store):
    _, gateway = zotero_source
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    plan = services.plan_note(note_candidate, gateway=gateway, store=store)
    before, calls = files(store), list(gateway.calls)
    assert services.preview_plan(plan) == services.preview_plan(plan)
    assert files(store) == before and gateway.calls == calls
    assert not (store.root / 'approvals').exists()
    assert not (store.root / 'operations').exists()
    assert not store.coordination_root.exists()


@pytest.mark.parametrize('field', ['parent', 'collections', 'tags', 'instance', 'pdf', 'html'])
def test_drift_rejected_before_plan_publication(note_candidate, zotero_source, store, field, tmp_path):
    _, gateway = zotero_source
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    if field == 'instance':
        gateway.context = gateway.context.model_copy(update={'server_id': 'replacement'})
    elif field == 'pdf':
        gateway.pdf_path = tmp_path / 'replacement.pdf'
        gateway.pdf_path.write_bytes(b'changed PDF')
    elif field == 'html':
        (store.root / note_candidate.note_html.path).write_bytes(b'changed HTML')
    elif field == 'parent':
        gateway.parent = gateway.parent.model_copy(update={'version': 9})
    else:
        gateway.parent = gateway.parent.model_copy(update={'data': gateway.parent.data.model_copy(
            update={field: ('OTHER123',)})})
    before = files(store)
    with pytest.raises(WorkflowError):
        services.plan_note(note_candidate, gateway=gateway, store=store)
    assert files(store) == before


def test_collision_and_library_drift_do_not_allocate_another_key(note_candidate, zotero_source, store, monkeypatch):
    _, gateway = zotero_source
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    def collision(key):
        gateway.calls.append(('exists', key))
        return True
    monkeypatch.setattr(gateway, 'item_exists', collision)
    before = files(store)
    with pytest.raises(WorkflowError, match='plan_stale'):
        services.plan_note(note_candidate, gateway=gateway, store=store)
    assert len([call for call in gateway.calls if call[0] == 'exists']) == 1
    assert files(store) == before
    def drift(key):
        gateway.version += 1
        return False
    monkeypatch.setattr(gateway, 'item_exists', drift)
    with pytest.raises(WorkflowError, match='plan_stale'):
        services.plan_note(note_candidate, gateway=gateway, store=store)
    assert files(store) == before


def test_title_collision_is_visible_and_blocks_approval(note_candidate, zotero_source, store):
    _, gateway = zotero_source
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    gateway.children += (ItemSnapshot(key='EXIST234', version=42,
        data=ItemData(item_type='note', parent_key='PARENT01', note=f'<h1>{note_candidate.note_title}</h1>'),
        raw_json={'key': 'EXIST234', 'version': 42, 'data': {'itemType': 'note'}}),)
    plan = services.plan_note(note_candidate, gateway=gateway, store=store)
    op, = services.preview_plan(plan).operations
    assert any('EXIST234' in blocker for blocker in op.blockers)
    with pytest.raises(WorkflowError, match='approval_mismatch'):
        services.approve_plan(plan, selected_operation_ids=(op.operation_id,),
            expected_plan_sha256=canonical_json_sha256(plan), confirmation_ref='chat:test', store=store)


def test_explicit_parent_key_is_preserved_without_title_search(note_candidate, zotero_source, store, monkeypatch):
    _, gateway = zotero_source
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    monkeypatch.setattr(gateway, 'search_items', lambda *a: pytest.fail('must use explicit selection'), raising=False)
    plan = services.plan_note(note_candidate, gateway=gateway, store=store)
    assert plan.operations[0].payload.parent_key == note_candidate.target.item_key


@pytest.mark.parametrize('field', ['run_id', 'target', 'gate', 'artifacts'])
def test_unsealed_or_detached_candidate_rejected(note_candidate, zotero_source, store, field):
    _, gateway = zotero_source
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    changes = {'run_id': 'different', 'target': None, 'gate': note_candidate.gate.model_copy(
        update={'status': 'blocked'}), 'artifacts': ()}
    altered = note_candidate.model_copy(update={field: changes[field]})
    before = files(store)
    with pytest.raises((ValueError, WorkflowError)):
        services.plan_note(altered, gateway=gateway, store=store)
    assert files(store) == before and not gateway.calls


@pytest.mark.parametrize('field', ['tags', 'title'])
def test_republished_candidate_cannot_relabel_reviewed_note(note_candidate, zotero_source, store, field):
    from paper_reader.note import render_note_html
    from paper_reader.note_hash import note_html_sha256, canonicalize_note_html_for_hash
    from paper_reader.analysis.rendering import _rewrite_markdown_h1
    if field == 'tags':
        changed = note_candidate.model_copy(update={'tags': ('unreviewed-tag',)})
    else:
        title = note_candidate.note_title.replace('Original title', 'Unrelated title')
        md = _rewrite_markdown_h1(store.read_bytes(note_candidate.note_markdown), title)
        html = render_note_html(md.decode())
        md_ref, html_ref = store.publish_bytes(md, role='note'), store.publish_bytes(html.encode(), role='note')
        package = store.load(note_candidate.sealed_review)
        replace = {note_candidate.note_markdown.path: md_ref, note_candidate.note_html.path: html_ref}
        package = package.model_copy(update={'artifacts': tuple(replace.get(ref.path, ref) for ref in package.artifacts)})
        package_ref = store.publish(package)
        replace[note_candidate.sealed_review.path] = package_ref
        changed = note_candidate.model_copy(update={'note_title': title, 'note_markdown': md_ref, 'note_html': html_ref,
            'sealed_review': package_ref, 'content_sha256': note_html_sha256(html),
            'content_length': len(canonicalize_note_html_for_hash(html)),
            'artifacts': tuple(replace.get(ref.path, ref) for ref in note_candidate.artifacts)})
    store.publish(changed)
    with pytest.raises(WorkflowError, match='verification_failed'):
        services.plan_note(changed, gateway=zotero_source[1], store=store)


def test_unselected_unavailable_pdf_does_not_block_explicit_attachment(note_candidate, zotero_source, store, monkeypatch):
    selection, gateway = zotero_source
    missing = gateway.children[0].model_copy(update={'key': 'MISSING2'})
    gateway.children = (missing, *gateway.children)
    original = gateway.get_file_path
    def locate(key):
        if key == 'MISSING2':
            pytest.fail('planner must not inspect an unselected attachment')
        return original(key)
    monkeypatch.setattr(gateway, 'get_file_path', locate)
    prepared = services.prepare_zotero(selection, gateway=gateway, store=store, attachment_key='ATTACH01')
    package = store.load(note_candidate.sealed_review)
    summary = store.load(package.summary).model_copy(update={'run_id': prepared.run_id,
        'evidence_digest': prepared.evidence_manifest.sha256})
    review = store.load(package.review).model_copy(update={'run_id': prepared.run_id,
        'evidence_digest': prepared.evidence_manifest.sha256, 'summary_sha256': canonical_json_sha256(summary)})
    candidate = services.seal_analysis(prepared, summary, review, store=store)
    gateway.calls.clear()
    plan = services.plan_note(candidate, gateway=gateway, store=store)
    assert ('file', 'ATTACH01') in gateway.calls
    assert plan.operations[0].payload.parent_key == selection.item_key


def test_candidate_cannot_omit_sealed_evidence_members(note_candidate, zotero_source, store):
    prepared = store.load(note_candidate.run_snapshot).model_copy(update={'artifacts': ()})
    prepared_ref = store.publish(prepared)
    package = store.load(note_candidate.sealed_review)
    package = package.model_copy(update={'artifacts': package.artifacts[:5]})
    package_ref = store.publish(package)
    changed = note_candidate.model_copy(update={'run_snapshot': prepared_ref, 'sealed_review': package_ref,
        'artifacts': (prepared_ref, package_ref, *package.artifacts, *prepared.source_snapshots)})
    store.publish(changed)
    before = files(store)
    with pytest.raises(WorkflowError, match='verification_failed'):
        services.plan_note(changed, gateway=zotero_source[1], store=store)
    assert files(store) == before
