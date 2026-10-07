"""Synthetic core wire responses, never network or credential access."""
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from paper_reader_batch.v2_json import canonical_json_bytes, sha256_bytes


@pytest.fixture
def api():
    assert importlib.util.find_spec('paper_reader_batch.official_workflow'), 'T8 batch workflow missing'
    return SimpleNamespace(**{name: importlib.import_module(f'paper_reader_batch.official_workflow.{name}')
                             for name in ('contracts', 'driver', 'client')})


@pytest.fixture
def batch(api, tmp_path):
    c = api.contracts
    core_root = tmp_path / 'separate' / 'core'
    core_root.mkdir(parents=True)
    run_root = tmp_path / 'batch'
    run_root.mkdir()
    refs, previews = [], {}
    for name in 'ABC':
        root = tmp_path / f'run-{name}'
        root.mkdir()
        raw = canonical_json_bytes({'schema_version': 'paper_reader.zotero-plan.v3', 'name': name})
        (root / 'plan.json').write_bytes(raw)
        ref = c.BoundArtifactRef(run_root=root, run_id=name,
            artifact=c.CoreArtifactRef(role='zotero-plan', path='plan.json', sha256=sha256_bytes(raw), size_bytes=len(raw)))
        refs.append(ref)
        previews[name] = {'plan': ref.artifact.model_dump(mode='json'), 'context': {}, 'content': [],
            'operations': [{'operation_id': f'op_{name}', 'subject_id': name, 'subject_title': f'Paper {name}',
                'type': 'create_note', 'reason': '已核对论文证据。', 'blockers': [], 'depends_on': [],
                'payload': {'html': '<h1>完整笔记</h1>'}}], 'import_details': None}

    class Core:
        paper_reader_root = core_root
        coordination_root = core_root / '.paper_reader_official'
        def __init__(self):
            self.calls, self.sends = [], []
            self.states = {name: 'planned' for name in 'ABC'}
            self.lose_response = False
            self.approve_loss = False
        def invoke(self, args):
            self.calls.append(args)
            action = args[1]
            if action in ('apply', 'status'):
                entries = []
                for i, arg in enumerate(args):
                    if arg != '--approval': continue
                    ref = c.BoundApprovalRef.model_validate_json(args[i+1])
                    name = ref.run_id
                    if action == 'apply':
                        self.sends.append(name)
                        self.states[name] = 'verified' if name != 'C' else 'uncertain'
                    entries.append({'reference': ref.model_dump(mode='json'), 'code': 'ok',
                        'selected_operation_ids': [f'op_{name}'], 'report': self.report(name, ref.plan)})
                if action == 'apply' and self.lose_response:
                    raise api.client.CoreProcessLost('core_process_lost', 'synthetic lost process')
                data, artifacts = {'entries': entries}, ()
            else:
                root = Path(args[args.index('--run-root')+1])
                name = next(r.run_id for r in refs if r.run_root == root)
                if action == 'preview': data, artifacts = previews[name], ()
                elif action == 'reconcile': data, artifacts = self.report(name, refs['ABC'.index(name)].artifact), ()
                elif action == 'approve':
                    if self.approve_loss: raise api.client.CoreProcessLost('core_process_lost', 'lost approve')
                    selected = tuple(args[i+1] for i, a in enumerate(args) if a == '--operation-id')
                    for op in previews[name]['operations']:
                        if op['operation_id'] in selected and set(op['depends_on']) - set(selected):
                            return self.result(action, None, (), code='dependency_excluded')
                    raw = canonical_json_bytes({'schema_version': 'paper_reader.zotero-approval.v3', 'selected_operation_ids': selected})
                    path = f'approval-{uuid4().hex}.json'
                    (root / path).write_bytes(raw)
                    artifacts = (c.CoreArtifactRef(role='zotero-approval', path=path, sha256=sha256_bytes(raw), size_bytes=len(raw)),)
                    data = {'run_id': name, 'plan': refs['ABC'.index(name)].artifact.model_dump(mode='json'), 'selected_operation_ids': list(selected)}
                else: raise AssertionError(args)
            return self.result(action, data, artifacts)
        def result(self, action, data, artifacts, code='ok'):
            return c.CoreCommandResult(schema_version='paper_reader.command-result.v3', command=f'plan {action}',
                ok=code == 'ok', code=code, created_at='2026-10-07T00:00:00Z', artifacts=artifacts, data=data)
        def report(self, name, plan):
            state = self.states[name]
            return {'schema_version': 'paper_reader.zotero-result.v3', 'run_id': name,
                'plan': plan.model_dump(mode='json'), 'operations': [{'operation_id': f'op_{name}', 'state': state,
                'blockers': [], 'next_steps': []}], 'local_status': 'local_verified' if state == 'verified' else 'incomplete',
                'sync_status': 'sync_unobserved', 'remote_observation': None}
    core = Core()
    manifest = c.BatchManifest(schema_version='paper_reader_batch.manifest.v3', batch_id='batch_test',
        paper_reader_root=core_root, plan_refs=tuple(refs))
    driver = api.driver.BatchDriver(client=core, run_root=run_root, manifest=manifest)
    return SimpleNamespace(api=api, core=core, manifest=manifest, driver=driver, refs=tuple(refs), root=run_root, previews=previews)
