from pathlib import Path
import unittest


class RepositoryBaselineTests(unittest.TestCase):
    def test_direction_is_present(self):
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "docs" / "DIRECTION.md").is_file())


if __name__ == "__main__":
    unittest.main()
