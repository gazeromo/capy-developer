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
MAX_APPLICATION_BYTES = 64 * 1024 * 1024
MAX_APPLICATION_MEMBERS = 4096
MAX_APPLICATION_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_TOOLCHAIN_BYTES = 64 * 1024 * 1024
MAX_TOOLCHAIN_MEMBERS = 4096
MAX_TOOLCHAIN_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_TOOLCHAIN_WHEEL_BYTES = 64 * 1024 * 1024
MAX_RECEIPT_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 130 * 1024 * 1024
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


def exact_pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("duplicate JSON key")
        result[key] = value
    return result


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


def read_application(payload: bytes) -> tuple[dict, bytes, bytes, set[str]]:
    if len(payload) > MAX_APPLICATION_BYTES:
        raise ValueError("application raw bound")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = infos(archive)
        if len(members) > MAX_APPLICATION_MEMBERS or sum(item.file_size for item in members) > MAX_APPLICATION_EXPANDED_BYTES:
            raise ValueError("application bounds")
        if [item.filename for item in members].count("capability.toml") != 1 or [item.filename for item in members].count("interaction.json") != 1:
            raise ValueError("application roots")
        descriptor_bytes = archive.read("capability.toml"); interaction = archive.read("interaction.json")
    return tomllib.loads(descriptor_bytes.decode("utf-8")), descriptor_bytes, interaction, {item.filename for item in members}


def leaves(schema: dict, prefix: tuple[str, ...] = (), required: bool = True) -> dict[str, tuple[dict, bool]]:
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False or not isinstance(schema.get("properties", {}), dict):
            raise ValueError("open input")
        needed = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(needed, list) or any(not isinstance(name,str) for name in needed) or not set(needed) <= set(properties): raise ValueError("required")
        if prefix and not properties: raise ValueError("empty nested input object")
        result = {}
        for name, child in properties.items():
            if re.fullmatch(r"[a-z][a-z0-9_]*", name) is None: raise ValueError("field name")
            result.update(leaves(child, (*prefix, name), required and name in needed))
        return result
    if schema.get("type") not in {"string","integer","number","boolean"} or not prefix: raise ValueError("input leaf")
    if schema.get("type") == "string" and "enum" in schema and (not isinstance(schema["enum"],list) or not schema["enum"] or any(not isinstance(choice,str) for choice in schema["enum"]) or len(set(schema["enum"])) != len(schema["enum"])): raise ValueError("choice field")
    return {".".join(prefix):(schema, required)}


def accepts(value: object, schema: dict) -> bool:
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]: return False
    if kind == "string": return isinstance(value,str) and len(value) >= schema.get("minLength",0) and len(value) <= schema.get("maxLength",len(value)) and ("pattern" not in schema or re.search(schema["pattern"],value) is not None)
    if kind == "boolean": return type(value) is bool
    if kind == "integer": return type(value) is int and value >= schema.get("minimum",value) and value <= schema.get("maximum",value)
    if kind == "number": return isinstance(value,(int,float)) and not isinstance(value,bool) and (not isinstance(value,float) or math.isfinite(value)) and value >= schema.get("minimum",value) and value <= schema.get("maximum",value)
    return False


def text(value: object, maximum: int) -> bool:
    return isinstance(value,str) and 1 <= len(value) <= maximum and value == value.strip() and "\x00" not in value and not any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def text_list(value: object, maximum: int) -> bool:
    return isinstance(value,list) and 1 <= len(value) <= maximum and all(text(item,500) for item in value)


def identifier(value: object) -> bool:
    return isinstance(value,str) and len(value) <= 128 and re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+",value) is not None


def dotted(value: object) -> bool:
    return isinstance(value,str) and len(value) <= 256 and all(re.fullmatch(r"[a-z][a-z0-9_]*",part) is not None for part in value.split("."))


