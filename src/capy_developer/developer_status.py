"""Safe, read-only local status shared by CLI and MCP; no credential access."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import time

from . import __version__
from .errors import DeveloperError
from .installation import validate_catalog
from .toolchain import current_lock


def status(config, arguments=None):
    arguments = {} if arguments is None else arguments
    if (not isinstance(arguments, dict) or set(arguments) - {'session_id'}
            or ('session_id' in arguments and (not isinstance(arguments['session_id'], str) or not arguments['session_id']))):
        raise DeveloperError('STATUS_INPUT_INVALID', 'provide only an optional exact session_id')
    from .mcp import TOOLS
    package = Path(__file__).parent
    digest = hashlib.sha256()
    for path in sorted(package.rglob('*.py')):
        digest.update(path.relative_to(package).as_posix().encode() + b'\0')
        digest.update(path.read_bytes() + b'\0')
    result = {'schema': 'capy.developer-status/v0', 'ok': True,
              'build': {'version': __version__, 'python_source_sha256': digest.hexdigest()},
              'current_authoring_toolchain': {k: v for k, v in current_lock(None).as_dict('BUNDLED').items() if k not in {'lock_source_path', 'detail'}},
              'authoring_compatibility': 'The current bundled release supports read-only semantic connections with interaction V1. Existing projects retain their declared capy.lock until explicitly updated as an application source change.',
              'toolset_sha256': hashlib.sha256(json.dumps(TOOLS, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
              'installation': {'status': 'UNAVAILABLE'}, 'sites': [], 'clients': [],
              'session': {'status': 'NOT_REQUESTED'}, 'remote_status': 'NOT_CHECKED',
              'ready': False, 'mutated': False,
              'next_action': 'Use the configured Capy connection; connect this client if setup is incomplete.'}
    if not config.database.exists():
        return result
    validate_catalog(config)
    result['installation']['status'] = 'CATALOG_AVAILABLE'
    if 'session_id' in arguments:
        with sqlite3.connect(config.database.as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            row = db.execute('SELECT session_id,project_id,status,terminal_disposition,exact_base_commit,final_commit FROM sessions WHERE session_id=?', (arguments['session_id'],)).fetchone()
        result['session'] = dict(row) if row else {'status': 'NOT_FOUND'}
        result['session']['next_action'] = ('Call capy_development_inspect with this session_id before editing; these are stored facts, not a fresh Git check.' if row else 'Provide an exact session_id from the configured installation; do not create a replacement installation.')
    try:
        from .desktop.state import State
        state = State(config.data_root / 'desktop', read_only=True)
        with state.connect() as db:
            pairs = db.execute('SELECT site_id,origin,installation_id,state,expires_at FROM pairs ORDER BY site_id').fetchall()
            clients = db.execute('SELECT site,adapter,installation,client,version,transport FROM harness_clients ORDER BY site,adapter').fetchall()
            handoffs = (db.execute('SELECT handoff_id FROM handoffs WHERE session_id=? ORDER BY handoff_id', (arguments['session_id'],)).fetchall() if 'session_id' in arguments else [])
    except (DeveloperError, sqlite3.Error):
        result['installation']['connection_status'] = 'UNAVAILABLE'
        return result
    result['sites'] = [dict(row, local_state=('EXPIRED' if row['expires_at'] <= time.time() else row['state'])) for row in pairs]
    result['clients'] = [{**dict(row), 'adapter': row['adapter'].split(':', 1)[0], 'check_status': 'NOT_CHECKED'} for row in clients]
    identities = {row['installation_id'] for row in pairs if row['state'] == 'APPROVED' and row['expires_at'] > time.time()}
    if len(identities) == 1:
        result['installation'].update(status='CONFIGURED', installation_id=next(iter(identities)))
        result['next_action'] = 'Use the listed exact client_id with capy_client_status for current site status; continue existing linked work with its handoff_id.'
    elif len(identities) > 1:
        result['ok'] = False
        result['installation']['status'] = 'CONFIGURED_CONNECTION_AMBIGUOUS'
        result['next_action'] = 'Multiple active site connections are recorded. Select an existing site and its exact client_id before starting linked work; do not guess or allocate another installation.'
    else:
        result['installation']['connection_status'] = 'NO_ACTIVE_LOCAL_APPROVAL'
    if 'session_id' in arguments:
        result['session']['handoff_ids'] = [row['handoff_id'] for row in handoffs]
    return result
