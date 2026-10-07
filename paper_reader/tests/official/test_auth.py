"""Native authorization and write transport, using synthetic HTTP responses only."""
import importlib
import json
import traceback

import pytest
from pydantic import SecretStr

from paper_reader.official.client import OfficialZoteroClient
from paper_reader.official.models import HttpResponse, LibraryContext
from paper_reader.operations.contracts import WorkflowError

KEY = 'synthetic-secret-never-persisted'


class Transport:
    def __init__(self, payload, status=200, server='synthetic-instance'):
        self.payload, self.status, self.server = payload, status, server
        self.calls = []

    def request(self, method, url, *, headers, body):
        self.calls.append((method, url, headers, body))
        if isinstance(self.payload, Exception):
            raise self.payload
        return HttpResponse(status=self.status, headers={
            'Zotero-Server-ID': self.server, 'Zotero-API-Version': '3',
            'Last-Modified-Version': '43'}, body=json.dumps(self.payload).encode())


@pytest.fixture
def auth():
    assert importlib.util.find_spec('paper_reader.official.auth'), 'T5 native authorization missing'
    return importlib.import_module('paper_reader.official.auth')


@pytest.mark.parametrize('remember,requests', [(True, 1), (False, 2)])
def test_native_key_lifetime_and_exact_authorization_request(auth, context_data, remember, requests):
    transport = Transport({'key': KEY, 'remember': remember})
    provider = auth.NativeCredentialProvider(transport)
    context = LibraryContext(**context_data)
    for _ in range(2):
        assert provider.get_key(context).get_secret_value() == KEY
    assert len(transport.calls) == requests
    method, url, headers, body = transport.calls[0]
    assert (method, url) == ('POST', context.base_url + 'local/authorize')
    assert headers['Zotero-Server-ID'] == context.server_id
    assert json.loads(body) == {'appName': 'Paper Reader'}
    assert KEY not in repr(provider)
    provider.invalidate(context)
    with pytest.raises(WorkflowError, match='auth_required'):
        provider.get_key(context)
    assert len(transport.calls) == requests


@pytest.mark.parametrize('status,code', [(403, 'auth_denied'), (401, 'auth_required'), (429, 'rate_limited')])
def test_denial_never_loops_or_exposes_sensitive_response(auth, context_data, status, code):
    transport = Transport({'key': KEY, 'denied': True}, status)
    provider = auth.NativeCredentialProvider(transport)
    for _ in range(2):
        with pytest.raises(WorkflowError, match=code) as error:
            provider.get_key(LibraryContext(**context_data))
        assert KEY not in ''.join(traceback.format_exception(error.value))
    assert len(transport.calls) == 1


def test_auth_transport_failure_is_sanitized(auth, context_data):
    provider = auth.NativeCredentialProvider(Transport(OSError(KEY)))
    with pytest.raises(WorkflowError) as error:
        provider.get_key(LibraryContext(**context_data))
    assert KEY not in ''.join(traceback.format_exception(error.value))


def test_instance_change_never_returns_key(auth, context_data):
    provider = auth.NativeCredentialProvider(Transport({'key': KEY, 'remember': True}, server='other'))
    with pytest.raises(WorkflowError, match='instance_changed'):
        provider.get_key(LibraryContext(**context_data))


def item_create():
    from paper_reader.official import models
    assert hasattr(models, 'ItemCreate'), 'T5 typed write payload missing'
    return models.ItemCreate(key='NOTEABCD', parent_key='PARENT01', html='<h1>标题</h1>', tags=('中文',))


def test_write_request_is_typed_versioned_and_parses_each_result(context_data):
    payload = item_create()
    transport = Transport({'successful': {'0': {'key': 'NOTEABCD', 'version': 43}}, 'unchanged': {}, 'failed': {}})
    client = OfficialZoteroClient(LibraryContext(**context_data), transport)
    result, = client.create_items((payload,), library_version=42, credentials=SecretStr(KEY), write_token='a' * 32)
    assert (result.key, result.version, result.state) == ('NOTEABCD', 43, 'succeeded')
    method, url, headers, body = transport.calls[0]
    assert method == 'POST' and url.endswith('/users/0/items')
    assert headers['If-Unmodified-Since-Version'] == '42'
    assert headers['Zotero-Server-ID'] == 'synthetic-instance'
    assert headers['Zotero-API-Key'] == KEY
    assert json.loads(body) == [{'key': 'NOTEABCD', 'version': 0, 'itemType': 'note',
        'parentItem': 'PARENT01', 'note': '<h1>标题</h1>', 'tags': [{'tag': '中文'}]}]
    assert KEY not in result.model_dump_json()


@pytest.mark.parametrize('status,code,state', [
    (401, 'auth_required', 'failed'), (403, 'auth_denied', 'failed'),
    (429, 'rate_limited', 'failed'), (412, 'plan_stale', 'failed'),
    (500, 'write_uncertain', 'unknown'), (302, 'write_uncertain', 'unknown'),
])
def test_write_http_errors_never_retry(context_data, status, code, state):
    transport = Transport({'secret': KEY}, status)
    client = OfficialZoteroClient(LibraryContext(**context_data), transport)
    result, = client.create_items((item_create(),), library_version=42,
        credentials=SecretStr(KEY), write_token='a' * 32)
    assert (result.state, result.error_code) == (state, code)
    assert len(transport.calls) == 1 and KEY not in result.model_dump_json()


def test_mixed_and_malformed_write_results_never_become_whole_batch_success(context_data):
    a = item_create()
    b = a.model_copy(update={'key': 'NOTEEFGH'})
    transport = Transport({'successful': {'0': {'key': a.key, 'version': 43}}, 'unchanged': {},
        'failed': {'1': {'key': b.key, 'code': 400, 'message': KEY}}})
    client = OfficialZoteroClient(LibraryContext(**context_data), transport)
    results = client.create_items((a, b), library_version=42, credentials=SecretStr(KEY), write_token='a' * 32)
    assert [r.state for r in results] == ['succeeded', 'failed']
    transport.payload = {'successful': {'0': {'key': 'WRONGKEY', 'version': 43}}, 'unchanged': {}, 'failed': {}}
    result, = client.create_items((a,), library_version=42, credentials=SecretStr(KEY), write_token='b' * 32)
    assert result.state == 'unknown'
