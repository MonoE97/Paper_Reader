"""Read-only import planning. Execution of these operations belongs to T7."""
from pathlib import Path
import re
import secrets

from pydantic import TypeAdapter, ValidationError

from paper_reader.analysis.contracts import PaperMetadata, PdfSource
from paper_reader.contracts import ArtifactRef
from paper_reader.ingest.contracts import (
    AttachmentEvidence, CollectionChoice, ExternalMetadataEvidence, FieldEvidence, IdentificationEvidence,
    IdentificationProposal, ImportDetails,
)
from paper_reader.ingest.duplicates import match_duplicates, normalized_identifier, normalized_text
from paper_reader.ingest.identify import DOI_PATTERN, inspect_pdf
from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.models import CollectionSnapshot, ItemSnapshot, ZoteroGateway
from paper_reader.operations.contracts import (
    AddToCollections, AttachmentPayload, ChangePlan, CollectionsPayload, CreateAttachment, CreateParent,
    ItemPrecondition, ParentPayload, PredecessorPrecondition, UploadAttachment, UploadPayload, WorkflowError,
)
from paper_reader.operations.planner import _KEY_ALPHABET
from paper_reader.operations.store import RunStore, artifact_ref
from paper_reader.resource_policy import V2_RESOURCE_POLICY as LIMITS
from paper_reader.storage import canonical_json_bytes, new_random_id, rfc3339_utc


def _source_current(source: PdfSource) -> None:
    if fingerprint_pdf(Path(source.resolved_path)) != source:
        raise WorkflowError('source_changed', 'input PDF changed since identification')


def _attributed_identifier(field: FieldEvidence, text: str, page: int,
                           evidence: IdentificationEvidence) -> tuple[str, str] | None:
    """Bind the proposer's self attribution to one exact quoted identifier occurrence."""
    if field.identifier is None or text.count(field.quote) != 1:
        return None
    kind, value = normalized_identifier(field.identifier)
    if kind != 'doi':
        normalized_quote = normalized_identifier(field.identifier.model_copy(update={'value': field.quote}))[1]
        return (kind, value) if normalized_quote.count(value) == 1 else None
    occurrences = list(DOI_PATTERN.finditer(field.quote))
    if len(occurrences) != 1:
        return None
    match = occurrences[0]
    quoted = field.identifier.model_copy(update={'value': match.group().rstrip('.,;)]}')})
    if normalized_identifier(quoted) != (kind, value):
        return None
    if page:  # External provenance has no PDF offset; its PDF comparison was checked separately.
        start = text.index(field.quote) + match.start()
        candidate = next((c for c in evidence.candidates if c.page == page and c.start == start), None)
        if candidate is None or candidate.region == 'references':
            return None
    return kind, value


def _metadata_blockers(proposal: IdentificationProposal, evidence: IdentificationEvidence,
                       evidence_ref: ArtifactRef, store: RunStore) -> tuple[str, ...]:
    blockers = list(proposal.conflicts)
    if not proposal.title or not proposal.title.strip():
        blockers.append('缺少可核对的文章原题名。')
    if proposal.item_type is None:
        blockers.append('文献类型待确认。')
    pages = {p.page: p.text for p in evidence.pages}
    verified, attributed = {}, set()
    for field in proposal.evidence:
        raw = store.read_bytes(field.source)
        if field.locator == 'external':
            try:
                external = ExternalMetadataEvidence.model_validate_json(raw)
            except ValidationError:
                blockers.append(f'{field.field} 外部来源记录无效。')
                continue
            if (field.field == 'title' or external.pdf_source != evidence.source
                    or not external.pdf_comparison.strip() or not field.explanation.strip()
                    or not field.quote.strip() or field.quote not in external.text):
                blockers.append(f'{field.field} 外部来源缺少与当前 PDF 的有效对照；题名必须来自 PDF。')
                continue
            page, text = 0, external.text
        else:
            locator = re.fullmatch(r'page:([1-9]\d*)', field.locator)
            if field.source != evidence_ref or locator is None or not field.quote.strip():
                blockers.append(f'{field.field} 缺少本 PDF 的页码与原文引用。')
                continue
            page = int(locator[1])
            text = pages.get(page, '')
            if field.quote not in text or not field.explanation.strip():
                blockers.append(f'{field.field} 引用与 PDF 原文不符。')
                continue
        verified.setdefault(field.field, []).append((page, field.quote))
        if field.field == 'identifiers' and field.identifier_relation == 'self':
            identifier = _attributed_identifier(field, text, page, evidence)
            if identifier is None:
                blockers.append('本文标识必须绑定一处明确原文和精确值；不能绑定引用文献 DOI。')
            else:
                attributed.add(identifier)
    values = {'title': (proposal.title,) if proposal.title else (), 'authors': proposal.authors,
              'year': (str(proposal.year),) if proposal.year else ()}
    for field, members in values.items():
        quotes = [normalized_text(q) for _, q in verified.get(field, ())]
        if any(not any(normalized_text(v) in q for q in quotes) for v in members):
            blockers.append(f'{field} 的提议值缺少逐字段原文证据。')
    if proposal.item_type and not verified.get('item_type'):
        blockers.append('文献类型缺少原文证据。')
    own_dois = {value for kind, value in attributed if kind == 'doi'}
    if len(own_dois) > 1:
        blockers.append('多份本文 DOI 声明互相冲突，需确认论文自身标识。')
    for identifier in proposal.identifiers:
        kind, value = normalized_identifier(identifier)
        if (kind, value) not in attributed:
            blockers.append(f'{kind} 无论文自身标识证据；不能使用引用文献的标识。')
    return tuple(dict.fromkeys(blockers))


