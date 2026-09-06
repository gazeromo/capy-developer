from pathlib import Path

import pytest

from capy_developer.client_setup import ClientSetup
from capy_developer.core import DeveloperCore
from capy_developer.errors import DeveloperError
from capy_developer.installation import located_config
from test_installation_discovery import config


def setup(tmp_path):
    core = DeveloperCore(config(tmp_path / 'installation'))
    return ClientSetup(core, skills=tmp_path/'skills', locator=tmp_path/'locator.json', codex_config=tmp_path/'codex.toml')


def test_muse_only_then_codex_share_owned_guidance_and_catalog(tmp_path):
    installer = setup(tmp_path)
    result = installer.install('muse')
    assert not result['ready'] and result['transport'] == 'JSON_CLI'
    assert not installer.codex_config.exists()
    before = installer.core.config.database.read_bytes()
    instruction = Path(result['instruction']).read_bytes()
    installer.install('muse')
    joined = installer.install('codex')
    assert joined['transport'] == 'MCP_STDIO'
    assert installer.core.config.database.read_bytes() == before
    assert Path(result['instruction']).read_bytes() == instruction
    assert located_config(installer.locator) == installer.core.config


def test_foreign_guidance_and_foreign_mcp_fail_before_shared_writes(tmp_path):
    installer = setup(tmp_path)
    installer.codex_config.write_text('[mcp_servers.capy_developer]\ncommand="foreign"\n')
    with pytest.raises(DeveloperError):
        installer.install('codex')
    assert not installer.locator.exists()
    assert not installer.skills.exists()
    (installer.skills/'capy-development').mkdir(parents=True)
    (installer.skills/'capy-development/SKILL.md').write_text('user-authored')
    with pytest.raises(DeveloperError):
        installer.install('muse')
    assert not installer.locator.exists()


def test_modified_owned_guidance_preserved(tmp_path):
    installer = setup(tmp_path)
    result = installer.install('muse')
    path = Path(result['instruction'])
    path.write_text('Owner edits')
    with pytest.raises(DeveloperError):
        installer.install('muse')
    assert path.read_text() == 'Owner edits'


def test_partial_write_replays_only_recorded_owned_content(tmp_path, monkeypatch):
    installer = setup(tmp_path)
    from capy_developer import client_setup
    original = client_setup.atomic
    def failing(path, payload):
        if path.name == 'SKILL.md':
            raise OSError('synthetic interrupted write')
        original(path, payload)
    monkeypatch.setattr(client_setup, 'atomic', failing)
    with pytest.raises(OSError):
        installer.install('muse')
    monkeypatch.setattr(client_setup, 'atomic', original)
    assert installer.install('muse')['status'] == 'CONFIGURED'


def test_interrupted_codex_config_write_can_resume(tmp_path, monkeypatch):
    installer = setup(tmp_path)
    from capy_developer.desktop import setup as desktop_setup
    original = desktop_setup.atomic
    def failing(path, payload):
        if path == installer.codex_config:
            raise OSError('synthetic interrupted Codex configuration write')
        original(path, payload)
    monkeypatch.setattr(desktop_setup, 'atomic', failing)
    with pytest.raises(OSError):
        installer.install('codex')
    monkeypatch.setattr(desktop_setup, 'atomic', original)
    assert installer.install('codex')['status'] == 'CONFIGURED'


def test_empty_interrupted_muse_setup_can_resume_from_repaired_environment(tmp_path, monkeypatch):
    import json
    installer = setup(tmp_path)
    from capy_developer import client_setup
    original = client_setup.atomic
    def fail(path, payload):
        if path.name == 'SKILL.md':
            raise OSError('interrupted')
        original(path, payload)
    monkeypatch.setattr(client_setup, 'atomic', fail)
    with pytest.raises(OSError):
        installer.install('muse')
    monkeypatch.setattr(client_setup, 'atomic', original)
    before = installer.core.config.database.read_bytes()
    old_files = installer._files()
    repaired = {path: payload + b'\n# repaired environment\n' for path, payload in old_files.items()}
    monkeypatch.setattr(installer, '_files', lambda: repaired)
    # A remaining old file must never be silently replaced.
    with pytest.raises(DeveloperError, match='another exact environment'):
        installer.install('muse')
    for path in old_files:
        if path.exists(): path.unlink()
    assert installer.install('muse')['status'] == 'CONFIGURED'
    assert installer.core.config.database.read_bytes() == before
    assert json.loads(installer.receipt.read_text())['state'] == 'CONFIGURED'
    assert all(path.read_bytes() == payload for path, payload in repaired.items())
