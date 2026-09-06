"""Run with a Python environment containing the accepted Developer 0.4.0 wheel."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ProbeTests(unittest.TestCase):
    def test_protocol_metadata_is_ignored_without_widening_arguments(self):
        from probe_server import normalize_call
        call = {"name": "capy_projects_search",
                "arguments": {"query": "capy-desktop-probe-20260906"}}
        for metadata in ({}, {"progressToken": "synthetic-canary"},
                         {"vendor/context": {"secret": "DO-NOT-FORWARD"}}):
            self.assertEqual(normalize_call({**call, "_meta": metadata}), call)
        for invalid in (None, [], {**call, "_meta": None}, {**call, "_meta": []},
                        {**call, "unexpected": True},
                        {**call, "arguments": {**call["arguments"], "limit": 10}},
                        {**call, "arguments": {"query": "wrong"}, "_meta": {}},
                        {**call, "name": "capy_development_start", "_meta": {}}):
            with self.assertRaises(ValueError):
                normalize_call(invalid)

    def test_read_only_protocol_against_separate_synthetic_state(self):
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "capy_projects_search",
                "arguments": {"query": "capy-desktop-probe-20260906"},
                "_meta": {"progressToken": "DO-NOT-PERSIST"}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "capy_development_start", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {
                "name": "capy_projects_search", "arguments": {"query": "other"}}},
        ]
        with tempfile.TemporaryDirectory(prefix="capy-probe-control-") as root:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("probe_server.py")), root],
                input="".join(json.dumps(m) + "\n" for m in messages),
                capture_output=True, text=True, check=True,
            )
            responses = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(len(responses), 5)
            self.assertEqual(responses[0]["result"]["serverInfo"]["version"], "0.4.0")
            self.assertEqual([t["name"] for t in responses[1]["result"]["tools"]],
                             ["capy_projects_search"])
            self.assertFalse(responses[2]["result"]["isError"])
            for request_id, response in zip((4, 5), responses[3:]):
                self.assertEqual(response["error"]["code"], -32602)
                self.assertEqual(response["id"], request_id)
            receipt = json.loads((Path(root) / "mcp-call-receipt.json").read_text())
            self.assertTrue(receipt["success"])
            self.assertEqual(receipt["probe_revision"], 2)
            self.assertNotIn("DO-NOT-PERSIST", result.stdout)
            self.assertNotIn("DO-NOT-PERSIST", json.dumps(receipt))
            self.assertFalse(receipt["desktop_visibility_proven"])
            self.assertEqual(list((Path(root) / "repositories").iterdir()), [])
            self.assertEqual(list((Path(root) / "worktrees").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
