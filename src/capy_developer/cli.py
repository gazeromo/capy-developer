from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import DeveloperCore
from .errors import DeveloperError
from .mcp import serve


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str):
        raise DeveloperError("CLI_ARGUMENT_INVALID", message)


def _read_input(path: str | None, inline: str | None) -> dict:
    if path and inline:
        raise DeveloperError("CLI_INPUT_CONFLICT", "use only one of --input and --input-json")
    try:
        if inline:
            value = json.loads(inline)
        elif path:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        elif not sys.stdin.isatty():
            value = json.load(sys.stdin)
        else:
            raise DeveloperError("CLI_INPUT_REQUIRED", "provide --input, --input-json, or JSON stdin")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DeveloperError("CLI_INPUT_INVALID", "input is not readable JSON") from exc
    if not isinstance(value, dict):
        raise DeveloperError("CLI_INPUT_INVALID", "input JSON must be an object")
    return value


def parser() -> argparse.ArgumentParser:
    root = JsonArgumentParser(prog="capy-dev")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("installation").add_subparsers(dest="installation_command", required=True).add_parser("inspect")
    connect = commands.add_parser("connect")
    connect.add_argument("--site", required=True)
    connect.add_argument("--client", choices=["muse", "codex"], required=True)
    client = commands.add_parser("client").add_subparsers(dest="client_command", required=True)
    client.add_parser("list")
    client.add_parser("remove").add_argument("--client", choices=["muse"], required=True)
    for name in ("inspect", "check"):
        client.add_parser(name).add_argument("--client-id", required=True)
    work = commands.add_parser("work").add_subparsers(dest="work_command", required=True)
    work.add_parser("list")
    work.add_parser("sync").add_argument("--handoff-id", required=True)
    work.add_parser("resume").add_argument("--handoff-id", required=True)
    begin = work.add_parser("begin")
    begin.add_argument("--input")
    begin.add_argument("--input-json")

    projects = commands.add_parser("projects").add_subparsers(dest="projects_command", required=True)
    project_import = projects.add_parser("import")
    project_import.add_argument("--path", required=True)
    project_search = projects.add_parser("search")
    project_search.add_argument("--query", required=True)
    project_search.add_argument("--limit", type=int, default=10)

    development = commands.add_parser("development").add_subparsers(dest="development_command", required=True)
    start = development.add_parser("start")
    start.add_argument("--input")
    start.add_argument("--input-json")
    attach = development.add_parser("attach")
    attach.add_argument("--handoff-id", required=True)
    continuation = development.add_parser("continue")
    continuation.add_argument("--input")
    continuation.add_argument("--input-json")
    inspect = development.add_parser("inspect")
    inspect.add_argument("--session-id", required=True)
    verify = development.add_parser("verify")
    verify.add_argument("--session-id", required=True)
    verify.add_argument("--application-id", required=True)
    verify.add_argument("--candidate-commit", required=True)
    verify.add_argument("--idempotency-key", required=True)
    finish = development.add_parser("finish")
    finish.add_argument("--session-id", required=True)
    finish.add_argument("--disposition", required=True, choices=["COMPLETED", "CANCELLED"])
    release_candidate = commands.add_parser("release-candidate").add_subparsers(
        dest="release_candidate_command", required=True
    )
    candidate_create = release_candidate.add_parser("create")
    candidate_create.add_argument("--verification-id", required=True)
    candidate_inspect = release_candidate.add_parser("inspect")
    candidate_inspect.add_argument("--release-candidate-id", required=True)
    commands.add_parser("mcp")
    return root


