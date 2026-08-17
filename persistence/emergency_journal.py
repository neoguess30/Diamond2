from __future__ import annotations
import os
import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any, Optional

from core.config import (
    MAX_EMERGENCY_FILE_BYTES,
    MAX_EMERGENCY_TOTAL_STORAGE_BYTES
)
from core.logger import logger

class EmergencyJournalManager:
    """
    Enterprise Emergency Journal Engine:
    1. Rotated .jsonl file chunks (emergency_YYYY-MM-DD_NN.jsonl).
    2. Hard File Size & Total Pool Storage Caps (FIFO eviction of oldest logs).
    3. Fault-Tolerant Line-by-Line Recovery: Valid records restored to SQLite, torn/corrupted lines quarantined.
    """
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir / "emergency_journals"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.quarantine_file = self.storage_dir / "emergency_quarantine.corrupt"

    def get_active_write_file(self) -> Path:
        """Determines active rotated chunk file while enforcing storage caps."""
        self._enforce_total_storage_cap()
        
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        part = 1

        while True:
            target = self.storage_dir / f"emergency_{date_str}_{part:02d}.jsonl"
            if not target.exists():
                return target
            try:
                if target.stat().st_size < MAX_EMERGENCY_FILE_BYTES:
                    return target
            except Exception:
                return target
            part += 1
            if part > 999:
                return target

    def _enforce_total_storage_cap(self):
        """Enforces MAX_EMERGENCY_TOTAL_STORAGE_BYTES by purging oldest chunks first."""
        try:
            journal_files = sorted(
                self.storage_dir.glob("emergency_*.jsonl"),
                key=lambda p: p.stat().st_mtime
            )
            total_size = sum(f.stat().st_size for f in journal_files)

            while total_size > MAX_EMERGENCY_TOTAL_STORAGE_BYTES and journal_files:
                oldest = journal_files.pop(0)
                file_size = oldest.stat().st_size
                oldest.unlink(missing_ok=True)
                total_size -= file_size
                logger.warning(f"🚨 EmergencyJournal: Storage pool exceeded {MAX_EMERGENCY_TOTAL_STORAGE_BYTES // (1024*1024)}MB. Purged oldest chunk: {oldest.name}")
        except Exception as e:
            logger.error(f"EmergencyJournal: Storage cap enforcement error: {e}")

    def write_emergency_dump(self, pending_records: List[Dict[str, Any]], error_reason: str) -> Path:
        """Appends uncommitted records to active rotated journal with immediate fsync durability."""
        target_file = self.get_active_write_file()
        timestamp = datetime.now(timezone.utc).isoformat()

        with open(target_file, "a", encoding="utf-8", errors="ignore") as f:
            for rec in pending_records:
                safe_rec = {k: v for k, v in rec.items() if not k.startswith("_")}
                safe_rec["_emergency_timestamp"] = timestamp
                safe_rec["_emergency_reason"] = str(error_reason)
                line = json.dumps(safe_rec, ensure_ascii=False)
                f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

        logger.critical(f"🚨 Emergency Dump: Successfully persisted {len(pending_records)} records to {target_file.name} with fsync barrier.")
        return target_file

    def replay_and_restore_journals(self, db_manager: Any) -> Tuple[int, int]:
        """
        P0 Production Startup Recovery:
        - Scans all un-replayed emergency_*.jsonl files.
        - Restores completed scan results directly into scan_results.
        - Restores uncompleted tasks into pending_jobs.
        - Quarantines torn/corrupted lines to quarantine log.
        - Renames processed chunks to .replayed to guarantee single-execution idempotency.
        """
        journal_files = sorted(self.storage_dir.glob("emergency_*.jsonl"))
        if not journal_files:
            return 0, 0

        total_restored = 0
        total_quarantined = 0

        for j_file in journal_files:
            logger.info(f"⚡ Emergency Recovery: Replaying {j_file.name}...")
            valid_batch = []

            with open(j_file, "r", encoding="utf-8", errors="replace") as f:
                line_no = 0
                for line in f:
                    line_no += 1
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                        valid_batch.append(record)
                    except json.JSONDecodeError as jde:
                        total_quarantined += 1
                        self._quarantine_corrupted_line(j_file.name, line_no, raw, str(jde))

            if valid_batch and db_manager:
                from core.models.job import Job
                from core.state.enums import JobSource
                
                try:
                    conn = db_manager._get_connection()
                    try:
                        scan_results_to_insert = []
                        pending_jobs_to_insert = []

                        for r in valid_batch:
                            uname = (r.get("raw_username") or r.get("username", "")).lower().strip().replace("@", "")
                            if not uname:
                                continue
                            
                            status = r.get("status")
                            # If result was already evaluated before crash, commit directly to scan_results
                            if status in ["AVAILABLE", "AUCTION", "SOLD", "TAKEN", "UNAVAILABLE", "FREE"]:
                                conf = r.get("confidence", 90.0)
                                price = r.get("price", "")
                                detail = r.get("detail", "")
                                pat_id = r.get("pat_id", "EMERGENCY_RECOVERED")
                                seq_num = r.get("result_sequence", 0)
                                job_id = r.get("job_id", "")
                                scan_results_to_insert.append((uname, status, conf, price, detail, pat_id, seq_num, job_id))
                            else:
                                j = Job.create_new(
                                    username=uname,
                                    pattern_id=r.get("pat_id", "EMERGENCY_RECOVERED"),
                                    source=JobSource.RECOVERY
                                )
                                if "attempt" in r and isinstance(r["attempt"], int):
                                    j.attempt = r["attempt"]
                                if "job_id" in r and r["job_id"]:
                                    j.job_id = r["job_id"]
                                if "correlation_id" in r and r["correlation_id"]:
                                    j.correlation_id = r["correlation_id"]
                                pending_jobs_to_insert.append(j)

                        # Insert scan results with True UPSERT
                        for row in scan_results_to_insert:
                            uname, status, conf, price, detail, pat_id, seq_num, job_id = row
                            conn.execute("""
                                INSERT INTO scan_results (username, status, confidence, price, detail, pattern_id, result_sequence, scanned_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(username) DO UPDATE SET
                                    status = excluded.status,
                                    confidence = excluded.confidence,
                                    price = excluded.price,
                                    detail = excluded.detail,
                                    pattern_id = excluded.pattern_id,
                                    result_sequence = excluded.result_sequence,
                                    scanned_at = CURRENT_TIMESTAMP;
                            """, (uname, status, conf, price, detail, pat_id, seq_num))
                            if job_id:
                                conn.execute("DELETE FROM pending_jobs WHERE job_id = ?;", (job_id,))
                            total_restored += 1

                        conn.commit()

                        if pending_jobs_to_insert:
                            db_manager.save_pending_jobs_batch(pending_jobs_to_insert, wait_for_commit=True)
                            total_restored += len(pending_jobs_to_insert)

                    finally:
                        conn.close()
                except Exception as ex:
                    logger.critical(f"Emergency Recovery: Error persisting salvaged records from {j_file.name}: {ex}")

            # Mark processed chunk as replayed
            replayed_path = j_file.with_suffix(".replayed")
            j_file.rename(replayed_path)

        logger.info(f"✅ Emergency Recovery Complete: {total_restored} records restored | {total_quarantined} torn lines quarantined.")
        return total_restored, total_quarantined

    def _quarantine_corrupted_line(self, filename: str, line_no: int, raw_content: str, error_msg: str):
        """Isolates torn / corrupted JSON lines into quarantine log with forensics metadata."""
        try:
            with open(self.quarantine_file, "a", encoding="utf-8", errors="ignore") as qf:
                meta = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source_file": filename,
                    "line_number": line_no,
                    "error": error_msg,
                    "raw_content": raw_content
                }
                qf.write(json.dumps(meta, ensure_ascii=False) + "\n")
                qf.flush()
            logger.warning(f"⚠️ Quarantined torn JSON line #{line_no} from {filename}: {error_msg}")
        except Exception as e:
            logger.error(f"Failed to write to quarantine file: {e}")