import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import Credentials
from import_support import ImportTransport
from test_duplicates import parent
from test_import_plan import build, approve

from paper_reader.official.client import OfficialZoteroClient
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.store import FileRunStore


@pytest.fixture
def imported(import_case):
    w = import_case
    def prepare(*, existing=False, filename=None):
        if existing:
            w.gateway.inventory = (parent(collections=('COLLECT2',)),)
        if filename:
            path = w.path.with_name(filename)
            path.write_bytes(w.path.read_bytes())
            evidence = w.api.inspect_pdf(path)
            from paper_reader.storage import canonical_json_bytes
            ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
            w.path, w.evidence = path, evidence
            w.proposal = w.proposal.model_copy(update={'source': evidence.source,
                'evidence': tuple(e.model_copy(update={'source': ref}) for e in w.proposal.evidence)})
        w.plan = build(w)
        w.approval = approve(w, w.plan)
        w.transport = ImportTransport(w, w.plan)
        w.live = OfficialZoteroClient(w.gateway.context, w.transport)
        w.credentials = Credentials()
        return w
    return prepare


def apply(w):
    return w.api.apply_plan(w.plan, w.approval, gateway=w.live, credentials=w.credentials, store=w.store)


def restart(w):
    w.store = FileRunStore(w.store.root, coordination_root=w.store.coordination_root)
    w.transport.store = w.store
    w.live = OfficialZoteroClient(w.gateway.context, w.transport)


def test_import_title_filename_bytes_and_replay_after_process_restart(imported):
    w = imported()
    original = w.path.read_bytes()
    result = apply(w)
    assert result.local_status == 'local_verified' and result.sync_status == 'sync_unobserved'
    p, a, u = w.plan.operations
    assert w.transport.items[p.target_key]['data']['title'] == 'Ion transport in solids'
    assert w.transport.items[a.target_key]['data']['parentItem'] == p.target_key
    assert w.transport.items[a.target_key]['data']['filename'] == 'source paper.pdf'
    assert w.transport.files[a.target_key].read_bytes() == original == w.path.read_bytes()
    assert [c[0] for c in w.transport.calls] == ['create', 'create', 'upload_authorize', 'upload_transfer', 'upload_register']
    sent = len(w.transport.calls)
    restart(w)
    assert apply(w).local_status == 'local_verified'
    assert len(w.transport.calls) == sent


def test_collection_union_own_version_change_allows_attachment(imported):
    w = imported(existing=True)
    result = apply(w)
    assert result.local_status == 'local_verified'
    data = w.transport.items['PARENT01']['data']
    assert set(data['collections']) == {'COLLECT1', 'COLLECT2'}
    assert data['title'] == 'Ion transport in solids'
    assert [c[0] for c in w.transport.calls].count('patch') == 1


@pytest.mark.parametrize('readback', ['promoted', 'changed', 'missing', 'conflicting', 'extra_text'])
def test_parent_identifier_promotion_preserves_exact_approved_value(imported, readback):
    w = imported()
    save = w.transport.save
    def zotero_save(key, data):
        data = dict(data)
        if data['itemType'] == 'journalArticle':
            doi = data['extra'].removeprefix('DOI: ')
            if readback != 'conflicting':
                data.pop('extra')
            if readback != 'missing':
                data['DOI'] = doi if readback in ('promoted', 'extra_text') else '10.5555/other'
            if readback == 'extra_text':
                data['extra'] = 'Unapproved text'
        save(key, data)
    w.transport.save = zotero_save
    result = apply(w)
    if readback == 'promoted':
        assert result.local_status == 'local_verified'
        restart(w)
        assert w.api.reconcile_plan(w.plan, gateway=w.live, store=w.store).local_status == 'local_verified'
        assert apply(w).local_status == 'local_verified'
        assert sum(c[0] == 'create' for c in w.transport.calls) == 2
    else:
        assert [r.state for r in result.operations] == ['blocked', 'planned', 'planned']
        assert [c[0] for c in w.transport.calls] == ['create']


@pytest.mark.parametrize('filename', ['含 空格 αβ paper.pdf', 'Ion + transport.pdf'])
def test_unicode_filename_is_preserved(imported, filename):
    w = imported(filename=filename)
    assert apply(w).local_status == 'local_verified'
    a = next(o for o in w.plan.operations if o.type == 'create_attachment')
    assert w.transport.items[a.target_key]['data']['filename'] == filename
    authorization = next(c[3] for c in w.transport.calls if c[0] == 'upload_authorize')
    assert b'+' not in authorization and b'%20' in authorization
    assert w.path.name == filename


