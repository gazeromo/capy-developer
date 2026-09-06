"""Private local link associations, credentials and transactional outbox."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import sqlite3
import stat
import time

from ..errors import DeveloperError
from .credentials import default_credentials


def preflight_open(data_root: Path, site_id: str) -> None:
    """Read-only callback admission before DeveloperCore can create any roots."""
    root = data_root / 'desktop'
    path = root / 'links.sqlite3'
    if not root.is_dir() or root.is_symlink() or not path.is_file() or path.is_symlink():
        raise DeveloperError('SITE_NOT_PAIRED', 'connect this computer to the selected site first')
    if os.name == 'posix':
        for item in (root, path):
            info = item.stat()
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise DeveloperError('LINK_STORAGE_UNSAFE', 'local pairing storage requires owner-only permissions')
    else:
        raise DeveloperError('CREDENTIAL_STORE_UNAVAILABLE', 'this platform has no qualified protected credential store')
    try:
        with contextlib.closing(sqlite3.connect(path.absolute().as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT state,expires_at,length(secret) FROM pairs WHERE site_id=?', (site_id,)).fetchone()
        if row is None or row[0] != 'APPROVED' or row[1] <= time.time() or not row[2]:
            raise DeveloperError('SITE_NOT_PAIRED', 'the local site connection is not active')
    except sqlite3.Error:
        raise DeveloperError('LINK_STORAGE_UNAVAILABLE', 'local pairing storage is unreadable; inspect setup') from None


def private_directory(path: Path) -> None:
    if path.is_symlink():
        raise DeveloperError('LINK_STORAGE_UNSAFE', 'private link directory cannot be a symlink')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        info = path.stat()
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise DeveloperError('LINK_STORAGE_UNSAFE', 'private link directory requires owner-only permissions')


class State:
    def __init__(self, root: Path, *, credential_store=None):
        self.root = root
        self.credentials = credential_store if credential_store is not None else default_credentials()
        private_directory(root)
        self.path = root / 'links.sqlite3'
        if self.path.is_symlink():
            raise DeveloperError('LINK_STORAGE_UNSAFE', 'private database cannot be a symlink')
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
        elif os.name != 'nt' and (self.path.stat().st_uid != os.getuid() or stat.S_IMODE(self.path.stat().st_mode) & 0o077):
            raise DeveloperError('LINK_STORAGE_UNSAFE', 'private database requires owner-only permissions')
        with self.connect() as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1, 2):
                raise DeveloperError('LINK_STORAGE_VERSION', 'unsupported local link schema')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS pairs (
                  site_id TEXT PRIMARY KEY, origin TEXT NOT NULL, installation_id TEXT NOT NULL,
                  secret TEXT NOT NULL, pair_id TEXT, device_id TEXT, principal_id TEXT,
                  expires_at INTEGER NOT NULL, state TEXT NOT NULL, label TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS handoffs (
                  handoff_id TEXT PRIMARY KEY, site_id TEXT NOT NULL, request TEXT NOT NULL,
                  session_id TEXT, project_id TEXT, attached INTEGER NOT NULL DEFAULT 0,
                  generation INTEGER NOT NULL DEFAULT 0, launch_state TEXT NOT NULL DEFAULT 'PREPARING',
                  last_snapshot TEXT, next_sequence INTEGER NOT NULL DEFAULT 1,
                  ack_sequence INTEGER NOT NULL DEFAULT 0, sync_error TEXT);
                CREATE TABLE IF NOT EXISTS outbox (
                  handoff_id TEXT NOT NULL, sequence INTEGER NOT NULL, event TEXT NOT NULL,
                  PRIMARY KEY(handoff_id, sequence));
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(handoffs)')}
            if 'pair_installation_id' not in columns:
                db.execute('ALTER TABLE handoffs ADD COLUMN pair_installation_id TEXT')
                db.execute('''UPDATE handoffs SET pair_installation_id=(
                    SELECT installation_id FROM pairs WHERE pairs.site_id=handoffs.site_id)''')
            db.execute('PRAGMA user_version=2')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        # DELETE journal inherits database permissions and avoids persistent WAL copies.
        try:
            with db:
                yield db
        finally:
            db.close()

    def pair_record(self, site_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM pairs WHERE site_id=?', (site_id,)).fetchone()
        if row is None:
            raise DeveloperError('SITE_NOT_PAIRED', 'connect this computer to the selected site first')
        return dict(row)

    def pair(self, site_id: str) -> dict:
        value = self.pair_record(site_id)
        value['credential_storage'] = 'macos-keychain' if value['secret'].startswith('keychain:') else 'private-local-file'
        value['secret'] = self.credentials.read(value['secret'])
        return value

    def handoff(self, handoff_id: str) -> dict:
        with self.connect() as db:
            row = db.execute('SELECT * FROM handoffs WHERE handoff_id=?', (handoff_id,)).fetchone()
        if row is None:
            raise DeveloperError('HANDOFF_NOT_FOUND', 'this computer has no prepared handoff with that identity')
        return dict(row)
