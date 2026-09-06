"""Native Muse user-skill adapter; never edits Muse settings or its lockfile."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from .desktop.companion import require
from .desktop.setup import atomic
from .errors import DeveloperError
from .installation import read_owned
from .link_protocol import canonical
from .util import operation_lock


class MuseGuidance:
    name = 'capy-development'

    def __init__(self, setup_root, executable, *, config_root=None, environment=None):
        self.root = setup_root
        self.executable = str(executable)
        self.environment = dict(os.environ if environment is None else environment)
        self.config = Path(config_root) if config_root is not None else Path(
            self.environment.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'muse'
        self.target = self.config / 'skills' / self.name
        self.receipt = self.root / 'muse-guidance.json'

    def _call(self, *arguments, missing=False):
        try:
            result = subprocess.run([self.executable, 'skills', *arguments, '--json'],
                env=self.environment, capture_output=True, text=True, timeout=30)
            require(len(result.stdout) <= 65536, 'CLIENT_ADAPTER_FAILED', 'Muse returned an oversized skill result')
            value = json.loads(result.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            raise DeveloperError('CLIENT_ADAPTER_FAILED', 'the native Muse skill command did not return a valid result') from None
        require(isinstance(value, dict), 'CLIENT_ADAPTER_FAILED', 'invalid Muse skill result')
        error = value.get('error')
        if missing and result.returncode != 0 and isinstance(error, dict) and error.get('code') == 'unknown-skill':
            return None
        require(result.returncode == 0 and 'error' not in value, 'CLIENT_ADAPTER_FAILED', 'the native Muse skill command failed; existing files were preserved')
        return value

    def _inspect(self):
        value = self._call('inspect', self.name, '--source', 'user', missing=True)
        if value is not None:
            skill = value.get('skill', {})
            require(isinstance(skill, dict) and skill.get('id') == self.name and skill.get('scope') == 'user',
                'CLIENT_SETUP_CONFLICT', 'Muse resolved another skill identity')
        return value

    @staticmethod
    def _hashes(directory):
        require(not any(p.is_symlink() for p in (directory, *directory.parents)),
            'CLIENT_SETUP_CONFLICT', 'native skill paths cannot pass through symlinks')
        require(directory.is_dir(), 'CLIENT_SETUP_CONFLICT', 'native skill directory is missing')
        paths = list(directory.iterdir())
        require({p.name for p in paths} == {'SKILL.md', 'entry.py'},
            'CLIENT_SETUP_CONFLICT', 'native skill contains unexpected files; preserve it for inspection')
        return {p.name:hashlib.sha256(read_owned(p)).hexdigest() for p in paths}

    def _saved(self):
        if not self.receipt.exists():
            require(not self.receipt.is_symlink(), 'CLIENT_SETUP_CONFLICT', 'invalid native ownership receipt')
            return None
        try:
            value = json.loads(read_owned(self.receipt))
        except (ValueError, UnicodeError):
            raise DeveloperError('CLIENT_SETUP_CONFLICT', 'invalid native ownership receipt') from None
        require(isinstance(value, dict) and value.get('schema') == 'capy.muse-guidance/v0' and value.get('target') == str(self.target),
            'CLIENT_SETUP_CONFLICT', 'native guidance belongs to a different installation')
        return value

    def _shared_discovery(self, installed, source=None):
        """Recognize only the exact files recorded by the shared setup transaction."""
        if installed is None or self.target.exists() or self.target.is_symlink():
            return False
        receipt = self.root / 'ownership.json'
        if not receipt.exists():
            return False
        try:
            saved = json.loads(read_owned(receipt))
            if saved.get('schema') != 'capy.client-setup/v0' or saved.get('state') not in ('PREPARING', 'CONFIGURED'):
                return False
            files = saved.get('files', {})
            guides = [Path(path) for path in files if Path(path).name == 'SKILL.md']
            if len(guides) != 1:
                return False
            directory = guides[0].parent
            if source is not None and directory != source:
                return False
            actual = self._hashes(directory)
            if files != {str(directory / name): digest for name, digest in actual.items()}:
                return False
            path = installed.get('skill', {}).get('path')
            if not isinstance(path, str):
                return False
            if path.startswith('$HOME/'):
                path = str(Path(self.environment['HOME']) / path[len('$HOME/'):])
            return path == str(directory / 'SKILL.md')
        except (ValueError, TypeError, KeyError, AttributeError, OSError, DeveloperError):
            return False

    def preflight(self, source):
        expected = self._hashes(source) if source.exists() else None
        saved = self._saved()
        installed = self._inspect()
        if self._shared_discovery(installed, source):
            installed = None
        if installed is not None or self.target.exists() or self.target.is_symlink():
            require(saved is not None and installed is not None and saved.get('state') in ('PREPARING', 'CONFIGURED'),
                'CLIENT_SETUP_CONFLICT', 'an existing native Muse skill is not owned by this setup')
            actual = self._hashes(self.target)
            require(actual == saved.get('files') and (expected is None or actual == expected),
                'CLIENT_SETUP_CONFLICT', 'native Muse guidance was modified; preserve it')
        return installed

    def install(self, source):
        with operation_lock(self.root / 'muse-guidance.lock'):
            installed = self.preflight(source)
            expected = self._hashes(source)
            receipt = dict(schema='capy.muse-guidance/v0', state='PREPARING', target=str(self.target), files=expected)
            atomic(self.receipt, canonical(receipt))
            if installed is None:
                # Native install owns conflict detection and its own lockfile. Never --force.
                self._call('install', str(source), '--scope', 'user', '--name', self.name)
            require(self._inspect() is not None and self._hashes(self.target) == expected,
                'CLIENT_ADAPTER_FAILED', 'Muse did not discover the exact installed guidance')
            receipt['state'] = 'CONFIGURED'
            atomic(self.receipt, canonical(receipt))
            return str(self.target / 'SKILL.md')

    def preflight_remove(self):
        saved = self._saved()
        require(saved is not None, 'CLIENT_SETUP_CONFLICT', 'no owned native Muse integration to remove')
        installed = self._inspect()
        if self._shared_discovery(installed):
            installed = None
        if installed is not None:
            require(saved.get('state') in ('PREPARING','CONFIGURED','REMOVING') and self._hashes(self.target) == saved.get('files'),
                'CLIENT_SETUP_CONFLICT', 'native Muse guidance changed; removal refused')
        else:
            require(not self.target.exists() and not self.target.is_symlink(),
                'CLIENT_SETUP_CONFLICT', 'unrecognized native guidance files remain; preserve them')
        return saved, installed

    def remove(self):
        with operation_lock(self.root / 'muse-guidance.lock'):
            saved, installed = self.preflight_remove()
            if installed is not None:
                saved['state'] = 'REMOVING'
                atomic(self.receipt, canonical(saved))
                self._call('uninstall', self.name)
            remaining = self._inspect()
            require((remaining is None or self._shared_discovery(remaining)) and not self.target.exists(),
                'CLIENT_ADAPTER_FAILED', 'Muse integration removal is incomplete')
            saved['state'] = 'REMOVED'
            atomic(self.receipt, canonical(saved))
            return {'ok':True, 'status':'REMOVED', 'client':'muse', 'shared_installation_preserved':True}