def run(arguments: list[str] | None = None) -> dict | None:
    raw = list(sys.argv[1:] if arguments is None else arguments)
    filtered = [argument for argument in raw if argument != "--json"]
    args = parser().parse_args(filtered)
    if args.command == "mcp":
        serve()
        return None
    if args.command == "installation":
        import os
        from .config import Config
        from .installation import discover, locator_path, roots, ROOT_KEYS
        current = Config.from_environment()
        result = discover(default=current, explicit=current if all(k in os.environ for k in ROOT_KEYS) else None,
                          config_path=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml",
                          locator=locator_path())
        return {"schema": "capy.installation-inspection/v0", "ok": True,
                "status": result["status"], "source": result["source"],
                "technical_details": {"roots": roots(result["config"])},
                "mutated": False, "ready": False}
    if args.command in {"connect", "client", "work"}:
        import os
        import shutil
        import subprocess
        import re
        from .config import Config
        from .harness_client import HarnessClient, connection_info
        from .installation import discover, locator_path, ROOT_KEYS
        current = Config.from_environment()
        found = discover(default=current, explicit=current if all(k in os.environ for k in ROOT_KEYS) else None,
                         config_path=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml",
                         locator=locator_path())
        if args.command != "connect" and found["status"] != "EXISTING":
            raise DeveloperError("INSTALLATION_NOT_FOUND", "connect this coding client before starting linked work")
        if args.command == "connect":
            from .desktop.transport import Transport
            connection_info(Transport(), args.site)
            from .workspace_resume import native_client
            executable = native_client(args.client)
            try:
                probe = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15, check=True)
            except (OSError, subprocess.SubprocessError):
                raise DeveloperError("CLIENT_PROBE_FAILED", "the installed client version could not be inspected") from None
            version = probe.stdout.strip()
            if not re.fullmatch(r'[A-Za-z0-9 ._()+-]{1,80}', version):
                raise DeveloperError("CLIENT_VERSION_INVALID", "invalid observed coding client version")
        muse = None
        muse_mcp = None
        if (args.command == 'connect' and args.client == 'muse') or (args.command == 'client' and args.client_command == 'remove'):
            from .muse_guidance import MuseGuidance
            from .muse_mcp import MuseMcpSetup
            executable = shutil.which('muse')
            if executable is None:
                raise DeveloperError('CLIENT_NOT_INSTALLED', 'the native Muse client is required to manage its integration')
            muse = MuseGuidance(found['config'].data_root / 'client-setup', executable)
            muse_mcp = MuseMcpSetup(found['config'],muse.config/'settings.json')
            if args.command == 'client':
                muse.preflight_remove()
                if muse_mcp.receipt.exists():
                    muse_mcp.remove()
                return muse.remove()
            muse.preflight(Path.home() / '.agents/skills/capy-development')
            muse_mcp.preflight()
        if args.command == "client":
            harness = HarnessClient.diagnostics(found["config"])
            if args.client_command == "list":
                return harness.clients()
            return harness.check(args.client_id, channel="JSON_CLI") if args.client_command == "check" else harness.status(args.client_id)
        core = DeveloperCore(found["config"])
        harness = HarnessClient(core)
        if args.command == "connect":
            from .client_setup import ClientSetup
            setup = ClientSetup(core, skills=Path.home() / ".agents/skills", locator=locator_path(),
                                codex_config=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml", muse=muse, muse_mcp=muse_mcp)
            configuration = setup.install(args.client)
            return {**harness.connect(args.site, args.client, version, configuration["transport"]), 'configuration':configuration}
        if args.work_command == "list":
            return harness.work()
        if args.work_command == "sync":
            return harness.sync(args.handoff_id)
        if args.work_command == "resume":
            from .workspace_resume import launch
            return launch(harness, args.handoff_id)
        result = harness.begin(_read_input(args.input, args.input_json))
        from .desktop_cli import start_sync
        start_sync(core.config)
        return result
    core = DeveloperCore()
    if args.command == "doctor":
        return core.doctor()
    if args.command == "projects" and args.projects_command == "import":
        return core.import_project(args.path)
    if args.command == "projects" and args.projects_command == "search":
        return core.search_projects(args.query, args.limit)
    if args.command == "development" and args.development_command == "attach":
        return core.attach_development(args.handoff_id)
    if args.command == "development" and args.development_command == "continue":
        return core.continue_development(_read_input(args.input, args.input_json))
    if args.command == "development" and args.development_command == "start":
        return core.start_development(_read_input(args.input, args.input_json))
    if args.command == "development" and args.development_command == "inspect":
        return core.inspect_development(args.session_id)
    if args.command == "development" and args.development_command == "verify":
        return core.verify_development({
            "session_id": args.session_id,
            "application_id": args.application_id,
            "candidate_commit": args.candidate_commit,
            "idempotency_key": args.idempotency_key,
        })
    if args.command == "development" and args.development_command == "finish":
        return core.finish_development(args.session_id, args.disposition)
    if args.command == "release-candidate" and args.release_candidate_command == "create":
        return core.create_release_candidate(args.verification_id)
    if args.command == "release-candidate" and args.release_candidate_command == "inspect":
        return core.inspect_release_candidate(args.release_candidate_id)
    raise DeveloperError("CLI_COMMAND_INVALID", "unsupported command")


def main(arguments: list[str] | None = None) -> int:
    import sqlite3
    raw = list(sys.argv[1:] if arguments is None else arguments)
    if raw and raw[0] in {"setup", "handoff"}:
        from .desktop_cli import run as desktop_run
        return desktop_run(raw)
    try:
        result = run(arguments)
        if result is not None:
            print(json.dumps(result, sort_keys=True))
        if result is not None and result.get("schema") in {"capy.development-verification-result/v0", "capy.development-verification-result/v1"}:
            return 0 if result.get("status") == "PASSED" else 1
        if result is not None and result.get("schema") in {"capy.development-release-candidate-result/v0", "capy.development-release-candidate-result/v1"}:
            return 0 if result.get("ok") else 1
        return 0
    except DeveloperError as exc:
        print(json.dumps(exc.result(), sort_keys=True))
        print(json.dumps({"code": exc.code, "detail": exc.detail}, sort_keys=True), file=sys.stderr)
        return 2
    except sqlite3.OperationalError as exc:
        if (getattr(exc, 'sqlite_errorcode', 0) & 0xff) != sqlite3.SQLITE_READONLY:
            raise
        failure = DeveloperError('INSTALLATION_WRITE_ACCESS_REQUIRED',
            'this operation requires write access to the existing Capy installation; use a supported client workspace or scoped write permission, then retry the same operation')
        print(json.dumps(failure.result(), sort_keys=True))
        print(json.dumps({'code':failure.code, 'detail':failure.detail}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
