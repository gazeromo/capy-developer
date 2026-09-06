"""Bounded, read-only discovery before constructing a mutating DeveloperCore.

A configuration command is data here: discovery never executes it. Historical
desktop ownership receipts remain authoritative for their exact owned MCP block.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import platform
import sqlite3
import stat
import tomllib

from .config import Config
from .errors import DeveloperError


ROOT_KEYS = (
    "CAPY_DEV_DATA_ROOT", "CAPY_DEV_CACHE_ROOT", "CAPY_DEV_REPOSITORIES_ROOT",
    "CAPY_DEV_WORKTREES_ROOT", "CAPY_DEV_VERIFICATION_TEMP_ROOT",
)
BEGIN = "# BEGIN CAPY DEVELOPER OWNED MCP V0\n"
END = "# END CAPY DEVELOPER OWNED MCP V0\n"


def conflict(detail: str) -> None:
    raise DeveloperError("INSTALLATION_CONFLICT", detail)


def read_owned(path: Path, maximum: int = 65536) -> bytes:
    """Reject nonregular, foreign-owned, symlinked and unbounded inputs."""
    for part in (path, *path.parents):
        if part.is_symlink():
            conflict("a recognized installation path is a symlink")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                conflict("a recognized installation file has an unsafe type or size")
            if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o022):
                conflict("a recognized installation file has unsafe ownership or write permissions")
            data = stream.read(maximum + 1)
            if len(data) > maximum:
                conflict("a recognized installation file exceeds its size bound")
            return data
    except OSError:
        conflict("a recognized installation file is unreadable")


def roots(config: Config) -> dict[str, str]:
    return dict(zip(ROOT_KEYS, map(str, (
        config.data_root, config.cache_root, config.repositories_root,
        config.worktrees_root, config.verification_temporary_root,
    ))))


def from_roots(value: object) -> Config:
    if not isinstance(value, dict) or set(value) != set(ROOT_KEYS):
        conflict("the installation must record all five exact roots")
    paths = []
    for key in ROOT_KEYS:
        raw = value[key]
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            conflict("invalid installation root")
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts:
            conflict("installation roots must be absolute and normalized")
        paths.append(path)
    return Config(*paths)


def validate_catalog(config: Config) -> None:
    path = config.database
    for part in (path, *path.parents):
        if part.is_symlink():
            conflict("a recognized catalog path is a symlink")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or (os.name != "nt" and (
            info.st_uid != os.getuid() or info.st_mode & 0o022
        )):
            conflict("the recognized catalog has unsafe ownership or permissions")
        # Read schema only. Never initialize, migrate or enumerate project data.
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        try:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"projects", "sessions"} <= tables:
                conflict("the recognized catalog does not have the Developer schema")
        finally:
            db.close()
    except (OSError, sqlite3.Error):
        conflict("the recognized Developer catalog is missing or unreadable")


def historical_config(config_path: Path) -> Config | None:
    """Recover roots only from an exact recorded Capy-owned configuration entry."""
    if not config_path.exists() and not config_path.is_symlink():
        return None
    raw = read_owned(config_path, 2 * 1024 * 1024)
    try:
        text = raw.decode("utf-8")
        document = tomllib.loads(text)
        entry = document.get("mcp_servers", {}).get("capy_developer")
    except (UnicodeError, ValueError, AttributeError):
        conflict("client configuration is invalid; no installation was allocated")
    if entry is None and BEGIN not in text and END not in text:
        return None
    if not isinstance(entry, dict) or text.count(BEGIN) != 1 or text.count(END) != 1:
        conflict("the recognized Capy entry has no exact ownership markers")
    start, end = text.index(BEGIN), text.index(END)
    if start >= end:
        conflict("Capy ownership markers are out of order")
    block = text[start:end + len(END)]
    config = from_roots(entry.get("env"))
    try:
        receipt = json.loads(read_owned(config.data_root / "desktop" / "setup.json"))
    except (ValueError, UnicodeError):
        conflict("the historical setup receipt is invalid")
    if not isinstance(receipt, dict) or (
        receipt.get("schema") != "capy.desktop-setup/v0"
        or receipt.get("config_path") != str(config_path)
        or receipt.get("mcp_block") != block
        or entry.get("command") != receipt.get("python")
        or entry.get("args") != ["-m", "capy_developer", "mcp"]
    ):
        conflict("the recognized Capy entry differs from its ownership receipt")
    try:
        block_entry = tomllib.loads(block)["mcp_servers"]["capy_developer"]
    except (ValueError, KeyError, TypeError):
        conflict("the recorded Capy block is invalid")
    if block_entry != entry:
        conflict("the Capy entry includes changes outside its ownership block")
    validate_catalog(config)
    return config


def locator_path() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/Capy/installation.json"
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "Capy/installation.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "capy/installation.json"


def located_config(path: Path) -> Config | None:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        locator = json.loads(read_owned(path))
        if not isinstance(locator, dict) or set(locator) != {"schema", "receipt", "sha256"} or locator["schema"] != "capy.installation-locator/v0":
            conflict("invalid Capy installation locator")
        if not isinstance(locator["receipt"], str) or not Path(locator["receipt"]).is_absolute():
            conflict("invalid installation receipt path")
        raw = read_owned(Path(locator["receipt"]))
        if hashlib.sha256(raw).hexdigest() != locator["sha256"]:
            conflict("installation locator and receipt disagree")
        receipt = json.loads(raw)
        if not isinstance(receipt, dict) or set(receipt) != {"schema", "roots"} or receipt["schema"] != "capy.installation/v0":
            conflict("invalid Capy installation receipt")
        config = from_roots(receipt["roots"])
        if Path(locator["receipt"]) != config.data_root / "installation.json":
            conflict("installation receipt is outside the recorded installation")
        validate_catalog(config)
        return config
    except (ValueError, UnicodeError, TypeError):
        conflict("invalid Capy installation locator or receipt")


def discover(*, default: Config, config_path: Path, explicit: Config | None = None,
             locator: Path | None = None) -> dict:
    """Return a validated existing installation or a mutation-free fresh proposal.

    Paths are mandatory inputs so tests and bootstrap never accidentally inspect
    another user profile. An explicit trusted entrypoint wins without home scans.
    """
    if explicit is not None:
        explicit = from_roots(roots(explicit))
        validate_catalog(explicit)
        return {"status": "EXISTING", "source": "EXPLICIT", "config": explicit}
    located = located_config(locator) if locator is not None else None
    if located is not None:
        return {"status": "EXISTING", "source": "LOCATOR", "config": located}
    historical = historical_config(config_path)
    exists = default.database.exists() or default.database.is_symlink()
    if historical is not None:
        if exists and historical.data_root != default.data_root:
            validate_catalog(default)
            conflict("multiple recognized installations require an explicit installation selection")
        return {"status": "EXISTING", "source": "HISTORICAL_SETUP", "config": historical}
    if exists:
        validate_catalog(default)
        return {"status": "EXISTING", "source": "DEFAULT", "config": default}
    # A partial installation is not evidence that no installation exists.
    if (default.data_root / "desktop").exists() or (default.data_root / "desktop").is_symlink():
        conflict("an existing partial installation needs repair before fresh setup")
    return {"status": "FRESH_PROPOSAL", "source": "DEFAULT", "config": default}


def historical_python(config: Config, config_path: Path) -> str | None:
    """Return a path only from the existing exact owned desktop configuration."""
    if not (config.data_root/'desktop/setup.json').exists():
        return None
    recognized = historical_config(config_path)
    if recognized is None or roots(recognized) != roots(config):
        conflict('historical environment and selected installation disagree')
    receipt = json.loads(read_owned(config.data_root/'desktop/setup.json'))
    value = receipt.get('python')
    if not isinstance(value, str) or not Path(value).is_absolute():
        conflict('invalid historical Python path')
    return value
