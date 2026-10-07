"""Build a note plan from sealed analysis and a coherent, read-only library view."""
import json
import secrets

from pydantic import TypeAdapter

from paper_reader.analysis.contracts import NoteCandidate, PreparedPaper, ReviewPackage, Summary, Review
from paper_reader.analysis.evidence import bind_prepared_evidence
from paper_reader.analysis.quality import validate_analysis_quality
from paper_reader.analysis.rendering import _rewrite_markdown_h1, build_note_title
from paper_reader.analysis.secondary import validate_secondary_source
from paper_reader.note import build_note_labels, render_note_html
from paper_reader.note_hash import canonicalize_note_html_for_hash, note_html_sha256
from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.models import ItemKey, ItemSnapshot, ZoteroGateway
from paper_reader.operations.contracts import ChangePlan, CreateNote, ItemPrecondition, NotePayload, WorkflowError
from paper_reader.operations.store import RunStore, artifact_ref
from paper_reader.storage import canonical_json_bytes, new_random_id, rfc3339_utc
from paper_reader.zotero_live import _parse_headings


_KEY_ALPHABET = '23456789ABCDEFGHIJKLMNPQRSTUVWXYZ'


def _load_candidate(candidate: NoteCandidate, store: RunStore) -> tuple[PreparedPaper, ItemSnapshot]:
    """Check the sealed closure before any library call or publication."""
    if store.load(artifact_ref(candidate)) != candidate:
        raise WorkflowError('verification_failed', 'candidate differs from its immutable artifact')
    prepared, package = store.load(candidate.run_snapshot), store.load(candidate.sealed_review)
    if not isinstance(prepared, PreparedPaper) or not isinstance(package, ReviewPackage):
        raise WorkflowError('verification_failed', 'candidate requires a run and sealed review')
    if (candidate.target is None or candidate.target != prepared.selection
            or candidate.run_id != prepared.run_id or candidate.run_id != package.run_id
            or candidate.source != prepared.source
            or candidate.evidence_manifest != prepared.evidence_manifest
            or candidate.evidence_manifest != package.evidence_manifest
            or candidate.gate != package.gate or candidate.gate.status != 'passed' or candidate.gate.blockers
            or candidate.artifacts != (candidate.run_snapshot, candidate.sealed_review,
                                      *package.artifacts, *prepared.source_snapshots)
            or package.artifacts != (package.summary, package.review, candidate.note_markdown,
                                     candidate.note_html, prepared.evidence_manifest, *prepared.artifacts)):
        raise WorkflowError('verification_failed', 'candidate is detached from its sealed analysis')
    for ref in candidate.artifacts:
        store.read_bytes(ref)
    evidence = bind_prepared_evidence(prepared, store=store)
    children_refs = [ref for ref in prepared.source_snapshots if ref.role == 'zotero_children']
    if len(children_refs) != 1:
        raise WorkflowError('verification_failed', 'analysis must bind one children snapshot')
    children = TypeAdapter(tuple[ItemSnapshot, ...]).validate_json(store.read_bytes(children_refs[0]))
    title = build_note_title(prepared.metadata.title, prepared.created_at[:10],
                            (child.data.note for child in children if child.data.item_type == 'note'))
    if candidate.note_title != title:
        raise WorkflowError('verification_failed', 'candidate title differs from analysis source')
    validate_secondary_source(prepared, evidence)
    metadata = json.loads(evidence.artifacts_by_role['metadata'][0].raw_bytes)
    attachment_key = TypeAdapter(ItemKey).validate_python(metadata['pdf_attachment_key'])
    attachments = [child for child in children if child.key == attachment_key
                   and child.data.item_type == 'attachment' and child.data.content_type == 'application/pdf'
                   and child.data.parent_key == candidate.target.item_key]
    if len(attachments) != 1 or metadata['pdf_path'] != candidate.source.resolved_path:
        raise WorkflowError('verification_failed', 'selected attachment differs from analysis metadata')
    summary, review = store.load(package.summary), store.load(package.review)
    if (not isinstance(summary, Summary) or not isinstance(review, Review)
            or package.summary_sha256 != package.summary.sha256 or package.review_sha256 != package.review.sha256
            or package.evidence_digest != evidence.digest or summary.evidence_digest != evidence.digest):
        raise WorkflowError('verification_failed', 'sealed summary/review/evidence binding mismatch')
    quality = validate_analysis_quality(run_id=prepared.run_id, created_at=prepared.created_at,
                                       summary=summary, review=review, evidence=evidence)
    if quality.blockers or quality.rendered_note is None:
        raise WorkflowError('verification_failed', 'sealed analysis no longer passes quality validation')
    markdown = _rewrite_markdown_h1(quality.rendered_note.encode(), candidate.note_title)
    html = render_note_html(markdown.decode())
    if (store.read_bytes(candidate.note_markdown) != markdown or store.read_bytes(candidate.note_html) != html.encode()
            or candidate.tags != tuple(build_note_labels(summary.model_dump(mode='json')))
            or candidate.content_sha256 != note_html_sha256(html)
            or candidate.content_length != len(canonicalize_note_html_for_hash(html))
            or _parse_headings(html)[0] != candidate.note_title):
        raise WorkflowError('verification_failed', 'candidate content differs from reviewed rendering')
    return prepared, attachments[0]


