import json

import pytest

from capy_developer import muse_mcp
from capy_developer.errors import DeveloperError
from capy_developer.muse_mcp import MuseMcpSetup
from test_installation_discovery import config


def setup(tmp_path, raw=None):
    cfg=config(tmp_path/'installation')
    (cfg.data_root/'client-setup').mkdir(parents=True)
    settings=tmp_path/'settings.json'
    if raw is not None:settings.write_bytes(raw)
    return MuseMcpSetup(cfg,settings)


@pytest.mark.parametrize('raw',[None,b'{ "schema_version": 1, "unknown" : 1e-5 }\n',
    b'{"schema_version":1,"mcp_servers":{"other":{"command":"keep-me"}},"model":"unchanged"}\n'])
def test_install_replay_remove_restores_original_bytes(tmp_path,raw):
    s=setup(tmp_path,raw)
    result=s.install()
    assert result['transport']=='MCP_STDIO'
    written=s.settings.read_bytes()
    assert s.install()==result and s.settings.read_bytes()==written
    if raw and b'1e-5' in raw: assert b'1e-5' in written
    s.remove()
    assert (s.settings.read_bytes() if s.settings.exists() else None)==raw
    assert s.remove()['status']=='REMOVED'


def test_remove_preserves_settings_added_after_install(tmp_path):
    s=setup(tmp_path,b'{"schema_version":1,"model":"unchanged"}')
    s.install()
    value=json.loads(s.settings.read_text());value['new_user_setting']='keep';value['mcp_servers']['user_server']={'command':'keep'}
    raw=json.dumps(value,indent=3).encode();s.settings.write_bytes(raw)
    s.remove()
    result=json.loads(s.settings.read_text())
    assert result['mcp_servers']=={'user_server':{'command':'keep'}}
    assert result['new_user_setting']=='keep' and result['model']=='unchanged'


@pytest.mark.parametrize('raw',[
 b'{"schema_version":1,"mcp_servers":{"capy_developer":{"command":"foreign"}}}',
 b'{"schema_version":1,"schema_version":1}',b'{"schema_version":2}',b'not-json'])
def test_conflict_preserves_settings_without_receipt(tmp_path,raw):
    s=setup(tmp_path,raw)
    with pytest.raises(DeveloperError):s.install()
    assert s.settings.read_bytes()==raw
    assert not s.receipt.exists()


def test_interrupted_install_and_remove_replay(tmp_path,monkeypatch):
    s=setup(tmp_path,b'{"schema_version":1}')
    original=muse_mcp.atomic
    def interrupted(path,payload):
        if path==s.receipt and json.loads(payload).get('state')=='CONFIGURED':raise OSError('lost final receipt')
        original(path,payload)
    monkeypatch.setattr(muse_mcp,'atomic',interrupted)
    with pytest.raises(OSError):s.install()
    monkeypatch.setattr(muse_mcp,'atomic',original)
    s.install()
    def removal_interrupted(path,payload):
        if path==s.receipt and json.loads(payload).get('state')=='REMOVED':raise OSError('lost removal receipt')
        original(path,payload)
    monkeypatch.setattr(muse_mcp,'atomic',removal_interrupted)
    with pytest.raises(OSError):s.remove()
    monkeypatch.setattr(muse_mcp,'atomic',original)
    assert s.remove()['status']=='REMOVED'
    assert s.settings.read_bytes()==b'{"schema_version":1}'


def test_modified_entry_is_never_removed(tmp_path):
    s=setup(tmp_path,b'{"schema_version":1}')
    s.install();value=json.loads(s.settings.read_text());value['mcp_servers']['capy_developer']['command']='owner-change'
    raw=json.dumps(value).encode();s.settings.write_bytes(raw)
    with pytest.raises(DeveloperError):s.remove()
    assert s.settings.read_bytes()==raw


@pytest.mark.parametrize('raw', ['not-json', '[]', 'null'])
def test_invalid_receipt_preserves_mcp_settings(tmp_path, raw):
    s = setup(tmp_path, b'{"schema_version":1}')
    s.install()
    before = s.settings.read_bytes()
    s.receipt.write_text(raw)
    with pytest.raises(DeveloperError):
        s.remove()
    assert s.settings.read_bytes() == before


def test_boolean_schema_is_not_version_one(tmp_path):
    s = setup(tmp_path, b'{"schema_version":true}')
    with pytest.raises(DeveloperError):
        s.install()
    assert not s.receipt.exists()
