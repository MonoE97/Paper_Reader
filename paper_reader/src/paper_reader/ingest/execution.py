"""Import bindings and observations; the operations executor owns every send."""
from dataclasses import dataclass
import json
from pathlib import Path

from pydantic import TypeAdapter

from paper_reader.analysis.contracts import PaperMetadata
from paper_reader.ingest.contracts import IdentificationEvidence, IdentificationProposal, AttachmentEvidence
from paper_reader.ingest.duplicates import match_duplicates
from paper_reader.ingest.planner import _metadata_blockers, _source_current, validate_import_observations
from paper_reader.official.client import _item, create_data
from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.models import ParentCreate, AttachmentCreate, ItemSnapshot
from paper_reader.operations.contracts import (
    AddToCollections, CreateParent, CreateAttachment, UploadAttachment, ItemPrecondition,
    PredecessorPrecondition, ParentPayload, WorkflowError,
)
from paper_reader.operations.execution_state import history
from paper_reader.storage import canonical_json_bytes


@dataclass(frozen=True)
class ImportBinding:
    operation: CreateParent | AddToCollections | CreateAttachment | UploadAttachment


def bind_import(plan, store):
    """Check the stored proposal and exact executable payloads without a live API."""
    detail = plan.import_details
    proposal = store.load(detail.proposal)
    if (not isinstance(proposal, IdentificationProposal) or proposal.source != detail.source
            or proposal.run_id != plan.run_id or proposal.collections != detail.collections):
        raise WorkflowError('verification_failed', 'import proposal binding mismatch')
    title_ref = next((e.source for e in proposal.evidence if e.field == 'title' and e.locator != 'external'), None)
    if title_ref is None:
        if not plan.operations:
            return ()
        raise WorkflowError('metadata_unresolved', 'import has no PDF title evidence')
    evidence = IdentificationEvidence.model_validate_json(store.read_bytes(title_ref))
    if evidence.source != detail.source or _metadata_blockers(proposal, evidence, title_ref, store):
        if not plan.operations:
            return ()
        raise WorkflowError('metadata_unresolved', 'import proposal is not evidence-bound')
    inventory = TypeAdapter(tuple[ItemSnapshot, ...]).validate_json(store.read_bytes(detail.inventory_snapshot))
    attachments = TypeAdapter(tuple[AttachmentEvidence, ...]).validate_json(store.read_bytes(detail.attachment_snapshot))
    if match_duplicates(proposal, detail.source, inventory, attachments=attachments) != detail.duplicates:
        raise WorkflowError('verification_failed', 'duplicate evidence mismatch')
    if not plan.operations:
        return ()
    parent = next((i for i in inventory if i.key == detail.selected_parent_key), None)
    expected_types = ['create_parent'] if parent is None else (
        ['add_to_collections'] if set(c.key for c in detail.collections) - set(parent.data.collections) else [])
    expected_types += ['create_attachment', 'upload_attachment']
    if [o.type for o in plan.operations] != expected_types:
        raise WorkflowError('verification_failed', 'unexpected import operation graph')
    parent_key = parent.key if parent else plan.operations[0].target_key
    filename = proposal.attachment_filename or Path(detail.source.resolved_path).name
    if detail.filename != filename:
        raise WorkflowError('verification_failed', 'attachment filename differs from proposal')
    for op in plan.operations:
        valid = op.subject_id == plan.run_id and op.subject_title == proposal.title
        if isinstance(op, CreateParent):
            valid &= op.before is None and not op.depends_on and op.payload == ParentPayload(
                item_type=proposal.item_type, metadata=PaperMetadata(title=proposal.title,
                    authors=proposal.authors, year=proposal.year, identifiers=proposal.identifiers),
                collections=tuple(c.key for c in detail.collections))
        elif isinstance(op, AddToCollections):
            valid &= (parent is not None and op.target_key == parent_key
                and set(op.payload.collections) == set(parent.data.collections) | {c.key for c in detail.collections})
        elif isinstance(op, CreateAttachment):
            valid &= (op.payload.source == detail.source and op.payload.filename == filename
                and op.payload.title == filename and op.payload.parent_key == parent_key)
        elif isinstance(op, UploadAttachment):
            previous = plan.operations[-2]
            valid &= (op.payload.source == detail.source and op.payload.filename == filename
                and op.target_key == previous.target_key and op.depends_on == (previous.operation_id,)
                and op.before == PredecessorPrecondition(kind='predecessor', operation_id=previous.operation_id))
        else:
            valid = False
        if isinstance(op.before, ItemPrecondition):
            valid &= (parent is not None and op.before.key == parent.key and op.before.version == parent.version
                      and store.read_bytes(op.before.snapshot) == canonical_json_bytes(parent.raw_json))
        if not valid:
            raise WorkflowError('verification_failed', 'import operation differs from approved identification')
    return tuple(ImportBinding(o) for o in plan.operations)


def create_request(op):
    if isinstance(op, CreateParent):
        metadata = op.payload.metadata
        labels = {'doi': 'DOI', 'isbn': 'ISBN', 'arxiv': 'arXiv', 'pmid': 'PMID'}
        return ParentCreate(key=op.target_key, item_type=op.payload.item_type,
            title=metadata.title, authors=metadata.authors, date=str(metadata.year) if metadata.year is not None else '',
            extra='\n'.join(f'{labels[i.kind]}: {i.value}' for i in metadata.identifiers),
            collections=op.payload.collections)
    return AttachmentCreate(key=op.target_key, parent_key=op.payload.parent_key,
                            title=op.payload.title, filename=op.payload.filename)


