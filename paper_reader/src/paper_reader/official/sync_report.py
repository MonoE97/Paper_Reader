"""Read-only local duplicate scans and independently verified peer observations."""
from itertools import combinations
import re

from paper_reader.ingest.contracts import AttachmentEvidence
from paper_reader.ingest.duplicates import assess_candidate, item_metadata, normalized_identifier, normalized_text
from paper_reader.note_hash import note_html_sha256
from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.models import RemoteObservation, RemoteOperationObservation, SyncReport, ZoteroGateway
from paper_reader.operations.contracts import ChangePlan, DuplicateMatch, DuplicateReport, ExecutionReport, WorkflowError
from paper_reader.operations.store import RunStore, artifact_ref
from paper_reader.resource_policy import V2_RESOURCE_POLICY as LIMITS
from paper_reader.storage import canonical_json_bytes, new_random_id, rfc3339_utc


def _stable(gateway, context, version):
    if gateway.context != context:
        raise WorkflowError('instance_changed', 'instance changed during observation')
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during observation')


def _candidate_pairs(inventory):
    """Index metadata first; never expand an unbounded all-pairs scan."""
    groups = {}
    for item in inventory:
        metadata = item_metadata(item)
        keys = {normalized_identifier(i) for i in metadata.identifiers}
        keys |= {('arxiv-base', re.sub(r'v\d+$', '', v)) for k, v in keys if k == 'arxiv'}
        title = normalized_text(item.data.title)
        if title:
            keys.add(('title', title))
        for key in keys:
            groups.setdefault(key, []).append(item.key)
    pairs = set()
    for group in groups.values():
        for pair in combinations(sorted(group), 2):
            pairs.add(pair)
            if len(pairs) > LIMITS.artifact_tree_max_members:
                raise WorkflowError('resource_limit', 'duplicate candidate pairs exceed member limit')
    return tuple(sorted(pairs))


def scan_duplicates(*, gateway: ZoteroGateway, store: RunStore) -> DuplicateReport:
    context, version = gateway.context, gateway.get_library_version()
    inventory = tuple(i for i in gateway.search_items('') if i.data.item_type not in ('note', 'attachment')
                      and not i.data.parent_key and not i.raw_json['data'].get('deleted'))
    if len(inventory) > LIMITS.artifact_tree_max_members or len({i.key for i in inventory}) != len(inventory):
        raise WorkflowError('resource_limit', 'duplicate inventory exceeds limits or has repeated keys')
    pairs = _candidate_pairs(inventory)
    candidates = {key for pair in pairs for key in pair}
    attachments, byte_count = [], 0
    for item in sorted(inventory, key=lambda i: i.key):
        if item.key not in candidates:
            continue
        for child in gateway.get_children(item.key):
            if (child.data.item_type != 'attachment' or child.data.content_type != 'application/pdf'
                    or child.raw_json['data'].get('deleted')):
                continue
            if child.data.parent_key != item.key:
                raise WorkflowError('verification_failed', 'candidate attachment belongs to another parent')
            if len(attachments) >= LIMITS.artifact_tree_max_members:
                raise WorkflowError('resource_limit', 'candidate attachments exceed member limit')
            try:
                pdf = fingerprint_pdf(gateway.get_file_path(child.key))
            except WorkflowError as exc:
                if exc.code != 'attachment_unavailable':
                    raise
                pdf = None
            byte_count += pdf.size_bytes if pdf is not None else 0
            if byte_count > LIMITS.run_max_bytes:
                raise WorkflowError('resource_limit', 'candidate PDF bytes exceed scan limit')
            attachments.append(AttachmentEvidence(attachment_key=child.key, parent_key=item.key, source=pdf))
    _stable(gateway, context, version)
    inventory_ref = store.publish_bytes(canonical_json_bytes([i.model_dump(mode='json') for i in inventory]), role='source')
    attachment_ref = store.publish_bytes(canonical_json_bytes([a.model_dump(mode='json') for a in attachments]), role='source')
    by_key = {i.key: i for i in inventory}
    pdfs = {}
    for a in attachments:
        if a.source is not None:
            pdfs.setdefault(a.parent_key, {}).setdefault((a.source.sha256, a.source.size_bytes), []).append(a.attachment_key)
    matches = []
    for left, right in pairs:
        shared_pdf = pdfs.get(left, {}).keys() & pdfs.get(right, {}).keys()
        exact = tuple(k for digest in sorted(shared_pdf) for key in (left, right) for k in pdfs[key][digest])
        match = assess_candidate(item_metadata(by_key[left]), by_key[right], exact_attachments=exact)
        relationship = ('conflict' if match.conflicting_fields else 'identical_pdf' if exact else
                        'compatible_identifier' if match.relationship == 'compatible_identifier' else 'possible_duplicate')
        matches.append(DuplicateMatch(item_keys=(left, right), relationship=relationship,
            evidence=(inventory_ref, attachment_ref), reasons=match.reasons, conflicting_fields=match.conflicting_fields))
    report = DuplicateReport(schema_version='paper_reader.duplicate-report.v3', report_id=new_random_id('duplicates'),
        context=context, created_at=rfc3339_utc(), matches=tuple(matches), scope='local_instance',
        inventory_snapshot=inventory_ref, attachment_snapshot=attachment_ref,
        unavailable_attachment_keys=tuple(sorted(a.attachment_key for a in attachments if a.source is None)))
    store.publish(report)
    return report


