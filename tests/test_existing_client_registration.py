import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from capy_developer.errors import DeveloperError
from capy_developer.harness_client import HarnessClient
from test_desktop import SITE, DEVICE, NOW
import test_desktop


@pytest.fixture
def legacy(tmp_path, monkeypatch):
    monkeypatch.setattr('tempfile.tempdir', str(tmp_path.resolve()))
    case = test_desktop.DesktopTests()
    case.setUp()
    monkeypatch.setattr('capy_developer.harness_client.observed_client_version', lambda adapter: '0.153.4')
    case.transport.connection_info = lambda site: {'schema': 'capy.harness-connection/v0', 'site_id': SITE, 'origin': site, 'capability': 'harness-first/v0'}
    yield case
    case.tearDown()


def test_legacy_pair_registration_keeps_authority_and_does_not_pair(legacy, monkeypatch):
    case = legacy
    pair_before = case.companion.state.pair_record(SITE)
    harness = HarnessClient(case.core, companion=case.companion)
    calls = []
    def post(site, operation, value):
        calls.append(operation)
        if operation == 'status':
            return {'approved': True}
        if operation == 'register':
            return {'client_id': value['client_id'], 'nonce': 'a'*64, 'expires_at': NOW+600}
        raise AssertionError(operation)
    monkeypatch.setattr(harness, '_post', post)
    monkeypatch.setattr(case.companion, 'pair_start', lambda *args: pytest.fail('must not create or replace pairing'))
    result = harness.register_existing({'site_id': SITE, 'client': 'codex'})
    assert result['status'] == 'CONFIGURED_WAITING_FOR_TOOL_CHECK' and result['ready'] is False
    assert result['next_action'] == {'tool': 'capy_client_check', 'arguments': {'client_id': result['client_id']}}
    assert case.companion.state.pair_record(SITE) == pair_before
    assert calls == ['status', 'register']
    assert not case.core.starts
    with case.companion.state.connect() as db:
        row = db.execute('SELECT * FROM harness_clients').fetchone()
        assert row['installation'] == pair_before['installation_id'] and row['transport'] == 'MCP_STDIO'
    replay = harness.register_existing({'site_id': SITE, 'client': 'codex'})
    assert replay['client_id'] == result['client_id']


def test_existing_registration_preserves_human_scope_approval(legacy, monkeypatch):
    case = legacy
    harness = HarnessClient(case.core, companion=case.companion)
    monkeypatch.setattr(harness, '_post', lambda *args: {'approved': False, 'approval_path': '/developer/connections/'+DEVICE+'/work'})
    result = harness.register_existing({'site_id': SITE, 'client': 'codex'})
    assert result == {'ok': True, 'status': 'WAITING_FOR_WORK_APPROVAL',
                      'approval_url': 'https://capy.example/developer/connections/'+DEVICE+'/work', 'ready': False}
    with case.companion.state.connect() as db:
        assert db.execute('SELECT count(*) FROM harness_clients').fetchone()[0] == 0


def test_explicit_site_invalid_revoked_and_changed_remote_identity_fail(legacy):
    case = legacy
    harness = HarnessClient(case.core, companion=case.companion)
    for value in ({'client': 'codex'}, {'site_id': SITE, 'client': 'codex', 'root': 'arbitrary'},
                  {'site_id': 'site_'+'9'*32, 'client': 'codex'}, {'site_id': SITE, 'client': 'other'}):
        with pytest.raises(DeveloperError):
            harness.register_existing(value)
    case.transport.connection_info = lambda site: {'schema': 'capy.harness-connection/v0', 'site_id': 'site_'+'9'*32, 'origin': site, 'capability': 'harness-first/v0'}
    with pytest.raises(DeveloperError, match='different identity'):
        harness.register_existing({'site_id': SITE, 'client': 'codex'})
    with case.companion.state.connect() as db:
        db.execute("UPDATE pairs SET state='REVOKED' WHERE site_id=?", (SITE,))
    with pytest.raises(DeveloperError, match='normal approval'):
        harness.register_existing({'site_id': SITE, 'client': 'codex'})


