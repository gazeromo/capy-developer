import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import zipfile

import pytest

from capy_developer import __version__
from capy_developer.bootstrap_manifest import ManifestError
from capy_developer.core import DeveloperCore
from capy_developer.installation import BEGIN, END, roots
from capy_developer.installation_repair import repair
from test_installation_discovery import config


@pytest.fixture
def owned_install(tmp_path):
    cfg = config(tmp_path / 'state')
    DeveloperCore(cfg)
    venv = tmp_path / 'venv'
    (venv / 'bin').mkdir(parents=True)
    (venv / 'bin/python').write_text('synthetic interpreter never executed')
    (venv / 'bin/python').chmod(0o755)
    (venv / 'pyvenv.cfg').write_text('include-system-site-packages = false\nversion = 3.14.0\n')
    site = venv / 'lib/python3.14/site-packages'
    package = site / 'capy_developer'
    metadata = site / 'capy_developer-0.6.0.dist-info'
    package.mkdir(parents=True)
    metadata.mkdir()
    (package / '__init__.py').write_text('__version__ = "0.6.0"\n')
    (metadata / 'METADATA').write_text('Name: capy-developer\nVersion: 0.6.0\n')
    (metadata / 'RECORD').write_text('capy_developer/__init__.py,,\ncapy_developer-0.6.0.dist-info/METADATA,,\ncapy_developer-0.6.0.dist-info/RECORD,,\n../../../bin/capy-dev,,\n')
    (venv / 'bin/capy-dev').write_text('old CLI')
    client = tmp_path / 'config.toml'
    block = BEGIN + '[mcp_servers.capy_developer]\ncommand = ' + json.dumps(str(venv / 'bin/python')) + '\nargs = ["-m", "capy_developer", "mcp"]\n[mcp_servers.capy_developer.env]\n' + ''.join(k+' = '+json.dumps(v)+'\n' for k,v in roots(cfg).items()) + END
    client.write_text(block)
    (cfg.data_root / 'desktop').mkdir()
    (cfg.data_root / 'desktop/setup.json').write_text(json.dumps({'schema':'capy.desktop-setup/v0','python':str(venv / 'bin/python'),'config_path':str(client),'mcp_block':block}))
    (cfg.data_root / 'desktop/preserved-sentinel').write_text('private state sentinel')
    wheel = tmp_path / ('capy_developer-' + __version__ + '-py3-none-any.whl')
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('capy_developer/__init__.py', '__version__ = "'+__version__+'"\n')
        archive.writestr('capy_developer-'+__version__+'.dist-info/METADATA', 'Name: capy-developer\nVersion: '+__version__+'\n')
        archive.writestr('capy_developer-'+__version__+'.dist-info/RECORD', 'capy_developer/__init__.py,,\ncapy_developer-'+__version__+'.dist-info/METADATA,,\ncapy_developer-'+__version__+'.dist-info/RECORD,,\n../../../bin/capy-dev,,\n')
    return cfg, venv, site, client, wheel, hashlib.sha256(wheel.read_bytes()).hexdigest()


def test_repair_plan_preserves_all_files_and_is_exact(owned_install, tmp_path):
    cfg, venv, site, client, wheel, sha = owned_install
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = repair(client, wheel, sha)
    assert result['status'] == 'PLANNED' and result['same_configured_interpreter']
    assert result['python'] == str(venv / 'bin/python')
    assert not result['mutated']
    assert before == {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ManifestError, match='digest'):
        repair(client, wheel, '0'*64)
    (site / 'capy_developer-0.6.0.dist-info/RECORD').write_text('../../../../outside,,\n')
    with pytest.raises(ManifestError, match='outside'):
        repair(client, wheel, sha)


def test_apply_and_explicit_rollback_touch_package_only(owned_install, tmp_path):
    cfg, venv, site, client, wheel, sha = owned_install
    preserved = {p: p.read_bytes() for p in cfg.data_root.rglob('*') if p.is_file()}
    config_before = client.read_bytes()
    backup = tmp_path / 'package-backup'
    def install(args):
        assert args[:4] == [venv / 'bin/python', '-I', '-m', 'pip']
        assert '--force-reinstall' in args and '--no-index' in args
        shutil.rmtree(site / 'capy_developer')
        shutil.rmtree(site / 'capy_developer-0.6.0.dist-info')
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(site)
        (venv / 'bin/capy-dev').write_text('new CLI')
    result = repair(client, wheel, sha, apply=True, backup=backup, execute=install)
    assert result['status'] == 'REPAIRED'
    assert __version__ in (site / 'capy_developer/__init__.py').read_text()
    assert repair(client, wheel, sha, rollback=True, backup=backup)['status'] == 'ROLLED_BACK'
    assert '0.6.0' in (site / 'capy_developer/__init__.py').read_text()
    assert (venv / 'bin/capy-dev').read_text() == 'old CLI'
    assert preserved == {p: p.read_bytes() for p in cfg.data_root.rglob('*') if p.is_file()}
    assert client.read_bytes() == config_before


def test_failed_apply_automatically_restores_exact_package(owned_install, tmp_path):
    cfg, venv, site, client, wheel, sha = owned_install
    before = (site / 'capy_developer/__init__.py').read_bytes()
    def fail(args):
        (site / 'capy_developer/__init__.py').write_text('interrupted')
        raise ManifestError('synthetic interrupted pip')
    with pytest.raises(ManifestError, match='interrupted pip'):
        repair(client, wheel, sha, apply=True, backup=tmp_path / 'backup', execute=fail)
    assert (site / 'capy_developer/__init__.py').read_bytes() == before


def test_rollback_recovers_interrupted_missing_distribution(owned_install, tmp_path):
    from capy_developer.installation_repair import preflight, snapshot
    cfg, venv, site, client, wheel, sha = owned_install
    backup = tmp_path / 'backup'
    snapshot(preflight(client, wheel, sha), backup)
    shutil.rmtree(site / 'capy_developer')
    shutil.rmtree(site / 'capy_developer-0.6.0.dist-info')
    result = repair(client, wheel, sha, rollback=True, backup=backup)
    assert result['status'] == 'ROLLED_BACK'
    assert '0.6.0' in (site / 'capy_developer/__init__.py').read_text()
    (backup / '0/__init__.py').write_text('tampered snapshot')
    with pytest.raises(ManifestError, match='snapshot bytes changed'):
        repair(client, wheel, sha, rollback=True, backup=backup)
    assert '0.6.0' in (site / 'capy_developer/__init__.py').read_text()
