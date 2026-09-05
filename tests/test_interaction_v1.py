from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
import hashlib
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.database import Database, SCHEMA_VERSION
from capy_developer.errors import DeveloperError
from capy_developer.git import run_git
from capy_developer.mcp import handle
from capy_developer.release_candidate import MEMBERS_V1, validate_bundle_bytes
from capy_developer.toolchain import (
    ACCEPTED_BUNDLE_SHA256, ACCEPTED_DEVKIT_MAIN, ACCEPTED_WHEEL_SHA256,
)


def file_path(uri: str) -> Path:
    return Path(url2pathname(urlparse(uri).path))


class InteractionV1Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="interaction-v1-")
        self.root = Path(self.temporary.name)
        self.verification_temporary = Path("/tmp") / self.root.name
        self.config = Config(
            self.root / "state", self.root / "cache", self.root / "repositories",
            self.root / "worktrees", self.verification_temporary,
        )
        self.core = DeveloperCore(self.config)

    def tearDown(self):
        shutil.rmtree(self.verification_temporary, ignore_errors=True)
        self.temporary.cleanup()

    def start(self, key: str = "start") -> tuple[dict, Path]:
        session = self.core.start_development({
            "idempotency_key": key,
            "request": "Create one provider-free portable interaction application.",
            "new": {"name": "Interaction Fixture", "application_id": "demo.interaction_fixture"},
        })
        workspace = Path(session["workspace"]["native_path"])
        run_git(["config", "user.name", "Fixture"], cwd=workspace)
        run_git(["config", "user.email", "fixture@localhost"], cwd=workspace)
        return session, workspace

    def verify(self, session: dict, workspace: Path, key: str = "verify") -> dict:
        return self.core.verify_development({
            "session_id": session["session_id"], "application_id": "demo.interaction_fixture",
            "candidate_commit": run_git(["rev-parse", "HEAD"], cwd=workspace),
            "idempotency_key": key,
        })

    def commit(self, workspace: Path, message: str) -> None:
        run_git(["add", "--all"], cwd=workspace)
        run_git(["commit", "-m", message], cwd=workspace)

    def test_new_project_uses_exact_v1_lock_and_template(self):
        session, workspace = self.start()
        lock = (workspace / "capy.lock").read_text(encoding="utf-8")
        self.assertIn('schema = "capy.toolchain-lock/v1"', lock)
        self.assertIn(f'devkit_commit = "{ACCEPTED_DEVKIT_MAIN}"', lock)
        self.assertIn(f'wheel_sha256 = "{ACCEPTED_WHEEL_SHA256}"', lock)
        self.assertIn(f'authoring_bundle_sha256 = "{ACCEPTED_BUNDLE_SHA256}"', lock)
        self.assertIn('interaction_contract = "capy.application-interaction/dev-v0"', lock)
        self.assertEqual("demo.interaction_fixture", json.loads((workspace / "interaction.json").read_bytes())["application_id"])
        self.assertEqual("capy.toolchain-lock/v1", session["toolchain"]["schema"])

    def test_v1_verification_candidate_restart_and_mcp_core_parity(self):
        session, workspace = self.start()
        verification = self.verify(session, workspace)
        self.assertEqual(("capy.development-verification-result/v1", "PASSED"), (verification["schema"], verification["status"]))
        self.assertEqual(11, len(verification["stages"]))
        self.assertNotIn("path", json.dumps(verification["interaction_contract"]))
        created = self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("capy.development-release-candidate-result/v1", created["schema"])
        self.assertEqual(set(MEMBERS_V1), {item["member_path"] for item in created["members"]})
        candidate_path = file_path(created["bundle"]["path_uri"])
        with zipfile.ZipFile(candidate_path) as archive:
            self.assertEqual(list(MEMBERS_V1), archive.namelist())
            self.assertEqual(
                json.dumps(json.loads(archive.read("application/interaction.json")), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
                archive.read("application/interaction.json"),
            )
        checked = validate_bundle_bytes(candidate_path.read_bytes())
        self.assertEqual(created["release_candidate_id"], checked["release_candidate_id"])
        restarted = DeveloperCore(self.config).inspect_release_candidate(created["release_candidate_id"])
        self.assertEqual(created["bundle"]["sha256"], restarted["bundle"]["sha256"])
        mcp = handle(self.core, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "capy_release_candidate_inspect", "arguments": {"release_candidate_id": created["release_candidate_id"]}},
        })
        self.assertFalse(mcp["result"]["isError"])
        self.assertEqual(restarted, mcp["result"]["structuredContent"])

    def test_invalid_interaction_is_causal_completed_failure_and_creates_nothing(self):
        session, workspace = self.start()
        interaction = json.loads((workspace / "interaction.json").read_bytes())
        interaction["operation"]["request_fields"].append({
            "field_id": "unknown", "label": "Unknown", "description": "Invalid field.",
            "required": False, "input_kind": "text", "safe_default": None,
            "examples": ["x"], "clarification_question": "What value?",
        })
        (workspace / "interaction.json").write_text(json.dumps(interaction, indent=2) + "\n", encoding="utf-8")
        self.commit(workspace, "invalid interaction")
        payload = {
            "session_id": session["session_id"], "application_id": "demo.interaction_fixture",
            "candidate_commit": run_git(["rev-parse", "HEAD"], cwd=workspace), "idempotency_key": "invalid",
        }
        response = handle(self.core, {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"capy_development_verify","arguments":payload}})
        result = response["result"]["structuredContent"]
        self.assertFalse(response["result"]["isError"])
        self.assertEqual(("FAILED", "INTERACTION_CONTRACT_FAILED"), (result["status"], result["classification"]))
        self.assertEqual("interaction_check", next(stage["name"] for stage in result["stages"] if stage["status"] == "FAILED"))
        with self.assertRaises(DeveloperError):
            self.core.create_release_candidate(result["verification_id"])
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_missing_or_conflicting_canonical_evidence_denies_candidate(self):
        session, workspace = self.start()
        verification = self.verify(session, workspace)
        with self.core.db.connect() as db:
            record = db.execute("SELECT canonical_path FROM verification_interactions").fetchone()
        canonical = Path(record["canonical_path"])
        original = canonical.read_bytes()
        canonical.unlink()
        with self.assertRaises(DeveloperError) as missing:
            self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("INTERACTION_EVIDENCE_MISSING", missing.exception.code)
        canonical.write_bytes(original + b"tamper")
        with self.assertRaises(DeveloperError) as invalid:
            self.core.create_release_candidate(verification["verification_id"])
        self.assertEqual("RELEASE_CANDIDATE_INTEGRITY_FAILED", invalid.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM release_candidates").fetchone()[0])

    def test_conflicting_interaction_preservation_path_is_causal_failure(self):
        session, workspace = self.start()
        document = json.loads((workspace / "interaction.json").read_bytes())
        canonical = json.dumps(
            document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        conflict = self.config.verification_interactions_root / digest / "interaction.json"
        conflict.mkdir(parents=True)
        result = self.verify(session, workspace)
        self.assertEqual(
            ("FAILED", "INTERACTION_CONTRACT_FAILED"),
            (result["status"], result["classification"]),
        )
        failed = [stage for stage in result["stages"] if stage["status"] == "FAILED"]
        self.assertEqual(["interaction_preserve"], [stage["name"] for stage in failed])
        with self.core.db.connect() as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM verification_interactions").fetchone()[0])

    def test_v1_candidate_uses_durable_verified_bytes_after_current_source_drifts(self):
        session, workspace = self.start()
        verification = self.verify(session, workspace)
        verified_source = verification["interaction_contract"]["source_sha256"]
        (workspace / "interaction.json").write_text("changed after verification\n", encoding="utf-8")
        self.assertEqual("STALE", self.core.inspect_development(session["session_id"])["verification"]["current_head_state"])
        created = self.core.create_release_candidate(verification["verification_id"])
        self.assertTrue(created["ok"])
        self.assertEqual(verified_source, created["application"]["interaction"]["source_sha256"])

    def test_schema_three_fixture_migrates_without_reinterpreting_v0(self):
        source = Path(__file__).parents[1] / "campaigns/developer_interaction_contract_v0/fixtures/schema-3.db"
        candidate = Path(__file__).parents[1] / "campaigns/developer_interaction_contract_v0/fixtures/accepted-v0.capyrc"
        destination = self.root / "schema-3.db"
        backup = self.root / "schema-3.rollback.db"
        shutil.copyfile(source, destination)
        shutil.copyfile(destination, backup)
        tables = ["projects", "project_aliases", "project_applications", "toolchain_locks", "sessions", "session_events", "verification_attempts", "verification_stages", "release_candidates", "release_candidate_members"]
        with sqlite3.connect(destination) as db:
            before = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
        Database(destination)
        with sqlite3.connect(destination) as db:
            after = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables}
            self.assertEqual(str(SCHEMA_VERSION), db.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0])
            self.assertEqual({"capy.development-verification-pipeline/v0"}, {row[0] for row in db.execute("SELECT pipeline_schema FROM verification_attempts")})
            self.assertEqual({"capy.application-release-candidate/v0"}, {row[0] for row in db.execute("SELECT format_schema FROM release_candidates")})
        self.assertEqual(before, after)
        self.assertEqual(source.read_bytes(), backup.read_bytes())
        checked = validate_bundle_bytes(candidate.read_bytes())
        self.assertEqual("capy.application-release-candidate/v0", checked["manifest"]["schema"])
        self.assertEqual("fab0d9e9a244af2b21da15e9f09d91dd5195be05d907eeddd4e9feae3b94b983", checked["bundle_sha256"])

    def test_frozen_cross_platform_format_vector_and_independent_oracle(self):
        campaign = Path(__file__).parents[1] / "campaigns/developer_interaction_contract_v0"
        vector = json.loads((campaign / "FORMAT-VECTOR.json").read_bytes())
        candidate = campaign / "fixtures/fixed-v1.capyrc"
        self.assertEqual(vector["bundle_sha256"], hashlib.sha256(candidate.read_bytes()).hexdigest())
        self.assertEqual(vector["bundle_size_bytes"], candidate.stat().st_size)
        checked = validate_bundle_bytes(candidate.read_bytes())
        self.assertEqual(vector["release_candidate_id"], checked["release_candidate_id"])
        oracle = subprocess.run([sys.executable, str(campaign / "ORACLE.py"), str(candidate)], cwd=self.root, text=True, capture_output=True)
        self.assertEqual(0, oracle.returncode, oracle.stdout + oracle.stderr)
        self.assertEqual("accepted", json.loads(oracle.stdout)["status"])
        artifact_vector = json.loads((campaign / "ARTIFACT-VECTOR.json").read_bytes())
        artifact_candidate = campaign / "fixtures/artifact-v1.capyrc"
        self.assertEqual(artifact_vector["bundle_sha256"], hashlib.sha256(artifact_candidate.read_bytes()).hexdigest())
        self.assertEqual(artifact_vector["bundle_size_bytes"], artifact_candidate.stat().st_size)
        artifact_oracle = subprocess.run([sys.executable, str(campaign / "ORACLE.py"), str(artifact_candidate)], cwd=self.root, text=True, capture_output=True)
        self.assertEqual(0, artifact_oracle.returncode, artifact_oracle.stdout + artifact_oracle.stderr)
        matrix = subprocess.run([sys.executable, str(campaign / "tamper_matrix.py"), str(artifact_candidate)], cwd=self.root, text=True, capture_output=True)
        self.assertEqual(0, matrix.returncode, matrix.stdout + matrix.stderr)
        facts = json.loads(matrix.stdout)
        self.assertEqual((43, 43, []), (facts["cases"], facts["rejected"], facts["unexpected_accepts"]))


if __name__ == "__main__":
    unittest.main()
