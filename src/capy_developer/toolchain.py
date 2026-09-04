from __future__ import annotations

import hashlib
import importlib.resources
import json
import shutil
import tomllib
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from .errors import DeveloperError
from .util import HEX40, HEX64


ACCEPTED_DEVKIT_MAIN = "0cf018faa02ade73ab0805aa0617c55ce36fa7b1"
ACCEPTED_BUNDLE_SHA256 = "cb7e4073a99bf8596509af02f466f90b5792d1d8075dffab0f27bbb2df0679e8"
ACCEPTED_WHEEL_SHA256 = "165faba51b56b667b087228e1c556b1e2369d0e61bb469785ddff1bad9d6e2d0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ToolchainLock:
    schema: str | None
    contract: str | None
    repository: str | None
    commit: str | None
    wheel: str | None
    wheel_sha256: str | None
    bundle_sha256: str | None
    source_path: str | None
    lock_status: str
    detail: str | None = None

    def as_dict(self, availability: str) -> dict:
        return {
            "schema": self.schema,
            "contract": self.contract,
            "devkit_repository": self.repository,
            "devkit_commit": self.commit,
            "wheel": self.wheel,
            "wheel_sha256": self.wheel_sha256,
            "authoring_bundle_sha256": self.bundle_sha256,
            "lock_source_path": self.source_path,
            "lock_status": self.lock_status,
            "availability": availability,
            "detail": self.detail,
        }


def _valid(lock: ToolchainLock) -> bool:
    return (
        lock.contract == "capy.script/dev-v0"
        and bool(lock.repository)
        and bool(lock.commit and HEX40.fullmatch(lock.commit))
        and bool(lock.wheel)
        and bool(lock.wheel_sha256 and HEX64.fullmatch(lock.wheel_sha256))
        and (lock.bundle_sha256 is None or HEX64.fullmatch(lock.bundle_sha256) is not None)
    )


