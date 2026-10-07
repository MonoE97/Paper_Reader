import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from paper_reader.operations.contracts import ChangePlan, WorkflowError
from paper_reader.operations.store import artifact_ref
from paper_reader.storage import canonical_json_bytes
from test_duplicates import parent, attachment


def build(w, proposal=None):
    return w.api.plan_import(w.evidence.source, proposal or w.proposal, gateway=w.gateway, store=w.store)


def approve(w, plan):
    return w.api.approve_plan(plan, selected_operation_ids=tuple(o.operation_id for o in plan.operations),
        expected_plan_sha256=artifact_ref(plan).sha256, confirmation_ref='explicit-test-preview', store=w.store)


def test_new_import_plan_exact_payload_dependency_and_pure_preview(import_case):
    w = import_case
    original = w.path.read_bytes()
    plan = build(w)
    assert [o.type for o in plan.operations] == ['create_parent', 'create_attachment', 'upload_attachment']
    p, a, u = plan.operations
    assert p.payload.metadata.title == 'Ion transport in solids'
    assert p.payload.item_type == 'journalArticle' and p.payload.collections == ('COLLECT1',)
    assert a.payload.filename == u.payload.filename == 'source paper.pdf'
    assert a.payload.parent_key == p.target_key and a.depends_on == (p.operation_id,)
    assert u.target_key == a.target_key and u.depends_on == (a.operation_id,)
    assert plan.import_details.collections[0].full_path == 'Materials / Imaging'
    assert plan.import_details.duplicates.scope == 'metadata_candidates'
    preview = w.api.preview_plan(plan)
    assert preview.import_details == plan.import_details
    approve(w, plan)
    assert w.path.read_bytes() == original and w.gateway.writes == 0
    with pytest.raises(WorkflowError, match='dependency_excluded'):
        w.api.approve_plan(plan, selected_operation_ids=(a.operation_id,),
            expected_plan_sha256=artifact_ref(plan).sha256, confirmation_ref='bad', store=w.store)


@pytest.mark.parametrize('change', [
    {'title': None}, {'item_type': None}, {'collections': ()}, {'conflicts': ('主文 DOI 冲突',)},
])
def test_unresolved_subject_has_no_approvable_operations(import_case, change):
    w = import_case
    plan = build(w, w.proposal.model_copy(update=change))
    assert plan.import_details.status == 'blocked' and plan.import_details.blockers
    assert not plan.operations
    with pytest.raises(ValueError):
        approve(w, plan)
    assert build(w).operations and w.gateway.writes == 0


def test_reference_doi_cannot_become_paper_identifier(import_case):
    from paper_reader.analysis.contracts import PaperIdentifier
    w = import_case
    evidence = tuple(e.model_copy(update={'locator': 'page:2', 'quote': 'DOI: 10.5555/cited'})
        if e.field == 'identifiers' else e for e in w.proposal.evidence)
    proposal = w.proposal.model_copy(update={'identifiers': (PaperIdentifier(kind='doi', value='10.5555/cited'),),
                                            'evidence': evidence})
    plan = build(w, proposal)
    assert plan.import_details.status == 'blocked' and not plan.operations
    assert any('DOI' in b or 'doi' in b for b in plan.import_details.blockers)


def test_missing_doi_is_allowed_but_forged_title_quote_is_not(import_case):
    w = import_case
    assert build(w, w.proposal.model_copy(update={'identifiers': (), 'missing_fields': ('doi',)})).operations
    forged = w.proposal.model_copy(update={'title': 'Made up paper title'})
    assert not build(w, forged).operations


def test_existing_parent_missing_attachment_preserves_collections(import_case):
    w = import_case
    w.gateway.inventory = (parent(collections=('OLD00001',)),)
    plan = build(w)
    assert [o.type for o in plan.operations] == ['add_to_collections', 'create_attachment', 'upload_attachment']
    assert set(plan.operations[0].payload.collections) == {'OLD00001', 'COLLECT1'}
    assert plan.operations[1].payload.parent_key == 'PARENT01'
    assert plan.operations[0].before.key == 'PARENT01'
    assert w.gateway.writes == 0


def test_identical_attachment_is_skipped_and_never_reuploaded(import_case):
    w = import_case
    w.gateway.inventory = (parent(collections=('COLLECT1',)),)
    w.gateway.children = {'PARENT01': (attachment(),)}
    w.gateway.files = {'ATTACH01': w.path}
    plan = build(w)
    assert plan.import_details.status == 'skipped' and not plan.operations
    assert plan.import_details.duplicates.relationship == 'exact_attachment'
    assert w.gateway.writes == 0