def verified_item(plan, operation_id, store):
    event = next((e for e in history(plan, operation_id, store) if e.state == 'verified'), None)
    if event is None:
        raise WorkflowError('dependency_excluded', 'predecessor has not been verified')
    return _item(json.loads(store.read_bytes(event.readback))['item'])


def expected_before(plan, op, store):
    if isinstance(op.before, PredecessorPrecondition):
        return verified_item(plan, op.before.operation_id, store)
    if isinstance(op.before, ItemPrecondition):
        expected = _item(json.loads(store.read_bytes(op.before.snapshot)))
        # A verified collection patch in this same plan owns its resulting version.
        for previous in plan.operations:
            if previous.operation_id == op.operation_id:
                break
            if previous.target_key == expected.key and isinstance(previous, AddToCollections):
                if any(e.state == 'verified' for e in history(plan, previous.operation_id, store)):
                    expected = verified_item(plan, previous.operation_id, store)
        return expected
    return None


def fresh_import(plan, op, gateway, store):
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'import belongs to another instance')
    detail = plan.import_details
    _source_current(detail.source)
    version = gateway.get_library_version()
    created = {o.target_key for o in plan.operations if isinstance(o, (CreateParent, CreateAttachment))
               and any(e.state == 'verified' for e in history(plan, o.operation_id, store))}
    validate_import_observations(plan, gateway=gateway, store=store, excluded_keys=created)
    before = expected_before(plan, op, store)
    if before is not None:
        _require_same_item(gateway.get_item(before.key), before)
    # Uploads still depend on the approved paper, not only the empty attachment.
    attachment = (next(o for o in plan.operations if isinstance(o, CreateAttachment)
                       and o.target_key == op.target_key) if isinstance(op, UploadAttachment)
                  else op if isinstance(op, CreateAttachment) else None)
    if attachment is not None:
        parent = expected_before(plan, attachment, store)
        _require_same_item(gateway.get_item(parent.key), parent)
        if parent.key in created:
            if any(c.key not in created and c.data.item_type == 'attachment'
                   and c.data.content_type == 'application/pdf' for c in gateway.get_children(parent.key)):
                raise WorkflowError('plan_stale', 'another PDF was attached outside this plan')
    if isinstance(op, (CreateParent, CreateAttachment)) and gateway.item_exists(op.target_key):
        raise WorkflowError('plan_stale', 'preallocated key is occupied')
    _source_current(detail.source)
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during import preflight')
    return version


def _require_same_item(live, expected):
    # Zotero's wrapper meta.numChildren can change after our child creation.
    # Identity, local version and all stored item data must still match.
    if (live.key, live.version, live.raw_json['data']) != (expected.key, expected.version, expected.raw_json['data']):
        raise WorkflowError('plan_stale', 'approved predecessor or existing item changed')


def _fields_equal(data, expected):
    for key, value in expected.items():
        if key in ('key', 'version', 'dateModified'):
            continue
        actual = data.get(key, '' if isinstance(value, str) else None)
        if key == 'collections':
            if set(actual or ()) != set(value):
                return False
        elif actual != value:
            return False
    return not data.get('deleted', False)


def observe_import(plan, op, gateway, store):
    """Return full checks and an item snapshot; never authorize recovery by HTTP alone."""
    before_version = gateway.get_library_version()
    if not gateway.item_exists(op.target_key):
        proof = {'matches': [], 'checks': [], 'item': None}
        state, code = 'uncertain', 'write_uncertain'
    else:
        item = gateway.get_item(op.target_key)
        data = item.raw_json['data']
        expected = expected_before(plan, op, store)
        checks = []
        if isinstance(op, (CreateParent, CreateAttachment)):
            checks.append(_fields_equal(data, create_data(create_request(op))))
        elif isinstance(op, AddToCollections):
            checks.append(_fields_equal(data, {**expected.raw_json['data'], 'collections': list(op.payload.collections)}))
        else:
            checks.append(_fields_equal(data, {k: v for k, v in expected.raw_json['data'].items()
                                               if k not in ('md5', 'mtime')}))
            try:
                pdf = fingerprint_pdf(gateway.get_file_path(op.target_key))
            except WorkflowError as exc:
                if exc.code != 'attachment_unavailable':
                    raise
                pdf = None
            if pdf is not None:
                checks.append((pdf.size_bytes, pdf.sha256) == (op.payload.source.size_bytes, op.payload.source.sha256))
                checks.append(item.data.filename == op.payload.filename)
            elif item == expected and not data.get('md5'):
                # Read-only absence is useful evidence, but registration uncertainty
                # still requires a new human confirmation before another attempt.
                proof = {'matches': [], 'checks': checks, 'item': item.raw_json, 'file_absent': True}
                state, code = 'uncertain', 'write_uncertain'
                return _stable_observation(gateway, before_version, proof, state, code)
            elif all(checks) and data.get('md5'):
                proof = {'matches': [item.key], 'checks': checks, 'item': item.raw_json, 'file_absent': True}
                return _stable_observation(gateway, before_version, proof, 'uncertain', 'attachment_unavailable')
            else:
                checks.append(False)
        proof = {'matches': [item.key], 'checks': checks, 'item': item.raw_json}
        state, code = ('verified', None) if all(checks) else ('blocked', 'verification_failed')
    return _stable_observation(gateway, before_version, proof, state, code)


def _stable_observation(gateway, version, proof, state, code):
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during import readback')
    return {**proof, 'library_version': version}, state, code
