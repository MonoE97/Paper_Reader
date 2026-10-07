"""Public Paper Reader 3.0 CLI; every write uses the approved core executor."""
from pathlib import Path
from typing import Annotated

import typer

from paper_reader import __version__, services
from paper_reader.analysis.contracts import NoteCandidate
from paper_reader.ingest.contracts import IdentificationProposal, InspectionReport
from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.auth import NativeCredentialProvider
from paper_reader.official.client import DEFAULT_BASE_URL, OfficialZoteroClient, UrllibTransport, connect
from paper_reader.official.models import ZoteroSelection
from paper_reader.operations.contracts import Approval, ChangePlan, WorkflowError
from paper_reader.operations.execution_state import validate_plan
from paper_reader.operations.preview import validate_plan_artifacts
from paper_reader.operations.store import FileRunStore, artifact_ref
from paper_reader.official_batch import BoundApprovalRef, admit_approvals, apply_admitted
from paper_reader.storage import canonical_json_bytes
from paper_reader.official_cli_support import JsonGroup, Root, Coordination, command, load
from paper_reader.official_analysis_cli import analysis, maintenance

app = typer.Typer(cls=JsonGroup, no_args_is_help=True, pretty_exceptions_enable=False)
zotero = typer.Typer(no_args_is_help=True)
plans = typer.Typer(no_args_is_help=True)
ingest = typer.Typer(no_args_is_help=True)
app.add_typer(zotero, name='zotero')
app.add_typer(plans, name='plan')
app.add_typer(ingest, name='ingest')
app.add_typer(analysis, name="analysis")
app.add_typer(maintenance, name="maintenance")


def show_version(value: bool):
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(version: Annotated[bool, typer.Option('--version', callback=show_version, is_eager=True)] = False):
    """Plan, preview, approve and verify changes through the official local API."""


def live(plan):
    observed = connect(plan.context.base_url)
    if observed.server_id != plan.context.server_id:
        raise WorkflowError('instance_changed', 'rebuild snapshots for the current instance')
    return OfficialZoteroClient(plan.context, UrllibTransport())


@zotero.command('search')
@command('zotero search')
def search(query: str, base_url: str = DEFAULT_BASE_URL):
    gateway = OfficialZoteroClient(connect(base_url), UrllibTransport())
    return {'context': gateway.context.model_dump(mode='json'),
            'items': [item.model_dump(mode='json') for item in gateway.search_items(query)]}


@zotero.command('collections')
@command('zotero collections')
def collections(base_url: str = DEFAULT_BASE_URL):
    gateway = OfficialZoteroClient(connect(base_url), UrllibTransport())
    return {'context': gateway.context.model_dump(mode='json'),
            'collections': [item.model_dump(mode='json') for item in gateway.get_collections()]}


@zotero.command('inspect')
@command('zotero inspect')
def inspect(item_key: Annotated[str, typer.Option()], base_url: str = DEFAULT_BASE_URL):
    gateway = OfficialZoteroClient(connect(base_url), UrllibTransport())
    return {'context': gateway.context.model_dump(mode='json'),
            'item': gateway.get_item(item_key).model_dump(mode='json'),
            'children': [c.model_dump(mode='json') for c in gateway.get_children(item_key)]}


@zotero.command('prepare')
@command('zotero prepare')
def prepare(run_root: Root, coordination_root: Coordination, item_key: Annotated[str, typer.Option()],
            attachment_key: str | None = None, base_url: str = DEFAULT_BASE_URL):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    gateway = OfficialZoteroClient(connect(base_url), UrllibTransport())
    parent = gateway.get_item(item_key)
    ref = store.publish_bytes(canonical_json_bytes(parent.raw_json), role='source')
    selection = ZoteroSelection(context=gateway.context, item_key=item_key, parent=parent, parent_snapshot=ref)
    return services.prepare_zotero(selection, gateway=gateway, store=store, attachment_key=attachment_key)


@zotero.command('check-duplicates')
@command('zotero check-duplicates')
def check_duplicates(run_root: Root, coordination_root: Coordination, base_url: str = DEFAULT_BASE_URL):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    gateway = OfficialZoteroClient(connect(base_url), UrllibTransport())
    return services.scan_duplicates(gateway=gateway, store=store)


@plans.command('note')
@command('plan note')
def note(run_root: Root, coordination_root: Coordination, candidate: Annotated[str, typer.Option()]):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, candidate, NoteCandidate)
    if value.target is None:
        raise WorkflowError('metadata_unresolved', 'Zotero candidate required')
    observed = connect(value.target.context.base_url)
    if observed.server_id != value.target.context.server_id:
        raise WorkflowError('instance_changed', 'candidate belongs to another instance')
    return services.plan_note(value, gateway=OfficialZoteroClient(value.target.context, UrllibTransport()), store=store)


@plans.command('preview')
@command('plan preview')
def preview(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()],
            expected_sha256: str | None = None, expected_run_id: str | None = None):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan, expected_sha256=expected_sha256, expected_run_id=expected_run_id)
    if value.import_details is not None:
        validate_plan_artifacts(value, store)
    else:
        validate_plan(value, store)
    return services.preview_plan(value)


