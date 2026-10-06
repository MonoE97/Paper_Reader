import importlib
import importlib.util

import pytest

from paper_reader.operations.contracts import WorkflowError


@pytest.fixture
def files():
    assert importlib.util.find_spec('paper_reader.official.files'), 'official files is not implemented'
    return importlib.import_module('paper_reader.official.files')


def test_percent_encoded_local_file_and_fingerprint(files, tmp_path):
    path = tmp_path / '文章 α #%.pdf'
    path.write_bytes(b'%PDF-1.4 sample')
    assert files.file_url_to_path(path.as_uri()) == path
    source = files.fingerprint_pdf(path)
    assert source.resolved_path == str(path)
    assert source.size_bytes == 15
    assert source.inode == path.stat().st_ino


@pytest.mark.parametrize('url', ['https://example.com/paper.pdf', 'file://remote/path.pdf',
    'file:relative.pdf', 'file:///tmp/a%00.pdf', 'file:///tmp/a%GG.pdf', 'file:///tmp/a.pdf?query'])
def test_unsafe_file_url_rejected(files, url):
    with pytest.raises(WorkflowError) as error:
        files.file_url_to_path(url)
    assert error.value.code == 'attachment_unavailable'


def test_missing_attachment(files, tmp_path):
    with pytest.raises(WorkflowError) as error:
        files.file_url_to_path((tmp_path / 'missing.pdf').as_uri())
    assert error.value.code == 'attachment_unavailable'
