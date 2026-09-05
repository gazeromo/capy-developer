from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.errors import DeveloperError
from capy_developer.git import run_git
from capy_developer.mcp import handle
from capy_developer.cli import main as cli_main
from capy_developer.database import Database, SCHEMA_VERSION
from capy_developer.release_candidate import (
    MEMBERS,
    _identity_from_manifest,
    _zip_bytes,
    canonical_json,
    digest_bytes,
    inspect_authoring_bundle,
    validate_bundle_bytes,
)
from capy_developer.toolchain import (
    HISTORICAL_BUNDLE_SHA256,
    HISTORICAL_DEVKIT_MAIN,
    HISTORICAL_WHEEL_SHA256,
    PREVIOUS_BUNDLE_SHA256,
    PREVIOUS_DEVKIT_MAIN,
    PREVIOUS_WHEEL_SHA256,
)


def file_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    return Path(url2pathname(parsed.path))


def rebind_receipt(payload: bytes, mutate) -> bytes:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        values = {name: archive.read(name) for name in MEMBERS}
    receipt = json.loads(values[MEMBERS[2]])
    mutate(receipt)
    values[MEMBERS[2]] = canonical_json(receipt)
    manifest = json.loads(values[MEMBERS[0]])
    manifest["verification"]["receipt"]["sha256"] = digest_bytes(values[MEMBERS[2]])
    manifest["verification"]["receipt"]["size_bytes"] = len(values[MEMBERS[2]])
    identity_sha256 = digest_bytes(canonical_json(_identity_from_manifest(manifest)))
    manifest["identity_sha256"] = identity_sha256
    manifest["release_candidate_id"] = "rc_" + identity_sha256[:32]
    values[MEMBERS[0]] = canonical_json(manifest)
    return _zip_bytes(values)


class ReleaseCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rc-test-")
        self.root = Path(self.temporary.name)
        self.verification_temp = Path("/tmp") / self.root.name
        self.config = Config(
            self.root / "state", self.root / "cache", self.root / "repositories",
            self.root / "worktrees", self.verification_temp,
        )
        self.core = DeveloperCore(self.config)

    def tearDown(self):
        shutil.rmtree(self.verification_temp, ignore_errors=True)
        self.temporary.cleanup()

    def passed_verification(self) -> tuple[dict, dict]:
        session = self.core.start_development({
            "idempotency_key": "start", "request": "Create a release candidate fixture.",
            "new": {"name": "Candidate Fixture", "application_id": "demo.candidate_fixture"},
        })
        workspace = Path(session["workspace"]["native_path"])
        (workspace / "capy.lock").write_text(
            'schema = "capy.toolchain-lock/v0"\ncontract = "capy.script/dev-v0"\n'
            'devkit_repository = "gazeromo/capy-script-devkit"\n'
            f'devkit_commit = "{PREVIOUS_DEVKIT_MAIN}"\n'
            'wheel = "capy_script_devkit-0.0.0-py3-none-any.whl"\n'
            f'wheel_sha256 = "{PREVIOUS_WHEEL_SHA256}"\n'
            f'authoring_bundle_sha256 = "{PREVIOUS_BUNDLE_SHA256}"\n', encoding="utf-8",
        )
        run_git(["config", "user.name", "Fixture"], cwd=workspace)
        run_git(["config", "user.email", "fixture@localhost"], cwd=workspace)
        run_git(["add", "capy.lock"], cwd=workspace)
        run_git(["commit", "-m", "select accepted V0 toolchain"], cwd=workspace)
        result = self.core.verify_development({
            "session_id": session["session_id"], "application_id": "demo.candidate_fixture",
            "candidate_commit": run_git(["rev-parse", "HEAD"], cwd=workspace), "idempotency_key": "verify",
        })
        self.assertEqual("PASSED", result["status"], json.dumps(result, indent=2))
        return session, result

    def test_frozen_outer_zip_bytes_are_cross_platform_stable(self):
        payloads = {name: f"fixture:{name}".encode() for name in MEMBERS}
        candidate = _zip_bytes(payloads)
        self.assertEqual(673, len(candidate))
        self.assertEqual(
            "5709c4233c1ae6bb6c2801425fc2ac0052738c8b5f5976dea2abd4b2e0763d18",
            __import__("hashlib").sha256(candidate).hexdigest(),
        )

    def test_create_replay_restart_inspect_and_exact_bundle(self):
        session, verification = self.passed_verification()
        workspace = Path(session["workspace"]["native_path"])
        (workspace / "capy.lock").write_text("changed after verification\n", encoding="utf-8")
        created = self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual((True, "READY", "AVAILABLE"), (created["ok"], created["status"], created["bundle"]["current_state"]), json.dumps(created, indent=2))
        candidate_path = file_uri(created["bundle"]["path_uri"])
        validated = validate_bundle_bytes(candidate_path.read_bytes())
        self.assertEqual(created["release_candidate_id"], validated["release_candidate_id"])
        with zipfile.ZipFile(candidate_path) as archive:
            self.assertEqual(list(MEMBERS), archive.namelist())
            manifest = json.loads(archive.read(MEMBERS[0]))
            receipt = json.loads(archive.read(MEMBERS[2]))
        self.assertEqual("required", manifest["handoff"]["independent_acceptance"])
        self.assertNotIn(str(self.root), json.dumps({"manifest": manifest, "receipt": receipt}))
        self.assertEqual(
            ["toolchain_install", "check", "test", "conform", "source_mutation_check", "pack_a", "pack_b", "package_compare", "archive_preserve"],
            [stage["name"] for stage in receipt["stages"]],
        )
        self.assertTrue(all("stdout" not in stage and "stderr" not in stage for stage in receipt["stages"]))
        isolated = self.root / "isolated"
        isolated.mkdir()
        copied = isolated / "candidate.capyrc"
        shutil.copyfile(candidate_path, copied)
        oracle = Path(__file__).parents[1] / "campaigns" / "developer_release_candidate_v0" / "ORACLE.py"
        checked = subprocess.run(
            [sys.executable, str(oracle), str(copied)], cwd=isolated,
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, checked.returncode, checked.stdout + checked.stderr)
        self.assertEqual("accepted", json.loads(checked.stdout)["status"])
        replay = self.core.create_release_candidate(verification["verification_id"])
        restarted = DeveloperCore(self.config).inspect_release_candidate(created["release_candidate_id"])
        self.assertEqual(created["bundle"]["sha256"], replay["bundle"]["sha256"])
        self.assertEqual(created["bundle"]["sha256"], restarted["bundle"]["sha256"])
        self.assertEqual(1, replay["attempt_count"])
        self.core.finish_development(session["session_id"], "COMPLETED")
        after_finish = self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual(created["release_candidate_id"], after_finish["release_candidate_id"])

    def test_failed_verification_is_rejected_without_candidate_state(self):
        session = self.core.start_development({
            "idempotency_key": "start", "request": "Create a broken release candidate fixture.",
            "new": {"name": "Broken Candidate", "application_id": "demo.candidate_fixture"},
        })
        workspace = Path(session["workspace"]["native_path"])
        (workspace / "tests" / "test_main.py").write_text(
            "import unittest\nclass Broken(unittest.TestCase):\n def test_broken(self): self.fail('broken')\n",
            encoding="utf-8",
        )
        run_git(["config", "user.name", "Fixture"], cwd=workspace)
        run_git(["config", "user.email", "fixture@localhost"], cwd=workspace)
        run_git(["add", "--all"], cwd=workspace)
        run_git(["commit", "-m", "broken candidate"], cwd=workspace)
        verification = self.core.verify_development({
            "session_id": session["session_id"], "application_id": "demo.candidate_fixture",
            "candidate_commit": run_git(["rev-parse", "HEAD"], cwd=workspace), "idempotency_key": "verify",
        })
        self.assertEqual("FAILED", verification["status"])
        with self.assertRaises(DeveloperError) as caught:
            self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("VERIFICATION_NOT_PASSED", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_tampered_ready_bundle_is_reported_and_not_rebuilt(self):
        _session, verification = self.passed_verification()
        created = self.core.create_release_candidate(verification["verification_id"])
        candidate_path = file_uri(created["bundle"]["path_uri"])
        candidate_path.write_bytes(candidate_path.read_bytes() + b"tamper")
        inspected = self.core.inspect_release_candidate(created["release_candidate_id"])
        self.assertFalse(inspected["ok"])
        self.assertEqual("DIGEST_MISMATCH", inspected["bundle"]["current_state"])
        replay = self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("DIGEST_MISMATCH", replay["bundle"]["current_state"])

    def test_mcp_precondition_error_and_durable_result_semantics(self):
        missing = handle(self.core, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "capy_release_candidate_create", "arguments": {"verification_id": "ver_missing"}},
        })
        self.assertTrue(missing["result"]["isError"])
        _session, verification = self.passed_verification()
        created = handle(self.core, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "capy_release_candidate_create", "arguments": {"verification_id": verification["verification_id"]}},
        })
        self.assertFalse(created["result"]["isError"])
        self.assertEqual("READY", created["result"]["structuredContent"]["status"])

    def test_validator_rejects_extra_member(self):
        _session, verification = self.passed_verification()
        created = self.core.create_release_candidate(verification["verification_id"])
        original = file_uri(created["bundle"]["path_uri"]).read_bytes()
        with self.assertRaises(DeveloperError):
            validate_bundle_bytes(original + b"trailing corruption")
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as target:
            for info in source.infolist():
                target.writestr(info, source.read(info))
            target.writestr("extra", b"x")
        with self.assertRaises(DeveloperError):
            validate_bundle_bytes(output.getvalue())
        mutated = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(mutated, "w", compression=zipfile.ZIP_STORED) as target:
            for info in source.infolist():
                value = source.read(info)
                if info.filename == MEMBERS[0]:
                    manifest = json.loads(value)
                    manifest["unexpected"] = True
                    value = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
                target.writestr(info, value)
        with self.assertRaises(DeveloperError):
            validate_bundle_bytes(mutated.getvalue())

    def test_authoring_bundle_rejects_oversized_nested_wheel_before_read(self):
        wheel = b"x" * 2048
        manifest = {
            "schema": "capy.devkit-authoring-bundle/v0",
            "wheel_filename": "fixture.whl",
            "wheel_sha256": digest_bytes(wheel),
        }
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("RELEASE-MANIFEST.json", json.dumps(manifest))
            archive.writestr("wheel/fixture.whl", wheel)
        from unittest import mock
        with mock.patch("capy_developer.release_candidate.MAX_TOOLCHAIN_WHEEL_BYTES", 1024):
            with self.assertRaises(DeveloperError) as caught:
                inspect_authoring_bundle(output.getvalue())
        self.assertEqual("TOOLCHAIN_INTEGRITY_FAILED", caught.exception.code)

    def test_validator_and_oracle_reject_digest_consistent_invalid_passed_stage_facts(self):
        _session, verification = self.passed_verification()
        created = self.core.create_release_candidate(verification["verification_id"])
        original = file_uri(created["bundle"]["path_uri"]).read_bytes()
        cases = {
            "nonzero_exit_code": lambda receipt: receipt["stages"][0].__setitem__("exit_code", 7),
            "malformed_boolean_fact": lambda receipt: receipt["stages"][0]["facts"].__setitem__("timed_out", 0),
            "timed_out_passed": lambda receipt: receipt["stages"][0]["facts"].__setitem__("timed_out", True),
            "source_changed_passed": lambda receipt: receipt["stages"][1]["facts"].__setitem__("candidate_unchanged", False),
            "missing_required_fact": lambda receipt: receipt["stages"][1]["facts"].pop("candidate_unchanged"),
            "unequal_package_digest": lambda receipt: receipt["stages"][7]["facts"].__setitem__("sha256_b", "0" * 64),
            "wrong_preserved_archive": lambda receipt: receipt["stages"][8]["facts"].__setitem__("sha256", "0" * 64),
        }
        oracle = Path(__file__).parents[1] / "campaigns" / "developer_release_candidate_v0" / "ORACLE.py"
        for label, mutate in cases.items():
            with self.subTest(label=label):
                payload = rebind_receipt(original, mutate)
                with self.assertRaises(DeveloperError):
                    validate_bundle_bytes(payload)
                candidate = self.root / f"{label}.capyrc"
                candidate.write_bytes(payload)
                checked = subprocess.run(
                    [sys.executable, str(oracle), str(candidate)], text=True,
                    capture_output=True, check=False,
                )
                self.assertNotEqual(0, checked.returncode, checked.stdout + checked.stderr)

    def test_producer_rejects_contradictory_passed_stage_facts(self):
        _session, verification = self.passed_verification()
        with self.core.db.connect() as db:
            row = db.execute(
                "SELECT facts FROM verification_stages WHERE verification_id=? AND stage_name='toolchain_install'",
                (verification["verification_id"],),
            ).fetchone()
            facts = json.loads(row["facts"])
            facts["timed_out"] = True
            db.execute(
                "UPDATE verification_stages SET facts=? WHERE verification_id=? AND stage_name='toolchain_install'",
                (json.dumps(facts), verification["verification_id"]),
            )
        with self.assertRaises(DeveloperError) as caught:
            self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("VERIFICATION_INCOMPLETE", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_cli_create_and_inspect_exit_semantics(self):
        _session, verification = self.passed_verification()
        environment = {
            "CAPY_DEV_DATA_ROOT": str(self.config.data_root),
            "CAPY_DEV_CACHE_ROOT": str(self.config.cache_root),
            "CAPY_DEV_REPOSITORIES_ROOT": str(self.config.repositories_root),
            "CAPY_DEV_WORKTREES_ROOT": str(self.config.worktrees_root),
            "CAPY_DEV_VERIFICATION_TEMP_ROOT": str(self.config.verification_temporary_root),
        }
        from unittest import mock
        with mock.patch.dict("os.environ", environment, clear=False):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(0, cli_main(["release-candidate", "create", "--verification-id", verification["verification_id"], "--json"]))
                with self.core.db.connect() as db:
                    candidate_id = db.execute("SELECT release_candidate_id FROM release_candidates").fetchone()[0]
                self.assertEqual(0, cli_main(["release-candidate", "inspect", "--release-candidate-id", candidate_id, "--json"]))
                self.assertEqual(2, cli_main(["release-candidate", "inspect", "--release-candidate-id", "rc_bad", "--json"]))

    def test_schema_two_migrates_without_losing_verification(self):
        _session, verification = self.passed_verification()
        with self.core.db.connect() as db:
            db.execute("DROP TABLE release_candidate_members")
            db.execute("DROP TABLE release_candidates")
            db.execute("UPDATE metadata SET value='2' WHERE key='schema_version'")
        Database(self.config.database)
        with self.core.db.connect() as db:
            self.assertEqual(str(SCHEMA_VERSION), db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0])
            self.assertEqual(verification["verification_id"], db.execute("SELECT verification_id FROM verification_attempts").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_historical_verification_embeds_historical_toolchain(self):
        _session, verification = self.passed_verification()
        with self.core.db.connect() as db:
            db.execute(
                """UPDATE verification_attempts SET release_binding_commit=?,authoring_bundle_sha256=?,wheel_sha256=?
                   WHERE verification_id=?""",
                (HISTORICAL_DEVKIT_MAIN, HISTORICAL_BUNDLE_SHA256, HISTORICAL_WHEEL_SHA256, verification["verification_id"]),
            )
        created = self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual(HISTORICAL_BUNDLE_SHA256, created["toolchain"]["authoring_bundle_sha256"])
        with zipfile.ZipFile(file_uri(created["bundle"]["path_uri"])) as archive:
            self.assertEqual(HISTORICAL_BUNDLE_SHA256, __import__("hashlib").sha256(archive.read(MEMBERS[3])).hexdigest())

    def test_preflight_fails_closed_without_allocating_candidate(self):
        session, verification = self.passed_verification()
        verification_id = verification["verification_id"]
        archive = file_uri(verification["candidate_archive"]["path_uri"])
        original_archive = archive.read_bytes()
        archive.write_bytes(original_archive + b"tamper")
        with self.assertRaises(DeveloperError) as caught:
            self.core.create_release_candidate(verification_id)
        self.assertEqual("VERIFICATION_ARCHIVE_INTEGRITY_FAILED", caught.exception.code)
        archive.write_bytes(original_archive)

        with self.core.db.connect() as db:
            db.execute("UPDATE verification_stages SET status='FAILED' WHERE verification_id=? AND stage_name='archive_preserve'", (verification_id,))
        with self.assertRaises(DeveloperError) as caught:
            self.core.create_release_candidate(verification_id)
        self.assertEqual("VERIFICATION_INCOMPLETE", caught.exception.code)
        with self.core.db.connect() as db:
            db.execute("UPDATE verification_stages SET status='PASSED' WHERE verification_id=? AND stage_name='archive_preserve'", (verification_id,))
            db.execute("UPDATE sessions SET status='CANCELLED',terminal_disposition='CANCELLED' WHERE session_id=?", (session["session_id"],))
        with self.assertRaises(DeveloperError) as caught:
            self.core.create_release_candidate(verification_id)
        self.assertEqual("DEVELOPMENT_SESSION_INELIGIBLE", caught.exception.code)
        with self.core.db.connect() as db:
            db.execute("UPDATE sessions SET status='READY',terminal_disposition=NULL WHERE session_id=?", (session["session_id"],))

        repository = self.config.repositories_root / f"{session['project']['project_id']}.git"
        unavailable = repository.with_suffix(".unavailable")
        repository.rename(unavailable)
        try:
            with self.assertRaises(DeveloperError) as caught:
                self.core.create_release_candidate(verification_id)
            self.assertEqual("CANDIDATE_SOURCE_UNAVAILABLE", caught.exception.code)
        finally:
            unavailable.rename(repository)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_stale_building_attempt_resumes_same_identity(self):
        _session, verification = self.passed_verification()
        first = self.core.create_release_candidate(verification["verification_id"])
        with self.core.db.connect() as db:
            db.execute(
                "UPDATE release_candidates SET status='BUILDING',classification=NULL,terminal_at=NULL WHERE release_candidate_id=?",
                (first["release_candidate_id"],),
            )
        resumed = self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual(first["release_candidate_id"], resumed["release_candidate_id"])
        self.assertEqual(first["bundle"]["sha256"], resumed["bundle"]["sha256"])
        self.assertEqual(2, resumed["attempt_count"])
        with self.core.db.connect() as db:
            event_types = [row[0] for row in db.execute("SELECT event_type FROM session_events ORDER BY event_id")]
        self.assertIn("RELEASE_CANDIDATE_INTERRUPTED", event_types)
        self.assertIn("RELEASE_CANDIDATE_RESUMED", event_types)

    def test_candidate_create_uses_session_lifecycle_lock(self):
        session, verification = self.passed_verification()
        from capy_developer.util import exclusive_lock
        with exclusive_lock(self.config.verification_lock(session["session_id"]), 0):
            with self.assertRaises(DeveloperError) as caught:
                self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("RELEASE_CANDIDATE_BUSY", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_allocation_rechecks_session_eligibility_transactionally(self):
        session, verification = self.passed_verification()
        service = self.core.release_candidates
        original_allocate = service._allocate

        def cancel_then_allocate(context, existing):
            with self.core.db.connect() as db:
                db.execute(
                    "UPDATE sessions SET status='CANCELLED',terminal_disposition='CANCELLED' WHERE session_id=?",
                    (session["session_id"],),
                )
            return original_allocate(context, existing)

        from unittest import mock
        with mock.patch.object(service, "_allocate", side_effect=cancel_then_allocate):
            with self.assertRaises(DeveloperError) as caught:
                self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("DEVELOPMENT_SESSION_INELIGIBLE", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_empty_unmarked_attempt_directory_from_crash_is_recovered(self):
        _session, verification = self.passed_verification()
        first = self.core.create_release_candidate(verification["verification_id"])
        candidate_id = first["release_candidate_id"]
        with self.core.db.connect() as db:
            db.execute(
                "UPDATE release_candidates SET status='BUILDING',classification=NULL,terminal_at=NULL WHERE release_candidate_id=?",
                (candidate_id,),
            )
        attempt_root = self.config.release_candidate_temporary_root / candidate_id
        attempt_root.mkdir(parents=True)
        resumed = self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("READY", resumed["status"])
        self.assertEqual(2, resumed["attempt_count"])
        self.assertFalse(attempt_root.exists())

    def test_content_addressed_preserve_never_clobbers_racing_conflict(self):
        payload = b"expected candidate bytes"
        digest = digest_bytes(payload)
        destination = self.config.release_candidates_root / digest / "candidate.capyrc"
        real_link = __import__("os").link

        def install_conflict_then_link(source, target):
            Path(target).write_bytes(b"conflicting winner")
            return real_link(source, target)

        from unittest import mock
        with mock.patch("capy_developer.release_candidate.os.link", side_effect=install_conflict_then_link):
            with self.assertRaises(DeveloperError) as caught:
                self.core.release_candidates._preserve(payload, digest)
        self.assertEqual("RELEASE_CANDIDATE_INTEGRITY_FAILED", caught.exception.code)
        self.assertEqual(b"conflicting winner", destination.read_bytes())

    @unittest.skipIf(os.name == "nt", "symlink creation is not guaranteed for Windows CI users")
    def test_content_addressed_preserve_rejects_in_store_symlink_alias(self):
        payload = b"expected candidate bytes"
        digest = digest_bytes(payload)
        digest_root = self.config.release_candidates_root / digest
        digest_root.mkdir(parents=True)
        alias = self.config.release_candidates_root / "mutable-candidate.capyrc"
        alias.write_bytes(payload)
        (digest_root / "candidate.capyrc").symlink_to(alias)
        with self.assertRaises(DeveloperError) as caught:
            self.core.release_candidates._preserve(payload, digest)
        self.assertEqual("RELEASE_CANDIDATE_INTEGRITY_FAILED", caught.exception.code)