def test_actual_mcp_registers_configured_legacy_pair_despite_conflicting_catalog(tmp_path):
    from capy_developer.installation import roots
    from test_installation_discovery import config
    cfg = config(tmp_path / 'configured')
    env = {**os.environ, **roots(cfg), 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
           'SYNTHETIC_ROOT': str(tmp_path)}
    script = '''
import json, os
from pathlib import Path
from capy_developer.core import DeveloperCore
from capy_developer.config import Config
from capy_developer.desktop.companion import Companion
from capy_developer.desktop.credentials import FileCredentials
from capy_developer.desktop.state import State
from capy_developer.desktop.setup import Setup
from capy_developer.desktop.transport import Transport
from capy_developer.installation import discover
from capy_developer.errors import DeveloperError
from capy_developer.mcp import serve
import capy_developer.harness_client as client
root=Path(os.environ['SYNTHETIC_ROOT'])
core=DeveloperCore()
setup=Setup(core,config_path=root/'codex/config.toml');setup.install(native=False)
other=Config(*(root/'unrelated'/name for name in ('data','cache','repos','trees','temp')))
DeveloperCore(other)
try:
    discover(default=other,config_path=root/'codex/config.toml')
except DeveloperError as exc:
    assert exc.code=='INSTALLATION_CONFLICT'
else:
    raise AssertionError('global ambiguity must remain fail closed')
credentials=FileCredentials(test_owned=True)
companion=Companion(core,credential_store=credentials)
reference=credentials.store('a'*32,'b'*64)
with companion.state.connect() as db:
    db.execute('INSERT INTO pairs VALUES (?,?,?,?,NULL,?,?,?, ?,?)', ('site_'+'a'*32,'https://example.test','a'*32,reference,'dev_'+'a'*32,'principal.fixture',9999999999,'APPROVED','Synthetic'))
    assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='harness_clients'").fetchone()
State.credentials=property(lambda self:credentials)
client.observed_client_version=lambda adapter:'0.153.4'
Transport.connection_info=lambda self,site:dict(schema='capy.harness-connection/v0',site_id='site_'+'a'*32,origin=site,capability='harness-first/v0')
def post(self,site,path,payload,secret):
    assert site=='https://example.test' and secret=='b'*64
    if path=='/api/developer-link/harness-v0/status':return {'approved':True}
    if path=='/api/developer-link/harness-v0/register':return {'client_id':payload['client_id'],'nonce':'c'*64,'expires_at':9999999999}
    raise AssertionError('No pairing/bootstrap or arbitrary request is allowed')
Transport.post=post
serve()
'''
    requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'capy_developer_status', 'arguments': {}}},
                {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'capy_client_register_existing', 'arguments': {'site_id': 'site_'+'a'*32, 'client': 'codex'}}}]
    proc = subprocess.run([sys.executable, '-c', script], input=''.join(json.dumps(r)+'\n' for r in requests), text=True, capture_output=True, env=env, check=True)
    values = [json.loads(line)['result'] for line in proc.stdout.splitlines()]
    tool = next(t for t in values[0]['tools'] if t['name'] == 'capy_client_register_existing')
    assert set(tool['inputSchema']['properties']) == {'site_id', 'client'}
    assert set(tool['inputSchema']['required']) == {'site_id', 'client'}
    status = values[1]['structuredContent']
    assert status['client_registration']['tool'] == 'capy_client_register_existing'
    assert 'do not run bootstrap' in status['next_action']
    assert values[2]['isError'] is False, values[2]
    assert values[2]['structuredContent']['status'] == 'CONFIGURED_WAITING_FOR_TOOL_CHECK'


def test_replaced_connection_during_registration_is_not_adopted(legacy):
    case = legacy
    harness = HarnessClient(case.core, companion=case.companion)
    def info(site):
        with case.companion.state.connect() as db:
            db.execute('UPDATE pairs SET installation_id=? WHERE site_id=?', ('9'*32, SITE))
        return {'schema': 'capy.harness-connection/v0', 'site_id': SITE, 'origin': site, 'capability': 'harness-first/v0'}
    case.transport.connection_info = info
    with pytest.raises(DeveloperError, match='connection changed'):
        harness.register_existing({'site_id': SITE, 'client': 'codex'})
    with case.companion.state.connect() as db:
        assert db.execute('SELECT count(*) FROM harness_clients').fetchone()[0] == 0
