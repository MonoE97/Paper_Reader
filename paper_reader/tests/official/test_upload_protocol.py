"""Documented HTTP contract; no live API or user PDFs."""
import hashlib
import json
import traceback
from urllib.parse import parse_qs

import pytest
from pydantic import SecretStr
from test_auth import Transport

from paper_reader.official.client import OfficialZoteroClient
from paper_reader.official.models import LibraryContext, ParentCreate, AttachmentCreate, ItemPatch
from paper_reader.official.uploads import UploadError
from paper_reader.operations.contracts import WorkflowError


def test_mixed_create_partial_http_200_does_not_mark_failure_success(context_data):
    transport = Transport({'successful': {'0': {'key': 'PARENT01', 'version': 43}},
        'unchanged': {}, 'failed': {'1': {'key': 'ATTACH01', 'code': 400}}})
    client = OfficialZoteroClient(LibraryContext(**context_data), transport)
    values = (ParentCreate(key='PARENT01', item_type='journalArticle', title='Original', authors=('Alice Researcher',),
                          date='2024', extra='DOI: 10.1234/ions', collections=('COLLECT1',)),
              AttachmentCreate(key='ATTACH01', parent_key='PARENT01', title='α file.pdf', filename='α file.pdf'))
    result = client.create_items(values, library_version=42, credentials=SecretStr('SECRET'), write_token='attempt')
    assert [r.state for r in result] == ['succeeded', 'failed']
    data = json.loads(transport.calls[0][3])
    assert data[0]['creators'] == [{'creatorType': 'author', 'name': 'Alice Researcher'}]
    assert data[1]['linkMode'] == 'imported_file' and data[1]['filename'] == 'α file.pdf'
    assert all('md5' not in row for row in data)


def test_upload_precondition_and_md5_are_independent_of_sha256(import_case, context_data):
    source = import_case.evidence.source
    transport = Transport({'exists': 1})
    client = OfficialZoteroClient(LibraryContext(**context_data), transport)
    permit = client.request_upload('ATTACH01', source, filename='准确 α.pdf',
        expected_file_md5='b' * 32, credentials=SecretStr('SECRET'))
    method, url, headers, body = transport.calls[0]
    assert headers['If-Match'] == 'b' * 32 and 'If-None-Match' not in headers
    fields = parse_qs(body.decode())
    assert fields['md5'] == [hashlib.md5(import_case.path.read_bytes()).hexdigest()]
    assert fields['filename'] == ['准确 α.pdf']
    assert int(fields['filesize'][0]) == source.size_bytes
    assert int(fields['mtime'][0]) == import_case.path.stat().st_mtime_ns // 1_000_000
    assert permit.upload_key is None


@pytest.mark.parametrize('url', ['https://example.com/private', 'http://localhost:23119/api/local/uploads/secret',
                                  'http://127.0.0.1:23119/api/local/uploads/other?key=secret'])
def test_upload_permit_cannot_redirect_pdf_or_credentials(import_case, context_data, url):
    transport = Transport({'url': url, 'uploadKey': 'secret', 'contentType': 'application/octet-stream',
                           'prefix': '', 'suffix': ''})
    client = OfficialZoteroClient(LibraryContext(**context_data), transport)
    with pytest.raises(UploadError) as exc:
        client.request_upload('ATTACH01', import_case.evidence.source, filename='source paper.pdf',
                              expected_file_md5=None, credentials=SecretStr('KEYSECRET'))
    assert len(transport.calls) == 1
    assert 'secret' not in ''.join(traceback.format_exception(exc.value))


def test_changed_source_rejected_before_upload_authorization(import_case, context_data):
    transport = Transport({'exists': 1})
    client = OfficialZoteroClient(LibraryContext(**context_data), transport)
    import_case.path.write_bytes(b'drift')
    with pytest.raises(WorkflowError, match='source_changed'):
        client.request_upload('ATTACH01', import_case.evidence.source, filename='source paper.pdf',
                              expected_file_md5=None, credentials=SecretStr('KEYSECRET'))
    assert not transport.calls


def test_official_pdf_content_type_and_expired_registration_response(import_case, context_data):
    context = LibraryContext(**context_data)
    raw = {'url': context.base_url + 'local/uploads/temporaryKEY', 'uploadKey': 'temporaryKEY',
           'contentType': 'application/pdf', 'prefix': '', 'suffix': ''}
    transport = Transport(raw)
    client = OfficialZoteroClient(context, transport)
    permit = client.request_upload('ATTACH01', import_case.evidence.source, filename='source paper.pdf',
                                  expected_file_md5=None, credentials=SecretStr('SECRET'))
    assert permit.content_type == 'application/pdf'
    from paper_reader.official.models import HttpResponse
    transport.request = lambda *a, **kw: HttpResponse(status=400, headers={
        'Zotero-Server-ID': context.server_id, 'Zotero-API-Version': '3'},
        body=b'Invalid or expired upload key')
    with pytest.raises(UploadError) as exc:
        client.register_upload(permit, expected_file_md5=None, credentials=SecretStr('SECRET'))
    assert exc.value.code == 'attachment_unavailable' and not exc.value.uncertain
