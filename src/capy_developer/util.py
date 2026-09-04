from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from .errors import DeveloperError


PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}\Z")
APPLICATION_ID = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\Z")
PROJECT_ID = re.compile(r"prj_[A-Za-z0-9_]{1,96}\Z")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def machine_id() -> str:
    return hashlib.sha256(f"{socket.gethostname()}:{uuid.getnode()}".encode()).hexdigest()[:24]


def safe_resolve(path: Path, *, root: Path | None = None, must_exist: bool = False) -> Path:
    absolute = path.expanduser().absolute()
    resolved = absolute.resolve(strict=must_exist)
    if root is not None:
        root_resolved = root.expanduser().absolute().resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise DeveloperError("MANAGED_PATH_ESCAPE", "managed path escapes its configured root") from exc
    return resolved


def path_uri(path: Path) -> str:
    return path.resolve().as_uri()


def validate_new_project(name: str, application_id: str) -> None:
    if PROJECT_NAME.fullmatch(name) is None:
        raise DeveloperError("PROJECT_NAME_INVALID", "name must use bounded letters, numbers, spaces, dot, underscore, or hyphen")
    if APPLICATION_ID.fullmatch(application_id) is None:
        raise DeveloperError("APPLICATION_ID_INVALID", "application_id must be a dotted lowercase identifier")


def normalize_repository(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise DeveloperError("REPOSITORY_IDENTITY_INVALID", "repository identity is empty")
    scp = re.fullmatch(r"(?:[^@\s]+@)?([^:\s]+):/?(.+)", raw)
    if scp and "://" not in raw and not re.fullmatch(r"[A-Za-z]:[\\/].*", raw):
        host, repo_path = scp.groups()
        clean = repo_path.rstrip("/")
        if clean.endswith(".git"):
            clean = clean[:-4]
        normalized_path = clean.lower() if host.lower() == "github.com" else clean
        return f"git://{host.lower()}/{normalized_path}"
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https", "ssh", "git"} and parsed.hostname:
        clean = parsed.path.strip("/")
        if clean.endswith(".git"):
            clean = clean[:-4]
        normalized_path = clean.lower() if parsed.hostname.lower() == "github.com" else clean
        return f"git://{parsed.hostname.lower()}/{normalized_path}"
    if parsed.scheme == "file":
        return safe_resolve(Path(url2pathname(parsed.path)), must_exist=False).as_uri()
    path = Path(raw)
    if path.is_absolute() or raw.startswith("."):
        return safe_resolve(path, must_exist=False).as_uri()
    return raw.lower().removesuffix(".git").rstrip("/")


@contextmanager
def operation_lock(path: Path, timeout: float = 30.0):
    deadline = time.monotonic() + timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    locked = False
    while not locked:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise DeveloperError("OPERATION_BUSY", "another Capy Developer operation is active")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
