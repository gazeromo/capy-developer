from __future__ import annotations

import json
import sys
from typing import Any

from .core import DeveloperCore
from .errors import DeveloperError


TOOLS = [
    {
        "name": "capy_projects_search",
        "description": "Search the configured Capy project catalog without changing any project.",
        "inputSchema": {
            "type": "object", "required": ["query"], "additionalProperties": False,
            "properties": {"query": {"type": "string", "minLength": 1}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
        },
    },
    {
        "name": "capy_development_start",
        "description": "Prepare one exact existing or explicitly new Capy project in an isolated Git worktree.",
        "inputSchema": {
            "type": "object", "required": ["idempotency_key", "request"], "additionalProperties": False,
            "properties": {
                "idempotency_key": {"type": "string", "minLength": 1},
                "request": {"type": "string", "minLength": 1},
                "existing": {
                    "type": "object", "minProperties": 1, "maxProperties": 1,
                    "additionalProperties": False,
                    "properties": {
                        "project_id": {"type": "string", "minLength": 1},
                        "application_id": {"type": "string", "minLength": 1},
                        "repository": {"type": "string", "minLength": 1},
                        "alias": {"type": "string", "minLength": 1},
                        "name": {"type": "string", "minLength": 1},
                    },
                    "oneOf": [
                        {"required": ["project_id"]}, {"required": ["application_id"]},
                        {"required": ["repository"]}, {"required": ["alias"]},
                        {"required": ["name"]},
                    ],
                },
                "new": {
                    "type": "object", "required": ["name", "application_id"], "additionalProperties": False,
                    "properties": {"name": {"type": "string"}, "application_id": {"type": "string"}},
                },
            },
            "oneOf": [{"required": ["existing"]}, {"required": ["new"]}],
        },
    },
    {
        "name": "capy_development_inspect",
        "description": "Inspect durable session state and revalidate its current Git worktree facts.",
        "inputSchema": {
            "type": "object", "required": ["session_id"], "additionalProperties": False,
            "properties": {"session_id": {"type": "string", "minLength": 1}},
        },
    },
    {
        "name": "capy_development_finish",
        "description": "Record a development session as completed or cancelled without deleting its worktree.",
        "inputSchema": {
            "type": "object", "required": ["session_id", "disposition"], "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "minLength": 1},
                "disposition": {"type": "string", "enum": ["COMPLETED", "CANCELLED"]},
            },
        },
    },
    {
        "name": "capy_development_verify",
        "description": "Verify one exact clean Git commit using its exact locked DevKit. Interaction-aware projects also require and preserve validated interaction.json evidence; historical projects retain V0 behavior. This does not accept, publish, deploy, or activate software.",
        "inputSchema": {
            "type": "object",
            "required": ["session_id", "application_id", "candidate_commit", "idempotency_key"],
            "additionalProperties": False,
            "properties": {
                "session_id": {"type": "string", "minLength": 1},
                "application_id": {"type": "string", "minLength": 1},
                "candidate_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 200},
            },
        },
    },
    {
        "name": "capy_release_candidate_create",
        "description": "Create one exact unaccepted versioned release candidate from a successful verification. V1 includes the structurally verified but unaccepted interaction contract; historical V0 remains unchanged. This does not accept, publish, install, bind, or deploy software.",
        "inputSchema": {
            "type": "object", "required": ["verification_id"], "additionalProperties": False,
            "properties": {"verification_id": {"type": "string", "pattern": "^ver_[A-Za-z0-9_]+$"}},
        },
    },
    {
        "name": "capy_release_candidate_inspect",
        "description": "Inspect and validate one durable V0 or interaction-aware V1 unaccepted release candidate. This does not accept, publish, install, bind, or deploy software.",
        "inputSchema": {
            "type": "object", "required": ["release_candidate_id"], "additionalProperties": False,
            "properties": {"release_candidate_id": {"type": "string", "pattern": "^rc_[0-9a-f]{32}$"}},
        },
    },
]


def _call(core: DeveloperCore, name: str, arguments: dict) -> dict:
    if name == "capy_projects_search":
        return core.search_projects(arguments.get("query", ""), arguments.get("limit", 10))
    if name == "capy_development_start":
        return core.start_development(arguments)
    if name == "capy_development_inspect":
        return core.inspect_development(arguments.get("session_id", ""))
    if name == "capy_development_finish":
        return core.finish_development(arguments.get("session_id", ""), arguments.get("disposition", ""))
    if name == "capy_development_verify":
        return core.verify_development(arguments)
    if name == "capy_release_candidate_create":
        if set(arguments) != {"verification_id"}:
            raise DeveloperError("RELEASE_CANDIDATE_INPUT_INVALID", "create input must contain only verification_id")
        return core.create_release_candidate(arguments.get("verification_id", ""))
    if name == "capy_release_candidate_inspect":
        if set(arguments) != {"release_candidate_id"}:
            raise DeveloperError("RELEASE_CANDIDATE_INPUT_INVALID", "inspect input must contain only release_candidate_id")
        return core.inspect_release_candidate(arguments.get("release_candidate_id", ""))
    raise DeveloperError("MCP_TOOL_UNKNOWN", "unknown Capy Developer tool")


def _response(request_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle(core: DeveloperCore, message: dict) -> dict | None:
    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32600, "message": "Invalid Request"}}
    if request_id is None and method.startswith("notifications/"):
        return None
    if method == "initialize":
        return _response(request_id, {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "capy-developer", "version": "0.4.0"},
        })
    if method == "ping":
        return _response(request_id, {})
    if method == "tools/list":
        return _response(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params")
        if not isinstance(params, dict) or not isinstance(params.get("arguments", {}), dict):
            raise DeveloperError("MCP_PAYLOAD_INVALID", "tools/call params are invalid")
        try:
            value = _call(core, params.get("name", ""), params.get("arguments", {}))
            return _response(request_id, {
                "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
                "structuredContent": value,
                "isError": False,
            })
        except DeveloperError as exc:
            value = exc.result()
            return _response(request_id, {
                "content": [{"type": "text", "text": json.dumps(value, sort_keys=True)}],
                "structuredContent": value,
                "isError": True,
            })
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}


def serve() -> None:
    core = DeveloperCore()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("message must be an object")
            response = handle(core, message)
        except (json.JSONDecodeError, ValueError) as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        except DeveloperError as exc:
            response = {"jsonrpc": "2.0", "id": message.get("id"), "error": {"code": -32602, "message": exc.detail, "data": {"code": exc.code}}}
        except Exception:
            response = {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None, "error": {"code": -32603, "message": "Internal error"}}
        if response is not None:
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
