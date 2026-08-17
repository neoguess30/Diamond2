from __future__ import annotations
import gc
import time
import threading
from typing import Tuple, Optional

from core.utils import (
    get_process_memory_mb,
    get_process_handles_count,
    get_system_ram_percent
)
from core.metrics import METRICS
from core.logger import logger

class ResourceMonitor:
    """
    Monitors OS resource usage and performs intelligent, slope-aware garbage collection
    without inducing Stop-the-World CPU/latency spikes during high-throughput scanning.
    """
    def __init__(self):
        self.ram_baseline = get_process_memory_mb() or 45.0
        self.last_gc_ram = self.ram_baseline
        self.last_gc_time = time.monotonic()
        self.min_gc_interval_sec = 60.0  # P0: Minimum 60-second cooldown between forced GC cycles

    def sample_and_record(self, scanner_queue_len: int, writer_queue_len: int) -> Tuple[Optional[float], int, int]:
        current_ram = get_process_memory_mb()
        current_handles = get_process_handles_count()
        current_threads = threading.active_count()
        
        METRICS.record_resources(current_ram, current_threads, current_handles)
        METRICS.record_queues(scanner_queue_len, writer_queue_len)

        # P0 Slope-Aware & Threshold-Gated Adaptive Garbage Collection:
        # Prevents CPU and latency spikes from aggressive periodic GC traversals.
        now = time.monotonic()
        time_since_last_gc = now - self.last_gc_time

        if current_ram is not None and time_since_last_gc >= self.min_gc_interval_sec:
            ram_pct = get_system_ram_percent()
            ram_delta = current_ram - self.last_gc_ram
            short_slope, long_slope = METRICS.calculate_ram_slope_mb_per_hr()

            # Trigger ONLY if significant sustained inflation (>= 150MB) with positive slope or critical RAM pressure
            should_collect = (ram_pct >= 85.0) or (ram_delta >= 150.0 and short_slope > 15.0)

            if should_collect:
                gc.collect()
                self.last_gc_time = now
                updated_ram = get_process_memory_mb()
                if updated_ram is not None:
                    freed = max(0.0, current_ram - updated_ram)
                    self.last_gc_ram = updated_ram
                    logger.info(f"⚡ Slope-Aware Adaptive GC Executed: RAM adjusted to {self.last_gc_ram:.1f} MB (Freed {freed:.1f} MB)")

        return current_ram, current_handles, current_threads