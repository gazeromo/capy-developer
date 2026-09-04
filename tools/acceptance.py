#!/usr/bin/env python3
"""Run the bounded local Capy Developer Foundation V0 acceptance journeys."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


FEDEx_HEAD = "de79fd1d0c08ab01f85b5d25a7a6d69a672c5b94"
PROFORMA_HEAD = "c21a308ec539898da8b6801ffc54845826bfd6cf"


def command(arguments: list[str], *, cwd: Path, environment: dict[str, str] | None = None, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments, cwd=cwd, env=environment, input=input_text, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )


def git(arguments: list[str], cwd: Path) -> str:
    return command(["git", *arguments], cwd=cwd).stdout.strip()


def cli(arguments: list[str], cwd: Path, environment: dict[str, str]) -> dict:
    completed = command([sys.executable, "-m", "capy_developer", *arguments, "--json"], cwd=cwd, environment=environment)
    if completed.stderr:
        raise RuntimeError(f"unexpected CLI stderr: {completed.stderr}")
    return json.loads(completed.stdout)


def local_fixture(source: Path, name: str, root: Path) -> tuple[Path, Path]:
    remote = root / f"{name}.git"
    checkout = root / f"{name}-checkout"
    command(["git", "clone", "--bare", str(source), str(remote)], cwd=root)
    command(["git", "clone", str(remote), str(checkout)], cwd=root)
    return checkout, remote


def session_counts(database: Path) -> dict[str, int]:
    with sqlite3.connect(database) as db:
        return {
            "projects": db.execute("SELECT count(*) FROM projects").fetchone()[0],
            "sessions": db.execute("SELECT count(*) FROM sessions").fetchone()[0],
            "ready": db.execute("SELECT count(*) FROM sessions WHERE status='READY'").fetchone()[0],
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fedex-checkout", required=True, type=Path)
    parser.add_argument("--proforma-checkout", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fedex = args.fedex_checkout.resolve(strict=True)
    proforma = args.proforma_checkout.resolve(strict=True)
    source_before = {
        "fedex": {"head": git(["rev-parse", "HEAD"], fedex), "status": git(["status", "--porcelain=v1"], fedex)},
        "proforma": {"head": git(["rev-parse", "HEAD"], proforma), "status": git(["status", "--porcelain=v1"], proforma)},
    }
    if source_before["fedex"]["head"] != FEDEx_HEAD or source_before["proforma"]["head"] != PROFORMA_HEAD:
        raise RuntimeError("fixture source head mismatch")

    with tempfile.TemporaryDirectory(prefix="capy-developer-acceptance-") as temporary_text:
        root = Path(temporary_text)
        sources = root / "sources"
        sources.mkdir()
        fedex_checkout, _ = local_fixture(fedex, "fedex", sources)
        proforma_checkout, _ = local_fixture(proforma, "proforma", sources)
        unrelated = root / "unrelated-starting-directory"
        unrelated.mkdir()
        environment = os.environ.copy()
        environment.update({
            "CAPY_DEV_DATA_ROOT": str(root / "state"),
            "CAPY_DEV_CACHE_ROOT": str(root / "cache"),
            "CAPY_DEV_REPOSITORIES_ROOT": str(root / "managed-repositories"),
            "CAPY_DEV_WORKTREES_ROOT": str(root / "managed-worktrees"),
        })

        doctor = cli(["doctor"], unrelated, environment)
        imported_fedex = cli(["projects", "import", "--path", str(fedex_checkout)], unrelated, environment)
        imported_fedex_again = cli(["projects", "import", "--path", str(fedex_checkout)], unrelated, environment)
        imported_proforma = cli(["projects", "import", "--path", str(proforma_checkout)], unrelated, environment)
        search = cli(["projects", "search", "--query", "shipping.fedex_quote"], unrelated, environment)

        fedex_input = {
            "idempotency_key": "acceptance-fedex-cli",
            "request": "Add support for one new truthful quote-result field.",
            "existing": {"application_id": "shipping.fedex_quote"},
        }
        fedex_start = cli(["development", "start", "--input-json", json.dumps(fedex_input)], unrelated, environment)
        fedex_replay = cli(["development", "start", "--input-json", json.dumps(fedex_input)], unrelated, environment)

        mcp_input = {
            "idempotency_key": "acceptance-fedex-mcp",
            "request": "Prepare a second protocol-equivalent development session.",
            "existing": {"application_id": "shipping.fedex_quote"},
        }
        messages = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "capy_development_start", "arguments": mcp_input}}),
            "",
        ])
        mcp = command([sys.executable, "-m", "capy_developer", "mcp"], cwd=unrelated, environment=environment, input_text=messages)
        if mcp.stderr:
            raise RuntimeError(f"unexpected MCP stderr: {mcp.stderr}")
        mcp_lines = [json.loads(line) for line in mcp.stdout.splitlines()]
        mcp_start = mcp_lines[2]["result"]["structuredContent"]

        new_input = {
            "idempotency_key": "acceptance-new-cli",
            "request": "Create a small Capy application that summarizes a CSV.",
            "new": {"name": "CSV Summary Probe", "application_id": "demo.csv_summary_probe"},
        }
        new_start = cli(["development", "start", "--input-json", json.dumps(new_input)], unrelated, environment)
        new_replay = cli(["development", "start", "--input-json", json.dumps(new_input)], unrelated, environment)
        restarted_inspect = cli(["development", "inspect", "--session-id", new_start["session_id"]], unrelated, environment)
        new_workspace = Path(new_start["workspace"]["native_path"])
        (new_workspace / "acceptance-note.txt").write_text("harmless test-owned change\n", encoding="utf-8")
        finished = cli([
            "development", "finish", "--session-id", new_start["session_id"], "--disposition", "COMPLETED",
        ], unrelated, environment)
        finished_replay = cli([
            "development", "finish", "--session-id", new_start["session_id"], "--disposition", "COMPLETED",
        ], unrelated, environment)

        source_after = {
            "fedex": {"head": git(["rev-parse", "HEAD"], fedex), "status": git(["status", "--porcelain=v1"], fedex)},
            "proforma": {"head": git(["rev-parse", "HEAD"], proforma), "status": git(["status", "--porcelain=v1"], proforma)},
        }
        checks = {
            "doctor": doctor["ok"] and doctor["accepted_toolchain"]["status"] == "AVAILABLE",
            "fedex_import_idempotent": imported_fedex["project"]["project_id"] == imported_fedex_again["project"]["project_id"],
            "proforma_imported": imported_proforma["project"]["application_ids"] == ["documents.proforma_invoice"],
            "exact_search": len(search["matches"]) == 1 and search["matches"][0]["exact_match_reason"] == "application_id",
            "fedex_cli_ready": fedex_start["status"] == "READY" and fedex_start["exact_base_commit"] == FEDEx_HEAD,
            "fedex_replay_exact": fedex_start["session_id"] == fedex_replay["session_id"] and fedex_start["workspace"] == fedex_replay["workspace"],
            "mcp_ready": mcp_start["status"] == "READY" and mcp_start["project"]["project_id"] == fedex_start["project"]["project_id"],
            "mcp_separate_workspace": mcp_start["workspace"]["native_path"] != fedex_start["workspace"]["native_path"],
            "mcp_four_tools": len(mcp_lines[1]["result"]["tools"]) == 4,
            "new_ready_available": new_start["status"] == "READY" and new_start["toolchain"]["availability"] == "AVAILABLE",
            "new_replay_exact": new_start["session_id"] == new_replay["session_id"] and new_start["workspace"] == new_replay["workspace"],
            "restart_inspect": restarted_inspect["status"] == "READY" and restarted_inspect["workspace"]["exists"],
            "finish_preserves_worktree": finished["status"] == "COMPLETED" and finished["terminal"]["final_dirty"] and new_workspace.is_dir(),
            "finish_idempotent": finished["terminal"] == finished_replay["terminal"],
            "source_unchanged": source_before == source_after,
        }
        if not all(checks.values()):
            raise RuntimeError(f"acceptance failed: {[name for name, passed in checks.items() if not passed]}")
        receipt = {
            "schema": "capy.developer-foundation-acceptance/v0",
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "passed",
            "checks": checks,
            "fixture_heads": {"fedex": FEDEx_HEAD, "proforma": PROFORMA_HEAD},
            "counts": session_counts(root / "state" / "catalog.sqlite3"),
            "project_ids": {
                "fedex": imported_fedex["project"]["project_id"],
                "proforma": imported_proforma["project"]["project_id"],
                "new": new_start["project"]["project_id"],
            },
            "developer_ceremony": {
                "selected_repository_paths": 0,
                "git_initialization_actions": 0,
                "branch_or_worktree_decisions": 0,
                "devkit_version_decisions": 0,
                "manual_template_copy_actions": 0,
            },
            "boundary_changes": {
                "imported_application_repositories": 0,
                "capy_outcome_runtime": 0,
                "production": 0,
                "provider_calls": 0,
                "coding_agent_launches": 0,
            },
        }
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(json.dumps({"status": "passed", "receipt_sha256": hashlib.sha256(encoded.encode()).hexdigest()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