def _collection_path(key: str, collections: dict[str, CollectionSnapshot]) -> str:
    names, seen = [], set()
    while key:
        if key in seen or key not in collections:
            raise WorkflowError('plan_stale', 'collection tree is incomplete or cyclic')
        seen.add(key)
        item = collections[key]
        names.append(item.name)
        key = item.parent_key
    return ' / '.join(reversed(names))


def _collection_blockers(choices: tuple[CollectionChoice, ...], snapshots: tuple[CollectionSnapshot, ...]) -> tuple[str, ...]:
    if not choices:
        return ('分类待确认；必须选择现有 collection。',)
    collections = {c.key: c for c in snapshots}
    if len(collections) != len(snapshots):
        raise WorkflowError('plan_stale', 'collection keys are not unique')
    blockers = []
    if len({c.key for c in choices}) != len(choices):
        blockers.append('分类选择重复。')
    for choice in choices:
        if choice.key not in collections or _collection_path(choice.key, collections) != choice.full_path:
            blockers.append(f'分类 {choice.key} 的 key/完整路径已变化或不存在。')
        if not choice.reason.strip():
            blockers.append(f'分类 {choice.key} 缺少理由。')
    return tuple(blockers)


def _safe_filename(name: str) -> str | None:
    unsafe = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
    reserved = re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', name.split('.')[0], re.I)
    if not unsafe.search(name) and not name.endswith((' ', '.')) and not reserved and len(name.encode()) <= 240:
        return None
    suggestion = unsafe.sub('_', name).rstrip(' .')
    if reserved:
        suggestion = '_' + suggestion
    if len(suggestion.encode()) > 240:
        suggestion = 'paper.pdf'
    return suggestion or 'paper.pdf'


def _inventory(proposal: IdentificationProposal, source: PdfSource, gateway: ZoteroGateway, *, excluded_keys=()):
    # The read adapter searches title/creator/year; an empty query obtains bounded metadata
    # inventory so DOI fields and Extra are compared locally, not misused as search terms.
    inventory = tuple(i for i in gateway.search_items('') if i.key not in excluded_keys)
    candidates = match_duplicates(proposal, source, inventory)
    keys = {m.parent_key for m in candidates.matches}
    attachments = []
    for item in inventory:
        if item.key not in keys:
            continue
        for child in gateway.get_children(item.key):
            if child.key in excluded_keys:
                continue
            if (child.data.item_type != 'attachment' or child.data.content_type != 'application/pdf'
                    or child.raw_json['data'].get('deleted')):
                continue
            if child.data.parent_key != item.key:
                raise WorkflowError('plan_stale', 'candidate attachment has a different parent')
            if len(attachments) >= LIMITS.artifact_tree_max_members:
                raise WorkflowError('resource_limit', 'candidate attachments exceed member limit')
            try:
                pdf = fingerprint_pdf(gateway.get_file_path(child.key))
            except WorkflowError as exc:
                if exc.code != 'attachment_unavailable':
                    raise
                pdf = None
            attachments.append(AttachmentEvidence(attachment_key=child.key, parent_key=item.key, source=pdf))
    return inventory, tuple(attachments)


def _key(gateway: ZoteroGateway, allocated: set[str]) -> str:
    key = ''.join(secrets.choice(_KEY_ALPHABET) for _ in range(8))
    if key in allocated or gateway.item_exists(key):
        raise WorkflowError('plan_stale', 'preallocated item key is occupied; rebuild the plan')
    allocated.add(key)
    return key


