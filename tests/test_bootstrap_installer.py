import hashlib
import io
import json
import zipfile
import pytest
from capy_developer.bootstrap_installer import Installer, ManifestError, NoRedirect


def wheel():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        for name,raw in {
            'capy_developer/__init__.py':b'__version__="0.7.0"\n',
            'capy_developer-0.7.0.dist-info/METADATA':b'Metadata-Version: 2.1\nName: capy-developer\nVersion: 0.7.0\n',
            'capy_developer-0.7.0.dist-info/WHEEL':b'Wheel-Version: 1.0\nGenerator: synthetic-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
            'capy_developer-0.7.0.dist-info/RECORD':b'',
        }.items():z.writestr(name,raw)
    raw=data.getvalue()
    return {'developer':{'version':'0.7.0','artifact':{'filename':'capy_developer-0.7.0-py3-none-any.whl','sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)}}},raw


def test_real_private_environment_creation_replay_and_modified_source(tmp_path,monkeypatch):
    monkeypatch.setenv("PIP_TARGET",str(tmp_path/"outside target"))
    monkeypatch.setenv("PIP_USER","true")
    m,raw=wheel();installer=Installer(tmp_path/'owned environments')
    python,state=installer.provision(m,raw)
    assert state=='CREATED' and python.is_file()
    assert not (tmp_path/'outside target').exists()
    assert installer.provision(m,raw)==(python,'REUSED')
    folder=python.parents[2]
    site=next((folder/'venv/lib').glob('python*/site-packages')) if python.name!='python.exe' else folder/'venv/Lib/site-packages'
    config=folder/'venv/pyvenv.cfg';before=config.read_bytes();config.write_bytes(before+b'\n')
    with pytest.raises(ManifestError,match='configuration changed'):installer.provision(m,raw)
    config.write_bytes(before)
    extra=site/'capy_developer/injected.py';extra.write_text('pass')
    with pytest.raises(ManifestError,match='unexpected installed'):installer.provision(m,raw)
    extra.unlink()
    (site/'capy_developer/__init__.py').write_text('raise RuntimeError("modified")')
    with pytest.raises(ManifestError,match='bytes differ'):installer.provision(m,raw)
    assert 'modified' in (site/'capy_developer/__init__.py').read_text()


def test_digest_failure_precedes_any_mutation(tmp_path):
    m,raw=wheel();root=tmp_path/'must not exist'
    with pytest.raises(ManifestError,match='identity mismatch'):Installer(root).provision(m,raw+b'corrupt')
    assert not root.exists()


def test_unowned_and_interrupted_directories_are_preserved(tmp_path):
    m,raw=wheel();folder=tmp_path/('0.7.0-'+m['developer']['artifact']['sha256'][:16]);folder.mkdir();keep=folder/'user-data';keep.write_text('keep')
    with pytest.raises(ManifestError,match='not owned'):Installer(tmp_path).provision(m,raw)
    assert keep.read_text()=='keep'
    (folder/'bootstrap.json').write_text('{}')
    with pytest.raises(ManifestError,match='requires repair'):Installer(tmp_path).provision(m,raw)
    assert keep.read_text()=='keep'


def test_no_redirects_or_unverified_download(tmp_path):
    with pytest.raises(ManifestError,match='redirects'):NoRedirect().redirect_request(None,None,302,'',{},'https://other.example')
    m,raw=wheel();m['origin']='https://example.com';m['release_id']='test'
    with pytest.raises(ManifestError,match='identity mismatch'):Installer(tmp_path,download=lambda *_:b'wrong').wheel(m)


def test_standalone_installer_help_has_no_package_dependency(tmp_path):
    import subprocess
    import sys
    from capy_developer.bootstrap_bundle import build
    path=tmp_path/'capy-bootstrap.py';raw=build();path.write_bytes(raw)
    assert build()==raw
    result=subprocess.run([sys.executable,'-I',str(path),'--help'],capture_output=True,text=True)
    assert result.returncode==0 and '--manifest-sha256' in result.stdout
    assert list(tmp_path.iterdir())==[path]
