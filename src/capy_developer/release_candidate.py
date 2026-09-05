from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import tempfile
import tomllib
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from .errors import DeveloperError
from .git import run_git
from .toolchain import (
    ACCEPTED_BUNDLE_SHA256, ACCEPTED_DEVKIT_MAIN, ACCEPTED_SOURCE_COMMIT,
    ACCEPTED_WHEEL_SHA256, sha256_file,
)
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
    read_regular_bytes,
    safe_resolve,
    utc_now,
)
from .verification import PIPELINE_V0, PIPELINE_V1, STAGES, STAGES_V1


RESULT_SCHEMA = "capy.development-release-candidate-result/v0"
RESULT_SCHEMA_V1 = "capy.development-release-candidate-result/v1"
MANIFEST_SCHEMA = "capy.application-release-candidate/v0"
MANIFEST_SCHEMA_V1 = "capy.application-release-candidate/v1"
RECEIPT_SCHEMA = "capy.development-verification-receipt/v0"
RECEIPT_SCHEMA_V1 = "capy.development-verification-receipt/v1"
MEMBERS = (
    "RELEASE-CANDIDATE.json",
    "application/application.zip",
    "evidence/verification.json",
    "toolchain/authoring-bundle.zip",
)
MEMBERS_V1 = (
    "RELEASE-CANDIDATE.json",
    "application/application.zip",
    "application/interaction.json",
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

_PROCESS_STAGES = {"toolchain_install", "check", "interaction_check", "test", "conform", "pack_a", "pack_b", "interaction_preserve"}

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
    "interaction_check": {"timed_out", "candidate_unchanged"},
    "interaction_preserve": {"timed_out", "candidate_unchanged", "source_sha256", "canonical_sha256", "canonical_size_bytes"},
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


def _read_candidate_bytes(path: Path) -> bytes:
    try:
        return read_regular_bytes(path)
    except OSError as exc:
        raise DeveloperError(
            "RELEASE_CANDIDATE_INTEGRITY_FAILED",
            "content-addressed candidate path is not a stable regular file",
        ) from exc


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
            interactions = [info for info in infos if info.filename == "interaction.json"]
            if len(interactions) > 1:
                raise DeveloperError("APPLICATION_ARCHIVE_INVALID", "application archive has duplicate root interaction.json")
            interaction_bytes = archive.read(interactions[0]) if interactions else None
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
        "descriptor": descriptor,
        "interaction_bytes": interaction_bytes,
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
    if manifest.get("schema") not in {"capy.devkit-authoring-bundle/v0", "capy.devkit-authoring-bundle/v1"}:
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
        if key in {"sha256", "sha256_a", "sha256_b", "source_sha256", "canonical_sha256"} and (
            not isinstance(item, str) or HEX64.fullmatch(item) is None
        ):
            raise DeveloperError("VERIFICATION_INCOMPLETE", "verification stage digest fact is malformed")
        if key in {"size_bytes", "size_a", "size_b", "canonical_size_bytes"} and (
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
    if manifest.get("schema") == MANIFEST_SCHEMA_V1:
        interaction = manifest["application"]["interaction"]
        return {
            "schema": MANIFEST_SCHEMA_V1,
            "project_id": manifest["project"]["project_id"],
            "application_id": manifest["application"]["id"],
            "source": manifest["source"],
            "application_archive_sha256": manifest["application"]["archive"]["sha256"],
            "application_descriptor_sha256": manifest["application"]["descriptor_sha256"],
            "interaction": {
                "schema": interaction["schema"],
                "source_sha256": interaction["source_sha256"],
                "canonical_sha256": interaction["sha256"],
                "operation_id": interaction["operation_id"],
            },
            "verification_receipt_sha256": manifest["verification"]["receipt"]["sha256"],
            "toolchain": {
                "release_binding_commit": manifest["toolchain"]["release_binding_commit"],
                "authoring_bundle_sha256": manifest["toolchain"]["authoring_bundle"]["sha256"],
                "wheel_sha256": manifest["toolchain"]["wheel_sha256"],
                "interaction_contract": manifest["toolchain"]["interaction_contract"],
            },
        }
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


def _zip_bytes(member_payloads: dict[str, bytes], members: tuple[str, ...] = MEMBERS) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.comment = b""
        for name in members:
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


def _validate_v0_bundle_bytes(payload: bytes) -> dict:
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


def _interaction_leaves(schema: dict, prefix: tuple[str, ...] = (), required: bool = True) -> dict[str, tuple[dict, bool]]:
    if not isinstance(schema, dict):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction input schema is invalid")
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False or not isinstance(schema.get("properties", {}), dict):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction input object is not closed")
        required_names = schema.get("required", [])
        properties = schema.get("properties", {})
        if (
            not isinstance(required_names, list)
            or any(not isinstance(name, str) for name in required_names)
            or len(set(required_names)) != len(required_names)
            or not set(required_names) <= set(properties)
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction requiredness is invalid")
        leaves: dict[str, tuple[dict, bool]] = {}
        for name, child in properties.items():
            if re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction input field name is invalid")
            leaves.update(_interaction_leaves(child, (*prefix, name), required and name in required_names))
        return leaves
    if schema.get("type") not in {"string", "integer", "number", "boolean"} or not prefix:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction input leaf is unsupported")
    return {".".join(prefix): (schema, required)}


def _schema_accepts(value: object, schema: dict) -> bool:
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        return False
    if kind == "string":
        return (
            isinstance(value, str)
            and len(value) >= schema.get("minLength", 0)
            and len(value) <= schema.get("maxLength", len(value))
            and ("pattern" not in schema or re.search(schema["pattern"], value) is not None)
        )
    if kind == "boolean":
        return type(value) is bool
    if kind == "integer":
        return type(value) is int and value >= schema.get("minimum", value) and value <= schema.get("maximum", value)
    if kind == "number":
        valid = (
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and (not isinstance(value, float) or math.isfinite(value))
        )
        return bool(valid) and value >= schema.get("minimum", value) and value <= schema.get("maximum", value)
    return False


def _interaction_text(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value == value.strip()
        and "\x00" not in value
        and not any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    )


def _interaction_text_list(value: object, maximum_items: int) -> bool:
    return (
        isinstance(value, list)
        and 1 <= len(value) <= maximum_items
        and all(_interaction_text(item, 500) for item in value)
    )


def _interaction_identifier(value: object) -> bool:
    return isinstance(value, str) and len(value) <= 128 and APPLICATION_ID.fullmatch(value) is not None


def _interaction_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= 256
        and all(re.fullmatch(r"[a-z][a-z0-9_]*", segment) is not None for segment in value.split("."))
    )


def _interaction_artifact_name(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 120
        and value not in {".", ".."}
        and not value.startswith(".")
        and "/" not in value
        and "\\" not in value
        and not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _interaction_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate interaction key")
        result[key] = value
    return result


def _interaction_bounded(value: object, depth: int = 0) -> bool:
    if depth > 16:
        return False
    if isinstance(value, dict):
        return all(_interaction_bounded(child, depth + 1) for child in value.values())
    if isinstance(value, list):
        return all(_interaction_bounded(child, depth + 1) for child in value)
    return not isinstance(value, float) or math.isfinite(value)


def _result_path(schema: dict, dotted: str) -> dict | None:
    node = schema
    for segment in dotted.split("."):
        if node.get("type") != "object" or segment not in node.get("properties", {}):
            return None
        node = node["properties"][segment]
    return node


def _validate_interaction_contract(descriptor: dict, source: bytes, canonical: bytes) -> dict:
    try:
        document = json.loads(
            source, object_pairs_hook=_interaction_object,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "source interaction JSON is malformed") from exc
    if not source or len(source) > 64 * 1024 or not _interaction_bounded(document) or canonical_json(document) != canonical:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "source and canonical interaction contracts differ")
    if not isinstance(document, dict) or set(document) != {"schema", "application_id", "title", "purpose", "not_for", "operation", "boundaries"}:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction top-level shape is invalid")
    if (
        document["schema"] != "capy.application-interaction/dev-v0"
        or not _interaction_identifier(document["application_id"])
        or document["application_id"] != descriptor.get("id")
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction application identity is invalid")
    if descriptor.get("schema") != "capy.script/dev-v0" or descriptor.get("state_required") is not False or descriptor.get("connections") != [] or descriptor.get("side_effect") not in {"read_only", "artifact_generation"}:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction executable eligibility is invalid")
    if (
        not _interaction_text(document["title"], 120)
        or not _interaction_text(document["purpose"], 1000)
        or not _interaction_text_list(document["not_for"], 32)
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction descriptive text is invalid")
    operation = document["operation"]
    operation_keys = {"operation_id", "title", "user_outcome", "description", "request_fields", "resource_fields", "examples", "common_misunderstandings", "result"}
    if (
        not isinstance(operation, dict) or set(operation) != operation_keys
        or not _interaction_identifier(operation.get("operation_id"))
        or not _interaction_text(operation.get("title"), 120)
        or not _interaction_text(operation.get("user_outcome"), 500)
        or not _interaction_text(operation.get("description"), 1000)
        or not _interaction_text_list(operation.get("examples"), 16)
        or not _interaction_text_list(operation.get("common_misunderstandings"), 16)
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction operation shape is invalid")
    leaves = _interaction_leaves(descriptor.get("input_schema", {}))
    request_keys = {"field_id", "label", "description", "required", "input_kind", "safe_default", "examples", "clarification_question"}
    observed: set[str] = set()
    request_fields = operation.get("request_fields")
    if not isinstance(request_fields, list) or len(request_fields) > 64:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction request fields are invalid")
    for field in request_fields:
        if (
            not isinstance(field, dict) or set(field) != request_keys
            or not _interaction_path(field.get("field_id"))
            or field.get("field_id") not in leaves or field["field_id"] in observed
            or not _interaction_text(field.get("label"), 120)
            or not _interaction_text(field.get("description"), 1000)
            or not _interaction_text_list(field.get("examples"), 16)
            or not _interaction_text(field.get("clarification_question"), 500)
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction request field coverage is invalid")
        observed.add(field["field_id"])
        rule, required = leaves[field["field_id"]]
        expected_kinds = {"string": {"choice"} if "enum" in rule else {"text", "long_text"}, "integer": {"number"}, "number": {"number"}, "boolean": {"boolean"}}[rule["type"]]
        if type(field.get("required")) is not bool or field["required"] is not required or field.get("input_kind") not in expected_kinds:
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction request field semantics are invalid")
        default = field.get("safe_default")
        if (required and default is not None) or (default is not None and not _schema_accepts(default, rule)):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction safe default is invalid")
    if observed != set(leaves):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction request fields are incomplete")
    resources = {item["name"]: item for item in descriptor.get("resources", [])}
    resource_keys = {"slot", "label", "description", "required", "minimum_count", "maximum_count", "input_kind", "examples", "clarification_question"}
    observed_resources: set[str] = set()
    resource_fields = operation.get("resource_fields")
    if not isinstance(resource_fields, list) or len(resource_fields) > 16:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction resource fields are invalid")
    for field in resource_fields:
        if (
            not isinstance(field, dict) or set(field) != resource_keys
            or not isinstance(field.get("slot"), str)
            or re.fullmatch(r"[a-z][a-z0-9_]*", field["slot"]) is None
            or field.get("slot") not in resources or field["slot"] in observed_resources
            or not _interaction_text(field.get("label"), 120)
            or not _interaction_text(field.get("description"), 1000)
            or not _interaction_text_list(field.get("examples"), 16)
            or not _interaction_text(field.get("clarification_question"), 500)
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction resource field coverage is invalid")
        observed_resources.add(field["slot"])
        rule = resources[field["slot"]]
        if (field.get("required"), field.get("minimum_count"), field.get("maximum_count"), field.get("input_kind")) != (rule["required"], rule["min_items"], rule["max_items"], "file"):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction resource field semantics are invalid")
    if observed_resources != set(resources):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction resource fields are incomplete")
    result = operation.get("result")
    if not isinstance(result, dict) or set(result) != {"presentation", "facts", "artifacts"}:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction result shape is invalid")
    if (
        not isinstance(result["facts"], list) or len(result["facts"]) > 64
        or not isinstance(result["artifacts"], list) or len(result["artifacts"]) > 32
        or (not result["facts"] and not result["artifacts"])
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction result collection is invalid")
    fact_paths: set[str] = set()
    for fact in result["facts"]:
        if (
            not isinstance(fact, dict) or set(fact) != {"path", "label"}
            or not _interaction_path(fact.get("path")) or fact.get("path") in fact_paths
            or not _interaction_text(fact.get("label"), 120)
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction result fact is invalid")
        fact_paths.add(fact["path"])
        node = _result_path(descriptor.get("result_schema", {}), fact["path"])
        if node is None or node.get("type") not in {"string", "integer", "number", "boolean"}:
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction result fact is unknown")
    filenames = []
    for item in result["artifacts"]:
        if (
            not isinstance(item, dict) or set(item) != {"filename", "label"}
            or not _interaction_artifact_name(item.get("filename"))
            or item["filename"] in filenames
            or not _interaction_text(item.get("label"), 120)
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction result artifact is invalid")
        filenames.append(item["filename"])
    expected_node = descriptor.get("result_schema", {}).get("properties", {}).get("artifact_filenames", {})
    expected_files = expected_node.get("items", {}).get("enum") if expected_node.get("type") == "array" else None
    if descriptor["side_effect"] == "read_only" and filenames:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "read-only interaction advertises artifacts")
    if descriptor["side_effect"] == "artifact_generation" and filenames != expected_files:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction artifact list differs from executable truth")
    if result.get("presentation") != ("artifact_result" if filenames else "facts"):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction presentation is invalid")
    boundaries = document.get("boundaries")
    if not isinstance(boundaries, list) or not 1 <= len(boundaries) <= 32:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction boundaries are invalid")
    boundary_ids = set()
    for item in boundaries:
        if (
            not isinstance(item, dict) or set(item) != {"boundary_id", "request_class", "explanation", "nearest_operation_ids"}
            or not _interaction_identifier(item.get("boundary_id")) or item["boundary_id"] in boundary_ids
            or not _interaction_text(item.get("request_class"), 1000)
            or not _interaction_text(item.get("explanation"), 1000)
            or not isinstance(item.get("nearest_operation_ids"), list)
            or not item["nearest_operation_ids"]
            or any(value != operation["operation_id"] for value in item["nearest_operation_ids"])
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction boundary is invalid")
        boundary_ids.add(item["boundary_id"])
    return {"schema": document["schema"], "operation_id": operation["operation_id"]}


def _validate_v1_bundle_bytes(payload: bytes) -> dict:
    if len(payload) > MAX_BUNDLE_BYTES:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate exceeds the byte limit")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = _safe_zip_infos(archive, exact_names=MEMBERS_V1)
            if archive.comment or any(info.date_time != FIXED_ZIP_TIME or info.compress_type != zipfile.ZIP_STORED or info.create_system != 3 or ((info.external_attr >> 16) & 0xFFFF) != 0o100644 or info.extra or info.comment for info in infos):
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate ZIP metadata is not canonical")
            members = {name: archive.read(name) for name in MEMBERS_V1}
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate is not a valid ZIP") from exc
    if _zip_bytes(members, MEMBERS_V1) != payload:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "release candidate outer bytes are not canonical")
    try:
        manifest = json.loads(members[MEMBERS_V1[0]])
        receipt = json.loads(members[MEMBERS_V1[3]])
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate JSON metadata is malformed") from exc
    if canonical_json(manifest) != members[MEMBERS_V1[0]] or canonical_json(receipt) != members[MEMBERS_V1[3]]:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate JSON metadata is not canonical")
    _require_keys(manifest, {"schema", "release_candidate_id", "identity_sha256", "project", "source", "application", "toolchain", "verification", "handoff", "verified_at"}, "manifest")
    _require_keys(receipt, {"schema", "pipeline", "verification_id", "status", "classification", "session_id", "project_id", "application_id", "source", "toolchain", "interaction_contract", "stages", "application_archive", "verified_at"}, "receipt")
    if manifest["schema"] != MANIFEST_SCHEMA_V1 or receipt["schema"] != RECEIPT_SCHEMA_V1 or receipt["pipeline"] != PIPELINE_V1:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 schema identity is invalid")
    _require_keys(manifest["project"], {"project_id"}, "manifest project")
    _require_keys(manifest["source"], {"repository", "commit", "tree", "base_commit"}, "manifest source")
    _require_keys(manifest["source"]["repository"], {"kind", "public_identity", "identity_sha256"}, "manifest repository")
    _require_keys(manifest["toolchain"], {"release_binding_commit", "implementation_commit", "authoring_bundle", "wheel_filename", "wheel_sha256", "interaction_contract"}, "manifest toolchain")
    _require_keys(manifest["toolchain"]["authoring_bundle"], {"member", "sha256", "size_bytes"}, "manifest authoring bundle")
    _require_keys(manifest["verification"], {"verification_id", "receipt"}, "manifest verification")
    _require_keys(manifest["verification"]["receipt"], {"member", "sha256", "size_bytes"}, "manifest verification receipt")
    _require_keys(receipt["source"], {"commit", "tree", "base_commit"}, "receipt source")
    _require_keys(receipt["toolchain"], {"contract", "interaction_contract", "lock_digest", "release_binding_commit", "implementation_commit", "authoring_bundle_sha256", "wheel_filename", "wheel_sha256"}, "receipt toolchain")
    _require_keys(receipt["application_archive"], {"sha256", "size_bytes"}, "receipt application archive")
    app = manifest["application"]
    _require_keys(app, {"id", "contract", "descriptor_sha256", "archive", "interaction"}, "manifest application")
    _require_keys(app["archive"], {"member", "sha256", "size_bytes"}, "manifest application archive")
    interaction_binding = _require_keys(app["interaction"], {"schema", "source_member", "source_sha256", "member", "sha256", "size_bytes", "operation_id"}, "manifest interaction")
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
                or digest_bytes(repository_identity["public_identity"].encode()) != repository_identity["identity_sha256"]
            )
        )
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 repository identity is invalid")
    if (
        PROJECT_ID.fullmatch(str(manifest["project"]["project_id"])) is None
        or APPLICATION_ID.fullmatch(str(app["id"])) is None
        or VERIFICATION_ID.fullmatch(str(manifest["verification"]["verification_id"])) is None
        or SESSION_ID.fullmatch(str(receipt["session_id"])) is None
        or any(HEX40.fullmatch(str(manifest["source"][key])) is None for key in ("commit", "tree", "base_commit"))
        or any(HEX40.fullmatch(str(manifest["toolchain"][key])) is None for key in ("release_binding_commit", "implementation_commit"))
        or any(
            HEX64.fullmatch(str(value)) is None
            for value in (
                app["descriptor_sha256"], app["archive"]["sha256"], interaction_binding["source_sha256"],
                interaction_binding["sha256"], manifest["toolchain"]["authoring_bundle"]["sha256"],
                manifest["toolchain"]["wheel_sha256"], manifest["verification"]["receipt"]["sha256"],
                receipt["toolchain"]["lock_digest"], receipt["application_archive"]["sha256"],
            )
        )
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (
                app["archive"]["size_bytes"], interaction_binding["size_bytes"],
                manifest["toolchain"]["authoring_bundle"]["size_bytes"],
                manifest["verification"]["receipt"]["size_bytes"], receipt["application_archive"]["size_bytes"],
            )
        )
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 identity field syntax is invalid")
    bindings = ((app["archive"], MEMBERS_V1[1]), (interaction_binding, MEMBERS_V1[2]), (manifest["verification"]["receipt"], MEMBERS_V1[3]), (manifest["toolchain"]["authoring_bundle"], MEMBERS_V1[4]))
    for binding, name in bindings:
        if binding.get("member") != name or binding.get("sha256") != digest_bytes(members[name]) or binding.get("size_bytes") != len(members[name]):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 member binding is invalid")
    application = inspect_application_archive(members[MEMBERS_V1[1]], app["id"], app["contract"])
    if application["descriptor_sha256"] != app["descriptor_sha256"] or application["interaction_bytes"] is None:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "application archive identity is invalid")
    validated_interaction = _validate_interaction_contract(application["descriptor"], application["interaction_bytes"], members[MEMBERS_V1[2]])
    if interaction_binding["schema"] != validated_interaction["schema"] or interaction_binding["operation_id"] != validated_interaction["operation_id"] or interaction_binding["source_member"] != "interaction.json" or interaction_binding["source_sha256"] != digest_bytes(application["interaction_bytes"]):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction source binding is invalid")
    toolchain = inspect_authoring_bundle(members[MEMBERS_V1[4]])
    toolchain_manifest = toolchain["manifest"]
    if (
        digest_bytes(members[MEMBERS_V1[4]]) != ACCEPTED_BUNDLE_SHA256
        or toolchain["wheel_sha256"] != ACCEPTED_WHEEL_SHA256
        or toolchain_manifest.get("schema") != "capy.devkit-authoring-bundle/v1"
        or toolchain_manifest.get("interaction_contract") != interaction_binding["schema"]
        or toolchain_manifest.get("source_commit") != ACCEPTED_SOURCE_COMMIT
        or manifest["toolchain"].get("release_binding_commit") != ACCEPTED_DEVKIT_MAIN
        or manifest["toolchain"].get("implementation_commit") != ACCEPTED_SOURCE_COMMIT
        or manifest["toolchain"].get("wheel_sha256") != ACCEPTED_WHEEL_SHA256
        or manifest["toolchain"].get("wheel_filename") != toolchain["wheel_filename"]
        or manifest["toolchain"].get("interaction_contract") != interaction_binding["schema"]
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "interaction-aware toolchain identity is invalid")
    expected_handoff = {"verification":"passed","independent_acceptance":"required","interaction_contract":"included_unaccepted","state_migration":"not_assessed","rollback":"not_assessed","runtime_version_digest":"not_assigned","publication":"not_performed","installation":"not_performed","binding":"not_performed","deployment":"not_performed","publisher_signature":"not_present","secret_scan":"not_performed","runtime_import":"not_performed"}
    if manifest.get("handoff") != expected_handoff:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 handoff claims were weakened or changed")
    if [stage.get("name") for stage in receipt.get("stages", [])] != list(STAGES_V1) or any(stage.get("status") != "PASSED" for stage in receipt.get("stages", [])):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 stage sequence is invalid")
    stage_keys = {"name", "status", "exit_code", "stored_stdout_sha256", "stored_stdout_bytes", "stored_stderr_sha256", "stored_stderr_bytes", "stdout_truncated_bytes", "stderr_truncated_bytes", "facts"}
    for stage in receipt["stages"]:
        _require_keys(stage, stage_keys, "verification receipt stage")
        exit_code = stage["exit_code"]
        if (
            not isinstance(stage["stored_stdout_sha256"], str)
            or HEX64.fullmatch(stage["stored_stdout_sha256"]) is None
            or not isinstance(stage["stored_stderr_sha256"], str)
            or HEX64.fullmatch(stage["stored_stderr_sha256"]) is None
            or (stage["name"] in _PROCESS_STAGES and (type(exit_code) is not int or exit_code != 0))
            or (stage["name"] not in _PROCESS_STAGES and exit_code is not None)
            or any(
                not isinstance(stage[key], int) or isinstance(stage[key], bool) or stage[key] < 0
                for key in ("stored_stdout_bytes", "stored_stderr_bytes", "stdout_truncated_bytes", "stderr_truncated_bytes")
            )
        ):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 stage output facts are invalid")
        _portable_facts(stage["name"], stage.get("facts"))
    facts = {stage["name"]: stage["facts"] for stage in receipt["stages"]}
    archive_fact = {"sha256": app["archive"]["sha256"], "size_bytes": app["archive"]["size_bytes"]}
    if (
        facts["archive_preserve"] != archive_fact
        or facts["package_compare"]["sha256_a"] != archive_fact["sha256"]
        or facts["package_compare"]["sha256_b"] != archive_fact["sha256"]
        or facts["package_compare"]["size_a"] != archive_fact["size_bytes"]
        or facts["package_compare"]["size_b"] != archive_fact["size_bytes"]
        or facts["interaction_preserve"]["source_sha256"] != interaction_binding["source_sha256"]
        or facts["interaction_preserve"]["canonical_sha256"] != interaction_binding["sha256"]
        or facts["interaction_preserve"]["canonical_size_bytes"] != interaction_binding["size_bytes"]
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 preservation facts disagree")
    expected_interaction = {key: interaction_binding[key] for key in ("schema", "source_member", "source_sha256", "sha256", "size_bytes", "operation_id")}
    expected_interaction = {"schema":expected_interaction["schema"],"source_member":expected_interaction["source_member"],"source_sha256":expected_interaction["source_sha256"],"canonical_sha256":expected_interaction["sha256"],"canonical_size_bytes":expected_interaction["size_bytes"],"operation_id":expected_interaction["operation_id"]}
    if (
        receipt.get("interaction_contract") != expected_interaction
        or receipt.get("application_archive") != {"sha256": app["archive"]["sha256"], "size_bytes": app["archive"]["size_bytes"]}
        or receipt.get("verification_id") != manifest["verification"]["verification_id"]
        or receipt.get("project_id") != manifest["project"]["project_id"]
        or receipt.get("application_id") != app["id"]
        or receipt.get("source") != {key: manifest["source"][key] for key in ("commit", "tree", "base_commit")}
        or receipt.get("status") != "PASSED" or receipt.get("classification") != "VERIFIED"
        or receipt.get("verified_at") != manifest.get("verified_at")
        or receipt["toolchain"] != {
            "contract": app["contract"], "interaction_contract": interaction_binding["schema"],
            "lock_digest": receipt["toolchain"]["lock_digest"],
            "release_binding_commit": manifest["toolchain"]["release_binding_commit"],
            "implementation_commit": manifest["toolchain"]["implementation_commit"],
            "authoring_bundle_sha256": manifest["toolchain"]["authoring_bundle"]["sha256"],
            "wheel_filename": manifest["toolchain"]["wheel_filename"],
            "wheel_sha256": manifest["toolchain"]["wheel_sha256"],
        }
    ):
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 receipt disagrees with manifest")
    identity_sha256 = digest_bytes(canonical_json(_identity_from_manifest(manifest)))
    candidate_id = "rc_" + identity_sha256[:32]
    if manifest.get("identity_sha256") != identity_sha256 or manifest.get("release_candidate_id") != candidate_id:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate V1 identity is invalid")
    return {"manifest":manifest,"receipt":receipt,"identity_sha256":identity_sha256,"release_candidate_id":candidate_id,"manifest_sha256":digest_bytes(members[MEMBERS_V1[0]]),"bundle_sha256":digest_bytes(payload),"bundle_size_bytes":len(payload)}


def validate_bundle_bytes(payload: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            first = archive.read("RELEASE-CANDIDATE.json")
        schema = json.loads(first).get("schema")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate manifest is unavailable") from exc
    if schema == MANIFEST_SCHEMA:
        return _validate_v0_bundle_bytes(payload)
    if schema == MANIFEST_SCHEMA_V1:
        return _validate_v1_bundle_bytes(payload)
    raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate metadata schema is unsupported")


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
                }
                if context["members"] == MEMBERS_V1:
                    payloads = {
                        MEMBERS_V1[0]: context["manifest_bytes"], MEMBERS_V1[1]: context["application_bytes"],
                        MEMBERS_V1[2]: context["interaction_bytes"], MEMBERS_V1[3]: context["receipt_bytes"],
                        MEMBERS_V1[4]: context["toolchain_bytes"],
                    }
                else:
                    payloads[MEMBERS[2]] = context["receipt_bytes"]
                    payloads[MEMBERS[3]] = context["toolchain_bytes"]
                bundle_a = _zip_bytes(payloads, context["members"])
                bundle_b = _zip_bytes(payloads, context["members"])
                if bundle_a != bundle_b:
                    raise DeveloperError("RELEASE_CANDIDATE_NOT_REPRODUCIBLE", "two candidate builds were not byte-identical")
                (attempt_root / "a.capyrc").write_bytes(bundle_a)
                (attempt_root / "b.capyrc").write_bytes(bundle_b)
                validation = validate_bundle_bytes(bundle_a)
                destination = self._preserve(bundle_a, validation["bundle_sha256"])
                durable = _read_candidate_bytes(destination)
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
                store_root = self.config.release_candidates_root.expanduser().absolute().resolve()
                bundle_path = store_root / candidate["bundle_sha256"] / "candidate.capyrc"
                if Path(candidate["bundle_path"]) != bundle_path:
                    raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "durable candidate path is not content-addressed")
                parent_status = bundle_path.parent.lstat()
                if not stat.S_ISDIR(parent_status.st_mode) or stat.S_ISLNK(parent_status.st_mode):
                    raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "durable candidate digest path is not a real directory")
                durable_bytes = read_regular_bytes(bundle_path)
            except (DeveloperError, OSError, ValueError):
                bundle_path = Path(candidate["bundle_path"])
                current_state = "BUNDLE_INVALID"
                discrepancy = {"code": "RELEASE_CANDIDATE_INTEGRITY_FAILED", "detail": "durable candidate path escapes its managed root"}
            if discrepancy is not None:
                return self._result(candidate, current_state, discrepancy)
            if digest_bytes(durable_bytes) != candidate["bundle_sha256"] or len(durable_bytes) != candidate["bundle_size_bytes"]:
                current_state = "DIGEST_MISMATCH"
                discrepancy = {"code": "RELEASE_CANDIDATE_INTEGRITY_FAILED", "detail": "durable candidate bundle digest or size differs"}
            else:
                try:
                    validation = validate_bundle_bytes(durable_bytes)
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
            interaction_row = db.execute(
                "SELECT * FROM verification_interactions WHERE verification_id=?", (verification_id,)
            ).fetchone()
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
        pipeline = attempt.get("pipeline_schema") or PIPELINE_V0
        expected_stages = STAGES_V1 if pipeline == PIPELINE_V1 else STAGES
        if len(stages) != len(expected_stages) or [row["stage_name"] for row in stages] != list(expected_stages) or any(
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
        interaction = dict(interaction_row) if interaction_row is not None else None
        interaction_bytes = None
        if pipeline == PIPELINE_V1:
            if interaction is None or application.get("interaction_bytes") is None:
                raise DeveloperError("INTERACTION_EVIDENCE_MISSING", "V1 verification interaction evidence is unavailable")
            try:
                interaction_root = self.config.verification_interactions_root.expanduser().absolute().resolve()
                interaction_path = interaction_root / interaction["canonical_sha256"] / "interaction.json"
                if Path(interaction["canonical_path"]) != interaction_path:
                    raise DeveloperError(
                        "INTERACTION_EVIDENCE_MISSING",
                        "canonical interaction evidence path is not content-addressed",
                    )
                digest_status = interaction_path.parent.lstat()
                if not stat.S_ISDIR(digest_status.st_mode) or stat.S_ISLNK(digest_status.st_mode):
                    raise OSError("canonical interaction digest path is not a real directory")
                interaction_bytes = read_regular_bytes(interaction_path)
            except (DeveloperError, OSError, ValueError) as exc:
                raise DeveloperError("INTERACTION_EVIDENCE_MISSING", "canonical interaction evidence is unavailable") from exc
            if digest_bytes(interaction_bytes) != interaction["canonical_sha256"] or len(interaction_bytes) != interaction["canonical_size_bytes"]:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "canonical interaction evidence differs from its record")
            if digest_bytes(application["interaction_bytes"]) != interaction["source_sha256"]:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "application archive interaction source differs from verification")
            validated = _validate_interaction_contract(application["descriptor"], application["interaction_bytes"], interaction_bytes)
            if validated != {"schema": interaction["schema"], "operation_id": interaction["operation_id"]}:
                raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "canonical interaction identity differs from verification")
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
            interaction_contract=attempt.get("interaction_contract"),
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
        if pipeline == PIPELINE_V1:
            identity_seed = {
                **identity_seed,
                "schema": MANIFEST_SCHEMA_V1,
                "interaction": {
                    "schema": interaction["schema"], "source_sha256": interaction["source_sha256"],
                    "canonical_sha256": interaction["canonical_sha256"], "operation_id": interaction["operation_id"],
                },
                "toolchain": {**identity_seed["toolchain"], "interaction_contract": attempt["interaction_contract"]},
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
            "interaction": interaction,
            "interaction_bytes": interaction_bytes,
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
            "members": MEMBERS_V1 if pipeline == PIPELINE_V1 else MEMBERS,
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
        receipt = {
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
        if attempt.get("pipeline_schema") == PIPELINE_V1:
            with self.db.connect() as db:
                interaction = dict(db.execute(
                    "SELECT * FROM verification_interactions WHERE verification_id=?", (attempt["verification_id"],)
                ).fetchone())
            receipt["schema"] = RECEIPT_SCHEMA_V1
            receipt["pipeline"] = PIPELINE_V1
            receipt["interaction_contract"] = {
                "schema": interaction["schema"], "source_member": interaction["source_member"],
                "source_sha256": interaction["source_sha256"], "canonical_sha256": interaction["canonical_sha256"],
                "canonical_size_bytes": interaction["canonical_size_bytes"], "operation_id": interaction["operation_id"],
            }
            receipt["toolchain"]["interaction_contract"] = attempt["interaction_contract"]
        return receipt

    def _manifest(
        self, candidate_id: str, identity_sha256: str, attempt: dict, session: dict,
        repository_identity: dict, application: dict, receipt_bytes: bytes,
        toolchain_bytes: bytes, toolchain_manifest: dict, wheel_filename: str,
    ) -> dict:
        manifest = {
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
        if attempt.get("pipeline_schema") == PIPELINE_V1:
            with self.db.connect() as db:
                interaction = dict(db.execute(
                    "SELECT * FROM verification_interactions WHERE verification_id=?", (attempt["verification_id"],)
                ).fetchone())
            manifest["schema"] = MANIFEST_SCHEMA_V1
            manifest["application"]["interaction"] = {
                "schema": interaction["schema"], "source_member": interaction["source_member"],
                "source_sha256": interaction["source_sha256"], "member": MEMBERS_V1[2],
                "sha256": interaction["canonical_sha256"], "size_bytes": interaction["canonical_size_bytes"],
                "operation_id": interaction["operation_id"],
            }
            manifest["application"]["archive"]["member"] = MEMBERS_V1[1]
            manifest["toolchain"]["authoring_bundle"]["member"] = MEMBERS_V1[4]
            manifest["toolchain"]["interaction_contract"] = attempt["interaction_contract"]
            manifest["verification"]["receipt"]["member"] = MEMBERS_V1[3]
            manifest["handoff"] = {
                "verification": "passed", "independent_acceptance": "required",
                "interaction_contract": "included_unaccepted", "state_migration": "not_assessed",
                "rollback": "not_assessed", "runtime_version_digest": "not_assigned",
                "publication": "not_performed", "installation": "not_performed",
                "binding": "not_performed", "deployment": "not_performed",
                "publisher_signature": "not_present", "secret_scan": "not_performed",
                "runtime_import": "not_performed",
            }
        return manifest

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
                       verification_receipt_sha256,format_schema,manifest_json,manifest_sha256,
                       bundle_sha256,bundle_size_bytes,bundle_path,status,classification,attempt_count,
                       started_at,updated_at,terminal_at,error_code,error_detail
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        context["release_candidate_id"], attempt["verification_id"], session["session_id"], session["project_id"], attempt["application_id"],
                        attempt["candidate_commit"], attempt["candidate_tree"], attempt["base_commit"], context["identity_sha256"],
                        repo["kind"], repo["public_identity"], repo["identity_sha256"], attempt["archive_sha256"], attempt["archive_size_bytes"],
                        context["application"]["descriptor_sha256"], attempt["contract"], attempt["release_binding_commit"], toolchain["source_commit"],
                        attempt["authoring_bundle_sha256"], toolchain["wheel_filename"], attempt["wheel_sha256"], context["receipt_sha256"],
                        context["manifest"]["schema"], context["manifest_bytes"].decode("utf-8"), context["manifest_sha256"], None, None, None,
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
        store_root = self.config.release_candidates_root.expanduser().absolute().resolve()
        digest_root = store_root / digest
        destination = digest_root / "candidate.capyrc"
        store_root.mkdir(parents=True, exist_ok=True)
        digest_root.mkdir(exist_ok=True)
        parent_status = digest_root.lstat()
        if not stat.S_ISDIR(parent_status.st_mode) or stat.S_ISLNK(parent_status.st_mode):
            raise DeveloperError("RELEASE_CANDIDATE_INTEGRITY_FAILED", "candidate digest path is not a real directory")
        if destination.exists():
            if _read_candidate_bytes(destination) != payload:
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
            if _read_candidate_bytes(destination) != payload:
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
            payloads = (
                ((MEMBERS_V1[0], context["manifest_bytes"]), (MEMBERS_V1[1], context["application_bytes"]), (MEMBERS_V1[2], context["interaction_bytes"]),
                 (MEMBERS_V1[3], context["receipt_bytes"]), (MEMBERS_V1[4], context["toolchain_bytes"]))
                if context["members"] == MEMBERS_V1 else
                ((MEMBERS[1], context["application_bytes"]), (MEMBERS[2], context["receipt_bytes"]), (MEMBERS[3], context["toolchain_bytes"]))
            )
            for member, payload in payloads:
                db.execute("INSERT INTO release_candidate_members VALUES (?,?,?,?)", (candidate_id, member, digest_bytes(payload), len(payload)))
            db.execute("DELETE FROM release_candidate_interactions WHERE release_candidate_id=?", (candidate_id,))
            if context["interaction"] is not None:
                interaction = context["interaction"]
                db.execute(
                    "INSERT INTO release_candidate_interactions VALUES (?,?,?,?,?,?,?,?)",
                    (candidate_id, interaction["schema"], interaction["source_member"], interaction["source_sha256"],
                     MEMBERS_V1[2], interaction["canonical_sha256"], interaction["canonical_size_bytes"], interaction["operation_id"]),
                )
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
        result = {
            "schema": RESULT_SCHEMA_V1 if candidate.get("format_schema") == MANIFEST_SCHEMA_V1 else RESULT_SCHEMA,
            "ok": available, "status": candidate["status"],
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
        if candidate.get("format_schema") == MANIFEST_SCHEMA_V1:
            with self.db.connect() as db:
                row = db.execute(
                    "SELECT * FROM release_candidate_interactions WHERE release_candidate_id=?",
                    (candidate["release_candidate_id"],),
                ).fetchone()
                member_rows = db.execute(
                    "SELECT member_path,sha256,size_bytes FROM release_candidate_members WHERE release_candidate_id=? ORDER BY member_path",
                    (candidate["release_candidate_id"],),
                ).fetchall()
            interaction = dict(row) if row is not None else None
            result["format_schema"] = MANIFEST_SCHEMA_V1
            result["application"]["interaction"] = None if interaction is None else {
                "schema": interaction["schema"], "source_member": interaction["source_member"],
                "source_sha256": interaction["source_sha256"], "member": interaction["canonical_member"],
                "canonical_sha256": interaction["canonical_sha256"],
                "canonical_size_bytes": interaction["canonical_size_bytes"], "operation_id": interaction["operation_id"],
            }
            result["handoff"] = json.loads(candidate["manifest_json"])["handoff"]
            result["members"] = [dict(item) for item in member_rows]
        return result
