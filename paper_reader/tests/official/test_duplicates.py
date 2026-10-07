import pytest

from paper_reader.official.client import _item


def parent(key='PARENT01', *, title='Ion transport in solids', doi='10.1234/ions', year='2024',
           author='Researcher', item_type='journalArticle', collections=()):
    return _item({'key': key, 'version': 7, 'data': {'itemType': item_type, 'title': title,
        'DOI': doi, 'date': year, 'creators': [{'firstName': 'Alice', 'lastName': author, 'creatorType': 'author'}],
        'collections': list(collections)}})


def attachment(parent_key='PARENT01'):
    return _item({'key': 'ATTACH01', 'version': 8, 'data': {'itemType': 'attachment',
        'parentItem': parent_key, 'contentType': 'application/pdf', 'filename': 'old name.pdf'}})


@pytest.mark.parametrize('change,relationship,conflict', [
    ({}, 'compatible_identifier', None),
    ({'doi': '10.5555/other'}, 'possible', 'identifiers'),
    ({'year': '2023'}, 'ambiguous', 'year'),
    ({'author': 'Someone'}, 'ambiguous', 'authors'),
    ({'item_type': 'preprint'}, 'ambiguous', 'item_type'),
    ({'doi': '', 'title': 'Unrelated research'}, 'none', None),
])
def test_identifiers_require_compatible_metadata(import_case, change, relationship, conflict):
    w = import_case
    result = w.api.match_duplicates(w.proposal, w.evidence.source, (parent(**change),))
    assert result.relationship == relationship
    assert result.scope == 'metadata_candidates'
    if conflict:
        assert conflict in result.matches[0].conflicting_fields
    if relationship in ('possible', 'ambiguous', 'none'):
        assert result.parent_key is None


def test_multiple_compatible_parents_are_ambiguous(import_case):
    w = import_case
    result = w.api.match_duplicates(w.proposal, w.evidence.source, (parent(), parent('PARENT02')))
    assert result.relationship == 'ambiguous' and result.parent_key is None
    assert {m.parent_key for m in result.matches} == {'PARENT01', 'PARENT02'}


def test_equal_pdf_hash_is_exact_and_conflicting_metadata_still_blocks(import_case):
    from paper_reader.ingest.contracts import AttachmentEvidence
    w = import_case
    evidence = AttachmentEvidence(attachment_key='ATTACH01', parent_key='PARENT01', source=w.evidence.source)
    result = w.api.match_duplicates(w.proposal, w.evidence.source, (parent(),), attachments=(evidence,))
    assert result.relationship == 'exact_attachment' and result.parent_key == 'PARENT01'
    conflict = w.api.match_duplicates(w.proposal, w.evidence.source, (parent(year='2020'),), attachments=(evidence,))
    assert conflict.relationship == 'ambiguous' and conflict.parent_key is None


def test_no_doi_same_title_is_only_possible(import_case):
    w = import_case
    proposal = w.proposal.model_copy(update={'identifiers': ()})
    result = w.api.match_duplicates(proposal, w.evidence.source, (parent(doi=''),))
    assert result.relationship == 'possible' and result.parent_key is None
