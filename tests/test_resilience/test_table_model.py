from __future__ import annotations
import unittest

from ui.models.table_model import LiveScannerTableModel

class TestTableModelDeduplication(unittest.TestCase):

    def test_in_batch_duplicate_usernames_folded_to_latest(self):
        """
        P0 Test: Proves that multiple occurrences of the same username within a single batch
        are cleanly folded into a single row displaying the latest state (No duplicate rows!).
        """
        model = LiveScannerTableModel(max_rows=100)

        # Batch contains duplicate entries for @alice and @bob
        batch = [
            {"username": "@alice", "status": "UNAVAILABLE", "detail": "OLD_STATE", "result_sequence": 1},
            {"username": "@bob", "status": "UNAVAILABLE", "detail": "OLD_BOB", "result_sequence": 2},
            {"username": "@alice", "status": "AVAILABLE", "detail": "$500 USD", "result_sequence": 3},  # Latest state
            {"username": "@charlie", "status": "AUCTION", "detail": "100 TON", "result_sequence": 4}
        ]

        model.add_records_batch(batch)

        # Must contain exactly 3 rows (@alice, @bob, @charlie), NOT 4!
        self.assertEqual(model.rowCount(), 3)
        self.assertEqual(len(model.username_row_map), 3)

        # Verify @alice holds the latest updated state ($500 USD / AVAILABLE)
        alice_idx = model.username_row_map["@alice"]
        alice_record = model.rows[alice_idx]
        self.assertEqual(alice_record["status"], "AVAILABLE")
        self.assertEqual(alice_record["detail"], "$500 USD")
        self.assertEqual(alice_record["result_sequence"], 3)

    def test_table_max_rows_batch_eviction(self):
        """P0 Test: Verifies that table strictly respects max_rows bound under large batch inserts."""
        model = LiveScannerTableModel(max_rows=5)

        # Insert 7 new unique records
        batch = [{"username": f"@user_{i}", "status": "AVAILABLE", "result_sequence": i} for i in range(7)]
        model.add_records_batch(batch)

        # Row count must be capped at 5
        self.assertEqual(model.rowCount(), 5)
        self.assertEqual(len(model.username_row_map), 5)
        # Oldest 2 (@user_0, @user_1) evicted; remaining are @user_2 to @user_6
        self.assertNotIn("@user_0", model.username_row_map)
        self.assertNotIn("@user_1", model.username_row_map)
        self.assertIn("@user_6", model.username_row_map)

if __name__ == "__main__":
    unittest.main()