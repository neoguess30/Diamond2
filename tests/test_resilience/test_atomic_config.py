from __future__ import annotations
import unittest
import shutil
from pathlib import Path
from core.atomic_config import AtomicConfigManager

class TestAtomicConfigManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_config_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_dir / "test_config.json"
        self.manager = AtomicConfigManager(self.config_path)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_atomic_save_and_load(self):
        initial = {"max_workers": 4, "scan_delay": 1.2}
        self.assertTrue(self.manager.save_config(initial))
        self.assertTrue(self.config_path.exists())

        loaded = self.manager.load_config(default_config={})
        self.assertEqual(loaded["max_workers"], 4)
        self.assertEqual(loaded["scan_delay"], 1.2)

    def test_corrupted_config_restore_defaults(self):
        # Write corrupted JSON
        with open(self.config_path, "w", encoding="utf-8") as f:
            f.write("{invalid_json_missing_quotes:")

        default_cfg = {"fallback": True}
        restored = self.manager.load_config(default_config=default_cfg)
        self.assertEqual(restored["fallback"], True)

if __name__ == "__main__":
    unittest.main()