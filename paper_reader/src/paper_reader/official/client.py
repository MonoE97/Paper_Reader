"""Read-only Zotero 10 adapter. No credentials, retries or redirect following."""
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import TypeAdapter, ValidationError

from paper_reader.official.models import (
    CollectionSnapshot, HttpResponse, HttpTransport, ItemData, ItemKey, ItemSnapshot,
    JsonObject, LibraryContext,
)
from paper_reader.official.files import file_url_to_path
from paper_reader.operations.contracts import WorkflowError
from paper_reader.resource_policy import V2_RESOURCE_POLICY as RESOURCE_POLICY

DEFAULT_BASE_URL = 'http://127.0.0.1:23119/api/'
_KEY = TypeAdapter(ItemKey)
_JSON_OBJECT = TypeAdapter(JsonObject)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    def request(self, method: str, url: str, *, headers: dict[str, str],
                body: bytes | None) -> HttpResponse:
        # Local traffic must not inherit HTTP_PROXY or a redirect to another origin.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            try:
                response = opener.open(Request(url, data=body, headers=headers, method=method), timeout=20)
            except HTTPError as exc:
                response = exc
            with response:
                content = response.read(RESOURCE_POLICY.structured_artifact_max_bytes + 1)
                if len(content) > RESOURCE_POLICY.structured_artifact_max_bytes:
                    raise WorkflowError('resource_limit', 'API response exceeds byte limit')
                return HttpResponse(status=response.code, headers=dict(response.headers), body=content)
        except (OSError, URLError):
            raise WorkflowError('attachment_unavailable', 'local API is unavailable') from None


def _headers(response: HttpResponse) -> dict[str, str]:
    return {key.lower(): value for key, value in response.headers.items()}


def _checked(response: HttpResponse, context: LibraryContext | None = None) -> dict[str, str]:
    headers = _headers(response)
    if response.status == 412 or (context is not None and headers.get('zotero-server-id') != context.server_id):
        raise WorkflowError('instance_changed', 'Zotero instance changed; reconnect and rebuild snapshots')
    codes = {401: 'auth_required', 403: 'auth_denied', 429: 'rate_limited'}
    if response.status != 200:
        raise WorkflowError(codes.get(response.status, 'attachment_unavailable'), 'local API read failed')
    if headers.get('zotero-api-version') != '3' or not headers.get('zotero-server-id'):
        raise WorkflowError('instance_changed', 'API version 3 and Server ID are required')
    if len(response.body) > RESOURCE_POLICY.structured_artifact_max_bytes:
        raise WorkflowError('resource_limit', 'API response exceeds byte limit')
    return headers


def connect(base_url: str = DEFAULT_BASE_URL, *, transport: HttpTransport | None = None) -> LibraryContext:
    # Validate the destination before making a request; identity is learned afresh each time.
    provisional = LibraryContext(base_url=base_url, server_id='unconnected', api_version=3,
                                 library_type='users', library_id=0)
    response = (transport or UrllibTransport()).request('GET', base_url,
        headers={'Zotero-API-Version': '3'}, body=None)
    headers = _checked(response)
    return provisional.model_copy(update={'server_id': headers['zotero-server-id']})


def _integer_header(headers: dict[str, str], name: str) -> int:
    value = headers.get(name, '')
    if not value.isascii() or not value.isdecimal():
        raise WorkflowError('verification_failed', 'missing or invalid API count/version header')
    return int(value)


def _json(response: HttpResponse):
    try:
        return json.loads(response.body)
    except (ValueError, UnicodeError):
        raise WorkflowError('verification_failed', 'invalid API JSON') from None


def _item(raw: JsonObject) -> ItemSnapshot:
    try:
        raw = _JSON_OBJECT.validate_python(raw, strict=True)
        data = raw['data']
        if not isinstance(data, dict):
            raise ValueError('item data must be an object')
        snapshot = ItemSnapshot(key=raw['key'], version=raw['version'], raw_json=raw,
            data=ItemData(item_type=data['itemType'], title=data.get('title', ''),
                extra=data.get('extra', ''), parent_key=data.get('parentItem'),
                collections=tuple(data.get('collections', [])),
                tags=tuple(tag['tag'] for tag in data.get('tags', [])), note=data.get('note', ''),
                filename=data.get('filename', ''), content_type=data.get('contentType', '')))
        if data.get('key', snapshot.key) != snapshot.key or data.get('version', snapshot.version) != snapshot.version:
            raise ValueError('inconsistent item identity')
        return snapshot
    except (KeyError, TypeError, ValueError, ValidationError):
        raise WorkflowError('verification_failed', 'invalid API item snapshot') from None


