from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path


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


@dataclass(frozen=True)
class Config:
    data_root: Path
    cache_root: Path
    repositories_root: Path
    worktrees_root: Path

    @classmethod
    def from_environment(cls) -> "Config":
        data = Path(os.environ.get("CAPY_DEV_DATA_ROOT", _default_data_root()))
        cache = Path(os.environ.get("CAPY_DEV_CACHE_ROOT", _default_cache_root()))
        repositories = Path(os.environ.get("CAPY_DEV_REPOSITORIES_ROOT", data / "repositories"))
        worktrees = Path(os.environ.get("CAPY_DEV_WORKTREES_ROOT", data / "worktrees"))
        return cls(data, cache, repositories, worktrees)

    def ensure(self) -> None:
        for path in (self.data_root, self.cache_root, self.repositories_root, self.worktrees_root):
            path.mkdir(parents=True, exist_ok=True)

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
        return self.data_root / "verification-locks" / f"{session_id}.lock"
