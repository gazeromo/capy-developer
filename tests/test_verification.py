from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.database import Database, SCHEMA_VERSION
from capy_developer.errors import DeveloperError
from capy_developer.git import run_git
from capy_developer.mcp import handle
from capy_developer.process import OUTPUT_LIMIT, ProcessResult, _bounded, run_process
from capy_developer.toolchain import ACCEPTED_WHEEL_SHA256
from capy_developer.util import exclusive_lock


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cv-test-")
        self.root = Path(self.temporary.name)
        self.config = Config(self.root / "s", self.root / "c", self.root / "r", self.root / "w")
        self.core = DeveloperCore(self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def start(self, key: str = "start") -> tuple[dict, Path]:
        session = self.core.start_development({
            "idempotency_key": key,
            "request": "Create a portable test application.",
            "new": {"name": "Verify Fixture", "application_id": "demo.verify_fixture"},
        })
        workspace = Path(session["workspace"]["native_path"])
        run_git(["config", "user.name", "Fixture"], cwd=workspace)
        run_git(["config", "user.email", "fixture@localhost"], cwd=workspace)
        return session, workspace

    def payload(self, session: dict, workspace: Path, key: str = "verify") -> dict:
        return {
            "session_id": session["session_id"],
            "application_id": "demo.verify_fixture",
            "candidate_commit": run_git(["rev-parse", "HEAD"], cwd=workspace),
            "idempotency_key": key,
        }

    def commit(self, workspace: Path, message: str = "candidate") -> str:
        run_git(["add", "--all"], cwd=workspace)
        run_git(["commit", "-m", message], cwd=workspace)
        return run_git(["rev-parse", "HEAD"], cwd=workspace)

    def test_full_pipeline_passes_replays_after_restart_and_preserves_archive(self):
        session, workspace = self.start()
        payload = self.payload(session, workspace)
        first = self.core.verify_development(payload)
        self.assertEqual((True, "PASSED", "VERIFIED"), (first["ok"], first["status"], first["classification"]))
        self.assertEqual(9, len(first["stages"]))
        self.assertTrue(all(stage["status"] == "PASSED" for stage in first["stages"]))
        self.assertEqual(2, first["candidate_archive"]["byte_identical_builds"])
        archive = Path(first["candidate_archive"]["path_uri"].removeprefix("file://"))
        self.assertTrue(archive.is_file())
        restarted = DeveloperCore(self.config)
        second = restarted.verify_development(payload)
        self.assertEqual(first["verification_id"], second["verification_id"])
        self.assertEqual("VERIFIED", restarted.inspect_development(session["session_id"])["verification"]["current_head_state"])
        with restarted.db.connect() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM verification_attempts").fetchone()[0])
        final = restarted.finish_development(session["session_id"], "COMPLETED")
        self.assertEqual(first["verification_id"], final["verification"]["latest"]["verification_id"])
        self.assertTrue(archive.is_file())

    def test_failed_unit_test_is_completed_result_and_mcp_not_tool_error(self):
        session, workspace = self.start()
        (workspace / "tests" / "test_main.py").write_text(
            "import unittest\nclass Broken(unittest.TestCase):\n def test_broken(self): self.fail('deterministic')\n",
            encoding="utf-8",
        )
        self.commit(workspace)
        payload = self.payload(session, workspace)
        response = handle(self.core, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "capy_development_verify", "arguments": payload},
        })
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual("FAILED", result["structuredContent"]["status"])
        self.assertEqual("APPLICATION_TESTS_FAILED", result["structuredContent"]["classification"])
        self.assertIsNone(result["structuredContent"]["candidate_archive"])

    def test_dirty_and_wrong_commit_preconditions_allocate_no_attempt(self):
        session, workspace = self.start()
        payload = self.payload(session, workspace)
        (workspace / "untracked.txt").write_text("dirty", encoding="utf-8")
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(payload)
        self.assertEqual("WORKTREE_DIRTY", caught.exception.code)
        (workspace / "untracked.txt").unlink()
        payload["candidate_commit"] = "0" * 40
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(payload)
        self.assertEqual("CANDIDATE_COMMIT_MISMATCH", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM verification_attempts").fetchone()[0])

    def test_unbound_toolchain_is_truthful_and_never_substituted(self):
        session, workspace = self.start()
        (workspace / "capy.lock").unlink()
        self.commit(workspace, "remove lock")
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(self.payload(session, workspace))
        self.assertEqual("TOOLCHAIN_LOCK_UNBOUND", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM verification_attempts").fetchone()[0])

    def test_historical_unavailable_toolchain_is_not_upgraded(self):
        session, workspace = self.start()
        (workspace / "capy.lock").write_text(
            'schema = "capy.toolchain-lock/v0"\ncontract = "capy.script/dev-v0"\n'
            'devkit_repository = "gazeromo/capy-script-devkit"\n'
            f'devkit_commit = "{"1" * 40}"\nwheel = "historical.whl"\n'
            f'wheel_sha256 = "{"2" * 64}"\nauthoring_bundle_sha256 = "{"3" * 64}"\n',
            encoding="utf-8",
        )
        self.commit(workspace, "historical lock")
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(self.payload(session, workspace))
        self.assertEqual("TOOLCHAIN_UNAVAILABLE", caught.exception.code)
        self.assertNotEqual(ACCEPTED_WHEEL_SHA256, "2" * 64)

    def test_source_mutation_is_causal_failure(self):
        session, workspace = self.start()
        (workspace / "tests" / "test_main.py").write_text(
            "import unittest\nfrom pathlib import Path\n"
            "class Mutating(unittest.TestCase):\n"
            " def test_mutates(self): Path('generated.txt').write_text('x'); self.assertTrue(True)\n",
            encoding="utf-8",
        )
        self.commit(workspace, "mutating test")
        result = self.core.verify_development(self.payload(session, workspace))
        self.assertEqual("SOURCE_MUTATED_DURING_VERIFICATION", result["classification"])
        self.assertEqual("FAILED", result["status"])
        self.assertIsNone(result["candidate_archive"])

    def test_verified_state_becomes_stale_after_edit(self):
        session, workspace = self.start()
        result = self.core.verify_development(self.payload(session, workspace))
        self.assertEqual("PASSED", result["status"])
        (workspace / "README.md").write_text("edited\n", encoding="utf-8")
        inspected = self.core.inspect_development(session["session_id"])
        self.assertEqual("STALE", inspected["verification"]["current_head_state"])

    def test_same_key_different_candidate_conflicts(self):
        session, workspace = self.start()
        payload = self.payload(session, workspace)
        self.core.verify_development(payload)
        (workspace / "README.md").write_text("next\n", encoding="utf-8")
        payload["candidate_commit"] = self.commit(workspace, "next")
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(payload)
        self.assertEqual("IDEMPOTENCY_CONFLICT", caught.exception.code)

    def test_replay_does_not_execute_processes_and_reports_missing_archive(self):
        session, workspace = self.start()
        payload = self.payload(session, workspace)
        first = self.core.verify_development(payload)
        archive = Path(first["candidate_archive"]["path_uri"].removeprefix("file://"))
        archive.unlink()
        with mock.patch("capy_developer.verification.run_process") as runner:
            replay = self.core.verify_development(payload)
        runner.assert_not_called()
        self.assertEqual(first["verification_id"], replay["verification_id"])
        self.assertFalse(replay["candidate_archive"]["available"])

    def test_fixed_stage_failures_are_causally_classified(self):
        cases = {
            3: "DEVKIT_CHECK_FAILED",
            4: "APPLICATION_TESTS_FAILED",
            5: "CONFORMANCE_FAILED",
        }
        for failed_call, classification in cases.items():
            with self.subTest(classification=classification):
                session, workspace = self.start(f"start-{failed_call}")
                calls = 0

                def runner(*args, **kwargs):
                    nonlocal calls
                    current = calls
                    calls += 1
                    code = 2 if current == failed_call else 0
                    return ProcessResult(code, "out", "err" if code else "", 0, 0, 1, False)

                with mock.patch("capy_developer.verification.run_process", side_effect=runner):
                    result = self.core.verify_development(self.payload(session, workspace, f"verify-{failed_call}"))
                self.assertEqual(classification, result["classification"])
                self.assertEqual("FAILED", result["status"])

    def test_stage_timeout_is_causal_and_skips_dependents(self):
        session, workspace = self.start()
        calls = 0

        def runner(*args, **kwargs):
            nonlocal calls
            current = calls
            calls += 1
            return ProcessResult(None if current == 3 else 0, "", "", 0, 0, 1, current == 3)

        with mock.patch("capy_developer.verification.run_process", side_effect=runner):
            result = self.core.verify_development(self.payload(session, workspace))
        self.assertEqual("STAGE_TIMEOUT", result["classification"])
        self.assertEqual("FAILED", result["stages"][1]["status"])
        self.assertTrue(all(item["status"] == "SKIPPED" for item in result["stages"][2:]))

    def test_nonidentical_pack_bytes_are_rejected(self):
        session, workspace = self.start()
        calls = 0

        def runner(arguments, **kwargs):
            nonlocal calls
            current = calls
            calls += 1
            if current in {6, 7}:
                Path(arguments[-1]).write_bytes(b"a" if current == 6 else b"b")
            return ProcessResult(0, "", "", 0, 0, 1, False)

        with mock.patch("capy_developer.verification.run_process", side_effect=runner):
            result = self.core.verify_development(self.payload(session, workspace))
        self.assertEqual("PACKAGE_NOT_REPRODUCIBLE", result["classification"])
        self.assertEqual("FAILED", result["status"])
        self.assertIsNone(result["candidate_archive"])

    def test_separate_sessions_can_verify_concurrently(self):
        first, first_workspace = self.start("parallel-a")
        second, second_workspace = self.start("parallel-b")
        payloads = [self.payload(first, first_workspace, "parallel-verify-a"), self.payload(second, second_workspace, "parallel-verify-b")]
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.core.verify_development, payloads))
        self.assertEqual(["PASSED", "PASSED"], [item["status"] for item in results])
        self.assertNotEqual(results[0]["verification_id"], results[1]["verification_id"])

    def test_child_environment_drops_ambient_secrets_and_python_overrides(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "secret", "PYTHONPATH": "/unsafe", "GIT_ASKPASS": "unsafe"}):
            environment = self.core.verifications._environment(self.root / "home", self.root / "tmp")
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("GIT_ASKPASS", environment)
        self.assertEqual("1", environment["PIP_NO_INDEX"])

    def test_live_session_lock_returns_busy_and_blocks_finish(self):
        session, workspace = self.start()
        lock = self.config.verification_lock(session["session_id"])
        with exclusive_lock(lock, 0):
            with self.assertRaises(DeveloperError) as caught:
                self.core.verify_development(self.payload(session, workspace))
            self.assertEqual("VERIFICATION_BUSY", caught.exception.code)
            with self.assertRaises(DeveloperError) as caught:
                self.core.finish_development(session["session_id"], "COMPLETED")
            self.assertEqual("VERIFICATION_BUSY", caught.exception.code)

    def test_abandoned_running_attempt_becomes_interrupted(self):
        session, workspace = self.start()
        payload = self.payload(session, workspace)
        now = "2026-09-04T00:00:00Z"
        with self.core.db.connect() as db:
            db.execute(
                """INSERT INTO verification_attempts(
                verification_id,session_id,idempotency_key,request_digest,application_id,
                candidate_commit,candidate_tree,base_commit,development_branch,lock_digest,
                contract,release_binding_commit,authoring_bundle_sha256,wheel_sha256,status,
                started_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'RUNNING',?,?)""",
                ("ver_abandoned", session["session_id"], "abandoned", "digest", "demo.verify_fixture",
                 payload["candidate_commit"], run_git(["rev-parse", "HEAD^{tree}"], cwd=workspace),
                 session["exact_base_commit"], session["development_branch"], "4" * 64,
                 "capy.script/dev-v0", "1" * 40, "2" * 64, "3" * 64, now, now),
            )
        attempt_root = self.config.verification_root / "abandoned"
        attempt_root.mkdir(parents=True)
        (attempt_root / "residue").write_text("x", encoding="utf-8")
        inspected = self.core.inspect_development(session["session_id"])
        self.assertEqual("INTERRUPTED", inspected["verification"]["latest"]["status"])
        self.assertEqual("VERIFIER_PROCESS_INTERRUPTED", inspected["verification"]["latest"]["classification"])
        self.assertFalse(attempt_root.exists())

    def test_candidate_must_descend_from_exact_base(self):
        session, workspace = self.start()
        tree = run_git(["rev-parse", "HEAD^{tree}"], cwd=workspace)
        unrelated = run_git(["commit-tree", tree, "-m", "unrelated"], cwd=workspace)
        run_git(["reset", "--hard", unrelated], cwd=workspace)
        payload = self.payload(session, workspace)
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(payload)
        self.assertEqual("CANDIDATE_BASE_MISMATCH", caught.exception.code)

    def test_duplicate_application_descriptor_is_rejected_before_attempt(self):
        session, workspace = self.start()
        duplicate = workspace / "duplicate"
        duplicate.mkdir()
        (duplicate / "capability.toml").write_text((workspace / "capability.toml").read_text(encoding="utf-8"), encoding="utf-8")
        self.commit(workspace, "duplicate descriptor")
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(self.payload(session, workspace))
        self.assertEqual("APPLICATION_ID_DUPLICATE", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM verification_attempts").fetchone()[0])

    def test_json_cli_passes_and_returns_exit_zero(self):
        session, workspace = self.start()
        payload = self.payload(session, workspace)
        environment = os.environ.copy()
        environment.update({
            "CAPY_DEV_DATA_ROOT": str(self.config.data_root),
            "CAPY_DEV_CACHE_ROOT": str(self.config.cache_root),
            "CAPY_DEV_REPOSITORIES_ROOT": str(self.config.repositories_root),
            "CAPY_DEV_WORKTREES_ROOT": str(self.config.worktrees_root),
        })
        completed = subprocess.run(
            [
                sys.executable, "-m", "capy_developer", "development", "verify",
                "--session-id", payload["session_id"], "--application-id", payload["application_id"],
                "--candidate-commit", payload["candidate_commit"], "--idempotency-key", payload["idempotency_key"],
                "--json",
            ],
            cwd=self.root, env=environment, text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("PASSED", json.loads(completed.stdout)["status"])
        self.assertEqual("", completed.stderr)

    def test_schema_one_migrates_without_losing_foundation_rows(self):
        session, _ = self.start()
        with self.core.db.connect() as db:
            db.execute("DROP TABLE verification_stages")
            db.execute("DROP TABLE verification_attempts")
            db.execute("UPDATE metadata SET value='1' WHERE key='schema_version'")
        Database(self.config.database)
        with self.core.db.connect() as db:
            self.assertEqual(str(SCHEMA_VERSION), db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0])
            self.assertEqual(session["session_id"], db.execute("SELECT session_id FROM sessions").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT count(*) FROM verification_attempts").fetchone()[0])

    def test_future_schema_fails_closed(self):
        with self.core.db.connect() as db:
            db.execute("UPDATE metadata SET value='99' WHERE key='schema_version'")
        with self.assertRaisesRegex(RuntimeError, "unsupported database schema"):
            Database(self.config.database)

    def test_output_is_bounded_with_head_and_tail(self):
        payload = b"h" * OUTPUT_LIMIT + b"tail"
        text, omitted = _bounded(payload)
        self.assertGreater(omitted, 0)
        self.assertTrue(text.startswith("h"))
        self.assertTrue(text.endswith("tail"))
        self.assertIn("omitted", text)

    def test_process_timeout_is_truthful(self):
        result = run_process(
            [__import__("sys").executable, "-c", "import time; time.sleep(2)"],
            cwd=self.root,
            environment={"PATH": __import__("os").environ.get("PATH", "")},
            timeout=0.05,
        )
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)

    def test_verify_input_rejects_unknown_fields_and_invalid_identity(self):
        session, workspace = self.start()
        payload = self.payload(session, workspace)
        payload["path"] = str(workspace)
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(payload)
        self.assertEqual("VERIFY_INPUT_INVALID", caught.exception.code)
        payload.pop("path")
        payload["application_id"] = "INVALID"
        with self.assertRaises(DeveloperError) as caught:
            self.core.verify_development(payload)
        self.assertEqual("APPLICATION_ID_INVALID", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
