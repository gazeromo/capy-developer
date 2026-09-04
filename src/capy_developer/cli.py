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
    inspect = development.add_parser("inspect")
    inspect.add_argument("--session-id", required=True)
    finish = development.add_parser("finish")
    finish.add_argument("--session-id", required=True)
    finish.add_argument("--disposition", required=True, choices=["COMPLETED", "CANCELLED"])
    commands.add_parser("mcp")
    return root


def run(arguments: list[str] | None = None) -> dict | None:
    raw = list(sys.argv[1:] if arguments is None else arguments)
    filtered = [argument for argument in raw if argument != "--json"]
    args = parser().parse_args(filtered)
    if args.command == "mcp":
        serve()
        return None
    core = DeveloperCore()
    if args.command == "doctor":
        return core.doctor()
    if args.command == "projects" and args.projects_command == "import":
        return core.import_project(args.path)
    if args.command == "projects" and args.projects_command == "search":
        return core.search_projects(args.query, args.limit)
    if args.command == "development" and args.development_command == "start":
        return core.start_development(_read_input(args.input, args.input_json))
    if args.command == "development" and args.development_command == "inspect":
        return core.inspect_development(args.session_id)
    if args.command == "development" and args.development_command == "finish":
        return core.finish_development(args.session_id, args.disposition)
    raise DeveloperError("CLI_COMMAND_INVALID", "unsupported command")


def main(arguments: list[str] | None = None) -> int:
    try:
        result = run(arguments)
        if result is not None:
            print(json.dumps(result, sort_keys=True))
        return 0
    except DeveloperError as exc:
        print(json.dumps(exc.result(), sort_keys=True))
        print(json.dumps({"code": exc.code, "detail": exc.detail}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
