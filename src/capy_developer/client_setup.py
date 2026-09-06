"""Ownership-checked shared workflow guidance and native coding-client adapters."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from .desktop.companion import require
from .desktop.setup import Setup, atomic
from .desktop.state import private_directory
from .installation import read_owned, roots, validate_catalog
from .link_protocol import canonical
from .util import operation_lock


class ClientSetup:
    def __init__(self, core, *, skills: Path, locator: Path, codex_config: Path, muse=None, muse_mcp=None):
        self.core, self.skills, self.locator, self.codex_config = core, skills, locator, codex_config
        self.root = core.config.data_root / 'client-setup'
        private_directory(self.root)
        self.receipt = self.root / 'ownership.json'
        self.muse = muse
        self.muse_mcp = muse_mcp

    def _files(self):
        # Only Capy variables are set in this private fixed shim. No shell parsing.
        shim = ('import os\n' + 'os.environ.update(' + repr(roots(self.core.config)) + ')\n'
                + 'from capy_developer.cli import main\nraise SystemExit(main())\n').encode()
        entry = self.skills / 'capy-development' / 'entry.py'
        guide = (Path(__file__).parent / 'data/capy-development.md').read_bytes()
        guide += ('\nLocal entrypoint (argument array; preserve spaces):\n\n```json\n' +
                  json.dumps([sys.executable, str(entry)]) + '\n```\n').encode()
        return {entry:shim, entry.parent / 'SKILL.md':guide}

    def install(self, adapter):
        require(adapter in ('muse','codex'), 'CLIENT_UNSUPPORTED', 'unsupported coding client')
        validate_catalog(self.core.config)
        with operation_lock(self.root / 'setup.lock'):
            files = self._files()
            if adapter == 'muse' and self.muse is not None:
                self.muse.preflight(self.skills / 'capy-development')
            if adapter == 'muse' and self.muse_mcp is not None:
                self.muse_mcp.preflight()
            for path in (*files, self.locator, self.core.config.data_root / 'installation.json'):
                require(not any(p.is_symlink() for p in (path,*path.parents)),
                        'CLIENT_SETUP_CONFLICT', 'client setup paths cannot pass through symlinks')
            if adapter == 'codex':
                setup = Setup(self.core, config_path=self.codex_config)
                old = setup._read()
                if old is not None:
                    intact = setup.inspect()['mcp_owned_entry_intact']
                    recoverable = (old.get('status') == 'PREPARING' and old.get('config_path') == str(self.codex_config)
                                   and old.get('mcp_block') == setup._block().decode()
                                   and hashlib.sha256(setup._config()).hexdigest() == old.get('before_sha256'))
                    require(intact or recoverable, 'CLIENT_SETUP_CONFLICT', 'the historical Codex entry is modified')
                else:
                    import tomllib
                    raw = setup._config()
                    require('capy_developer' not in tomllib.loads(raw.decode()).get('mcp_servers', {})
                            and b'BEGIN CAPY DEVELOPER' not in raw, 'CLIENT_SETUP_CONFLICT', 'the existing Codex entry is not owned')
            previous = json.loads(read_owned(self.receipt)) if self.receipt.exists() else None
            if previous is not None:
                require(isinstance(previous, dict) and previous.get('schema') == 'capy.client-setup/v0', 'CLIENT_SETUP_CONFLICT', 'invalid client setup ownership receipt')
                require(previous.get('files') == {str(p):hashlib.sha256(v).hexdigest() for p,v in files.items()},
                        'CLIENT_SETUP_CONFLICT', 'existing guidance belongs to another exact environment')
            else:
                directory = self.skills / 'capy-development'
                require(not directory.exists() and not directory.is_symlink(), 'CLIENT_SETUP_CONFLICT', 'existing Capy skill is not owned by this setup')
            for path, payload in files.items():
                if path.exists() or path.is_symlink():
                    require(read_owned(path) == payload, 'CLIENT_SETUP_CONFLICT', 'owned guidance changed; preserve it and inspect setup')
            installation = self.core.config.data_root / 'installation.json'
            installation_payload = canonical({'schema':'capy.installation/v0','roots':roots(self.core.config)})
            if installation.exists() or installation.is_symlink():
                require(read_owned(installation) == installation_payload, 'CLIENT_SETUP_CONFLICT', 'installation receipt changed')
            locator_payload = canonical({'schema':'capy.installation-locator/v0','receipt':str(installation),
                                         'sha256':hashlib.sha256(installation_payload).hexdigest()})
            if self.locator.exists() or self.locator.is_symlink():
                require(read_owned(self.locator) == locator_payload, 'CLIENT_SETUP_CONFLICT', 'a different installation owns the locator')
            adapters = sorted(set((previous or {}).get('adapters', [])) | {adapter})
            receipt = {'schema':'capy.client-setup/v0', 'state':'PREPARING','adapters':adapters,
                       'files':{str(p):hashlib.sha256(v).hexdigest() for p,v in files.items()}}
            atomic(self.receipt, canonical(receipt))
            for path, payload in files.items():
                if path.exists() or path.is_symlink():
                    require(read_owned(path) == payload, 'CLIENT_SETUP_CONFLICT', 'guidance changed during setup')
                atomic(path, payload)
            atomic(installation, installation_payload)
            atomic(self.locator, locator_payload)
            if adapter == 'codex':
                setup = Setup(self.core, config_path=self.codex_config)
                old = setup._read()
                if old is None or old.get('status') == 'PREPARING':
                    setup.install(native=False)
                else:
                    require(setup.inspect()['mcp_owned_entry_intact'], 'CLIENT_SETUP_CONFLICT', 'the historical Codex entry is modified')
            receipt['state'] = 'CONFIGURED'
            instruction = str(self.skills / 'capy-development/SKILL.md')
            if adapter == 'muse' and self.muse is not None:
                instruction = self.muse.install(self.skills / 'capy-development')
            if adapter == 'muse' and self.muse_mcp is not None:
                self.muse_mcp.install()
            atomic(self.receipt, canonical(receipt))
            return {'ok':True,'status':'CONFIGURED','ready':False,
                    'transport':'MCP_STDIO' if adapter == 'codex' or self.muse_mcp is not None else 'JSON_CLI',
                    'instruction':instruction,
                    'reload':'A fresh client session may be required to load the tools and guidance.'}
