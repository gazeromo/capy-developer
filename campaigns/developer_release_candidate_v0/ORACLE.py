#!/usr/bin/env python3
"""Independent standard-library validator for copied Release Candidate V0 bytes."""

from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath


MEMBERS = (
    "RELEASE-CANDIDATE.json",
    "application/application.zip",
    "evidence/verification.json",
    "toolchain/authoring-bundle.zip",
)
STAGES = (
    "toolchain_install", "check", "test", "conform", "source_mutation_check",
    "pack_a", "pack_b", "package_compare", "archive_preserve",
)
PROCESS_STAGES = {"toolchain_install", "check", "test", "conform", "pack_a", "pack_b"}
HANDOFF = {
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


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_keys(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} shape")
    return value


def safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("duplicate member")
    for info in infos:
        name = PurePosixPath(info.filename)
        mode = (info.external_attr >> 16) & 0xFFFF
        if (
            not info.filename or info.is_dir() or name.is_absolute() or ".." in name.parts
            or "\\" in info.filename or (mode & 0o170000) == 0o120000 or info.flag_bits & 1
        ):
            raise ValueError("unsafe member")
    return infos


def canonical_zip(values: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.comment = b""
        for name in MEMBERS:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.extra = b""
            info.comment = b""
            archive.writestr(info, values[name])
    return output.getvalue()


def application(payload: bytes) -> dict:
    if len(payload) > 64 * 1024 * 1024:
        raise ValueError("application archive too large")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = safe_members(archive)
        if len(infos) > 4096 or sum(info.file_size for info in infos) > 256 * 1024 * 1024:
            raise ValueError("application archive bounds exceeded")
        descriptors = [info for info in infos if info.filename == "capability.toml"]
        if len(descriptors) != 1:
            raise ValueError("root descriptor count")
        descriptor_bytes = archive.read(descriptors[0])
    descriptor = tomllib.loads(descriptor_bytes.decode("utf-8"))
    return {"id": descriptor.get("id"), "contract": descriptor.get("schema"), "sha256": digest(descriptor_bytes)}


def toolchain(payload: bytes) -> dict:
    if len(payload) > 64 * 1024 * 1024:
        raise ValueError("toolchain archive too large")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = safe_members(archive)
        if len(infos) > 4096 or sum(info.file_size for info in infos) > 256 * 1024 * 1024:
            raise ValueError("toolchain archive bounds exceeded")
        release = json.loads(archive.read("RELEASE-MANIFEST.json"))
        wheel_name = release["wheel_filename"]
        wheel_member = archive.getinfo(f"wheel/{wheel_name}")
        if wheel_member.file_size > 64 * 1024 * 1024:
            raise ValueError("toolchain wheel too large")
        wheel = archive.read(wheel_member)
    if release.get("schema") != "capy.devkit-authoring-bundle/v0" or release.get("wheel_sha256") != digest(wheel):
        raise ValueError("toolchain identity")
    return {"manifest": release, "wheel_filename": wheel_name, "wheel_sha256": digest(wheel)}


def identity_from_manifest(manifest: dict) -> dict:
    return {
        "schema": "capy.application-release-candidate/v0",
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


def validate(payload: bytes) -> dict:
    if len(payload) > 130 * 1024 * 1024:
        raise ValueError("candidate too large")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = safe_members(archive)
        if tuple(info.filename for info in infos) != MEMBERS or archive.comment:
            raise ValueError("outer member set/order")
        for info in infos:
            if (
                info.date_time != (1980, 1, 1, 0, 0, 0)
                or info.compress_type != zipfile.ZIP_STORED or info.create_system != 3
                or ((info.external_attr >> 16) & 0xFFFF) != 0o100644
                or info.extra or info.comment
            ):
                raise ValueError("outer metadata")
        values = {name: archive.read(name) for name in MEMBERS}
    if canonical_zip(values) != payload:
        raise ValueError("noncanonical outer bytes")
    manifest = json.loads(values[MEMBERS[0]])
    receipt = json.loads(values[MEMBERS[2]])
    if canonical(manifest) != values[MEMBERS[0]] or canonical(receipt) != values[MEMBERS[2]]:
        raise ValueError("noncanonical JSON")
    if manifest.get("schema") != "capy.application-release-candidate/v0":
        raise ValueError("manifest schema")
    if receipt.get("schema") != "capy.development-verification-receipt/v0":
        raise ValueError("receipt schema")
    require_keys(manifest, {"schema", "release_candidate_id", "identity_sha256", "project", "source", "application", "toolchain", "verification", "handoff", "verified_at"}, "manifest")
    require_keys(manifest["project"], {"project_id"}, "manifest project")
    require_keys(manifest["source"], {"repository", "commit", "tree", "base_commit"}, "manifest source")
    require_keys(manifest["source"]["repository"], {"kind", "public_identity", "identity_sha256"}, "manifest repository")
    require_keys(manifest["application"], {"id", "contract", "descriptor_sha256", "archive"}, "manifest application")
    require_keys(manifest["application"]["archive"], {"member", "sha256", "size_bytes"}, "manifest application archive")
    require_keys(manifest["toolchain"], {"release_binding_commit", "implementation_commit", "authoring_bundle", "wheel_filename", "wheel_sha256"}, "manifest toolchain")
    require_keys(manifest["toolchain"]["authoring_bundle"], {"member", "sha256", "size_bytes"}, "manifest authoring bundle")
    require_keys(manifest["verification"], {"verification_id", "receipt"}, "manifest verification")
    require_keys(manifest["verification"]["receipt"], {"member", "sha256", "size_bytes"}, "manifest receipt")
    require_keys(receipt, {"schema", "verification_id", "status", "classification", "session_id", "project_id", "application_id", "source", "toolchain", "stages", "application_archive", "verified_at"}, "receipt")
    require_keys(receipt["source"], {"commit", "tree", "base_commit"}, "receipt source")
    require_keys(receipt["toolchain"], {"contract", "lock_digest", "release_binding_commit", "implementation_commit", "authoring_bundle_sha256", "wheel_filename", "wheel_sha256"}, "receipt toolchain")
    require_keys(receipt["application_archive"], {"sha256", "size_bytes"}, "receipt archive")
    stage_keys = {"name", "status", "exit_code", "stored_stdout_sha256", "stored_stdout_bytes", "stored_stderr_sha256", "stored_stderr_bytes", "stdout_truncated_bytes", "stderr_truncated_bytes", "facts"}
    if not isinstance(receipt["stages"], list):
        raise ValueError("receipt stages")
    for stage in receipt["stages"]:
        require_keys(stage, stage_keys, "receipt stage")
    if manifest.get("handoff") != HANDOFF:
        raise ValueError("handoff claims")
    repository = manifest["source"]["repository"]
    if (
        repository["kind"] not in {"local", "remote"}
        or re.fullmatch(r"[0-9a-f]{64}", str(repository["identity_sha256"])) is None
        or (repository["kind"] == "local" and repository["public_identity"] is not None)
        or (
            repository["kind"] == "remote"
            and (
                not isinstance(repository["public_identity"], str)
                or not repository["public_identity"].startswith("git://")
                or "@" in repository["public_identity"]
                or digest(repository["public_identity"].encode()) != repository["identity_sha256"]
            )
        )
        or any(re.fullmatch(r"[0-9a-f]{40}", str(manifest["source"][key])) is None for key in ("commit", "tree", "base_commit"))
    ):
        raise ValueError("identity syntax")
    for binding, expected in (
        (manifest["application"]["archive"], MEMBERS[1]),
        (manifest["verification"]["receipt"], MEMBERS[2]),
        (manifest["toolchain"]["authoring_bundle"], MEMBERS[3]),
    ):
        if binding.get("member") != expected:
            raise ValueError("member path binding")
        member = values[expected]
        if binding.get("sha256") != digest(member) or binding.get("size_bytes") != len(member):
            raise ValueError("member digest/size binding")
    app = application(values[MEMBERS[1]])
    kit = toolchain(values[MEMBERS[3]])
    if (
        app != {
            "id": manifest["application"]["id"],
            "contract": manifest["application"]["contract"],
            "sha256": manifest["application"]["descriptor_sha256"],
        }
        or kit["wheel_filename"] != manifest["toolchain"]["wheel_filename"]
        or kit["wheel_sha256"] != manifest["toolchain"]["wheel_sha256"]
        or kit["manifest"].get("contract") != app["contract"]
        or kit["manifest"].get("source_commit") != manifest["toolchain"]["implementation_commit"]
    ):
        raise ValueError("application/toolchain binding")
    if (
        receipt.get("status") != "PASSED" or receipt.get("classification") != "VERIFIED"
        or receipt.get("verification_id") != manifest["verification"]["verification_id"]
        or receipt.get("project_id") != manifest["project"]["project_id"]
        or receipt.get("application_id") != manifest["application"]["id"]
        or receipt.get("source") != {
            "commit": manifest["source"]["commit"], "tree": manifest["source"]["tree"],
            "base_commit": manifest["source"]["base_commit"],
        }
        or receipt.get("application_archive") != {
            "sha256": manifest["application"]["archive"]["sha256"],
            "size_bytes": manifest["application"]["archive"]["size_bytes"],
        }
        or [item.get("name") for item in receipt.get("stages", [])] != list(STAGES)
        or any(item.get("status") != "PASSED" for item in receipt.get("stages", []))
    ):
        raise ValueError("verification binding")
    fact_keys = {
        "toolchain_install": {"timed_out"}, "check": {"timed_out", "candidate_unchanged"},
        "test": {"timed_out", "candidate_unchanged"}, "conform": {"timed_out", "candidate_unchanged"},
        "source_mutation_check": set(), "pack_a": {"timed_out", "candidate_unchanged"},
        "pack_b": {"timed_out", "candidate_unchanged"},
        "package_compare": {"sha256_a", "sha256_b", "size_a", "size_b"},
        "archive_preserve": {"sha256", "size_bytes"},
    }
    for stage in receipt["stages"]:
        exit_code = stage["exit_code"]
        facts = stage["facts"]
        if (
            not isinstance(stage["stored_stdout_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", stage["stored_stdout_sha256"]) is None
            or not isinstance(stage["stored_stderr_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", stage["stored_stderr_sha256"]) is None
            or (stage["name"] in PROCESS_STAGES and (
                not isinstance(exit_code, int) or isinstance(exit_code, bool) or exit_code != 0
            ))
            or (stage["name"] not in PROCESS_STAGES and exit_code is not None)
            or not isinstance(facts, dict)
            or set(facts) != fact_keys[stage["name"]]
            or any(
                not isinstance(stage[key], int) or isinstance(stage[key], bool) or stage[key] < 0
                for key in ("stored_stdout_bytes", "stored_stderr_bytes", "stdout_truncated_bytes", "stderr_truncated_bytes")
            )
        ):
            raise ValueError("receipt stage facts")
        for key, value in facts.items():
            if key in {"timed_out", "candidate_unchanged"} and not isinstance(value, bool):
                raise ValueError("receipt boolean fact")
            if key in {"sha256", "sha256_a", "sha256_b"} and (
                not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
            ):
                raise ValueError("receipt digest fact")
            if key in {"size_bytes", "size_a", "size_b"} and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError("receipt size fact")
        if facts.get("timed_out") is True or facts.get("candidate_unchanged") is False:
            raise ValueError("contradictory passed-stage fact")
        if stage["name"] == "package_compare" and (
            facts["sha256_a"] != facts["sha256_b"] or facts["size_a"] != facts["size_b"]
        ):
            raise ValueError("package comparison disagreement")
    stage_facts = {stage["name"]: stage["facts"] for stage in receipt["stages"]}
    compared = stage_facts["package_compare"]
    preserved = stage_facts["archive_preserve"]
    expected_archive = receipt["application_archive"]
    if (
        preserved != expected_archive
        or compared["sha256_a"] != expected_archive["sha256"]
        or compared["size_a"] != expected_archive["size_bytes"]
    ):
        raise ValueError("package/archive preservation disagreement")
    if receipt["verified_at"] != manifest["verified_at"]:
        raise ValueError("verified time")
    receipt_toolchain = receipt.get("toolchain", {})
    if (
        receipt_toolchain.get("contract") != manifest["application"]["contract"]
        or receipt_toolchain.get("release_binding_commit") != manifest["toolchain"]["release_binding_commit"]
        or receipt_toolchain.get("implementation_commit") != manifest["toolchain"]["implementation_commit"]
        or receipt_toolchain.get("authoring_bundle_sha256") != manifest["toolchain"]["authoring_bundle"]["sha256"]
        or receipt_toolchain.get("wheel_filename") != manifest["toolchain"]["wheel_filename"]
        or receipt_toolchain.get("wheel_sha256") != manifest["toolchain"]["wheel_sha256"]
    ):
        raise ValueError("receipt toolchain binding")
    identity = digest(canonical(identity_from_manifest(manifest)))
    candidate_id = "rc_" + identity[:32]
    if manifest.get("identity_sha256") != identity or manifest.get("release_candidate_id") != candidate_id:
        raise ValueError("candidate identity")
    return {
        "schema": "capy.development-release-candidate-oracle/v0",
        "status": "accepted",
        "release_candidate_id": candidate_id,
        "identity_sha256": identity,
        "manifest_sha256": digest(values[MEMBERS[0]]),
        "bundle_sha256": digest(payload),
        "bundle_size_bytes": len(payload),
    }


def main(arguments: list[str]) -> int:
    if len(arguments) != 1:
        print(json.dumps({"schema": "capy.development-release-candidate-oracle/v0", "status": "rejected", "error": "provide one .capyrc path"}, sort_keys=True))
        return 2
    try:
        result = validate(Path(arguments[0]).read_bytes())
    except Exception as exc:
        print(json.dumps({"schema": "capy.development-release-candidate-oracle/v0", "status": "rejected", "error": type(exc).__name__}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