def test_unavailable_candidate_attachment_blocks_without_claiming_absence(import_case):
    w = import_case
    w.gateway.inventory = (parent(),)
    w.gateway.children = {'PARENT01': (attachment(),)}
    plan = build(w)
    assert not plan.operations and plan.import_details.duplicates.unavailable_attachment_keys == ('ATTACH01',)


@pytest.mark.parametrize('field,value', [('key', 'UNKNOWN1'), ('full_path', 'Imaging')])
def test_collection_key_and_full_path_must_match_current_tree(import_case, field, value):
    w = import_case
    chosen = w.proposal.collections[0].model_copy(update={field: value})
    plan = build(w, w.proposal.model_copy(update={'collections': (chosen,)}))
    assert not plan.operations and plan.import_details.status == 'blocked'


@pytest.mark.parametrize('drift', ['source', 'collection', 'parent', 'instance', 'target'])
def test_plan_freshness_rejects_changed_source_or_library(import_case, drift):
    w = import_case
    w.gateway.inventory = (parent(),)
    plan = build(w)
    if drift == 'source':
        w.path.write_bytes(w.path.read_bytes() + b'changed')
    elif drift == 'collection':
        w.gateway.collections = tuple(c.model_copy(update={'name': 'Renamed'}) if c.key == 'ROOT0001' else c
                                      for c in w.gateway.collections)
    elif drift == 'parent':
        w.gateway.inventory = (parent(year='2025'),)
    elif drift == 'instance':
        w.gateway.context = w.gateway.context.model_copy(update={'server_id': 'different'})
    else:
        w.gateway.item_exists = lambda key: True
    with pytest.raises(WorkflowError):
        w.api.validate_import_plan(plan, gateway=w.gateway, store=w.store)
    assert w.gateway.writes == 0


def test_unsafe_filename_is_blocked_with_explicit_safe_suggestion(import_case):
    w = import_case
    path = w.path.parent / 'unsafe:paper.pdf'
    path.write_bytes(w.path.read_bytes())
    evidence = w.api.inspect_pdf(path)
    ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
    proposal = w.proposal.model_copy(update={'source': evidence.source, 'evidence': tuple(
        e.model_copy(update={'source': ref}) for e in w.proposal.evidence)})
    plan = w.api.plan_import(evidence.source, proposal, gateway=w.gateway, store=w.store)
    assert not plan.operations and plan.import_details.suggested_filename == 'unsafe_paper.pdf'
    assert path.name == 'unsafe:paper.pdf' and path.exists()


def test_import_cli_and_preview_keep_one_json_and_execution_requires_approval(import_case, monkeypatch):
    from paper_reader import official_cli as cli
    from conftest import Credentials
    w = import_case
    ref = w.store.publish(w.proposal)
    monkeypatch.setattr(cli, 'connect', lambda *a, **kw: w.gateway.context)
    monkeypatch.setattr(cli, 'OfficialZoteroClient', lambda *a, **kw: w.gateway)
    roots = ['--run-root', str(w.store.root), '--coordination-root', str(w.store.coordination_root)]
    result = CliRunner().invoke(cli.app, ['plan', 'import', *roots, '--source', str(w.path), '--proposal', ref.path])
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    plan = ChangePlan.model_validate_json(json.dumps(value['data']))
    monkeypatch.setattr(cli, 'connect', lambda *a, **kw: pytest.fail('preview is pure'))
    result = CliRunner().invoke(cli.app, ['plan', 'preview', *roots, '--plan', artifact_ref(plan).path])
    assert result.exit_code == 0 and json.loads(result.stdout)['data']['import_details']
    credentials = Credentials()
    with pytest.raises(WorkflowError):
        w.api.apply_plan(plan, None, gateway=w.gateway, credentials=credentials, store=w.store)
    assert credentials.calls == w.gateway.writes == 0


def test_explicit_parent_choice_resolves_same_title_without_identifier(import_case):
    from paper_reader.official.models import ZoteroSelection
    w = import_case
    first, second = parent(doi=''), parent('PARENT02', doi='')
    w.gateway.inventory = (first, second)
    raw = w.store.publish_bytes(canonical_json_bytes(second.raw_json), role='source')
    selection = ZoteroSelection(context=w.gateway.context, item_key=second.key, parent=second, parent_snapshot=raw)
    proposal = w.proposal.model_copy(update={'identifiers': (), 'selected_parent': selection})
    plan = build(w, proposal)
    assert plan.operations and all(o.type != 'create_parent' for o in plan.operations)
    assert next(o for o in plan.operations if o.type == 'create_attachment').payload.parent_key == 'PARENT02'
    w.api.validate_import_plan(plan, gateway=w.gateway, store=w.store)


