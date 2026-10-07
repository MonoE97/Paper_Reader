"""Development entrypoint only: python -m paper_reader_batch.official_workflow.cli."""
from functools import wraps
from pathlib import Path
from typing import Annotated

import typer
from typer import _click as click
from pydantic import BaseModel, ValidationError
from typer.core import TyperGroup

from paper_reader_batch.official_workflow.client import CoreProcessClient
from paper_reader_batch.official_workflow.contracts import BatchManifest, PreviewDocument, BoundApprovalRef, CommandResult
from paper_reader_batch.official_workflow.driver import BatchDriver
from paper_reader_batch.v2_errors import BatchRuntimeError
from paper_reader_batch.v2_json import MAX_JSON_ARTIFACT_BYTES, read_bytes


def emit(command, *, code='ok', data=None):
    typer.echo(CommandResult(schema_version='paper_reader_batch.command-result.v3',
        command=command, ok=code == 'ok', code=code, data=data).model_dump_json())


class JsonGroup(TyperGroup):
    def main(self, args=None, *, standalone_mode=True, **kwargs):
        try:
            result = super().main(args=args, standalone_mode=False, **kwargs)
            if standalone_mode and isinstance(result, int):
                raise SystemExit(result)
            return result
        except click.ClickException:
            emit('arguments', code='invalid_arguments')
            raise SystemExit(2) from None


app = typer.Typer(cls=JsonGroup, no_args_is_help=True, pretty_exceptions_enable=False)
Root = Annotated[Path, typer.Option()]


def command(name):
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            try:
                value = function(*args, **kwargs)
                data = value.model_dump(mode='json') if isinstance(value, BaseModel) else value
            except BatchRuntimeError as exc:
                emit(name, code=exc.code)
                raise typer.Exit(1) from None
            except (ValidationError, ValueError, OSError):
                emit(name, code='invalid_artifact')
                raise typer.Exit(1) from None
            except Exception:
                emit(name, code='internal_error')
                raise typer.Exit(1) from None
            emit(name, data=data)
        return invoke
    return decorate


def load(path, model):
    return model.model_validate_json(read_bytes(path, max_bytes=MAX_JSON_ARTIFACT_BYTES))


def driver(manifest, run_root):
    manifest = load(manifest, BatchManifest)
    return BatchDriver(client=CoreProcessClient(manifest.paper_reader_root), run_root=run_root, manifest=manifest)


@app.command('preview')
@command('preview')
def preview(manifest: Root, run_root: Root):
    batch = driver(manifest, run_root)
    value = batch.preview(batch.manifest.plan_refs)
    return PreviewDocument(preview=value, preview_sha256=value.sha256)


@app.command('approve')
@command('approve')
def approve(manifest: Root, run_root: Root, preview: Root,
            expected_preview_sha256: Annotated[str, typer.Option()],
            confirmation_ref: Annotated[str, typer.Option()], request_id: Annotated[str, typer.Option()],
            subject_id: Annotated[list[str] | None, typer.Option()] = None):
    batch = driver(manifest, run_root)
    refs = batch.approve(load(preview, PreviewDocument).preview, selected_subject_ids=tuple(subject_id or ()),
        expected_preview_sha256=expected_preview_sha256, confirmation_ref=confirmation_ref, request_id=request_id)
    return {'approval_refs': [ref.model_dump(mode='json') for ref in refs]}


@app.command('apply')
@command('apply')
def apply(manifest: Root, run_root: Root, request_id: Annotated[str, typer.Option()],
          approval: Annotated[list[str], typer.Option()]):
    refs = tuple(BoundApprovalRef.model_validate_json(value) for value in approval)
    return driver(manifest, run_root).apply(refs, request_id=request_id)


if __name__ == '__main__':
    app()
