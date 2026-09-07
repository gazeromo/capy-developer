import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from capy_developer.core import DeveloperCore
from capy_developer.developer_status import status
from capy_developer.desktop.companion import Companion
from capy_developer.desktop.credentials import FileCredentials
from capy_developer.harness_client import HarnessClient
from capy_developer.installation import roots
from test_installation_discovery import config


def test_actual_mcp_list_and_fail_closed_start(tmp_path):
    cfg = config(tmp_path / 'owned')
    env = {**os.environ, **roots(cfg), 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
    messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}]
    for i, intent in enumerate(({}, {'existing': {'name': 'Example'}, 'new': {'name': 'Example', 'application_id': 'example'}}), 2):
        messages.append({'jsonrpc': '2.0', 'id': i, 'method': 'tools/call', 'params': {'name': 'capy_development_start', 'arguments': {'request': 'Build app', 'idempotency_key': str(i), **intent}}})
    messages.append({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'capy_developer_status', 'arguments': {}}})
    proc = subprocess.run([sys.executable, '-m', 'capy_developer', 'mcp'], input=''.join(json.dumps(m) + '\n' for m in messages), text=True, capture_output=True, env=env, check=True)
    responses = [json.loads(line)['result'] for line in proc.stdout.splitlines()]
    tools = responses[0]['tools']
    start = next(t for t in tools if t['name'] == 'capy_development_start')
    assert 'oneOf' not in start['inputSchema']
    assert set(start['inputSchema']['properties']) == {'request', 'idempotency_key', 'existing', 'new'}
    assert 'Example:' in start['description']
    work_schema = next(t for t in tools if t['name'] == 'capy_work_begin')['inputSchema']
    assert 'oneOf' not in work_schema
    assert 'session_id' in work_schema['properties']
    assert all(r['isError'] and 'PROJECT_INTENT_INVALID' in json.dumps(r) for r in responses[1:3])
    state = responses[3]['structuredContent']
    assert state['toolset_sha256'] == hashlib.sha256(json.dumps(tools, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert state['remote_status'] == 'NOT_CHECKED'
    assert str(cfg.data_root) not in json.dumps(state)


def test_status_safe_read_only_and_conflict(tmp_path, monkeypatch):
    cfg = config(tmp_path / 'owned')
    core = DeveloperCore(cfg)
    harness = HarnessClient(core, companion=Companion(core, credential_store=FileCredentials(test_owned=True)))
    state = harness.companion.state
    with state.connect() as db:
        db.execute('INSERT INTO pairs VALUES (?,?,?,?,NULL,NULL,NULL,?,?,?)', ('site_' + '1'*32, 'https://example.test', '1'*32, 'SECRET_SENTINEL', 9999999999, 'APPROVED', 'Example'))
        db.execute('INSERT INTO harness_clients VALUES (?,?,?,?,?,?,NULL)', ('site_' + '1'*32, 'codex', '1'*32, 'cli_'+'2'*32, 'v1', 'MCP_STDIO'))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in (cfg.database, state.path)}
    monkeypatch.setattr(type(state), 'credentials', property(lambda self: (_ for _ in ()).throw(AssertionError('no secrets'))))
    result = status(cfg, {'session_id': 'missing'})
    assert result['installation']['installation_id'] == '1'*32
    assert result['session']['status'] == 'NOT_FOUND'
    assert 'SECRET_SENTINEL' not in json.dumps(result)
    assert str(cfg.data_root) not in json.dumps(result)
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before}
    with state.connect() as db:
        db.execute('INSERT INTO pairs VALUES (?,?,?,?,NULL,NULL,NULL,?,?,?)', ('site_' + '3'*32, 'https://other.test', '3'*32, 'OTHER_SECRET', 9999999999, 'APPROVED', 'Other'))
    assert status(cfg)['installation']['status'] == 'CONFIGURED_CONNECTION_AMBIGUOUS'


def test_cli_status_uses_same_readonly_surface(tmp_path, monkeypatch):
    from capy_developer import cli, installation
    cfg = config(tmp_path / 'owned')
    DeveloperCore(cfg)
    monkeypatch.setattr(installation, 'discover', lambda **kwargs: {'status': 'EXISTING', 'config': cfg})
    monkeypatch.setattr(cli, 'DeveloperCore', lambda *args: (_ for _ in ()).throw(AssertionError('no initialization')))
    assert cli.run(['developer-status']) == status(cfg)
