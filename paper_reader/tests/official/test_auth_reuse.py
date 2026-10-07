"""Persistence, safe diagnostics and real executor behavior with synthetic HTTP only."""
import importlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import traceback

import pytest

from paper_reader.official.auth import NativeCredentialProvider
from paper_reader.official.credentials import default_directory
from paper_reader.official.models import LibraryContext
from paper_reader.operations.contracts import WorkflowError
from test_auth import KEY, Transport
from test_import_execution import imported, apply, restart


@pytest.fixture(autouse=True)
def isolated_credentials(tmp_path, monkeypatch):
    from paper_reader.official import credentials
    monkeypatch.setattr(credentials, 'default_directory', lambda: tmp_path / 'credentials')


def test_persistent_grant_reused_by_a_new_provider(context_data, tmp_path):
    context = LibraryContext(**context_data)
    transport = Transport({'key': KEY, 'remember': True})
    assert NativeCredentialProvider(transport).get_key(context).get_secret_value() == KEY
    no_prompt = Transport(AssertionError('unexpected authorization'))
    assert NativeCredentialProvider(no_prompt).get_key(context).get_secret_value() == KEY
    assert no_prompt.calls == []
    saved, = tmp_path.rglob('*.json')
    assert saved.stat().st_mode & 0o777 == 0o600
    assert saved.parent.stat().st_mode & 0o777 == 0o700


def test_single_use_grant_never_persisted(context_data, tmp_path):
    transport = Transport({'key': KEY, 'remember': False})
    provider = NativeCredentialProvider(transport)
    context = LibraryContext(**context_data)
    assert provider.get_key(context).get_secret_value() == KEY
    with pytest.raises(WorkflowError, match='auth_required'):
        provider.get_key(context)
    assert len(transport.calls) == 1
    assert not list(tmp_path.rglob('*.json'))


