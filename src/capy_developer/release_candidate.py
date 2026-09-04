from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import tomllib
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from .errors import DeveloperError
from .git import run_git
from .toolchain import sha256_file
from .util import (
    APPLICATION_ID,
    HEX40,
    HEX64,
    PROJECT_ID,
    RELEASE_CANDIDATE_ID,
    SESSION_ID,
    VERIFICATION_ID,
    exclusive_lock,
    path_uri,
    safe_resolve,
    utc_now,
)
from .verification import STAGES


RESULT_SCHEMA = "capy.development-release-candidate-result/v0"
MANIFEST_SCHEMA = "capy.application-release-candidate/v0"
RECEIPT_SCHEMA = "capy.development-verification-receipt/v0"
MEMBERS = (
    "RELEASE-CANDIDATE.json",
    "application/application.zip",
    "evidence/verification.json",
    "toolchain/authoring-bundle.zip",
)
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
MAX_APPLICATION_BYTES = 64 * 1024 * 1024
MAX_APPLICATION_MEMBERS = 4096
MAX_APPLICATION_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_TOOLCHAIN_BYTES = 64 * 1024 * 1024
MAX_TOOLCHAIN_MEMBERS = 4096
MAX_TOOLCHAIN_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_TOOLCHAIN_WHEEL_BYTES = 64 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 130 * 1024 * 1024

_PROCESS_STAGES = {"toolchain_install", "check", "test", "conform", "pack_a", "pack_b"}

_FACT_KEYS = {
    "toolchain_install": {"timed_out"},
    "check": {"timed_out", "candidate_unchanged"},
    "test": {"timed_out", "candidate_unchanged"},
    "conform": {"timed_out", "candidate_unchanged"},
    "source_mutation_check": set(),
    "pack_a": {"timed_out", "candidate_unchanged"},
    "pack_b": {"timed_out", "candidate_unchanged"},
    "package_compare": {"sha256_a", "sha256_b", "size_a", "size_b"},
    "archive_preserve": {"sha256", "size_bytes"},
}


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DeveloperError("RELEASE_CANDIDATE_METADATA_INVALID", "candidate metadata is not canonical JSON") from exc


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_keys(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", f"{label} shape is invalid")
    return value


def _safe_zip_infos(archive: zipfile.ZipFile, *, exact_names: tuple[str, ...] | None = None) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "archive contains duplicate member paths")
    if exact_names is not None and tuple(names) != exact_names:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate member set or order is invalid")
    for info in infos:
        member = PurePosixPath(info.filename)
        mode = (info.external_attr >> 16) & 0xFFFF
        if (
            not info.filename
            or info.is_dir()
            or member.is_absolute()
            or ".." in member.parts
            or "\\" in info.filename
            or (mode & 0o170000) == 0o120000
            or info.flag_bits & 0x1
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "archive contains an unsafe member")
    return infos


def inspect_application_archive(payload: bytes, expected_id: str | None = None, expected_contract: str | None = None) -> dict:
    if len(payload) > MAX_APPLICATION_BYTES:
        raise DeveloperError("APPLICATION_ARCHIVE_INVALID", "application archive exceeds the V0 byte limit")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = _safe_zip_infos(archive)
            if len(infos) > MAX_APPLICATION_MEMBERS:
                raise DeveloperError("APPLICATION_ARCHIVE_INVALID", "application archive has too many members")
            if sum(info.file_size for info in infos) > MAX_APPLICATION_EXPANDED_BYTES:
                raise DeveloperError("APPLICATION_ARCHIVE_INVALID", "application archive expands beyond the V0 limit")
            descriptors = [info for info in infos if info.filename == "capability.toml"]
            if len(descriptors) != 1:
                raise DeveloperError("APPLICATION_ARCHIVE_INVALID", "application archive requires one root capability.toml")
            descriptor_bytes = archive.read(descriptors[0])
    except DeveloperError as exc:
        raise DeveloperError("APPLICATION_ARCHIVE_INVALID", exc.detail) from exc
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise DeveloperError("APPLICATION_ARCHIVE_INVALID", "application archive is not a safe ZIP") from exc
    try:
        descriptor = tomllib.loads(descriptor_bytes.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise DeveloperError("APPLICATION_ARCHIVE_INVALID", "application descriptor is malformed") from exc
    application_id = descriptor.get("id")
    contract = descriptor.get("schema")
    if expected_id is not None and application_id != expected_id:
        raise DeveloperError("APPLICATION_DESCRIPTOR_MISMATCH", "application descriptor id differs from verification")
    if expected_contract is not None and contract != expected_contract:
        raise DeveloperError("APPLICATION_DESCRIPTOR_MISMATCH", "application descriptor schema differs from verification")
    return {
        "id": application_id,
        "contract": contract,
        "descriptor_sha256": digest_bytes(descriptor_bytes),
    }


def inspect_authoring_bundle(payload: bytes) -> dict:
    if len(payload) > MAX_TOOLCHAIN_BYTES:
        raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", "DevKit authoring bundle exceeds the V0 byte limit")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = _safe_zip_infos(archive)
            if len(infos) > MAX_TOOLCHAIN_MEMBERS:
                raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", "DevKit authoring bundle has too many members")
            if sum(info.file_size for info in infos) > MAX_TOOLCHAIN_EXPANDED_BYTES:
                raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", "DevKit authoring bundle expands beyond the V0 limit")
            manifest_bytes = archive.read("RELEASE-MANIFEST.json")
            manifest = json.loads(manifest_bytes)
            wheel_filename = manifest["wheel_filename"]
            wheel_member = archive.getinfo(f"wheel/{wheel_filename}")
            if wheel_member.file_size > MAX_TOOLCHAIN_WHEEL_BYTES:
                raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", "DevKit wheel expands beyond the V0 limit")
            wheel_bytes = archive.read(wheel_member)
    except DeveloperError as exc:
        raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", exc.detail) from exc
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError, RuntimeError) as exc:
        raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", "DevKit authoring bundle is invalid") from exc
    if manifest.get("schema") != "capy.devkit-authoring-bundle/v0":
        raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", "DevKit authoring bundle schema is unsupported")
    wheel_sha256 = digest_bytes(wheel_bytes)
    if manifest.get("wheel_sha256") != wheel_sha256:
        raise DeveloperError("TOOLCHAIN_INTEGRITY_FAILED", "DevKit authoring bundle contains the wrong wheel bytes")
    return {
        "manifest": manifest,
        "wheel_filename": wheel_filename,
        "wheel_sha256": wheel_sha256,
    }


