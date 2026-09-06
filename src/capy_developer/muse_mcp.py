"""Owned native Muse MCP entry using the documented settings.json schema."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from .desktop.companion import require
from .desktop.setup import atomic
from .errors import DeveloperError
from .installation import read_owned, roots
from .link_protocol import canonical
from .util import operation_lock


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'CLIENT_SETUP_CONFLICT', 'Muse settings contain duplicate JSON keys')
        result[key] = value
    return result


def _parse(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise DeveloperError('CLIENT_SETUP_CONFLICT', 'Muse settings are not valid JSON') from None
    require(isinstance(value,dict) and type(value.get('schema_version')) is int and value.get('schema_version') == 1 and isinstance(value.get('mcp_servers',{}),dict),
            'CLIENT_SETUP_CONFLICT', 'unsupported Muse settings schema')
    return value


def _members(text, start=0):
    """Locate object members without rewriting unknown values or their spelling."""
    decoder = json.JSONDecoder()
    pos = start
    while text[pos].isspace(): pos += 1
    require(text[pos] == '{', 'CLIENT_SETUP_CONFLICT', 'expected a settings object')
    pos += 1
    result = []
    while True:
        while text[pos].isspace(): pos += 1
        if text[pos] == '}': return result, pos
        begin = pos
        key, pos = decoder.raw_decode(text,pos)
        while text[pos].isspace(): pos += 1
        require(text[pos] == ':', 'CLIENT_SETUP_CONFLICT', 'invalid settings member')
        pos += 1
        while text[pos].isspace(): pos += 1
        value_start = pos
        _, pos = decoder.raw_decode(text,pos)
        result.append((key,begin,value_start,pos))
        while text[pos].isspace(): pos += 1
        if text[pos] == ',': pos += 1
        else:
            require(text[pos] == '}', 'CLIENT_SETUP_CONFLICT', 'invalid settings object')
            return result,pos


def _insert(text, start, key, value):
    members, end = _members(text,start)
    pos = members[-1][3] if members else end
    addition = (',' if members else '') + json.dumps(key) + ':' + json.dumps(value,separators=(',',':'))
    return text[:pos] + addition + text[pos:]


def _remove(text, start, key):
    members,_ = _members(text,start)
    for index,member in enumerate(members):
        if member[0] == key:
            if index+1 < len(members): left,right = member[1],members[index+1][1]
            elif index: left,right = members[index-1][3],member[3]
            else: left,right = member[1],member[3]
            return text[:left]+text[right:]
    return text


class MuseMcpSetup:
    key = 'capy_developer'

    def __init__(self, config, settings):
        self.config,self.settings = config,Path(settings)
        self.root = config.data_root/'client-setup'
        self.receipt = self.root/'muse-mcp.json'
        self.before = self.root/'muse-settings.before'
        self.entry = {'transport':'stdio','command':sys.executable,'args':['-m','capy_developer.cli','mcp'],
                      'env':roots(config),'enabled':True,'mode':'optional'}

    def _read(self):
        require(not any(p.is_symlink() for p in (self.settings,*self.settings.parents)),
                'CLIENT_SETUP_CONFLICT', 'Muse settings path cannot pass through symlinks')
        return read_owned(self.settings,1048576) if self.settings.exists() else None

    def _saved(self):
        if not self.receipt.exists():
            require(not self.receipt.is_symlink(),'CLIENT_SETUP_CONFLICT','invalid MCP ownership receipt')
            return None
        try:
            value = json.loads(read_owned(self.receipt))
        except (ValueError, UnicodeError):
            raise DeveloperError('CLIENT_SETUP_CONFLICT', 'invalid MCP ownership receipt') from None
        require(isinstance(value,dict) and value.get('schema')=='capy.muse-mcp/v0' and value.get('settings')==str(self.settings),
                'CLIENT_SETUP_CONFLICT','MCP entry belongs to another settings file')
        return value

    def preflight(self):
        raw = self._read()
        value = _parse(raw) if raw is not None else {'schema_version':1}
        saved = self._saved()
        present = self.key in value.get('mcp_servers',{})
        if present:
            require(saved is not None and saved.get('state') in ('PREPARING','CONFIGURED')
                    and saved.get('entry')==self.entry and value['mcp_servers'][self.key]==self.entry,
                    'CLIENT_SETUP_CONFLICT','existing Muse Capy MCP entry is unowned or modified')
        elif saved is not None and saved.get('state')=='CONFIGURED':
            raise DeveloperError('CLIENT_SETUP_CONFLICT','owned Muse MCP entry was removed outside setup')
        return raw,value,saved,present

    def install(self):
        with operation_lock(self.root/'muse-mcp.lock'):
            raw,value,saved,present = self.preflight()
            if present:
                saved['state']='CONFIGURED';atomic(self.receipt,canonical(saved))
                return {'transport':'MCP_STDIO','reload':'TOOLS_RELOAD_REQUIRED'}
            text = raw.decode() if raw is not None else '{"schema_version":1}\n'
            if 'mcp_servers' in value:
                member=next(x for x in _members(text)[0] if x[0]=='mcp_servers')
                after=_insert(text,member[2],self.key,self.entry).encode()
            else: after=_insert(text,0,'mcp_servers',{self.key:self.entry}).encode()
            _parse(after)
            receipt=dict(schema='capy.muse-mcp/v0',state='PREPARING',settings=str(self.settings),entry=self.entry,
                before_exists=raw is not None,before_sha256=hashlib.sha256(raw or b'').hexdigest(),
                after_sha256=hashlib.sha256(after).hexdigest(),created_servers='mcp_servers' not in value)
            require(saved is not None or (not self.before.exists() and not self.before.is_symlink()),
                    'CLIENT_SETUP_CONFLICT','unowned settings preservation file exists')
            atomic(self.before,raw or b'')
            atomic(self.receipt,canonical(receipt))
            require(self._read()==raw,'CLIENT_SETUP_CONFLICT','Muse settings changed during setup')
            atomic(self.settings,after)
            require(self._read()==after,'CLIENT_SETUP_CONFLICT','Muse settings changed during verification')
            receipt['state']='CONFIGURED';atomic(self.receipt,canonical(receipt))
            return {'transport':'MCP_STDIO','reload':'TOOLS_RELOAD_REQUIRED'}

    def remove(self):
        with operation_lock(self.root/'muse-mcp.lock'):
            raw=self._read();saved=self._saved()
            require(saved is not None,'CLIENT_SETUP_CONFLICT','no owned Muse MCP entry to remove')
            if saved.get('state')=='REMOVED' or (saved.get('state')=='REMOVING' and (raw is None or self.key not in _parse(raw).get('mcp_servers',{}))):
                require(raw is None or self.key not in _parse(raw).get('mcp_servers',{}),
                        'CLIENT_SETUP_CONFLICT','another MCP entry replaced the removed integration')
                saved['state']='REMOVED';atomic(self.receipt,canonical(saved))
                return {'ok':True,'status':'REMOVED','shared_installation_preserved':True}
            value=_parse(raw) if raw is not None else {}
            require(value.get('mcp_servers',{}).get(self.key)==saved.get('entry'),
                    'CLIENT_SETUP_CONFLICT','owned Muse MCP entry changed; removal refused')
            original=read_owned(self.before,1048576)
            require(hashlib.sha256(original).hexdigest()==saved['before_sha256'],
                    'CLIENT_SETUP_CONFLICT','settings preservation receipt changed')
            if hashlib.sha256(raw).hexdigest()==saved['after_sha256']:
                after=original if saved['before_exists'] else None
            else:
                text=raw.decode();member=next(x for x in _members(text)[0] if x[0]=='mcp_servers')
                text=_remove(text,member[2],self.key)
                if saved['created_servers'] and not _parse(text)['mcp_servers']: text=_remove(text,0,'mcp_servers')
                after=text.encode()
            saved['state']='REMOVING';atomic(self.receipt,canonical(saved))
            require(self._read()==raw,'CLIENT_SETUP_CONFLICT','Muse settings changed during removal')
            if after is None: self.settings.unlink()
            else:
                _parse(after);atomic(self.settings,after)
            saved['state']='REMOVED';atomic(self.receipt,canonical(saved))
            return {'ok':True,'status':'REMOVED','shared_installation_preserved':True}
