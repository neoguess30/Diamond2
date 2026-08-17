from __future__ import annotations
import unittest
import shutil
from pathlib import Path
from datetime import datetime, timezone

from persistence.writer.storage_writer import StorageWriterWorker
from core.config import MAX_EXPORT_FILE_BYTES

class TestExportRotationResilience(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_export_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.writer = StorageWriterWorker(db_path=":memory:")
        self.writer.desktop_dir = self.test_dir

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_unbounded_part_rotation_past_999(self):
        status_key = "available"
        # Dynamic UTC Date matching active system date
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        target_dir = self.test_dir / status_key
        target_dir.mkdir(parents=True, exist_ok=True)

        p999 = target_dir / f"{today_str}_0999.txt"
        # Write dummy data exceeding 5MB
        with open(p999, "wb") as f:
            f.write(b"0" * (MAX_EXPORT_FILE_BYTES + 1024))

        self.writer.active_export_targets[status_key] = {
            "date": today_str,
            "part": 999,
            "path": p999
        }

        # Request next active file -> must cleanly rotate to 1000 without crashing or looping
        next_file = self.writer._get_active_export_file(status_key)
        self.assertEqual(next_file.name, f"{today_str}_1000.txt")
        self.assertEqual(self.writer.active_export_targets[status_key]["part"], 1000)

        # Fill part 1000 and verify it advances to 1001
        with open(next_file, "wb") as f:
            f.write(b"0" * (MAX_EXPORT_FILE_BYTES + 1024))

        file_1001 = self.writer._get_active_export_file(status_key)
        self.assertEqual(file_1001.name, f"{today_str}_1001.txt")
        self.assertEqual(self.writer.active_export_targets[status_key]["part"], 1001)

if __name__ == "__main__":
    unittest.main()