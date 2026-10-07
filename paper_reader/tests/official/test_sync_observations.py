"""T9 read-only scans and independent observations over synthetic gateways."""
import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paper_reader.official.client import _item
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.store import artifact_ref
from test_duplicates import parent
from test_executor import apply as apply_note
from test_import_execution import imported, apply as apply_import


@pytest.fixture
def sync():
    assert importlib.util.find_spec('paper_reader.official.sync_report'), 'T9 readonly services missing'
    return importlib.import_module('paper_reader.official.sync_report')


class InventoryGateway:
    def __init__(self, context, items, files=None):
        self.context, self.items = context, items
        self.files = files or {}
        self.version = 42
        self.calls = []

    def get_library_version(self):
        return self.version

    def search_items(self, query):
        self.calls.append(('search', query))
        return tuple(i for i in self.items if not i.data.parent_key)

    def get_children(self, key):
        self.calls.append(('children', key))
        return tuple(i for i in self.items if i.data.parent_key == key)

    def get_file_path(self, key):
        self.calls.append(('file', key))
        if key not in self.files:
            raise WorkflowError('attachment_unavailable', 'synthetic not downloaded')
        return self.files[key]


def pdf_child(key, parent_key):
    return _item({'key': key, 'version': 7, 'data': {'itemType': 'attachment',
        'parentItem': parent_key, 'contentType': 'application/pdf', 'filename': 'paper.pdf'}})


def gateway(context_data, *items, files=None):
    from paper_reader.official.models import LibraryContext
    return InventoryGateway(LibraryContext(**context_data), items, files)


@pytest.mark.parametrize('change,relationship,conflict', [
    ({}, 'compatible_identifier', None),
    ({'doi': ''}, 'possible_duplicate', None),
    ({'doi': '10.5555/other'}, 'conflict', 'identifiers'),
    ({'year': '2023'}, 'conflict', 'year'),
    ({'item_type': 'preprint'}, 'conflict', 'item_type'),
    ({'author': 'Someone'}, 'conflict', 'authors'),
])
def test_scan_conservative_pairs_and_persisted_evidence(sync, store, context_data, change, relationship, conflict):
    g = gateway(context_data, parent(), parent('PARENT02', **change), parent('OTHER001', title='Other', doi=''))
    result = sync.scan_duplicates(gateway=g, store=store)
    assert result.scope == 'local_instance' and result.remote_status == 'unknown'
    pair, = result.matches
    assert pair.item_keys == ('PARENT01', 'PARENT02') and pair.relationship == relationship
    if conflict:
        assert conflict in pair.conflicting_fields
    assert pair.evidence and all(store.read_bytes(ref) for ref in pair.evidence)
    assert store.load(artifact_ref(result)) == result
    assert ('children', 'OTHER001') not in g.calls
    assert not store.coordination_root.exists()


def test_identical_pdf_and_unavailable_are_separate_facts(sync, store, context_data):
    pdf = Path(__file__).parents[1] / 'fixtures/minimal.pdf'
    g = gateway(context_data, parent(doi=''), parent('PARENT02', doi=''),
        pdf_child('ATTACH01', 'PARENT01'), pdf_child('ATTACH02', 'PARENT02'),
        pdf_child('ATTACH03', 'PARENT02'), files={'ATTACH01': pdf, 'ATTACH02': pdf})
    result = sync.scan_duplicates(gateway=g, store=store)
    assert result.matches[0].relationship == 'identical_pdf'
    assert result.unavailable_attachment_keys == ('ATTACH03',)
    assert result.remote_status == 'unknown'


def test_rescan_after_user_resolution_does_not_retain_deleted_pair(sync, store, context_data):
    g = gateway(context_data, parent(), parent('PARENT02'))
    first = sync.scan_duplicates(gateway=g, store=store)
    removed = parent('PARENT02').model_dump(mode='json')['raw_json']
    removed['data']['deleted'] = True
    g.items = (parent(), _item(removed))
    second = sync.scan_duplicates(gateway=g, store=store)
    assert not second.matches and first.matches
    assert store.load(artifact_ref(first)) == first


