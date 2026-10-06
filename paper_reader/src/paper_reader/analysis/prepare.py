"""PDF analysis preparation, with a narrow official-Zotero discovery adapter."""
import json
from pathlib import Path
import re
import tempfile

from paper_reader.contracts import ArtifactRef
from paper_reader.analysis.contracts import PaperIdentifier, PaperMetadata, PdfSource, PreparedPaper
from paper_reader.analysis.evidence import AnalysisEvidence, input_digest, publish_member
from paper_reader.evidence_bundle import _verified_pdf_snapshot, _page_count
from paper_reader.evidence_figures import prepare_figure_artifacts
from paper_reader.evidence_manifest import build_evidence_manifest
from paper_reader.workflow import build_figure_context_markdown
from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.models import ZoteroGateway, ZoteroSelection
from paper_reader.operations.contracts import WorkflowError
from paper_reader.operations.store import RunStore
from paper_reader.pdf_extract import extract_pdf
from paper_reader.pdf_workflow import build_pdf_metadata
from paper_reader.resource_policy import V2_RESOURCE_POLICY as RESOURCE_POLICY
from paper_reader.storage import (canonical_json_bytes, new_random_id, open_directory_anchor, rfc3339_utc)
from paper_reader.workflow import build_context_markdown, build_metadata, build_section_context_markdown, format_creators


def prepare_pdf(source: PdfSource, *, metadata: PaperMetadata, store: RunStore) -> PreparedPaper:
    render_metadata = build_pdf_metadata(Path(source.resolved_path), title=metadata.title,
        authors=', '.join(metadata.authors), date=str(metadata.year) if metadata.year else '',
        doi=next((item.value for item in metadata.identifiers if item.kind == 'doi'), ''))
    return _prepare(source, metadata=metadata, render_metadata=render_metadata, selection=None,
                    snapshots=(), store=store)


def prepare_zotero(source: ZoteroSelection, *, gateway: ZoteroGateway, store: RunStore,
                   attachment_key: str | None = None) -> PreparedPaper:
    if source.context != gateway.context:
        raise WorkflowError('instance_changed', 'selection belongs to another Zotero instance/library')
    if store.read_bytes(source.parent_snapshot) != canonical_json_bytes(source.parent.raw_json):
        raise WorkflowError('source_changed', 'selected parent snapshot does not match its raw JSON')
    version = gateway.get_library_version()
    parent = gateway.get_item(source.item_key)
    if parent != source.parent:
        raise WorkflowError('plan_stale', 'selected parent changed')
    if parent.data.item_type in ('note', 'attachment') or parent.data.parent_key:
        raise WorkflowError('metadata_unresolved', 'select a bibliographic parent')
    children = gateway.get_children(source.item_key)
    pdfs = [child for child in children if child.data.item_type == 'attachment'
            and child.data.content_type == 'application/pdf' and child.data.parent_key == source.item_key]
    selected = [child for child in pdfs if attachment_key is None or child.key == attachment_key]
    if len(selected) != 1:
        raise WorkflowError('attachment_unavailable', 'select exactly one primary PDF attachment')
    attachment = selected[0]
    pdf = fingerprint_pdf(gateway.get_file_path(attachment.key))
    if gateway.context != source.context:
        raise WorkflowError('instance_changed', 'Zotero instance changed during preparation')
    if gateway.get_library_version() != version:
        raise WorkflowError('plan_stale', 'library changed while reading source')
    data = dict(parent.raw_json['data'])
    data['key'] = parent.key
    data['attachments'] = [{**attachment.raw_json['data'], 'key': attachment.key, 'path': pdf.resolved_path}]
    render_metadata = build_metadata(data)
    creators = data.get('creators', [])
    authors = tuple(format_creators([creator]) for creator in creators if format_creators([creator]))
    date_text = data.get('date', '')
    year_match = re.search(r'\b([12]\d{3})\b', date_text)
    identifiers = tuple(PaperIdentifier(kind=kind, value=data[field]) for field, kind in
                        (('DOI', 'doi'), ('ISBN', 'isbn')) if data.get(field))
    metadata = PaperMetadata(title=parent.data.title, authors=authors,
        year=int(year_match[1]) if year_match else None, identifiers=identifiers)
    children_ref = store.publish_bytes(canonical_json_bytes([child.model_dump(mode='json') for child in children]),
        role='source').model_copy(update={'role': 'zotero_children'})
    snapshots = (source.parent_snapshot, children_ref)
    return _prepare(pdf, metadata=metadata, render_metadata=render_metadata, selection=source,
                    snapshots=snapshots, store=store)


