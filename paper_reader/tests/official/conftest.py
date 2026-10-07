"""Synthetic fixtures only; no live Zotero or LLM calls."""
import importlib
import importlib.util
from types import SimpleNamespace

import pytest


@pytest.fixture
def api():
    # An assertion gives a useful RED before these new packages exist.
    for package in ("official", "analysis", "operations", "ingest"):
        assert importlib.util.find_spec(f"paper_reader.{package}") is not None, f"missing v3 {package}"
    return SimpleNamespace(**{
        name: importlib.import_module(f"paper_reader.{path}")
        for name, path in {
            "official": "official.models", "analysis": "analysis.contracts",
            "operations": "operations.contracts", "ingest": "ingest.contracts",
            "store": "operations.store",
        }.items()
    })


@pytest.fixture
def context_data():
    return dict(base_url="http://127.0.0.1:23119/api/", server_id="synthetic-instance",
                api_version=3, library_type="users", library_id=0)


@pytest.fixture
def event_data():
    return dict(schema_version="paper_reader.zotero-event.v3", operation_id="op_1",
                stage="create", seq=1, previous_digest=None, state="started",
                attempt_id="attempt_1", request_id="request_1",
                created_at="2026-10-06T00:00:00Z", readback=None,
                approval={'role': 'zotero-approval', 'path': 'approvals/test.json',
                          'sha256': 'a' * 64, 'size_bytes': 1})


@pytest.fixture
def store(api, tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    return api.store.FileRunStore(root, coordination_root=tmp_path / "coordination")

# Reuse released regression fixtures when running only tests/official.
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))


class FakeGateway:
    """Synthetic read-only gateway. No mutation implementation exists."""
    def __init__(self, context, parent, children, pdf_path):
        self.context, self.parent, self.children, self.pdf_path = context, parent, children, pdf_path
        self.calls = []
        self.version = 42

    def get_library_version(self):
        self.calls.append(('version',))
        return self.version

    def search_items(self, query):
        self.calls.append(('search', query))
        return (self.parent,)

    def get_item(self, key):
        self.calls.append(('item', key))
        assert key == self.parent.key
        return self.parent

    def item_exists(self, key):
        self.calls.append(('exists', key))
        return key in {self.parent.key, *(child.key for child in self.children)}

    def get_children(self, key):
        self.calls.append(('children', key))
        assert key == self.parent.key
        return self.children

    def get_file_path(self, key):
        self.calls.append(('file', key))
        assert key in [child.key for child in self.children]
        return self.pdf_path


@pytest.fixture
def zotero_source(store, context_data):
    from paper_reader.official.models import LibraryContext, ItemSnapshot, ItemData, ZoteroSelection
    from paper_reader.storage import canonical_json_bytes
    parent = ItemSnapshot(key='PARENT01', version=7,
        data=ItemData(item_type='journalArticle', title='Original title',
                      extra='https://example.org/commentary', collections=('COLLECT1',)),
        raw_json={'key': 'PARENT01', 'version': 7, 'data': {'key': 'PARENT01', 'version': 7,
            'itemType': 'journalArticle', 'title': 'Original title', 'extra': 'https://example.org/commentary',
            'collections': ['COLLECT1'], 'creators': [{'firstName': 'A', 'lastName': 'Researcher'}],
            'date': '2024-01-02', 'DOI': '10.1234/paper'}})
    attachment = ItemSnapshot(key='ATTACH01', version=8,
        data=ItemData(item_type='attachment', parent_key='PARENT01', filename='minimal.pdf', content_type='application/pdf'),
        raw_json={'key': 'ATTACH01', 'version': 8, 'data': {'key': 'ATTACH01', 'version': 8,
            'itemType': 'attachment', 'parentItem': 'PARENT01', 'filename': 'minimal.pdf', 'contentType': 'application/pdf'}})
    context = LibraryContext(**context_data)
    snapshot = store.publish_bytes(canonical_json_bytes(parent.raw_json), role='source')
    selection = ZoteroSelection(context=context, item_key=parent.key, parent=parent, parent_snapshot=snapshot)
    gateway = FakeGateway(context, parent, (attachment,), Path(__file__).parents[1] / 'fixtures/minimal.pdf')
    return selection, gateway