def read_lock(checkout: Path) -> ToolchainLock:
    current = checkout / "capy.lock"
    legacy = checkout / "DEVKIT.lock"
    selected = current if current.is_file() else legacy if legacy.is_file() else None
    if selected is None:
        return ToolchainLock(None, None, None, None, None, None, None, None, "UNBOUND", "no DevKit lock declared")
    try:
        data = tomllib.loads(selected.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        return ToolchainLock(None, None, None, None, None, None, None, str(selected), "INVALID", str(exc))
    if selected.name == "DEVKIT.lock":
        lock = ToolchainLock(
            "legacy-devkit-lock/v0", data.get("contract"), data.get("repository"),
            data.get("commit"), data.get("wheel"), data.get("wheel_sha256"),
            None, str(selected), "VALID",
        )
    else:
        lock = ToolchainLock(
            data.get("schema"), data.get("contract"), data.get("devkit_repository"),
            data.get("devkit_commit"), data.get("wheel"), data.get("wheel_sha256"),
            data.get("authoring_bundle_sha256"), str(selected), "VALID",
        )
    if not _valid(lock):
        return replace(lock, lock_status="INVALID", detail="lock fields are incomplete or malformed")
    return lock


class ToolchainCache:
    def __init__(self, cache_root: Path):
        self.root = cache_root / "toolchains" / "sha256"

    def accepted_bundle(self) -> Path:
        resource = importlib.resources.files("capy_developer").joinpath("data/accepted-authoring-bundle.zip")
        with importlib.resources.as_file(resource) as bundled:
            if sha256_file(bundled) != ACCEPTED_BUNDLE_SHA256:
                raise DeveloperError("DEVKIT_BUNDLE_DIGEST_MISMATCH", "embedded accepted DevKit bundle is invalid")
            target = self.root / ACCEPTED_BUNDLE_SHA256 / "authoring-bundle.zip"
            if target.exists() and sha256_file(target) != ACCEPTED_BUNDLE_SHA256:
                raise DeveloperError("DEVKIT_CACHE_CONFLICT", "cached accepted DevKit bundle has the wrong digest")
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                shutil.copyfile(bundled, temporary)
                if sha256_file(temporary) != ACCEPTED_BUNDLE_SHA256:
                    temporary.unlink(missing_ok=True)
                    raise DeveloperError("DEVKIT_BUNDLE_DIGEST_MISMATCH", "copied DevKit bundle failed verification")
                temporary.replace(target)
            self._verify_bundle(target)
            return target

    def _verify_bundle(self, bundle: Path) -> dict:
        try:
            with zipfile.ZipFile(bundle) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise DeveloperError("DEVKIT_BUNDLE_INVALID", "DevKit bundle contains duplicate paths")
                for name in names:
                    path = PurePosixPath(name)
                    if path.is_absolute() or ".." in path.parts:
                        raise DeveloperError("DEVKIT_BUNDLE_INVALID", "DevKit bundle contains an unsafe path")
                manifest = json.loads(archive.read("RELEASE-MANIFEST.json"))
                wheel_name = manifest["wheel_filename"]
                wheel_bytes = archive.read(f"wheel/{wheel_name}")
        except (KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
            raise DeveloperError("DEVKIT_BUNDLE_INVALID", "DevKit bundle structure is invalid") from exc
        if manifest.get("schema") != "capy.devkit-authoring-bundle/v0":
            raise DeveloperError("DEVKIT_BUNDLE_INVALID", "DevKit bundle schema is unsupported")
        if hashlib.sha256(wheel_bytes).hexdigest() != ACCEPTED_WHEEL_SHA256:
            raise DeveloperError("DEVKIT_WHEEL_DIGEST_MISMATCH", "accepted DevKit wheel digest is invalid")
        return manifest

    def availability(self, lock: ToolchainLock) -> str:
        if lock.lock_status == "UNBOUND":
            return "UNBOUND"
        if lock.lock_status != "VALID":
            return "INVALID"
        if lock.bundle_sha256:
            if lock.bundle_sha256 == ACCEPTED_BUNDLE_SHA256:
                self.accepted_bundle()
            candidate = self.root / lock.bundle_sha256 / "authoring-bundle.zip"
            return "AVAILABLE" if candidate.is_file() and sha256_file(candidate) == lock.bundle_sha256 else "MISSING"
        if lock.wheel_sha256 == ACCEPTED_WHEEL_SHA256:
            self.accepted_bundle()
            return "AVAILABLE"
        for bundle in self.root.glob("*/authoring-bundle.zip"):
            try:
                with zipfile.ZipFile(bundle) as archive:
                    manifest = json.loads(archive.read("RELEASE-MANIFEST.json"))
                    wheel_name = manifest["wheel_filename"]
                    wheel_bytes = archive.read(f"wheel/{wheel_name}")
                actual_wheel_sha256 = hashlib.sha256(wheel_bytes).hexdigest()
                if (
                    manifest.get("wheel_sha256") == lock.wheel_sha256
                    and actual_wheel_sha256 == lock.wheel_sha256
                    and sha256_file(bundle) == bundle.parent.name
                ):
                    return "AVAILABLE"
            except (OSError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
                continue
        return "MISSING"

    def materialize_template(self, target: Path, application_id: str, name: str) -> None:
        bundle = self.accepted_bundle()
        with zipfile.ZipFile(bundle) as archive:
            members = [info for info in archive.infolist() if info.filename.startswith("template/") and not info.is_dir()]
            for info in members:
                relative = PurePosixPath(info.filename).relative_to("template")
                if ".." in relative.parts:
                    raise DeveloperError("DEVKIT_BUNDLE_INVALID", "template path escapes its root")
                destination = target.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                payload = archive.read(info)
                if relative.as_posix() == "capability.toml":
                    text = payload.decode("utf-8")
                    text = text.replace('id = "demo.hello"', f'id = "{application_id}"', 1)
                    text = text.replace('name = "Hello"', f'name = "{name}"', 1)
                    payload = text.encode("utf-8")
                destination.write_bytes(payload)


def current_lock(source_path: str | None = "capy.lock") -> ToolchainLock:
    return ToolchainLock(
        "capy.toolchain-lock/v0", "capy.script/dev-v0", "gazeromo/capy-script-devkit",
        ACCEPTED_DEVKIT_MAIN, "capy_script_devkit-0.0.0-py3-none-any.whl",
        ACCEPTED_WHEEL_SHA256, ACCEPTED_BUNDLE_SHA256, source_path, "VALID",
    )