def _repository_identity(repository_identity: str) -> dict:
    local = repository_identity.startswith("file:")
    return {
        "kind": "local" if local else "remote",
        "public_identity": None if local else repository_identity,
        "identity_sha256": digest_bytes(repository_identity.encode("utf-8")),
    }


def _portable_facts(stage_name: str, value: object) -> dict:
    allowed = _FACT_KEYS[stage_name]
    if not isinstance(value, dict) or set(value) != allowed:
        raise DeveloperError("VERIFICATION_INCOMPLETE", "verification contains nonportable stage facts")
    for key, item in value.items():
        if key in {"timed_out", "candidate_unchanged"} and not isinstance(item, bool):
            raise DeveloperError("VERIFICATION_INCOMPLETE", "verification stage boolean fact is malformed")
        if key in {"sha256", "sha256_a", "sha256_b"} and (
            not isinstance(item, str) or HEX64.fullmatch(item) is None
        ):
            raise DeveloperError("VERIFICATION_INCOMPLETE", "verification stage digest fact is malformed")
        if key in {"size_bytes", "size_a", "size_b"} and (
            not isinstance(item, int) or isinstance(item, bool) or item < 0
        ):
            raise DeveloperError("VERIFICATION_INCOMPLETE", "verification stage size fact is malformed")
    if value.get("timed_out") is True or value.get("candidate_unchanged") is False:
        raise DeveloperError("VERIFICATION_INCOMPLETE", "passed verification stage facts are contradictory")
    if stage_name == "package_compare" and (
        value["sha256_a"] != value["sha256_b"] or value["size_a"] != value["size_b"]
    ):
        raise DeveloperError("VERIFICATION_INCOMPLETE", "passed package comparison facts disagree")
    return value


def _identity_from_manifest(manifest: dict) -> dict:
    return {
        "schema": MANIFEST_SCHEMA,
        "project_id": manifest["project"]["project_id"],
        "application_id": manifest["application"]["id"],
        "source": {
            "repository": manifest["source"]["repository"],
            "commit": manifest["source"]["commit"],
            "tree": manifest["source"]["tree"],
            "base_commit": manifest["source"]["base_commit"],
        },
        "application_archive_sha256": manifest["application"]["archive"]["sha256"],
        "application_descriptor_sha256": manifest["application"]["descriptor_sha256"],
        "verification_receipt_sha256": manifest["verification"]["receipt"]["sha256"],
        "toolchain": {
            "release_binding_commit": manifest["toolchain"]["release_binding_commit"],
            "authoring_bundle_sha256": manifest["toolchain"]["authoring_bundle"]["sha256"],
            "wheel_sha256": manifest["toolchain"]["wheel_sha256"],
        },
    }


