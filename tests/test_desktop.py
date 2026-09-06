from __future__ import annotations

import copy
import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest import mock

from capy_developer.config import Config
from capy_developer.desktop import Companion
from capy_developer.desktop.credentials import FileCredentials, KeychainCredentials
from capy_developer.desktop.setup import Setup, BEGIN, DIAGNOSTIC_NAME, atomic
from capy_developer.desktop.transport import Transport, NoRedirect
from capy_developer.errors import DeveloperError
from capy_developer.git import run_git
from capy_developer.link_protocol import ProtocolError, canonical, digest, make_uri, validate_event

SITE = 'site_' + '1' * 32
HANDOFF = 'hof_' + '2' * 32
DEVICE = 'dev_' + '3' * 32
PROJECT = 'prj_' + '4' * 32
SESSION = 'ses_' + '5' * 32
PAIR = 'pair_' + '6' * 32
CANDIDATE = 'rc_' + '7' * 32
NOW = 1800000000


def request(handoff=HANDOFF, generation=1, **changes):
    value = dict(schema='capy.developer-link-request/v0', site_id=SITE, handoff_id=handoff,
                 device_id=DEVICE, principal_id='principal.fixture', authority_id='authority.fixture',
                 workspace_kind='personal', workspace_id='workspace.fixture', membership_id='membership.fixture',
                 intent='NEW', parent_handoff_id=None, release_candidate_id=None,
                 created_at=NOW - 10, expires_at=NOW + 300, launch_generation=generation)
    value.update(changes)
    value['request_digest'] = digest({k: v for k, v in value.items() if k not in ('request_digest', 'launch_generation')})
    return value


class FakeCore:
    def __init__(self, root):
        self.config = Config(root / 'state', root / 'cache', root / 'repositories', root / 'worktrees', root / 'temp')
        self.config.ensure()
        workspace = self.config.worktrees_root / PROJECT / SESSION
        workspace.mkdir(parents=True)
        run_git(['init', '--initial-branch=main'], cwd=workspace)
        run_git(['config', 'user.name', 'Fixture'], cwd=workspace)
        run_git(['config', 'user.email', 'fixture@localhost'], cwd=workspace)
        (workspace / 'CAPY.md').write_text('Fixture orientation\n')
        run_git(['add', 'CAPY.md'], cwd=workspace)
        run_git(['commit', '-m', 'Fixture'], cwd=workspace)
        commit = run_git(['rev-parse', 'HEAD'], cwd=workspace)
        self.value = dict(ok=True, status='READY', session_id=SESSION, project={'project_id': PROJECT, 'application_ids': ['apps.fixture']},
                          exact_base_commit=commit, workspace={'native_path': str(workspace), 'exists': True, 'branch_matches': True,
                          'current_commit': commit, 'dirty': False}, discrepancy=None, toolchain={'availability': 'AVAILABLE'},
                          terminal={'disposition': None}, verification={'latest': None, 'current_head_state': 'NO_VERIFICATION'}, events=[])
        self.starts = []
        self.continues = []
        self.candidates = {}

    def start_development(self, payload):
        if payload not in self.starts:
            self.starts.append(payload)
        return copy.deepcopy(self.value)

    def inspect_development(self, identifier):
        if identifier != self.value['session_id']:
            raise AssertionError('unexpected session')
        return copy.deepcopy(self.value)

    def inspect_release_candidate(self, identifier):
        return copy.deepcopy(self.candidates[identifier])

    def continue_development(self, payload):
        self.continues.append(payload)
        return copy.deepcopy(self.value)