def _operations(proposal: IdentificationProposal, source: PdfSource, parent: ItemSnapshot | None,
                parent_ref: ArtifactRef | None, filename: str, *, gateway: ZoteroGateway):
    if proposal.title is None or proposal.item_type is None:
        raise WorkflowError('metadata_unresolved', 'import requires a title and item type')
    shared = dict(subject_id=proposal.run_id, subject_title=proposal.title, blockers=())
    collections = tuple(c.key for c in proposal.collections)
    allocated, operations = set(), []
    if parent is None:
        parent_key = _key(gateway, allocated)
        create = CreateParent(type='create_parent', operation_id=new_random_id('operation'), **shared,
            target_key=parent_key, depends_on=(), before=None, reason='按已核对的文章元数据创建条目并加入选定分类。',
            payload=ParentPayload(item_type=proposal.item_type, collections=collections,
                metadata=PaperMetadata(title=proposal.title, authors=proposal.authors, year=proposal.year,
                                       identifiers=proposal.identifiers)))
        operations.append(create)
        before = PredecessorPrecondition(kind='predecessor', operation_id=create.operation_id)
        dependencies = (create.operation_id,)
    else:
        parent_key = parent.key
        before = ItemPrecondition(kind='existing', key=parent.key, version=parent.version, snapshot=parent_ref)
        dependencies = ()
        union = tuple(sorted(set(parent.data.collections) | set(collections)))
        if set(union) != set(parent.data.collections):
            operations.append(AddToCollections(type='add_to_collections', operation_id=new_random_id('operation'),
                **shared, target_key=parent.key, depends_on=(), before=before,
                reason='保留已有分类，加入本次明确选定的分类。', payload=CollectionsPayload(collections=union)))
    attachment = CreateAttachment(type='create_attachment', operation_id=new_random_id('operation'), **shared,
        target_key=_key(gateway, allocated), depends_on=dependencies, before=before,
        reason='关联本地 PDF；保留源路径、文件名和内容。', payload=AttachmentPayload(parent_key=parent_key,
            title=filename, filename=filename, source=source, content_type='application/pdf', link_mode='imported_file'))
    operations.append(attachment)
    operations.append(UploadAttachment(type='upload_attachment', operation_id=new_random_id('operation'), **shared,
        target_key=attachment.target_key, depends_on=(attachment.operation_id,),
        before=PredecessorPrecondition(kind='predecessor', operation_id=attachment.operation_id),
        reason='将已批准 PDF bytes 上传为 Zotero 存储附件。', payload=UploadPayload(source=source, filename=filename)))
    return tuple(operations)


def plan_import(source: PdfSource, proposal: IdentificationProposal, *, gateway: ZoteroGateway,
                store: RunStore) -> ChangePlan:
    proposal = IdentificationProposal.model_validate_json(canonical_json_bytes(proposal))
    if proposal.source != source:
        raise WorkflowError('source_changed', 'proposal belongs to another PDF')
    _source_current(source)
    from paper_reader.official.sync_report import scan_duplicates
    duplicate_report = scan_duplicates(gateway=gateway, store=store)
    evidence = inspect_pdf(Path(source.resolved_path))
    evidence_ref = store.publish_bytes(canonical_json_bytes(evidence), role='source')
    blockers = list(_metadata_blockers(proposal, evidence, evidence_ref, store))
    context, version = gateway.context, gateway.get_library_version()
    collections = gateway.get_collections()
    blockers.extend(_collection_blockers(proposal.collections, collections))
    original_filename = Path(source.resolved_path).name
    filename = proposal.attachment_filename or original_filename
    suggestion = _safe_filename(filename)
    if filename != original_filename and _safe_filename(original_filename) is None:
        blockers.append('源文件名可安全使用；首期保留原文件名。')
    if suggestion:
        blockers.append('附件文件名不安全；请确认替代文件名后重新生成计划。')
    inventory, attachments = _inventory(proposal, source, gateway)
    duplicates = match_duplicates(proposal, source, inventory, attachments=attachments)
    parent_key, relationship = duplicates.parent_key, duplicates.relationship
    selection = proposal.selected_parent
    if selection is not None:
        if selection.context != context:
            raise WorkflowError('instance_changed', 'selected parent belongs to another instance/library')
        if (selection.parent not in inventory
                or store.read_bytes(selection.parent_snapshot) != canonical_json_bytes(selection.parent.raw_json)):
            raise WorkflowError('plan_stale', 'selected parent snapshot changed')
        chosen = next((m for m in duplicates.matches if m.parent_key == selection.item_key), None)
        if chosen is None or chosen.conflicting_fields:
            blockers.append('明确选择的 parent 与 PDF 元数据不相容；请先解决冲突。')
        else:
            parent_key, relationship = selection.item_key, chosen.relationship
    if relationship in ('possible', 'ambiguous') and selection is None:
        blockers.append('重复关系或版本待确认；不自动选择 parent。')
    relevant_unavailable = [a for a in attachments if a.source is None
                           and (selection is None or a.parent_key == selection.item_key)]
    if relevant_unavailable:
        blockers.append('候选附件尚不可在本机读取，不能确认是否缺少相同 PDF。')
    proposal_ref = store.publish(proposal)
    collection_ref = store.publish_bytes(canonical_json_bytes([c.model_dump(mode='json') for c in collections]), role='source')
    inventory_ref = store.publish_bytes(canonical_json_bytes([i.model_dump(mode='json') for i in inventory]), role='source')
    attachment_ref = store.publish_bytes(canonical_json_bytes([a.model_dump(mode='json') for a in attachments]), role='source')
    inputs = [proposal_ref, evidence_ref, *(e.source for e in proposal.evidence), collection_ref, inventory_ref,
              attachment_ref, artifact_ref(duplicate_report)]
    parent = next((i for i in inventory if i.key == parent_key), None)
    parent_ref = store.publish_bytes(canonical_json_bytes(parent.raw_json), role='source') if parent is not None else None
    if parent_ref:
        inputs.append(parent_ref)
    if selection is not None:
        inputs.append(selection.parent_snapshot)
    status = 'blocked' if blockers else 'skipped' if relationship == 'exact_attachment' else 'ready'
    operations = _operations(proposal, source, parent, parent_ref, filename, gateway=gateway) if status == 'ready' else ()
    _source_current(source)
    if gateway.context != context:
        raise WorkflowError('instance_changed', 'instance changed during import planning')
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during import planning')
    plan = ChangePlan(schema_version='paper_reader.zotero-plan.v3', plan_id=new_random_id('plan'),
        run_id=proposal.run_id, context=context, created_at=rfc3339_utc(), library_version=version,
        operations=operations, inputs=tuple(dict.fromkeys(inputs)), content=(),
        import_details=ImportDetails(proposal=proposal_ref, source=source, filename=filename,
            suggested_filename=suggestion, status=status, blockers=tuple(dict.fromkeys(blockers)),
            collections=proposal.collections, duplicates=duplicates, selected_parent_key=parent_key,
            collection_snapshot=collection_ref,
            inventory_snapshot=inventory_ref, attachment_snapshot=attachment_ref))
    store.publish(plan)
    return plan


