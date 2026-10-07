"""Process-local native grants. Content approval is enforced by the executor."""
import json

from pydantic import SecretStr

from paper_reader.official.client import UrllibTransport, _checked, _json
from paper_reader.official.models import HttpTransport, LibraryContext
from paper_reader.operations.contracts import ErrorCode, WorkflowError


class NativeCredentialProvider:
    def __init__(self, transport: HttpTransport | None = None):
        self._transport = transport or UrllibTransport(timeout=120)
        self._keys: dict[tuple, SecretStr] = {}
        self._failures: dict[tuple, ErrorCode] = {}

    @staticmethod
    def _identity(context: LibraryContext) -> tuple:
        return (context.base_url, context.server_id, context.library_type, context.library_id)

    def invalidate(self, context: LibraryContext) -> None:
        identity = self._identity(context)
        self._keys.pop(identity, None)
        self._failures[identity] = 'auth_required'

    def get_key(self, context: LibraryContext) -> SecretStr:
        context = LibraryContext.model_validate_json(context.model_dump_json())
        identity = self._identity(context)
        if identity in self._failures:
            raise WorkflowError(self._failures[identity], 'start a new explicit authorization session')
        if identity in self._keys:
            return self._keys[identity]
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
            if raw['remember']:
                self._keys[identity] = key
            return key
        except Exception as exc:
            code = exc.code if isinstance(exc, WorkflowError) else 'auth_required'
            self._failures[identity] = code
        # Never retain a sensitive exception chain or response body.
        raise WorkflowError(code, 'native authorization was not obtained') from None