@ingest.command('inspect')
@command('ingest inspect')
def inspect_import(path: Path, run_root: Root, coordination_root: Coordination):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    report = services.inspect_inputs(path)
    entries = tuple(entry.model_copy(update={'evidence_ref': store.publish_bytes(
        canonical_json_bytes(entry.evidence), role='source')}) if entry.evidence is not None else entry
        for entry in report.entries)
    return InspectionReport(entries=entries)


@plans.command('import')
@command('plan import')
def import_pdf(run_root: Root, coordination_root: Coordination, source: Annotated[Path, typer.Option()],
               proposal: Annotated[str, typer.Option()], base_url: str = DEFAULT_BASE_URL):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, proposal, IdentificationProposal)
    pdf = fingerprint_pdf(source)
    if pdf != value.source:
        raise WorkflowError('source_changed', 'proposal belongs to another PDF')
    gateway = OfficialZoteroClient(connect(base_url), UrllibTransport())
    return services.plan_import(pdf, value, gateway=gateway, store=store)


@plans.command('approve')
@command('plan approve')
def approve(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()],
            plan_sha256: Annotated[str, typer.Option()], operation_id: Annotated[list[str], typer.Option()],
            confirmation_ref: Annotated[str, typer.Option()], expected_run_id: str | None = None):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan, expected_sha256=plan_sha256, expected_run_id=expected_run_id)
    return services.approve_plan(value, selected_operation_ids=tuple(operation_id),
        expected_plan_sha256=plan_sha256, confirmation_ref=confirmation_ref, store=store)


@plans.command('apply')
@command('plan apply')
def apply(coordination_root: Coordination,
          approval: Annotated[list[str] | None, typer.Option()] = None,
          run_root: Annotated[Path | None, typer.Option()] = None,
          plan: Annotated[str | None, typer.Option()] = None):
    # Existing single-run development syntax is converted to the same admission.
    if run_root is not None and plan is not None:
        store = FileRunStore(run_root, coordination_root=coordination_root)
        value = load(store, plan, ChangePlan)
        if not approval or len(approval) != 1:
            raise WorkflowError('approval_mismatch', 'one explicit approval artifact required')
        approved = load(store, approval[0], Approval)
        refs = (BoundApprovalRef(run_root=store.root, run_id=value.run_id,
                artifact=artifact_ref(approved), plan=artifact_ref(value)),)
        single = True
    elif run_root is None and plan is None and approval:
        refs = tuple(BoundApprovalRef.model_validate_json(ref) for ref in approval)
        single = False
    else:
        raise WorkflowError('approval_mismatch', 'explicit approval artifact required')
    admitted = admit_approvals(refs, coordination_root)
    credentials = NativeCredentialProvider()
    if single:
        item, = admitted
        return services.apply_plan(item.plan, item.approval, gateway=live(item.plan),
                                   credentials=credentials, store=item.store)
    return apply_admitted(admitted, credentials=credentials, live=live)


@plans.command('status')
@command('plan status')
def status(coordination_root: Coordination, run_root: Annotated[Path | None, typer.Option()] = None,
           plan: str | None = None, approval: Annotated[list[str] | None, typer.Option()] = None):
    if run_root is not None and plan is not None and not approval:
        store = FileRunStore(run_root, coordination_root=coordination_root)
        return services.plan_status(load(store, plan, ChangePlan), store=store)
    if run_root is None and plan is None and approval:
        refs = tuple(BoundApprovalRef.model_validate_json(ref) for ref in approval)
        admitted = admit_approvals(refs, coordination_root)
        return {'entries': [{'reference': item.reference.model_dump(mode='json'), 'code': 'ok',
                 'selected_operation_ids': list(item.approval.selected_operation_ids),
                 'report': services.plan_status(item.plan, store=item.store).model_dump(mode='json')}
                for item in admitted]}
    raise WorkflowError('approval_mismatch', 'explicit plan or bound approvals required')


@plans.command('reconcile')
@command('plan reconcile')
def reconcile(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()],
              expected_sha256: str | None = None, expected_run_id: str | None = None):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan, expected_sha256=expected_sha256, expected_run_id=expected_run_id)
    services.plan_status(value, store=store)
    return services.reconcile_plan(value, gateway=live(value), store=store)


@plans.command('retry')
@command('plan retry')
def retry(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()],
          operation_id: Annotated[str, typer.Option()], confirmation_ref: Annotated[str, typer.Option()],
          acknowledge_no_match: bool = False):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan)
    if not acknowledge_no_match or not confirmation_ref.strip():
        raise WorkflowError('approval_mismatch', 'explicit no-match retry confirmation required')
    services.plan_status(value, store=store)
    return services.retry_operation(value, operation_id=operation_id, acknowledge_no_match=acknowledge_no_match,
        confirmation_ref=confirmation_ref, gateway=live(value), store=store)


if __name__ == '__main__':
    app()
