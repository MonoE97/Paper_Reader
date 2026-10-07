"""Projection of core previews and observations; no operation recovery decisions."""
import json
from pydantic import ValidationError

from paper_reader_batch.official_workflow.contracts import BatchReport, CoreArtifactRef, SubjectReport
from paper_reader_batch.v2_errors import BatchRuntimeError
from paper_reader_batch.v2_json import canonical_sha256


def subject_operations(entry):
    """Read only the presentation/selection fields in the core's preview response."""
    operations = entry.preview.get('operations')
    if not isinstance(operations, list) or not operations:
        raise BatchRuntimeError('core_response_invalid', 'preview has no operations')
    groups = {}
    for op in operations:
        if not isinstance(op, dict) or any(not isinstance(op.get(k), str) or not op[k]
                for k in ('subject_id', 'subject_title', 'operation_id')):
            raise BatchRuntimeError('core_response_invalid', 'preview selection fields missing')
        groups.setdefault(op['subject_id'], []).append(op)
    return groups


def build_report(manifest, preview, selected, observations):
    subjects = []
    for entry in preview.plans:
        observed = observations.get(canonical_sha256(entry.reference))
        for subject, operations in subject_operations(entry).items():
            status, sync, blockers, next_steps = 'skipped', 'sync_unobserved', (), ()
            observation = None
            if subject in selected:
                if observed is None:
                    status, blockers = 'uncertain', ('core_process_lost',)
                else:
                    code, report = observed
                    ids = {op['operation_id'] for op in operations}
                    results = [op for op in report.get('operations', []) if op.get('operation_id') in ids]
                    states = {op.get('state') for op in results}
                    blockers = tuple(dict.fromkeys([code] if code != 'ok' else [])) + tuple(dict.fromkeys(
                        b for op in results for b in op.get('blockers', [])))
                    next_steps = tuple(dict.fromkeys(n for op in results for n in op.get('next_steps', [])))
                    if states & {'started', 'uncertain'} or len(results) != len(ids):
                        status = 'uncertain'
                    elif code == 'ok' and states == {'verified'}:
                        status = 'verified'
                    else:
                        status = 'blocked'
                    sync = report.get('sync_status', 'sync_unobserved')
                    if report.get('remote_observation') is not None:
                        try:
                            observation = CoreArtifactRef.model_validate_json(json.dumps(report['remote_observation']))
                        except ValidationError:
                            raise BatchRuntimeError('core_response_invalid', 'invalid remote observation reference') from None
                    if sync == 'remote_observed' and (observation is None or status != 'verified'):
                        raise BatchRuntimeError('core_response_invalid', 'remote observation evidence missing')
            subjects.append(SubjectReport(subject_id=subject, title=operations[0]['subject_title'],
                plan=entry.reference, status=status, sync_status=sync, blockers=blockers, next_steps=next_steps,
                remote_observation=observation))
    return BatchReport(schema_version='paper_reader_batch.report.v3', manifest_sha256=preview.manifest_sha256,
                       plan_refs=manifest.plan_refs, subjects=tuple(subjects))
