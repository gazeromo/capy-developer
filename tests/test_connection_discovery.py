import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from capy_developer.connection_discovery import validate_request, validate_response
from capy_developer.errors import DeveloperError
from capy_developer.installation import roots
from test_installation_discovery import config


def metadata():
    schema = {'type': 'object', 'properties': {'value': {'type': 'string'}}, 'required': ['value'], 'additionalProperties': False}
    return {'schema': 'capy.managed-connection-contracts/v0', 'contracts': [
        {'contract': 'example.read/v1', 'name': 'Example read', 'operation': 'read',
         'request_schema': schema, 'result_schema': schema, 'examples': [{'request': {'value': 'Example'}, 'result': {'value': 'Example'}}],
         'credential': 'managed_by_capy', 'binding': 'team_configuration', 'availability': 'not_checked', 'notes': ['Synthetic contract.']}]}


def test_generic_bounded_metadata_validation_rejects_injection():
    assert validate_response(metadata(), 'example.read/v1') == metadata()
    for mutation in (
        lambda x: x.update({'url': 'https://untrusted.test'}),
        lambda x: x['contracts'][0].update({'credential_path': '/private/secret'}),
        lambda x: x['contracts'][0]['examples'][0]['request'].update({'account_number': 'synthetic-account'}),
        lambda x: x['contracts'][0]['request_schema'].update({'$ref': 'https://untrusted.test'}),
        lambda x: x['contracts'][0].update({'availability': 'configured'}),
        lambda x: x['contracts'][0].update({'notes': ['x'*70000]}),
        lambda x: x['contracts'][0].update({'notes': ['https://untrusted.test']}),
    ):
        value = copy.deepcopy(metadata())
        mutation(value)
        with pytest.raises(DeveloperError, match='unsupported connection metadata'):
            validate_response(value)
    with pytest.raises(DeveloperError):
        validate_response(metadata(), 'another/v1')
    for contract in ('../../secret', 'https://untrusted.test', '/api/override', None):
        with pytest.raises(DeveloperError):
            validate_request({'client_id': 'cli_'+'1'*32, 'contract': contract})


def test_actual_mcp_lists_tool_and_returns_validated_fixed_route_metadata(tmp_path):
    cfg = config(tmp_path / 'owned')
    env = {**os.environ, **roots(cfg), 'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'), 'SYNTHETIC_METADATA': json.dumps(metadata())}
    script = '''
import json, os
from capy_developer.core import DeveloperCore
from capy_developer.desktop.companion import Companion
from capy_developer.desktop.credentials import FileCredentials
from capy_developer.desktop.state import State
from capy_developer.desktop.transport import Transport
from capy_developer.harness_client import HarnessClient
from capy_developer.mcp import serve
core = DeveloperCore()
credentials = FileCredentials(test_owned=True)
companion = Companion(core, credential_store=credentials)
harness = HarnessClient(core, companion=companion)
reference = credentials.store('a'*32, 'b'*64)
with companion.state.connect() as db:
    db.execute('INSERT INTO pairs VALUES (?,?,?,?,NULL,?,?,?, ?,?)', ('site_'+'a'*32, 'https://example.test', 'a'*32, reference, 'dev_'+'a'*32, 'principal.fixture', 9999999999, 'APPROVED', 'Synthetic'))
    db.execute('INSERT INTO harness_clients VALUES (?,?,?,?,?,?,NULL)', ('site_'+'a'*32, 'codex', 'a'*32, 'cli_'+'1'*32, 'v1', 'MCP_STDIO'))
State.credentials = property(lambda self: credentials)
def post(self, site, path, payload, secret):
    assert site == 'https://example.test'
    assert path == '/api/developer-link/harness-v0/connection-contracts'
    assert payload == {'site_id':'site_'+'a'*32, 'device_id':'dev_'+'a'*32, 'client_id':'cli_'+'1'*32, 'contract':'example.read/v1'}
    assert secret == 'b'*64
    return json.loads(os.environ['SYNTHETIC_METADATA'])
Transport.post = post
serve()
'''
    requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'capy_connection_contracts', 'arguments': {'client_id': 'cli_'+'1'*32, 'contract': 'example.read/v1'}}}]
    proc = subprocess.run([sys.executable, '-c', script], input=''.join(json.dumps(x)+'\n' for x in requests), capture_output=True, text=True, env=env, check=True)
    values = [json.loads(line)['result'] for line in proc.stdout.splitlines()]
    tool = next(t for t in values[0]['tools'] if t['name'] == 'capy_connection_contracts')
    assert set(tool['inputSchema']['properties']) == {'client_id', 'contract'}
    assert values[1]['isError'] is False, values[1]
    assert values[1]['structuredContent'] == metadata()
