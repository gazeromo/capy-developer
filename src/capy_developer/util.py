from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import stat
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
SESSION_ID = re.compile(r"ses_[A-Za-z0-9_]{1,124}\Z")
VERIFICATION_ID = re.compile(r"ver_[A-Za-z0-9_]{1,124}\Z")
RELEASE_CANDIDATE_ID = re.compile(r"rc_[0-9a-f]{32}\Z")
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


def read_regular_bytes(path: Path) -> bytes:
    """Read one durable regular file without following a mutable symlink alias."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise OSError("managed evidence is not a regular non-symlink file")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError("managed evidence changed type while opening")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            payload = stream.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    after = path.lstat()
    if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise OSError("managed evidence changed identity while reading")
    return payload


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
    native_path = Path(raw)
    if native_path.is_absolute() or raw.startswith(".") or re.fullmatch(r"[A-Za-z]:[\\/].*", raw):
        return safe_resolve(native_path, must_exist=False).as_uri()
    if "::" in raw:
        raise DeveloperError("REPOSITORY_PROTOCOL_UNSUPPORTED", "Git remote helpers are not supported")
    scp = re.fullmatch(r"(?:[^@\s]+@)?([^:\s]+):/?([^:\s].*)", raw)
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
        try:
            port = parsed.port
        except ValueError as exc:
            raise DeveloperError("REPOSITORY_IDENTITY_INVALID", "repository URL port is invalid") from exc
        default_port = {"http": 80, "https": 443, "ssh": 22}.get(parsed.scheme)
        authority = parsed.hostname.lower() if port is None or port == default_port else f"{parsed.hostname.lower()}:{port}"
        return f"git://{authority}/{normalized_path}"
    if parsed.scheme == "file":
        return safe_resolve(Path(url2pathname(parsed.path)), must_exist=False).as_uri()
    if parsed.scheme:
        raise DeveloperError("REPOSITORY_PROTOCOL_UNSUPPORTED", "repository URL protocol is unsupported")
    raise DeveloperError("REPOSITORY_IDENTITY_INVALID", "repository identity must be a native path or supported Git URL")


def _try_lock(candidate) -> None:
    if os.fstat(candidate.fileno()).st_size == 0:
        candidate.write(b"\0")
        candidate.flush()
    candidate.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(candidate.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(candidate.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(candidate) -> None:
    candidate.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(candidate.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(candidate.fileno(), fcntl.LOCK_UN)


@contextmanager
def exclusive_lock(
    path: Path,
    timeout: float = 30.0,
    *,
    busy_code: str = "OPERATION_BUSY",
    busy_detail: str = "another Capy Developer operation is active",
):
    deadline = time.monotonic() + timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = None
    while handle is None:
        candidate = None
        descriptor = None
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            candidate = os.fdopen(descriptor, "r+b")
            descriptor = None
            _try_lock(candidate)
            handle = candidate
        except OSError:
            if candidate is not None:
                candidate.close()
            elif descriptor is not None:
                os.close(descriptor)
            if time.monotonic() >= deadline:
                raise DeveloperError(busy_code, busy_detail)
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            _unlock(handle)
        finally:
            handle.close()


def operation_lock(path: Path, timeout: float = 30.0):
    return exclusive_lock(path, timeout)


def lock_is_available(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    candidate = os.fdopen(descriptor, "r+b")
    try:
        _try_lock(candidate)
    except OSError:
        candidate.close()
        return False
    try:
        _unlock(candidate)
    finally:
        candidate.close()
    return True