@pytest.fixture
def note_candidate(store, zotero_source, tmp_path, monkeypatch):
    """A real T3-sealed candidate; only Zotero transport is synthetic."""
    from paper_reader import services
    from paper_reader.analysis.contracts import Summary, Review
    from paper_reader.storage import canonical_json_bytes, canonical_json_sha256
    from test_v2_review_package import _prepared_run, _write_summary_and_review
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    run_dir, digest = _prepared_run(baseline)
    old_summary, old_review = _write_summary_and_review(run_dir, digest)
    selection, gateway = zotero_source
    prepared = services.prepare_zotero(selection, gateway=gateway, store=store)
    summary = Summary.model_validate_json(canonical_json_bytes({
        **old_summary.model_dump(mode='json'), 'schema_version': 'paper_reader.summary.v3',
        'run_id': prepared.run_id, 'evidence_digest': prepared.evidence_manifest.sha256,
        'secondary_cross_checks': [{'source_id': 'secondary-001', 'status': 'unavailable',
            'reason': '离线测试没有采集外部来源。', 'findings': []}]}))
    review = Review.model_validate_json(canonical_json_bytes({
        **old_review.model_dump(mode='json'), 'schema_version': 'paper_reader.review.v3',
        'run_id': prepared.run_id, 'summary_sha256': canonical_json_sha256(summary),
        'evidence_digest': prepared.evidence_manifest.sha256}))
    candidate = services.seal_analysis(prepared, summary, review, store=store)
    gateway.calls.clear()
    return candidate


class WriteGateway(FakeGateway):
    """Only the external service is synthetic; stores, plans and gates stay real."""
    def __init__(self, gateway, store):
        super().__init__(gateway.context, gateway.parent, gateway.children, gateway.pdf_path)
        self.store = store
        self.sent = []
        self.mode = 'success'
        self.operation_id = None

    def get_item(self, key):
        self.calls.append(('item', key))
        return self.parent if key == self.parent.key else next(c for c in self.children if c.key == key)

    def create_items(self, payloads, *, library_version, credentials, write_token):
        from paper_reader.official.client import _item
        from paper_reader.official.models import ItemWriteResult
        from paper_reader.operations.contracts import WorkflowError
        assert self.store.events(self.operation_id)[-1].state == 'started'
        assert library_version == self.version
        self.sent.append((payloads, write_token))
        if self.mode in ('auth_required', 'rate_limited', 'plan_stale'):
            return (ItemWriteResult(key=payloads[0].key, version=None, state='failed', error_code=self.mode),)
        if self.mode == 'lost_without_write':
            raise TimeoutError('synthetic-sensitive-exception')
        payload, = payloads
        self.version += 1
        raw = {'key': payload.key, 'version': self.version, 'data': {'key': payload.key,
            'version': self.version, 'itemType': 'note', 'parentItem': payload.parent_key,
            'note': payload.html, 'tags': [{'tag': tag} for tag in payload.tags]}}
        if self.mode == 'wrong_tags':
            raw['data']['tags'] = [{'tag': 'unexpected'}]
        if self.mode == 'wrong_parent':
            raw['data']['parentItem'] = 'OTHER123'
        self.children += (_item(raw),)
        if self.mode == 'lost':
            raise TimeoutError('synthetic-sensitive-exception')
        return (ItemWriteResult(key=payload.key, version=self.version, state='succeeded', error_code=None),)


class Credentials:
    def __init__(self):
        self.calls = 0
        self.invalidated = 0
        self.code = None

    def get_key(self, context):
        from pydantic import SecretStr
        from paper_reader.operations.contracts import WorkflowError
        self.calls += 1
        if self.code:
            raise WorkflowError(self.code, 'synthetic denial')
        return SecretStr('synthetic-key')

    def invalidate(self, context):
        self.invalidated += 1


@pytest.fixture
def approved_note(note_candidate, zotero_source, store):
    from paper_reader import services
    from paper_reader.operations.store import artifact_ref
    gateway = WriteGateway(zotero_source[1], store)
    plan = services.plan_note(note_candidate, gateway=gateway, store=store)
    gateway.operation_id = plan.operations[0].operation_id
    approval = services.approve_plan(plan, selected_operation_ids=(gateway.operation_id,),
        expected_plan_sha256=artifact_ref(plan).sha256, confirmation_ref='synthetic-user-confirmation', store=store)
    gateway.calls.clear()
    return SimpleNamespace(plan=plan, approval=approval, gateway=gateway, credentials=Credentials(),
                           store=store, candidate=note_candidate)


