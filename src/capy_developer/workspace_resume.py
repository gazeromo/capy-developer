"""Explicit, same-client workspace reopen; never invoked by work preparation."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

from .desktop.companion import require
from .desktop.setup import atomic
from .desktop.state import private_directory
from .errors import DeveloperError
from .installation import read_owned, roots
from .link_protocol import canonical


def native_client(adapter):
    require(adapter in ('muse', 'codex'), 'CLIENT_UNSUPPORTED', 'unsupported coding client')
    bundled = Path('/Applications/Codex.app/Contents/Resources/codex')
    if adapter == 'codex' and platform.system() == 'Darwin' and bundled.is_file():
        return str(bundled)
    executable = shutil.which(adapter)
    require(executable is not None, 'CLIENT_NOT_INSTALLED', 'install and sign in to the coding client first')
    return executable


def prepare(config, handoff_id, adapter):
    # Opaque reference only: prompts and URLs never enter shell source.
    import re
    require(isinstance(handoff_id, str) and bool(re.fullmatch(r'hof_[0-9a-f]{32}', handoff_id)),
            'WORK_INPUT_INVALID', 'provide an exact linked handoff')
    require(adapter in ('muse', 'codex'), 'CLIENT_UNSUPPORTED', 'unsupported coding client')
    if platform.system() != 'Darwin':
        return {'supported': False, 'reason': 'Explicit native reopen is currently qualified on macOS only.'}
    directory = config.data_root / 'workspace-resume' / handoff_id
    for path in (directory, *directory.parents):
        require(not path.is_symlink(), 'WORK_RESUME_CONFLICT', 'resume paths cannot pass through symlinks')
    private_directory(directory.parent)
    private_directory(directory)
    script = directory / 'resume.py'
    launcher = directory / ('Continue in ' + ('Muse' if adapter == 'muse' else 'Codex') + '.command')
    payload = ('import os\nos.environ.update(' + repr(roots(config)) + ')\n'
               'from capy_developer.cli import main\n'
               'raise SystemExit(main(' + repr(['work', 'resume', '--handoff-id', handoff_id]) + '))\n').encode()
    shell = ('#!/bin/sh\nexec ' + shlex.join([sys.executable, str(script)]) + '\n').encode()
    files = {script: payload, launcher: shell}
    receipt = directory / 'packet.json'
    recorded = canonical({'schema': 'capy.workspace-resume/v0', 'handoff_id': handoff_id,
                          'adapter': adapter, 'files': {str(p): hashlib.sha256(v).hexdigest() for p, v in files.items()}})
    if receipt.exists() or receipt.is_symlink():
        require(read_owned(receipt) == recorded, 'WORK_RESUME_CONFLICT', 'continuation ownership changed')
    else:
        require(not any(p.exists() or p.is_symlink() for p in files),
                'WORK_RESUME_CONFLICT', 'unowned continuation files already exist')
    for path, content in files.items():
        if path.exists() or path.is_symlink():
            require(read_owned(path) == content, 'WORK_RESUME_CONFLICT', 'existing continuation file was modified; preserve it')
    atomic(receipt, recorded)
    for path, content in files.items():
        atomic(path, content)
    launcher.chmod(0o700)
    return {'supported': True, 'label': 'Continue in prepared workspace', 'client': adapter,
            'launcher_path': str(launcher), 'requires_explicit_user_action': True}


def launch(harness, handoff_id, *, runner=None):
    # Resolve objective and workspace from the authoritative local association,
    # not from editable launcher payloads or the caller's working directory.
    import re
    require(isinstance(handoff_id, str) and bool(re.fullmatch(r'hof_[0-9a-f]{32}', handoff_id)),
            'WORK_INPUT_INVALID', 'provide an exact linked handoff')
    handoff = harness.companion.state.handoff(handoff_id)
    with harness.companion.state.connect() as db:
        rows = db.execute('''SELECT w.input,w.request,c.adapter FROM harness_work w
            JOIN harness_clients c ON c.site=w.site AND c.client=w.client
            WHERE w.site=? AND w.request IS NOT NULL''', (handoff['site_id'],)).fetchall()
    matches = [row for row in rows if json.loads(row['request'])['handoff_id'] == handoff_id]
    require(len(matches) == 1, 'WORK_RESUME_CONFLICT', 'continuation requires one exact local work association')
    adapter = matches[0]['adapter'].split(':', 1)[0]
    packet = prepare(harness.core.config, handoff_id, adapter)
    require(packet['supported'], 'WORK_RESUME_UNAVAILABLE', packet.get('reason', 'native reopen unavailable'))
    development = harness.core.inspect_development(handoff['session_id'])
    require(development['ok'] and development['status'] == 'READY' and development['workspace']['exists']
            and development['workspace']['branch_matches'], 'WORK_RESUME_UNAVAILABLE', 'this linked session is not ready to reopen')
    progress = harness.sync(handoff_id)
    require(progress['ok'], 'WORK_REPORT_PENDING', 'restore the linked connection before reopening this work')
    objective = json.loads(matches[0]['input'])['request']
    prompt = ('Continue the existing linked Capy work in this managed workspace. Read CAPY.md and '
              '.capy-local/handoff.json; attach through capy_development_attach using handoff ' + handoff_id +
              '. Preserve this session and project. User objective: ' + objective +
              '\nUse normal native edits and Git approvals. Verify the exact full commit, repair failures, '
              'create a candidate only after verification passes, then finish and call capy_work_sync '
              'to confirm acknowledgment and return the review URL. Source sending, acceptance and '
              'installation retain separate owner consent. Review URL: ' + progress['review_url'])
    command = [native_client(adapter), '--workspace' if adapter == 'muse' else '--cd',
               development['workspace']['native_path'], prompt]
    # argv only; never a shell, hidden launch, sandbox override, or provider override.
    result = (runner or subprocess.run)(command, check=False)
    return {'ok': result.returncode == 0, 'client': adapter, 'exit_code': result.returncode,
            'handoff_id': handoff_id, 'review_url': progress['review_url']}
