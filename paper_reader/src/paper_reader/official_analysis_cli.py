"""Thin adapters for existing analysis services and the offline PDF extractor."""
from pathlib import Path
from typing import Annotated

import typer

from paper_reader import services
from paper_reader.analysis.contracts import PreparedPaper, Summary, Review
from paper_reader.analysis.evidence import bind_prepared_evidence
from paper_reader.analysis.secondary import validate_secondary_source
from paper_reader.evidence_bundle import _verified_pdf_snapshot
from paper_reader.official.files import fingerprint_pdf
from paper_reader.operations.store import FileRunStore
from paper_reader.pdf_extract import extract_pdf
from paper_reader.resource_policy import V2_RESOURCE_POLICY
from paper_reader.official_cli_support import Root, Coordination, command, load

analysis = typer.Typer(no_args_is_help=True)
maintenance = typer.Typer(no_args_is_help=True)


@analysis.command('capture-binding')
@command('analysis capture-binding')
def capture_binding(run_root: Root, coordination_root: Coordination,
                    prepared: Annotated[str, typer.Option()]):
    """Read-only binding used by the strict browser capture script."""
    store = FileRunStore(run_root, coordination_root=coordination_root)
    paper = load(store, prepared, PreparedPaper)
    evidence = bind_prepared_evidence(paper, store=store)
    validate_secondary_source(paper, evidence)
    if paper.selection is None:
        raise ValueError('local PDF analysis has no secondary capture plan')
    plan, = evidence.artifacts_by_role['secondary_plan']
    return {'plan_path': str(store.root / plan.ref.path), 'size_bytes': plan.ref.size_bytes,
            'binding': {'runId': paper.run_id, 'itemKey': paper.selection.item_key,
                        'sourceSnapshotSha256': paper.selection.parent_snapshot.sha256,
                        'secondaryPlanSha256': plan.ref.sha256}}


@analysis.command('seal')
@command('analysis seal')
def seal(run_root: Root, coordination_root: Coordination,
         prepared: Annotated[str, typer.Option()], summary: Annotated[str, typer.Option()],
         review: Annotated[str, typer.Option()]):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    return services.seal_analysis(load(store, prepared, PreparedPaper), load(store, summary, Summary),
                                  load(store, review, Review), store=store)


@analysis.command('attach-secondary')
@command('analysis attach-secondary')
def attach_secondary(run_root: Root, coordination_root: Coordination,
                     prepared: Annotated[str, typer.Option()], capture_dir: Annotated[Path, typer.Option()]):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    return services.attach_secondary_captures(load(store, prepared, PreparedPaper), capture_dir, store=store)


@maintenance.command('extract-pdf')
@command('maintenance extract-pdf')
def extract(pdf_path: Path, max_pages: Annotated[int | None, typer.Option(min=1,
            max=V2_RESOURCE_POLICY.pdf_max_pages)] = None):
    source = fingerprint_pdf(pdf_path)
    with _verified_pdf_snapshot(source, run_id='maintenance') as snapshot:
        extraction = extract_pdf(snapshot, max_pages=max_pages,
            max_chars=V2_RESOURCE_POLICY.extracted_text_max_chars,
            hard_max_pages=V2_RESOURCE_POLICY.pdf_max_pages)
    extraction['pdf_path'] = source.resolved_path
    return {'pdf_path': str(pdf_path), 'extraction': extraction}
