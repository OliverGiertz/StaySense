import unittest
from pathlib import Path

from open_data_connector import import_from_config


class OpenDataConnectorTests(unittest.TestCase):
    def test_import_from_config_has_stats(self) -> None:
        cfg = Path(__file__).resolve().parents[2] / "docs" / "open_data_sources.json"
        result = import_from_config(cfg, prune_legacy=True)
        self.assertIn("imported", result)
        self.assertIn("pruned", result)
        self.assertGreaterEqual(len(result["imported"]), 1)

        imported = result["imported"][0]
        self.assertIn("stats", imported)
        self.assertIn("accepted", imported["stats"])


if __name__ == "__main__":
    unittest.main()
