from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .util import utc_now


SCHEMA_VERSION = 1


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    repository_identity TEXT NOT NULL UNIQUE,
                    repository_url TEXT NOT NULL,
                    default_branch TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS project_aliases (
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    alias TEXT NOT NULL COLLATE NOCASE,
                    source TEXT NOT NULL,
                    UNIQUE(project_id, alias)
                );
                CREATE TABLE IF NOT EXISTS project_applications (
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    application_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    UNIQUE(project_id, application_id)
                );
                CREATE TABLE IF NOT EXISTS local_checkouts (
                    checkout_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    machine_id TEXT NOT NULL,
                    native_path TEXT NOT NULL,
                    path_uri TEXT NOT NULL,
                    checkout_kind TEXT NOT NULL,
                    observed_commit TEXT,
                    observed_branch TEXT,
                    dirty INTEGER NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(machine_id, native_path)
                );
                CREATE TABLE IF NOT EXISTS toolchain_locks (
                    project_id TEXT PRIMARY KEY REFERENCES projects(project_id),
                    schema TEXT,
                    contract TEXT,
                    devkit_repository TEXT,
                    devkit_commit TEXT,
                    wheel_filename TEXT,
                    wheel_sha256 TEXT,
                    authoring_bundle_sha256 TEXT,
                    lock_source_path TEXT,
                    lock_status TEXT NOT NULL,
                    availability TEXT NOT NULL,
                    detail TEXT
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    project_id TEXT REFERENCES projects(project_id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_digest TEXT NOT NULL,
                    normalized_input TEXT NOT NULL,
                    exact_base_commit TEXT,
                    development_branch TEXT,
                    worktree_path TEXT,
                    allocated_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    terminal_disposition TEXT,
                    terminal_at TEXT,
                    final_commit TEXT,
                    final_dirty INTEGER,
                    error_code TEXT,
                    error_detail TEXT
                );
                CREATE TABLE IF NOT EXISTS session_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    facts TEXT NOT NULL
                );
                """
            )
            current = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if current is None:
                db.execute("INSERT INTO metadata VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(current[0]) != SCHEMA_VERSION:
                raise RuntimeError(f"unsupported database schema {current[0]}")

    @staticmethod
    def row(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    def event(self, db: sqlite3.Connection, session_id: str, event_type: str, facts: dict | None = None) -> None:
        db.execute(
            "INSERT INTO session_events(session_id,event_type,created_at,facts) VALUES (?,?,?,?)",
            (session_id, event_type, utc_now(), json.dumps(facts or {}, sort_keys=True)),
        )
