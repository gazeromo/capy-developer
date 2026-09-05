#!/usr/bin/env python3
"""Run the frozen V1 copied-byte oracle against the required tamper matrix."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import warnings
import zipfile
from pathlib import Path

import ORACLE


def load(payload: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in ORACLE.MEMBERS}


def canonical_change(payload: bytes, member: str, mutate) -> bytes:
    values = load(payload); value = json.loads(values[member]); mutate(value); values[member] = ORACLE.canonical(value)
    return ORACLE.outer(values)


def inner_change(payload: bytes, member: str, mutate) -> bytes:
    values = load(payload); source = io.BytesIO(values[member]); output = io.BytesIO()
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as after:
        for info in before.infolist():
            data = before.read(info); data = mutate(info.filename, data)
            after.writestr(info, data)
    values[member] = output.getvalue(); return ORACLE.outer(values)


def rebuild_inner(payload: bytes, mutate) -> bytes:
    source = io.BytesIO(payload); output = io.BytesIO()
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as after:
        for info in before.infolist():
            after.writestr(info, mutate(info.filename, before.read(info)))
    return output.getvalue()


def coherent_rebind(payload: bytes, *, interaction_mutate=None, descriptor_append: bytes | None = None, descriptor_transform=None, receipt_mutate=None, manifest_mutate=None) -> bytes:
    values = load(payload); manifest = json.loads(values[ORACLE.MEMBERS[0]]); receipt = json.loads(values[ORACLE.MEMBERS[3]])
    if interaction_mutate is not None or descriptor_append is not None or descriptor_transform is not None:
        document = json.loads(values[ORACLE.MEMBERS[2]])
        if interaction_mutate is not None: interaction_mutate(document)
        canonical = ORACLE.canonical(document)
        application = rebuild_inner(values[ORACLE.MEMBERS[1]], lambda name,data: canonical if name == "interaction.json" else (descriptor_transform(data) if name == "capability.toml" and descriptor_transform is not None else (data + descriptor_append if name == "capability.toml" and descriptor_append is not None else data)))
        values[ORACLE.MEMBERS[1]] = application; values[ORACLE.MEMBERS[2]] = canonical
        archive = {"member":ORACLE.MEMBERS[1],"sha256":ORACLE.digest(application),"size_bytes":len(application)}
        binding = manifest["application"]["interaction"]
        binding.update({"source_sha256":ORACLE.digest(canonical),"sha256":ORACLE.digest(canonical),"size_bytes":len(canonical),"operation_id":document["operation"]["operation_id"],"schema":document["schema"]})
        if descriptor_append is not None or descriptor_transform is not None:
            with zipfile.ZipFile(io.BytesIO(application)) as archive_zip:
                manifest["application"]["descriptor_sha256"] = ORACLE.digest(archive_zip.read("capability.toml"))
        manifest["application"]["archive"] = archive
        receipt["application_archive"] = {"sha256":archive["sha256"],"size_bytes":archive["size_bytes"]}
        receipt["interaction_contract"] = {"schema":binding["schema"],"source_member":binding["source_member"],"source_sha256":binding["source_sha256"],"canonical_sha256":binding["sha256"],"canonical_size_bytes":binding["size_bytes"],"operation_id":binding["operation_id"]}
        facts = {stage["name"]:stage["facts"] for stage in receipt["stages"]}
        facts["package_compare"].update({"sha256_a":archive["sha256"],"sha256_b":archive["sha256"],"size_a":archive["size_bytes"],"size_b":archive["size_bytes"]})
        facts["archive_preserve"].update({"sha256":archive["sha256"],"size_bytes":archive["size_bytes"]})
        facts["interaction_preserve"].update({"source_sha256":binding["source_sha256"],"canonical_sha256":binding["sha256"],"canonical_size_bytes":binding["size_bytes"]})
    if receipt_mutate is not None: receipt_mutate(receipt)
    values[ORACLE.MEMBERS[3]] = ORACLE.canonical(receipt)
    manifest["verification"]["receipt"].update({"sha256":ORACLE.digest(values[ORACLE.MEMBERS[3]]),"size_bytes":len(values[ORACLE.MEMBERS[3]])})
    if manifest_mutate is not None: manifest_mutate(manifest)
    app = manifest["application"]; interaction = app["interaction"]; tool = manifest["toolchain"]
    identity_object = {"schema":manifest["schema"],"project_id":manifest["project"]["project_id"],"application_id":app["id"],"source":manifest["source"],"application_archive_sha256":app["archive"]["sha256"],"application_descriptor_sha256":app["descriptor_sha256"],"interaction":{"schema":interaction["schema"],"source_sha256":interaction["source_sha256"],"canonical_sha256":interaction["sha256"],"operation_id":interaction["operation_id"]},"verification_receipt_sha256":manifest["verification"]["receipt"]["sha256"],"toolchain":{"release_binding_commit":tool["release_binding_commit"],"authoring_bundle_sha256":tool["authoring_bundle"]["sha256"],"wheel_sha256":tool["wheel_sha256"],"interaction_contract":tool["interaction_contract"]}}
    identity = ORACLE.digest(ORACLE.canonical(identity_object)); manifest["identity_sha256"] = identity; manifest["release_candidate_id"] = "rc_" + identity[:32]
    values[ORACLE.MEMBERS[0]] = ORACLE.canonical(manifest)
    return ORACLE.outer(values)


def weaken_required_field(payload: bytes, interaction: str) -> bytes:
    values = load(payload)
    document = json.loads(values[interaction])
    required = [field for field in document["operation"]["request_fields"] if field["required"]]
    if not required:
        raise ValueError("required-field tamper needs a control with a required request field")
    required[0]["required"] = False
    values[interaction] = ORACLE.canonical(document)
    return ORACLE.outer(values)


def custom_outer(payload: bytes, names: list[str], *, comment: bytes = b"", tweak=None) -> bytes:
    values = load(payload); output = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        warnings.simplefilter("ignore", UserWarning)
        archive.comment = comment
        for index, name in enumerate(names):
            source = name if name in values else ORACLE.MEMBERS[0]
            info = zipfile.ZipInfo(name, (1980,1,1,0,0,0)); info.compress_type=zipfile.ZIP_STORED; info.create_system=3; info.external_attr=0o100644<<16
            if tweak: tweak(info,index)
            archive.writestr(info, values[source])
    return output.getvalue()


def cases(payload: bytes) -> dict[str, bytes]:
    values = load(payload); manifest = ORACLE.MEMBERS[0]; receipt = ORACLE.MEMBERS[3]; interaction = ORACLE.MEMBERS[2]
    change_manifest = lambda label, fn: canonical_change(payload, manifest, fn)
    change_receipt = lambda label, fn: canonical_change(payload, receipt, fn)
    result = {
        "outer_member_removed": custom_outer(payload,list(ORACLE.MEMBERS[:-1])),
        "outer_member_added": custom_outer(payload,list(ORACLE.MEMBERS)+["extra"]),
        "outer_duplicate_member": custom_outer(payload,list(ORACLE.MEMBERS)+[ORACLE.MEMBERS[-1]]),
        "outer_member_reordered": custom_outer(payload,list(reversed(ORACLE.MEMBERS))),
        "absolute_member_path": custom_outer(payload,["/absolute"]+list(ORACLE.MEMBERS[1:])),
        "parent_traversal_member": custom_outer(payload,["../escape"]+list(ORACLE.MEMBERS[1:])),
        "backslash_member": custom_outer(payload,["bad\\path"]+list(ORACLE.MEMBERS[1:])),
        "symlink_member": custom_outer(payload,list(ORACLE.MEMBERS),tweak=lambda info,index:setattr(info,"external_attr",(0o120777 if index==1 else 0o100644)<<16)),
        "noncanonical_zip_metadata": custom_outer(payload,list(ORACLE.MEMBERS),tweak=lambda info,index:setattr(info,"date_time",(1981,1,1,0,0,0)) if index==0 else None),
        "zip_comment": custom_outer(payload,list(ORACLE.MEMBERS),comment=b"comment"),
        "zip_extra_field": custom_outer(payload,list(ORACLE.MEMBERS),tweak=lambda info,index:setattr(info,"extra",b"\x01\x00\x00\x00") if index==0 else None),
        "manifest_noncanonical_json": ORACLE.outer({**values,manifest:values[manifest]+b" "}),
        "receipt_noncanonical_json": ORACLE.outer({**values,receipt:values[receipt]+b" "}),
        "interaction_noncanonical_json": ORACLE.outer({**values,interaction:json.dumps(json.loads(values[interaction]),indent=2).encode()}),
        "manifest_schema_changed": change_manifest("",lambda value:value.__setitem__("schema","capy.application-release-candidate/v0")),
        "candidate_id_changed": change_manifest("",lambda value:value.__setitem__("release_candidate_id","rc_"+"0"*32)),
        "identity_digest_changed": change_manifest("",lambda value:value.__setitem__("identity_sha256","0"*64)),
        "application_archive_bytes_changed": ORACLE.outer({**values,ORACLE.MEMBERS[1]:values[ORACLE.MEMBERS[1]]+b"x"}),
        "descriptor_bytes_changed": inner_change(payload,ORACLE.MEMBERS[1],lambda name,data:data+b"\n#tamper" if name=="capability.toml" else data),
        "interaction_source_bytes_changed": inner_change(payload,ORACLE.MEMBERS[1],lambda name,data:data+b" " if name=="interaction.json" else data),
        "outer_canonical_interaction_changed": ORACLE.outer({**values,interaction:values[interaction]+b" "}),
        "interaction_source_digest_changed": change_manifest("",lambda value:value["application"]["interaction"].__setitem__("source_sha256","0"*64)),
        "interaction_canonical_digest_changed": change_manifest("",lambda value:value["application"]["interaction"].__setitem__("sha256","0"*64)),
        "interaction_schema_changed": change_manifest("",lambda value:value["application"]["interaction"].__setitem__("schema","changed/v0")),
        "interaction_application_id_changed": ORACLE.outer({**values,interaction:ORACLE.canonical({**json.loads(values[interaction]),"application_id":"demo.changed"})}),
        "operation_id_changed": ORACLE.outer({**values,interaction:ORACLE.canonical({**json.loads(values[interaction]),"operation":{**json.loads(values[interaction])["operation"],"operation_id":"changed.run"}})}),
        "unknown_request_field_inserted": ORACLE.outer({**values,interaction:ORACLE.canonical((lambda doc:(doc["operation"]["request_fields"].append({"field_id":"unknown","label":"Unknown","description":"x","required":False,"input_kind":"text","safe_default":None,"examples":["x"],"clarification_question":"x"}),doc)[1])(json.loads(values[interaction])))}),
        "required_field_weakened": weaken_required_field(payload, interaction),
        "resource_count_changed": ORACLE.outer({**values,interaction:ORACLE.canonical((lambda doc:(doc["operation"]["resource_fields"].append({"slot":"unknown","label":"Unknown","description":"x","required":False,"minimum_count":0,"maximum_count":1,"input_kind":"file","examples":["x"],"clarification_question":"x"}),doc)[1])(json.loads(values[interaction])))}),
        "unknown_result_fact_inserted": ORACLE.outer({**values,interaction:ORACLE.canonical((lambda doc:(doc["operation"]["result"]["facts"].append({"path":"unknown","label":"Unknown"}),doc)[1])(json.loads(values[interaction])))}),
        "artifact_list_changed": ORACLE.outer({**values,interaction:ORACLE.canonical((lambda doc:(doc["operation"]["result"]["artifacts"].append({"filename":"changed.txt","label":"Changed"}),doc)[1])(json.loads(values[interaction])))}),
        "receipt_interaction_digest_changed": change_receipt("",lambda value:value["interaction_contract"].__setitem__("canonical_sha256","0"*64)),
        "interaction_check_stage_removed": change_receipt("",lambda value:value["stages"].pop(2)),
        "interaction_check_stage_failed": change_receipt("",lambda value:value["stages"][2].__setitem__("status","FAILED")),
        "interaction_preserve_stage_removed": change_receipt("",lambda value:value["stages"].pop()),
        "interaction_preserve_stage_failed": change_receipt("",lambda value:value["stages"][-1].__setitem__("status","FAILED")),
        "toolchain_bundle_changed": ORACLE.outer({**values,ORACLE.MEMBERS[4]:values[ORACLE.MEMBERS[4]]+b"x"}),
        "contained_wheel_changed": inner_change(payload,ORACLE.MEMBERS[4],lambda name,data:data+b"x" if name.startswith("wheel/") else data),
        "handoff_independent_acceptance_weakened": change_manifest("",lambda value:value["handoff"].__setitem__("independent_acceptance","not_required")),
        "handoff_interaction_accepted": change_manifest("",lambda value:value["handoff"].__setitem__("interaction_contract","accepted")),
        "handoff_installation_performed": change_manifest("",lambda value:value["handoff"].__setitem__("installation","performed")),
        "handoff_publication_performed": change_manifest("",lambda value:value["handoff"].__setitem__("publication","performed")),
        "handoff_deployment_performed": change_manifest("",lambda value:value["handoff"].__setitem__("deployment","performed")),
        "coherent_empty_title": coherent_rebind(payload,interaction_mutate=lambda value:value.__setitem__("title","")),
        "coherent_failed_receipt": coherent_rebind(payload,receipt_mutate=lambda value:value.__setitem__("status","FAILED")),
        "coherent_malformed_output_digest": coherent_rebind(payload,receipt_mutate=lambda value:value["stages"][0].__setitem__("stored_stdout_sha256","not-a-sha256")),
        "coherent_negative_output_size": coherent_rebind(payload,receipt_mutate=lambda value:value["stages"][0].__setitem__("stored_stdout_bytes",-1)),
        "coherent_oversized_receipt": coherent_rebind(
            payload,
            receipt_mutate=lambda value:value.__setitem__("verified_at", "x" * ORACLE.MAX_RECEIPT_BYTES + "Z"),
            manifest_mutate=lambda value:value.__setitem__("verified_at", "x" * ORACLE.MAX_RECEIPT_BYTES + "Z"),
        ),
        "coherent_integer_source_commit": coherent_rebind(
            payload,
            receipt_mutate=lambda value:value["source"].__setitem__("commit", int("1" * 40)),
            manifest_mutate=lambda value:value["source"].__setitem__("commit", int("1" * 40)),
        ),
        "coherent_integer_lock_digest": coherent_rebind(
            payload,
            receipt_mutate=lambda value:value["toolchain"].__setitem__("lock_digest", int("1" * 64)),
        ),
        "coherent_manifest_wheel_filename": coherent_rebind(
            payload,
            receipt_mutate=lambda value:value["toolchain"].__setitem__("wheel_filename", "bogus.whl"),
            manifest_mutate=lambda value:value["toolchain"].__setitem__("wheel_filename", "bogus.whl"),
        ),
        "coherent_manifest_local_path": coherent_rebind(payload,manifest_mutate=lambda value:value["application"]["archive"].__setitem__("local_path","/tmp/secret")),
        "coherent_repository_kind": coherent_rebind(payload,manifest_mutate=lambda value:value["source"]["repository"].__setitem__("kind","bogus")),
        "coherent_empty_nested_input_object": coherent_rebind(payload,descriptor_append=b'\n[input_schema.properties.options]\ntype = "object"\nadditionalProperties = false\n'),
        "coherent_nonstring_choice_enum": coherent_rebind(
            payload,
            interaction_mutate=lambda value: value["operation"]["request_fields"][0].__setitem__("input_kind", "choice"),
            descriptor_transform=lambda data: data.replace(
                b'[input_schema.properties.text]\ntype = "string"\nminLength = 1',
                b'[input_schema.properties.text]\ntype = "string"\nminLength = 1\nenum = [1]',
            ),
        ),
        "coherent_empty_artifact_enum": coherent_rebind(
            payload,
            interaction_mutate=lambda value: (
                value["operation"]["result"].__setitem__("artifacts", []),
                value["operation"]["result"].__setitem__("presentation", "facts"),
            ),
            descriptor_transform=lambda data: data.replace(b'enum = ["text-report.txt"]', b'enum = []'),
        ),
        "coherent_duplicate_descriptor_resource": coherent_rebind(
            payload,
            interaction_mutate=lambda value: value["operation"]["resource_fields"].append({
                "slot":"source", "label":"Source", "description":"Source file.",
                "required":False, "minimum_count":0, "maximum_count":1,
                "input_kind":"file", "examples":["source.txt"],
                "clarification_question":"Which source file?",
            }),
            descriptor_transform=lambda data: data.replace(
                b"resources = []",
                b'[[resources]]\nname = "source"\nrequired = false\nmin_items = 0\nmax_items = 1\n\n[[resources]]\nname = "source"\nrequired = false\nmin_items = 0\nmax_items = 1',
            ),
        ),
    }
    return result


def main(arguments: list[str]) -> int:
    if len(arguments) != 1: return 2
    payload = Path(arguments[0]).read_bytes(); failures = []
    ORACLE.validate(payload)
    tampered = cases(payload)
    with tempfile.TemporaryDirectory(prefix="capy-v1-tamper-") as temporary:
        for name, value in tampered.items():
            try: ORACLE.validate(value)
            except Exception: continue
            failures.append(name)
    print(json.dumps({"schema":"capy.development-release-candidate-tamper-matrix/v1","valid_control":"accepted","cases":len(tampered),"rejected":len(tampered)-len(failures),"unexpected_accepts":failures},sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__": raise SystemExit(main(sys.argv[1:]))
