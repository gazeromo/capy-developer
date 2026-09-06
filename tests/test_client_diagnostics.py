import sqlite3

import pytest

from capy_developer import cli, installation
from capy_developer.core import DeveloperCore
from capy_developer.desktop.companion import Companion
from capy_developer.desktop.credentials import FileCredentials
from capy_developer.errors import DeveloperError
from capy_developer.harness_client import HarnessClient
from test_installation_discovery import config


def test_diagnostics_open_readonly_and_cli_does_not_initialize_core(tmp_path, monkeypatch):
    cfg = config(tmp_path / 'owned')
    core = DeveloperCore(cfg)
    writer = HarnessClient(core, companion=Companion(core, credential_store=FileCredentials(test_owned=True)))
    files = [cfg.database, writer.companion.state.path]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
    reader = HarnessClient.diagnostics(cfg, credential_store=FileCredentials(test_owned=True))
    assert reader.clients() == {'ok': True, 'clients': []}
    with reader.companion.state.connect() as db:
        with pytest.raises(sqlite3.OperationalError, match='readonly'):
            db.execute('DELETE FROM harness_clients')
    monkeypatch.setattr(installation, 'discover', lambda **kwargs: {'status':'EXISTING','config':cfg})
    def forbidden(*args, **kwargs):
        raise AssertionError('client diagnostics must not initialize DeveloperCore')
    monkeypatch.setattr(cli, 'DeveloperCore', forbidden)
    assert cli.run(['client','list']) == {'ok': True, 'clients': []}
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files} == before


def test_diagnostics_missing_setup_creates_nothing(tmp_path):
    cfg = config(tmp_path / 'missing')
    with pytest.raises(DeveloperError, match='connect this installation'):
        HarnessClient.diagnostics(cfg, credential_store=FileCredentials(test_owned=True))
    assert not cfg.data_root.parent.exists()


def test_write_denial_is_structured_without_new_installation(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'state.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE evidence(value)')
    def denied(*args):
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            db.execute('INSERT INTO evidence VALUES (1)')
    monkeypatch.setattr(cli, 'run', denied)
    assert cli.main(['work','begin']) == 2
    import json
    result = json.loads(capsys.readouterr().out)
    assert 'INSTALLATION_WRITE_ACCESS_REQUIRED' in json.dumps(result)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM evidence').fetchone()[0] == 0
