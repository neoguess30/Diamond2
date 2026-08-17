from __future__ import annotations
import os
import json
import threading
from pathlib import Path
from typing import Dict, Any
from core.logger import logger

class AtomicConfigManager:
    """
    P0 Atomic Configuration Engine:
    Guarantees zero torn/corrupted configuration files during unexpected crashes
    using the atomic write-tmp-fsync-replace pattern.
    """
    def __init__(self, config_path: Path | str = "falcon_config.json"):
        self.config_path = Path(config_path)
        self.lock = threading.RLock()

    def load_config(self, default_config: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            if not self.config_path.exists():
                self.save_config(default_config)
                return dict(default_config)
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else dict(default_config)
            except Exception as e:
                logger.error(f"AtomicConfig: Corrupted config file detected ({e}). Restoring defaults.")
                self.save_config(default_config)
                return dict(default_config)

    def save_config(self, config_data: Dict[str, Any]) -> bool:
        with self.lock:
            tmp_path = self.config_path.with_suffix(".tmp")
            try:
                # 1. Write to temporary file
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, indent=4, ensure_ascii=False)
                    f.flush()
                    # 2. Flush to physical storage
                    os.fsync(f.fileno())

                # 3. Atomic rename/replace (POSIX & Windows atomic replacement)
                tmp_path.replace(self.config_path)
                return True
            except Exception as e:
                logger.critical(f"AtomicConfig: Failed to write configuration atomically: {e}")
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                return False