"""Current-user, machine-bound local grants; never part of a run or release."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import pwd
import stat
import subprocess
import sys

from pydantic import SecretStr

from paper_reader.operations.contracts import WorkflowError
from paper_reader.storage import (
    atomic_write_bytes, open_directory_anchor, open_anchored_regular_file, stat_anchored_entry,
)


def machine_identity() -> str:
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/sbin/ioreg', '-rd1', '-c', 'IOPlatformExpertDevice', '-a'],
                                capture_output=True, check=True, timeout=5)
        value = plistlib.loads(result.stdout)[0]['IOPlatformUUID']
    elif sys.platform.startswith('linux'):
        value = Path('/etc/machine-id').read_text().strip()
    else:
        raise ValueError('unsupported local credential platform')
    if not isinstance(value, str) or not value.strip():
        raise ValueError('local machine identity unavailable')
    return hashlib.sha256(f'{value}:{os.getuid()}'.encode()).hexdigest()


def default_directory() -> Path:
    # Ignore HOME/XDG overrides: they can point into a repository or cloud folder.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if sys.platform == 'darwin':
        return home / 'Library/Application Support/Paper Reader/zotero-local'
    return home / '.config/paper-reader/zotero-local'


class LocalCredentialStore:
    def __init__(self, root: Path | None = None):
        self.root = root if root is not None else default_directory()

    def _identity(self, context):
        try:
            machine = machine_identity()
        except Exception:
            raise ValueError('local machine identity unavailable') from None
        return {'machine': machine, 'base_url': context.base_url, 'server_id': context.server_id}

    def _name(self, identity):
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        return self.root / f'{digest}.json'

    @staticmethod
    def _private(metadata, mode):
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != mode:
            raise ValueError('unsafe credential permissions')

    def _read(self, anchor, path, identity):
        metadata = stat_anchored_entry(anchor, path)
        if metadata.st_size > 4096:
            raise ValueError('credential record too large')
        with open_anchored_regular_file(anchor, path, expected_size=metadata.st_size) as held:
            self._private(os.fstat(held.descriptor), 0o600)
            content = os.pread(held.descriptor, 4097, 0)
            if hashlib.sha256(content).hexdigest() != held.content_sha256:
                raise ValueError('credential changed during read')
            raw = json.loads(content)
        if (not isinstance(raw, dict) or set(raw) != {'machine', 'base_url', 'server_id', 'remember', 'key'}
                or any(raw[k] != v for k, v in identity.items())):
            raise ValueError('invalid credential binding')
        if raw['remember'] is False and raw['key'] is None:
            return None  # An explicitly invalidated key; no deletion or old-key history.
        if raw['remember'] is not True or not isinstance(raw['key'], str) or len(raw['key']) != 32:
            raise ValueError('invalid persistent grant')
        return SecretStr(raw['key'])

    def load(self, context) -> SecretStr | None:
        try:
            identity = self._identity(context)
            with open_directory_anchor(self.root) as anchor:
                self._private(os.fstat(anchor.descriptor), 0o700)
                return self._read(anchor, self._name(identity), identity)
        except FileNotFoundError:
            return None
        except Exception:
            raise WorkflowError('verification_failed', 'local credential storage is unavailable or unsafe') from None

    def save(self, context, key: SecretStr | None) -> None:
        try:
            identity = self._identity(context)
            path = self._name(identity)
            with open_directory_anchor(self.root, create=True, mode=0o700) as anchor:
                self._private(os.fstat(anchor.descriptor), 0o700)
                try:
                    self._read(anchor, path, identity)
                except FileNotFoundError:
                    pass
                data = {**identity, 'remember': key is not None,
                        'key': key.get_secret_value() if key is not None else None}
                atomic_write_bytes(path, json.dumps(data).encode(), mode=0o600, anchor=anchor)
        except Exception:
            raise WorkflowError('verification_failed', 'local credential storage could not be updated safely') from None

    def invalidate(self, context) -> None:
        if self.load(context) is not None:
            self.save(context, None)