def _zip_bytes(member_payloads: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.comment = b""
        for name in MEMBERS:
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.extra = b""
            info.comment = b""
            archive.writestr(info, member_payloads[name])
    value = output.getvalue()
    if len(value) > MAX_BUNDLE_BYTES:
        raise DeveloperError("RELEASE_CANDIDATE_BUILD_FAILED", "release candidate exceeds the V0 byte limit")
    return value


def validate_bundle_bytes(payload: bytes) -> dict:
    if len(payload) > MAX_BUNDLE_BYTES:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate exceeds the V0 byte limit")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = _safe_zip_infos(archive, exact_names=MEMBERS)
            if archive.comment:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate ZIP comment is forbidden")
            for info in infos:
                mode = (info.external_attr >> 16) & 0xFFFF
                if (
                    info.date_time != FIXED_ZIP_TIME
                    or info.compress_type != zipfile.ZIP_STORED
                    or info.create_system != 3
                    or mode != 0o100644
                    or info.extra
                    or info.comment
                ):
                    raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate ZIP metadata is not canonical")
            members = {name: archive.read(name) for name in MEMBERS}
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate is not a valid ZIP") from exc
    if _zip_bytes(members) != payload:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate outer bytes are not canonical")
    try:
        manifest = json.loads(members[MEMBERS[0]])
        receipt = json.loads(members[MEMBERS[2]])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate JSON metadata is malformed") from exc
    if canonical_json(manifest) != members[MEMBERS[0]] or canonical_json(receipt) != members[MEMBERS[2]]:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate JSON metadata is not canonical")
    if manifest.get("schema") != MANIFEST_SCHEMA or receipt.get("schema") != RECEIPT_SCHEMA:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate metadata schema is unsupported")
    _require_keys(manifest, {"schema", "release_candidate_id", "identity_sha256", "project", "source", "application", "toolchain", "verification", "handoff", "verified_at"}, "manifest")
    _require_keys(manifest["project"], {"project_id"}, "manifest project")
    _require_keys(manifest["source"], {"repository", "commit", "tree", "base_commit"}, "manifest source")
    _require_keys(manifest["source"]["repository"], {"kind", "public_identity", "identity_sha256"}, "manifest repository")
    _require_keys(manifest["application"], {"id", "contract", "descriptor_sha256", "archive"}, "manifest application")
    _require_keys(manifest["application"]["archive"], {"member", "sha256", "size_bytes"}, "manifest application archive")
    _require_keys(manifest["toolchain"], {"release_binding_commit", "implementation_commit", "authoring_bundle", "wheel_filename", "wheel_sha256"}, "manifest toolchain")
    _require_keys(manifest["toolchain"]["authoring_bundle"], {"member", "sha256", "size_bytes"}, "manifest authoring bundle")
    _require_keys(manifest["verification"], {"verification_id", "receipt"}, "manifest verification")
    _require_keys(manifest["verification"]["receipt"], {"member", "sha256", "size_bytes"}, "manifest verification receipt")
    _require_keys(receipt, {"schema", "verification_id", "status", "classification", "session_id", "project_id", "application_id", "source", "toolchain", "stages", "application_archive", "verified_at"}, "verification receipt")
    _require_keys(receipt["source"], {"commit", "tree", "base_commit"}, "receipt source")
    _require_keys(receipt["toolchain"], {"contract", "lock_digest", "release_binding_commit", "implementation_commit", "authoring_bundle_sha256", "wheel_filename", "wheel_sha256"}, "receipt toolchain")
    _require_keys(receipt["application_archive"], {"sha256", "size_bytes"}, "receipt application archive")
    if not isinstance(receipt["stages"], list):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "verification receipt stages are invalid")
    stage_keys = {"name", "status", "exit_code", "stored_stdout_sha256", "stored_stdout_bytes", "stored_stderr_sha256", "stored_stderr_bytes", "stdout_truncated_bytes", "stderr_truncated_bytes", "facts"}
    for stage in receipt["stages"]:
        _require_keys(stage, stage_keys, "verification receipt stage")
    required_handoff = {
        "verification": "passed",
        "independent_acceptance": "required",
        "interaction_contract": "not_included",
        "state_migration": "not_assessed",
        "rollback": "not_assessed",
        "runtime_version_digest": "not_assigned",
        "secret_scan": "not_performed",
        "publication": "not_performed",
        "installation": "not_performed",
        "binding": "not_performed",
        "deployment": "not_performed",
        "publisher_signature": "not_present",
    }
    if manifest.get("handoff") != required_handoff:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate handoff claims were weakened or changed")
    repository_identity = manifest["source"]["repository"]
    if (
        repository_identity["kind"] not in {"local", "remote"}
        or not isinstance(repository_identity["identity_sha256"], str)
        or HEX64.fullmatch(repository_identity["identity_sha256"]) is None
        or (repository_identity["kind"] == "local" and repository_identity["public_identity"] is not None)
        or (
            repository_identity["kind"] == "remote"
            and (
                not isinstance(repository_identity["public_identity"], str)
                or not repository_identity["public_identity"].startswith("git://")
                or "@" in repository_identity["public_identity"]
                or digest_bytes(repository_identity["public_identity"].encode("utf-8")) != repository_identity["identity_sha256"]
            )
        )
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "safe repository identity is invalid")
    if (
        PROJECT_ID.fullmatch(str(manifest["project"]["project_id"])) is None
        or APPLICATION_ID.fullmatch(str(manifest["application"]["id"])) is None
        or VERIFICATION_ID.fullmatch(str(manifest["verification"]["verification_id"])) is None
        or SESSION_ID.fullmatch(str(receipt["session_id"])) is None
        or any(HEX40.fullmatch(str(manifest["source"][key])) is None for key in ("commit", "tree", "base_commit"))
        or HEX40.fullmatch(str(manifest["toolchain"]["release_binding_commit"])) is None
        or HEX40.fullmatch(str(manifest["toolchain"]["implementation_commit"])) is None
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate identity field syntax is invalid")
    bindings = (
        (manifest["application"]["archive"], MEMBERS[1]),
        (manifest["verification"]["receipt"], MEMBERS[2]),
        (manifest["toolchain"]["authoring_bundle"], MEMBERS[3]),
    )
    for binding, expected_name in bindings:
        member = binding.get("member")
        if member != expected_name:
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "manifest member path is invalid")
        member_bytes = members[member]
        if binding.get("sha256") != digest_bytes(member_bytes) or binding.get("size_bytes") != len(member_bytes):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "manifest member binding is invalid")
    application = inspect_application_archive(
        members[MEMBERS[1]], manifest["application"]["id"], manifest["application"]["contract"]
    )
    if application["descriptor_sha256"] != manifest["application"]["descriptor_sha256"]:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "application descriptor digest is invalid")
    toolchain = inspect_authoring_bundle(members[MEMBERS[3]])
    toolchain_manifest = toolchain["manifest"]
    if (
        toolchain["wheel_filename"] != manifest["toolchain"]["wheel_filename"]
        or toolchain["wheel_sha256"] != manifest["toolchain"]["wheel_sha256"]
        or toolchain_manifest.get("contract") != manifest["application"]["contract"]
        or toolchain_manifest.get("source_commit") != manifest["toolchain"]["implementation_commit"]
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate toolchain identity is inconsistent")
    if (
        receipt.get("verification_id") != manifest["verification"]["verification_id"]
        or receipt.get("project_id") != manifest["project"]["project_id"]
        or receipt.get("application_id") != manifest["application"]["id"]
        or receipt.get("source") != {
            "commit": manifest["source"]["commit"],
            "tree": manifest["source"]["tree"],
            "base_commit": manifest["source"]["base_commit"],
        }
        or receipt.get("application_archive") != {
            "sha256": manifest["application"]["archive"]["sha256"],
            "size_bytes": manifest["application"]["archive"]["size_bytes"],
        }
        or receipt.get("status") != "PASSED"
        or receipt.get("classification") != "VERIFIED"
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "verification receipt disagrees with the manifest")
    receipt_toolchain = receipt.get("toolchain", {})
    if (
        receipt_toolchain.get("contract") != manifest["application"]["contract"]
        or receipt_toolchain.get("release_binding_commit") != manifest["toolchain"]["release_binding_commit"]
        or receipt_toolchain.get("implementation_commit") != manifest["toolchain"]["implementation_commit"]
        or receipt_toolchain.get("authoring_bundle_sha256") != manifest["toolchain"]["authoring_bundle"]["sha256"]
        or receipt_toolchain.get("wheel_filename") != manifest["toolchain"]["wheel_filename"]
        or receipt_toolchain.get("wheel_sha256") != manifest["toolchain"]["wheel_sha256"]
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "verification receipt toolchain identity disagrees")
    if [stage.get("name") for stage in receipt.get("stages", [])] != list(STAGES) or any(
        stage.get("status") != "PASSED" for stage in receipt.get("stages", [])
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "verification receipt stage sequence is invalid")
    for stage in receipt["stages"]:
        exit_code = stage["exit_code"]
        if (
            not isinstance(stage["stored_stdout_sha256"], str)
            or HEX64.fullmatch(stage["stored_stdout_sha256"]) is None
            or not isinstance(stage["stored_stderr_sha256"], str)
            or HEX64.fullmatch(stage["stored_stderr_sha256"]) is None
            or (
                stage["name"] in _PROCESS_STAGES
                and (not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0)
            )
            or (stage["name"] not in _PROCESS_STAGES and exit_code is not None)
            or any(
                not isinstance(stage[key], int) or isinstance(stage[key], bool) or stage[key] < 0
                for key in ("stored_stdout_bytes", "stored_stderr_bytes", "stdout_truncated_bytes", "stderr_truncated_bytes")
            )
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "verification receipt output facts are invalid")
        try:
            _portable_facts(stage["name"], stage["facts"])
        except DeveloperError as exc:
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", exc.detail) from exc
    stage_facts = {stage["name"]: stage["facts"] for stage in receipt["stages"]}
    compared = stage_facts["package_compare"]
    preserved = stage_facts["archive_preserve"]
    expected_archive = receipt["application_archive"]
    if (
        preserved != expected_archive
        or compared["sha256_a"] != expected_archive["sha256"]
        or compared["size_a"] != expected_archive["size_bytes"]
    ):
        raise DeveloperError(
            "RELEASE_CANDIDATE_INTEGRITY_FAILED",
            "passed package and preservation facts disagree with the verified archive",
        )
    if receipt["verified_at"] != manifest["verified_at"]:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "verification terminal time disagrees")
    identity = _identity_from_manifest(manifest)
    identity_sha256 = digest_bytes(canonical_json(identity))
    candidate_id = "rc_" + identity_sha256[:32]
    if manifest.get("identity_sha256") != identity_sha256 or manifest.get("release_candidate_id") != candidate_id:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate identity is invalid")
    return {
        "manifest": manifest,
        "receipt": receipt,
        "identity_sha256": identity_sha256,
        "release_candidate_id": candidate_id,
        "manifest_sha256": digest_bytes(members[MEMBERS[0]]),
        "bundle_sha256": digest_bytes(payload),
        "bundle_size_bytes": len(payload),
    }


