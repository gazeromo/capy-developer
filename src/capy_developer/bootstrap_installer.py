"""Hash-verified private environment provisioning; never modifies system Python."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from .bootstrap_manifest import decode, artifact_url, ManifestError, MAX_MANIFEST


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ManifestError('bootstrap redirects are forbidden')


def fetch(url, maximum):
    if not url.startswith('https://'):
        raise ManifestError('bootstrap requires verified HTTPS')
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(urllib.request.Request(url,headers={'Accept':'application/octet-stream'}),timeout=30) as response:
        if response.status!=200:raise ManifestError('bootstrap download failed')
        raw=response.read(maximum+1)
    if len(raw)>maximum:raise ManifestError('bootstrap download exceeds declared bound')
    return raw


def owned(path, *, directory=False):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ManifestError('bootstrap path is symlinked')
    if path.exists():
        info=path.stat()
        if path.is_dir()!=directory or (os.name!='nt' and (info.st_uid!=os.getuid() or info.st_mode & 0o022)):
            raise ManifestError('bootstrap path is not safely owned')
    return path


def atomic(path, value):
    owned(path)
    raw=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    fd,name=tempfile.mkstemp(prefix='.bootstrap-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def environment_root():
    if sys.platform=='darwin':return Path.home()/'Library/Application Support/Capy/Environments'
    if os.name=='nt':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))/'Capy/Environments'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'capy/environments'


def run(args, *, env=None):
    child_env=dict(os.environ if env is None else env)
    for key in list(child_env):
        if key.startswith('PIP_'):child_env.pop(key)
    child_env['PIP_CONFIG_FILE']=os.devnull
    result=subprocess.run(list(map(str,args)),env=child_env,capture_output=True,text=True,timeout=120)
    if result.returncode:
        raise ManifestError('bootstrap subprocess failed: '+result.stderr[-1500:])
    return result.stdout


def platform_key():
    system={'darwin':'macos','linux':'linux','win32':'windows'}.get(sys.platform)
    arch={'arm64':'arm64','aarch64':'arm64','x86_64':'x86_64','amd64':'x86_64'}.get(platform.machine().lower())
    return str(system)+'-'+str(arch)


class Installer:
    def __init__(self, root, *, download=fetch, execute=run):
        self.root=Path(root);self.download=download;self.execute=execute

    def manifest(self, url, digest):
        m=decode(self.download(url,MAX_MANIFEST),digest)
        expected=m['origin']+'/developer/bootstrap/'+m['release_id']+'/manifest.json'
        if url!=expected:raise ManifestError('manifest URL differs from configured identity')
        if platform_key() not in m['platforms']:raise ManifestError('this platform is not supported by the release')
        return m

    def wheel(self,m):
        item=m['developer']['artifact'];raw=self.download(artifact_url(m,item),item['size_bytes'])
        if len(raw)!=item['size_bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise ManifestError('Developer wheel identity mismatch')
        return raw

    def discover(self,m,raw):
        """Run bounded discovery from the verified wheel before environment allocation."""
        item=m['developer']['artifact']
        if hashlib.sha256(raw).hexdigest()!=item['sha256'] or len(raw)!=item['size_bytes']:
            raise ManifestError('Developer wheel identity mismatch')
        script = """import sys,json,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from capy_developer.config import Config