def plan_note(candidate: NoteCandidate, *, gateway: ZoteroGateway, store: RunStore) -> ChangePlan:
    candidate = NoteCandidate.model_validate_json(canonical_json_bytes(candidate))
    prepared, attachment = _load_candidate(candidate, store)
    selection = prepared.selection
    # _load_candidate rejects local candidates; a local PDF never implies import consent.
    if selection is None:
        raise WorkflowError('metadata_unresolved', 'note planning requires an explicit Zotero selection')
    if gateway.context != selection.context:
        raise WorkflowError('instance_changed', 'candidate belongs to another instance/library')
    version = gateway.get_library_version()
    parent = gateway.get_item(selection.item_key)
    if parent != selection.parent:
        raise WorkflowError('plan_stale', 'selected parent changed; prepare a new analysis')
    children = gateway.get_children(parent.key)
    # The evidence records the exact attachment chosen at preparation time.
    if attachment not in children:
        raise WorkflowError('plan_stale', 'selected PDF attachment changed or was removed')
    if fingerprint_pdf(gateway.get_file_path(attachment.key)) != candidate.source:
        raise WorkflowError('source_changed', 'analyzed PDF is no longer attached with the same identity')
    target_key = ''.join(secrets.choice(_KEY_ALPHABET) for _ in range(8))
    if gateway.item_exists(target_key):
        raise WorkflowError('plan_stale', 'preallocated note key is occupied; build a new plan')
    if gateway.context != selection.context:
        raise WorkflowError('instance_changed', 'instance changed during planning')
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed during planning')
    matches = [child.key for child in children if child.data.item_type == 'note'
               and _parse_headings(child.data.note)[0] == candidate.note_title]
    blockers = tuple(f'同名笔记已存在：{key}；需重新生成并预览笔记。' for key in matches)
    children_ref = store.publish_bytes(canonical_json_bytes([child.model_dump(mode='json') for child in children]),
                                       role='source').model_copy(update={'role': 'planning_children'})
    operation = CreateNote(type='create_note', operation_id=new_random_id('operation'),
        subject_id=candidate.run_id, subject_title=prepared.metadata.title, depends_on=(), target_key=target_key,
        before=ItemPrecondition(kind='existing', key=parent.key, version=parent.version,
                                snapshot=selection.parent_snapshot),
        reason='为明确选中的文献新增已通过证据与中文审核的阅读笔记，保留已有笔记。', blockers=blockers,
        payload=NotePayload(parent_key=parent.key, title=candidate.note_title,
            html=store.read_bytes(candidate.note_html).decode(), tags=candidate.tags,
            content_sha256=candidate.content_sha256))
    plan = ChangePlan(schema_version='paper_reader.zotero-plan.v3', plan_id=new_random_id('plan'),
        run_id=candidate.run_id, context=selection.context, created_at=rfc3339_utc(), library_version=version,
        operations=(operation,), inputs=(artifact_ref(candidate), *candidate.artifacts, children_ref),
        content=(candidate.note_markdown, candidate.note_html))
    store.publish(plan)
    return plan
