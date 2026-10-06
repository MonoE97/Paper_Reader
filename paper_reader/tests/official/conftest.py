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
                created_at="2026-10-06T00:00:00Z", readback=None)


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

    def get_item(self, key):
        self.calls.append(('item', key))
        assert key == self.parent.key
        return self.parent

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
