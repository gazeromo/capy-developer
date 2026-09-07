import json
from pathlib import Path
import subprocess
import shutil
import os

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
    shell=shutil.which('sh')
    assert shell is not None, 'launcher syntax qualification requires sh'
    assert subprocess.run([shell, '-n', str(path)]).returncode == 0
    if os.name != 'nt':
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


def test_packet_retains_profile_on_replay_without_capturing_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_resume.platform, 'system', lambda: 'Darwin')
    profile=tmp_path/'original profile with spaces'
    monkeypatch.setenv('HOME',str(profile))
    monkeypatch.setenv('CODEX_HOME',str(profile/'.codex'))
    monkeypatch.setenv('CAPY_TEST_SECRET','must-not-be-persisted')
    monkeypatch.delenv('XDG_DATA_HOME',raising=False)
    cfg=config(tmp_path/'data')
    result=workspace_resume.prepare(cfg,HANDOFF,'codex')
    directory=Path(result['launcher_path']).parent
    original=(directory/'resume.py').read_bytes()
    receipt=json.loads((directory/'packet.json').read_bytes())
    assert receipt['client_environment']['CODEX_HOME']==str(profile/'.codex')
    assert 'CAPY_TEST_SECRET' not in receipt['client_environment']
    assert b'must-not-be-persisted' not in original
    monkeypatch.setenv('HOME',str(tmp_path/'another profile'))
    monkeypatch.setenv('CODEX_HOME',str(tmp_path/'another codex'))
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path/'unrelated data'))
    assert workspace_resume.prepare(cfg,HANDOFF,'codex')==result
    assert (directory/'resume.py').read_bytes()==original
    # Execute the saved environment assignment only: no client or CLI action.
    import ast
    module=ast.parse(original)
    end=next(i for i,node in enumerate(module.body) if isinstance(node,ast.ImportFrom))
    prefix=ast.Module(body=module.body[:end],type_ignores=[])
    before=dict(os.environ)
    try:
        exec(compile(prefix,'saved-profile','exec'),{})
        assert os.environ['HOME']==str(profile)
        assert os.environ['CODEX_HOME']==str(profile/'.codex')
        assert 'XDG_DATA_HOME' not in os.environ
    finally:
        os.environ.clear();os.environ.update(before)


def test_legacy_packet_is_preserved_without_profile_upgrade(tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setattr(workspace_resume.platform, 'system', lambda: 'Darwin')
    cfg=config(tmp_path)
    result=workspace_resume.prepare(cfg,HANDOFF,'muse')
    directory=Path(result['launcher_path']).parent
    script=directory/'resume.py'
    legacy=('import os\nos.environ.update('+repr(workspace_resume.roots(cfg))+')\n'
            'from capy_developer.cli import main\n'
            'raise SystemExit(main('+repr(['work','resume','--handoff-id',HANDOFF])+'))\n').encode()
    record=json.loads((directory/'packet.json').read_bytes())
    record.pop('client_environment')
    record['files'][str(script)]=hashlib.sha256(legacy).hexdigest()
    script.write_bytes(legacy)
    receipt=workspace_resume.canonical(record)
    (directory/'packet.json').write_bytes(receipt)
    assert workspace_resume.prepare(cfg,HANDOFF,'muse')==result
    assert script.read_bytes()==legacy
    assert (directory/'packet.json').read_bytes()==receipt
