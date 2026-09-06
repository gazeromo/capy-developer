import copy
import hashlib
import pytest
from capy_developer.bootstrap_manifest import decode, canonical, artifact_url, ManifestError

def manifest():
    item=lambda name:dict(filename=name,sha256='a'*64,size_bytes=25)
    return dict(schema='capy.harness-bootstrap/v0',release_id='0.7.0-probe',origin='https://127.0.0.1:18891',site_id='site_'+'1'*32,scope='local-coding-client',protocols={'developer':'harness-first/v0','runtime':'harness-first/v0'},developer=dict(version='0.7.0',artifact=item('capy_developer-0.7.0-py3-none-any.whl')),installer=item('capy-bootstrap.py'),platforms=['macos-arm64'],clients={x:dict(version=v,transport='MCP_STDIO') for x,v in [('muse','1.0.3'),('codex','0.153.4')]},prerequisites=dict(python_minimum='3.11',python_exact='3.13.7',uv={}))

def test_exact_manifest_and_canonical_origin():
    m=manifest();raw=canonical(m)
    assert decode(raw,hashlib.sha256(raw).hexdigest())==m
    assert artifact_url(m,m['installer'])=='https://127.0.0.1:18891/developer/bootstrap/0.7.0-probe/capy-bootstrap.py'
    with pytest.raises(ManifestError):decode(raw,'b'*64)

@pytest.mark.parametrize('site',['http://example.com','https://example.com/','https://user:secret@example.com','https://example.com?token=x','https://example.com#fragment','https://example.com\\evil','https://example.com:99999'])
def test_reject_origin_injection(site):
    m=manifest();m['origin']=site
    with pytest.raises(ManifestError):decode(canonical(m))

@pytest.mark.parametrize('field,value',[('filename','../x.py'),('filename','x/y'),('filename','x?token=y'),('size_bytes',True),('size_bytes',129*1024*1024),('sha256','A'*64)])
def test_artifact_bounds(field,value):
    m=manifest();m['installer'][field]=value
    with pytest.raises(ManifestError):decode(canonical(m))

def test_closed_duplicate_and_invalid_values():
    m=manifest();m['command']='curl | sh'
    with pytest.raises(ManifestError):decode(canonical(m))
    with pytest.raises(ManifestError):decode(b'{"schema":1,"schema":2}')
    with pytest.raises(ManifestError):decode(b'{"schema":NaN}')
    m=manifest();m['platforms']=[{}]
    with pytest.raises(ManifestError):decode(canonical(m))
    m=manifest();m['platforms']=['macos-arm64','macos-arm64']
    with pytest.raises(ManifestError):decode(canonical(m))
