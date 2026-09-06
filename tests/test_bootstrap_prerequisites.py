import hashlib
import subprocess
from capy_developer.bootstrap_prerequisites import posix_script
from test_bootstrap_manifest import manifest


def test_generated_script_is_fixed_and_parses(tmp_path):
    m=manifest()
    item=lambda n:dict(filename=n,sha256='b'*64,size_bytes=123)
    m['prerequisites']['uv']['macos-arm64']=dict(version='0.9.0',artifact=item('uv-aarch64-apple-darwin.tar.gz'),python_artifact=item('python.tar.gz'),downloads=item('python-downloads.json'),python_key='cpython-3.13.7-darwin-aarch64-none')
    raw=posix_script(m,'a'*64,'macos-arm64');p=tmp_path/'bootstrap.sh';p.write_bytes(raw)
    assert subprocess.run(['/bin/sh','-n',str(p)],capture_output=True).returncode==0
    assert b'--no-bin --no-registry' in raw and b'--no-config' in raw
    assert b'--max-redirs 0' in raw and b'--manifest-sha256 '+b'a'*64 in raw
    assert b'latest' not in raw and b'--force' not in raw
