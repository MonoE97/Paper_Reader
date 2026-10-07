"""Local-only upload protocol. Handles and transport diagnostics never escape."""
import hashlib
import json
import os
import re
from urllib.parse import quote, urlencode

from pydantic import SecretStr

from paper_reader.analysis.contracts import PdfSource
from paper_reader.official.models import HttpResponse, ItemWriteResult, UploadPermit, UploadReceipt
from paper_reader.operations.contracts import WorkflowError
from paper_reader.resource_policy import V2_RESOURCE_POLICY as LIMITS
from paper_reader.storage import open_resolved_source_guard


class UploadError(WorkflowError):
    def __init__(self, code, *, uncertain=False):
        super().__init__(code, 'local upload request did not complete')
        self.uncertain = uncertain


def read_source(source: PdfSource) -> tuple[bytes, int]:
    """Read bounded approved bytes using the canonical held-source guard."""
    try:
        with open_resolved_source_guard(source.resolved_path, max_bytes=LIMITS.local_pdf_max_bytes,
                expected_sha256=source.sha256, expected_size=source.size_bytes,
                expected_device=source.device, expected_inode=source.inode) as guard:
            data = os.pread(guard.descriptor, source.size_bytes + 1, 0)
            guard.verify()
            if len(data) != source.size_bytes or hashlib.sha256(data).hexdigest() != source.sha256:
                raise ValueError('source drift')
            return data, guard.fingerprint.mtime_ns // 1_000_000
    except (OSError, ValueError):
        raise WorkflowError('source_changed', 'approved PDF changed or is unavailable') from None


def write_headers(context, credentials):
    return {'Zotero-API-Version': '3', 'Zotero-Server-ID': context.server_id,
            'Zotero-API-Key': credentials.get_secret_value()}


def write_response(client, method, url, *, headers, body):
    try:
        return client.transport.request(method, url, headers=headers, body=body)
    except Exception:
        raise UploadError('write_uncertain', uncertain=True) from None


def checked_response(response: HttpResponse, context, success: int):
    headers = {k.lower(): v for k, v in response.headers.items()}
    if headers.get('zotero-server-id') != context.server_id:
        raise UploadError('instance_changed', uncertain=True)
    if response.status == 400 and response.body == b'Invalid or expired upload key':
        raise UploadError('attachment_unavailable')
    codes = {400: 'verification_failed', 401: 'auth_required', 403: 'auth_denied',
             404: 'attachment_unavailable', 409: 'plan_stale', 412: 'plan_stale',
             413: 'resource_limit', 428: 'plan_stale', 429: 'rate_limited'}
    if response.status in codes:
        raise UploadError(codes[response.status])
    if (response.status != success or headers.get('zotero-api-version') != '3'
            or len(response.body) > LIMITS.structured_artifact_max_bytes):
        raise UploadError('write_uncertain', uncertain=True)
    return headers


def item_result(response, context, key):
    headers = checked_response(response, context, 204)
    version = headers.get('last-modified-version', '')
    if not version.isascii() or not version.isdecimal():
        raise UploadError('write_uncertain', uncertain=True)
    return ItemWriteResult(key=key, version=int(version), state='succeeded', error_code=None)


def file_precondition(md5):
    if md5 is None:
        return {'If-None-Match': '*'}
    if not re.fullmatch('[a-f0-9]{32}', md5):
        raise WorkflowError('verification_failed', 'invalid previous file digest')
    return {'If-Match': md5}


def request_upload(client, attachment_key, source, *, filename, expected_file_md5, credentials):
    from paper_reader.official.client import _KEY
    attachment_key = _KEY.validate_python(attachment_key, strict=True)
    data, mtime = read_source(source)
    md5 = hashlib.md5(data).hexdigest()
    body = urlencode({'md5': md5, 'filename': filename, 'filesize': len(data), 'mtime': mtime},
                     quote_via=quote).encode()
    response = write_response(client, 'POST', client._prefix + f'items/{attachment_key}/file',
        headers={**write_headers(client.context, credentials), **file_precondition(expected_file_md5),
                 'Content-Type': 'application/x-www-form-urlencoded'}, body=body)
    checked_response(response, client.context, 200)
    try:
        raw = json.loads(response.body)
        if raw == {'exists': 1} and type(raw['exists']) is int:
            return UploadPermit(client.context, attachment_key, None, md5, '')
        key = raw['uploadKey']
        if (not isinstance(key, str) or not re.fullmatch('[A-Za-z0-9_-]{1,256}', key)
                or raw['url'] != client.context.base_url + 'local/uploads/' + key
                or raw['prefix'] != '' or raw['suffix'] != ''
                or raw['contentType'] != 'application/pdf'):
            raise ValueError('invalid permit')
        return UploadPermit(client.context, attachment_key, SecretStr(key), md5, raw['contentType'])
    except (ValueError, KeyError, TypeError):
        raise UploadError('write_uncertain', uncertain=True) from None


def send_upload(client, permit, source):
    if permit.context != client.context or permit.upload_key is None:
        raise WorkflowError('verification_failed', 'invalid local upload permit')
    data, _ = read_source(source)
    if hashlib.md5(data).hexdigest() != permit.md5:
        raise WorkflowError('source_changed', 'upload bytes differ from authorization')
    response = write_response(client, 'POST', client.context.base_url + 'local/uploads/' + permit.upload_key.get_secret_value(),
        headers={'Content-Type': permit.content_type}, body=data)
    checked_response(response, client.context, 201)
    return UploadReceipt(permit.attachment_key, permit.md5, len(data))


def register_upload(client, permit, *, expected_file_md5, credentials):
    if permit.context != client.context or permit.upload_key is None:
        raise WorkflowError('verification_failed', 'invalid local upload permit')
    body = urlencode({'upload': permit.upload_key.get_secret_value()}).encode()
    response = write_response(client, 'POST', client._prefix + f'items/{permit.attachment_key}/file',
        headers={**write_headers(client.context, credentials), **file_precondition(expected_file_md5),
                 'Content-Type': 'application/x-www-form-urlencoded'}, body=body)
    return item_result(response, client.context, permit.attachment_key)
