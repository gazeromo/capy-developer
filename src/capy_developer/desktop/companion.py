from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time
import tempfile

from ..errors import DeveloperError
from ..git import run_git
from ..harnesses.codex import CodexAdapter
from ..link_protocol import ProtocolError, canonical, decode_json, digest, origin, parse_uri, validate_event, validate_request, validate_snapshot
from ..util import operation_lock
from .state import State, private_directory
from .transport import Transport


def require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise DeveloperError(code, detail)


class Companion:
    def __init__(self, core, *, transport=None, adapter=None, credential_store=None, clock=time.time):
        self.core = core
        self.state = State(core.config.data_root / 'desktop', credential_store=credential_store)
        self.transport = transport or Transport()
        self.adapter = adapter or CodexAdapter()
        self.clock = clock
        self.prepared_for_launch = False

    def _lock(self):
        return operation_lock(self.state.root / 'operations.lock')

    def pair_start(self, site_origin: str, site_id: str, label: str = 'This computer') -> dict:
        origin(site_origin)
        require(bool(re.fullmatch(r'site_[0-9a-f]{32}', site_id)), 'SITE_ID_INVALID', 'invalid site identity')
        require(isinstance(label, str) and 0 < len(label) <= 80 and all(ord(c) >= 32 for c in label), 'DEVICE_LABEL_INVALID', 'use a short plain text computer name')
        with self._lock():
            obsolete_credential = None
            with self.state.connect() as db:
                existing = db.execute('SELECT * FROM pairs WHERE site_id=?', (site_id,)).fetchone()
                if existing:
                    require(existing['origin'] == site_origin, 'PAIR_ORIGIN_CONFLICT', 'site identity is already bound to another exact origin')
                    if existing['state'] == 'APPROVED' and existing['expires_at'] > self.clock():
                        return self._public_pair(dict(existing))
                    if existing['state'] in ('REMOVED', 'REVOKED') or existing['expires_at'] <= self.clock():
                        obsolete_credential = existing['secret']
                        existing = None
                if existing is None:
                    installation = secrets.token_hex(16)
                    reference = self.state.credentials.store(installation, secrets.token_hex(32))
                    db.execute('DELETE FROM pairs WHERE site_id=?', (site_id,))
                    db.execute('INSERT INTO pairs VALUES (?,?,?,?,NULL,NULL,NULL,?,?,?)',
                               (site_id, site_origin, installation, reference, int(self.clock()) + 600, 'STARTING', label))
            if obsolete_credential:
                self.state.credentials.remove(obsolete_credential)
            pair = self.state.pair(site_id)
            # The secret is durably protected before any enrollment request.
            result = self.transport.post(site_origin, '/api/developer-link/pair/start', {
                'site_id': site_id, 'installation_id': pair['installation_id'],
                'secret_sha256': hashlib.sha256(pair['secret'].encode()).hexdigest(), 'label': pair['label'],
            })
            require(set(result) == {'site_id', 'pair_id', 'confirmation_code', 'expires_at', 'verification_path'}
                    and result['site_id'] == site_id
                    and isinstance(result['pair_id'], str) and bool(re.fullmatch(r'pair_[0-9a-f]{32}', result['pair_id']))
                    and type(result['expires_at']) is int and self.clock() < result['expires_at'] <= self.clock() + 600
                    and isinstance(result['confirmation_code'], str) and bool(re.fullmatch(r'[A-Z0-9-]{4,32}', result['confirmation_code']))
                    and result['verification_path'] == '/developer/connections/' + result['pair_id'],
                    'PAIR_RESPONSE_INVALID', 'site returned an invalid pending connection')
            with self.state.connect() as db:
                db.execute("UPDATE pairs SET pair_id=?,expires_at=?,state='PENDING' WHERE site_id=?", (result['pair_id'], result['expires_at'], site_id))
            return {**result, 'origin': site_origin, 'label': label, 'verification_url': site_origin + result['verification_path'], 'status': 'PENDING'}

    def pair_poll(self, site_id: str) -> dict:
        with self._lock():
            pair = self.state.pair(site_id)
            require(pair['expires_at'] > self.clock(), 'PAIR_EXPIRED', 'this connection has expired; reconnect this computer')
            result = self.transport.post(pair['origin'], '/api/developer-link/pair/poll', {'site_id': site_id, 'pair_id': pair['pair_id']}, pair['secret'])
            require(set(result) == {'status', 'site_id', 'device_id', 'principal_id', 'expires_at'}
                    and result['site_id'] == site_id and result['status'] in ('PENDING', 'APPROVED')
                    and type(result['expires_at']) is int and self.clock() < result['expires_at'] <= self.clock() + 366 * 86400,
                    'PAIR_RESPONSE_INVALID', 'site returned an invalid connection status')
            if result['status'] == 'APPROVED':
                require(isinstance(result['device_id'], str) and bool(re.fullmatch(r'dev_[0-9a-f]{32}', result['device_id']))
                        and isinstance(result['principal_id'], str) and 0 < len(result['principal_id']) <= 128,
                        'PAIR_RESPONSE_INVALID', 'approved connection has invalid identity')
            else:
                require(result['device_id'] is None and result['principal_id'] is None, 'PAIR_RESPONSE_INVALID', 'pending connection cannot carry authority')
            with self.state.connect() as db:
                db.execute('UPDATE pairs SET state=?,device_id=?,principal_id=?,expires_at=? WHERE site_id=?',
                           (result['status'], result['device_id'], result['principal_id'], result['expires_at'], site_id))
            return self._public_pair(self.state.pair(site_id))

    @staticmethod
    def _public_pair(pair: dict) -> dict:
        mechanism = pair.get('credential_storage') or ('macos-keychain' if pair['secret'].startswith('keychain:') else 'private-local-file')
        return {**{key: pair[key] for key in ('site_id', 'origin', 'device_id', 'expires_at', 'state', 'label')}, 'credential_storage': mechanism, 'credential_scope': 'developer-link only; not isolation from other code running as this OS user'}

    def connections(self) -> list[dict]:
        with self.state.connect() as db:
            return [self._public_pair(dict(row)) for row in db.execute('SELECT * FROM pairs ORDER BY site_id')]

    def remove_pair(self, site_id: str) -> dict:
        with self._lock():
            pair = self.state.pair_record(site_id)
            self.state.credentials.remove(pair['secret'])
            with self.state.connect() as db:
                db.execute("UPDATE pairs SET secret='',state='REMOVED',expires_at=0 WHERE site_id=?", (site_id,))
                db.execute("UPDATE handoffs SET sync_error='LINK_REMOVED' WHERE site_id=?", (site_id,))
        return {'site_id': site_id, 'removed': True, 'source_retained': True}

    def _approved(self, site_id: str) -> dict:
        pair = self.state.pair(site_id)
        require(pair['state'] == 'APPROVED' and pair['expires_at'] > self.clock(), 'SITE_NOT_PAIRED', 'the local site connection is not active')
        return pair

    def _pair_for_handoff(self, handoff: dict) -> dict:
        pair = self._approved(handoff['site_id'])
        request = json.loads(handoff['request'])
        require(handoff['pair_installation_id'] == pair['installation_id'] and request['device_id'] == pair['device_id'] and request['principal_id'] == pair['principal_id'],
                'LINK_CONNECTION_REPLACED', 'this handoff belongs to an earlier connection; its local source is retained')
        return pair

    def open_uri(self, uri: str) -> dict:
        self.prepared_for_launch = False
        try:
            return self._open_uri(uri)
        except Exception:
            if self.prepared_for_launch:
                # Persisted uncertainty must reach the site even when dispatch fails.
                # This executes outside the operation lock and preserves the failure.
                try:
                    self.sync_once(parse_uri(uri)['handoff_id'])
                except (DeveloperError, ProtocolError):
                    pass
            raise

    def prepare_uri(self, uri: str, *, local_request: dict | None = None) -> dict:
        """Claim and prepare linked work without dispatching a desktop launcher."""
        return self._open_uri(uri, launch=False, local_request=local_request)

    def _open_uri(self, uri: str, *, launch: bool = True, local_request: dict | None = None) -> dict:
        parsed = parse_uri(uri)
        with self._lock():
            pair = self._approved(parsed['site_id'])
            with self.state.connect() as db:
                prior = db.execute('SELECT * FROM handoffs WHERE handoff_id=?', (parsed['handoff_id'],)).fetchone()
            if prior is not None:
                self._pair_for_handoff(dict(prior))
            request = validate_request(self.transport.post(pair['origin'], '/api/developer-link/requests/' + parsed['handoff_id'] + '/claim', {
                'site_id': pair['site_id'], 'device_id': pair['device_id'], 'launch_generation': parsed['launch_generation'],
            }, pair['secret']))
            require(all(request[key] == parsed[key] for key in ('site_id', 'handoff_id', 'launch_generation'))
                    and request['device_id'] == pair['device_id'] and request['principal_id'] == pair['principal_id']
                    and request['created_at'] <= self.clock() and request['expires_at'] > self.clock(),
                    'HANDOFF_AUTHORITY_MISMATCH', 'claimed request does not match this local connection')
            with self.state.connect() as db:
                old = db.execute('SELECT * FROM handoffs WHERE handoff_id=?', (request['handoff_id'],)).fetchone()
                if old:
                    previous = json.loads(old['request'])
                    require(old['site_id'] == pair['site_id'] and previous['request_digest'] == request['request_digest'], 'HANDOFF_CONFLICT', 'handoff immutable binding differs')
                else:
                    db.execute('INSERT INTO handoffs(handoff_id,site_id,request,pair_installation_id) VALUES (?,?,?,?)', (request['handoff_id'], pair['site_id'], canonical(request).decode(), pair['installation_id']))
            handoff = self.state.handoff(request['handoff_id'])
            self._pair_for_handoff(handoff)
            if handoff['session_id'] is None:
                if local_request is not None and request['intent'] == 'NEW':
                    prepared = self.core.start_development({**local_request,
                        'idempotency_key': 'handoff:' + request['site_id'] + ':' + request['handoff_id']})
                else:
                    prepared = self._prepare(request, brief=local_request['request'] if local_request else None)
                self._usable(prepared)
                with self.state.connect() as db:
                    db.execute('UPDATE handoffs SET session_id=?,project_id=? WHERE handoff_id=?',
                               (prepared['session_id'], prepared['project']['project_id'], request['handoff_id']))
            handoff = self.state.handoff(request['handoff_id'])
            result = self.core.inspect_development(handoff['session_id'])
            self._usable(result)
            self._marker(handoff, result, write=True)
            self.prepared_for_launch = True
            if not launch:
                with self.state.connect() as db:
                    db.execute("UPDATE handoffs SET generation=?,launch_state='WAITING_FOR_HARNESS' WHERE handoff_id=?",
                               (parsed['launch_generation'], request['handoff_id']))
            elif parsed['launch_generation'] > handoff['generation']:
                # Intent commits before the nontransactional OS side effect. Crash means unknown.
                with self.state.connect() as db:
                    db.execute("UPDATE handoffs SET generation=?,launch_state='LAUNCH_OUTCOME_UNKNOWN' WHERE handoff_id=?", (parsed['launch_generation'], request['handoff_id']))
                self._enqueue(request['handoff_id'])
                self.adapter.launch(Path(result['workspace']['native_path']))
                with self.state.connect() as db:
                    db.execute("UPDATE handoffs SET launch_state='WAITING_FOR_HARNESS' WHERE handoff_id=?", (request['handoff_id'],))
            self._enqueue(request['handoff_id'])
        self.sync_once(request['handoff_id'])
        return self.inspect(request['handoff_id'])

    def _prepare(self, request: dict, *, brief: str | None = None) -> dict:
        key = 'handoff:' + request['site_id'] + ':' + request['handoff_id']
        brief = brief or 'Owner-opened app development. The owner will provide requirements in the interactive coding harness.'
        if request['intent'] == 'NEW':
            return self.core.start_development({'new': {'name': 'New app ' + request['handoff_id'][4:12], 'application_id': 'apps.a' + request['handoff_id'][4:]}, 'request': brief, 'idempotency_key': key})
        parent = self.state.handoff(request['parent_handoff_id'])
        parent_request = json.loads(parent['request'])
        require(all(parent_request[key] == request[key] for key in ('site_id', 'device_id', 'principal_id', 'authority_id', 'workspace_kind', 'workspace_id', 'membership_id')),
                'CONTINUATION_AUTHORITY_MISMATCH', 'continuation is outside its original local authority')
        require(parent['session_id'] is not None, 'CONTINUATION_NOT_PREPARED', 'parent session is not prepared on this computer')
        if request['release_candidate_id'] is None:
            result = self.core.inspect_development(parent['session_id'])
            require(result['status'] == 'READY', 'CONTINUATION_TERMINAL', 'a terminal session requires exact candidate continuation')
            return result
        candidate = self.core.inspect_release_candidate(request['release_candidate_id'])
        require(candidate['ok'] and candidate['session_id'] == parent['session_id'] and candidate['project_id'] == parent['project_id'],
                'CONTINUATION_CANDIDATE_MISMATCH', 'candidate does not belong to the linked parent')
        return self.core.continue_development({'release_candidate_id': request['release_candidate_id'], 'request': brief, 'idempotency_key': key})

    def _usable(self, result: dict) -> None:
        workspace = result.get('workspace') or {}
        require(result['status'] == 'READY' and workspace.get('exists') and workspace.get('branch_matches') and not result.get('discrepancy'),
                'HANDOFF_WORKSPACE_UNAVAILABLE', 'the prepared session workspace is not ready')
        require((result.get('toolchain') or {}).get('availability') == 'AVAILABLE', 'TOOLCHAIN_UNAVAILABLE', 'install the exact locked Developer toolchain before opening this session')
        path = Path(workspace['native_path'])
        require(path.is_absolute() and path.resolve().is_relative_to(self.core.config.worktrees_root.resolve()),
                'HANDOFF_WORKSPACE_INVALID', 'workspace is not in the managed worktree root')

    def _marker(self, handoff: dict, result: dict, *, write: bool = False) -> None:
        root = Path(result['workspace']['native_path'])
        directory = root / '.capy-local'
        expected = {'schema': 'capy.local-handoff/v0', 'site_id': handoff['site_id'], 'handoff_id': handoff['handoff_id'], 'project_id': handoff['project_id'], 'session_id': handoff['session_id']}
        path = directory / 'handoff.json'
        if write:
            private_directory(directory)
            # Native Git local exclude covers existing projects without changing tracked source.
            exclusion = Path(run_git(['rev-parse', '--git-path', 'info/exclude'], cwd=root))
            if not exclusion.is_absolute():
                exclusion = root / exclusion
            require(not exclusion.is_symlink(), 'HANDOFF_MARKER_INVALID', 'local exclusion file cannot be a symlink')
            exclusion.parent.mkdir(parents=True, exist_ok=True)
            before = exclusion.read_text() if exclusion.exists() else ''
            if '/.capy-local/' not in before.splitlines():
                exclusion.write_text(before + ('\n' if before and not before.endswith('\n') else '') + '/.capy-local/\n')
            require(not path.is_symlink(), 'HANDOFF_MARKER_INVALID', 'handoff marker cannot be a symlink')
            if path.exists():
                previous = decode_json(path.read_bytes(), max_bytes=2048)
                # Active continuation may move the marker to another handoff of this same session.
                require(previous == expected or (isinstance(previous, dict) and previous.get('session_id') == handoff['session_id'] and previous.get('project_id') == handoff['project_id'] and previous.get('site_id') == handoff['site_id']),
                        'HANDOFF_MARKER_CONFLICT', 'existing local marker belongs to another session')
            descriptor, temporary_name = tempfile.mkstemp(prefix='handoff-', suffix='.tmp', dir=directory)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(canonical(expected))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        require(not directory.is_symlink() and not path.is_symlink() and path.is_file() and path.stat().st_size <= 2048,
                'HANDOFF_MARKER_INVALID', 'prepared handoff marker is absent or unsafe')
        require(decode_json(path.read_bytes(), max_bytes=2048) == expected, 'HANDOFF_MARKER_MISMATCH', 'local marker does not match trusted handoff state')

    def attach(self, handoff_id: str) -> dict:
        with self._lock():
            handoff = self.state.handoff(handoff_id)
            self._pair_for_handoff(handoff)
            require(handoff['session_id'] is not None, 'HANDOFF_NOT_PREPARED', 'prepare this handoff before attachment')
            result = self.core.inspect_development(handoff['session_id'])
            self._usable(result)
            self._marker(handoff, result)
            with self.state.connect() as db:
                db.execute('UPDATE handoffs SET attached=1 WHERE handoff_id=?', (handoff_id,))
            self._enqueue(handoff_id)
        self.sync_once(handoff_id)
        return {'ok': True, 'handoff_id': handoff_id, 'attached': True, 'development': result}

    def inspect(self, handoff_id: str) -> dict:
        with self._lock():
            self._enqueue(handoff_id)
            handoff = self.state.handoff(handoff_id)
        return {'ok': True, 'handoff_id': handoff_id, 'site_id': handoff['site_id'], 'snapshot': json.loads(handoff['last_snapshot']),
                'launch_generation': handoff['generation'], 'launch_state': handoff['launch_state'], 'ack_sequence': handoff['ack_sequence'], 'sync_error': handoff['sync_error']}

    def _snapshot(self, handoff: dict) -> dict:
        value = dict(milestone='PREPARING', project_id=handoff['project_id'], session_id=handoff['session_id'], application_id=None,
                     source_commit=None, dirty=False, verification_id=None, verification_commit=None, verification_status=None, candidate_id=None, candidate_verification_id=None,
                     candidate_sha256=None, candidate_size=None, candidate_commit=None, source_fresh=False, terminal=None)
        if not handoff['session_id']:
            return validate_snapshot(value)
        result = self.core.inspect_development(handoff['session_id'])
        workspace = result.get('workspace') or {}
        value.update(source_commit=workspace.get('current_commit'), dirty=bool(workspace.get('dirty')),
                     milestone='HARNESS_ATTACHED' if handoff['attached'] else handoff['launch_state'])
        applications = result['project']['application_ids']
        value['application_id'] = applications[0] if len(applications) == 1 else None
        if handoff['attached'] and (value['dirty'] or value['source_commit'] != result['exact_base_commit']):
            value['milestone'] = 'CHANGES_IN_PROGRESS'
        verification = (result.get('verification') or {}).get('latest')
        if verification:
            value.update(verification_id=verification['verification_id'], verification_commit=verification['candidate_commit'], verification_status=verification['status'])
            fresh = (result['verification']['current_head_state'] != 'STALE' and workspace.get('exists') and workspace.get('branch_matches')
                     and not value['dirty'] and value['source_commit'] == verification['candidate_commit'])
            value['source_fresh'] = bool(fresh)
            if fresh:
                value['milestone'] = {'RUNNING': 'VERIFYING', 'PASSED': 'CHECKS_PASSED', 'FAILED': 'CHECKS_FAILED', 'INTERRUPTED': 'CHANGES_IN_PROGRESS'}[verification['status']]
        for event in reversed(result.get('events', [])):
            if event['type'] != 'RELEASE_CANDIDATE_READY':
                continue
            candidate = self.core.inspect_release_candidate(event['facts']['release_candidate_id'])
            if not candidate['ok']:
                continue
            require(candidate['session_id'] == handoff['session_id'] and candidate['project_id'] == handoff['project_id'],
                    'HANDOFF_CANDIDATE_MISMATCH', 'durable candidate association differs')
            value.update(candidate_id=candidate['release_candidate_id'], candidate_sha256=candidate['bundle']['sha256'],
                         candidate_size=candidate['bundle']['size_bytes'], candidate_commit=candidate['source']['commit'],
                         candidate_verification_id=candidate['verification_id'])
            value['source_fresh'] = bool(workspace.get('exists') and workspace.get('branch_matches') and not value['dirty'] and value['source_commit'] == candidate['source']['commit'])
            if value['source_fresh'] and value['verification_status'] == 'PASSED' and value['verification_id'] == candidate['verification_id']:
                value['milestone'] = 'CANDIDATE_PREPARED'
            elif value['milestone'] not in ('VERIFYING', 'CHECKS_FAILED', 'CHECKS_PASSED'):
                value['milestone'] = 'CHANGES_IN_PROGRESS'
            break
        terminal = result.get('terminal', {}).get('disposition')
        if terminal:
            value['terminal'] = terminal
            if value['candidate_id'] is None:
                value['milestone'] = 'SESSION_FINISHED'
        return validate_snapshot(value)

    def _enqueue(self, handoff_id: str) -> None:
        handoff = self.state.handoff(handoff_id)
        snapshot = self._snapshot(handoff)
        encoded = canonical(snapshot).decode()
        if encoded == handoff['last_snapshot']:
            return
        request = json.loads(handoff['request'])
        event = {'schema': 'capy.developer-link-event/v0', 'site_id': handoff['site_id'], 'handoff_id': handoff_id,
                 'device_id': request['device_id'], 'sequence': handoff['next_sequence'], 'snapshot': snapshot}
        event['digest'] = digest(event)
        validate_event(event)
        with self.state.connect() as db:
            db.execute('INSERT INTO outbox VALUES (?,?,?)', (handoff_id, event['sequence'], canonical(event).decode()))
            db.execute('UPDATE handoffs SET last_snapshot=?,next_sequence=next_sequence+1 WHERE handoff_id=?', (encoded, handoff_id))

    def sync_once(self, handoff_id: str | None = None) -> dict:
        results = []
        with self._lock():
            with self.state.connect() as db:
                ids = [r[0] for r in db.execute('SELECT handoff_id FROM handoffs ORDER BY handoff_id')] if handoff_id is None else [handoff_id]
            for identifier in ids:
                try:
                    self._enqueue(identifier)
                    handoff = self.state.handoff(identifier)
                    pair = self._pair_for_handoff(handoff)
                    with self.state.connect() as db:
                        rows = db.execute('SELECT event FROM outbox WHERE handoff_id=? ORDER BY sequence LIMIT 64', (identifier,)).fetchall()
                    events = []
                    for row in rows:
                        event = json.loads(row[0])
                        if len(canonical({'events': events + [event]})) > 262144:
                            break
                        events.append(event)
                    response = self.transport.post(pair['origin'], '/api/developer-link/requests/' + identifier + '/events', {'events': events}, pair['secret'])
                    maximum = events[-1]['sequence'] if events else handoff['ack_sequence']
                    require(set(response) == {'ack_sequence'} and type(response['ack_sequence']) is int and response['ack_sequence'] == maximum,
                            'LINK_ACK_INVALID', 'site acknowledgement differs from the contiguous submitted outbox')
                    with self.state.connect() as db:
                        db.execute('DELETE FROM outbox WHERE handoff_id=? AND sequence<=?', (identifier, maximum))
                        db.execute('UPDATE handoffs SET ack_sequence=?,sync_error=NULL WHERE handoff_id=?', (maximum, identifier))
                    results.append({'handoff_id': identifier, 'ok': True, 'ack_sequence': maximum})
                except DeveloperError as exc:
                    with self.state.connect() as db:
                        db.execute('UPDATE handoffs SET sync_error=? WHERE handoff_id=?', (exc.code, identifier))
                    results.append({'handoff_id': identifier, 'ok': False, 'code': exc.code})
                except ProtocolError:
                    with self.state.connect() as db:
                        db.execute("UPDATE handoffs SET sync_error='LINK_PROTOCOL_INVALID' WHERE handoff_id=?", (identifier,))
                    results.append({'handoff_id': identifier, 'ok': False, 'code': 'LINK_PROTOCOL_INVALID'})
        return {'ok': all(r['ok'] for r in results), 'results': results}