def test_saved_grant_survives_actual_python_process_restart(context_data, tmp_path):
    NativeCredentialProvider(Transport({'key': KEY, 'remember': True})).get_key(LibraryContext(**context_data))
    saved, = tmp_path.rglob('*.json')
    script = '''
import json, sys
from pathlib import Path
from paper_reader.official.auth import NativeCredentialProvider
from paper_reader.official.credentials import LocalCredentialStore
from paper_reader.official.models import LibraryContext
class NoNetwork:
    def request(self, *args, **kwargs):
        raise AssertionError('process restart requested authorization')
provider = NativeCredentialProvider(NoNetwork(), store=LocalCredentialStore(Path(sys.argv[1])))
key = provider.get_key(LibraryContext(**json.loads(sys.argv[2])))
assert len(key.get_secret_value()) == 32
print('reused')
'''
    result = subprocess.run([sys.executable, '-c', script, str(saved.parent), json.dumps(context_data)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0 and result.stdout == 'reused\n', result.stderr
    assert KEY not in result.stdout + result.stderr


def test_instance_and_machine_partition(context_data, tmp_path, monkeypatch):
    assert importlib.util.find_spec('paper_reader.official.credentials'), 'local credential store missing'
    module = importlib.import_module('paper_reader.official.credentials')
    context = LibraryContext(**context_data)
    NativeCredentialProvider(Transport({'key': KEY, 'remember': True})).get_key(context)
    for changes in ({'server_id': 'other-instance'}, {'base_url': 'http://127.0.0.1:23120/api/'}):
        denied = Transport({}, status=403, server=changes.get('server_id', context.server_id))
        with pytest.raises(WorkflowError, match='auth_denied'):
            NativeCredentialProvider(denied).get_key(context.model_copy(update=changes))
        assert len(denied.calls) == 1
    monkeypatch.setattr(module, 'machine_identity', lambda: 'another-machine')
    denied = Transport({}, status=403)
    with pytest.raises(WorkflowError, match='auth_denied'):
        NativeCredentialProvider(denied).get_key(context)
    assert len(denied.calls) == 1


@pytest.mark.parametrize('damage', ['permissions', 'symlink', 'hardlink', 'directory_link', 'corrupt'])
def test_unsafe_credential_file_never_loaded_or_reprompted(context_data, tmp_path, damage):
    context = LibraryContext(**context_data)
    NativeCredentialProvider(Transport({'key': KEY, 'remember': True})).get_key(context)
    saved, = tmp_path.rglob('*.json')
    if damage == 'permissions':
        saved.chmod(0o644)
    elif damage == 'symlink':
        target = saved.with_suffix('.original')
        saved.rename(target)
        saved.symlink_to(target)
    elif damage == 'hardlink':
        os.link(saved, saved.with_suffix('.hardlink'))
    elif damage == 'directory_link':
        target = saved.parent.with_name('original-dir')
        saved.parent.rename(target)
        saved.parent.symlink_to(target, target_is_directory=True)
    else:
        saved.write_text('{')
    transport = Transport({'key': KEY, 'remember': True})
    with pytest.raises(WorkflowError, match='verification_failed') as error:
        NativeCredentialProvider(transport).get_key(context)
    assert transport.calls == []
    assert KEY not in ''.join(traceback.format_exception(error.value))


def test_missing_machine_identity_is_not_missing_authorization(context_data, monkeypatch):
    from paper_reader.official import credentials
    def unavailable():
        raise FileNotFoundError('machine id unavailable')
    monkeypatch.setattr(credentials, 'machine_identity', unavailable)
    transport = Transport({'key': KEY, 'remember': True})
    with pytest.raises(WorkflowError, match='verification_failed'):
        NativeCredentialProvider(transport).get_key(LibraryContext(**context_data))
    assert not transport.calls


def test_default_directory_uses_os_user_home_not_environment(tmp_path, monkeypatch):
    import pwd
    monkeypatch.setattr(Path, 'home', lambda: tmp_path / 'project')
    real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    assert default_directory().is_relative_to(real_home)
    assert not default_directory().is_relative_to(tmp_path)


def test_changed_bytes_after_file_open_do_not_return_a_key(context_data, tmp_path, monkeypatch):
    from paper_reader.official import credentials
    context = LibraryContext(**context_data)
    NativeCredentialProvider(Transport({'key': KEY, 'remember': True})).get_key(context)
    saved, = tmp_path.rglob('*.json')
    original = credentials.open_anchored_regular_file
    def replace_after_open(*args, **kwargs):
        held = original(*args, **kwargs)
        raw = json.loads(saved.read_text())
        raw['key'] = 'b' * 32
        saved.write_text(json.dumps(raw))
        return held
    monkeypatch.setattr(credentials, 'open_anchored_regular_file', replace_after_open)
    with pytest.raises(WorkflowError, match='verification_failed'):
        credentials.LocalCredentialStore(saved.parent).load(context)


def test_invalidation_clears_persistent_grant_without_a_new_dialog(context_data, tmp_path):
    context = LibraryContext(**context_data)
    transport = Transport({'key': KEY, 'remember': True})
    provider = NativeCredentialProvider(transport)
    provider.get_key(context)
    provider.invalidate(context)
    with pytest.raises(WorkflowError, match='auth_required'):
        provider.get_key(context)
    assert len(transport.calls) == 1
    assert all(KEY not in f.read_text() for f in tmp_path.rglob('*.json'))
    next_transport = Transport({}, status=403)
    with pytest.raises(WorkflowError, match='auth_denied'):
        NativeCredentialProvider(next_transport).get_key(context)
    assert len(next_transport.calls) == 1


@pytest.mark.parametrize('stage', ['create', 'upload_authorize', 'upload_register', 'upload_transfer'])
@pytest.mark.parametrize('fault', [401, 403, 412, 429, 'before'])
def test_only_authenticated_401_invalidates_key(imported, stage, fault):
    w = imported()
    w.transport.faults[stage] = fault
    result = apply(w)
    assert result.local_status == 'incomplete'
    assert w.credentials.invalidated == int(fault == 401 and stage != 'upload_transfer')
    assert sum(c[0] == stage for c in w.transport.calls) == 1


def test_whole_import_uses_one_persistent_authorization(imported, caplog):
    w = imported()
    caplog.set_level(logging.DEBUG, logger='paper_reader.official')
    authorizer = Transport({'key': KEY, 'remember': True})
    w.credentials = NativeCredentialProvider(authorizer)
    assert apply(w).local_status == 'local_verified'
    assert len(authorizer.calls) == 1
    for stage, _, headers, _ in w.transport.calls:
        if stage == 'upload_transfer':
            assert 'Zotero-API-Key' not in headers
        else:
            assert headers['Zotero-API-Key'] == KEY
            assert headers['Zotero-Server-ID'] == w.live.context.server_id
    records = [json.loads(r.message) for r in caplog.records if r.name.startswith('paper_reader.official')]
    assert records and any(r['remember'] is True for r in records)
    assert all(set(r) == {'has_key', 'remember', 'path', 'status'} for r in records)
    assert KEY not in caplog.text and 'temporary0' not in caplog.text
    assert any(r['path'] == '/api/local/uploads/{uploadKey}' and r['status'] == 201 for r in records)
    restart(w)
    no_prompt = Transport(AssertionError('replay must not authorize'))
    w.credentials = NativeCredentialProvider(no_prompt)
    sent = len(w.transport.calls)
    assert apply(w).local_status == 'local_verified'
    assert not no_prompt.calls and len(w.transport.calls) == sent


@pytest.mark.parametrize('status,code', [(401, 'auth_required'), (403, 'auth_denied'),
                                      (412, 'instance_changed'), (429, 'rate_limited')])
def test_failed_authorization_logs_only_safe_fields(context_data, status, code, caplog):
    caplog.set_level(logging.DEBUG, logger='paper_reader.official')
    transport = Transport({'key': KEY, 'secret': KEY}, status=status)
    provider = NativeCredentialProvider(transport)
    for _ in range(2):
        with pytest.raises(WorkflowError, match=code):
            provider.get_key(LibraryContext(**context_data))
    assert len(transport.calls) == 1
    records = [json.loads(r.message) for r in caplog.records if r.name.startswith('paper_reader.official')]
    assert len(records) == 1
    assert records[0] == {'has_key': False, 'remember': None, 'path': '/api/local/authorize', 'status': status}
    assert KEY not in caplog.text
