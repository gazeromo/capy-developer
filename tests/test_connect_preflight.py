import subprocess

import pytest

from capy_developer import cli, installation
from capy_developer.desktop.transport import Transport
from capy_developer.errors import DeveloperError
from test_installation_discovery import config


@pytest.mark.parametrize('failure', ['missing','failed','malformed'])
def test_client_preflight_failure_creates_no_installation(tmp_path, monkeypatch, failure):
    candidate = config(tmp_path / 'fresh')
    monkeypatch.setattr(installation, 'discover', lambda **kwargs: {'status':'FRESH_PROPOSAL','source':'DEFAULT','config':candidate})
    monkeypatch.setattr(Transport, 'connection_info', lambda self, site: {
        'schema':'capy.harness-connection/v0','site_id':'site_'+'a'*32,'origin':site,'capability':'harness-first/v0'})
    import shutil
    monkeypatch.setattr(shutil, 'which', lambda name: None if failure == 'missing' else '/synthetic/muse')
    def probe(*args, **kwargs):
        if failure == 'failed':
            raise subprocess.CalledProcessError(1,args[0])
        return subprocess.CompletedProcess(args[0],0,stdout='invalid\nversion',stderr='')
    monkeypatch.setattr(subprocess, 'run', probe)
    with pytest.raises(DeveloperError):
        cli.run(['connect','--site','https://capy.test','--client','muse'])
    assert not candidate.data_root.parent.exists()
