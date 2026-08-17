from __future__ import annotations
import time
import threading
from collections import deque, defaultdict
from typing import Dict, Tuple, Optional
from core.state.enums import MemoryBudgetState
from core.utils import get_process_memory_mb, get_process_handles_count, get_system_ram_percent

class SystemMetrics:
    def __init__(self, reservoir_size: int = 10000):
        self.lock = threading.RLock()
        self.reservoir_size = reservoir_size
        self.latencies_network: deque = deque(maxlen=reservoir_size)
        self.latencies_parser: deque = deque(maxlen=reservoir_size)
        self.payload_sizes_html: deque = deque(maxlen=reservoir_size)
        self.latencies_db: deque = deque(maxlen=1000)
        self.latencies_checkpoint: deque = deque(maxlen=500)
        self.latencies_queue_wait: deque = deque(maxlen=reservoir_size)
        
        self.lifetime_requests = 0
        self.lifetime_successful_requests = 0
        self.lifetime_429 = 0
        self.lifetime_5xx = 0
        self.lifetime_timeouts = 0
        self.lifetime_parse_errors = 0
        self.lifetime_unknowns = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.retry_enqueued = 0
        self.retry_success = 0
        self.retry_exhausted = 0
        self.dead_letter_count = 0
        self.poison_jobs_count = 0
        self.total_targets_scanned = 0
        self.total_jobs_persisted = 0
        self.db_writes = 0
        self.ram_min = float('inf')
        self.ram_max = 0.0
        self.scanner_queue_peak = 0
        self.writer_queue_peak = 0
        self.threads_peak = 0
        self.handles_peak = 0
        self.thread_birth_count = 0
        self.thread_death_count = 0
        self.thread_restart_count = 0
        
        # P0 Parked / Paused Patterns Observability
        self.paused_pattern_depth = 0
        self.oldest_paused_job_age_sec = 0.0

        self.ram_short_history: deque = deque(maxlen=150)
        self.ram_long_history: deque = deque(maxlen=900)
        self.start_monotonic = time.monotonic()
        self.last_network_success_monotonic = time.monotonic()
        self.last_scan_success_monotonic = time.monotonic()
        self.last_persist_success_monotonic = time.monotonic()
        self.last_rate_calc_time = time.monotonic()
        self.last_rate_req_count = 0
        self.current_req_per_sec = 0.0
        self.stats_60s_window: deque = deque()

    def record_network_request(self, latency_ms: float, status_code: int):
        with self.lock:
            self.lifetime_requests += 1
            self.latencies_network.append(latency_ms)
            if status_code == 200:
                self.lifetime_successful_requests += 1
                self.last_network_success_monotonic = time.monotonic()
            elif status_code == 429:
                self.lifetime_429 += 1
            elif 500 <= status_code <= 599:
                self.lifetime_5xx += 1
            elif status_code == 0:
                self.lifetime_timeouts += 1
            now = time.monotonic()
            elapsed = now - self.last_rate_calc_time
            if elapsed >= 2.0:
                req_delta = self.lifetime_requests - self.last_rate_req_count
                self.current_req_per_sec = req_delta / elapsed
                self.last_rate_calc_time = now
                self.last_rate_req_count = self.lifetime_requests

    def record_parser_latency(self, duration_ms: float, payload_size_bytes: int = 0):
        with self.lock:
            self.latencies_parser.append(duration_ms)
            if payload_size_bytes > 0:
                self.payload_sizes_html.append(payload_size_bytes)

    def record_queue_wait(self, wait_ms: float):
        with self.lock:
            self.latencies_queue_wait.append(wait_ms)

    def record_db_commit(self, duration_ms: float, write_count: int):
        with self.lock:
            self.db_writes += write_count
            self.latencies_db.append(duration_ms)
            self.last_persist_success_monotonic = time.monotonic()

    def record_checkpoint_latency(self, duration_ms: float):
        with self.lock:
            self.latencies_checkpoint.append(duration_ms)

    def record_cache_lookup(self, hit: bool):
        with self.lock:
            if hit:
                self.cache_hits += 1
            else:
                self.cache_misses += 1

    def record_paused_patterns_state(self, depth: int, oldest_age_sec: float):
        with self.lock:
            self.paused_pattern_depth = depth
            self.oldest_paused_job_age_sec = oldest_age_sec

    def get_dynamic_hit_rate_str(self) -> str:
        with self.lock:
            total_lookups = self.cache_hits + self.cache_misses
            if total_lookups == 0:
                return "N/A"
            rate = (self.cache_hits / total_lookups) * 100.0
            return f"{rate:.1f}%"

    def record_target_scanned(self, status: str):
        with self.lock:
            self.total_targets_scanned += 1
            self.last_scan_success_monotonic = time.monotonic()
            now = time.monotonic()
            self.stats_60s_window.append((now, status))
            while self.stats_60s_window and (now - self.stats_60s_window[0][0]) > 60.0:
                self.stats_60s_window.popleft()

    def get_delta_60s(self) -> Dict[str, int]:
        with self.lock:
            now = time.monotonic()
            while self.stats_60s_window and (now - self.stats_60s_window[0][0]) > 60.0:
                self.stats_60s_window.popleft()
            counts = defaultdict(int)
            for _, st in self.stats_60s_window:
                counts[st] += 1
            counts["TOTAL"] = len(self.stats_60s_window)
            return counts

    def record_jobs_persisted_batch(self, count: int):
        with self.lock:
            self.total_jobs_persisted += count

    def record_queues(self, scanner_q: int, writer_q: int):
        with self.lock:
            if scanner_q > self.scanner_queue_peak:
                self.scanner_queue_peak = scanner_q
            if writer_q > self.writer_queue_peak:
                self.writer_queue_peak = writer_q

    def record_resources(self, ram_mb: Optional[float], threads_count: int, handles_count: int):
        with self.lock:
            if threads_count > self.threads_peak:
                self.threads_peak = threads_count
            if handles_count > self.handles_peak:
                self.handles_peak = handles_count
            if ram_mb is not None:
                if ram_mb < self.ram_min:
                    self.ram_min = ram_mb
                if ram_mb > self.ram_max:
                    self.ram_max = ram_mb
                now = time.monotonic()
                self.ram_short_history.append((now, ram_mb))
                self.ram_long_history.append((now, ram_mb))

    def evaluate_memory_budget(self) -> MemoryBudgetState:
        ram_pct = get_system_ram_percent()
        if ram_pct >= 90.0:
            return MemoryBudgetState.EMERGENCY
        elif ram_pct >= 85.0:
            return MemoryBudgetState.PAUSE_PRODUCERS
        elif ram_pct >= 75.0:
            return MemoryBudgetState.THROTTLE
        elif ram_pct >= 60.0:
            return MemoryBudgetState.WARNING
        return MemoryBudgetState.NORMAL

    def calculate_ram_slope_mb_per_hr(self) -> Tuple[float, float]:
        with self.lock:
            def _calc_slope(hist: deque) -> float:
                if len(hist) < 10:
                    return 0.0
                t_first, r_first = hist[0]
                t_last, r_last = hist[-1]
                elapsed = t_last - t_first
                if elapsed < 20.0:
                    return 0.0
                return ((r_last - r_first) / elapsed) * 3600.0

            short_slope = _calc_slope(self.ram_short_history)
            long_slope = _calc_slope(self.ram_long_history)
            return short_slope, long_slope

    def get_latency_percentiles(self) -> Tuple[float, float, float]:
        with self.lock:
            if not self.latencies_network:
                return 0.0, 0.0, 0.0
            sorted_lat = sorted(self.latencies_network)
            n = len(sorted_lat)
            p50 = sorted_lat[int(0.50 * n)]
            p95 = sorted_lat[min(int(0.95 * n), n - 1)]
            p99 = sorted_lat[min(int(0.99 * n), n - 1)]
            return p50, p95, p99

    def get_parser_latency_percentiles(self) -> Tuple[float, float, float]:
        """P0: Computes dedicated parser latency percentiles to audit CPU hotspots."""
        with self.lock:
            if not self.latencies_parser:
                return 0.0, 0.0, 0.0
            sorted_lat = sorted(self.latencies_parser)
            n = len(sorted_lat)
            p50 = sorted_lat[int(0.50 * n)]
            p95 = sorted_lat[min(int(0.95 * n), n - 1)]
            p99 = sorted_lat[min(int(0.99 * n), n - 1)]
            return p50, p95, p99

    def get_html_payload_stats(self) -> Tuple[float, float]:
        """Returns (avg_size_kb, p95_size_kb) for incoming HTML documents."""
        with self.lock:
            if not self.payload_sizes_html:
                return 0.0, 0.0
            avg_kb = (sum(self.payload_sizes_html) / len(self.payload_sizes_html)) / 1024.0
            sorted_sizes = sorted(self.payload_sizes_html)
            n = len(sorted_sizes)
            p95_kb = sorted_sizes[min(int(0.95 * n), n - 1)] / 1024.0
            return avg_kb, p95_kb

    def get_latency_breakdown_avg(self) -> Dict[str, float]:
        with self.lock:
            avg_net = (sum(self.latencies_network) / len(self.latencies_network)) if self.latencies_network else 0.0
            avg_parse = (sum(self.latencies_parser) / len(self.latencies_parser)) if self.latencies_parser else 0.0
            avg_db = (sum(self.latencies_db) / len(self.latencies_db)) if self.latencies_db else 0.0
            avg_ckpt = (sum(self.latencies_checkpoint) / len(self.latencies_checkpoint)) if self.latencies_checkpoint else 0.0
            avg_queue = (sum(self.latencies_queue_wait) / len(self.latencies_queue_wait)) if self.latencies_queue_wait else 0.0
            return {
                "network_ms": avg_net,
                "parser_ms": avg_parse,
                "db_ms": avg_db,
                "checkpoint_ms": avg_ckpt,
                "queue_wait_ms": avg_queue
            }

    def get_effective_throughput_jobs_per_sec(self) -> float:
        with self.lock:
            elapsed = time.monotonic() - self.start_monotonic
            return (self.total_jobs_persisted / elapsed) if elapsed > 0.5 else 0.0

    def get_snapshot(self) -> dict:
        with self.lock:
            p50, p95, p99 = self.get_latency_percentiles()
            parse_p50, parse_p95, parse_p99 = self.get_parser_latency_percentiles()
            html_avg_kb, html_p95_kb = self.get_html_payload_stats()
            short_slope, long_slope = self.calculate_ram_slope_mb_per_hr()
            breakdown = self.get_latency_breakdown_avg()
            deltas = self.get_delta_60s()
            return {
                "requests": self.lifetime_requests,
                "success": self.lifetime_successful_requests,
                "429": self.lifetime_429,
                "5xx": self.lifetime_5xx,
                "timeouts": self.lifetime_timeouts,
                "parse_err": self.lifetime_parse_errors,
                "unknowns": self.lifetime_unknowns,
                "hit_rate_str": self.get_dynamic_hit_rate_str(),
                "retry_success": self.retry_success,
                "retry_exhausted": self.retry_exhausted,
                "dead_letters": self.dead_letter_count,
                "poison_jobs": self.poison_jobs_count,
                "targets_scanned": self.total_targets_scanned,
                "jobs_persisted": self.total_jobs_persisted,
                "effective_jobs_per_sec": self.get_effective_throughput_jobs_per_sec(),
                "db_writes": self.db_writes,
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p99,
                "parser_p50_ms": parse_p50,
                "parser_p95_ms": parse_p95,
                "parser_p99_ms": parse_p99,
                "html_avg_kb": html_avg_kb,
                "html_p95_kb": html_p95_kb,
                "breakdown": breakdown,
                "deltas_60s": deltas,
                "req_per_sec": self.current_req_per_sec,
                "ram_min": self.ram_min if self.ram_min != float('inf') else 0.0,
                "ram_max": self.ram_max,
                "ram_short_slope": short_slope,
                "ram_long_slope": long_slope,
                "threads_current": threading.active_count(),
                "threads_peak": self.threads_peak,
                "threads_restarts": self.thread_restart_count,
                "handles_current": get_process_handles_count(),
                "handles_peak": self.handles_peak,
                "q_scanner_peak": self.scanner_queue_peak,
                "q_writer_peak": self.writer_queue_peak,
                "paused_pattern_depth": self.paused_pattern_depth,
                "oldest_paused_job_age_sec": self.oldest_paused_job_age_sec,
                "last_net_success_sec": time.monotonic() - self.last_network_success_monotonic,
                "last_scan_success_sec": time.monotonic() - self.last_scan_success_monotonic,
                "last_persist_success_sec": time.monotonic() - self.last_persist_success_monotonic
            }

METRICS = SystemMetrics()