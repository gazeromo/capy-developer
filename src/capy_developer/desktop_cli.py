"""Desktop commands are deliberately separate from the existing lifecycle CLI."""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import time

from .core import DeveloperCore
from .config import Config
from .desktop import Companion
from .desktop.setup import Setup
from .desktop.state import preflight_open
from .errors import DeveloperError
from .link_protocol import ProtocolError, parse_uri
from .util import exclusive_lock


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DeveloperError('CLI_ARGUMENT_INVALID', message)


def parser():
    root = Parser(prog='capy-dev')
    commands = root.add_subparsers(dest='command', required=True)
    setup = commands.add_parser('setup')
    setup.add_argument('action', nargs='?', choices=['inspect', 'remove', 'poll'])
    setup.add_argument('--site')
    setup.add_argument('--site-id')
    setup.add_argument('--label', default='This computer')
    setup.add_argument('--json', action='store_true')
    handoff = commands.add_parser('handoff').add_subparsers(dest='action', required=True)
    opening = handoff.add_parser('open')
    opening.add_argument('--uri', required=True)
    opening.add_argument('--json', action='store_true')
    for name in ('inspect', 'attach'):
        item = handoff.add_parser(name)
        item.add_argument('--handoff-id', required=True)
        item.add_argument('--json', action='store_true')
    sync = handoff.add_parser('sync')
    sync.add_argument('--handoff-id')
    sync.add_argument('--once', action='store_true')
    sync.add_argument('--json', action='store_true')
    return root


def start_sync() -> None:
    # No credential, model option or remote command enters child argv/environment.
    subprocess.Popen([sys.executable, '-m', 'capy_developer', 'handoff', 'sync'],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, close_fds=True, env=os.environ.copy())


def synchronize(companion: Companion, handoff_id=None) -> dict:
    # One per-installation reporter, bounded to eight hours and ten offline attempts.
    # It starts only after an explicit local open, never at OS boot or from remote jobs.
    permanent_errors = {'LINK_AUTHORITY_REJECTED', 'LINK_REMOVED', 'SITE_NOT_PAIRED', 'LINK_CONNECTION_REPLACED'}
    with exclusive_lock(companion.state.root / 'synchronizer.lock', 0,
                        busy_code='LINK_SYNC_ALREADY_RUNNING', busy_detail='this installation already has an active reporter'):
        deadline = time.monotonic() + 8 * 3600
        failures = 0
        while time.monotonic() < deadline:
            result = companion.sync_once(handoff_id)
            failures = 0 if result['ok'] else failures + 1
            if failures >= 10:
                return result
            with companion.state.connect() as db:
                query = '''SELECT last_snapshot,sync_error,
                           EXISTS(SELECT 1 FROM outbox WHERE outbox.handoff_id=handoffs.handoff_id) AS pending
                           FROM handoffs'''
                if handoff_id is None:
                    rows = db.execute(query).fetchall()
                else:
                    rows = db.execute(query + ' WHERE handoff_id=?', (handoff_id,)).fetchall()
            active = any(row['last_snapshot'] and not json.loads(row['last_snapshot'])['terminal']
                         and row['sync_error'] not in permanent_errors for row in rows)
            retry_pending = any(row['pending'] and row['sync_error'] not in permanent_errors for row in rows)
            if not active and not retry_pending:
                return result
            time.sleep(min(60, 5 * 2 ** min(failures, 4)) + random.uniform(0, 2))
        return {'ok': True, 'status': 'SYNC_WINDOW_ENDED', 'source_retained': True}


def run(raw_args) -> int:
    try:
        args = parser().parse_args(raw_args)
        if args.command == 'handoff' and args.action == 'open':
            parsed = parse_uri(args.uri)
            preflight_open(Config.from_environment().data_root, parsed['site_id'])
        core = DeveloperCore()
        companion = Companion(core)
        if args.command == 'setup':
            setup = Setup(core)
            if args.action == 'inspect':
                result = {**setup.inspect(), 'connections': companion.connections()}
            elif args.action == 'remove':
                if args.site_id:
                    result = setup.remove_site(companion, args.site_id)
                else:
                    result = setup.remove()
            elif args.action == 'poll':
                if not args.site_id:
                    raise DeveloperError('CLI_ARGUMENT_INVALID', '--site-id is required')
                result = companion.pair_poll(args.site_id)
            else:
                if not args.site or not args.site_id:
                    raise DeveloperError('CLI_ARGUMENT_INVALID', 'setup requires --site and --site-id from the Capy connection page')
                setup.install()
                result = companion.pair_start(args.site, args.site_id, args.label)
                if result.get('verification_url'):
                    print(json.dumps(result, sort_keys=True), flush=True)
                    subprocess.run(['/usr/bin/open', result['verification_url']], check=True, timeout=15, capture_output=True)
                    # Normal browser login/CSRF approval is the authority, not opening the page.
                    deadline = time.monotonic() + 600
                    while time.monotonic() < deadline:
                        time.sleep(3)
                        result = companion.pair_poll(args.site_id)
                        if result['state'] == 'APPROVED':
                            break
        elif args.action == 'open':
            try:
                result = companion.open_uri(args.uri)
            finally:
                if companion.prepared_for_launch:
                    start_sync()
        elif args.action == 'inspect':
            result = companion.inspect(args.handoff_id)
        elif args.action == 'attach':
            result = companion.attach(args.handoff_id)
        else:
            result = companion.sync_once(args.handoff_id) if args.once else synchronize(companion, args.handoff_id)
        print(json.dumps(result, sort_keys=True))
        return 0 if result.get('ok', True) else 1
    except (DeveloperError, ProtocolError, OSError, subprocess.SubprocessError) as exc:
        code = exc.code if isinstance(exc, DeveloperError) else ('LINK_PROTOCOL_INVALID' if isinstance(exc, ProtocolError) else 'DESKTOP_OPERATION_FAILED')
        detail = exc.detail if isinstance(exc, DeveloperError) else 'The desktop operation could not complete; inspect local setup and retry.'
        print(json.dumps({'ok': False, 'error': {'code': code, 'detail': detail}}, sort_keys=True))
        return 1