@pytest.fixture
def import_api():
    from paper_reader import services
    for name in ('inspect_pdf', 'inspect_inputs', 'match_duplicates', 'plan_import', 'validate_import_plan'):
        assert hasattr(services, name), f'T6 service missing: {name}'
    return services


@pytest.fixture
def import_case(import_api, store, tmp_path, context_data):
    import fitz
    from paper_reader.ingest.contracts import IdentificationProposal, FieldEvidence, CollectionChoice
    from paper_reader.analysis.contracts import PaperIdentifier
    from paper_reader.official.models import LibraryContext, CollectionSnapshot
    from paper_reader.storage import canonical_json_bytes
    path = tmp_path / 'source paper.pdf'
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 50), 'Ion transport in solids\nAlice Researcher\n2024\nJournal Article\nDOI: 10.1234/ions')
        page = doc.new_page()
        page.insert_text((50, 50), 'References\nOther paper. DOI: 10.5555/cited')
        doc.save(path)
    evidence = import_api.inspect_pdf(path)
    ref = store.publish_bytes(canonical_json_bytes(evidence), role='source')
    quotes = {'title': 'Ion transport in solids', 'authors': 'Alice Researcher',
              'year': '2024', 'item_type': 'Journal Article', 'identifiers': 'DOI: 10.1234/ions'}
    proposal = IdentificationProposal(schema_version='paper_reader.identification-proposal.v3',
        proposal_id='proposal_test', run_id='run_import', created_at='2026-10-07T00:00:00Z',
        source=evidence.source, title='Ion transport in solids', authors=('Alice Researcher',), year=2024,
        identifiers=(PaperIdentifier(kind='doi', value='10.1234/ions'),), item_type='journalArticle',
        evidence=tuple(FieldEvidence(field=field, source=ref, locator='page:1', quote=quote,
            explanation='由主文逐项核对。', identifier_relation='self' if field == 'identifiers' else 'unresolved',
            identifier=PaperIdentifier(kind='doi', value='10.1234/ions') if field == 'identifiers' else None)
            for field, quote in quotes.items()),
        collections=(CollectionChoice(key='COLLECT1', full_path='Materials / Imaging', reason='研究固体材料。'),),
        missing_fields=(), conflicts=())
    class ImportGateway:
        context = LibraryContext(**context_data)
        version = 42
        inventory = ()
        children = {}
        files = {}
        collections = (CollectionSnapshot(key='ROOT0001', parent_key=None, name='Materials', version=3),
            CollectionSnapshot(key='COLLECT1', parent_key='ROOT0001', name='Imaging', version=4),
            CollectionSnapshot(key='COLLECT2', parent_key=None, name='Imaging', version=5))
        def __init__(self):
            self.calls = []
            self.writes = 0
        def get_library_version(self):
            self.calls.append(('version',))
            return self.version
        def search_items(self, query):
            self.calls.append(('search', query))
            return self.inventory
        def get_item(self, key):
            self.calls.append(('item', key))
            return next(i for i in self.inventory if i.key == key)
        def get_children(self, key):
            self.calls.append(('children', key))
            return self.children.get(key, ())
        def get_collections(self):
            self.calls.append(('collections',))
            return self.collections
        def item_exists(self, key):
            self.calls.append(('exists', key))
            return key in {item.key for item in self.inventory}
        def get_file_path(self, key):
            from paper_reader.operations.contracts import WorkflowError
            self.calls.append(('file', key))
            if key not in self.files:
                raise WorkflowError('attachment_unavailable', 'synthetic missing attachment')
            return self.files[key]
        def create_items(self, *args, **kwargs):
            self.writes += 1
            raise AssertionError('T6 must not write')
    return SimpleNamespace(api=import_api, path=path, evidence=evidence, evidence_ref=ref,
                           proposal=proposal, gateway=ImportGateway(), store=store)