def test_arxiv_versions_and_empty_titles_are_not_strong_duplicates(sync, store, context_data):
    one = parent(doi='', item_type='preprint').raw_json
    two = parent('PARENT02', doi='', item_type='preprint', title='Revised title').raw_json
    one = _item({**one, 'data': {**one['data'], 'archive': 'arXiv', 'archiveID': '2401.00001v1'}})
    two = _item({**two, 'data': {**two['data'], 'archive': 'arXiv', 'archiveID': '2401.00001v2'}})
    g = gateway(context_data, one, two, parent('EMPTY001', title='', doi=''), parent('EMPTY002', title='', doi=''))
    result = sync.scan_duplicates(gateway=g, store=store)
    assert [m.item_keys for m in result.matches] == [('PARENT01', 'PARENT02')]
    assert result.matches[0].relationship == 'conflict'


@pytest.mark.parametrize('change,code', [('instance', 'instance_changed'), ('version', 'plan_stale')])
def test_scan_drift_never_publishes_partial_report(sync, store, context_data, change, code):
    g = gateway(context_data, parent(), parent('PARENT02'))
    read = g.get_children
    def drift(key):
        children = read(key)
        if change == 'instance':
            g.context = g.context.model_copy(update={'server_id': 'replacement'})
        else:
            g.version += 1
        return children
    g.get_children = drift
    before = list(store.root.rglob('*'))
    with pytest.raises(WorkflowError, match=code):
        sync.scan_duplicates(gateway=g, store=store)
    assert list(store.root.rglob('*')) == before


def test_public_check_duplicates_is_one_json_and_only_reads(sync, store, context_data, monkeypatch):
    cli = importlib.import_module('paper_reader.official_cli')
    g = gateway(context_data, parent(), parent('PARENT02'))
    monkeypatch.setattr(cli, 'connect', lambda _: g.context)
    monkeypatch.setattr(cli, 'OfficialZoteroClient', lambda *_: g)
    result = CliRunner().invoke(cli.app, ['zotero', 'check-duplicates', '--run-root', str(store.root),
        '--coordination-root', str(store.coordination_root)])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope['command'] == 'zotero check-duplicates' and envelope['ok']
    assert envelope['artifacts'][0]['role'] == 'duplicate-report'
    assert envelope['data']['matches'][0]['item_keys'] == ['PARENT01', 'PARENT02']


def test_reading_start_records_scan_in_existing_source_closure(sync, store, zotero_source):
    from paper_reader import services
    selection, g = zotero_source
    g.search_items = lambda _: (g.parent, parent('PARENT02', title='Original title', doi='10.1234/paper'))
    get_children = g.get_children
    g.get_children = lambda key: get_children(key) if key == g.parent.key else ()
    prepared = services.prepare_zotero(selection, gateway=g, store=store)
    refs = [ref for ref in prepared.source_snapshots if ref.role == 'duplicate-report']
    assert len(refs) == 1 and store.load(refs[0]).matches


def test_import_start_records_scan_without_adding_write_operations(sync, import_case):
    w = import_case
    plan = w.api.plan_import(w.evidence.source, w.proposal, gateway=w.gateway, store=w.store)
    refs = [ref for ref in plan.inputs if ref.role == 'duplicate-report']
    assert len(refs) == 1 and not w.store.load(refs[0]).matches
    assert w.gateway.writes == 0


def test_local_success_alone_never_proves_remote(sync, approved_note):
    local = apply_note(approved_note)
    report = sync.build_sync_report(local)
    assert report.local_status == 'local_verified' and report.sync_status == 'sync_unobserved'
    assert report.observation_status == 'unknown' and report.remote_observation is None


