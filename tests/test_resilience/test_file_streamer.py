from __future__ import annotations
import unittest
import json
import shutil
from pathlib import Path

from parser.file_streamer import StreamingTargetExtractor

class TestStreamingTargetExtractor(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_streamer_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_json_nested_root_dictionary(self):
        """P0 Test: Verifies extraction from nested root objects like {"users": [{"username": "alice"}, ...]}"""
        file_path = self.test_dir / "nested_users.json"
        data = {
            "metadata": {"version": 1.0},
            "users": [
                {"username": "alice", "id": 1},
                {"username": "bob", "id": 2},
                {"user": "charlie", "id": 3}
            ]
        }
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        extracted = list(StreamingTargetExtractor.stream_json(str(file_path)))
        self.assertEqual(extracted, ["alice", "bob", "charlie"])

    def test_json_flat_and_object_arrays(self):
        """P0 Test: Verifies extraction from standard root arrays."""
        file_path = self.test_dir / "array_users.json"
        data = ["@target1", {"handle": "target2"}, "target3"]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        extracted = list(StreamingTargetExtractor.stream_json(str(file_path)))
        self.assertEqual(extracted, ["target1", "target2", "target3"])

    def test_json_chunk_boundary_crossing_long_element(self):
        """
        P0 Test: Verifies that elements exceeding the 64KB chunk boundary
        (e.g. string > 75,000 characters) are seamlessly parsed without data loss.
        """
        file_path = self.test_dir / "large_boundary.json"
        
        # Create a string of 75,000 characters (exceeds 65,536-byte chunk buffer)
        long_user = "user_" + ("a" * 75000)
        data = ["first_user", long_user, "last_user"]
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        extracted = list(StreamingTargetExtractor.stream_json(str(file_path)))
        self.assertEqual(len(extracted), 3)
        self.assertEqual(extracted[0], "first_user")
        self.assertEqual(extracted[1], long_user)
        self.assertEqual(extracted[2], "last_user")

    def test_jsonl_line_delimited_extraction(self):
        """P0 Test: Verifies line-delimited JSON (JSONL / NDJSON) streaming."""
        file_path = self.test_dir / "stream.jsonl"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write('{"username": "jsonl_user_1"}\n')
            f.write('{"user": "jsonl_user_2"}\n')
            f.write('"jsonl_user_3"\n')

        extracted = list(StreamingTargetExtractor.stream_json(str(file_path)))
        self.assertEqual(extracted, ["jsonl_user_1", "jsonl_user_2", "jsonl_user_3"])

if __name__ == "__main__":
    unittest.main()