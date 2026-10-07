from __future__ import annotations

from contextlib import contextmanager
import fcntl
from hashlib import sha256
from pathlib import Path
import re
from typing import ContextManager, Iterator, Protocol, get_args

from pydantic import TypeAdapter, ValidationError

from paper_reader.contracts import ArtifactRef, PortableIdentifier
from paper_reader.official.models import LibraryContext
from paper_reader.operations.contracts import (
    ArtifactRole, BoundArtifactRef, ChangePlan, ContractArtifact, OperationEvent, WorkflowError, parse_artifact,
)
from paper_reader.resource_policy import V2_RESOURCE_POLICY as RESOURCE_POLICY
from paper_reader.storage import (
    ImmutableTreeEntry, OwnedDirectoryAnchor, TreeSnapshotLimitError, UnexpectedStorageSizeError,
    canonical_json_bytes, open_anchored_directory, open_directory_anchor,
    publish_bytes_no_replace, read_anchored_bytes, snapshot_anchored_tree, validate_directory_anchor,
)


class RunStore(Protocol):
    def publish(self, model: ContractArtifact) -> ArtifactRef: ...
    def load(self, ref: ArtifactRef) -> ContractArtifact: ...
    def publish_bytes(self, content: bytes, *, role: ArtifactRole) -> ArtifactRef: ...
    def read_bytes(self, ref: ArtifactRef) -> bytes: ...
    def append_event(self, event: OperationEvent, *, expected_head: str | None) -> ArtifactRef: ...
    def events(self, operation_id: str) -> tuple[OperationEvent, ...]: ...
    def library_lock(self, context: LibraryContext) -> ContextManager[None]: ...
    def bind_operation(self, plan: ChangePlan, operation_id: str) -> None: ...


# Artifact names come only from a schema-owned identity plus a content digest.
_ARTIFACT_LOCATIONS = {
    "run": ("source", "run_id"), "summary": ("evidence", "summary_id"),
    "review": ("reviews", "review_id"), "review-package": ("reviews", "review_package_id"),
    "candidate": ("candidates", "candidate_id"),
    "identification-proposal": ("source", "proposal_id"),
    "zotero-plan": ("plans", "plan_id"), "zotero-approval": ("approvals", "approval_id"),
    "zotero-result": ("readback", "run_id"), "duplicate-report": ("readback", "report_id"),
    "command-result": ("readback", None),
}
_IDENTIFIER = TypeAdapter(PortableIdentifier)
_EVENT_NAME = re.compile(r"[0-9]{20}\.json\Z")


def artifact_ref(model: ContractArtifact) -> ArtifactRef:
    """Compute the store-owned immutable location without reading or publishing."""
    content = canonical_json_bytes(model)
    checked = parse_artifact(content)
    if isinstance(checked, OperationEvent):
        raise WorkflowError("journal_corrupt", "events must be published with append_event")
    kind = checked.schema_version.split(".")[1]
    directory, identity_field = _ARTIFACT_LOCATIONS[kind]
    identity = _IDENTIFIER.validate_python(getattr(checked, identity_field)) if identity_field else "commands"
    digest = sha256(content).hexdigest()
    return ArtifactRef(role=kind, path=f"{directory}/{identity}/{digest}.json",
                       sha256=digest, size_bytes=len(content))


