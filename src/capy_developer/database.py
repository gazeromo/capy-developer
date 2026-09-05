from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .util import utc_now


SCHEMA_VERSION = 4


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
            existing = db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'"
            ).fetchone()
            if existing:
                current = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                if current is not None and int(current[0]) not in {1, 2, 3, SCHEMA_VERSION}:
                    raise RuntimeError(f"unsupported database schema {current[0]}")
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
                    interaction_contract TEXT,
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
                CREATE TABLE IF NOT EXISTS verification_attempts (
                    verification_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_digest TEXT NOT NULL,
                    application_id TEXT NOT NULL,
                    candidate_commit TEXT NOT NULL,
                    candidate_tree TEXT NOT NULL,
                    base_commit TEXT NOT NULL,
                    development_branch TEXT NOT NULL,
                    lock_digest TEXT NOT NULL,
                    contract TEXT NOT NULL,
                    release_binding_commit TEXT,
                    authoring_bundle_sha256 TEXT NOT NULL,
                    wheel_sha256 TEXT NOT NULL,
                    pipeline_schema TEXT NOT NULL DEFAULT 'capy.development-verification-pipeline/v0',
                    interaction_contract TEXT,
                    status TEXT NOT NULL,
                    classification TEXT,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    terminal_at TEXT,
                    archive_sha256 TEXT,
                    archive_size_bytes INTEGER,
                    archive_path TEXT,
                    temporary_path TEXT,
                    error_code TEXT,
                    error_detail TEXT
                );
                CREATE INDEX IF NOT EXISTS verification_attempts_session
                    ON verification_attempts(session_id, started_at, verification_id);
                CREATE TABLE IF NOT EXISTS verification_stages (
                    verification_id TEXT NOT NULL REFERENCES verification_attempts(verification_id),
                    stage_order INTEGER NOT NULL,
                    stage_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    terminal_at TEXT,
                    duration_ms INTEGER,
                    exit_code INTEGER,
                    stdout_text TEXT NOT NULL DEFAULT '',
                    stderr_text TEXT NOT NULL DEFAULT '',
                    stdout_truncated_bytes INTEGER NOT NULL DEFAULT 0,
                    stderr_truncated_bytes INTEGER NOT NULL DEFAULT 0,
                    facts TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(verification_id, stage_order),
                    UNIQUE(verification_id, stage_name)
                );
                CREATE TABLE IF NOT EXISTS verification_interactions (
                    verification_id TEXT PRIMARY KEY REFERENCES verification_attempts(verification_id),
                    schema TEXT NOT NULL,
                    source_member TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    canonical_sha256 TEXT NOT NULL,
                    canonical_size_bytes INTEGER NOT NULL,
                    canonical_path TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS release_candidates (
                    release_candidate_id TEXT PRIMARY KEY,
                    verification_id TEXT NOT NULL UNIQUE REFERENCES verification_attempts(verification_id),
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    application_id TEXT NOT NULL,
                    candidate_commit TEXT NOT NULL,
                    candidate_tree TEXT NOT NULL,
                    base_commit TEXT NOT NULL,
                    identity_sha256 TEXT NOT NULL,
                    repository_kind TEXT NOT NULL,
                    repository_public_identity TEXT,
                    repository_identity_sha256 TEXT NOT NULL,
                    application_archive_sha256 TEXT NOT NULL,
                    application_archive_size_bytes INTEGER NOT NULL,
                    descriptor_sha256 TEXT NOT NULL,
                    toolchain_contract TEXT NOT NULL,
                    toolchain_release_binding_commit TEXT NOT NULL,
                    toolchain_implementation_commit TEXT NOT NULL,
                    toolchain_authoring_bundle_sha256 TEXT NOT NULL,
                    toolchain_wheel_filename TEXT NOT NULL,
                    toolchain_wheel_sha256 TEXT NOT NULL,
                    verification_receipt_sha256 TEXT NOT NULL,
                    format_schema TEXT NOT NULL DEFAULT 'capy.application-release-candidate/v0',
                    manifest_json TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    bundle_sha256 TEXT,
                    bundle_size_bytes INTEGER,
                    bundle_path TEXT,
                    status TEXT NOT NULL,
                    classification TEXT,
                    attempt_count INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    terminal_at TEXT,
                    error_code TEXT,
                    error_detail TEXT
                );
                CREATE INDEX IF NOT EXISTS release_candidates_session
                    ON release_candidates(session_id, started_at, release_candidate_id);
                CREATE TABLE IF NOT EXISTS release_candidate_members (
                    release_candidate_id TEXT NOT NULL REFERENCES release_candidates(release_candidate_id),
                    member_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    PRIMARY KEY(release_candidate_id, member_path)
                );
                CREATE TABLE IF NOT EXISTS release_candidate_interactions (
                    release_candidate_id TEXT PRIMARY KEY REFERENCES release_candidates(release_candidate_id),
                    schema TEXT NOT NULL,
                    source_member TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    canonical_member TEXT NOT NULL,
                    canonical_sha256 TEXT NOT NULL,
                    canonical_size_bytes INTEGER NOT NULL,
                    operation_id TEXT NOT NULL
                );
                """
            )
            self._add_column(db, "toolchain_locks", "interaction_contract", "TEXT")
            self._add_column(
                db, "verification_attempts", "pipeline_schema",
                "TEXT NOT NULL DEFAULT 'capy.development-verification-pipeline/v0'",
            )
            self._add_column(db, "verification_attempts", "interaction_contract", "TEXT")
            self._add_column(
                db, "release_candidates", "format_schema",
                "TEXT NOT NULL DEFAULT 'capy.application-release-candidate/v0'",
            )
            db.execute(
                "UPDATE verification_attempts SET pipeline_schema='capy.development-verification-pipeline/v0' "
                "WHERE pipeline_schema IS NULL OR pipeline_schema=''"
            )
            db.execute(
                "UPDATE release_candidates SET format_schema='capy.application-release-candidate/v0' "
                "WHERE format_schema IS NULL OR format_schema=''"
            )
            current = db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            if current is None:
                db.execute("INSERT INTO metadata VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif int(current[0]) in {1, 2, 3}:
                db.execute("UPDATE metadata SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))

    @staticmethod
    def _add_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def row(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    def event(self, db: sqlite3.Connection, session_id: str, event_type: str, facts: dict | None = None) -> None:
        db.execute(
            "INSERT INTO session_events(session_id,event_type,created_at,facts) VALUES (?,?,?,?)",
            (session_id, event_type, utc_now(), json.dumps(facts or {}, sort_keys=True)),
        )