def test_explicit_parent_choice_never_overrides_metadata_conflict(import_case):
    from paper_reader.official.models import ZoteroSelection
    w = import_case
    chosen = parent(year='2020')
    w.gateway.inventory = (chosen,)
    ref = w.store.publish_bytes(canonical_json_bytes(chosen.raw_json), role='source')
    proposal = w.proposal.model_copy(update={'selected_parent': ZoteroSelection(context=w.gateway.context,
        item_key=chosen.key, parent=chosen, parent_snapshot=ref)})
    assert not build(w, proposal).operations


def test_confirmed_safe_alternative_filename_does_not_rename_source(import_case):
    w = import_case
    path = w.path.parent / 'unsafe:paper.pdf'
    path.write_bytes(w.path.read_bytes())
    evidence = w.api.inspect_pdf(path)
    ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
    proposal = w.proposal.model_copy(update={'source': evidence.source, 'attachment_filename': 'unsafe_paper.pdf',
        'evidence': tuple(e.model_copy(update={'source': ref}) for e in w.proposal.evidence)})
    plan = w.api.plan_import(evidence.source, proposal, gateway=w.gateway, store=w.store)
    assert plan.operations and plan.import_details.filename == 'unsafe_paper.pdf'
    assert next(o for o in plan.operations if o.type == 'create_attachment').payload.filename == 'unsafe_paper.pdf'
    assert path.name == 'unsafe:paper.pdf' and path.read_bytes() == w.path.read_bytes()


def test_publisher_record_is_bound_to_pdf_and_does_not_replace_pdf_title(import_case):
    w = import_case
    external = {'pdf_source': w.evidence.source.model_dump(mode='json'), 'url': 'https://publisher.example/article',
        'text': 'Publication year: 2024; article type: Journal Article', 'pdf_comparison': '文章题名及作者与此 PDF 相符。'}
    ref = w.store.publish_bytes(canonical_json_bytes(external), role='source')
    evidence = tuple(e.model_copy(update={'source': ref, 'locator': 'external', 'quote': 'Publication year: 2024'})
                     if e.field == 'year' else e for e in w.proposal.evidence)
    assert build(w, w.proposal.model_copy(update={'evidence': evidence})).operations
    evidence = tuple(e.model_copy(update={'source': ref, 'locator': 'external', 'quote': external['text']})
                     if e.field == 'title' else e for e in evidence)
    assert not build(w, w.proposal.model_copy(update={'evidence': evidence})).operations


def test_main_text_doi_conflict_blocks_without_selecting_first(import_case):
    import fitz
    from paper_reader.analysis.contracts import PaperIdentifier
    w = import_case
    path = w.path.parent / 'conflict.pdf'
    with fitz.open(w.path) as pdf:
        pdf[0].insert_text((50, 200), 'DOI: 10.2222/different')
        pdf.save(path)
    evidence = w.api.inspect_pdf(path)
    ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
    proposal = w.proposal.model_copy(update={'source': evidence.source,
        'evidence': tuple(e.model_copy(update={'source': ref}) for e in w.proposal.evidence)})
    second = PaperIdentifier(kind='doi', value='10.2222/different')
    extra = next(e for e in proposal.evidence if e.field == 'identifiers').model_copy(
        update={'identifier': second, 'quote': 'DOI: 10.2222/different'})
    proposal = proposal.model_copy(update={'identifiers': (*proposal.identifiers, second),
                                           'evidence': (*proposal.evidence, extra)})
    plan = w.api.plan_import(evidence.source, proposal, gateway=w.gateway, store=w.store)
    assert not plan.operations and any('DOI' in b for b in plan.import_details.blockers)


def test_planning_stale_source_rejected_before_library_calls(import_case):
    w = import_case
    w.path.write_bytes(w.path.read_bytes() + b'changed')
    with pytest.raises(WorkflowError, match='source_changed'):
        build(w)
    assert not w.gateway.calls


def test_only_metadata_candidates_have_attachment_files_read(import_case):
    w = import_case
    w.gateway.inventory = (parent(), parent('OTHER001', title='Unrelated', doi='10.9999/other'))
    w.gateway.children = {'PARENT01': (attachment(),), 'OTHER001': (attachment('OTHER001'),)}
    w.gateway.files = {'ATTACH01': w.path}
    assert build(w).import_details.status == 'skipped'
    assert ('children', 'OTHER001') not in w.gateway.calls


