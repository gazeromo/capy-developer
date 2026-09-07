"""Bounded generic metadata validation; provider contract knowledge stays on site."""
from __future__ import annotations

import json
import re

from .errors import DeveloperError

CONTRACT = re.compile(r'[a-z][a-z0-9.]{0,79}/v[1-9][0-9]{0,2}')
ENTRY_KEYS = {'contract', 'name', 'operation', 'request_schema', 'result_schema', 'examples',
              'credential', 'binding', 'availability', 'notes'}
SCHEMA_KEYS = {'type', 'properties', 'required', 'additionalProperties', 'items', 'oneOf', 'anyOf',
               'enum', 'const', 'description', 'format', 'pattern', 'minimum', 'maximum',
               'minLength', 'maxLength', 'minItems', 'maxItems'}


def require(condition):
    if not condition:
        raise DeveloperError('CONNECTION_CONTRACT_RESPONSE_INVALID', 'the site returned unsupported connection metadata; no contract was used')


def validate_request(arguments):
    if (not isinstance(arguments, dict) or set(arguments) not in ({'client_id'}, {'client_id', 'contract'})
            or not isinstance(arguments['client_id'], str)
            or re.fullmatch(r'cli_[0-9a-f]{32}', arguments['client_id']) is None
            or ('contract' in arguments and (not isinstance(arguments['contract'], str)
                                           or CONTRACT.fullmatch(arguments['contract']) is None))):
        raise DeveloperError('CONNECTION_CONTRACT_INPUT_INVALID', 'provide an exact configured client_id and optional contract identifier')


def validate_response(value, requested=None):
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        require(False)
    require(len(encoded.encode()) <= 65536)
    nodes = 0
    def bounded(item, depth=0):
        nonlocal nodes
        nodes += 1
        require(nodes <= 5000 and depth <= 20)
        if isinstance(item, dict):
            require(len(item) <= 64)
            for key, child in item.items():
                require(isinstance(key, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', key) is not None)
                require(key not in {'password', 'secret', 'client_secret', 'api_key', 'access_token', 'refresh_token', 'credential_path', 'credential_value', 'account_number'})
                bounded(child, depth + 1)
        elif isinstance(item, list):
            require(len(item) <= 64)
            for child in item:
                bounded(child, depth + 1)
        elif isinstance(item, str):
            require(len(item) <= 2048 and not any(ord(c) < 32 or ord(c) == 127 for c in item)
                    and '://' not in item and not item.startswith(('/', '~')))
        else:
            require(item is None or type(item) in (bool, int, float))
    bounded(value)
    require(isinstance(value, dict) and set(value) == {'schema', 'contracts'}
            and value['schema'] == 'capy.managed-connection-contracts/v0'
            and isinstance(value['contracts'], list) and 1 <= len(value['contracts']) <= 16)
    def schema(item):
        require(isinstance(item, dict) and not set(item) - SCHEMA_KEYS)
        if 'properties' in item:
            require(isinstance(item['properties'], dict))
            for child in item['properties'].values():
                schema(child)
        if 'items' in item:
            schema(item['items'])
        for union in ('oneOf', 'anyOf'):
            if union in item:
                require(isinstance(item[union], list) and 1 <= len(item[union]) <= 16)
                for child in item[union]:
                    schema(child)
    identities = set()
    for entry in value['contracts']:
        require(isinstance(entry, dict) and set(entry) == ENTRY_KEYS)
        require(isinstance(entry['contract'], str) and CONTRACT.fullmatch(entry['contract']) is not None)
        require(isinstance(entry['operation'], str) and re.fullmatch(r'[a-z][a-z0-9_]{0,63}', entry['operation']) is not None)
        identity = (entry['contract'], entry['operation'])
        require(identity not in identities)
        identities.add(identity)
        require(requested is None or entry['contract'] == requested)
        require(isinstance(entry['name'], str) and 1 <= len(entry['name']) <= 100)
        require(entry['credential'] == 'managed_by_capy' and entry['binding'] == 'team_configuration'
                and entry['availability'] == 'not_checked')
        require(isinstance(entry['notes'], list) and len(entry['notes']) <= 16
                and all(isinstance(note, str) for note in entry['notes']))
        require(isinstance(entry['examples'], list) and 1 <= len(entry['examples']) <= 4)
        for example in entry['examples']:
            require(isinstance(example, dict) and set(example) == {'request', 'result'}
                    and isinstance(example['request'], dict) and isinstance(example['result'], dict))
        schema(entry['request_schema'])
        schema(entry['result_schema'])
    return value