class ReleaseCandidateService:
    def __init__(self, core):
        self.core = core
        self.config = core.config
        self.db = core.db
        self.toolchains = core.toolchains

    def create(self, verification_id: str) -> dict:
        if not isinstance(verification_id, str) or VERIFICATION_ID.fullmatch(verification_id) is None:
            raise DeveloperError("VERIFICATION_ID_INVALID", "verification_id is invalid")
        with self.db.connect() as db:
            verification = db.execute(
                "SELECT session_id FROM verification_attempts WHERE verification_id=?", (verification_id,)
            ).fetchone()
        if verification is None:
            raise DeveloperError("VERIFICATION_NOT_FOUND", "verification does not exist")
        with ExitStack() as locks:
            locks.enter_context(exclusive_lock(
                self.config.verification_lock(verification["session_id"]), 0,
                busy_code="RELEASE_CANDIDATE_BUSY",
                busy_detail="the verification session lifecycle is currently active",
            ))
            context = self._preflight(verification_id)
            candidate_id = context["release_candidate_id"]
            locks.enter_context(exclusive_lock(
                self.config.release_candidate_lock(candidate_id), 0,
                busy_code="RELEASE_CANDIDATE_BUSY",
                busy_detail="release candidate construction is already active",
            ))
            with self.db.connect() as db:
                by_verification = db.execute(
                    "SELECT * FROM release_candidates WHERE verification_id=?", (verification_id,)
                ).fetchone()
                by_identity = db.execute(
                    "SELECT * FROM release_candidates WHERE release_candidate_id=?", (candidate_id,)
                ).fetchone()
            existing = by_verification or by_identity
            if existing and existing["release_candidate_id"] != candidate_id:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "verification is bound to a conflicting candidate identity")
            if existing and (
                existing["verification_id"] != verification_id
                or existing["identity_sha256"] != context["identity_sha256"]
                or existing["manifest_sha256"] != context["manifest_sha256"]
            ):
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate identity collision detected")
            if existing and existing["status"] == "READY":
                return self.inspect(candidate_id)
            self._allocate(context, dict(existing) if existing else None)
            attempt_root = safe_resolve(
                self.config.release_candidate_temporary_root / candidate_id,
                root=self.config.release_candidate_temporary_root,
            )
            cleanup_failure = None
            try:
                self._prepare_attempt_root(attempt_root, candidate_id)
                payloads = {
                    MEMBERS[0]: context["manifest_bytes"],
                    MEMBERS[1]: context["application_bytes"],
                    MEMBERS[2]: context["receipt_bytes"],
                    MEMBERS[3]: context["toolchain_bytes"],
                }
                bundle_a = _zip_bytes(payloads)
                bundle_b = _zip_bytes(payloads)
                if bundle_a != bundle_b:
                    raise DeveloperError("RELEASE_CANDIDATE_NOT_REPRODUCIBLE", "two candidate builds were not byte-identical")
                (attempt_root / "a.capyrc").write_bytes(bundle_a)
                (attempt_root / "b.capyrc").write_bytes(bundle_b)
                validation = validate_bundle_bytes(bundle_a)
                destination = self._preserve(bundle_a, validation["bundle_sha256"])
                durable = destination.read_bytes()
                validate_bundle_bytes(durable)
                self._ready(context, validation, destination)
            except DeveloperError as exc:
                self._failed(candidate_id, exc.code, exc.detail)
            except Exception as exc:
                self._failed(candidate_id, "RELEASE_CANDIDATE_BUILD_FAILED", type(exc).__name__)
            finally:
                try:
                    self._cleanup_attempt_root(attempt_root, candidate_id)
                except DeveloperError as exc:
                    cleanup_failure = exc
                    self._failed(candidate_id, exc.code, exc.detail, classification="RELEASE_CANDIDATE_CLEANUP_FAILED")
            result = self.inspect(candidate_id)
            if cleanup_failure is not None:
                return result
            return result

    def inspect(self, release_candidate_id: str) -> dict:
        if not isinstance(release_candidate_id, str) or RELEASE_CANDIDATE_ID.fullmatch(release_candidate_id) is None:
            raise DeveloperError("RELEASE_CANDIDATE_ID_INVALID", "release_candidate_id is invalid")
        with self.db.connect() as db:
            row = db.execute(
                "SELECT * FROM release_candidates WHERE release_candidate_id=?", (release_candidate_id,)
            ).fetchone()
        if row is None:
            raise DeveloperError("RELEASE_CANDIDATE_NOT_FOUND", "release candidate does not exist")
        candidate = dict(row)
        current_state = "UNAVAILABLE"
        discrepancy = None
        if candidate["status"] == "READY" and candidate.get("bundle_path"):
            try:
                bundle_path = safe_resolve(
                    Path(candidate["bundle_path"]), root=self.config.release_candidates_root
                )
            except (DeveloperError, OSError, ValueError):
                bundle_path = Path(candidate["bundle_path"])
                current_state = "BUNDLE_INVALID"
                discrepancy = {"code": "RELEASE_CANDIDATE_INTEGRITY_FAILED", "detail": "durable candidate path escapes its managed root"}
            if discrepancy is not None:
                return self._result(candidate, current_state, discrepancy)
            if not bundle_path.is_file():
                current_state = "MISSING"
                discrepancy = {"code": "RELEASE_CANDIDATE_INTEGRITY_FAILED", "detail": "durable candidate bundle is missing"}
            elif sha256_file(bundle_path) != candidate["bundle_sha256"] or bundle_path.stat().st_size != candidate["bundle_size_bytes"]:
                current_state = "DIGEST_MISMATCH"
                discrepancy = {"code": "RELEASE_CANDIDATE_INTEGRITY_FAILED", "detail": "durable candidate bundle digest or size differs"}
            else:
                try:
                    validation = validate_bundle_bytes(bundle_path.read_bytes())
                    if validation["release_candidate_id"] != release_candidate_id:
                        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "durable candidate identity differs")
                    current_state = "AVAILABLE"
                except (DeveloperError, OSError) as exc:
                    current_state = "BUNDLE_INVALID"
                    discrepancy = {"code": "RELEASE_CANDIDATE_INTEGRITY_FAILED", "detail": str(exc)}
        return self._result(candidate, current_state, discrepancy)

    def _preflight(self, verification_id: str) -> dict:
        with self.db.connect() as db:
            attempt = db.execute(
                "SELECT * FROM verification_attempts WHERE verification_id=?", (verification_id,)
            ).fetchone()
            if attempt is None:
                raise DeveloperError("VERIFICATION_NOT_FOUND", "verification does not exist")
            attempt = dict(attempt)
            if attempt["status"] != "PASSED" or attempt["classification"] != "VERIFIED":
                raise DeveloperError("VERIFICATION_NOT_PASSED", "release candidate requires a PASSED VERIFIED verification")
            stages = [dict(row) for row in db.execute(
                "SELECT * FROM verification_stages WHERE verification_id=? ORDER BY stage_order", (verification_id,)
            )]
            session = db.execute("SELECT * FROM sessions WHERE session_id=?", (attempt["session_id"],)).fetchone()
            if session is None:
                raise DeveloperError("DEVELOPMENT_SESSION_INELIGIBLE", "verification session is unavailable")
            session = dict(session)
            project = db.execute("SELECT * FROM projects WHERE project_id=?", (session["project_id"],)).fetchone()
            registered = db.execute(
                "SELECT 1 FROM project_applications WHERE project_id=? AND application_id=?",
                (session["project_id"], attempt["application_id"]),
            ).fetchone()
        if session["status"] not in {"READY", "COMPLETED"} or session.get("terminal_disposition") == "CANCELLED":
            raise DeveloperError("DEVELOPMENT_SESSION_INELIGIBLE", "verification session is not eligible for candidate creation")
        if project is None or registered is None:
            raise DeveloperError("DEVELOPMENT_SESSION_INELIGIBLE", "verification project or application registration is unavailable")
        if len(stages) != len(STAGES) or [row["stage_name"] for row in stages] != list(STAGES) or any(
            row["status"] != "PASSED" for row in stages
        ):
            raise DeveloperError("VERIFICATION_INCOMPLETE", "verification does not contain the complete passed stage sequence")
        try:
            archive_path = safe_resolve(
                Path(attempt["archive_path"] or ""), root=self.config.verification_artifacts_root
            )
        except (DeveloperError, OSError, ValueError) as exc:
            raise DeveloperError("VERIFICATION_ARCHIVE_UNAVAILABLE", "verified application archive path is outside its managed store") from exc
        if not archive_path.is_file():
            raise DeveloperError("VERIFICATION_ARCHIVE_UNAVAILABLE", "verified application archive is unavailable")
        application_bytes = archive_path.read_bytes()
        if digest_bytes(application_bytes) != attempt["archive_sha256"] or len(application_bytes) != attempt["archive_size_bytes"]:
            raise DeveloperError("VERIFICATION_ARCHIVE_INTEGRITY_FAILED", "verified application archive differs from its record")
        application = inspect_application_archive(application_bytes, attempt["application_id"], attempt["contract"])
        try:
            repository = safe_resolve(
                self.config.repositories_root / f"{session['project_id']}.git", root=self.config.repositories_root, must_exist=True
            )
        except (OSError, ValueError) as exc:
            raise DeveloperError("CANDIDATE_SOURCE_UNAVAILABLE", "managed canonical Git repository is unavailable") from exc
        commit = run_git(["--git-dir", str(repository), "rev-parse", f"{attempt['candidate_commit']}^{{commit}}"], check=False)
        tree = run_git(["--git-dir", str(repository), "rev-parse", f"{attempt['candidate_commit']}^{{tree}}"], check=False)
        base = run_git(["--git-dir", str(repository), "rev-parse", f"{attempt['base_commit']}^{{commit}}"], check=False)
        common = run_git(["--git-dir", str(repository), "merge-base", attempt["base_commit"], attempt["candidate_commit"]], check=False)
        if not commit or not base:
            raise DeveloperError("CANDIDATE_SOURCE_UNAVAILABLE", "verified Git objects are unavailable")
        if commit != attempt["candidate_commit"] or tree != attempt["candidate_tree"] or common != attempt["base_commit"]:
            raise DeveloperError("CANDIDATE_SOURCE_IDENTITY_MISMATCH", "verified Git source identity no longer matches")
        bundle, toolchain_manifest = self.toolchains.resolve_recorded(
            contract=attempt["contract"],
            release_binding_commit=attempt["release_binding_commit"],
            authoring_bundle_sha256=attempt["authoring_bundle_sha256"],
            wheel_sha256=attempt["wheel_sha256"],
        )
        toolchain_bytes = bundle.read_bytes()
        inspected_toolchain = inspect_authoring_bundle(toolchain_bytes)
        receipt = self._receipt(attempt, session, stages, toolchain_manifest)
        receipt_bytes = canonical_json(receipt)
        if len(receipt_bytes) > MAX_RECEIPT_BYTES:
            raise DeveloperError("VERIFICATION_INCOMPLETE", "portable verification receipt exceeds the V0 limit")
        repository_identity = _repository_identity(project["repository_identity"])
        identity_seed = {
            "schema": MANIFEST_SCHEMA,
            "project_id": session["project_id"],
            "application_id": attempt["application_id"],
            "source": {
                "repository": repository_identity,
                "commit": attempt["candidate_commit"],
                "tree": attempt["candidate_tree"],
                "base_commit": attempt["base_commit"],
            },
            "application_archive_sha256": attempt["archive_sha256"],
            "application_descriptor_sha256": application["descriptor_sha256"],
            "verification_receipt_sha256": digest_bytes(receipt_bytes),
            "toolchain": {
                "release_binding_commit": attempt["release_binding_commit"],
                "authoring_bundle_sha256": attempt["authoring_bundle_sha256"],
                "wheel_sha256": attempt["wheel_sha256"],
            },
        }
        identity_sha256 = digest_bytes(canonical_json(identity_seed))
        candidate_id = "rc_" + identity_sha256[:32]
        manifest = self._manifest(
            candidate_id, identity_sha256, attempt, session, repository_identity,
            application, receipt_bytes, toolchain_bytes, toolchain_manifest,
            inspected_toolchain["wheel_filename"],
        )
        manifest_bytes = canonical_json(manifest)
        return {
            "attempt": attempt,
            "session": session,
            "project": dict(project),
            "application": application,
            "application_bytes": application_bytes,
            "toolchain_bytes": toolchain_bytes,
            "toolchain_manifest": toolchain_manifest,
            "receipt_bytes": receipt_bytes,
            "receipt_sha256": digest_bytes(receipt_bytes),
            "repository_identity": repository_identity,
            "identity_sha256": identity_sha256,
            "release_candidate_id": candidate_id,
            "manifest": manifest,
            "manifest_bytes": manifest_bytes,
            "manifest_sha256": digest_bytes(manifest_bytes),
        }

    def _receipt(self, attempt: dict, session: dict, stages: list[dict], toolchain_manifest: dict) -> dict:
        portable_stages = []
        for row in stages:
            try:
                facts = json.loads(row["facts"])
            except json.JSONDecodeError as exc:
                raise DeveloperError("VERIFICATION_INCOMPLETE", "verification stage facts are malformed") from exc
            facts = _portable_facts(row["stage_name"], facts)
            stdout = row["stdout_text"].encode("utf-8")
            stderr = row["stderr_text"].encode("utf-8")
            portable_stages.append({
                "name": row["stage_name"], "status": row["status"], "exit_code": row["exit_code"],
                "stored_stdout_sha256": digest_bytes(stdout), "stored_stdout_bytes": len(stdout),
                "stored_stderr_sha256": digest_bytes(stderr), "stored_stderr_bytes": len(stderr),
                "stdout_truncated_bytes": row["stdout_truncated_bytes"],
                "stderr_truncated_bytes": row["stderr_truncated_bytes"], "facts": facts,
            })
        stage_facts = {stage["name"]: stage["facts"] for stage in portable_stages}
        compared = stage_facts["package_compare"]
        preserved = stage_facts["archive_preserve"]
        expected_archive = {"sha256": attempt["archive_sha256"], "size_bytes": attempt["archive_size_bytes"]}
        if (
            preserved != expected_archive
            or compared["sha256_a"] != expected_archive["sha256"]
            or compared["size_a"] != expected_archive["size_bytes"]
        ):
            raise DeveloperError(
                "VERIFICATION_INCOMPLETE",
                "passed package and preservation facts disagree with the verified archive",
            )
        return {
            "schema": RECEIPT_SCHEMA,
            "verification_id": attempt["verification_id"],
            "status": "PASSED", "classification": "VERIFIED",
            "session_id": attempt["session_id"], "project_id": session["project_id"],
            "application_id": attempt["application_id"],
            "source": {"commit": attempt["candidate_commit"], "tree": attempt["candidate_tree"], "base_commit": attempt["base_commit"]},
            "toolchain": {
                "contract": attempt["contract"], "lock_digest": attempt["lock_digest"],
                "release_binding_commit": attempt["release_binding_commit"],
                "implementation_commit": toolchain_manifest["source_commit"],
                "authoring_bundle_sha256": attempt["authoring_bundle_sha256"],
                "wheel_filename": toolchain_manifest["wheel_filename"], "wheel_sha256": attempt["wheel_sha256"],
            },
            "stages": portable_stages,
            "application_archive": {"sha256": attempt["archive_sha256"], "size_bytes": attempt["archive_size_bytes"]},
            "verified_at": attempt["terminal_at"],
        }

    def _manifest(
        self, candidate_id: str, identity_sha256: str, attempt: dict, session: dict,
        repository_identity: dict, application: dict, receipt_bytes: bytes,
        toolchain_bytes: bytes, toolchain_manifest: dict, wheel_filename: str,
    ) -> dict:
        return {
            "schema": MANIFEST_SCHEMA, "release_candidate_id": candidate_id,
            "identity_sha256": identity_sha256, "project": {"project_id": session["project_id"]},
            "source": {"repository": repository_identity, "commit": attempt["candidate_commit"], "tree": attempt["candidate_tree"], "base_commit": attempt["base_commit"]},
            "application": {
                "id": attempt["application_id"], "contract": attempt["contract"],
                "descriptor_sha256": application["descriptor_sha256"],
                "archive": {"member": MEMBERS[1], "sha256": attempt["archive_sha256"], "size_bytes": attempt["archive_size_bytes"]},
            },
            "toolchain": {
                "release_binding_commit": attempt["release_binding_commit"],
                "implementation_commit": toolchain_manifest["source_commit"],
                "authoring_bundle": {"member": MEMBERS[3], "sha256": digest_bytes(toolchain_bytes), "size_bytes": len(toolchain_bytes)},
                "wheel_filename": wheel_filename, "wheel_sha256": attempt["wheel_sha256"],
            },
            "verification": {"verification_id": attempt["verification_id"], "receipt": {"member": MEMBERS[2], "sha256": digest_bytes(receipt_bytes), "size_bytes": len(receipt_bytes)}},
            "handoff": {
                "verification": "passed", "independent_acceptance": "required", "interaction_contract": "not_included",
                "state_migration": "not_assessed", "rollback": "not_assessed", "runtime_version_digest": "not_assigned",
                "secret_scan": "not_performed", "publication": "not_performed", "installation": "not_performed",
                "binding": "not_performed", "deployment": "not_performed", "publisher_signature": "not_present",
            },
            "verified_at": attempt["terminal_at"],
        }

    def _allocate(self, context: dict, existing: dict | None) -> None:
        now = utc_now()
        attempt = context["attempt"]
        session = context["session"]
        repo = context["repository_identity"]
        toolchain = context["toolchain_manifest"]
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current_session = db.execute(
                "SELECT status,terminal_disposition FROM sessions WHERE session_id=?", (session["session_id"],)
            ).fetchone()
            if (
                current_session is None
                or current_session["status"] not in {"READY", "COMPLETED"}
                or current_session["terminal_disposition"] == "CANCELLED"
            ):
                raise DeveloperError(
                    "DEVELOPMENT_SESSION_INELIGIBLE",
                    "verification session became ineligible before candidate allocation",
                )
            if existing:
                if existing["status"] == "BUILDING":
                    db.execute(
                        "UPDATE release_candidates SET status='INTERRUPTED',classification='RELEASE_CANDIDATE_PROCESS_INTERRUPTED',updated_at=?,terminal_at=? WHERE release_candidate_id=?",
                        (now, now, context["release_candidate_id"]),
                    )
                    self.db.event(db, session["session_id"], "RELEASE_CANDIDATE_INTERRUPTED", {"release_candidate_id": context["release_candidate_id"]})
                db.execute(
                    """UPDATE release_candidates SET status='BUILDING',classification=NULL,attempt_count=attempt_count+1,
                       started_at=?,updated_at=?,terminal_at=NULL,error_code=NULL,error_detail=NULL WHERE release_candidate_id=?""",
                    (now, now, context["release_candidate_id"]),
                )
                event = "RELEASE_CANDIDATE_RESUMED"
            else:
                db.execute(
                    """INSERT INTO release_candidates(
                       release_candidate_id,verification_id,session_id,project_id,application_id,
                       candidate_commit,candidate_tree,base_commit,identity_sha256,
                       repository_kind,repository_public_identity,repository_identity_sha256,
                       application_archive_sha256,application_archive_size_bytes,descriptor_sha256,
                       toolchain_contract,toolchain_release_binding_commit,toolchain_implementation_commit,
                       toolchain_authoring_bundle_sha256,toolchain_wheel_filename,toolchain_wheel_sha256,
                       verification_receipt_sha256,manifest_json,manifest_sha256,
                       bundle_sha256,bundle_size_bytes,bundle_path,status,classification,attempt_count,
                       started_at,updated_at,terminal_at,error_code,error_detail
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        context["release_candidate_id"], attempt["verification_id"], session["session_id"], session["project_id"], attempt["application_id"],
                        attempt["candidate_commit"], attempt["candidate_tree"], attempt["base_commit"], context["identity_sha256"],
                        repo["kind"], repo["public_identity"], repo["identity_sha256"], attempt["archive_sha256"], attempt["archive_size_bytes"],
                        context["application"]["descriptor_sha256"], attempt["contract"], attempt["release_binding_commit"], toolchain["source_commit"],
                        attempt["authoring_bundle_sha256"], toolchain["wheel_filename"], attempt["wheel_sha256"], context["receipt_sha256"],
                        context["manifest_bytes"].decode("utf-8"), context["manifest_sha256"], None, None, None,
                        "BUILDING", None, 1, now, now, None, None, None,
                    ),
                )
                event = "RELEASE_CANDIDATE_STARTED"
            self.db.event(db, session["session_id"], event, {"release_candidate_id": context["release_candidate_id"], "verification_id": attempt["verification_id"]})

    def _prepare_attempt_root(self, root: Path, candidate_id: str) -> None:
        if root.exists() or root.is_symlink():
            marker = root / ".capy-release-candidate-owner"
            if root.is_dir() and not root.is_symlink() and not marker.exists() and not any(root.iterdir()):
                root.rmdir()
            else:
                self._cleanup_attempt_root(root, candidate_id)
        root.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=f".{candidate_id}-", dir=root.parent))
        marker = staging / ".capy-release-candidate-owner"
        try:
            marker.write_text(candidate_id, encoding="utf-8")
            staging.replace(root)
        finally:
            if staging.exists():
                self._cleanup_attempt_root(staging, candidate_id)

    def _cleanup_attempt_root(self, root: Path, candidate_id: str) -> None:
        if not root.exists() and not root.is_symlink():
            return
        marker = root / ".capy-release-candidate-owner"
        if root.is_symlink() or not marker.is_file() or marker.is_symlink():
            raise DeveloperError("RELEASE_CANDIDATE_CLEANUP_FAILED", "candidate attempt path ownership is invalid")
        try:
            owner = marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise DeveloperError("RELEASE_CANDIDATE_CLEANUP_FAILED", "candidate attempt owner marker is unreadable") from exc
        if owner != candidate_id:
            raise DeveloperError("RELEASE_CANDIDATE_CLEANUP_FAILED", "candidate attempt path belongs to another operation")
        shutil.rmtree(root)
        if root.exists():
            raise DeveloperError("RELEASE_CANDIDATE_CLEANUP_FAILED", "candidate attempt path remains")

    def _preserve(self, payload: bytes, digest: str) -> Path:
        destination = safe_resolve(
            self.config.release_candidates_root / digest / "candidate.capyrc",
            root=self.config.release_candidates_root,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if sha256_file(destination) != digest or destination.read_bytes() != payload:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "content-addressed candidate path contains conflicting bytes")
            return destination
        descriptor, temporary_name = tempfile.mkstemp(prefix="candidate-", suffix=".tmp", dir=destination.parent)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_bytes(payload)
            if sha256_file(temporary) != digest:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "preserved candidate copy failed digest verification")
            try:
                os.link(temporary, destination)
            except FileExistsError:
                pass
            if sha256_file(destination) != digest or destination.read_bytes() != payload:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "content-addressed candidate path contains conflicting bytes")
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def _ready(self, context: dict, validation: dict, destination: Path) -> None:
        now = utc_now()
        candidate_id = context["release_candidate_id"]
        with self.db.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM release_candidate_members WHERE release_candidate_id=?", (candidate_id,))
            for member, payload in (
                (MEMBERS[1], context["application_bytes"]),
                (MEMBERS[2], context["receipt_bytes"]),
                (MEMBERS[3], context["toolchain_bytes"]),
            ):
                db.execute("INSERT INTO release_candidate_members VALUES (?,?,?,?)", (candidate_id, member, digest_bytes(payload), len(payload)))
            db.execute(
                """UPDATE release_candidates SET bundle_sha256=?,bundle_size_bytes=?,bundle_path=?,status='READY',
                   classification='RELEASE_CANDIDATE_CREATED',updated_at=?,terminal_at=?,error_code=NULL,error_detail=NULL
                   WHERE release_candidate_id=?""",
                (validation["bundle_sha256"], validation["bundle_size_bytes"], str(destination), now, now, candidate_id),
            )
            self.db.event(db, context["session"]["session_id"], "RELEASE_CANDIDATE_READY", {"release_candidate_id": candidate_id, "bundle_sha256": validation["bundle_sha256"]})

    def _failed(self, candidate_id: str, code: str, detail: str, *, classification: str = "RELEASE_CANDIDATE_BUILD_FAILED") -> None:
        now = utc_now()
        with self.db.connect() as db:
            row = db.execute("SELECT session_id,status FROM release_candidates WHERE release_candidate_id=?", (candidate_id,)).fetchone()
            if row is None:
                return
            db.execute(
                "UPDATE release_candidates SET status='FAILED',classification=?,updated_at=?,terminal_at=?,error_code=?,error_detail=? WHERE release_candidate_id=?",
                (classification, now, now, code, detail[:2000], candidate_id),
            )
            self.db.event(db, row["session_id"], "RELEASE_CANDIDATE_FAILED", {"release_candidate_id": candidate_id, "code": code})

    def _result(self, candidate: dict, current_state: str, discrepancy: dict | None) -> dict:
        available = candidate["status"] == "READY" and current_state == "AVAILABLE"
        return {
            "schema": RESULT_SCHEMA, "ok": available, "status": candidate["status"],
            "classification": candidate["classification"], "release_candidate_id": candidate["release_candidate_id"],
            "verification_id": candidate["verification_id"], "session_id": candidate["session_id"],
            "project_id": candidate["project_id"], "application_id": candidate["application_id"],
            "identity_sha256": candidate["identity_sha256"],
            "source": {"commit": candidate["candidate_commit"], "tree": candidate["candidate_tree"], "base_commit": candidate["base_commit"]},
            "application": {"archive_sha256": candidate["application_archive_sha256"], "descriptor_sha256": candidate["descriptor_sha256"]},
            "toolchain": {"contract": candidate["toolchain_contract"], "release_binding_commit": candidate["toolchain_release_binding_commit"], "authoring_bundle_sha256": candidate["toolchain_authoring_bundle_sha256"], "wheel_sha256": candidate["toolchain_wheel_sha256"]},
            "verification_receipt_sha256": candidate["verification_receipt_sha256"], "manifest_sha256": candidate["manifest_sha256"],
            "bundle": {
                "format": "zip", "suffix": ".capyrc", "sha256": candidate["bundle_sha256"],
                "size_bytes": candidate["bundle_size_bytes"],
                "path_uri": path_uri(Path(candidate["bundle_path"])) if candidate.get("bundle_path") else None,
                "byte_identical_builds": 2, "available": available, "current_state": current_state,
            },
            "handoff": {"independent_acceptance": "required", "publication": "not_performed", "installation": "not_performed", "deployment": "not_performed"},
            "created_at": candidate["started_at"], "terminal_at": candidate["terminal_at"],
            "attempt_count": candidate["attempt_count"], "discrepancy": discrepancy,
            "error": None if not candidate["error_code"] else {"code": candidate["error_code"], "detail": candidate["error_detail"]},
        }
