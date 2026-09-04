from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.errors import DeveloperError
from capy_developer.git import checkout_facts, run_git
from capy_developer.mcp import handle
from capy_developer.toolchain import ACCEPTED_BUNDLE_SHA256, ACCEPTED_WHEEL_SHA256
from capy_developer.util import normalize_repository
from capy_developer.util import operation_lock


def git(args: list[str], cwd: Path) -> str:
    return run_git(args, cwd=cwd)


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.config = Config(
            self.root / "state", self.root / "cache",
            self.root / "repositories", self.root / "worktrees",
        )
        self.core = DeveloperCore(self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def fixture(self, name: str, application_id: str, *, project_name: str | None = None, lock: str | None = None) -> tuple[Path, Path]:
        seed = self.root / f"{name}-seed"
        remote = self.root / f"{name}.git"
        checkout = self.root / name
        seed.mkdir()
        (seed / "capability.toml").write_text(
            f'schema = "capy.script/dev-v0"\nid = "{application_id}"\nname = "Fixture"\n', encoding="utf-8"
        )
        (seed / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
        if project_name:
            (seed / "capy.project.toml").write_text(
                f'schema = "capy.project/v0"\nproject_id = "prj_{name}"\nname = "{project_name}"\n', encoding="utf-8"
            )
        if lock is not None:
            (seed / "DEVKIT.lock").write_text(lock, encoding="utf-8")
        git(["init", "--initial-branch=main"], seed)
        git(["config", "user.name", "Fixture"], seed)
        git(["config", "user.email", "fixture@localhost"], seed)
        git(["add", "--all"], seed)
        git(["commit", "-m", "fixture"], seed)
        run_git(["clone", "--bare", str(seed), str(remote)])
        run_git(["clone", str(remote), str(checkout)])
        return checkout, remote

    def start_new(self, key: str = "new-1") -> dict:
        return self.core.start_development({
            "idempotency_key": key,
            "request": "Create a CSV summary probe.",
            "new": {"name": "CSV Summary Probe", "application_id": "demo.csv_summary_probe"},
        })

    def test_doctor_verifies_exact_embedded_toolchain(self):
        result = self.core.doctor()
        self.assertEqual(ACCEPTED_BUNDLE_SHA256, result["accepted_toolchain"]["bundle_sha256"])
        self.assertEqual("AVAILABLE", result["accepted_toolchain"]["status"])

    def test_new_project_is_ready_exact_and_idempotent(self):
        first = self.start_new()
        second = self.start_new()
        self.assertEqual("READY", first["status"])
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["workspace"]["native_path"], second["workspace"]["native_path"])
        workspace = Path(first["workspace"]["native_path"])
        self.assertEqual(first["exact_base_commit"], git(["rev-parse", "HEAD"], workspace))
        self.assertEqual(first["development_branch"], git(["branch", "--show-current"], workspace))
        self.assertIn('id = "demo.csv_summary_probe"', (workspace / "capability.toml").read_text())
        self.assertIn(ACCEPTED_WHEEL_SHA256, (workspace / "capy.lock").read_text())
        self.assertTrue((workspace / "CAPY.md").is_file())
        self.assertEqual("AVAILABLE", first["toolchain"]["availability"])
        with self.core.db.connect() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM sessions WHERE idempotency_key='new-1'").fetchone()[0])

    def test_same_key_different_payload_conflicts(self):
        self.start_new()
        with self.assertRaisesRegex(DeveloperError, "different input") as caught:
            self.core.start_development({
                "idempotency_key": "new-1", "request": "Different",
                "new": {"name": "Other", "application_id": "demo.other"},
            })
        self.assertEqual("IDEMPOTENCY_CONFLICT", caught.exception.code)

    def test_failed_start_replay_preserves_causal_failure(self):
        checkout, _ = self.fixture("unreachable", "demo.unreachable")
        imported = self.core.import_project(str(checkout))
        missing = (self.root / "missing-remote.git").as_uri()
        with self.core.db.connect() as db:
            db.execute(
                "UPDATE projects SET repository_url=? WHERE project_id=?",
                (missing, imported["project"]["project_id"]),
            )
        payload = {
            "idempotency_key": "failed-replay", "request": "Prepare it.",
            "existing": {"application_id": "demo.unreachable"},
        }
        errors = []
        for _ in range(2):
            with self.assertRaises(DeveloperError) as caught:
                self.core.start_development(payload)
            errors.append((caught.exception.code, caught.exception.detail, caught.exception.data["session_id"]))
        self.assertEqual(errors[0], errors[1])

    def test_import_and_existing_start_leave_checkout_unchanged(self):
        lock = (
            'repository = "https://github.com/gazeromo/capy-script-devkit"\n'
            'commit = "59fbd1dcb4f2138d17622fbb2226d3864c27aa1d"\n'
            'wheel = "capy_script_devkit-0.0.0-py3-none-any.whl"\n'
            'wheel_sha256 = "ed663af84c827e93a9b58a460317a78d6d0e500fd6b90d71f9233af9c83c0e30"\n'
            'contract = "capy.script/dev-v0"\n'
        )
        checkout, _ = self.fixture("fedex", "shipping.fedex_quote", lock=lock)
        before_status = git(["status", "--porcelain=v1"], checkout)
        before_head = git(["rev-parse", "HEAD"], checkout)
        imported = self.core.import_project(str(checkout))
        result = self.core.start_development({
            "idempotency_key": "existing-1", "request": "Add a truthful field.",
            "existing": {"application_id": "shipping.fedex_quote"},
        })
        self.assertEqual(imported["project"]["project_id"], result["project"]["project_id"])
        self.assertEqual(before_head, result["exact_base_commit"])
        self.assertEqual("MISSING", result["toolchain"]["availability"])
        self.assertEqual(before_status, git(["status", "--porcelain=v1"], checkout))
        self.assertEqual(before_head, git(["rev-parse", "HEAD"], checkout))

    def test_import_twice_and_moved_checkout_keep_one_project(self):
        checkout, remote = self.fixture("one", "demo.one")
        first = self.core.import_project(str(checkout))
        moved = self.root / "moved-one"
        checkout.rename(moved)
        second = self.core.import_project(str(moved))
        self.assertEqual(first["project"]["project_id"], second["project"]["project_id"])
        with self.core.db.connect() as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM projects").fetchone()[0])
        self.assertTrue(remote.is_dir())

    def test_repository_normalization_unifies_https_and_ssh(self):
        self.assertEqual(
            normalize_repository("https://github.com/Owner/Repo.git"),
            normalize_repository("git@github.com:Owner/Repo.git"),
        )
        self.assertNotEqual(
            normalize_repository("https://git.example/Owner/Repo.git"),
            normalize_repository("https://git.example/owner/repo.git"),
        )
        self.assertNotEqual(
            normalize_repository("https://git.example:8443/team/app.git"),
            normalize_repository("https://git.example:9443/team/app.git"),
        )
        with self.assertRaises(DeveloperError) as caught:
            normalize_repository("ext::touch marker")
        self.assertEqual("REPOSITORY_PROTOCOL_UNSUPPORTED", caught.exception.code)

    def test_non_git_username_scp_origin_remains_remote_identity(self):
        checkout, _ = self.fixture("scp-user", "demo.scp_user")
        git(["remote", "set-url", "origin", "alice@example.com:team/repo.git"], checkout)
        facts = checkout_facts(checkout)
        self.assertEqual("alice@example.com:team/repo.git", facts["origin"])
        self.assertEqual("git://example.com/team/repo", normalize_repository(facts["origin"]))

    def test_reimport_replaces_stale_application_identities(self):
        checkout, _ = self.fixture("applications", "demo.old")
        self.core.import_project(str(checkout))
        (checkout / "capability.toml").write_text(
            'schema = "capy.script/dev-v0"\nid = "demo.new"\nname = "Fixture"\n', encoding="utf-8"
        )
        git(["config", "user.name", "Fixture"], checkout)
        git(["config", "user.email", "fixture@localhost"], checkout)
        git(["add", "capability.toml"], checkout)
        git(["commit", "-m", "replace application"], checkout)
        git(["push", "origin", "main"], checkout)
        self.core.import_project(str(checkout))
        self.assertEqual([], self.core.search_projects("demo.old")["matches"])
        matches = self.core.search_projects("demo.new")["matches"]
        self.assertEqual([["demo.new"]], [match["application_ids"] for match in matches])

    def test_import_uses_remote_default_metadata_not_dirty_checkout(self):
        checkout, _ = self.fixture("dirty-metadata", "demo.main")
        (checkout / "capability.toml").write_text(
            'schema = "capy.script/dev-v0"\nid = "demo.dirty_only"\n', encoding="utf-8"
        )
        imported = self.core.import_project(str(checkout))
        self.assertEqual(["demo.main"], imported["project"]["application_ids"])
        self.assertEqual([], self.core.search_projects("demo.dirty_only")["matches"])

    def test_import_uses_remote_default_metadata_not_feature_branch(self):
        checkout, _ = self.fixture("feature-metadata", "demo.main")
        git(["switch", "-c", "feature"], checkout)
        (checkout / "capability.toml").write_text(
            'schema = "capy.script/dev-v0"\nid = "demo.feature_only"\n', encoding="utf-8"
        )
        git(["config", "user.name", "Fixture"], checkout)
        git(["config", "user.email", "fixture@localhost"], checkout)
        git(["add", "capability.toml"], checkout)
        git(["commit", "-m", "feature application"], checkout)
        imported = self.core.import_project(str(checkout))
        self.assertEqual(["demo.main"], imported["project"]["application_ids"])
        result = self.core.start_development({
            "idempotency_key": "main-after-feature", "request": "Prepare main.",
            "existing": {"application_id": "demo.main"},
        })
        self.assertIn('id = "demo.main"', (Path(result["workspace"]["native_path"]) / "capability.toml").read_text())

    def test_legacy_bundle_requires_actual_wheel_digest(self):
        expected = "1" * 64
        lock = (
            'repository = "https://github.com/example/devkit"\n'
            f'commit = "{"2" * 40}"\n'
            'wheel = "devkit.whl"\n'
            f'wheel_sha256 = "{expected}"\n'
            'contract = "capy.script/dev-v0"\n'
        )
        checkout, _ = self.fixture("legacy-bytes", "demo.legacy_bytes", lock=lock)
        bundle = self.config.cache_root / "toolchains" / "sha256" / "pending" / "authoring-bundle.zip"
        bundle.parent.mkdir(parents=True)
        with zipfile.ZipFile(bundle, "w") as archive:
            archive.writestr("RELEASE-MANIFEST.json", json.dumps({
                "wheel_filename": "devkit.whl", "wheel_sha256": expected,
            }))
            archive.writestr("wheel/devkit.whl", b"wrong wheel bytes")
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
        destination = bundle.parent.parent / digest / bundle.name
        destination.parent.mkdir()
        bundle.replace(destination)
        result = self.core.import_project(str(checkout))
        self.assertEqual("MISSING", result["toolchain"]["availability"])

    def test_originless_checkout_is_rejected_instead_of_path_identified(self):
        repository = self.root / "originless"
        repository.mkdir()
        (repository / "capability.toml").write_text(
            'schema = "capy.script/dev-v0"\nid = "demo.originless"\n', encoding="utf-8"
        )
        git(["init", "--initial-branch=main"], repository)
        git(["config", "user.name", "Fixture"], repository)
        git(["config", "user.email", "fixture@localhost"], repository)
        git(["add", "--all"], repository)
        git(["commit", "-m", "fixture"], repository)
        with self.assertRaises(DeveloperError) as caught:
            self.core.import_project(str(repository))
        self.assertEqual("CANONICAL_ORIGIN_REQUIRED", caught.exception.code)

    def test_import_disables_repository_fsmonitor_command(self):
        checkout, _ = self.fixture("fsmonitor", "demo.fsmonitor")
        git(["config", "core.fsmonitor", "definitely-not-an-executable"], checkout)
        result = self.core.import_project(str(checkout))
        self.assertTrue(result["ok"])

    def test_ambiguous_alias_mutates_nothing(self):
        first, _ = self.fixture("first", "demo.first", project_name="Same")
        second, _ = self.fixture("second", "demo.second", project_name="Same")
        self.core.import_project(str(first))
        self.core.import_project(str(second))
        with self.core.db.connect() as db:
            before = db.execute("SELECT count(*) FROM sessions").fetchone()[0]
        with self.assertRaises(DeveloperError) as caught:
            self.core.start_development({
                "idempotency_key": "ambiguous", "request": "Change it.",
                "existing": {"name": "Same"},
            })
        self.assertEqual("PROJECT_AMBIGUOUS", caught.exception.code)
        with self.core.db.connect() as db:
            self.assertEqual(before, db.execute("SELECT count(*) FROM sessions").fetchone()[0])

    def test_malformed_lock_is_imported_but_explicitly_invalid(self):
        checkout, _ = self.fixture("bad-lock", "demo.bad", lock="not = [valid")
        result = self.core.import_project(str(checkout))
        self.assertEqual("INVALID", result["toolchain"]["lock_status"])
        self.assertEqual("INVALID", result["toolchain"]["availability"])

    def test_non_git_and_symlink_import_rejected(self):
        plain = self.root / "plain"
        plain.mkdir()
        with self.assertRaises(DeveloperError) as caught:
            self.core.import_project(str(plain))
        self.assertEqual("NOT_GIT_CHECKOUT", caught.exception.code)
        checkout, _ = self.fixture("target", "demo.target")
        link = self.root / "link"
        link.symlink_to(checkout, target_is_directory=True)
        with self.assertRaises(DeveloperError) as caught:
            self.core.import_project(str(link))
        self.assertEqual("PATH_SYMLINK_REJECTED", caught.exception.code)

    def test_symlinked_descriptor_is_rejected(self):
        checkout, _ = self.fixture("descriptor-link", "demo.original")
        (checkout / "capability.toml").unlink()
        outside = self.root / "outside-capability.toml"
        outside.write_text('schema = "capy.script/dev-v0"\nid = "demo.outside"\n', encoding="utf-8")
        (checkout / "capability.toml").symlink_to(outside)
        with self.assertRaises(DeveloperError) as caught:
            self.core.import_project(str(checkout))
        self.assertEqual("CAPABILITY_PATH_INVALID", caught.exception.code)

    def test_manifest_project_id_cannot_bind_two_repositories(self):
        first, _ = self.fixture("identity_first", "demo.first", project_name="First")
        second, _ = self.fixture("identity_second", "demo.second", project_name="Second")
        (second / "capy.project.toml").write_text(
            'schema = "capy.project/v0"\nproject_id = "prj_identity_first"\nname = "Second"\n', encoding="utf-8"
        )
        git(["config", "user.name", "Fixture"], second)
        git(["config", "user.email", "fixture@localhost"], second)
        git(["add", "capy.project.toml"], second)
        git(["commit", "-m", "conflicting identity"], second)
        git(["push", "origin", "main"], second)
        self.core.import_project(str(first))
        with self.assertRaises(DeveloperError) as caught:
            self.core.import_project(str(second))
        self.assertEqual("PROJECT_ID_CONFLICT", caught.exception.code)

    def test_finish_records_dirty_state_and_is_idempotent(self):
        ready = self.start_new()
        workspace = Path(ready["workspace"]["native_path"])
        (workspace / "note.txt").write_text("developer work\n", encoding="utf-8")
        finished = self.core.finish_development(ready["session_id"], "COMPLETED")
        repeated = self.core.finish_development(ready["session_id"], "COMPLETED")
        self.assertEqual("COMPLETED", finished["status"])
        self.assertTrue(finished["terminal"]["final_dirty"])
        self.assertEqual(finished["terminal"], repeated["terminal"])
        self.assertTrue(workspace.is_dir())

    def test_inspect_reports_externally_removed_worktree(self):
        ready = self.start_new()
        shutil.rmtree(ready["workspace"]["native_path"])
        inspected = self.core.inspect_development(ready["session_id"])
        self.assertEqual("WORKTREE_MISSING", inspected["discrepancy"]["code"])
        self.assertFalse(inspected["workspace"]["exists"])

    def test_ready_session_survives_core_restart(self):
        ready = self.start_new()
        restarted = DeveloperCore(self.config)
        inspected = restarted.inspect_development(ready["session_id"])
        self.assertEqual("READY", inspected["status"])
        self.assertEqual(ready["workspace"]["native_path"], inspected["workspace"]["native_path"])

    def test_preparing_session_resumes_after_process_interruption(self):
        original = self.core._prepare_new

        def interrupt(_session_id: str):
            raise KeyboardInterrupt()

        self.core._prepare_new = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.start_new("interrupted")
        self.core._prepare_new = original
        restarted = DeveloperCore(self.config)
        result = restarted.start_development({
            "idempotency_key": "interrupted",
            "request": "Create a CSV summary probe.",
            "new": {"name": "CSV Summary Probe", "application_id": "demo.csv_summary_probe"},
        })
        self.assertEqual("READY", result["status"])

    def test_two_sessions_use_distinct_worktrees(self):
        ready = self.start_new()
        project_id = ready["project"]["project_id"]
        second = self.core.start_development({
            "idempotency_key": "new-2", "request": "Continue safely.",
            "existing": {"project_id": project_id},
        })
        self.assertNotEqual(ready["session_id"], second["session_id"])
        self.assertNotEqual(ready["workspace"]["native_path"], second["workspace"]["native_path"])

    def test_same_key_threads_yield_one_session(self):
        results: list[dict] = []
        failures: list[Exception] = []
        barrier = threading.Barrier(2)

        def invoke():
            try:
                barrier.wait()
                results.append(self.start_new("race"))
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertFalse(failures)
        self.assertEqual(2, len(results))
        self.assertEqual(results[0]["session_id"], results[1]["session_id"])

    def test_operation_lock_is_released_when_process_exits(self):
        lock = self.root / "crash.lock"
        source = (
            "import os,sys\n"
            "from pathlib import Path\n"
            "from capy_developer.util import operation_lock\n"
            "with operation_lock(Path(sys.argv[1])):\n"
            "    os._exit(0)\n"
        )
        completed = subprocess.run([sys.executable, "-c", source, str(lock)], check=False)
        self.assertEqual(0, completed.returncode)
        with operation_lock(lock, timeout=1):
            self.assertTrue(lock.is_file())

    def test_mcp_and_core_results_have_semantic_parity(self):
        direct = self.start_new("parity")
        response = handle(self.core, {
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "capy_development_inspect", "arguments": {"session_id": direct["session_id"]}},
        })
        structured = response["result"]["structuredContent"]
        expected = self.core.inspect_development(direct["session_id"])
        self.assertEqual(expected, structured)

    def test_mcp_lists_only_four_tools(self):
        response = handle(self.core, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(
            ["capy_projects_search", "capy_development_start", "capy_development_inspect", "capy_development_finish"],
            [tool["name"] for tool in response["result"]["tools"]],
        )
        start = next(tool for tool in response["result"]["tools"] if tool["name"] == "capy_development_start")
        self.assertEqual(
            {"project_id", "application_id", "repository", "alias", "name"},
            set(start["inputSchema"]["properties"]["existing"]["properties"]),
        )

    def test_mcp_invalid_method_shape_does_not_raise(self):
        response = handle(self.core, {"jsonrpc": "2.0", "method": ["invalid"]})
        self.assertEqual(-32600, response["error"]["code"])


class CliProcessTests(unittest.TestCase):
    def test_cli_and_mcp_work_from_unrelated_directory(self):
        with tempfile.TemporaryDirectory() as temporary_text:
            root = Path(temporary_text)
            unrelated = root / "unrelated"
            unrelated.mkdir()
            environment = os.environ.copy()
            environment.update({
                "CAPY_DEV_DATA_ROOT": str(root / "state"),
                "CAPY_DEV_CACHE_ROOT": str(root / "cache"),
                "CAPY_DEV_REPOSITORIES_ROOT": str(root / "repositories"),
                "CAPY_DEV_WORKTREES_ROOT": str(root / "worktrees"),
            })
            completed = subprocess.run(
                [sys.executable, "-m", "capy_developer", "doctor", "--json"],
                cwd=unrelated, env=environment, text=True, capture_output=True, check=True,
            )
            result = json.loads(completed.stdout)
            self.assertTrue(result["ok"])
            self.assertEqual("", completed.stderr)
            start_input = json.dumps({
                "idempotency_key": "cli-new", "request": "Create a CLI probe.",
                "new": {"name": "CLI Probe", "application_id": "demo.cli_probe"},
            })
            started = subprocess.run(
                [sys.executable, "-m", "capy_developer", "development", "start", "--input-json", start_input, "--json"],
                cwd=unrelated, env=environment, text=True, capture_output=True, check=True,
            )
            started_result = json.loads(started.stdout)
            self.assertEqual("READY", started_result["status"])
            self.assertEqual("", started.stderr)
            messages = "\n".join([
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                json.dumps({
                    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "capy_development_inspect", "arguments": {"session_id": started_result["session_id"]}},
                }),
                "",
            ])
            mcp = subprocess.run(
                [sys.executable, "-m", "capy_developer", "mcp"], cwd=unrelated,
                env=environment, input=messages, text=True, capture_output=True, check=True,
            )
            lines = [json.loads(line) for line in mcp.stdout.splitlines()]
            self.assertEqual([1, 2, 3], [line["id"] for line in lines])
            self.assertEqual(4, len(lines[1]["result"]["tools"]))
            self.assertEqual("READY", lines[2]["result"]["structuredContent"]["status"])
            self.assertEqual("", mcp.stderr)

    def test_invalid_cli_arguments_return_json(self):
        completed = subprocess.run(
            [sys.executable, "-m", "capy_developer", "development", "inspect", "--json"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(2, completed.returncode)
        result = json.loads(completed.stdout)
        self.assertEqual("CLI_ARGUMENT_INVALID", result["error"]["code"])
        self.assertIn('"code": "CLI_ARGUMENT_INVALID"', completed.stderr)


if __name__ == "__main__":
    unittest.main()