def _collection(raw: JsonObject) -> CollectionSnapshot:
    try:
        data = raw['data']
        parent = data.get('parentCollection')
        return CollectionSnapshot(key=raw['key'], version=raw['version'], name=data['name'],
                                  parent_key=None if parent is False or parent is None else parent)
    except (KeyError, TypeError, ValueError):
        raise WorkflowError('verification_failed', 'invalid API collection snapshot') from None


class OfficialZoteroClient:
    def __init__(self, context: LibraryContext, transport: HttpTransport):
        self.context = context
        self.transport = transport
        self._prefix = f'{context.base_url}{context.library_type}/{context.library_id}/'

    def _read(self, path: str, **query) -> tuple[HttpResponse, dict[str, str]]:
        url = self._prefix + path
        if query:
            url += '?' + urlencode(query)
        response = self.transport.request('GET', url, headers={
            'Zotero-API-Version': '3', 'Zotero-Server-ID': self.context.server_id}, body=None)
        return response, _checked(response, self.context)

    def get_library_version(self) -> int:
        _, headers = self._read('items', limit=1, format='json')
        return _integer_header(headers, 'last-modified-version')

    def get_item(self, key: str) -> ItemSnapshot:
        key = _KEY.validate_python(key, strict=True)
        response, _ = self._read(f'items/{key}', format='json')
        result = _item(_json(response))
        if result.key != key:
            raise WorkflowError('verification_failed', 'API returned a different item')
        return result

    def _pages(self, path: str, **query) -> tuple[JsonObject, ...]:
        version = self.get_library_version()
        results = []
        total = None
        byte_count = 0
        while total is None or len(results) < total:
            response, headers = self._read(path, format='json', limit=100, start=len(results), **query)
            if _integer_header(headers, 'last-modified-version') != version:
                raise WorkflowError('plan_stale', 'library changed during pagination')
            count = _integer_header(headers, 'total-results')
            byte_count += len(response.body)
            if count > RESOURCE_POLICY.artifact_tree_max_members or byte_count > RESOURCE_POLICY.run_max_bytes:
                raise WorkflowError('resource_limit', 'API inventory exceeds resource limits')
            if total is not None and count != total:
                raise WorkflowError('plan_stale', 'API inventory changed during pagination')
            total = count
            page = _json(response)
            if (not isinstance(page, list) or len(page) > 100 or len(results) + len(page) > total
                    or (not page and len(results) < total)):
                raise WorkflowError('verification_failed', 'invalid or incomplete API page')
            results.extend(page)
        if self.get_library_version() != version:
            raise WorkflowError('plan_stale', 'library changed after pagination')
        keys = [value.get('key') for value in results if isinstance(value, dict)]
        if len(keys) != len(results) or len(set(keys)) != len(keys):
            raise WorkflowError('verification_failed', 'API inventory has invalid or duplicate keys')
        return tuple(results)

    def search_items(self, query: str) -> tuple[ItemSnapshot, ...]:
        return tuple(_item(raw) for raw in self._pages('items/top', q=query, qmode='titleCreatorYear'))

    def item_exists(self, key: str) -> bool:
        key = _KEY.validate_python(key, strict=True)
        # Include trash: a deleted item still occupies its key. Read errors propagate.
        items = tuple(_item(raw) for raw in self._pages('items', itemKey=key, includeTrashed=1))
        if any(item.key != key for item in items):
            raise WorkflowError('verification_failed', 'key lookup returned a different item')
        return bool(items)

    def get_children(self, key: str) -> tuple[ItemSnapshot, ...]:
        key = _KEY.validate_python(key, strict=True)
        children = tuple(_item(raw) for raw in self._pages(f'items/{key}/children'))
        if any(child.data.parent_key != key for child in children):
            raise WorkflowError('verification_failed', 'child belongs to a different parent')
        return children

    def get_collections(self) -> tuple[CollectionSnapshot, ...]:
        return tuple(_collection(raw) for raw in self._pages('collections'))

    def get_file_path(self, key: str) -> Path:
        key = _KEY.validate_python(key, strict=True)
        response, _ = self._read(f'items/{key}/file/view/url')
        try:
            return file_url_to_path(response.body.decode('utf-8').strip())
        except UnicodeError:
            raise WorkflowError('attachment_unavailable', 'invalid attachment URL encoding') from None
