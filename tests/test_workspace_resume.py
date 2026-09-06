import json
from pathlib import Path
import subprocess

import pytest

from capy_developer import workspace_resume
from capy_developer.errors import DeveloperError
from test_installation_discovery import config


HANDOFF = 'hof_' + 'a' * 32


def test_packet_replays_and_quotes_only_fixed_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_resume.platform, 'system', lambda: 'Darwin')
    cfg = config(tmp_path / 'spaces and $literal')
    result = workspace_resume.prepare(cfg, HANDOFF, 'muse')
    path = Path(result['launcher_path'])
    assert result['requires_explicit_user_action']
    assert workspace_resume.prepare(cfg, HANDOFF, 'muse') == result
    assert subprocess.run(['/bin/sh', '-n', str(path)]).returncode == 0
    assert path.stat().st_mode & 0o777 == 0o700
    assert '$literal' in path.read_text()
    compile((path.parent / 'resume.py').read_text(), 'resume.py', 'exec')
    (path.parent / 'resume.py').write_text('owner edits')
    with pytest.raises(DeveloperError):
        workspace_resume.prepare(cfg, HANDOFF, 'muse')
    assert (path.parent / 'resume.py').read_text() == 'owner edits'


def test_packet_refuses_unowned_files_and_bad_references(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_resume.platform, 'system', lambda: 'Darwin')
    cfg = config(tmp_path)
    directory = cfg.data_root / 'workspace-resume' / HANDOFF
    directory.mkdir(parents=True, mode=0o700)
    directory.parent.chmod(0o700)
    (directory / 'resume.py').write_text('keep me')
    with pytest.raises(DeveloperError):
        workspace_resume.prepare(cfg, HANDOFF, 'muse')
    assert not (directory / 'packet.json').exists()
    with pytest.raises(DeveloperError):
        workspace_resume.prepare(cfg, '../other', 'muse')


def test_unqualified_platform_has_no_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_resume.platform, 'system', lambda: 'Windows')
    cfg = config(tmp_path)
    assert not workspace_resume.prepare(cfg, HANDOFF, 'muse')['supported']
    assert not (cfg.data_root / 'workspace-resume').exists()
