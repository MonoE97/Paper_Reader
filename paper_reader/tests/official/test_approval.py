"""Exact immutable approvals; selection never implies dependency auto-inclusion."""
import pytest
from pydantic import ValidationError

from paper_reader import services
from paper_reader.operations.contracts import ChangePlan, WorkflowError, CreateParent, ParentPayload
from paper_reader.analysis.contracts import PaperMetadata
from paper_reader.storage import canonical_json_bytes, canonical_json_sha256


def approve(plan, store, selected, **overrides):
    return services.approve_plan(plan, selected_operation_ids=selected,
        **({'expected_plan_sha256': canonical_json_sha256(plan), 'confirmation_ref': 'chat:confirmation-1',
            'store': store} | overrides))


@pytest.fixture
def plan(note_candidate, zotero_source, store):
    assert hasattr(services, 'plan_note'), 'T4 plan service is not implemented'
    return services.plan_note(note_candidate, gateway=zotero_source[1], store=store)


def test_exclusion_does_not_expand_selection(plan, store):
    first = plan.operations[0]
    second = first.model_copy(update={'operation_id': 'excluded', 'target_key': 'BCDE2345',
                                    'blockers': ('待确认',)})
    plan = plan.model_copy(update={'operations': (first, second)})
    store.publish(plan)
    approval = approve(plan, store, (first.operation_id,))
    assert approval.selected_operation_ids == (first.operation_id,)
    assert approval.plan == services.preview_plan(plan).plan
    from paper_reader.operations.store import artifact_ref
    assert store.load(artifact_ref(approval)) == approval
    before = store.read_bytes(artifact_ref(approval))
    approve(plan, store, (first.operation_id,), confirmation_ref='chat:confirmation-2')
    assert store.read_bytes(artifact_ref(approval)) == before


def test_missing_parent_dependency_rejects_approval(plan, store):
    parent = CreateParent(type='create_parent', operation_id='parent', subject_id='paper',
        subject_title='New paper', depends_on=(), target_key='BCDE2345', before=None,
        reason='明确的 PDF 身份', blockers=(), payload=ParentPayload(item_type='journalArticle',
        metadata=PaperMetadata(title='New paper', authors=(), year=None, identifiers=()), collections=()))
    note = plan.operations[0].model_copy(update={'depends_on': ('parent',), 'before': None,
        'payload': plan.operations[0].payload.model_copy(update={'parent_key': parent.target_key})})
    plan = plan.model_copy(update={'operations': (parent, note)})
    store.publish(plan)
    with pytest.raises(WorkflowError, match='dependency_excluded'):
        approve(plan, store, (note.operation_id,))
    assert not (store.root / 'approvals').exists()
    assert approve(plan, store, (note.operation_id, 'parent')).selected_operation_ids == ('parent', note.operation_id)


@pytest.mark.parametrize('change', ['reason', 'parent', 'html', 'tags', 'target', 'inputs'])
def test_plan_tampering_invalidates_approval(plan, store, change):
    original_digest = canonical_json_sha256(plan)
    op = plan.operations[0]
    if change == 'reason':
        op = op.model_copy(update={'reason': 'Different reason'})
    elif change == 'target':
        op = op.model_copy(update={'target_key': 'BCDE2345'})
    elif change != 'inputs':
        field = 'parent_key' if change == 'parent' else change
        value = {'parent': 'BCDE2345', 'html': '<h1>Other</h1>', 'tags': ('other',)}[change]
        op = op.model_copy(update={'payload': op.payload.model_copy(update={field: value})})
    altered = plan.model_copy(update={'operations': (op,), **({'inputs': ()} if change == 'inputs' else {})})
    with pytest.raises((WorkflowError, ValidationError)):
        approve(altered, store, (op.operation_id,), expected_plan_sha256=original_digest)
    assert not (store.root / 'approvals').exists()


@pytest.mark.parametrize('selection', [(), ('unknown',), ('DUPLICATE',), ['unknown']])
def test_invalid_selection_is_readonly(plan, store, selection):
    if selection == ('DUPLICATE',):
        selection = (plan.operations[0].operation_id,) * 2
    before = {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}
    with pytest.raises((WorkflowError, ValidationError)):
        approve(plan, store, selection)
    assert before == {p: p.read_bytes() for p in store.root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('reason', ['', ' \n\t'])
def test_empty_reason_and_unknown_fields_rejected(plan, reason):
    payload = plan.model_dump(mode='json')
    payload['operations'][0]['reason'] = reason
    with pytest.raises(ValidationError):
        ChangePlan.model_validate_json(canonical_json_bytes(payload))
    payload['operations'][0]['reason'] = 'valid'
    payload['operations'][0]['override'] = True
    with pytest.raises(ValidationError):
        ChangePlan.model_validate_json(canonical_json_bytes(payload))


@pytest.mark.parametrize('confirmation', ['', '   '])
def test_confirmation_required(plan, store, confirmation):
    with pytest.raises((WorkflowError, ValidationError)):
        approve(plan, store, (plan.operations[0].operation_id,), confirmation_ref=confirmation)
    assert not (store.root / 'approvals').exists()


def test_broken_content_prevents_approval(plan, store):
    (store.root / plan.content[0].path).write_bytes(b'altered')
    with pytest.raises(WorkflowError, match='source_changed'):
        approve(plan, store, (plan.operations[0].operation_id,))
    assert not (store.root / 'approvals').exists()


@pytest.mark.parametrize('kind', ['duplicate', 'unknown_dependency', 'cycle'])
def test_invalid_operation_graph_rejected(plan, kind):
    a = plan.operations[0]
    b = a.model_copy(update={'operation_id': 'second', 'target_key': 'BCDE2345'})
    if kind == 'duplicate':
        b = a
    elif kind == 'unknown_dependency':
        a = a.model_copy(update={'depends_on': ('absent',)})
    else:
        a = a.model_copy(update={'depends_on': ('second',)})
        b = b.model_copy(update={'depends_on': (a.operation_id,)})
    with pytest.raises(ValidationError):
        ChangePlan.model_validate_json(canonical_json_bytes(plan.model_copy(update={'operations': (a, b)})))


def test_child_cannot_hide_dependency_by_omitting_depends_on(plan, store):
    parent = CreateParent(type='create_parent', operation_id='parent', subject_id=plan.run_id,
        subject_title='New paper', depends_on=(), target_key='BCDE2345', before=None,
        reason='已确认新文献', blockers=(), payload=ParentPayload(item_type='journalArticle',
        metadata=PaperMetadata(title='New paper', authors=(), year=None, identifiers=()), collections=()))
    note = plan.operations[0].model_copy(update={'before': None, 'depends_on': (),
        'payload': plan.operations[0].payload.model_copy(update={'parent_key': parent.target_key})})
    with pytest.raises(ValidationError):
        services.preview_plan(plan.model_copy(update={'operations': (parent, note)}))


def test_precondition_must_target_the_note_parent(plan):
    note = plan.operations[0]
    note = note.model_copy(update={'before': note.before.model_copy(update={'key': 'OTHER234'})})
    with pytest.raises(ValidationError):
        services.preview_plan(plan.model_copy(update={'operations': (note,)}))
