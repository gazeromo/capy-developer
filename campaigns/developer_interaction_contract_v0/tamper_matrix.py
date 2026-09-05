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
        "required_field_weakened": change_manifest("",lambda value:value["application"]["interaction"].__setitem__("operation_id","changed.run")),
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
