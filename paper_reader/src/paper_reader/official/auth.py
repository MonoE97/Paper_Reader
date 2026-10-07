"""Reuse remembered local grants; content approval belongs to the executor."""
import json

from pydantic import SecretStr

from paper_reader.official.client import UrllibTransport, _checked, _json, auth_diagnostic
from paper_reader.official.credentials import LocalCredentialStore
from paper_reader.official.models import HttpTransport, LibraryContext
from paper_reader.operations.contracts import ErrorCode, WorkflowError


class NativeCredentialProvider:
    def __init__(self, transport: HttpTransport | None = None, *, store: LocalCredentialStore | None = None):
        self._transport = transport or UrllibTransport(timeout=120)
        self._store = store if store is not None else LocalCredentialStore()
        self._keys: dict[tuple, SecretStr] = {}
        self._failures: dict[tuple, ErrorCode] = {}
        self._attempted: set[tuple] = set()

    @staticmethod
    def _identity(context: LibraryContext) -> tuple:
        return (context.base_url, context.server_id)

    def invalidate(self, context: LibraryContext) -> None:
        identity = self._identity(context)
        self._keys.pop(identity, None)
        self._failures[identity] = 'auth_required'
        self._store.invalidate(context)

    def get_key(self, context: LibraryContext) -> SecretStr:
        context = LibraryContext.model_validate_json(context.model_dump_json())
        identity = self._identity(context)
        if identity in self._failures:
            raise WorkflowError(self._failures[identity], 'start a new explicit authorization session')
        if identity in self._keys:
            return self._keys[identity]
        if identity in self._attempted:
            raise WorkflowError('auth_required', 'single-use grant consumed; start a new explicit authorization session')
        key = self._store.load(context)
        if key is not None:
            self._keys[identity] = key
            auth_diagnostic('/api/local/authorize', has_key=True, remember=True, status=None)
            return key
        self._attempted.add(identity)
        response, remember, has_key = None, None, False
        try:
            response = self._transport.request('POST', context.base_url + 'local/authorize', headers={
                'Content-Type': 'application/json', 'Zotero-API-Version': '3',
                'Zotero-Server-ID': context.server_id}, body=json.dumps({'appName': 'Paper Reader'}).encode())
            _checked(response, context)
            raw = _json(response)
            if (not isinstance(raw, dict) or type(raw.get('remember')) is not bool
                    or not isinstance(raw.get('key'), str) or len(raw['key']) != 32):
                raise WorkflowError('auth_required', 'invalid native grant')
            key = SecretStr(raw['key'])
            remember, has_key = raw['remember'], True
            if remember:
                self._store.save(context, key)
                self._keys[identity] = key
            return key
        except Exception as exc:
            code = exc.code if isinstance(exc, WorkflowError) else 'attachment_unavailable'
            self._failures[identity] = code
        finally:
            auth_diagnostic('/api/local/authorize', has_key=has_key, remember=remember,
                            status=response.status if response is not None else None)
        # Never retain a sensitive exception chain or response body.
        raise WorkflowError(code, 'native authorization was not obtained') from None
