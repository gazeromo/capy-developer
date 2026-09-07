"""Explicit exact-wheel repair of the existing owned MCP interpreter.

Default mode is a read-only plan. Apply touches package files only; catalogs,
worktrees, pairing, credentials, owned MCP configuration and setup receipts stay
in place. A package-only snapshot supports explicit rollback.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from . import __version__
from .errors import DeveloperError
from .bootstrap_installer import Installer, owned, atomic, lease, run
from .bootstrap_manifest import ManifestError
from .installation import historical_config, historical_python, read_owned


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight(config_path, wheel, sha256, *, recovery=False):
    config_path, wheel = Path(config_path), Path(wheel)
    config = historical_config(config_path)
    if config is None:
        raise ManifestError('an exact owned MCP configuration is required; no new installation was allocated')
    python = Path(historical_python(config, config_path))
    venv = owned(python.parent.parent, directory=True)
    configuration = owned(venv / 'pyvenv.cfg')
    fields = dict(line.split('=', 1) for line in configuration.read_text().splitlines() if '=' in line)
    fields = {key.strip(): value.strip() for key, value in fields.items()}
    if fields.get('include-system-site-packages', '').strip() != 'false':
        raise ManifestError('repair requires the existing private virtual environment')
    resolved = python.resolve(strict=True)
    info = resolved.stat()
    if not resolved.is_file() or (os.name != 'nt' and (info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022)):
        raise ManifestError('the configured interpreter is not safely owned')
    sites = [venv / 'Lib/site-packages'] if os.name == 'nt' else list((venv / 'lib').glob('python*/site-packages'))
    if len(sites) != 1:
        raise ManifestError('the configured environment layout is ambiguous')
    site = owned(sites[0], directory=True)
    metadata = list(site.glob('capy_developer-*.dist-info'))
    if not recovery and len(metadata) != 1:
        raise ManifestError('the existing Developer package metadata is ambiguous')
    package = owned(site / 'capy_developer', directory=True)
    metadata = owned(site / ('capy_developer-' + __version__ + '.dist-info') if recovery else metadata[0], directory=True)
    script = venv / ('Scripts/capy-dev.exe' if os.name == 'nt' else 'bin/capy-dev')
    # Before pip uninstalls anything, constrain every recorded path to this exact
    # distribution. No arbitrary path from RECORD may be removed by the repair.
    record = '' if recovery else read_owned(metadata / 'RECORD', maximum=2*1024*1024).decode()
    for row in csv.reader(io.StringIO(record)):
        if not row:
            continue
        target = (site / row[0]).resolve()
        if not (target.is_relative_to(package) or target.is_relative_to(metadata) or target == script):
            raise ManifestError('the existing package RECORD names files outside the bounded repair')
    owned(script)
    for directory in (package, metadata):
        for path in directory.rglob('*'):
            owned(path, directory=path.is_dir())
    wheel = owned(wheel)
    raw = read_owned(wheel, maximum=64*1024*1024)
    if not re.fullmatch(r'[0-9a-f]{64}', sha256) or hashlib.sha256(raw).hexdigest() != sha256:
        raise ManifestError('the exact repair wheel digest does not match')
    expected_metadata = 'capy_developer-' + __version__ + '.dist-info'
    if wheel.name != 'capy_developer-' + __version__ + '-py3-none-any.whl':
        raise ManifestError('repair wheel must match this Developer repair version')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > 128*1024*1024:
            raise ManifestError('invalid repair wheel member bounds')
        for name in names:
            parts = Path(name).parts
            if not parts or name.startswith('/') or '..' in parts or parts[0] not in ('capy_developer', expected_metadata):
                raise ManifestError('repair wheel contains an unexpected installation target')
        metadata_text = archive.read(expected_metadata + '/METADATA').decode()
        if '\nName: capy-developer\n' not in '\n' + metadata_text or '\nVersion: ' + __version__ + '\n' not in '\n' + metadata_text:
            raise ManifestError('repair wheel package identity differs')
    return dict(config=config, config_path=config_path, python=python, venv=venv, site=site,
                package=package, metadata=metadata, script=script, wheel=wheel, raw=raw, sha256=sha256)


def package_files(context):
    paths = [context['package'], context['metadata']]
    if context['script'].exists():
        paths.append(context['script'])
    return paths


def snapshot(context, backup):
    backup.mkdir(mode=0o700)
    entries = []
    for index, path in enumerate(package_files(context)):
        name = str(index)
        target = backup / name
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
        checksums = {str(p.relative_to(target)) if target.is_dir() else '.': digest(p) for p in (target.rglob('*') if target.is_dir() else [target]) if p.is_file()}
        entries.append({'source': str(path), 'snapshot': name, 'sha256': checksums})
    atomic(backup / 'repair.json', dict(schema='capy.installation-repair/v0', python=str(context['python']),
        version=__version__, wheel_sha256=context['sha256'], entries=entries,
        config_sha256=digest(context['config_path']),
        setup_sha256=digest(context['config'].data_root / 'desktop/setup.json')))


def restore(context, backup):
    receipt = json.loads(read_owned(backup / 'repair.json'))
    if receipt.get('schema') != 'capy.installation-repair/v0' or receipt.get('python') != str(context['python']):
        raise ManifestError('rollback snapshot does not match the configured interpreter')
    if receipt.get('config_sha256') != digest(context['config_path']) or receipt.get('setup_sha256') != digest(context['config'].data_root / 'desktop/setup.json'):
        raise ManifestError('owned configuration changed since the package snapshot')
    entries = receipt.get('entries')
    if not isinstance(entries, list) or not 2 <= len(entries) <= 3 or not all(isinstance(entry, dict) for entry in entries):
        raise ManifestError('rollback snapshot entries are invalid')
    if len({entry.get('source') for entry in entries}) != len(entries) or len({entry.get('snapshot') for entry in entries}) != len(entries):
        raise ManifestError('rollback snapshot entries are ambiguous')
    allowed = {str(context['package']), str(context['script'])}
    for entry in receipt['entries']:
        if not isinstance(entry.get('source'), str) or not isinstance(entry.get('snapshot'), str):
            raise ManifestError('rollback snapshot path is invalid')
        source = Path(entry['source'])
        metadata_target = source.parent == context['site'] and re.fullmatch(r'capy_developer-[0-9]+[.][0-9]+[.][0-9]+[.]dist-info', source.name) is not None
        if set(entry) != {'source', 'snapshot', 'sha256'} or (entry['source'] not in allowed and not metadata_target) or not re.fullmatch(r'[0-2]', entry['snapshot']):
            raise ManifestError('rollback contains an unexpected path')
        original = owned(backup / entry['snapshot'], directory=Path(entry['source']).name != context['script'].name)
        if not original.exists():
            raise ManifestError('rollback package snapshot is incomplete')
        checksums = {}
        for path in (original.rglob('*') if original.is_dir() else [original]):
            owned(path, directory=path.is_dir())
            if path.is_file():
                checksums[str(path.relative_to(original)) if original.is_dir() else '.'] = digest(path)
        if checksums != entry['sha256']:
            raise ManifestError('rollback package snapshot bytes changed')
    for path in set(package_files(context)) | {Path(entry['source']) for entry in receipt['entries']} | {context['site'] / ('capy_developer-' + __version__ + '.dist-info')}:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for entry in receipt['entries']:
        source, target = backup / entry['snapshot'], Path(entry['source'])
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def repair(config_path, wheel, sha256, *, apply=False, backup=None, rollback=False, execute=run):
    context = preflight(config_path, wheel, sha256, recovery=rollback)
    plan = dict(schema='capy.installation-repair-plan/v0', status='PLANNED', version=__version__,
                python=str(context['python']), wheel_sha256=sha256,
                same_configured_interpreter=True, state_migration=False, mutated=False)
    if not apply and not rollback:
        return plan
    if apply and rollback:
        raise ManifestError('choose repair or rollback, not both')
    if backup is None:
        raise ManifestError('apply requires an explicit new package-backup directory')
    backup = owned(Path(backup), directory=True)
    owned(backup.parent, directory=True)
    if rollback:
        with lease(context['venv'] / '.capy-package-repair.lock'):
            restore(context, backup)
        return {**plan, 'status': 'ROLLED_BACK', 'mutated': True, 'package_backup': str(backup)}
    if backup.exists() or not backup.parent.is_dir():
        raise ManifestError('choose a new package-backup directory under an existing owned directory')
    if backup.is_relative_to(context['venv']) or backup.is_relative_to(context['config'].data_root):
        raise ManifestError('the package backup must be outside the environment and Developer state')
    with lease(context['venv'] / '.capy-package-repair.lock'):
        snapshot(context, backup)
        try:
            execute([context['python'], '-I', '-m', 'pip', 'install', '--require-virtualenv', '--no-user',
                     '--no-index', '--no-deps', '--disable-pip-version-check', '--force-reinstall', context['wheel']])
            Installer(context['venv'].parent).verify_environment(context['venv'], context['raw'])
        except Exception:
            restore(context, backup)
            raise
    return {**plan, 'status': 'REPAIRED', 'mutated': True, 'package_backup': str(backup),
            'next_action': 'Reconnect the configured MCP process to load the exact updated tools, then call capy_developer_status. Existing catalogs, sessions and connections remain in place.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--wheel', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(repair(args.config, args.wheel, args.sha256, apply=args.apply, backup=args.backup, rollback=args.rollback), sort_keys=True))
    except (DeveloperError, ManifestError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, sort_keys=True))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
