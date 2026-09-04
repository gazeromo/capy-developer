from __future__ import annotations

import os
import platform
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import DeveloperError
from .util import SESSION_ID, safe_resolve


def _default_data_root() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Capy" / "Developer"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Capy" / "Developer"
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "capy" / "developer"


def _default_cache_root() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "Capy" / "Developer" / "Cache"
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Caches" / "Capy" / "Developer"
    base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "capy" / "developer"


def _default_verification_temp_root() -> Path:
    if platform.system() == "Windows":
        # The accepted DevKit uses AF_UNIX even for an empty connection set.
        # A drive-root child keeps its nested simulator socket below Windows'
        # sockaddr_un limit; operators can override this managed root.
        return Path(Path(tempfile.gettempdir()).anchor) / "cv"
    return Path("/tmp/cv") if Path("/tmp").is_dir() else Path(tempfile.gettempdir()) / "cv"


@dataclass(frozen=True)
class Config:
    data_root: Path
    cache_root: Path
    repositories_root: Path
    worktrees_root: Path
    temporary_root: Path | None = None

    @classmethod
    def from_environment(cls) -> "Config":
        data = Path(os.environ.get("CAPY_DEV_DATA_ROOT", _default_data_root()))
        cache = Path(os.environ.get("CAPY_DEV_CACHE_ROOT", _default_cache_root()))
        repositories = Path(os.environ.get("CAPY_DEV_REPOSITORIES_ROOT", data / "repositories"))
        worktrees = Path(os.environ.get("CAPY_DEV_WORKTREES_ROOT", data / "worktrees"))
        temporary = Path(os.environ.get("CAPY_DEV_VERIFICATION_TEMP_ROOT", _default_verification_temp_root()))
        return cls(data, cache, repositories, worktrees, temporary)

    def ensure(self) -> None:
        for path in (
            self.data_root, self.cache_root, self.repositories_root,
            self.worktrees_root, self.verification_temporary_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def verification_temporary_root(self) -> Path:
        return self.temporary_root or _default_verification_temp_root()

    @property
    def database(self) -> Path:
        return self.data_root / "catalog.sqlite3"

    @property
    def operation_lock(self) -> Path:
        return self.data_root / "operation.lock"

    @property
    def verification_root(self) -> Path:
        return self.cache_root / "v"

    @property
    def verification_artifacts_root(self) -> Path:
        return self.cache_root / "verification-artifacts" / "sha256"

    def verification_lock(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or SESSION_ID.fullmatch(session_id) is None:
            raise DeveloperError("SESSION_ID_INVALID", "session_id is invalid")
        root = self.data_root / "verification-locks"
        return safe_resolve(root / f"{session_id}.lock", root=root)