def artifact_name(value: object) -> bool:
    return isinstance(value,str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",value) is not None


def bounded(value: object, depth: int = 0) -> bool:
    if depth > 16: return False
    if isinstance(value,dict): return all(bounded(child,depth+1) for child in value.values())
    if isinstance(value,list): return all(bounded(child,depth+1) for child in value)
    return not isinstance(value,float) or math.isfinite(value)


def check_schema(schema: object) -> None:
    keywords = {"type","required","additionalProperties","properties","items","enum","minItems","maxItems","minLength","maxLength","minimum","maximum","pattern"}
    kinds = {"object","array","string","integer","number","boolean","null"}
    if not isinstance(schema,dict) or not isinstance(schema.get("type"),str) or set(schema)-keywords or schema["type"] not in kinds: raise ValueError("schema")
    if "enum" in schema and (not isinstance(schema["enum"],list) or not schema["enum"]): raise ValueError("schema enum")
    if schema["type"] == "object":
        properties = schema.get("properties",{}); required = schema.get("required",[])
        if not isinstance(properties,dict) or not isinstance(required,list) or any(not isinstance(item,str) for item in required) or not set(required) <= set(properties) or not isinstance(schema.get("additionalProperties",True),bool): raise ValueError("object schema")
        for child in properties.values(): check_schema(child)
    if schema["type"] == "array" and "items" in schema: check_schema(schema["items"])
    for key in ("minItems","maxItems","minLength","maxLength"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0): raise ValueError("schema bound")
    for key in ("minimum","maximum"):
        if key in schema and (not isinstance(schema[key],(int,float)) or isinstance(schema[key],bool)): raise ValueError("schema bound")
    if "pattern" in schema:
        try: re.compile(schema["pattern"])
        except (TypeError,re.error) as exc: raise ValueError("schema pattern") from exc


def validate_descriptor(descriptor: object, member_names: set[str]) -> dict:
    fields = {"schema","id","name","description","entrypoint","side_effect","timeout_seconds","memory_mb","state_required","resources","connections","input_schema","result_schema"}
    if not isinstance(descriptor,dict) or set(descriptor) != fields: raise ValueError("descriptor shape")
    if descriptor["schema"] != "capy.script/dev-v0" or not identifier(descriptor["id"]): raise ValueError("descriptor identity")
    if any(not isinstance(descriptor[key],str) or not descriptor[key].strip() or len(descriptor[key]) > 512 for key in ("name","description")): raise ValueError("descriptor text")
    entrypoint = descriptor["entrypoint"]
    if not isinstance(entrypoint,str) or PurePosixPath(entrypoint).name != entrypoint or entrypoint not in member_names: raise ValueError("entrypoint")
    if descriptor["side_effect"] not in {"read_only","artifact_generation","scope_state_mutation","external_effect"}: raise ValueError("side effect")
    if type(descriptor["timeout_seconds"]) is not int or not 1 <= descriptor["timeout_seconds"] <= 300 or type(descriptor["memory_mb"]) is not int or not 32 <= descriptor["memory_mb"] <= 2048: raise ValueError("descriptor limits")
    if type(descriptor["state_required"]) is not bool or (descriptor["state_required"] and descriptor["side_effect"] not in {"scope_state_mutation","external_effect"}): raise ValueError("descriptor state")
    if not isinstance(descriptor["resources"],list): raise ValueError("resources")
    names = set()
    for item in descriptor["resources"]:
        exact(item,{"name","required","min_items","max_items"},"resource"); name = item["name"]
        if not isinstance(name,str) or re.fullmatch(r"[a-z][a-z0-9_]*",name) is None or name in names: raise ValueError("resource name")
        names.add(name)
        if type(item["required"]) is not bool or type(item["min_items"]) is not int or type(item["max_items"]) is not int or item["min_items"] < 0 or item["max_items"] < item["min_items"] or item["max_items"] > 100 or (item["required"] and item["min_items"] < 1): raise ValueError("resource count")
    if descriptor["connections"] != []: raise ValueError("connections")
    check_schema(descriptor["input_schema"]); check_schema(descriptor["result_schema"])
    return descriptor


def result_path(schema: dict, dotted: str) -> dict | None:
    node = schema
    for segment in dotted.split("."):
        if node.get("type") != "object" or segment not in node.get("properties", {}): return None
        node = node["properties"][segment]
    return node


def validate_interaction(descriptor: dict, source: bytes, projection: bytes, member_names: set[str]) -> dict:
    document = json.loads(source, object_pairs_hook=lambda pairs: exact_pairs(pairs), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if not source or canonical(document) != projection or len(source) > 64 * 1024 or not bounded(document): raise ValueError("interaction canonical")
    exact(document, {"schema","application_id","title","purpose","not_for","operation","boundaries"}, "interaction shape")
    if document["schema"] != INTERACTION_SCHEMA or not identifier(document["application_id"]) or document["application_id"] != descriptor.get("id"): raise ValueError("interaction identity")
    descriptor = validate_descriptor(descriptor, member_names)
    if descriptor.get("state_required") is not False or descriptor.get("side_effect") not in {"read_only","artifact_generation"}: raise ValueError("eligibility")
    if not text(document["title"],120) or not text(document["purpose"],1000) or not text_list(document["not_for"],32): raise ValueError("interaction text")
    operation = exact(document["operation"], {"operation_id","title","user_outcome","description","request_fields","resource_fields","examples","common_misunderstandings","result"}, "operation")
    if not identifier(operation["operation_id"]) or not text(operation["title"],120) or not text(operation["user_outcome"],500) or not text(operation["description"],1000) or not text_list(operation["examples"],16) or not text_list(operation["common_misunderstandings"],16): raise ValueError("operation fields")
    expected = leaves(descriptor["input_schema"]); observed = set()
    request_keys = {"field_id","label","description","required","input_kind","safe_default","examples","clarification_question"}
    if not isinstance(operation["request_fields"],list) or len(operation["request_fields"]) > 64: raise ValueError("request list")
    for field in operation["request_fields"]:
        exact(field, request_keys, "request field"); field_id = field["field_id"]
        if not dotted(field_id) or field_id in observed or field_id not in expected or not text(field["label"],120) or not text(field["description"],1000) or not text_list(field["examples"],16) or not text(field["clarification_question"],500): raise ValueError("request coverage")
        observed.add(field_id); rule, required = expected[field_id]
        kinds = {"string":({"choice"} if "enum" in rule else {"text","long_text"}),"integer":{"number"},"number":{"number"},"boolean":{"boolean"}}[rule["type"]]
        if type(field["required"]) is not bool or field["required"] is not required or field["input_kind"] not in kinds: raise ValueError("request semantics")
        if (required and field["safe_default"] is not None) or (field["safe_default"] is not None and not accepts(field["safe_default"], rule)): raise ValueError("default")
    if observed != set(expected): raise ValueError("missing request")
    resources = {item["name"]:item for item in descriptor["resources"]}; observed = set()
    resource_keys = {"slot","label","description","required","minimum_count","maximum_count","input_kind","examples","clarification_question"}
    if not isinstance(operation["resource_fields"],list) or len(operation["resource_fields"]) > 16: raise ValueError("resource list")
    for field in operation["resource_fields"]:
        exact(field, resource_keys, "resource field"); slot = field["slot"]
        if not isinstance(slot,str) or re.fullmatch(r"[a-z][a-z0-9_]*",slot) is None or slot in observed or slot not in resources or not text(field["label"],120) or not text(field["description"],1000) or not text_list(field["examples"],16) or not text(field["clarification_question"],500): raise ValueError("resource coverage")
        observed.add(slot); rule = resources[slot]
        if type(field["required"]) is not bool or type(field["minimum_count"]) is not int or type(field["maximum_count"]) is not int or (field["required"],field["minimum_count"],field["maximum_count"],field["input_kind"]) != (rule["required"],rule["min_items"],rule["max_items"],"file"): raise ValueError("resource semantics")
    if observed != set(resources): raise ValueError("missing resource")
    result = exact(operation["result"], {"presentation","facts","artifacts"}, "result")
    if not isinstance(result["facts"],list) or len(result["facts"]) > 64 or not isinstance(result["artifacts"],list) or len(result["artifacts"]) > 32 or (not result["facts"] and not result["artifacts"]): raise ValueError("result lists")
    facts = set()
    for fact in result["facts"]:
        exact(fact,{"path","label"},"fact")
        if not dotted(fact["path"]) or fact["path"] in facts or not text(fact["label"],120): raise ValueError("fact duplicate")
        facts.add(fact["path"]); node = result_path(descriptor["result_schema"], fact["path"])
        if node is None or node.get("type") not in {"string","integer","number","boolean"}: raise ValueError("fact unknown")
    filenames = []
    for artifact in result["artifacts"]:
        exact(artifact,{"filename","label"},"artifact"); filename = artifact["filename"]
        if not artifact_name(filename) or filename in filenames or not text(artifact["label"],120): raise ValueError("artifact filename")
        filenames.append(filename)
    node = descriptor["result_schema"].get("properties",{}).get("artifact_filenames",{}); expected_files = node.get("items",{}).get("enum") if node.get("type") == "array" else None
    if descriptor["side_effect"] == "read_only" and filenames: raise ValueError("read-only artifacts")
    if descriptor["side_effect"] == "artifact_generation" and (not isinstance(expected_files,list) or not expected_files or any(not artifact_name(item) for item in expected_files) or len(set(expected_files)) != len(expected_files) or filenames != expected_files): raise ValueError("artifact mismatch")
    if result["presentation"] != ("artifact_result" if filenames else "facts"): raise ValueError("presentation")
    boundaries = document["boundaries"]
    if not isinstance(boundaries,list) or not 1 <= len(boundaries) <= 32: raise ValueError("boundaries")
    seen = set()
    for boundary in boundaries:
        exact(boundary,{"boundary_id","request_class","explanation","nearest_operation_ids"},"boundary")
        if not identifier(boundary["boundary_id"]) or boundary["boundary_id"] in seen or not text(boundary["request_class"],1000) or not text(boundary["explanation"],1000) or not isinstance(boundary["nearest_operation_ids"],list) or not boundary["nearest_operation_ids"] or any(value != operation["operation_id"] for value in boundary["nearest_operation_ids"]): raise ValueError("boundary operation")
        seen.add(boundary["boundary_id"])
    return {"schema":document["schema"],"operation_id":operation["operation_id"]}


def validate(payload: bytes) -> dict:
    if len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError("candidate raw bound")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        outer_infos = infos(archive, MEMBERS)
        if archive.comment or any(item.date_time != (1980,1,1,0,0,0) or item.compress_type != zipfile.ZIP_STORED or item.create_system != 3 or ((item.external_attr >> 16)&0xFFFF) != 0o100644 or item.extra or item.comment for item in outer_infos): raise ValueError("outer metadata")
        values = {name:archive.read(name) for name in MEMBERS}
    if outer(values) != payload: raise ValueError("outer bytes")
    if len(values[MEMBERS[3]]) > MAX_RECEIPT_BYTES:
        raise ValueError("receipt raw bound")
    manifest = json.loads(values[MEMBERS[0]]); receipt = json.loads(values[MEMBERS[3]])
    if canonical(manifest) != values[MEMBERS[0]] or canonical(receipt) != values[MEMBERS[3]]: raise ValueError("canonical metadata")
    exact(manifest,{"schema","release_candidate_id","identity_sha256","project","source","application","toolchain","verification","handoff","verified_at"},"manifest")
    exact(receipt,{"schema","pipeline","verification_id","status","classification","session_id","project_id","application_id","source","toolchain","interaction_contract","stages","application_archive","verified_at"},"receipt")
    if manifest["schema"] != "capy.application-release-candidate/v1" or receipt["schema"] != "capy.development-verification-receipt/v1" or receipt["pipeline"] != "capy.development-verification-pipeline/v1" or manifest["handoff"] != HANDOFF or not isinstance(manifest["verified_at"],str) or not manifest["verified_at"].endswith("Z"): raise ValueError("schemas/claims")
    project = exact(manifest["project"],{"project_id"},"project")
    source = exact(manifest["source"],{"repository","commit","tree","base_commit"},"source")
    repository = exact(source["repository"],{"kind","public_identity","identity_sha256"},"repository")
    app = exact(manifest["application"],{"id","contract","descriptor_sha256","archive","interaction"},"application")
    exact(app["archive"],{"member","sha256","size_bytes"},"archive binding")
    interaction = exact(app["interaction"],{"schema","source_member","source_sha256","member","sha256","size_bytes","operation_id"},"interaction binding")
    tool = exact(manifest["toolchain"],{"release_binding_commit","implementation_commit","authoring_bundle","wheel_filename","wheel_sha256","interaction_contract"},"toolchain")
    exact(tool["authoring_bundle"],{"member","sha256","size_bytes"},"toolchain bundle")
    verification = exact(manifest["verification"],{"verification_id","receipt"},"verification")
    exact(verification["receipt"],{"member","sha256","size_bytes"},"receipt binding")
    exact(receipt["source"],{"commit","tree","base_commit"},"receipt source")
    receipt_tool = exact(receipt["toolchain"],{"contract","interaction_contract","lock_digest","release_binding_commit","implementation_commit","authoring_bundle_sha256","wheel_filename","wheel_sha256"},"receipt toolchain")
    exact(receipt["application_archive"],{"sha256","size_bytes"},"receipt archive")
    hex40 = lambda value:isinstance(value,str) and re.fullmatch(r"[0-9a-f]{40}",value) is not None
    hex64 = lambda value:isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value) is not None
    nonnegative = lambda value:type(value) is int and value >= 0
    if repository["kind"] not in {"local","remote"} or not hex64(repository["identity_sha256"]): raise ValueError("repository identity")
    if repository["kind"] == "local" and repository["public_identity"] is not None: raise ValueError("local identity")
    if repository["kind"] == "remote" and (not isinstance(repository["public_identity"],str) or not repository["public_identity"].startswith("git://") or "@" in repository["public_identity"] or digest(repository["public_identity"].encode()) != repository["identity_sha256"]): raise ValueError("remote identity")
    if re.fullmatch(r"prj_[A-Za-z0-9_]{1,96}",str(project["project_id"])) is None or not identifier(app["id"]) or re.fullmatch(r"ver_[A-Za-z0-9_]{1,124}",str(verification["verification_id"])) is None or re.fullmatch(r"ses_[A-Za-z0-9_]{1,124}",str(receipt["session_id"])) is None or not all(hex40(source[key]) for key in ("commit","tree","base_commit")) or not hex40(tool["release_binding_commit"]) or not hex40(tool["implementation_commit"]): raise ValueError("identity syntax")
    if not all(hex64(value) for value in (app["descriptor_sha256"],app["archive"]["sha256"],interaction["source_sha256"],interaction["sha256"],tool["authoring_bundle"]["sha256"],tool["wheel_sha256"],verification["receipt"]["sha256"],receipt_tool["lock_digest"],receipt["application_archive"]["sha256"])): raise ValueError("digest syntax")
    if not all(nonnegative(value) for value in (app["archive"]["size_bytes"],interaction["size_bytes"],tool["authoring_bundle"]["size_bytes"],verification["receipt"]["size_bytes"],receipt["application_archive"]["size_bytes"])): raise ValueError("size syntax")
    bindings = ((app["archive"],MEMBERS[1]),(interaction,MEMBERS[2]),(manifest["verification"]["receipt"],MEMBERS[3]),(manifest["toolchain"]["authoring_bundle"],MEMBERS[4]))
    for binding,name in bindings:
        if binding.get("member") != name or binding.get("sha256") != digest(values[name]) or binding.get("size_bytes") != len(values[name]): raise ValueError("member binding")
    descriptor, descriptor_bytes, source_interaction, application_members = read_application(values[MEMBERS[1]])
    if app["descriptor_sha256"] != digest(descriptor_bytes) or app["id"] != descriptor.get("id") or app["contract"] != descriptor.get("schema"): raise ValueError("descriptor binding")
    checked = validate_interaction(descriptor, source_interaction, values[MEMBERS[2]], application_members)
    if interaction["schema"] != checked["schema"] or interaction["operation_id"] != checked["operation_id"] or interaction["source_member"] != "interaction.json" or interaction["source_sha256"] != digest(source_interaction): raise ValueError("interaction binding")
    if len(values[MEMBERS[4]]) > MAX_TOOLCHAIN_BYTES:
        raise ValueError("toolchain raw bound")
    with zipfile.ZipFile(io.BytesIO(values[MEMBERS[4]])) as bundle:
        bundle_infos = infos(bundle)
        if len(bundle_infos) > MAX_TOOLCHAIN_MEMBERS or sum(item.file_size for item in bundle_infos) > MAX_TOOLCHAIN_EXPANDED_BYTES:
            raise ValueError("toolchain expanded bound")
        release = json.loads(bundle.read("RELEASE-MANIFEST.json")); wheel_info = bundle.getinfo("wheel/"+release["wheel_filename"])
        if wheel_info.file_size > MAX_TOOLCHAIN_WHEEL_BYTES:
            raise ValueError("toolchain wheel bound")
        wheel = bundle.read(wheel_info)
    if digest(values[MEMBERS[4]]) != BUNDLE_SHA256 or digest(wheel) != WHEEL_SHA256 or release.get("schema") != "capy.devkit-authoring-bundle/v1" or release.get("source_commit") != DEVKIT_SOURCE or release.get("interaction_contract") != INTERACTION_SCHEMA: raise ValueError("toolchain bytes")
    if not isinstance(receipt["stages"],list) or [stage.get("name") for stage in receipt["stages"] if isinstance(stage,dict)] != list(STAGES) or any(not isinstance(stage,dict) or stage.get("status") != "PASSED" for stage in receipt["stages"]): raise ValueError("stages")
    stage_keys = {"name","status","exit_code","stored_stdout_sha256","stored_stdout_bytes","stored_stderr_sha256","stored_stderr_bytes","stdout_truncated_bytes","stderr_truncated_bytes","facts"}
    for stage in receipt["stages"]:
        exact(stage,stage_keys,"stage"); facts = exact(stage["facts"],FACT_KEYS[stage["name"]],"stage facts")
        if not hex64(stage["stored_stdout_sha256"]) or not hex64(stage["stored_stderr_sha256"]) or not all(nonnegative(stage[key]) for key in ("stored_stdout_bytes","stored_stderr_bytes","stdout_truncated_bytes","stderr_truncated_bytes")): raise ValueError("stage output")
        if (stage["name"] in PROCESS and (type(stage["exit_code"]) is not int or stage["exit_code"] != 0)) or (stage["name"] not in PROCESS and stage["exit_code"] is not None) or facts.get("timed_out") is True or facts.get("candidate_unchanged") is False: raise ValueError("passed stage")
        for key,value in facts.items():
            if key in {"timed_out","candidate_unchanged"} and type(value) is not bool: raise ValueError("fact bool")
            if key in {"sha256","sha256_a","sha256_b","source_sha256","canonical_sha256"} and not hex64(value): raise ValueError("fact digest")
            if key in {"size_bytes","size_a","size_b","canonical_size_bytes"} and not nonnegative(value): raise ValueError("fact size")
        if stage["name"] == "package_compare" and (facts["sha256_a"] != facts["sha256_b"] or facts["size_a"] != facts["size_b"]): raise ValueError("package comparison")
    preserved = {"sha256":app["archive"]["sha256"],"size_bytes":app["archive"]["size_bytes"]}; stage_facts = {stage["name"]:stage["facts"] for stage in receipt["stages"]}
    if stage_facts["archive_preserve"] != preserved or stage_facts["package_compare"] != {"sha256_a":preserved["sha256"],"sha256_b":preserved["sha256"],"size_a":preserved["size_bytes"],"size_b":preserved["size_bytes"]} or stage_facts["interaction_preserve"]["source_sha256"] != interaction["source_sha256"] or stage_facts["interaction_preserve"]["canonical_sha256"] != interaction["sha256"] or stage_facts["interaction_preserve"]["canonical_size_bytes"] != interaction["size_bytes"]: raise ValueError("preservation")
    receipt_interaction = {"schema":interaction["schema"],"source_member":interaction["source_member"],"source_sha256":interaction["source_sha256"],"canonical_sha256":interaction["sha256"],"canonical_size_bytes":interaction["size_bytes"],"operation_id":interaction["operation_id"]}
    if receipt["interaction_contract"] != receipt_interaction or receipt["application_archive"] != preserved or receipt["verification_id"] != verification["verification_id"] or receipt["project_id"] != project["project_id"] or receipt["application_id"] != app["id"] or receipt["source"] != {key:source[key] for key in ("commit","tree","base_commit")} or receipt["status"] != "PASSED" or receipt["classification"] != "VERIFIED" or receipt["verified_at"] != manifest["verified_at"]: raise ValueError("receipt binding")
    if tool.get("release_binding_commit") != DEVKIT_COMMIT or tool.get("implementation_commit") != DEVKIT_SOURCE or tool.get("wheel_sha256") != WHEEL_SHA256 or tool.get("interaction_contract") != INTERACTION_SCHEMA: raise ValueError("manifest toolchain")
    if receipt_tool != {"contract":app["contract"],"interaction_contract":interaction["schema"],"lock_digest":receipt_tool["lock_digest"],"release_binding_commit":tool["release_binding_commit"],"implementation_commit":tool["implementation_commit"],"authoring_bundle_sha256":tool["authoring_bundle"]["sha256"],"wheel_filename":tool["wheel_filename"],"wheel_sha256":tool["wheel_sha256"]}: raise ValueError("receipt toolchain")
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
