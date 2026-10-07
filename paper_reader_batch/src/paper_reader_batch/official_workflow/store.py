"""Immutable scheduling intents and receipts. Core journals own all write state."""
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from paper_reader_batch.official_workflow.contracts import BatchEvent, BatchManifest, BatchState, BoundApprovalRef
from paper_reader_batch.v2_errors import BatchRuntimeError
from paper_reader_batch.v2_json import (MAX_JSON_ARTIFACT_BYTES, canonical_json_bytes, canonical_sha256,
    entry_exists_allow_missing_parent, locked_file, publish_bytes_no_replace, read_bytes)


class BatchStore:
    def __init__(self, root: Path, manifest: BatchManifest):
        if not root.is_absolute() or not root.is_dir():
            raise BatchRuntimeError('batch_root_invalid', 'existing absolute batch root required')
        self.root, self.manifest = root, manifest
        self.manifest_sha256 = canonical_sha256(manifest)

    def _read(self, path, model):
        if not entry_exists_allow_missing_parent(path):
            return None
        raw = read_bytes(path, max_bytes=MAX_JSON_ARTIFACT_BYTES)
        try:
            value = model.model_validate_json(raw)
            if canonical_json_bytes(value) != raw:
                raise ValueError('noncanonical record')
            return value
        except (ValueError, ValidationError):
            raise BatchRuntimeError('batch_record_invalid', 'invalid batch scheduling record') from None

    def _publish(self, path, value):
        raw = canonical_json_bytes(value)
        if len(raw) > MAX_JSON_ARTIFACT_BYTES:
            raise BatchRuntimeError('resource_limit', 'batch record exceeds size limit')
        publish_bytes_no_replace(path, raw, allow_existing_exact=True, create_parent=True)

    def _check(self, event):
        manifest = self._read(self.root / 'manifest.json', BatchManifest)
        if manifest is not None and manifest != self.manifest:
            raise BatchRuntimeError('manifest_changed', 'batch manifest changed')
        previous = self._read(self.root / 'requests' / event.request_id / 'intent.json', BatchEvent)
        if previous is not None and previous != event:
            raise BatchRuntimeError('idempotency_conflict', 'idempotency_conflict: request is already bound')
        if previous is not None and manifest is None:
            raise BatchRuntimeError('batch_record_invalid', 'request has no manifest')
        return previous

    @contextmanager
    def request(self, event: BatchEvent):
        # Reparse strict types before using request ID as a path or taking locks.
        event = BatchEvent.model_validate_json(canonical_json_bytes(event))
        if event.manifest_sha256 != self.manifest_sha256:
            raise BatchRuntimeError('manifest_changed', 'request belongs to another manifest')
        self._check(event)
        with locked_file(self.root / '.batch.lock'):
            previous = self._check(event)
            self._publish(self.root / 'manifest.json', self.manifest)
            self._publish(self.root / 'requests' / event.request_id / 'intent.json', event)
            yield previous is not None

    def result(self, event: BatchEvent):
        value = self._read(self.root / 'requests' / event.request_id / 'result.json', BatchState)
        if value is not None and (value.manifest_sha256 != self.manifest_sha256
                or value.request_id != event.request_id or value.request_fingerprint != event.request_fingerprint):
            raise BatchRuntimeError('batch_record_invalid', 'result is not bound to request')
        return value

    def record_approval(self, event: BatchEvent, index: int, ref: BoundApprovalRef):
        self._publish(self.root / 'requests' / event.request_id / 'approvals' / f'{index:04d}.json', ref)

    def complete(self, event: BatchEvent, *, approvals: tuple[BoundApprovalRef, ...], report=None):
        state = BatchState(schema_version='paper_reader_batch.state.v3', manifest_sha256=self.manifest_sha256,
            request_id=event.request_id, request_fingerprint=event.request_fingerprint,
            approval_refs=approvals, report=report)
        self._publish(self.root / 'requests' / event.request_id / 'result.json', state)
        return state
