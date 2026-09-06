"""Build the standalone installer from the same reviewed stdlib source modules."""
from pathlib import Path
import hashlib
import json
import sys


def build():
    root=Path(__file__).parent
    manifest=(root/'bootstrap_manifest.py').read_text()
    installer=(root/'bootstrap_installer.py').read_text()
    installer=installer.replace('from __future__ import annotations\n','').replace('from .bootstrap_manifest import decode, artifact_url, ManifestError, MAX_MANIFEST\n','')
    return ('#!/usr/bin/env python3\n'+manifest+'\n'+installer).encode()


def main():
    if len(sys.argv)!=2:raise SystemExit('usage: python -m capy_developer.bootstrap_bundle OUTPUT')
    path=Path(sys.argv[1]);raw=build()
    if path.exists() and path.read_bytes()!=raw:raise SystemExit('existing different installer preserved')
    path.write_bytes(raw)
    print(json.dumps(dict(filename=path.name,sha256=hashlib.sha256(raw).hexdigest(),size_bytes=len(raw))))

if __name__=='__main__':main()
