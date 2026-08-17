from __future__ import annotations
from typing import Any
from core.logger import logger

class SupervisorAutoHealer:
    """Coordinates automated thread reconstitution and signal reconnection."""
    
    @staticmethod
    def heal_scanner(controller: Any) -> bool:
        logger.critical("🚨 SupervisorAutoHealer: Rebuilding dead ScannerWorker...")
        return controller.replace_dead_worker()

    @staticmethod
    def heal_writer(controller: Any) -> bool:
        logger.critical("🚨 SupervisorAutoHealer: Rebuilding dead StorageWriterWorker...")
        return controller.replace_dead_writer()