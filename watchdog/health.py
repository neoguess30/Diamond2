from __future__ import annotations
import time
from typing import Any, Tuple

from core.state.enums import (
    SystemHealthState,
    DatabaseHealthState,
    DiskHealthState,
    CircuitState
)

class HealthEvaluator:
    """Evaluates multi-tier health states combining storage, network, and thread heartbeats."""
    
    @staticmethod
    def evaluate(
        scanner: Any,
        network: Any,
        db: Any,
        invariants_ok: bool,
        is_starving: bool,
        long_slope: float
    ) -> Tuple[SystemHealthState, float, float]:
        now = time.monotonic()
        scanner_active = scanner.pause_event.is_set()
        time_since_heartbeat = (now - scanner.last_heartbeat_monotonic) if scanner_active else 0.0
        time_since_last_completed = (now - scanner.last_completed_job_monotonic) if scanner_active else 0.0
        
        circuit_st = network.circuit_breaker.get_state()
        disk_st = db.check_disk_health()
        db_health = db.get_health_state()

        if disk_st in [DiskHealthState.CRITICAL, DiskHealthState.HALTED] or db_health != DatabaseHealthState.HEALTHY:
            return SystemHealthState.DEGRADED, time_since_heartbeat, time_since_last_completed
        elif circuit_st == CircuitState.OPEN:
            return SystemHealthState.DEGRADED, time_since_heartbeat, time_since_last_completed
        elif scanner_active and (time_since_heartbeat > 30.0 or (scanner.get_queue_len() > 0 and time_since_last_completed > 45.0)):
            return SystemHealthState.STALLED, time_since_heartbeat, time_since_last_completed
        elif long_slope > 25.0:
            return SystemHealthState.DEGRADED, time_since_heartbeat, time_since_last_completed
        elif invariants_ok and not is_starving:
            return SystemHealthState.HEALTHY, time_since_heartbeat, time_since_last_completed
        
        return SystemHealthState.DEGRADED, time_since_heartbeat, time_since_last_completed