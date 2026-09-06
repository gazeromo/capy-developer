"""Shared CLI/MCP facade for computer-scoped linked development work."""
from __future__ import annotations

import json
import re
import secrets

from .desktop.companion import Companion, require
from .errors import DeveloperError
from .link_protocol import canonical, make_uri, origin, validate_request


def connection_info(transport, site):
    origin(site)
    info = transport.connection_info(site)
    require(set(info) == {'schema','site_id','origin','capability'} and info['schema'] == 'capy.harness-connection/v0'
            and info['origin'] == site and info['capability'] == 'harness-first/v0',
            'LINK_CAPABILITY_UNAVAILABLE', 'this site does not support harness-first work')
    require(isinstance(info['site_id'], str) and bool(re.fullmatch(r'site_[0-9a-f]{32}', info['site_id'])),
            'SITE_ID_INVALID', 'invalid site identity')
    return info


class HarnessClient:
    @classmethod
    def diagnostics(cls, config, *, transport=None, credential_store=None):
        # Diagnostics need pairing references, never catalog migrations/toolchains.
        from types import SimpleNamespace
        core = SimpleNamespace(config=config)
        return cls(core, companion=Companion(core, transport=transport,
            credential_store=credential_store, read_only=True))

    def __init__(self, core, *, companion=None):
        self.core = core
        self.companion = companion or Companion(core)
        if self.companion.state.read_only:
            import sqlite3
            try:
                with self.companion.state.connect() as db:
                    db.execute('SELECT site,adapter,installation,client,version,transport,challenge FROM harness_clients LIMIT 0')
            except sqlite3.Error:
                raise DeveloperError('CLIENT_NOT_CONFIGURED', 'configure the coding client before checking it') from None
            return
        with self.companion.state.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS harness_clients(
                    site TEXT NOT NULL, adapter TEXT NOT NULL, installation TEXT NOT NULL,
                    client TEXT NOT NULL, version TEXT NOT NULL, transport TEXT NOT NULL,
                    challenge TEXT, PRIMARY KEY(site,adapter));
                CREATE TABLE IF NOT EXISTS harness_work(
                    intent TEXT PRIMARY KEY, site TEXT NOT NULL, client TEXT NOT NULL,
                    installation TEXT NOT NULL, input TEXT NOT NULL, request TEXT);
            ''')

    def clients(self):
        with self.companion.state.connect() as db:
            rows = db.execute('SELECT site,adapter,client,version,transport FROM harness_clients ORDER BY site,adapter').fetchall()
        return {'ok':True, 'clients':[{**dict(r), 'adapter':r['adapter'].split(':',1)[0]} for r in rows]}

    def work(self):
        with self.companion.state.connect() as db:
            rows = db.execute('SELECT site,client,request FROM harness_work WHERE request IS NOT NULL ORDER BY intent').fetchall()
        result = []
        for row in rows:
            request = json.loads(row['request'])
            try:
                handoff = self.companion.state.handoff(request['handoff_id'])
            except DeveloperError:
                continue
            result.append({'site_id':row['site'],'client_id':row['client'],'handoff_id':request['handoff_id'],
                           'project_id':handoff['project_id'],'session_id':handoff['session_id'],
                           'snapshot':json.loads(handoff['last_snapshot']) if handoff['last_snapshot'] else None})
        return {'ok':True,'work':result}

    def _post(self, site_id, operation, value):
        pair = self.companion._approved(site_id)
        return self.companion.transport.post(pair['origin'], '/api/developer-link/harness-v0/' + operation,
            {'site_id': site_id, 'device_id': pair['device_id'], **value}, pair['secret'])

    def connect(self, site, adapter, version, transport='JSON_CLI'):
        origin(site)
        require(adapter in ('muse', 'codex'), 'CLIENT_UNSUPPORTED', 'choose a supported coding client')
        require(transport in ('JSON_CLI', 'MCP_STDIO'), 'CLIENT_CHANNEL_INVALID', 'unsupported tool channel')
        require(isinstance(version, str) and bool(re.fullmatch(r'[A-Za-z0-9 ._()+-]{1,80}', version)),
                'CLIENT_VERSION_INVALID', 'invalid observed coding client version')
        info = connection_info(self.companion.transport, site)
        site_id = info['site_id']
        require(isinstance(site_id, str) and bool(re.fullmatch(r'site_[0-9a-f]{32}', site_id)),
                'SITE_ID_INVALID', 'invalid site identity')
        pairs = {p['site_id']:p for p in self.companion.connections()}
        if site_id in pairs and pairs[site_id]['state'] in ('PENDING','STARTING') and pairs[site_id]['expires_at'] > self.companion.clock():
            pair = self.companion.pair_poll(site_id) if pairs[site_id]['state'] == 'PENDING' else self.companion.pair_start(site, site_id)
        else:
            pair = self.companion.pair_start(site, site_id)
        if pair.get('state', pair.get('status')) != 'APPROVED':
            return {'ok':True, 'status':'WAITING_FOR_ACCOUNT_APPROVAL', 'connection':pair, 'ready':False}
        status = self._post(site_id, 'status', {})
        if not status.get('approved'):
            expected = '/developer/connections/' + pair['device_id'] + '/work'
            require(status.get('approval_path') == expected, 'LINK_RESPONSE_INVALID', 'invalid approval path')
            return {'ok':True, 'status':'WAITING_FOR_WORK_APPROVAL', 'approval_url':site + expected, 'ready':False}
        pair = self.companion._approved(site_id)
        with self.companion._lock(), self.companion.state.connect() as db:
            # A newly configured channel is a separate observed client instance.
            # Keep the old channel's identity/history under the same computer.
            key = adapter
            prior = db.execute('SELECT * FROM harness_clients WHERE site=? AND adapter=?', (site_id, adapter)).fetchone()
            if prior is not None and prior['transport'] != transport:
                key = adapter + ':' + transport
            row = db.execute('SELECT * FROM harness_clients WHERE site=? AND adapter=?', (site_id, key)).fetchone()
            if row:
                require(row['installation'] == pair['installation_id'] and row['version'] == version and row['transport'] == transport,
                        'CLIENT_REGISTRATION_CONFLICT', 'existing client registration differs; inspect it before changing setup')
            else:
                db.execute('INSERT INTO harness_clients VALUES (?,?,?,?,?,?,NULL)',
                           (site_id, key, pair['installation_id'], 'cli_' + secrets.token_hex(16), version, transport))
            row = dict(db.execute('SELECT * FROM harness_clients WHERE site=? AND adapter=?', (site_id, key)).fetchone())
        challenge = self._post(site_id, 'register', {'client_id':row['client'], 'label':'Muse Code' if adapter == 'muse' else 'Codex',
                                                  'version':version, 'transport':transport})
        require(set(challenge) == {'client_id','nonce','expires_at'} and challenge['client_id'] == row['client']
                and isinstance(challenge['nonce'], str) and bool(re.fullmatch(r'[0-9a-f]{64}', challenge['nonce']))
                and type(challenge['expires_at']) is int, 'CLIENT_CHALLENGE_INVALID', 'invalid site client challenge')
        with self.companion.state.connect() as db:
            db.execute('UPDATE harness_clients SET challenge=? WHERE site=? AND adapter=?', (canonical(challenge).decode(), site_id, key))
        return {'ok':True, 'status':'CONFIGURED_WAITING_FOR_TOOL_CHECK', 'site_id':site_id, 'client_id':row['client'], 'ready':False}

    def _client(self, client_id):
        require(isinstance(client_id, str) and bool(re.fullmatch(r'cli_[0-9a-f]{32}', client_id)), 'CLIENT_ID_INVALID', 'invalid coding client reference')
        with self.companion.state.connect() as db:
            rows = db.execute('SELECT * FROM harness_clients WHERE client=?', (client_id,)).fetchall()
        require(len(rows) == 1, 'CLIENT_NOT_FOUND', 'connect this coding client first')
        row = dict(rows[0])
        pair = self.companion._approved(row['site'])
        require(pair['installation_id'] == row['installation'], 'CLIENT_CONNECTION_REPLACED', 'client belongs to a previous computer connection')
        return row

    def check(self, client_id, *, channel):
        row = self._client(client_id)
        require(row['transport'] == channel, 'CLIENT_CHANNEL_MISMATCH', 'call through the configured tool channel')
        require(row['challenge'] is not None, 'CLIENT_CHECK_NOT_PREPARED', 'resume connect to obtain a tool challenge')
        challenge = json.loads(row['challenge'])
        return self._post(row['site'], 'check', {'client_id':client_id, 'nonce':challenge['nonce']})

    def status(self, client_id):
        row = self._client(client_id)
        return self._post(row['site'], 'status', {})

    def begin(self, value):
        require(isinstance(value, dict) and set(value) in (
            {'client_id','intent_id','request','new'}, {'client_id','intent_id','request','parent_handoff_id'}),
            'WORK_INPUT_INVALID', 'provide an explicit new app or an exact completed linked handoff')
        require(isinstance(value['intent_id'], str) and bool(re.fullmatch(r'[0-9a-f]{32}', value['intent_id'])),
                'WORK_INTENT_INVALID', 'invalid durable work intent')
        require(isinstance(value['request'], str) and 0 < len(value['request'].strip()) <= 10000,
                'WORK_REQUEST_INVALID', 'provide a bounded local development objective')
        if 'new' in value:
            require(isinstance(value['new'], dict) and set(value['new']) == {'name','application_id'}, 'WORK_INPUT_INVALID', 'new apps require name and application_id')
            require(all(isinstance(v,str) for v in value['new'].values()), 'WORK_INPUT_INVALID', 'new application identifiers must be strings')
            self.core._normalize_start({'idempotency_key':value['intent_id'], 'request':value['request'], 'new':value['new']})
        parent = value.get('parent_handoff_id')
        if 'parent_handoff_id' in value:
            require(isinstance(parent, str) and bool(re.fullmatch(r'hof_[0-9a-f]{32}', parent)), 'WORK_INPUT_INVALID', 'invalid parent handoff')
        row = self._client(value['client_id'])
        encoded = canonical(value).decode()
        with self.companion._lock(), self.companion.state.connect() as db:
            old = db.execute('SELECT * FROM harness_work WHERE intent=?', (value['intent_id'],)).fetchone()
            if old:
                require(old['input'] == encoded and old['installation'] == row['installation'], 'WORK_INTENT_CONFLICT', 'this intent already names different exact work')
            else:
                db.execute('INSERT INTO harness_work VALUES (?,?,?,?,?,NULL)',
                           (value['intent_id'], row['site'], row['client'], row['installation'], encoded))
        # Always revalidate current server authority, even after a saved reply.
        request = validate_request(self._post(row['site'], 'begin', {'client_id':row['client'],
            'intent_id':value['intent_id'], 'parent_handoff_id':parent}))
        pair = self.companion._approved(row['site'])
        require(request['site_id'] == row['site'] and request['device_id'] == pair['device_id']
                and request['principal_id'] == pair['principal_id'] and request['parent_handoff_id'] == parent,
                'WORK_AUTHORITY_MISMATCH', 'site returned work for another authority')
        with self.companion.state.connect() as db:
            db.execute('UPDATE harness_work SET request=? WHERE intent=?', (canonical(request).decode(), value['intent_id']))
        local = {'new':value['new'], 'request':value['request']} if 'new' in value else {'request':value['request']}
        progress = self.companion.prepare_uri(make_uri(row['site'], request['handoff_id'], request['launch_generation']), local_request=local)
        handoff = self.companion.state.handoff(request['handoff_id'])
        development = self.core.inspect_development(handoff['session_id'])
        return {'ok':True, 'handoff_id':request['handoff_id'], 'development':development,
                'progress':progress, 'workspace_adoption':'REQUIRED',
                'review_url':pair['origin'] + '/developer/requests/' + request['handoff_id']}