def _reading_source(binding, gateway):
    """A reading observation needs the selected paper and primary PDF too."""
    from paper_reader.ingest.execution import _fields_equal
    expected = (binding.candidate.target.parent, binding.attachment)
    items = [gateway.get_item(item.key) for item in expected if gateway.item_exists(item.key)]
    proof = {'items': [i.raw_json for i in items], 'checks': [], 'missing_keys':
             [e.key for e in expected if e.key not in {i.key for i in items}]}
    proof['checks'] = [_fields_equal(i.raw_json['data'], e.raw_json['data'])
                       for e in expected for i in items if i.key == e.key]
    if not all(proof['checks']):
        return proof, 'conflict'
    if proof['missing_keys']:
        return proof, 'missing'
    try:
        pdf = fingerprint_pdf(gateway.get_file_path(binding.attachment.key))
    except WorkflowError as exc:
        if exc.code != 'attachment_unavailable':
            raise
        return {**proof, 'file_absent': True}, 'unavailable'
    source = binding.candidate.source
    proof.update(pdf_sha256=pdf.sha256, pdf_size_bytes=pdf.size_bytes)
    proof['checks'].append((pdf.size_bytes, pdf.sha256) == (source.size_bytes, source.sha256))
    return proof, 'verified' if all(proof['checks']) else 'conflict'


def observe_remote(local: ExecutionReport, *, gateway: ZoteroGateway, store: RunStore) -> RemoteObservation:
    """Caller supplies original immutable run artifacts and the peer's local gateway.

    Full verification is reused; no credential request, journal event or sync trigger.
    """
    from paper_reader.ingest.execution import read_import_content
    from paper_reader.operations.execution_state import NoteBinding, validate_plan
    from paper_reader.operations.reconcile import observe_note
    local = ExecutionReport.model_validate_json(canonical_json_bytes(local))
    if store.load(artifact_ref(local)) != local or local.local_status != 'local_verified':
        raise WorkflowError('verification_failed', 'a persisted locally verified result is required')
    context, version = gateway.context, gateway.get_library_version()
    if (context.server_id == local.context.server_id or
            (context.library_type, context.library_id) != (local.context.library_type, local.context.library_id)):
        raise WorkflowError('instance_changed', 'an independent instance of the same library is required')
    plan = store.load(local.plan)
    if not isinstance(plan, ChangePlan) or plan.context != local.context:
        raise WorkflowError('verification_failed', 'local result does not bind its original plan')
    bindings = {b.operation.operation_id: b for b in validate_plan(plan, store)}
    observed = []
    proofs = []
    for result in local.operations:
        binding = bindings[result.operation_id]
        op = binding.operation
        if result.state != 'verified' or result.target_key != op.target_key:
            raise WorkflowError('verification_failed', 'local operation has not been verified')
        if isinstance(binding, NoteBinding):
            source_proof, source_status = _reading_source(binding, gateway)
            if op.payload.parent_key in source_proof['missing_keys']:
                proof, state = {'matches': [], 'checks': []}, 'uncertain'
            else:
                proof, state, _ = observe_note(binding, gateway=gateway)
            note_hash = (note_html_sha256(proof['matches'][0]['data']['note'])
                         if len(proof['matches']) == 1 else None)
            keys = (op.payload.parent_key, binding.attachment.key, op.target_key)
            states = {source_status, 'verified' if state == 'verified' else 'missing' if not proof['matches'] else 'conflict'}
            status = next(s for s in ('conflict', 'unavailable', 'missing', 'verified') if s in states)
            proof = {**proof, 'reading_source': source_proof, 'pdf_sha256': source_proof.get('pdf_sha256')}
        else:
            if not gateway.item_exists(op.target_key):
                proof, status = {'matches': [], 'checks': [], 'item': None}, 'missing'
            else:
                proof = read_import_content(plan, op, gateway.get_item(op.target_key), gateway, store)
                status = 'conflict' if not all(proof['checks']) else 'unavailable' if proof.get('file_absent') else 'verified'
            note_hash = None
            keys = (op.target_key,)
        proofs.append(proof)
        observed.append((op.operation_id, keys, status, proof.get('pdf_sha256'), note_hash))
    _stable(gateway, context, version)
    operations = tuple(RemoteOperationObservation(operation_id=op, item_keys=keys, status=status,
        readback=store.publish_bytes(canonical_json_bytes(proof), role='readback'), pdf_sha256=pdf, note_sha256=note)
        for (op, keys, status, pdf, note), proof in zip(observed, proofs, strict=True))
    return RemoteObservation(context=context, observed_at=rfc3339_utc(),
                             local_result=artifact_ref(local), operations=operations)


def build_sync_report(local: ExecutionReport, remote: RemoteObservation | None = None) -> SyncReport:
    local = ExecutionReport.model_validate_json(canonical_json_bytes(local))
    status, sync_status = 'unknown', 'sync_unobserved'
    ref = artifact_ref(local)
    if remote is not None:
        remote = RemoteObservation.model_validate_json(canonical_json_bytes(remote))
        if (remote.local_result != ref or remote.context.server_id == local.context.server_id or
                (remote.context.library_type, remote.context.library_id) != (local.context.library_type, local.context.library_id)
                or {o.operation_id for o in remote.operations} != {o.operation_id for o in local.operations}
                or len(remote.operations) != len(local.operations) or not remote.operations):
            raise WorkflowError('verification_failed', 'remote evidence belongs to another local result or library')
        targets = {o.operation_id: o.target_key for o in local.operations}
        if any(targets[o.operation_id] not in o.item_keys for o in remote.operations):
            raise WorkflowError('verification_failed', 'remote evidence has different target keys')
        states = {o.status for o in remote.operations}
        status = next(s for s in ('conflict', 'unavailable', 'missing', 'verified') if s in states)
        sync_status = ('conflict_needs_review' if status == 'conflict' else
                       'remote_observed' if status == 'verified' and local.local_status == 'local_verified'
                       else 'sync_unobserved')
    return SyncReport(local_result=ref, local_status=local.local_status, sync_status=sync_status,
                      observation_status=status, remote_observation=remote)
