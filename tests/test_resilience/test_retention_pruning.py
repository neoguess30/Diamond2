from __future__ import annotations
import unittest
import os
import shutil
import sqlite3
import time
from pathlib import Path

from persistence.database import ConsolidatedDatabaseManager
from persistence.writer.storage_writer import StorageWriterWorker

class TestRetentionPruning(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path("./test_retention_env")
        self.test_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = str(self.test_dir / "retention_test.db")
        self.db_mgr = ConsolidatedDatabaseManager(self.db_path)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_pruning_health_snapshots_older_than_7_days(self):
        """P0 Test: Verifies that health snapshots older than 7 days are pruned."""
        conn = self.db_mgr._get_connection()
        conn.execute("""
            INSERT INTO health_snapshots (session_id, timestamp, requests, successful_requests)
            VALUES ('old_session', datetime('now', '-10 days'), 100, 95);
        """)
        conn.execute("""
            INSERT INTO health_snapshots (session_id, timestamp, requests, successful_requests)
            VALUES ('old_session', datetime('now', '-8 days'), 200, 190);
        """)
        conn.execute("""
            INSERT INTO health_snapshots (session_id, timestamp, requests, successful_requests)
            VALUES ('recent_session', datetime('now', '-1 days'), 50, 48);
        """)
        conn.execute("""
            INSERT INTO health_snapshots (session_id, timestamp, requests, successful_requests)
            VALUES ('recent_session', CURRENT_TIMESTAMP, 10, 10);
        """)
        conn.commit()
        conn.close()

        pruned_count = self.db_mgr.prune_old_health_snapshots(retention_days=7)
        self.assertEqual(pruned_count, 2)

    def test_pruning_dead_letters_older_than_30_days(self):
        """P0 Test: Verifies that dead jobs older than 30 days are pruned while recent ones are preserved."""
        conn = self.db_mgr._get_connection()
        conn.execute("""
            INSERT INTO dead_jobs (job_id, username, error, attempts, reason, failure_category, first_seen, last_attempt)
            VALUES ('dead_old_1', 'old_user_1', 'timeout', 3, 'MAX_RETRIES', 'TIMEOUT', datetime('now', '-40 days'), datetime('now', '-35 days'));
        """)
        conn.execute("""
            INSERT INTO dead_jobs (job_id, username, error, attempts, reason, failure_category, first_seen, last_attempt)
            VALUES ('dead_old_2', 'old_user_2', 'timeout', 3, 'MAX_RETRIES', 'TIMEOUT', datetime('now', '-45 days'), datetime('now', '-32 days'));
        """)
        conn.execute("""
            INSERT INTO dead_jobs (job_id, username, error, attempts, reason, failure_category, first_seen, last_attempt)
            VALUES ('dead_recent_1', 'recent_user_1', 'timeout', 3, 'MAX_RETRIES', 'TIMEOUT', datetime('now', '-5 days'), datetime('now', '-1 days'));
        """)
        conn.commit()
        conn.close()

        pruned_count = self.db_mgr.prune_old_dead_letters(retention_days=30)
        self.assertEqual(pruned_count, 2)

        # Verify only 1 recent record remains
        conn = self.db_mgr._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM dead_jobs;")
        self.assertEqual(cur.fetchone()[0], 1)
        conn.close()

if __name__ == "__main__":
    unittest.main()