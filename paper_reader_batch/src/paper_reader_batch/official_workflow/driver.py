"""Preview and select locally; delegate every approval, send and recovery to core."""
from pathlib import Path

from paper_reader_batch.official_workflow.client import CoreProcessClient, CoreProcessLost, check_reference
from paper_reader_batch.official_workflow.contracts import (ApplyRequest, ApproveRequest, BatchEvent,
    BatchManifest, BatchPreview, BoundApprovalRef, BoundArtifactRef, PreviewEntry)
from paper_reader_batch.official_workflow.report import build_report, subject_operations
from paper_reader_batch.official_workflow.store import BatchStore
from paper_reader_batch.v2_errors import BatchRuntimeError
from paper_reader_batch.v2_json import canonical_json_bytes, canonical_sha256


class BatchDriver:
    def __init__(self, *, client: CoreProcessClient, run_root: Path, manifest: BatchManifest):
        self.manifest = BatchManifest.model_validate_json(canonical_json_bytes(manifest))
        if manifest.paper_reader_root != client.paper_reader_root:
            raise BatchRuntimeError('core_root_invalid', 'manifest names a different core root')
        self.client = client
        self.store = BatchStore(run_root, self.manifest)

    def _invoke(self, args):
        result = self.client.invoke(tuple(args))
        if not result.ok:
            raise BatchRuntimeError(result.code, f'core refused command: {result.code}')
        if result.data is None:
            raise BatchRuntimeError('core_response_invalid', 'core response has no data')
        return result

    def _plan_args(self, action, ref):
        return ['plan', action, '--run-root', str(ref.run_root),
                '--coordination-root', str(self.client.coordination_root), '--plan', ref.artifact.path,
                '--expected-run-id', ref.run_id]

    def _approval_args(self, action, refs):
        args = ['plan', action, '--coordination-root', str(self.client.coordination_root)]
        for ref in refs:
            args += ['--approval', ref.model_dump_json()]
        return args

    def preview(self, plan_refs: tuple[BoundArtifactRef, ...]) -> BatchPreview:
        if plan_refs != self.manifest.plan_refs:
            raise BatchRuntimeError('manifest_changed', 'preview must cover the entire manifest')
        for ref in plan_refs:
            check_reference(ref)
        entries, subjects = [], set()
        for ref in plan_refs:
            result = self._invoke(self._plan_args('preview', ref) + ['--expected-sha256', ref.artifact.sha256])
            if result.data.get('plan') != ref.artifact.model_dump(mode='json'):
                raise BatchRuntimeError('core_reference_changed', 'preview plan reference differs')
            entry = PreviewEntry(reference=ref, preview=result.data)
            ids = subject_operations(entry).keys()
            if subjects.intersection(ids):
                raise BatchRuntimeError('subject_ambiguous', 'subject appears in multiple plans')
            subjects.update(ids)
            entries.append(entry)
        return BatchPreview(manifest_sha256=self.store.manifest_sha256, plans=tuple(entries))

    def _event(self, request_id, request):
        return BatchEvent(schema_version='paper_reader_batch.event.v3', request_id=request_id,
            manifest_sha256=self.store.manifest_sha256, request_fingerprint=canonical_sha256(request), request=request)

    def approve(self, preview: BatchPreview, *, selected_subject_ids: tuple[str, ...],
                expected_preview_sha256: str, confirmation_ref: str, request_id: str) -> tuple[BoundApprovalRef, ...]:
        preview = BatchPreview.model_validate_json(canonical_json_bytes(preview))
        if preview.sha256 != expected_preview_sha256 or preview != self.preview(self.manifest.plan_refs):
            raise BatchRuntimeError('preview_changed', 'entire preview must match the confirmed digest')
        subjects = {s for entry in preview.plans for s in subject_operations(entry)}
        selected = set(selected_subject_ids)
        if len(selected) != len(selected_subject_ids) or selected - subjects:
            raise BatchRuntimeError('selection_invalid', 'selection must name unique known subjects')
        if not selected:
            return ()
        if not confirmation_ref.strip():
            raise BatchRuntimeError('confirmation_required', 'explicit content confirmation required')
        event = self._event(request_id, ApproveRequest(command='approve', preview=preview,
            selected_subject_ids=selected_subject_ids, confirmation_ref=confirmation_ref))
        with self.store.request(event) as replayed:
            previous = self.store.result(event)
            if previous is not None:
                return previous.approval_refs
            if replayed:
                raise BatchRuntimeError('approval_uncertain', 'approval_uncertain: inspect partial approval receipts before a new explicit request')
            approvals = []
            for entry in preview.plans:
                ids = tuple(op['operation_id'] for subject, ops in subject_operations(entry).items()
                            if subject in selected for op in ops)
                if not ids:
                    continue
                ref = entry.reference
                args = self._plan_args('approve', ref) + ['--plan-sha256', ref.artifact.sha256,
                                                        '--confirmation-ref', confirmation_ref]
                for operation_id in ids:
                    args += ['--operation-id', operation_id]
                result = self._invoke(args)
                if (len(result.artifacts) != 1 or result.artifacts[0].role != 'zotero-approval'
                        or result.data.get('run_id') != ref.run_id
                        or result.data.get('plan') != ref.artifact.model_dump(mode='json')
                        or result.data.get('selected_operation_ids') != list(ids)):
                    raise BatchRuntimeError('core_response_invalid', 'approval response differs from selection')
                approval = BoundApprovalRef(run_root=ref.run_root, run_id=ref.run_id,
                                           artifact=result.artifacts[0], plan=ref.artifact)
                check_reference(approval)
                self.store.record_approval(event, len(approvals), approval)
                approvals.append(approval)
            result = tuple(approvals)
            self.store.complete(event, approvals=result)
            return result

    def _read_entries(self, result, refs):
        entries = result.data.get('entries')
        if not isinstance(entries, list) or len(entries) != len(refs):
            raise BatchRuntimeError('core_response_invalid', 'core report is missing entries')
        checked = []
        for entry, ref in zip(entries, refs):
            if not isinstance(entry, dict) or entry.get('reference') != ref.model_dump(mode='json'):
                raise BatchRuntimeError('core_response_invalid', 'core response belongs to another approval')
            report = entry.get('report')
            if (not isinstance(report, dict) or report.get('schema_version') != 'paper_reader.zotero-result.v3'
                    or report.get('plan') != ref.plan.model_dump(mode='json') or report.get('run_id') != ref.run_id
                    or not isinstance(entry.get('code'), str) or not isinstance(entry.get('selected_operation_ids'), list)):
                raise BatchRuntimeError('core_response_invalid', 'core report identity differs')
            checked.append(entry)
        return checked

    def _observations(self, entries):
        return {canonical_sha256(BoundArtifactRef(run_root=Path(e['reference']['run_root']),
                    run_id=e['reference']['run_id'], artifact=e['reference']['plan'])):
                    (e['code'], e['report']) for e in entries}

    def apply(self, approval_refs: tuple[BoundApprovalRef, ...], *, request_id: str):
        refs = tuple(BoundApprovalRef.model_validate_json(canonical_json_bytes(r)) for r in approval_refs)
        event = self._event(request_id, ApplyRequest(command='apply', approval_refs=refs))
        # Request identity is checked before any subprocess or coordination mutation.
        self.store._check(event)
        plan_refs = tuple(BoundArtifactRef(run_root=r.run_root, run_id=r.run_id, artifact=r.plan) for r in refs)
        if (len(set(canonical_sha256(r) for r in plan_refs)) != len(refs)
                or any(r not in self.manifest.plan_refs for r in plan_refs)):
            raise BatchRuntimeError('approval_mismatch', 'approval references must name unique manifest plans')
        for ref in refs:
            check_reference(ref)
        preview = self.preview(self.manifest.plan_refs)
        if not refs:
            return build_report(self.manifest, preview, set(), {})
        status = self._read_entries(self._invoke(self._approval_args('status', refs)), refs)
        selection = set()
        for entry, ref in zip(status, plan_refs):
            selected_ids = set(entry['selected_operation_ids'])
            shown = next(p for p in preview.plans if p.reference == ref)
            groups = subject_operations(shown)
            available = {op['operation_id'] for ops in groups.values() for op in ops}
            if not selected_ids or selected_ids - available or len(selected_ids) != len(entry['selected_operation_ids']):
                raise BatchRuntimeError('approval_mismatch', 'core selection names unknown or duplicate operations')
            for subject, ops in groups.items():
                ids = {op['operation_id'] for op in ops}
                if ids.intersection(selected_ids):
                    if not ids.issubset(selected_ids):
                        raise BatchRuntimeError('approval_mismatch', 'batch requires complete subject selections')
                    selection.add(subject)
        with self.store.request(event) as replayed:
            if not replayed:
                try:
                    status = self._read_entries(self._invoke(self._approval_args('apply', refs)), refs)
                except (CoreProcessLost, BatchRuntimeError):
                    # No trustworthy process outcome can authorize another apply.
                    status = self._recover(refs, status)
            else:
                status = self._recover(refs, status)
            report = build_report(self.manifest, preview, selection, self._observations(status))
            if self.store.result(event) is None:
                self.store.complete(event, approvals=refs, report=report)
            return report

    def _recover(self, refs, previous):
        recovered = []
        for ref, entry in zip(refs, previous):
            plan_ref = BoundArtifactRef(run_root=ref.run_root, run_id=ref.run_id, artifact=ref.plan)
            try:
                result = self._invoke(self._plan_args('reconcile', plan_ref) + ['--expected-sha256', ref.plan.sha256])
                updated = {**entry, 'code': 'ok', 'report': result.data}
                # Reuse the same identity check for individual read-only recovery.
                envelope = result.model_copy(update={'data': {'entries': [updated]}})
                recovered.extend(self._read_entries(envelope, (ref,)))
            except (CoreProcessLost, BatchRuntimeError):
                # Previous planned state cannot prove a timed-out child did not send.
                recovered.append({**entry, 'code': 'core_process_lost', 'report': {
                    **entry['report'], 'operations': []}})
        return recovered
