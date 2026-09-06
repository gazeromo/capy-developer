import json
import shutil
import subprocess

import pytest

from capy_developer import muse_guidance
from capy_developer.errors import DeveloperError
from capy_developer.muse_guidance import MuseGuidance


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    source = tmp_path / 'source'
    source.mkdir()
    (source/'SKILL.md').write_text('---\nname: capy-development\ndescription: Develop Capy apps.\n---\n')
    (source/'entry.py').write_text('print("synthetic")\n')
    root = tmp_path/'owned'
    root.mkdir()
    instance = MuseGuidance(root, '/synthetic/muse', config_root=tmp_path/'config')
    def command(args, **kwargs):
        assert '--force' not in args
        action = args[2]
        exists = instance.target.exists()
        if action == 'inspect':
            value = {'skill':{'id':'capy-development','scope':'user'}} if exists else {'error':{'code':'unknown-skill'}}
            return subprocess.CompletedProcess(args,0 if exists else 1,json.dumps(value),'')
        if action == 'install':
            shutil.copytree(source, instance.target)
        elif action == 'uninstall':
            shutil.rmtree(instance.target)
        return subprocess.CompletedProcess(args,0,'{}','')
    monkeypatch.setattr(muse_guidance.subprocess, 'run', command)
    return instance,source,command


def test_native_install_replay_remove_preserves_shared_files(adapter):
    instance,source,_ = adapter
    path = instance.install(source)
    assert path == str(instance.target/'SKILL.md')
    assert instance.install(source) == path
    assert instance.remove()['shared_installation_preserved']
    assert source.exists() and not instance.target.exists()
    assert instance.remove()['status'] == 'REMOVED'
    assert instance.install(source) == path


def test_foreign_native_skill_is_never_adopted(adapter):
    instance,source,_ = adapter
    shutil.copytree(source,instance.target)
    with pytest.raises(DeveloperError, match='not owned'):
        instance.install(source)
    assert not instance.receipt.exists()
    assert instance.target.exists()


def test_modified_or_extra_native_files_block_removal(adapter):
    instance,source,_ = adapter
    instance.install(source)
    (instance.target/'user-note.txt').write_text('keep me')
    with pytest.raises(DeveloperError):
        instance.remove()
    assert (instance.target/'user-note.txt').read_text() == 'keep me'


def test_lost_native_install_reply_recovers_exact_owned_files(adapter, monkeypatch):
    instance,source,command = adapter
    def interrupted(args,**kwargs):
        result = command(args,**kwargs)
        if args[2] == 'install':
            raise subprocess.TimeoutExpired(args,30)
        return result
    monkeypatch.setattr(muse_guidance.subprocess,'run',interrupted)
    with pytest.raises(DeveloperError):
        instance.install(source)
    assert json.loads(instance.receipt.read_text())['state'] == 'PREPARING'
    monkeypatch.setattr(muse_guidance.subprocess,'run',command)
    instance.install(source)
    assert json.loads(instance.receipt.read_text())['state'] == 'CONFIGURED'


@pytest.mark.parametrize('raw', ['not-json', '[]', 'null'])
def test_invalid_receipt_preserves_native_guidance(adapter, raw):
    instance, source, _ = adapter
    instance.install(source)
    instance.receipt.write_text(raw)
    with pytest.raises(DeveloperError):
        instance.remove()
    assert instance.target.exists()


@pytest.mark.parametrize('value', [{'error': 'failure'}, {'skill': None}])
def test_malformed_native_reply_is_structured(adapter, monkeypatch, value):
    instance, source, _ = adapter
    monkeypatch.setattr(muse_guidance.subprocess, 'run', lambda args, **kwargs:
        subprocess.CompletedProcess(args, 1 if 'error' in value else 0, json.dumps(value), ''))
    with pytest.raises(DeveloperError):
        instance.install(source)
    assert not instance.receipt.exists()


def test_removal_preflight_recovers_interrupted_uninstall(adapter, monkeypatch):
    instance, source, command = adapter
    instance.install(source)
    def interrupted(args, **kwargs):
        if args[2] == 'uninstall':
            raise subprocess.TimeoutExpired(args, 30)
        return command(args, **kwargs)
    monkeypatch.setattr(muse_guidance.subprocess, 'run', interrupted)
    with pytest.raises(DeveloperError):
        instance.remove()
    assert instance.preflight_remove()[0]['state'] == 'REMOVING'
    monkeypatch.setattr(muse_guidance.subprocess, 'run', command)
    assert instance.remove()['status'] == 'REMOVED'
