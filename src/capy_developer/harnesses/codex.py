from __future__ import annotations

from pathlib import Path
import platform
import subprocess
from urllib.parse import quote

from ..errors import DeveloperError


class CodexAdapter:
    adapter_id = 'codex-desktop/v0'

    def launch(self, workspace: Path) -> dict:
        if platform.system() != 'Darwin':
            raise DeveloperError('HARNESS_LAUNCH_UNSUPPORTED', 'Codex desktop handoff is qualified only on macOS; use the interactive CLI on this platform')
        if not workspace.is_absolute() or not workspace.is_dir():
            raise DeveloperError('HARNESS_WORKSPACE_INVALID', 'prepared workspace is unavailable')
        uri = 'codex://threads/new?path=' + quote(str(workspace), safe='')
        try:
            subprocess.run(['/usr/bin/open', uri], check=True, timeout=15, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            raise DeveloperError('HARNESS_LAUNCH_UNSUPPORTED', 'install and sign in to the supported Codex desktop client') from None
        return {'adapter': self.adapter_id, 'dispatched': True, 'attached': False}
