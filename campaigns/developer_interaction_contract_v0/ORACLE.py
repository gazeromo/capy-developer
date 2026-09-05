#!/usr/bin/env python3
"""Independent standard-library validator for copied interaction-aware V1 candidates."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

MEMBERS = ("RELEASE-CANDIDATE.json", "application/application.zip", "application/interaction.json", "evidence/verification.json", "toolchain/authoring-bundle.zip")
STAGES = ("toolchain_install", "check", "interaction_check", "test", "conform", "source_mutation_check", "pack_a", "pack_b", "package_compare", "archive_preserve", "interaction_preserve")
PROCESS = {"toolchain_install", "check", "interaction_check", "test", "conform", "pack_a", "pack_b", "interaction_preserve"}
BUNDLE_SHA256 = "12e492ec2dce11b4227d10bdf9385705a60bc12a88fec0073ff48a87b2a57a57"
WHEEL_SHA256 = "56c9f6c930b21d600a2e8f10da7a3e92f5cfbf1c6d91490d170d1790e5555603"
DEVKIT_COMMIT = "24b6418c0ee2dada5a08f78ff6752bb43f9d8e16"
DEVKIT_SOURCE = "1211861edbb512aaefae8c20b207f590fac34c35"
INTERACTION_SCHEMA = "capy.application-interaction/dev-v0"
HANDOFF = {"verification":"passed","independent_acceptance":"required","interaction_contract":"included_unaccepted","state_migration":"not_assessed","rollback":"not_assessed","runtime_version_digest":"not_assigned","publication":"not_performed","installation":"not_performed","binding":"not_performed","deployment":"not_performed","publisher_signature":"not_present","secret_scan":"not_performed","runtime_import":"not_performed"}
FACT_KEYS = {
    "toolchain_install":{"timed_out"}, "check":{"timed_out","candidate_unchanged"},
    "interaction_check":{"timed_out","candidate_unchanged"}, "test":{"timed_out","candidate_unchanged"},
    "conform":{"timed_out","candidate_unchanged"}, "source_mutation_check":set(),
    "pack_a":{"timed_out","candidate_unchanged"}, "pack_b":{"timed_out","candidate_unchanged"},
    "package_compare":{"sha256_a","sha256_b","size_a","size_b"}, "archive_preserve":{"sha256","size_bytes"},
    "interaction_preserve":{"timed_out","candidate_unchanged","source_sha256","canonical_sha256","canonical_size_bytes"},
}


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exact(value: object, keys: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(label)
    return value


def infos(archive: zipfile.ZipFile, names: tuple[str, ...] | None = None) -> list[zipfile.ZipInfo]:
    values = archive.infolist()
    observed = [item.filename for item in values]
    if len(observed) != len(set(observed)) or (names is not None and tuple(observed) != names):
        raise ValueError("member set/order")
    for item in values:
        path = PurePosixPath(item.filename)
        mode = (item.external_attr >> 16) & 0xFFFF
        if not item.filename or item.is_dir() or path.is_absolute() or ".." in path.parts or "\\" in item.filename or (mode & 0o170000) == 0o120000 or item.flag_bits & 1:
            raise ValueError("unsafe member")
    return values


def outer(values: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name in MEMBERS:
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0)); item.compress_type = zipfile.ZIP_STORED
            item.create_system = 3; item.external_attr = 0o100644 << 16; item.extra = b""; item.comment = b""
            archive.writestr(item, values[name])
    return output.getvalue()


def read_application(payload: bytes) -> tuple[dict, bytes, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = infos(archive)
        if len(members) > 4096 or sum(item.file_size for item in members) > 256 * 1024 * 1024:
            raise ValueError("application bounds")
        if [item.filename for item in members].count("capability.toml") != 1 or [item.filename for item in members].count("interaction.json") != 1:
            raise ValueError("application roots")
        descriptor_bytes = archive.read("capability.toml"); interaction = archive.read("interaction.json")
    return tomllib.loads(descriptor_bytes.decode("utf-8")), descriptor_bytes, interaction


def leaves(schema: dict, prefix: tuple[str, ...] = (), required: bool = True) -> dict[str, tuple[dict, bool]]:
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False or not isinstance(schema.get("properties", {}), dict):
            raise ValueError("open input")
        needed = schema.get("required", [])
        if not isinstance(needed, list): raise ValueError("required")
        result = {}
        for name, child in schema.get("properties", {}).items(): result.update(leaves(child, (*prefix, name), required and name in needed))
        return result
    if schema.get("type") not in {"string","integer","number","boolean"} or not prefix: raise ValueError("input leaf")
    return {".".join(prefix):(schema, required)}


def accepts(value: object, schema: dict) -> bool:
    kind = schema.get("type")
    return ((kind == "string" and isinstance(value, str) and ("enum" not in schema or value in schema["enum"])) or
            (kind == "boolean" and type(value) is bool) or (kind == "integer" and type(value) is int) or
            (kind == "number" and isinstance(value, (int,float)) and not isinstance(value, bool) and (not isinstance(value,float) or math.isfinite(value))))


def result_path(schema: dict, dotted: str) -> dict | None:
    node = schema
    for segment in dotted.split("."):
        if node.get("type") != "object" or segment not in node.get("properties", {}): return None
        node = node["properties"][segment]
    return node


def validate_interaction(descriptor: dict, source: bytes, projection: bytes) -> dict:
    document = json.loads(source)
    if canonical(document) != projection or len(source) > 64 * 1024: raise ValueError("interaction canonical")
    exact(document, {"schema","application_id","title","purpose","not_for","operation","boundaries"}, "interaction shape")
    if document["schema"] != INTERACTION_SCHEMA or document["application_id"] != descriptor.get("id"): raise ValueError("interaction identity")
    if descriptor.get("schema") != "capy.script/dev-v0" or descriptor.get("state_required") is not False or descriptor.get("connections") != [] or descriptor.get("side_effect") not in {"read_only","artifact_generation"}: raise ValueError("eligibility")
    operation = exact(document["operation"], {"operation_id","title","user_outcome","description","request_fields","resource_fields","examples","common_misunderstandings","result"}, "operation")
    if re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", str(operation["operation_id"])) is None: raise ValueError("operation id")
    expected = leaves(descriptor["input_schema"]); observed = set()
    request_keys = {"field_id","label","description","required","input_kind","safe_default","examples","clarification_question"}
    for field in operation["request_fields"]:
        exact(field, request_keys, "request field"); field_id = field["field_id"]
        if field_id in observed or field_id not in expected: raise ValueError("request coverage")
        observed.add(field_id); rule, required = expected[field_id]
        kinds = {"string":({"choice"} if "enum" in rule else {"text","long_text"}),"integer":{"number"},"number":{"number"},"boolean":{"boolean"}}[rule["type"]]
        if type(field["required"]) is not bool or field["required"] is not required or field["input_kind"] not in kinds: raise ValueError("request semantics")
        if (required and field["safe_default"] is not None) or (field["safe_default"] is not None and not accepts(field["safe_default"], rule)): raise ValueError("default")
    if observed != set(expected): raise ValueError("missing request")
    resources = {item["name"]:item for item in descriptor["resources"]}; observed = set()
    resource_keys = {"slot","label","description","required","minimum_count","maximum_count","input_kind","examples","clarification_question"}
    for field in operation["resource_fields"]:
        exact(field, resource_keys, "resource field"); slot = field["slot"]
        if slot in observed or slot not in resources: raise ValueError("resource coverage")
        observed.add(slot); rule = resources[slot]
        if (field["required"],field["minimum_count"],field["maximum_count"],field["input_kind"]) != (rule["required"],rule["min_items"],rule["max_items"],"file"): raise ValueError("resource semantics")
    if observed != set(resources): raise ValueError("missing resource")
    result = exact(operation["result"], {"presentation","facts","artifacts"}, "result"); facts = set()
    for fact in result["facts"]:
        exact(fact,{"path","label"},"fact")
        if fact["path"] in facts: raise ValueError("fact duplicate")
        facts.add(fact["path"]); node = result_path(descriptor["result_schema"], fact["path"])
        if node is None or node.get("type") not in {"string","integer","number","boolean"}: raise ValueError("fact unknown")
    filenames = []
    for artifact in result["artifacts"]:
        exact(artifact,{"filename","label"},"artifact"); filename = artifact["filename"]
        if not isinstance(filename,str) or len(filename) > 120 or filename in filenames or filename in {".",".."} or filename.startswith(".") or "/" in filename or "\\" in filename or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in filename): raise ValueError("artifact filename")
        filenames.append(filename)
    node = descriptor["result_schema"].get("properties",{}).get("artifact_filenames",{}); expected_files = node.get("items",{}).get("enum") if node.get("type") == "array" else None
    if descriptor["side_effect"] == "read_only" and filenames: raise ValueError("read-only artifacts")
    if descriptor["side_effect"] == "artifact_generation" and filenames != expected_files: raise ValueError("artifact mismatch")
    if result["presentation"] != ("artifact_result" if filenames else "facts"): raise ValueError("presentation")
    boundaries = document["boundaries"]
    if not isinstance(boundaries,list) or not boundaries: raise ValueError("boundaries")
    for boundary in boundaries:
        exact(boundary,{"boundary_id","request_class","explanation","nearest_operation_ids"},"boundary")
        if boundary["nearest_operation_ids"] != [operation["operation_id"]]: raise ValueError("boundary operation")
    return {"schema":document["schema"],"operation_id":operation["operation_id"]}


def validate(payload: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        outer_infos = infos(archive, MEMBERS)
        if archive.comment or any(item.date_time != (1980,1,1,0,0,0) or item.compress_type != zipfile.ZIP_STORED or item.create_system != 3 or ((item.external_attr >> 16)&0xFFFF) != 0o100644 or item.extra or item.comment for item in outer_infos): raise ValueError("outer metadata")
        values = {name:archive.read(name) for name in MEMBERS}
    if outer(values) != payload: raise ValueError("outer bytes")
    manifest = json.loads(values[MEMBERS[0]]); receipt = json.loads(values[MEMBERS[3]])
    if canonical(manifest) != values[MEMBERS[0]] or canonical(receipt) != values[MEMBERS[3]]: raise ValueError("canonical metadata")
    exact(manifest,{"schema","release_candidate_id","identity_sha256","project","source","application","toolchain","verification","handoff","verified_at"},"manifest")
    exact(receipt,{"schema","pipeline","verification_id","status","classification","session_id","project_id","application_id","source","toolchain","interaction_contract","stages","application_archive","verified_at"},"receipt")
    if manifest["schema"] != "capy.application-release-candidate/v1" or receipt["schema"] != "capy.development-verification-receipt/v1" or receipt["pipeline"] != "capy.development-verification-pipeline/v1" or manifest["handoff"] != HANDOFF: raise ValueError("schemas/claims")
    app = exact(manifest["application"],{"id","contract","descriptor_sha256","archive","interaction"},"application")
    interaction = exact(app["interaction"],{"schema","source_member","source_sha256","member","sha256","size_bytes","operation_id"},"interaction binding")
    bindings = ((app["archive"],MEMBERS[1]),(interaction,MEMBERS[2]),(manifest["verification"]["receipt"],MEMBERS[3]),(manifest["toolchain"]["authoring_bundle"],MEMBERS[4]))
    for binding,name in bindings:
        if binding.get("member") != name or binding.get("sha256") != digest(values[name]) or binding.get("size_bytes") != len(values[name]): raise ValueError("member binding")
    descriptor, descriptor_bytes, source_interaction = read_application(values[MEMBERS[1]])
    if app["descriptor_sha256"] != digest(descriptor_bytes) or app["id"] != descriptor.get("id") or app["contract"] != descriptor.get("schema"): raise ValueError("descriptor binding")
    checked = validate_interaction(descriptor, source_interaction, values[MEMBERS[2]])
    if interaction["schema"] != checked["schema"] or interaction["operation_id"] != checked["operation_id"] or interaction["source_member"] != "interaction.json" or interaction["source_sha256"] != digest(source_interaction): raise ValueError("interaction binding")
    with zipfile.ZipFile(io.BytesIO(values[MEMBERS[4]])) as bundle:
        infos(bundle); release = json.loads(bundle.read("RELEASE-MANIFEST.json")); wheel = bundle.read("wheel/"+release["wheel_filename"])
    if digest(values[MEMBERS[4]]) != BUNDLE_SHA256 or digest(wheel) != WHEEL_SHA256 or release.get("schema") != "capy.devkit-authoring-bundle/v1" or release.get("source_commit") != DEVKIT_SOURCE or release.get("interaction_contract") != INTERACTION_SCHEMA: raise ValueError("toolchain bytes")
    if [stage.get("name") for stage in receipt["stages"]] != list(STAGES) or any(stage.get("status") != "PASSED" for stage in receipt["stages"]): raise ValueError("stages")
    stage_keys = {"name","status","exit_code","stored_stdout_sha256","stored_stdout_bytes","stored_stderr_sha256","stored_stderr_bytes","stdout_truncated_bytes","stderr_truncated_bytes","facts"}
    for stage in receipt["stages"]:
        exact(stage,stage_keys,"stage"); facts = exact(stage["facts"],FACT_KEYS[stage["name"]],"stage facts")
        if (stage["name"] in PROCESS and stage["exit_code"] != 0) or (stage["name"] not in PROCESS and stage["exit_code"] is not None) or facts.get("timed_out") is True or facts.get("candidate_unchanged") is False: raise ValueError("passed stage")
    preserved = {"sha256":app["archive"]["sha256"],"size_bytes":app["archive"]["size_bytes"]}; stage_facts = {stage["name"]:stage["facts"] for stage in receipt["stages"]}
    if stage_facts["archive_preserve"] != preserved or stage_facts["package_compare"]["sha256_a"] != preserved["sha256"] or stage_facts["interaction_preserve"]["source_sha256"] != interaction["source_sha256"] or stage_facts["interaction_preserve"]["canonical_sha256"] != interaction["sha256"]: raise ValueError("preservation")
    receipt_interaction = {"schema":interaction["schema"],"source_member":interaction["source_member"],"source_sha256":interaction["source_sha256"],"canonical_sha256":interaction["sha256"],"canonical_size_bytes":interaction["size_bytes"],"operation_id":interaction["operation_id"]}
    if receipt["interaction_contract"] != receipt_interaction or receipt["application_archive"] != preserved or receipt["verification_id"] != manifest["verification"]["verification_id"] or receipt["project_id"] != manifest["project"]["project_id"] or receipt["application_id"] != app["id"] or receipt["verified_at"] != manifest["verified_at"]: raise ValueError("receipt binding")
    tool = manifest["toolchain"]
    if tool.get("release_binding_commit") != DEVKIT_COMMIT or tool.get("implementation_commit") != DEVKIT_SOURCE or tool.get("wheel_sha256") != WHEEL_SHA256 or tool.get("interaction_contract") != INTERACTION_SCHEMA: raise ValueError("manifest toolchain")
    identity_object = {"schema":manifest["schema"],"project_id":manifest["project"]["project_id"],"application_id":app["id"],"source":manifest["source"],"application_archive_sha256":app["archive"]["sha256"],"application_descriptor_sha256":app["descriptor_sha256"],"interaction":{"schema":interaction["schema"],"source_sha256":interaction["source_sha256"],"canonical_sha256":interaction["sha256"],"operation_id":interaction["operation_id"]},"verification_receipt_sha256":manifest["verification"]["receipt"]["sha256"],"toolchain":{"release_binding_commit":tool["release_binding_commit"],"authoring_bundle_sha256":tool["authoring_bundle"]["sha256"],"wheel_sha256":tool["wheel_sha256"],"interaction_contract":tool["interaction_contract"]}}
    identity = digest(canonical(identity_object)); candidate_id = "rc_"+identity[:32]
    if manifest["identity_sha256"] != identity or manifest["release_candidate_id"] != candidate_id: raise ValueError("identity")
    return {"schema":"capy.development-release-candidate-oracle/v1","status":"accepted","release_candidate_id":candidate_id,"identity_sha256":identity,"manifest_sha256":digest(values[MEMBERS[0]]),"interaction_sha256":digest(values[MEMBERS[2]]),"bundle_sha256":digest(payload),"bundle_size_bytes":len(payload)}


def main(arguments: list[str]) -> int:
    try:
        if len(arguments) != 1: raise ValueError("provide one candidate")
        result = validate(Path(arguments[0]).read_bytes())
    except Exception as exc:
        print(json.dumps({"schema":"capy.development-release-candidate-oracle/v1","status":"rejected","error":type(exc).__name__},sort_keys=True)); return 1
    print(json.dumps(result,sort_keys=True)); return 0


if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
