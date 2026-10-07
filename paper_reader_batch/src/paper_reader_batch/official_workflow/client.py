"""One explicit installed core root, one bounded subprocess, one JSON envelope."""
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import tomllib

from pydantic import ValidationError

from paper_reader_batch.official_workflow.contracts import BoundArtifactRef, CoreCommandResult
from paper_reader_batch.v2_errors import BatchRuntimeError
from paper_reader_batch.v2_json import (MAX_JSON_ARTIFACT_BYTES, canonical_sha256, open_directory_fd,
                                      read_relative_bytes, sha256_bytes)


class CoreProcessLost(BatchRuntimeError):
    """No trustworthy response: only core status/reconcile may resolve the outcome."""


def check_reference(ref: BoundArtifactRef) -> None:
    with open_directory_fd(ref.run_root, create=False) as (descriptor, _):
        raw = read_relative_bytes(descriptor, ref.artifact.path, code='core_reference_changed',
                                  max_bytes=MAX_JSON_ARTIFACT_BYTES)
    if len(raw) != ref.artifact.size_bytes or sha256_bytes(raw) != ref.artifact.sha256:
        raise BatchRuntimeError('core_reference_changed', 'core reference bytes changed')


class CoreProcessClient:
    def __init__(self, paper_reader_root: Path, *, timeout_seconds: int = 600):
        self.paper_reader_root = paper_reader_root.absolute()
        self.coordination_root = self.paper_reader_root / '.paper_reader_official'
        self.timeout_seconds = timeout_seconds
        self._identity = self._root_identity()

    def _root_identity(self):
        root = self.paper_reader_root
        with open_directory_fd(root, create=False) as (descriptor, _):
            identity = os.fstat(descriptor)
            paths = ('SKILL.md', 'pyproject.toml', 'uv.lock', 'src/paper_reader/official_cli.py')
            files = {p: read_relative_bytes(descriptor, p, code='core_root_invalid',
                                           max_bytes=MAX_JSON_ARTIFACT_BYTES) for p in paths}
        try:
            project = tomllib.loads(files['pyproject.toml'].decode())['project']
            if project['name'] != 'paper_reader':
                raise ValueError('wrong project')
        except (ValueError, KeyError) as exc:
            raise BatchRuntimeError('core_root_invalid', 'expected a Paper Reader installation') from exc
        return identity.st_dev, identity.st_ino, canonical_sha256({p: sha256_bytes(b) for p, b in files.items()})

    def invoke(self, args: tuple[str, ...]) -> CoreCommandResult:
        if self._root_identity() != self._identity:
            raise BatchRuntimeError('core_root_changed', 'core installation changed')
        if len(args) < 2 or args[:2] not in {
                ('plan', name) for name in ('preview', 'approve', 'apply', 'status', 'reconcile')}:
            raise BatchRuntimeError('core_command_invalid', 'unsupported batch command')
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV')}
        env['UV_PROJECT_ENVIRONMENT'] = str(self.paper_reader_root / '.venv')
        argv = ('uv', 'run', '--offline', '--locked', '--no-sync', 'python', '-m', 'paper_reader.official_cli', *args)
        # The core never returns credentials; also discard dependency stderr and
        # never put child output into exceptions or batch logs.
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(argv, cwd=self.paper_reader_root, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                raise CoreProcessLost('core_process_lost', 'core process timed out; query its journal') from None
            output.seek(0)
            raw = output.read(MAX_JSON_ARTIFACT_BYTES + 1)
        try:
            if len(raw) > MAX_JSON_ARTIFACT_BYTES:
                raise ValueError('oversized result')
            result = CoreCommandResult.model_validate_json(raw)
            if result.command != ' '.join(args[:2]) or result.ok != (process.returncode == 0):
                raise ValueError('invalid result envelope')
        except (ValueError, ValidationError):
            raise CoreProcessLost('core_process_lost', 'core response unavailable; query its journal') from None
        return result
