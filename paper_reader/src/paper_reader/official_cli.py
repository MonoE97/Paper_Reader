"""Development CLI: python -m paper_reader.official_cli (not the 2.2 entrypoint)."""
from functools import wraps
from pathlib import Path
from typing import Annotated

import typer
import click
from typer.core import TyperGroup
from pydantic import BaseModel, ValidationError

from paper_reader import services
from paper_reader.analysis.contracts import NoteCandidate
from paper_reader.ingest.contracts import IdentificationProposal, InspectionReport
from paper_reader.official.files import fingerprint_pdf
from paper_reader.official.auth import NativeCredentialProvider
from paper_reader.official.client import DEFAULT_BASE_URL, OfficialZoteroClient, UrllibTransport, connect
from paper_reader.official.models import ZoteroSelection
from paper_reader.operations.contracts import Approval, ChangePlan, CommandResult, WorkflowError, parse_artifact
from paper_reader.operations.execution_state import validate_approval, validate_plan
from paper_reader.operations.preview import validate_plan_artifacts
from paper_reader.operations.store import FileRunStore, artifact_ref
from paper_reader.resource_policy import V2_RESOURCE_POLICY
from paper_reader.storage import canonical_json_bytes, open_directory_anchor, read_anchored_bytes, rfc3339_utc

class JsonGroup(TyperGroup):
    def main(self, args=None, *, standalone_mode=True, **kwargs):
        try:
            result = super().main(args=args, standalone_mode=False, **kwargs)
            if standalone_mode and isinstance(result, int):
                raise SystemExit(result)
            return result
        except click.ClickException:
            result = CommandResult(schema_version='paper_reader.command-result.v3', command='arguments',
                ok=False, code='verification_failed', created_at=rfc3339_utc(), artifacts=())
            typer.echo(result.model_dump_json())
            if standalone_mode:
                raise SystemExit(2)
            raise typer.Exit(2)


app = typer.Typer(cls=JsonGroup, no_args_is_help=True, pretty_exceptions_enable=False)
zotero = typer.Typer(no_args_is_help=True)
plans = typer.Typer(no_args_is_help=True)
ingest = typer.Typer(no_args_is_help=True)
app.add_typer(zotero, name='zotero')
app.add_typer(plans, name='plan')
app.add_typer(ingest, name='ingest')
Root = Annotated[Path, typer.Option()]
Coordination = Annotated[Path, typer.Option()]


def command(name):
    """One JSON result; errors never echo exception strings or remote bodies."""
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            code, data, refs = 'ok', None, ()
            try:
                value = function(*args, **kwargs)
                data = value.model_dump(mode='json') if isinstance(value, BaseModel) else value
                if isinstance(value, (ChangePlan, Approval, NoteCandidate)):
                    refs = (artifact_ref(value),)
                elif isinstance(value, InspectionReport):
                    refs = tuple(e.evidence_ref for e in value.entries if e.evidence_ref is not None)
            except WorkflowError as exc:
                code = exc.code
            except (ValidationError, ValueError, OSError):
                code = 'verification_failed'
            except Exception:
                # Last boundary prevents credential-bearing dependency errors escaping.
                code = 'verification_failed'
            result = CommandResult(schema_version='paper_reader.command-result.v3', command=name,
                ok=code == 'ok', code=code, created_at=rfc3339_utc(), artifacts=refs, data=data)
            typer.echo(result.model_dump_json())
            if code != 'ok':
                raise typer.Exit(1)
        return invoke
    return decorate


def load(store, path, expected):
    with open_directory_anchor(store.root) as anchor:
        content = read_anchored_bytes(anchor, store.root / path,
            max_bytes=V2_RESOURCE_POLICY.structured_artifact_max_bytes)
    value = parse_artifact(content)
    if not isinstance(value, expected):
        raise WorkflowError('unsupported_artifact_schema', 'unexpected artifact kind')
    return value


def live(plan):
    observed = connect(plan.context.base_url)
    if observed.server_id != plan.context.server_id:
        raise WorkflowError('instance_changed', 'rebuild snapshots for the current instance')
    return OfficialZoteroClient(plan.context, UrllibTransport())


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
def preview(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()]):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan)
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
            confirmation_ref: Annotated[str, typer.Option()]):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan)
    return services.approve_plan(value, selected_operation_ids=tuple(operation_id),
        expected_plan_sha256=plan_sha256, confirmation_ref=confirmation_ref, store=store)


@plans.command('apply')
@command('plan apply')
def apply(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()],
          approval: str | None = None):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan)
    if approval is None:
        raise WorkflowError('approval_mismatch', 'explicit approval artifact required')
    approved = load(store, approval, Approval)
    validate_approval(value, approved, store)
    services.plan_status(value, store=store)  # Also reject invalid execution journals before connect.
    return services.apply_plan(value, approved, gateway=live(value),
                               credentials=NativeCredentialProvider(), store=store)


@plans.command('status')
@command('plan status')
def status(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()]):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    return services.plan_status(load(store, plan, ChangePlan), store=store)


@plans.command('reconcile')
@command('plan reconcile')
def reconcile(run_root: Root, coordination_root: Coordination, plan: Annotated[str, typer.Option()]):
    store = FileRunStore(run_root, coordination_root=coordination_root)
    value = load(store, plan, ChangePlan)
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