from capy_developer.installation import discover,locator_path,roots,ROOT_KEYS
current=Config.from_environment()
found=discover(default=current,explicit=current if all(k in os.environ for k in ROOT_KEYS) else None,config_path=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml',locator=locator_path())
print(json.dumps(dict(status=found['status'],source=found['source'],roots=roots(found['config']))))
"""
        with tempfile.TemporaryDirectory(prefix='capy-bootstrap-discovery-') as scratch:
            wheel=Path(scratch)/item['filename'];wheel.write_bytes(raw)
            value=json.loads(self.execute([sys.executable,'-I','-c',script,wheel]))
        if type(value) is not dict or set(value)!={'status','source','roots'} or value['status'] not in ('EXISTING','FRESH_PROPOSAL'):
            raise ManifestError('invalid discovery result')
        return value

    def provision(self,m,raw):
        """Reuse exact intact owned environment, or create one under an exclusive lease."""
        item=m['developer']['artifact']
        if len(raw)!=item['size_bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise ManifestError('Developer wheel identity mismatch')
        if sys.version_info<(3,11):raise ManifestError('compatible Python prerequisite required')
        owned(self.root,directory=True);self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        folder=self.root/(m['developer']['version']+'-'+item['sha256'][:16])
        owned(folder,directory=True)
        lease=self.root/(folder.name+'.lock')
        try:fd=os.open(lease,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:raise ManifestError('bootstrap operation already active; inspect the existing operation') from None
        os.close(fd)
        expected=dict(schema='capy.bootstrap-environment/v0',version=m['developer']['version'],wheel_sha256=item['sha256'],wheel_size_bytes=item['size_bytes'])
        try:
            receipt=folder/'bootstrap.json'
            if folder.exists():
                if not receipt.exists():raise ManifestError('existing environment is not owned by bootstrap')
                owned(receipt)
                value=json.loads(receipt.read_bytes())
                if not isinstance(value,dict) or set(value)!=set(expected)|{'state','runtime'} or any(value.get(k)!=v for k,v in expected.items()) or value['state']!='READY':raise ManifestError('existing environment requires repair; preserved without overwrite')
                if value['runtime']!=self.runtime_identity(folder):raise ManifestError('private interpreter configuration changed')
                self.verify(folder,raw)
                return self.python(folder),'REUSED'
            folder.mkdir(mode=0o700)
            atomic(receipt,{**expected,'state':'PREPARING'})
            wheel=folder/item['filename'];wheel.write_bytes(raw);wheel.chmod(0o600)
            self.execute([sys.executable,'-I','-m','venv',folder/'venv'])
            python=self.python(folder)
            self.execute([python,'-I','-m','pip','install','--require-virtualenv','--no-user','--no-index','--no-deps','--disable-pip-version-check',wheel])
            self.verify(folder,raw)
            atomic(receipt,{**expected,'state':'READY','runtime':self.runtime_identity(folder)})
            return python,'CREATED'
        finally:
            lease.unlink()

    def runtime_identity(self,folder):
        python=self.python(folder)
        cfg=owned(folder/'venv/pyvenv.cfg')
        return {'executable_sha256':hashlib.sha256(python.read_bytes()).hexdigest(),'executable_target':str(python.resolve()),'configuration_sha256':hashlib.sha256(cfg.read_bytes()).hexdigest()}

    @staticmethod
    def python(folder):
        return folder/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')

    def verify(self,folder,raw):
        """Compare installed package bytes with verified wheel before running them."""
        import io
        venv=owned(folder/'venv',directory=True)
        if os.name=='nt':sites=[venv/'Lib/site-packages']
        else:sites=list((venv/'lib').glob('python*/site-packages'))
        if len(sites)!=1:raise ManifestError('private Python environment layout differs')
        site=owned(sites[0],directory=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names=archive.namelist()
            if len(names)!=len(set(names)):raise ManifestError('duplicate wheel members')
            for name in names:
                if name.endswith('/'):continue
                if name.startswith('/') or '..' in Path(name).parts:raise ManifestError('unsafe wheel member')
                target=owned(site/name)
                if not target.is_file() or target.read_bytes()!=archive.read(name):
                    # pip rewrites RECORD and may normalize WHEEL installation metadata.
                    if name.endswith('.dist-info/RECORD'):continue
                    raise ManifestError('installed Developer bytes differ from the exact wheel')
        package=site/'capy_developer'
        expected_files={n for n in names if n.startswith('capy_developer/') and not n.endswith('/')}
        for path in package.rglob('*'):
            if '__pycache__' in path.parts:continue
            if path.is_file() and path.relative_to(site).as_posix() not in expected_files:
                raise ManifestError('unexpected installed Developer file')
        if not self.python(folder).is_file():raise ManifestError('private interpreter missing')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',required=True)
    parser.add_argument('--manifest-sha256',required=True)
    parser.add_argument('--client',choices=['muse','codex'],required=True)
    args=parser.parse_args()
    try:
        if shutil.which('git') is None:raise ManifestError('native Git is required; install the normal OS developer tools')
        installer=Installer(environment_root());m=installer.manifest(args.manifest,args.manifest_sha256)
        raw=installer.wheel(m);found=installer.discover(m,raw);python,status=installer.provision(m,raw)
        env=os.environ.copy()
        if found['status']=='EXISTING':env.update(found['roots'])
        result=subprocess.run([str(python),'-I','-m','capy_developer.cli','connect','--site',m['origin'],'--client',args.client],env=env,check=False)
        return result.returncode
    except (ManifestError,OSError,ValueError,zipfile.BadZipFile) as exc:
        print(json.dumps({'ok':False,'code':'BOOTSTRAP_FAILED','detail':str(exc)}));return 1

if __name__=='__main__':raise SystemExit(main())
