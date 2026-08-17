from __future__ import annotations
from typing import Tuple, Any
from core.state.enums import EngineState

class WorkerLivenessMonitor:
    """Monitors scanner and storage writer thread heartbeats and unexpected terminations."""
    
    @staticmethod
    def check_scanner_alive(scanner: Any, engine_state: EngineState) -> bool:
        if engine_state == EngineState.RUNNING and not scanner.isRunning():
            return False
        return True

    @staticmethod
    def check_writer_alive(writer: Any, engine_state: EngineState) -> bool:
        if engine_state not in (EngineState.STOPPING, EngineState.STOPPED, EngineState.STARTUP_BLOCKED):
            if not writer.isRunning():
                return False
        return True