def validate_import_observations(plan: ChangePlan, *, gateway: ZoteroGateway, store: RunStore,
                                 excluded_keys=()) -> None:
    """One selected-classification and duplicate check for planning and execution."""
    detail = plan.import_details
    proposal = store.load(detail.proposal)
    if not isinstance(proposal, IdentificationProposal) or proposal.source != detail.source:
        raise WorkflowError('verification_failed', 'import proposal/source binding mismatch')
    previous = TypeAdapter(tuple[CollectionSnapshot, ...]).validate_json(store.read_bytes(detail.collection_snapshot))
    current = gateway.get_collections()
    # Only selected paths matter; unrelated collection edits do not invalidate this subject.
    old_by_key, new_by_key = {c.key: c for c in previous}, {c.key: c for c in current}
    for choice in detail.collections:
        key = choice.key
        while key:
            if key not in old_by_key or old_by_key.get(key) != new_by_key.get(key):
                raise WorkflowError('plan_stale', 'selected collection path changed')
            key = old_by_key[key].parent_key
    inventory, attachments = _inventory(proposal, detail.source, gateway, excluded_keys=excluded_keys)
    duplicates = match_duplicates(proposal, detail.source, inventory, attachments=attachments)
    if (duplicates != detail.duplicates or canonical_json_bytes([a.model_dump(mode='json') for a in attachments])
            != store.read_bytes(detail.attachment_snapshot)):
        raise WorkflowError('plan_stale', 'duplicate evidence changed')


def validate_import_plan(plan: ChangePlan, *, gateway: ZoteroGateway, store: RunStore) -> None:
    """Refresh import observations without authorizing or sending anything."""
    if store.load(artifact_ref(plan)) != plan or plan.import_details is None:
        raise WorkflowError('verification_failed', 'expected the persisted import plan')
    for ref in plan.inputs:
        store.read_bytes(ref)
    detail = plan.import_details
    _source_current(detail.source)
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'import belongs to another instance/library')
    version = gateway.get_library_version()
    validate_import_observations(plan, gateway=gateway, store=store)
    for operation in plan.operations:
        if isinstance(operation.before, ItemPrecondition):
            live = gateway.get_item(operation.before.key)
            if (live.version != operation.before.version
                    or canonical_json_bytes(live.raw_json) != store.read_bytes(operation.before.snapshot)):
                raise WorkflowError('plan_stale', 'existing parent changed')
        if isinstance(operation, (CreateParent, CreateAttachment)) and gateway.item_exists(operation.target_key):
            raise WorkflowError('plan_stale', 'preallocated target is occupied')
    _source_current(detail.source)
    if gateway.context != plan.context:
        raise WorkflowError('instance_changed', 'instance changed during validation')
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during validation')
