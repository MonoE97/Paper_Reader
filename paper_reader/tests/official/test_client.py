"""Read contract tests: only the HTTP boundary is replaced."""
import importlib
import importlib.util
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from paper_reader.official.models import LibraryContext
from paper_reader.operations.contracts import WorkflowError


@pytest.fixture
def client_module():
    assert importlib.util.find_spec('paper_reader.official.client'), 'official client is not implemented'
    return importlib.import_module('paper_reader.official.client')


def item(key='PARENT01', **fields):
    return {'key': key, 'version': 7, 'data': {'key': key, 'version': 7,
            'itemType': 'journalArticle', 'title': 'Same title', 'extra': 'DOI: 10.1/example',
            'collections': ['COLLECT1'], 'tags': [{'tag': 'physics'}], **fields}}


class Transport:
    def __init__(self, module, responder=None):
        self.module = module
        self.calls = []
        self.responder = responder
        self.headers = {'Zotero-Server-ID': 'synthetic-instance', 'Zotero-API-Version': '3',
                        'Last-Modified-Version': '42', 'Total-Results': '0'}

    def request(self, method, url, *, headers, body):
        self.calls.append((method, url, headers, body))
        status, extra, payload = self.responder(url) if self.responder else (200, {}, [])
        return self.module.HttpResponse(status=status, headers={**self.headers, **extra},
            body=payload if isinstance(payload, bytes) else json.dumps(payload).encode())


def client(module, context_data, responder=None):
    transport = Transport(module, responder)
    return module.OfficialZoteroClient(LibraryContext(**context_data), transport), transport


def test_connect_reads_each_instance_and_requires_headers(client_module):
    t = Transport(client_module)
    a = client_module.connect('http://127.0.0.1:23119/api/', transport=t)
    t.headers['Zotero-Server-ID'] = 'replacement'
    b = client_module.connect(a.base_url, transport=t)
    assert a.server_id != b.server_id
    for missing in ('Zotero-Server-ID', 'Zotero-API-Version'):
        prior = t.headers.pop(missing)
        with pytest.raises(WorkflowError):
            client_module.connect(a.base_url, transport=t)
        t.headers[missing] = prior
    t.headers['Zotero-API-Version'] = '4'
    with pytest.raises(WorkflowError):
        client_module.connect(a.base_url, transport=t)


@pytest.mark.parametrize('url', ['https://example.com/api/', 'http://192.168.1.2:23119/api/',
                                  'http://127.0.0.1:23119/api/?key=secret'])
def test_nonlocal_url_rejected_before_request(client_module, url):
    t = Transport(client_module)
    with pytest.raises((ValueError, WorkflowError)):
        client_module.connect(url, transport=t)
    assert not t.calls


def test_item_keeps_raw_extra_collections_and_library_version(client_module, context_data):
    c, t = client(client_module, context_data, lambda url: (200, {}, item()))
    snapshot = c.get_item('PARENT01')
    assert snapshot.data.extra == 'DOI: 10.1/example'
    assert snapshot.data.collections == ('COLLECT1',)
    assert snapshot.data.tags == ('physics',)
    assert snapshot.raw_json == item()
    assert c.get_library_version() == 42  # never the item version 7
    assert all(call[0] == 'GET' and call[2]['Zotero-Server-ID'] == 'synthetic-instance' for call in t.calls)


def test_paginated_same_title_results_are_not_collapsed(client_module, context_data):
    def respond(url):
        query = parse_qs(urlsplit(url).query)
        if query.get('limit') == ['1']:
            return 200, {}, []
        start = int(query['start'][0])
        return 200, {'Total-Results': '2'}, [item('PARENT01' if start == 0 else 'PARENT02')]
    c, t = client(client_module, context_data, respond)
    assert [x.key for x in c.search_items('Same title')] == ['PARENT01', 'PARENT02']
    assert any('q=Same+title' in call[1] for call in t.calls)


@pytest.mark.parametrize('change,code', [({'Zotero-Server-ID': 'other'}, 'instance_changed'),
                                        ({'Last-Modified-Version': '43'}, 'plan_stale')])
def test_page_changes_stop_without_partial_results(client_module, context_data, change, code):
    def respond(url):
        query = parse_qs(urlsplit(url).query)
        changed = query.get('start') == ['1']
        return 200, {'Total-Results': '2', **(change if changed else {})}, [item()]
    c, t = client(client_module, context_data, respond)
    with pytest.raises(WorkflowError) as error:
        c.search_items('title')
    assert error.value.code == code
    assert all(call[0] == 'GET' for call in t.calls)


@pytest.mark.parametrize('status,code', [(412, 'instance_changed'), (401, 'auth_required'),
                                        (403, 'auth_denied'), (429, 'rate_limited')])
