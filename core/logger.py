from __future__ import annotations
import sys
import os
import re
import time
import logging
from logging.handlers import RotatingFileHandler
import traceback
import threading
from datetime import datetime, timezone
from typing import Dict, Tuple

from core.utils import (
    get_process_memory_mb_str,
    get_process_handles_count,
    get_free_disk_space_gb
)

class SensitiveDataSanitizer(logging.Formatter):
    """Masks authorization tokens, credentials, cookies, and proxy strings from logs."""
    SENSITIVE_PATTERNS = [
        (re.compile(r'(?i)(bearer\s+)[a-z0-9_\-\.]+'), r'\1********'),
        (re.compile(r'(?i)(cookie\s*:\s*)[^\r\n]+'), r'\1[MASKED_COOKIES]'),
        (re.compile(r'(?i)(password\s*=\s*)[^&\s]+'), r'\1********'),
        (re.compile(r'(?i)(proxy\s*=\s*https?://[^:]+:)[^@]+@'), r'\1********@'),
    ]

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        sanitized = original
        for pattern, replacement in self.SENSITIVE_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)
        return sanitized

class ThrottledDuplicateLogFilter(logging.Filter):
    """
    P0 Log Anti-Spam Filter:
    Aggregates repeated errors under heavy pressure (e.g. 10,000 timeouts/sec)
    and flushes aggregated summaries every 2 seconds to prevent I/O bottlenecks.
    """
    def __init__(self, flush_interval_sec: float = 2.0):
        super().__init__()
        self.flush_interval = flush_interval_sec
        self.last_flush = time.monotonic()
        self.error_counts: Dict[str, int] = {}
        self.lock = threading.RLock()

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < logging.WARNING:
            return True

        msg = record.getMessage()
        now = time.monotonic()

        with self.lock:
            # Check flush interval
            if now - self.last_flush >= self.flush_interval:
                self.error_counts.clear()
                self.last_flush = now
                return True

            count = self.error_counts.get(msg, 0) + 1
            self.error_counts[msg] = count

            if count == 1:
                return True
            elif count in (5, 50, 500, 5000):
                record.msg = f"[SPAM SUPPRESSED × {count}] {record.msg}"
                return True
            return False

logger = logging.getLogger("FalconCore")
logger.setLevel(logging.INFO)

log_file = "falcon_production.log"
rotating_handler = RotatingFileHandler(
    log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
formatter = SensitiveDataSanitizer("%(asctime)s | %(levelname)-7s | %(threadName)-14s | %(message)s")
rotating_handler.setFormatter(formatter)
rotating_handler.addFilter(ThrottledDuplicateLogFilter())
logger.addHandler(rotating_handler)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
console_handler.addFilter(ThrottledDuplicateLogFilter())
logger.addHandler(console_handler)

def global_crash_guard_hook(exctype, value=None, tb=None):
    """Intercepts unhandled crashes, sanitizing exceptions to never hold response bodies in memory."""
    thread_name = "MainThread"
    if hasattr(exctype, "exc_type") and hasattr(exctype, "exc_value"):
        args = exctype
        exctype = args.exc_type
        value = args.exc_value
        tb = args.exc_traceback
        if hasattr(args, "thread") and args.thread:
            thread_name = getattr(args.thread, "name", str(args.thread))
    else:
        current_t = threading.current_thread()
        if current_t:
            thread_name = current_t.name

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # P0: Truncate raw exception strings to max 1000 characters to prevent holding huge payloads in log RAM
    err_str = str(value)[:1000]
    stack_trace = "".join(traceback.format_exception(exctype, value, tb))
    
    crash_report = f"""
================================================================================
🚨 CYBER-FALCON COMMAND CENTER CRASH REPORT - {timestamp}
================================================================================
Failing Thread : {thread_name}
Exception Type : {exctype.__name__ if hasattr(exctype, '__name__') else str(exctype)}
Exception Value: {err_str}
Process RAM    : {get_process_memory_mb_str()}
OS Handles     : {get_process_handles_count()}
Disk Free      : {get_free_disk_space_gb():.2f} GB Free

Stack Trace:
{stack_trace}
================================================================================
"""
    logger.critical(crash_report)
    try:
        with open("falcon_crash.log", "a", encoding="utf-8") as f:
            f.write(crash_report + "\n")
    except Exception:
        pass
        
    if thread_name == "MainThread" and hasattr(sys, "__excepthook__"):
        sys.__excepthook__(exctype, value, tb)

sys.excepthook = global_crash_guard_hook
if hasattr(threading, "excepthook"):
    threading.excepthook = global_crash_guard_hook