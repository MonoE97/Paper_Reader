"""JSON/error and artifact boundary shared by the public v3 command groups."""
from functools import wraps
from pathlib import Path
from typing import Annotated

import click
import typer
from pydantic import BaseModel, ValidationError
from typer.core import TyperGroup

from paper_reader.analysis.contracts import PreparedPaper, NoteCandidate
from paper_reader.ingest.contracts import InspectionReport
from paper_reader.operations.contracts import Approval, ChangePlan, CommandResult, DuplicateReport, WorkflowError, parse_artifact
from paper_reader.operations.store import artifact_ref
from paper_reader.resource_policy import V2_RESOURCE_POLICY
from paper_reader.review_package import ReviewSealError
from paper_reader.storage import open_directory_anchor, read_anchored_bytes, rfc3339_utc

Root = Annotated[Path, typer.Option()]
Coordination = Annotated[Path, typer.Option()]

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


def command(name):
    """One JSON result; errors never echo exception strings or remote bodies."""
    def decorate(function):
        @wraps(function)
        def invoke(*args, **kwargs):
            code, data, refs = 'ok', None, ()
            try:
                value = function(*args, **kwargs)
                data = value.model_dump(mode='json') if isinstance(value, BaseModel) else value
                if isinstance(value, (ChangePlan, Approval, NoteCandidate, DuplicateReport)):
                    refs = (artifact_ref(value),)
                elif isinstance(value, PreparedPaper):
                    refs = (artifact_ref(value),)
                elif isinstance(value, InspectionReport):
                    refs = tuple(e.evidence_ref for e in value.entries if e.evidence_ref is not None)
            except ReviewSealError as exc:
                code = 'verification_failed'
                data = {'blockers': [blocker.model_dump(mode='json') for blocker in exc.blockers]}
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


def load(store, path, expected, *, expected_sha256=None, expected_run_id=None):
    with open_directory_anchor(store.root) as anchor:
        content = read_anchored_bytes(anchor, store.root / path,
            max_bytes=V2_RESOURCE_POLICY.structured_artifact_max_bytes)
    value = parse_artifact(content)
    if not isinstance(value, expected):
        raise WorkflowError('unsupported_artifact_schema', 'unexpected artifact kind')
    if ((expected_sha256 is not None and artifact_ref(value).sha256 != expected_sha256)
            or (expected_run_id is not None and value.run_id != expected_run_id)):
        raise WorkflowError('approval_mismatch', 'artifact differs from bound reference')
    return value