class FakeTransport:
    def __init__(self):
        self.request = request()
        self.calls = []
        self.events = {}
        self.offline = False
        self.ack_lost = False

    def post(self, site_origin, path, body, secret=None):
        self.calls.append((site_origin, path, copy.deepcopy(body), secret))
        if self.offline:
            raise DeveloperError('LINK_OFFLINE', 'offline')
        if path.endswith('/pair/start'):
            return {'site_id': SITE, 'pair_id': PAIR, 'confirmation_code': '1234-ABCD', 'expires_at': NOW + 600,
                    'verification_path': '/developer/connections/' + PAIR}
        if path.endswith('/pair/poll'):
            return {'status': 'APPROVED', 'site_id': SITE, 'device_id': DEVICE, 'principal_id': 'principal.fixture', 'expires_at': NOW + 86400}
        if path.endswith('/claim'):
            value = copy.deepcopy(self.request)
            value['launch_generation'] = body['launch_generation']
            return value
        handoff = path.split('/')[-2]
        history = self.events.setdefault(handoff, {})
        for event in body['events']:
            validate_event(event)
            seq = event['sequence']
            if seq in history:
                assert history[seq] == event
            else:
                assert seq == len(history) + 1
                history[seq] = copy.deepcopy(event)
        if self.ack_lost:
            self.ack_lost = False
            raise DeveloperError('LINK_OFFLINE', 'acknowledgement lost')
        return {'ack_sequence': len(history)}


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.crash = False

    def launch(self, path):
        self.calls.append(path)
        if self.crash:
            raise RuntimeError('crash at dispatch')
        return {'dispatched': True, 'attached': False}


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.core = FakeCore(self.root)
        self.transport = FakeTransport()
        self.adapter = FakeAdapter()
        self.companion = Companion(self.core, transport=self.transport, adapter=self.adapter, clock=lambda: NOW, credential_store=FileCredentials(test_owned=True))
        self.companion.pair_start('https://capy.example', SITE)
        self.companion.pair_poll(SITE)

    def tearDown(self):
        self.temporary.cleanup()

    def open(self, generation=1):
        return self.companion.open_uri(make_uri(SITE, HANDOFF, generation))

    def test_open_replay_attach_and_marker_privacy(self):
        first = self.open()
        self.assertEqual(first['snapshot']['milestone'], 'WAITING_FOR_HARNESS')
        self.open()
        self.assertEqual(len(self.core.starts), 1)
        self.assertEqual(len(self.adapter.calls), 1)
        attached = self.companion.attach(HANDOFF)
        self.assertTrue(attached['attached'])
        self.companion.attach(HANDOFF)
        self.assertEqual(self.companion.inspect(HANDOFF)['snapshot']['milestone'], 'HARNESS_ATTACHED')
        marker = Path(self.core.value['workspace']['native_path']) / '.capy-local/handoff.json'
        secret = self.companion.state.pair(SITE)['secret']
        public = canonical(first) + marker.read_bytes() + canonical(attached) + canonical(list(self.transport.events[HANDOFF].values()))
        self.assertNotIn(secret.encode(), public)
        self.assertNotIn(str(self.root).encode(), canonical(first))
        self.assertEqual(run_git(['status', '--porcelain'], cwd=marker.parent.parent), '')
        marker.write_text('{}')
        with self.assertRaisesRegex(DeveloperError, 'marker'):
            self.companion.attach(HANDOFF)

    def test_unpaired_and_uri_injection_cannot_reach_network_or_core(self):
        before = len(self.transport.calls)
        for uri in [make_uri('site_' + 'a' * 32, HANDOFF, 1), make_uri(SITE, HANDOFF, 1) + '&command=sh',
                    make_uri(SITE, HANDOFF, 1) + '#fragment', 'capy-dev://handoff/../../etc/passwd', 'capy-dev://handoff/%252e']:
            with self.assertRaises((DeveloperError, ProtocolError)):
                self.companion.open_uri(uri)
        self.assertEqual(len(self.transport.calls), before)
        self.assertFalse(self.core.starts)

    def test_claim_identity_mismatch_prevents_preparation(self):
        self.transport.request = request(principal_id='principal.other')
        with self.assertRaises(DeveloperError):
            self.open()
        self.assertFalse(self.core.starts)

    def test_launch_crash_requires_explicit_new_generation(self):
        self.adapter.crash = True
        with self.assertRaises(RuntimeError):
            self.open()
        self.assertEqual(list(self.transport.events[HANDOFF].values())[-1]['snapshot']['milestone'], 'LAUNCH_OUTCOME_UNKNOWN')
        restarted = Companion(self.core, transport=self.transport, adapter=self.adapter, clock=lambda: NOW, credential_store=FileCredentials(test_owned=True))
        self.assertEqual(restarted.inspect(HANDOFF)['snapshot']['milestone'], 'LAUNCH_OUTCOME_UNKNOWN')
        restarted.open_uri(make_uri(SITE, HANDOFF, 1))
        self.assertEqual(len(self.adapter.calls), 1)
        self.adapter.crash = False
        self.open(2)
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertEqual(len(self.core.starts), 1)

    def test_removed_and_expired_pairings_get_fresh_credentials_and_isolate_old_links(self):
        self.open()
        first = self.companion.state.pair(SITE)
        self.companion.remove_pair(SITE)
        self.companion.pair_start('https://capy.example', SITE)
        self.companion.pair_poll(SITE)
        second = self.companion.state.pair(SITE)
        self.assertNotEqual(first['secret'], second['secret'])
        self.assertNotEqual(first['installation_id'], second['installation_id'])
        before = len(self.transport.calls)
        with self.assertRaises(DeveloperError) as caught:
            self.companion.attach(HANDOFF)
        self.assertEqual(caught.exception.code, 'LINK_CONNECTION_REPLACED')
        with self.assertRaises(DeveloperError):
            self.open()
        self.assertFalse(self.companion.sync_once()['ok'])
        self.assertEqual(len(self.transport.calls), before)
        with self.companion.state.connect() as db:
            db.execute('UPDATE pairs SET expires_at=? WHERE site_id=?', (NOW - 1, SITE))
        self.companion.pair_start('https://capy.example', SITE)
        third = self.companion.state.pair(SITE)
        self.assertNotEqual(second['secret'], third['secret'])
        self.assertNotEqual(second['installation_id'], third['installation_id'])
        self.assertEqual(len(self.core.starts), 1)

    def test_protocol_failure_retains_outbox_with_exact_safe_error(self):
        self.open()
        self.core.value['workspace']['dirty'] = True
        with mock.patch.object(self.transport, 'post', side_effect=ProtocolError('synthetic-secret-canary')):
            result = self.companion.sync_once()
        self.assertEqual(result['results'][0]['code'], 'LINK_PROTOCOL_INVALID')
        self.assertNotIn('synthetic-secret-canary', json.dumps(result))
        with self.companion.state.connect() as db:
            self.assertGreater(db.execute('SELECT count(*) FROM outbox').fetchone()[0], 0)
        self.assertTrue(self.companion.sync_once()['ok'])

    def test_offline_reconciliation_replays_lost_ack_without_rerun(self):
        self.open()
        self.companion.attach(HANDOFF)
        self.transport.offline = True
        self.core.value['workspace']['dirty'] = True
        self.assertFalse(self.companion.sync_once()['ok'])
        self.assertEqual(self.companion.inspect(HANDOFF)['snapshot']['milestone'], 'CHANGES_IN_PROGRESS')
        self.transport.offline = False
        self.transport.ack_lost = True
        self.assertFalse(self.companion.sync_once()['ok'])
        event_count = len(self.transport.events[HANDOFF])
        self.assertTrue(self.companion.sync_once()['ok'])
        self.companion.sync_once()
        self.assertEqual(len(self.transport.events[HANDOFF]), event_count)
        self.assertEqual(len(self.core.starts), 1)

    def test_candidate_exact_source_and_failed_current_check(self):
        self.open()
        self.companion.attach(HANDOFF)
        commit = self.core.value['workspace']['current_commit']
        self.core.value['verification'] = {'latest': {'verification_id': 'ver_pass', 'status': 'PASSED', 'candidate_commit': commit}, 'current_head_state': 'VERIFIED'}
        self.core.value['events'] = [{'type': 'RELEASE_CANDIDATE_READY', 'facts': {'release_candidate_id': CANDIDATE}}]
        self.core.candidates[CANDIDATE] = dict(ok=True, release_candidate_id=CANDIDATE, verification_id='ver_pass', project_id=PROJECT, session_id=SESSION,
                                               source={'commit': commit}, bundle={'sha256': 'a' * 64, 'size_bytes': 123})
        first = self.companion.inspect(HANDOFF)['snapshot']
        self.assertEqual(first['milestone'], 'CANDIDATE_PREPARED')
        self.assertTrue(first['source_fresh'])
        newer = 'b' * 40
        self.core.value['workspace']['current_commit'] = newer
        self.core.value['verification'] = {'latest': {'verification_id': 'ver_failed', 'status': 'FAILED', 'candidate_commit': newer}, 'current_head_state': 'FAILED'}
        current = self.companion.inspect(HANDOFF)['snapshot']
        self.assertEqual(current['milestone'], 'CHECKS_FAILED')
        self.assertEqual(current['verification_status'], 'FAILED')
        self.assertEqual(current['candidate_verification_id'], 'ver_pass')
        self.assertFalse(current['source_fresh'])
        self.assertEqual(current['candidate_id'], CANDIDATE)

    def test_active_continuation_reuses_dirty_session(self):
        self.open()
        child = 'hof_' + '8' * 32
        self.transport.request = request(handoff=child, intent='CONTINUE', parent_handoff_id=HANDOFF)
        self.core.value['workspace']['dirty'] = True
        result = self.companion.open_uri(make_uri(SITE, child, 1))
        self.assertEqual(result['snapshot']['session_id'], SESSION)
        self.assertTrue(result['snapshot']['dirty'])
        self.assertEqual(len(self.core.starts), 1)
        self.assertFalse(self.core.continues)
        self.assertEqual(self.companion.attach(child)['development']['session_id'], SESSION)

    def test_unavailable_toolchain_blocks_launch_without_new_intent(self):
        self.core.value['toolchain']['availability'] = 'MISSING'
        with self.assertRaises(DeveloperError):
            self.open()
        self.assertFalse(self.adapter.calls)
        self.core.value['toolchain']['availability'] = 'AVAILABLE'
        self.open()
        self.assertEqual(len(self.core.starts), 1)

    def test_real_core_new_project_uses_same_companion_contract(self):
        from capy_developer.core import DeveloperCore
        config = Config(self.root / 'real/state', self.root / 'real/cache', self.root / 'real/repositories', self.root / 'real/worktrees', self.root / 'real/temp')
        core = DeveloperCore(config)
        link = Companion(core, transport=FakeTransport(), adapter=FakeAdapter(), clock=lambda: NOW, credential_store=FileCredentials(test_owned=True))
        link.pair_start('https://capy.example', SITE)
        link.pair_poll(SITE)
        opened = link.open_uri(make_uri(SITE, HANDOFF, 1))
        attached = link.attach(HANDOFF)
        self.assertEqual(opened['snapshot']['session_id'], attached['development']['session_id'])
        self.assertFalse(attached['development']['workspace']['dirty'])

    def test_origin_rebind_and_secret_permissions(self):
        with self.assertRaises(DeveloperError):
            self.companion.pair_start('https://different.example', SITE)
        if os.name != 'nt':
            self.assertEqual(self.companion.state.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.companion.state.root.stat().st_mode & 0o777, 0o700)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))
        transport = Transport()
        with mock.patch.object(transport.opener, 'open', side_effect=__import__('urllib.error', fromlist=['HTTPError']).HTTPError('https://capy.example', 302, '', {}, None)):
            with self.assertRaisesRegex(DeveloperError, 'rejected'):
                transport.post('https://capy.example', '/api/developer-link/pair/poll', {}, 'synthetic')


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.core = FakeCore(self.root)
        self.config = self.root / 'codex/config.toml'
        self.config.parent.mkdir()
        self.original = '# personal comment\nmodel = "owner-choice"\n[mcp_servers.other]\ncommand = "unrelated"\n'
        self.config.write_bytes(self.original.encode())
        self.setup = Setup(self.core, config_path=self.config, applications=self.root / 'Applications')

    def tearDown(self):
        self.temporary.cleanup()

    def test_additive_install_idempotent_and_remove_preserves_later_changes(self):
        self.setup.install(native=False)
        once = self.config.read_bytes()
        self.setup.install(native=False)
        self.assertEqual(self.config.read_bytes(), once)
        self.assertTrue(once.startswith(self.original.encode()))
        extra = '\n[features]\nowner_feature = true\n'
        self.config.write_bytes(once + extra.encode())
        self.setup.remove()
        self.assertEqual(self.config.read_bytes(), (self.original + extra).encode())

    def test_setup_preserves_existing_crlf_bytes(self):
        original = self.original.replace('\n', '\r\n').encode()
        self.config.write_bytes(original)
        self.setup.install(native=False)
        self.assertTrue(self.config.read_bytes().startswith(original))
        self.setup.remove()
        self.assertEqual(self.config.read_bytes(), original)

    def test_unowned_and_modified_entry_are_never_overwritten(self):
        self.config.write_bytes((self.original + '[mcp_servers.capy_developer]\ncommand = "user-custom"\n').encode())
        before = self.config.read_bytes()
        with self.assertRaises(DeveloperError):
            self.setup.install(native=False)
        self.assertEqual(self.config.read_bytes(), before)
        self.config.write_bytes(self.original.encode())
        self.setup.install(native=False)
        self.config.write_bytes(self.config.read_bytes().replace(b'"mcp"', b'"changed"'))
        before = self.config.read_bytes()
        with self.assertRaises(DeveloperError):
            self.setup.remove()
        self.assertEqual(self.config.read_bytes(), before)

    def test_config_crash_recovery_uses_durable_intent(self):
        from capy_developer.desktop import setup as module
        original_atomic = module.atomic
        def crash_after_config(path, payload):
            original_atomic(path, payload)
            if path == self.config:
                raise RuntimeError('crash after config replace')
        with mock.patch.object(module, 'atomic', side_effect=crash_after_config):
            with self.assertRaises(RuntimeError):
                self.setup.install(native=False)
        self.assertEqual(self.setup._read()['status'], 'PREPARING')
        self.setup.install(native=False)
        self.assertEqual(self.config.read_bytes().count(BEGIN.encode()), 1)
        self.setup.remove()
        self.assertEqual(self.config.read_bytes(), self.original.encode())

    def test_native_wrapper_handles_url_events_as_one_argv_without_shell(self):
        swift = self.setup._swift()
        self.assertIn('open urls: [URL]', swift)
        self.assertIn('"--uri", url.absoluteString', swift)
        self.assertNotIn('/bin/sh', swift)
        self.assertNotIn('codex exec', swift)
        self.assertNotIn('approval_policy', self.setup._block().decode())

    def test_native_diagnostic_only_projects_closed_nonsecret_fields(self):
        path = self.setup.root / DIAGNOSTIC_NAME
        self.assertIsNone(self.setup.inspect()['native_handler_diagnostic'])
        safe = {'phase': 'CHILD_EXITED', 'timestamp': NOW, 'pid': 123, 'exit_status': 1}
        atomic(path, canonical(safe))
        self.assertEqual(self.setup.inspect()['native_handler_diagnostic'], safe)
        for mutation in ({**safe, 'url': 'synthetic-secret-canary'}, {**safe, 'phase': ['CHILD_EXITED']},
                         {**safe, 'phase': {'secret': 'synthetic-secret-canary'}}, {**safe, 'timestamp': True},
                         {**safe, 'pid': 0}, {**safe, 'exit_status': 'synthetic-secret-canary'},
                         {**safe, 'phase': 'URL_RECEIVED'}):
            atomic(path, canonical(mutation))
            result = self.setup.inspect()['native_handler_diagnostic']
            self.assertEqual(result, {'status': 'INVALID'})
            self.assertNotIn('synthetic-secret-canary', json.dumps(result))
        atomic(path, b'x' * 1025)
        self.assertEqual(self.setup.inspect()['native_handler_diagnostic'], {'status': 'INVALID'})

    @unittest.skipIf(os.name == 'nt', 'POSIX ownership qualification')
    def test_native_diagnostic_refuses_symlinks_and_nonprivate_files(self):
        path = self.setup.root / DIAGNOSTIC_NAME
        safe = {'phase': 'APP_STARTED', 'timestamp': NOW, 'pid': 123}
        atomic(path, canonical(safe))
        path.chmod(0o644)
        self.assertEqual(self.setup.inspect()['native_handler_diagnostic'], {'status': 'INVALID'})
        path.unlink()
        target = self.root / 'unrelated-private-file'
        target.write_bytes(b'synthetic-secret-canary')
        path.symlink_to(target)
        self.assertEqual(self.setup.inspect()['native_handler_diagnostic'], {'status': 'UNREADABLE'})
        self.assertEqual(target.read_bytes(), b'synthetic-secret-canary')

    def test_native_diagnostic_generation_has_fixed_phases_and_atomic_private_writer(self):
        source = self.setup._swift()
        self.assertIn('recordHandlerEvent(.appStarted)', source)
        self.assertIn('recordHandlerEvent(.urlReceived)', source)
        self.assertIn('recordHandlerEvent(.childStarted)', source)
        self.assertIn('recordHandlerEvent(.childExited, exitStatus: task.terminationStatus)', source)
        receipt_writer = source.split('func recordHandlerEvent', 1)[1].split('final class Delegate', 1)[0]
        self.assertIn('renameat(directory, temporary, directory, destination)', receipt_writer)
        self.assertIn('O_NOFOLLOW', receipt_writer)
        self.assertIn('0o600', receipt_writer)
        self.assertIn('0o700', receipt_writer)
        self.assertNotIn('url.absoluteString', receipt_writer)
        self.assertNotIn('process.arguments', receipt_writer)
        self.assertNotIn('ProcessInfo.processInfo.environment', receipt_writer)

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swiftc'), 'isolated macOS diagnostic writer qualification')
    def test_native_diagnostic_helper_writes_atomic_private_receipt_without_launching_app(self):
        # Compile and execute only the pure receipt helper. The delegate,
        # NSApplication.run, child launch and external URI dispatch are absent.
        source = self.setup._swift().split('final class Delegate:', 1)[0]
        source += '\nrecordHandlerEvent(.appStarted)\nrecordHandlerEvent(.childExited, exitStatus: 7)\n'
        path = self.root / 'diagnostic-writer.swift'
        path.write_bytes(source.encode())
        binary = self.root / 'diagnostic-writer'
        compiled = subprocess.run(['swiftc', str(path), '-o', str(binary)], capture_output=True, text=True, timeout=120)
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        subprocess.run([str(binary)], check=True, capture_output=True, timeout=20)
        receipt = self.setup.root / DIAGNOSTIC_NAME
        actual = self.setup.inspect()['native_handler_diagnostic']
        self.assertEqual(actual['phase'], 'CHILD_EXITED')
        self.assertEqual(actual['exit_status'], 7)
        self.assertEqual(set(actual), {'phase', 'timestamp', 'pid', 'exit_status'})
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.setup.root.glob('.native-handler-event-*.tmp')))
        # A replaced diagnostic path cannot redirect this writer to another file.
        receipt.unlink()
        protected = self.root / 'protected-fixture'
        protected.write_bytes(b'synthetic-secret-canary')
        receipt.symlink_to(protected)
        subprocess.run([str(binary)], check=True, capture_output=True, timeout=20)
        self.assertEqual(protected.read_bytes(), b'synthetic-secret-canary')
        self.assertTrue(receipt.is_symlink())

    def test_owned_mcp_command_reaches_real_initialize(self):
        import tomllib
        entry = tomllib.loads(self.setup._block().decode())['mcp_servers']['capy_developer']
        environment = dict(os.environ, **entry['env'])
        result = subprocess.run([entry['command'], *entry['args']], input=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}) + '\n',
                                text=True, capture_output=True, env=environment, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('serverInfo', json.loads(result.stdout)['result'])
        self.assertEqual(entry['command'], str(Path(sys.executable).absolute()))

    def test_last_site_removal_preserves_other_connections_and_config_conflicts(self):
        link = Companion(self.core, transport=FakeTransport(), credential_store=FileCredentials(test_owned=True), clock=lambda: NOW)
        link.pair_start('https://capy.example', SITE)
        link.pair_poll(SITE)
        self.setup.install(native=False)
        other = 'site_' + '9' * 32
        with link.state.connect() as db:
            row = link.state.pair_record(SITE)
            db.execute('INSERT INTO pairs VALUES (?,?,?,?,?,?,?,?,?,?)', (other, 'https://other.example', '0' * 32, 'a' * 64, None, None, None, NOW + 500, 'PENDING', 'Fixture'))
        self.assertEqual(self.setup.remove_site(link, SITE)['integration'], 'RETAINED_FOR_OTHER_CONNECTIONS')
        self.assertTrue(self.setup.receipt.exists())
        before = self.config.read_bytes()
        self.config.write_bytes(before.replace(b'"mcp"', b'"user-modified"'))
        with self.assertRaises(DeveloperError):
            self.setup.remove_site(link, other)
        self.assertEqual(link.state.pair(other)['state'], 'PENDING')
        self.config.write_bytes(before)
        self.assertEqual(self.setup.remove_site(link, other)['integration'], 'REMOVED')
        self.assertFalse(self.setup.receipt.exists())
        self.assertEqual(self.config.read_bytes(), self.original.encode())

    def test_invalid_and_unpaired_callbacks_leave_nonexistent_roots_absent(self):
        from capy_developer.desktop_cli import run
        absent = self.root / 'must-remain-absent'
        environment = {'CAPY_DEV_DATA_ROOT': str(absent / 'state'), 'CAPY_DEV_CACHE_ROOT': str(absent / 'cache'),
                       'CAPY_DEV_REPOSITORIES_ROOT': str(absent / 'repos'), 'CAPY_DEV_WORKTREES_ROOT': str(absent / 'worktrees'),
                       'CAPY_DEV_VERIFICATION_TEMP_ROOT': str(absent / 'temp')}
        for uri in ('capy-dev://handoff/invalid', make_uri(SITE, HANDOFF, 1)):
            with mock.patch.dict(os.environ, environment), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run(['handoff', 'open', '--uri', uri]), 1)
            self.assertFalse(absent.exists())

    def test_keychain_references_never_enter_database_as_secrets(self):
        class TestOwnedVault:
            mechanism = 'macos-keychain'
            def __init__(self):
                self.items = {}
            def store(self, account, secret):
                reference = 'keychain:' + account
                self.items[reference] = secret
                return reference
            def read(self, reference):
                return self.items[reference]
            def remove(self, reference):
                self.items.pop(reference, None)
        vault = TestOwnedVault()
        link = Companion(self.core, transport=FakeTransport(), credential_store=vault, clock=lambda: NOW)
        link.pair_start('https://capy.example', SITE)
        reference = link.state.pair_record(SITE)['secret']
        secret = link.state.pair(SITE)['secret']
        self.assertTrue(reference.startswith('keychain:'))
        self.assertNotIn(secret.encode(), link.state.path.read_bytes())
        self.assertEqual(link.connections()[0]['credential_storage'], 'macos-keychain')
        link.remove_pair(SITE)
        self.assertFalse(vault.items)

    @unittest.skipUnless(sys.platform == 'darwin', 'public macOS framework binding check')
    def test_keychain_public_framework_queries_and_fail_closed_status(self):
        # Exercise real public CF allocation/type/lifetime signatures, while mock
        # SecItem calls guarantee no writes to the user's actual Keychain.
        import ctypes
        store = KeychainCredentials()
        account = 'a' * 32
        canary = 'b' * 64
        with mock.patch.object(store.security, 'SecItemAdd', return_value=0) as adding:
            reference = store.store(account, canary)
        self.assertEqual(reference, 'keychain:' + account)
        self.assertEqual(adding.call_count, 1)
        def copy_item(query, output):
            buffer = ctypes.create_string_buffer(canary.encode())
            data = store.cf.CFDataCreate(None, buffer, 64)
            ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = data
            return 0
        with mock.patch.object(store.security, 'SecItemCopyMatching', side_effect=copy_item):
            self.assertEqual(store.read(reference), canary)
        with mock.patch.object(store.security, 'SecItemDelete', return_value=0):
            store.remove(reference)
        with mock.patch.object(store.security, 'SecItemAdd', return_value=-25293):
            with self.assertRaises(DeveloperError) as result:
                store.store(account, canary)
        self.assertEqual(result.exception.code, 'CREDENTIAL_STORE_REJECTED')
        self.assertNotIn(canary, str(result.exception))


if __name__ == '__main__':
    unittest.main()
