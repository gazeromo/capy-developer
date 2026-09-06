"""Synthetic desktop capability probe, not a shipping handoff or attachment API.

Expose only the accepted Developer catalog search against test-owned roots.
No project creation, application execution, credentials, or production access.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from capy_developer.config import Config
from capy_developer.core import DeveloperCore
from capy_developer.mcp import handle


def normalize_call(params: object) -> dict:
    # Request metadata is protocol context, not tool arguments or authority.
    # Discard it rather than forwarding or persisting client information.
    if (not isinstance(params, dict)
            or set(params) - {"name", "arguments", "_meta"}
            or ("_meta" in params and not isinstance(params["_meta"], dict))
            or params.get("name") != "capy_projects_search"
            or params.get("arguments") != {"query": "capy-desktop-probe-20260906"}):
        raise ValueError("only the fixed synthetic read-only search is allowed")
    return {"name": "capy_projects_search",
            "arguments": {"query": "capy-desktop-probe-20260906"}}


def serve(root: Path) -> None:
    root = root.resolve(strict=True)
    core = DeveloperCore(Config(
        root / "data", root / "cache", root / "repositories",
        root / "worktrees", root / "temporary",
    ))
    for line in sys.stdin:
        request_id = None
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("object required")
            if type(message.get("id")) in (str, int):
                request_id = message["id"]
            method = message.get("method")
            if method == "tools/call":
                message = {**message, "params": normalize_call(message.get("params"))}
            elif method not in {"initialize", "ping", "tools/list", "notifications/initialized"}:
                raise ValueError("unsupported probe method")
            response = handle(core, message)
            if method == "tools/list":
                response["result"]["tools"] = [
                    {**item, "inputSchema": {
                        "type": "object", "required": ["query"],
                        "additionalProperties": False,
                        "properties": {"query": {"type": "string",
                            "enum": ["capy-desktop-probe-20260906"]}},
                    }} for item in response["result"]["tools"]
                    if item["name"] == "capy_projects_search"
                ]
            if method == "tools/call" and not response["result"].get("isError"):
                # Presence proves an MCP request reached the accepted core, not
                # that a desktop was visible. The driver is recorded separately.
                receipt = {"schema": "capy.synthetic-mcp-probe/v0",
                           "probe_revision": 2,
                           "tool": "capy_projects_search", "success": True,
                           "desktop_visibility_proven": False}
                temporary = root / "mcp-call-receipt.pending"
                temporary.write_text(json.dumps(receipt, sort_keys=True) + "\n")
                temporary.replace(root / "mcp-call-receipt.json")
        except (ValueError, TypeError, KeyError) as exc:
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32602, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    serve(Path(sys.argv[1]))