class FileRunStore:
    """One existing run root, immutable files, and per-operation hash chains.

    Construction and loading are read-only. Mutations lock the anchored run
    directory (no replaceable lock file), check all committed journals, then
    publish once. No snapshots, recovery guesses, or transport live here.
    """

    def __init__(self, root: Path, *, coordination_root: Path):
        self.root = root.absolute()
        self.coordination_root = coordination_root.absolute()
        with open_directory_anchor(self.root) as anchor:
            self._root_identity = (anchor.device, anchor.inode)
        with open_directory_anchor(self.coordination_root.parent) as installation:
            self._installation_identity = (installation.device, installation.inode)

    @contextmanager
    def _anchor(self) -> Iterator[OwnedDirectoryAnchor]:
        with open_directory_anchor(self.root) as anchor:
            if (anchor.device, anchor.inode) != self._root_identity:
                raise WorkflowError("source_changed", "run directory was replaced")
            yield anchor

    def _snapshot(self, anchor: OwnedDirectoryAnchor) -> tuple[ImmutableTreeEntry, ...]:
        try:
            return snapshot_anchored_tree(
                anchor, max_file_bytes=RESOURCE_POLICY.structured_artifact_max_bytes,
                max_total_bytes=RESOURCE_POLICY.run_max_bytes,
                max_members=RESOURCE_POLICY.artifact_tree_max_members,
                max_depth=RESOURCE_POLICY.artifact_tree_max_depth,
            ).entries
        except TreeSnapshotLimitError as exc:
            raise WorkflowError("resource_limit", "run exceeds storage limits") from exc

    @contextmanager
    def _locked(self) -> Iterator[tuple[OwnedDirectoryAnchor, tuple[ImmutableTreeEntry, ...]]]:
        with self._anchor() as anchor:
            # Unsupported/corrupt journals fail before taking any lock.
            self._journals(anchor, self._snapshot(anchor))
            fcntl.flock(anchor.descriptor, fcntl.LOCK_EX)
            try:
                validate_directory_anchor(anchor)
                entries = self._snapshot(anchor)
                self._journals(anchor, entries)
                yield anchor, entries
            finally:
                fcntl.flock(anchor.descriptor, fcntl.LOCK_UN)

    @staticmethod
    def _check_size(content: bytes) -> None:
        if len(content) > RESOURCE_POLICY.structured_artifact_max_bytes:
            raise WorkflowError("resource_limit", "artifact exceeds byte limit")

    def _read(self, anchor: OwnedDirectoryAnchor, ref: ArtifactRef) -> bytes:
        if ref.size_bytes > RESOURCE_POLICY.structured_artifact_max_bytes:
            raise WorkflowError("resource_limit", "artifact exceeds byte limit")
        try:
            content = read_anchored_bytes(anchor, self.root / ref.path,
                expected_size=ref.size_bytes, max_bytes=RESOURCE_POLICY.structured_artifact_max_bytes)
        except (FileNotFoundError, UnexpectedStorageSizeError) as exc:
            raise WorkflowError("source_changed", "artifact size or path changed") from exc
        if sha256(content).hexdigest() != ref.sha256:
            raise WorkflowError("source_changed", "artifact digest changed")
        return content

    def read_bytes(self, ref: ArtifactRef) -> bytes:
        with self._anchor() as anchor:
            return self._read(anchor, ref)

    def load(self, ref: ArtifactRef) -> ContractArtifact:
        return parse_artifact(self.read_bytes(ref))

    def _publish(self, anchor: OwnedDirectoryAnchor, entries: tuple[ImmutableTreeEntry, ...],
                 content: bytes, path: str, role: str) -> ArtifactRef:
        ref = ArtifactRef(role=role, path=path, sha256=sha256(content).hexdigest(), size_bytes=len(content))
        existing = {entry.path: entry for entry in entries}
        if path in existing:
            self._read(anchor, ref)  # Exact replay; never replace an occupied name.
            return ref
        needed = {path, *(p.as_posix() for p in Path(path).parents if p != Path("."))} - existing.keys()
        # Reserve one transient publication entry as well as the final path.
        if (sum(entry.size_bytes for entry in entries) + len(content) > RESOURCE_POLICY.run_max_bytes
                or len(entries) + len(needed) + 1 > RESOURCE_POLICY.artifact_tree_max_members
                or len(Path(path).parts) > RESOURCE_POLICY.artifact_tree_max_depth):
            raise WorkflowError("resource_limit", "publication exceeds run limits")
        publish_bytes_no_replace(content, self.root / path, anchor=anchor)
        return ref

    def publish_bytes(self, content: bytes, *, role: ArtifactRole) -> ArtifactRef:
        if role not in get_args(ArtifactRole):
            raise ValueError("unknown artifact role")
        self._check_size(content)
        path = f"{role}/{sha256(content).hexdigest()}.bin"
        with self._locked() as (anchor, entries):
            return self._publish(anchor, entries, content, path, role)

    def publish(self, model: ContractArtifact) -> ArtifactRef:
        content = canonical_json_bytes(model)
        self._check_size(content)
        ref = artifact_ref(model)
        with self._locked() as (anchor, entries):
            return self._publish(anchor, entries, content, ref.path, ref.role)

    def _journals(self, anchor: OwnedDirectoryAnchor, entries: tuple[ImmutableTreeEntry, ...]
                  ) -> dict[str, list[tuple[OperationEvent, ArtifactRef]]]:
        journals: dict[str, list[tuple[OperationEvent, ArtifactRef]]] = {}
        for entry in sorted(entries, key=lambda entry: entry.path):
            parts = Path(entry.path).parts
            if not parts or parts[0] != "operations" or entry.kind == "directory":
                continue
            # Incomplete publication files carry no truth and are never promoted.
            if entry.path.endswith((".tmp", ".writing")):
                continue
            if len(parts) != 4 or parts[2] != "events" or not _EVENT_NAME.fullmatch(parts[3]):
                raise WorkflowError("journal_corrupt", "unexpected committed event path")
            ref = ArtifactRef(role="event", path=entry.path, sha256=entry.sha256, size_bytes=entry.size_bytes)
            content = self._read(anchor, ref)
            try:
                event = parse_artifact(content)
            except ValidationError as exc:
                raise WorkflowError("journal_corrupt", "invalid event") from exc
            if not isinstance(event, OperationEvent) or canonical_json_bytes(event) != content:
                raise WorkflowError("journal_corrupt", "expected canonical event")
            journal = journals.setdefault(parts[1], [])
            self._check_next(event, journal, expected_head=journal[-1][1].sha256 if journal else None)
            if event.operation_id != parts[1] or event.seq != int(parts[3][:-5]):
                raise WorkflowError("journal_corrupt", "event path and identity disagree")
            journal.append((event, ref))
        return journals

    @staticmethod
    def _check_next(event: OperationEvent, journal: list[tuple[OperationEvent, ArtifactRef]],
                    *, expected_head: str | None) -> None:
        head = journal[-1][1].sha256 if journal else None
        if event.seq != len(journal) + 1 or event.previous_digest != head or expected_head != head:
            raise WorkflowError("journal_corrupt", "event sequence or previous digest mismatch")
        for previous, _ in journal:
            if previous.request_id == event.request_id:
                raise WorkflowError("journal_corrupt", "request identity was reused")
            if (previous.state == event.state == "started" and previous.stage == event.stage
                    and previous.attempt_id == event.attempt_id):
                raise WorkflowError("journal_corrupt", "send identity was already started")

    def events(self, operation_id: str) -> tuple[OperationEvent, ...]:
        _IDENTIFIER.validate_python(operation_id)
        with self._anchor() as anchor:
            journal = self._journals(anchor, self._snapshot(anchor)).get(operation_id, [])
            return tuple(event for event, _ in journal)

    def append_event(self, event: OperationEvent, *, expected_head: str | None) -> ArtifactRef:
        content = canonical_json_bytes(event)
        self._check_size(content)
        checked = parse_artifact(content)
        if not isinstance(checked, OperationEvent):
            raise WorkflowError("journal_corrupt", "append_event requires an event")
        with self._locked() as (anchor, entries):
            journal = self._journals(anchor, entries).get(checked.operation_id, [])
            if checked.seq <= len(journal):
                previous, ref = journal[checked.seq - 1]
                if previous == checked and expected_head == checked.previous_digest:
                    return ref
                raise WorkflowError("journal_corrupt", "occupied event sequence")
            self._check_next(checked, journal, expected_head=expected_head)
            path = f"operations/{checked.operation_id}/events/{checked.seq:020d}.json"
            return self._publish(anchor, entries, content, path, "event")

    def _library_path(self, context: LibraryContext) -> Path:
        server = sha256(context.server_id.encode()).hexdigest()
        library = sha256(f"{context.library_type}/{context.library_id}".encode()).hexdigest()
        return self.coordination_root / server / library

    def bind_operation(self, plan: ChangePlan, operation_id: str) -> None:
        """Call under library_lock; index points to truth, never contains state."""
        _IDENTIFIER.validate_python(operation_id)
        if operation_id not in {op.operation_id for op in plan.operations}:
            raise WorkflowError('approval_mismatch', 'operation is absent from plan')
        binding = BoundArtifactRef(run_root=self.root, run_id=plan.run_id, artifact=artifact_ref(plan))
        content = canonical_json_bytes(binding)
        with open_directory_anchor(self.coordination_root.parent) as installation:
            if (installation.device, installation.inode) != self._installation_identity:
                raise WorkflowError('source_changed', 'installation directory was replaced')
            with open_anchored_directory(installation, self._library_path(plan.context)) as library:
                path = library.path / 'operations' / f'{operation_id}.json'
                try:
                    existing = read_anchored_bytes(library, path, max_bytes=RESOURCE_POLICY.structured_artifact_max_bytes)
                except FileNotFoundError:
                    # Never rebuild an index after execution has begun.
                    if self.events(operation_id):
                        raise WorkflowError('journal_corrupt', 'execution index is missing') from None
                    publish_bytes_no_replace(content, path, anchor=library)
                else:
                    if existing != content:
                        raise WorkflowError('approval_mismatch', 'operation belongs to another run/plan')

    @contextmanager
    def library_lock(self, context: LibraryContext) -> Iterator[None]:
        # The configured installation parent is stable for the lifetime of a
        # writer. Its exclusive guard prevents contenders opening a replacement
        # coordination/library directory while the old lock is still held.
        # This intentionally serializes all libraries in this one installation.
        context = LibraryContext.model_validate_json(context.model_dump_json())
        with open_directory_anchor(self.coordination_root.parent) as installation:
            if (installation.device, installation.inode) != self._installation_identity:
                raise WorkflowError("source_changed", "installation directory was replaced")
            fcntl.flock(installation.descriptor, fcntl.LOCK_EX)
            try:
                validate_directory_anchor(installation)
                with open_anchored_directory(installation, self.coordination_root, create=True) as root:
                    with open_anchored_directory(root, self._library_path(context), create=True) as lock:
                        validate_directory_anchor(installation)
                        validate_directory_anchor(root)
                        validate_directory_anchor(lock)
                        yield
                        validate_directory_anchor(installation)
                        validate_directory_anchor(root)
                        validate_directory_anchor(lock)
            finally:
                fcntl.flock(installation.descriptor, fcntl.LOCK_UN)