@pytest.mark.parametrize('change,status,sync_status', [
    ('none', 'verified', 'remote_observed'),
    ('missing', 'missing', 'sync_unobserved'),
    ('tags', 'conflict', 'conflict_needs_review'),
    ('parent', 'conflict', 'conflict_needs_review'),
    ('parent_missing', 'missing', 'sync_unobserved'),
    ('attachment_missing', 'missing', 'sync_unobserved'),
    ('file_unavailable', 'unavailable', 'sync_unobserved'),
    ('file_different', 'conflict', 'conflict_needs_review'),
])
def test_peer_note_full_verification_ignores_cross_instance_versions(sync, approved_note, tmp_path, change, status, sync_status):
    w = approved_note
    local = apply_note(w)
    peer = copy.copy(w.gateway)
    peer.context = peer.context.model_copy(update={'server_id': 'independent-peer'})
    peer.version = 2
    peer.children = tuple(_item({**c.raw_json, 'version': 1,
        'data': {**c.raw_json['data'], 'version': 1}}) for c in peer.children)
    if change == 'missing':
        peer.children = tuple(c for c in peer.children if c.data.item_type != 'note')
    if change == 'tags':
        peer.children = tuple(_item({**c.raw_json, 'data': {**c.raw_json['data'], 'tags': []}})
            if c.data.item_type == 'note' else c for c in peer.children)
    if change == 'parent':
        peer.parent = _item({**peer.parent.raw_json, 'data': {**peer.parent.raw_json['data'], 'title': 'Different paper'}})
    if change == 'parent_missing':
        exists = peer.item_exists
        peer.item_exists = lambda key: key != peer.parent.key and exists(key)
        peer.get_children = lambda _: pytest.fail('missing parent children must not be queried')
    if change == 'attachment_missing':
        peer.children = tuple(c for c in peer.children if c.data.item_type != 'attachment')
    if change == 'file_unavailable':
        def unavailable(_):
            raise WorkflowError('attachment_unavailable', 'synthetic not downloaded')
        peer.get_file_path = unavailable
    if change == 'file_different':
        peer.pdf_path = tmp_path / 'different.pdf'
        peer.pdf_path.write_bytes(b'different bytes')
    events = w.store.events(w.gateway.operation_id)
    sends = len(w.gateway.sent)
    observed = sync.observe_remote(local, gateway=peer, store=w.store)
    report = sync.build_sync_report(local, observed)
    assert report.observation_status == status and report.sync_status == sync_status
    assert observed.context.server_id == 'independent-peer'
    assert observed.operations[0].item_keys
    assert observed.operations[0].readback and w.store.read_bytes(observed.operations[0].readback)
    assert w.store.events(w.gateway.operation_id) == events and len(w.gateway.sent) == sends
    if change == 'none':
        assert observed.operations[0].note_sha256 == w.plan.operations[0].payload.content_sha256
        assert observed.operations[0].pdf_sha256 == w.candidate.source.sha256
    with pytest.raises(WorkflowError, match='verification_failed'):
        sync.build_sync_report(local.model_copy(update={'created_at': '2026-10-07T12:00:00Z'}), observed)


def test_same_instance_cannot_be_its_own_remote_observation(sync, approved_note):
    w = approved_note
    local = apply_note(w)
    with pytest.raises(WorkflowError, match='instance_changed'):
        sync.observe_remote(local, gateway=w.gateway, store=w.store)


@pytest.mark.parametrize('missing_file', [False, True])
def test_peer_upload_hash_and_unavailable_are_reported_without_sends(sync, imported, missing_file):
    from paper_reader.official.client import OfficialZoteroClient
    w = imported()
    local = apply_import(w)
    peer_transport = copy.copy(w.transport)
    peer_transport.context = w.live.context.model_copy(update={'server_id': 'independent-peer'})
    peer_transport.version = 2
    peer_transport.items = {k: {**v, 'version': 1, 'data': {**v['data'], 'version': 1}}
        for k, v in w.transport.items.items()}
    if missing_file:
        peer_transport.files = {}
    peer = OfficialZoteroClient(peer_transport.context, peer_transport)
    sends = len(w.transport.calls)
    observed = sync.observe_remote(local, gateway=peer, store=w.store)
    report = sync.build_sync_report(local, observed)
    assert report.sync_status == ('sync_unobserved' if missing_file else 'remote_observed')
    assert report.observation_status == ('unavailable' if missing_file else 'verified')
    assert len(w.transport.calls) == sends
    if not missing_file:
        assert observed.operations[-1].pdf_sha256 == w.evidence.source.sha256


def test_peer_unregistered_pdf_unavailable_with_different_version_is_not_a_conflict(sync, imported):
    from paper_reader.ingest.execution import verified_item
    from paper_reader.official.client import OfficialZoteroClient
    w = imported()
    local = apply_import(w)
    peer_transport = copy.copy(w.transport)
    peer_transport.context = w.live.context.model_copy(update={'server_id': 'independent-peer'})
    peer_transport.items = dict(w.transport.items)
    op = w.plan.operations[1]
    original = verified_item(w.plan, op.operation_id, w.store).raw_json
    peer_transport.items[op.target_key] = {**original, 'version': 999, 'data': {**original['data'], 'version': 999}}
    peer_transport.files = {}
    observed = sync.observe_remote(local, gateway=OfficialZoteroClient(peer_transport.context, peer_transport), store=w.store)
    report = sync.build_sync_report(local, observed)
    assert observed.operations[-1].status == 'unavailable'
    assert report.observation_status == 'unavailable' and report.sync_status == 'sync_unobserved'