def _prepare(source: PdfSource, *, metadata: PaperMetadata, render_metadata: dict,
             selection: ZoteroSelection | None, snapshots: tuple[ArtifactRef, ...],
             store: RunStore) -> PreparedPaper:
    from paper_reader.analysis.secondary import secondary_files
    run_id, created_at = new_random_id('run'), rfc3339_utc()
    with _verified_pdf_snapshot(source, run_id=run_id) as verified:
        if _page_count(verified) > RESOURCE_POLICY.pdf_max_pages:
            raise WorkflowError('resource_limit', 'PDF exceeds page limit')
        extraction = extract_pdf(Path(source.resolved_path), _verified_pdf_path=verified,
                                 max_chars=RESOURCE_POLICY.extracted_text_max_chars)
        secondary = secondary_files(selection, run_id=run_id)
        files = {
            'metadata.json': (canonical_json_bytes(render_metadata), 'metadata', 'application/json'),
            'extract.json': (canonical_json_bytes(extraction), 'extract', 'application/json'),
            'context.md': (build_context_markdown(render_metadata, extraction).encode(), 'context', 'text/markdown'),
            'section_context.md': (build_section_context_markdown(render_metadata, extraction).encode(), 'section_context', 'text/markdown'),
        }
        from paper_reader.analysis.secondary import secondary_member_role
        files.update({name: (raw, *secondary_member_role(name)) for name, raw in secondary.files.items()})
        members = []
        # Figure extractor owns ephemeral scratch only; durable artifacts belong to RunStore.
        with tempfile.TemporaryDirectory(prefix='paper-reader-analysis-') as directory:
            scratch = Path(directory)
            with open_directory_anchor(scratch) as anchor:
                figures = prepare_figure_artifacts(source_path=Path(source.resolved_path), verified_source_path=verified,
                    staging=scratch, staging_anchor=anchor, future_dir=scratch, run_dir=scratch,
                    figure_limit=RESOURCE_POLICY.figure_default_limit, preview_pages=None, complete=True,
                    allow_network_source=False)
            image_refs = {}
            for path, future, role, media_type in figures.artifacts:
                name = future.relative_to(scratch).as_posix()
                if role == 'figure_image':
                    member = publish_member(store, name, path.read_bytes(), role, media_type)
                    members.append(member)
                    image_refs[name] = member.artifact
                else:
                    files[name] = (path.read_bytes(), role, media_type)
            if 'figures.json' in files:
                payload = json.loads(files['figures.json'][0])
                for figure in payload['selected_figures']:
                    figure['image_path'] = image_refs[figure['image_path']].path
                files['figures.json'] = (canonical_json_bytes(payload), 'figures', 'application/json')
                files['figure_context.md'] = (build_figure_context_markdown(payload).encode(), 'figure_context', 'text/markdown')
            members.extend(publish_member(store, name, content, role, media_type)
                           for name, (content, role, media_type) in files.items())
        manifest = build_evidence_manifest(evidence_id=new_random_id('evidence'), run_id=run_id,
            source_sha256=source.sha256, complete=True, preview_pages=None,
            files=tuple(member.artifact for member in members), extraction=extraction,
            figure_limit=RESOURCE_POLICY.figure_default_limit,
            run_size_bytes=sum(member.artifact.size_bytes for member in members),
            figures=tuple(member.model_copy(update={'artifact_path': image_refs[member.artifact_path].path})
                          for member in figures.members),
            degraded=figures.degraded or secondary.degraded, figure_check=figures.extraction_check,
            figure_resource_checks=figures.resource_checks, secondary_resource_checks=())
        # RunStore enforces aggregate run bytes on every publication; member bytes are not a run total.
        manifest = manifest.model_copy(update={'resource_checks': tuple(
            check for check in manifest.resource_checks if check.name != 'run_size_bytes')})
        bundle = AnalysisEvidence(format='paper_reader.analysis-evidence.v3-internal',
            input_digest=input_digest(run_id=run_id, created_at=created_at, source=source, metadata=metadata,
                                      selection=selection, snapshots=snapshots), manifest=manifest, members=tuple(members))
        ref = store.publish_bytes(canonical_json_bytes(bundle), role='evidence')
    prepared = PreparedPaper(schema_version='paper_reader.run.v3', run_id=run_id, created_at=created_at,
        source=source, metadata=metadata, selection=selection, source_snapshots=snapshots,
        evidence_manifest=ref, context=next(m.artifact for m in members if m.artifact.role == 'context'),
        figure_inventory=tuple(m.artifact for m in members if m.artifact.role in ('figures', 'figure_context', 'figure_image')),
        artifacts=tuple(m.artifact for m in members))
    store.publish(prepared)
    return prepared
