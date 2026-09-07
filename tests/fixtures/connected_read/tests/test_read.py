import unittest
from pathlib import Path
from capy_script.runner import run
from capy_script.failures import PreExecutionRejection

class ConnectedReadTests(unittest.TestCase):
    def test_synthetic_read(self):
        root = Path(__file__).resolve().parents[1]
        result = run(root, root / "conformance/read.json")
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.result, {"message": "synthetic read"})
        self.assertEqual(len(result.calls), 1)
        self.assertEqual(result.calls[0]["operation"], "read")

    def test_missing_connection_denied(self):
        root = Path(__file__).resolve().parents[1]
        with self.assertRaises(PreExecutionRejection):
            run(root, root / "conformance/missing.json")