@pytest.mark.parametrize('relation', ['citation', 'unresolved'])
def test_first_page_citation_or_unresolved_doi_is_not_paper_identity(import_case, relation):
    import fitz
    from paper_reader.analysis.contracts import PaperIdentifier
    w = import_case
    path = w.path.parent / 'citation.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), 'Ion transport in solids\nAlice Researcher\n2024\nJournal Article\nIntroduction\nPrior work: DOI: 10.5555/cited')
        pdf.save(path)
    evidence = w.api.inspect_pdf(path)
    ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
    identifier = PaperIdentifier(kind='doi', value='10.5555/cited')
    fields = tuple(e.model_copy(update={'source': ref, **({'quote': 'Prior work: DOI: 10.5555/cited',
        'identifier': identifier, 'identifier_relation': relation} if e.field == 'identifiers' else {})})
        for e in w.proposal.evidence)
    proposal = w.proposal.model_copy(update={'source': evidence.source, 'evidence': fields, 'identifiers': (identifier,)})
    plan = w.api.plan_import(evidence.source, proposal, gateway=w.gateway, store=w.store)
    assert plan.import_details.status == 'blocked' and not plan.operations


def test_own_identifier_after_repository_cover_is_supported(import_case):
    import fitz
    w = import_case
    path = w.path.parent / 'cover.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), 'Repository cover sheet')
        page = pdf.new_page()
        page.insert_text((50, 50), 'Ion transport in solids\nAlice Researcher\n2024\nJournal Article\nDOI: 10.1234/ions')
        pdf.save(path)
    evidence = w.api.inspect_pdf(path)
    ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
    fields = tuple(e.model_copy(update={'source': ref, 'locator': 'page:2', **({
        'identifier': w.proposal.identifiers[0], 'identifier_relation': 'self'} if e.field == 'identifiers' else {})})
        for e in w.proposal.evidence)
    proposal = w.proposal.model_copy(update={'source': evidence.source, 'evidence': fields})
    assert w.api.plan_import(evidence.source, proposal, gateway=w.gateway, store=w.store).operations


def test_other_first_page_doi_does_not_conflict_with_explicit_own_identifier(import_case):
    import fitz
    w = import_case
    path = w.path.parent / 'cites.pdf'
    with fitz.open(w.path) as pdf:
        pdf[0].insert_text((50, 200), 'Prior work: DOI: 10.2222/different')
        pdf.save(path)
    evidence = w.api.inspect_pdf(path)
    ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
    fields = tuple(e.model_copy(update={'source': ref, **({'identifier': w.proposal.identifiers[0],
        'identifier_relation': 'self'} if e.field == 'identifiers' else {})}) for e in w.proposal.evidence)
    proposal = w.proposal.model_copy(update={'source': evidence.source, 'evidence': fields})
    assert w.api.plan_import(evidence.source, proposal, gateway=w.gateway, store=w.store).operations


def test_identifier_attribution_requires_exact_value_and_unique_occurrence(import_case):
    from paper_reader.analysis.contracts import PaperIdentifier
    w = import_case
    identifier = PaperIdentifier(kind='doi', value='10.9999/not-this-paper')
    fields = tuple(e.model_copy(update={'identifier': identifier, 'identifier_relation': 'self'})
                   if e.field == 'identifiers' else e for e in w.proposal.evidence)
    assert not build(w, w.proposal.model_copy(update={'evidence': fields})).operations


def test_two_identifier_values_in_one_self_quote_remain_unresolved(import_case):
    import fitz
    w = import_case
    path = w.path.parent / 'two-values.pdf'
    quote = 'DOI: 10.1234/ions; related DOI: 10.2222/different'
    with fitz.open(w.path) as pdf:
        pdf[0].insert_text((50, 200), quote)
        pdf.save(path)
    evidence = w.api.inspect_pdf(path)
    ref = w.store.publish_bytes(canonical_json_bytes(evidence), role='source')
    fields = tuple(e.model_copy(update={'source': ref, **({'quote': quote} if e.field == 'identifiers' else {})})
                   for e in w.proposal.evidence)
    proposal = w.proposal.model_copy(update={'source': evidence.source, 'evidence': fields})
    assert not w.api.plan_import(evidence.source, proposal, gateway=w.gateway, store=w.store).operations


def test_equivalent_doi_declarations_do_not_create_conflict(import_case):
    from paper_reader.analysis.contracts import PaperIdentifier
    w = import_case
    second = next(e for e in w.proposal.evidence if e.field == 'identifiers').model_copy(
        update={'identifier': PaperIdentifier(kind='doi', value='https://doi.org/10.1234/IONS')})
    proposal = w.proposal.model_copy(update={'evidence': (*w.proposal.evidence, second)})
    assert build(w, proposal).operations