def test_http_failure_is_bounded_no_retry(client_module, context_data, status, code):
    c, t = client(client_module, context_data, lambda url: (status, {}, b'sensitive response'))
    with pytest.raises(WorkflowError) as error:
        c.get_item('PARENT01')
    assert error.value.code == code
    assert 'sensitive' not in str(error.value)
    assert len(t.calls) == 1


def test_redirect_never_followed(client_module, context_data):
    c, t = client(client_module, context_data,
                  lambda url: (302, {'Location': 'https://example.com/private'}, b''))
    with pytest.raises(WorkflowError):
        c.get_item('PARENT01')
    assert len(t.calls) == 1


def test_collection_parents_and_multiple_attachments(client_module, context_data):
    def respond(url):
        if '/collections?' in url:
            return 200, {'Total-Results': '2'}, [
                {'key': 'COLLECT1', 'version': 3, 'data': {'name': 'Root', 'parentCollection': False}},
                {'key': 'COLLECT2', 'version': 4, 'data': {'name': 'Leaf', 'parentCollection': 'COLLECT1'}}]
        if '/children?' in url:
            return 200, {'Total-Results': '2'}, [item(key, itemType='attachment', parentItem='PARENT01',
                filename='paper.pdf', contentType='application/pdf') for key in ('ATTACH01', 'ATTACH02')]
        return 200, {}, []
    c, _ = client(client_module, context_data, respond)
    assert [x.parent_key for x in c.get_collections()] == [None, 'COLLECT1']
    assert [x.key for x in c.get_children('PARENT01')] == ['ATTACH01', 'ATTACH02']


def test_resource_limit_before_materializing_all_results(client_module, context_data, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(client_module, 'RESOURCE_POLICY', replace(client_module.RESOURCE_POLICY, artifact_tree_max_members=2))
    c, _ = client(client_module, context_data, lambda url: (200, {'Total-Results': '100'}, []))
    with pytest.raises(WorkflowError) as error:
        c.search_items('title')
    assert error.value.code == 'resource_limit'


def test_file_url_endpoint_uses_plaintext_and_encoded_path(client_module, context_data, tmp_path):
    path = tmp_path / '中文 α.pdf'
    path.write_bytes(b'pdf')
    c, t = client(client_module, context_data, lambda url: (200, {}, path.as_uri().encode()))
    assert c.get_file_path('ATTACH01') == path
    assert t.calls[0][1].endswith('/items/ATTACH01/file/view/url')


def test_transport_disables_proxy_and_redirect_and_bounds_bytes(client_module, monkeypatch):
    from io import BytesIO
    from dataclasses import replace
    observed = []
    class Reply(BytesIO):
        code = 200
        headers = {}
    class Opener:
        def open(self, request, timeout):
            assert request.method == 'GET'
            assert timeout > 0
            return Reply(b'0123456789')
    def build(*handlers):
        observed.extend(handlers)
        return Opener()
    monkeypatch.setattr(client_module, 'build_opener', build)
    monkeypatch.setattr(client_module, 'RESOURCE_POLICY', replace(client_module.RESOURCE_POLICY, structured_artifact_max_bytes=5))
    with pytest.raises(WorkflowError) as error:
        client_module.UrllibTransport().request('GET', 'http://127.0.0.1:23119/api/', headers={}, body=None)
    assert error.value.code == 'resource_limit'
    assert observed[0].proxies == {}
    assert observed[1].redirect_request(None, None, 302, '', {}, 'https://example.com') is None


@pytest.mark.parametrize('raw', [[], {'key': 'PARENT01', 'version': True, 'data': {}},
                                item('OTHERKEY')])
def test_invalid_item_snapshot_is_structured(client_module, context_data, raw):
    c, _ = client(client_module, context_data, lambda url: (200, {}, raw))
    with pytest.raises(WorkflowError) as error:
        c.get_item('PARENT01')
    assert error.value.code == 'verification_failed'


@pytest.mark.parametrize('present', [True, False])
def test_item_exists_is_exact_and_includes_trash(client_module, context_data, present):
    def respond(url):
        query = parse_qs(urlsplit(url).query)
        if 'itemKey' not in query:
            return 200, {}, []
        assert query['itemKey'] == ['ABCD2345']
        assert query['includeTrashed'] == ['1']
        return 200, {'Total-Results': str(int(present))}, [item('ABCD2345', deleted=1)] if present else []
    c, t = client(client_module, context_data, respond)
    assert hasattr(c, 'item_exists'), 'T4 collision read is not implemented'
    assert c.item_exists('ABCD2345') is present
    assert all(call[0] == 'GET' for call in t.calls)


@pytest.mark.parametrize('status', [404, 403, 429, 500])
def test_existence_read_failure_is_not_available_key(client_module, context_data, status):
    c, _ = client(client_module, context_data, lambda url: (status, {}, []))
    assert hasattr(c, 'item_exists'), 'T4 collision read is not implemented'
    with pytest.raises(WorkflowError):
        c.item_exists('ABCD2345')
