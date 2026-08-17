from __future__ import annotations
import os
import sys
import sqlite3
from typing import Tuple

from core.config import DISK_CRITICAL_GB
from core.utils import get_free_disk_space_gb, get_real_desktop_path
from core.logger import logger

class DependencyValidator:
    """Performs rigorous pre-flight environment, disk, and database validation."""

    @staticmethod
    def verify_environment(db_path: str = "falcon_master.db") -> Tuple[bool, str]:
        # 1. Python Version Check
        if sys.version_info < (3, 9):
            return False, f"Startup Blocked: Python 3.9+ required (Current: {sys.version.split()[0]})"

        # 2. Disk Space Guard
        free_gb = get_free_disk_space_gb()
        if free_gb < DISK_CRITICAL_GB:
            return False, f"Startup Blocked: Insufficient disk space ({free_gb:.2f} GB free < {DISK_CRITICAL_GB} GB)"

        # 3. SQLite Database R/W & Lock Verification
        try:
            conn = sqlite3.connect(db_path, timeout=5.0)
            try:
                conn.execute("CREATE TABLE IF NOT EXISTS _dependency_check (id INTEGER PRIMARY KEY);")
                conn.execute("INSERT OR REPLACE INTO _dependency_check (id) VALUES (1);")
                conn.commit()
                conn.execute("DROP TABLE _dependency_check;")
                conn.commit()
            finally:
                conn.close()
        except Exception as dbe:
            return False, f"Startup Blocked: Database R/W check failed on '{db_path}': {dbe}"

        # 4. Desktop Export Path Writable Check
        try:
            desktop_dir = get_real_desktop_path()
            test_file = desktop_dir / ".falcon_perm_test.tmp"
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("OK")
            if os.path.exists(test_file):
                os.remove(test_file)
        except Exception as fe:
            return False, f"Startup Blocked: Desktop export directory not writable: {fe}"

        logger.info("DependencyValidator: All pre-flight dependency checks PASSED.")
        return True, "PREFLIGHT_ALL_SYSTEMS_OPERATIONAL"