def test_denial_between_parent_and_attachment_does_not_recreate_parent(imported):
    w = imported()
    original_get = w.credentials.get_key
    def grant(context):
        if len(w.transport.calls) == 1:
            raise WorkflowError('auth_denied', 'synthetic denial')
        return original_get(context)
    w.credentials.get_key = grant
    result = apply(w)
    assert [r.state for r in result.operations] == ['verified', 'blocked', 'planned']
    w.credentials.get_key = original_get
    restart(w)
    assert apply(w).local_status == 'local_verified'
    assert sum(c[0] == 'create' for c in w.transport.calls) == 2


def test_external_parent_edit_during_authorization_stops_patch(imported):
    w = imported(existing=True)
    original_get = w.credentials.get_key
    def edit(context):
        w.transport.save('PARENT01', {**w.transport.items['PARENT01']['data'], 'collections': ['COLLECT2', 'NEWCOL01']})
        return original_get(context)
    w.credentials.get_key = edit
    with pytest.raises(WorkflowError, match='plan_stale'):
        apply(w)
    assert w.transport.calls == []


def test_excluded_attachment_has_no_write(imported):
    w = imported()
    from paper_reader.operations.store import artifact_ref
    w.approval = w.api.approve_plan(w.plan, selected_operation_ids=(w.plan.operations[0].operation_id,),
        expected_plan_sha256=artifact_ref(w.plan).sha256, confirmation_ref='parent-only', store=w.store)
    assert apply(w).local_status == 'local_verified'
    assert [c[0] for c in w.transport.calls] == ['create']


def test_changed_source_before_apply_has_no_auth_or_write(imported):
    w = imported()
    w.path.write_bytes(b'changed')
    with pytest.raises(WorkflowError, match='source_changed'):
        apply(w)
    assert w.credentials.calls == 0 and not w.transport.calls


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('change', ['title', 'collections'])
def test_upload_checks_parent_again_after_native_authorization(imported, existing, change):
    w = imported(existing=existing)
    attachment = next(o for o in w.plan.operations if o.type == 'create_attachment')
    parent_key = attachment.payload.parent_key
    grant = w.credentials.get_key
    def edit(context):
        if len(w.transport.calls) == 2:
            value = 'A different paper' if change == 'title' else []
            w.transport.save(parent_key, {**w.transport.items[parent_key]['data'], change: value})
        return grant(context)
    w.credentials.get_key = edit
    with pytest.raises(WorkflowError, match='plan_stale'):
        apply(w)
    assert len(w.transport.calls) == 2
    assert not w.transport.files


def test_parent_derived_child_count_is_not_a_content_change(imported):
    w = imported()
    p = w.plan.operations[0]
    grant = w.credentials.get_key
    def derive(context):
        if p.target_key in w.transport.items:
            w.transport.items[p.target_key]['meta'] = {'numChildren': len(w.transport.items) - 1}
        return grant(context)
    w.credentials.get_key = derive
    assert apply(w).local_status == 'local_verified'


def test_upload_checks_parent_after_transfer_before_registration(imported):
    w = imported()
    p = w.plan.operations[0]
    def edit(stage, key):
        if stage == 'upload_transfer':
            w.transport.save(p.target_key, {**w.transport.items[p.target_key]['data'], 'title': 'A different paper'})
    w.transport.hook = edit
    with pytest.raises(WorkflowError, match='plan_stale'):
        apply(w)
    assert 'upload_register' not in [c[0] for c in w.transport.calls]


def test_unplanned_pdf_under_created_parent_invalidates_upload(imported):
    w = imported()
    p = w.plan.operations[0]
    grant = w.credentials.get_key
    def edit(context):
        if len(w.transport.calls) == 2:
            w.transport.save('OTHERPDF', {'itemType': 'attachment', 'parentItem': p.target_key,
                'contentType': 'application/pdf', 'filename': 'concurrent.pdf'})
        return grant(context)
    w.credentials.get_key = edit
    with pytest.raises(WorkflowError, match='plan_stale'):
        apply(w)
    assert len(w.transport.calls) == 2
