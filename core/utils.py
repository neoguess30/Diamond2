from __future__ import annotations
import os
import shutil
from pathlib import Path
from typing import Optional
from core.state.enums import DiskHealthState
from core.config import DISK_HALT_WRITES_GB, DISK_CRITICAL_GB, DISK_WARNING_GB

def get_process_memory_mb() -> Optional[float]:
    try:
        import psutil
        process = psutil.Process(os.getpid())
        return process.memory_info().rss / (1024 * 1024)
    except Exception:
        return None

def get_system_ram_percent() -> float:
    try:
        import psutil
        return psutil.virtual_memory().percent
    except Exception:
        return 50.0

def get_process_memory_mb_str() -> str:
    mem = get_process_memory_mb()
    return f"{mem:.1f} MB" if mem is not None else "N/A"

def get_process_handles_count() -> int:
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        if hasattr(proc, "num_handles"):
            return proc.num_handles()
        elif hasattr(proc, "num_fds"):
            return proc.num_fds()
        return 0
    except Exception:
        return 0

def get_free_disk_space_gb() -> float:
    try:
        total, used, free = shutil.disk_usage(Path.home())
        return free / (1024 ** 3)
    except Exception:
        return 10.0

def get_file_size_mb(path_str: str) -> float:
    try:
        if os.path.exists(path_str):
            return os.path.getsize(path_str) / (1024 * 1024)
        return 0.0
    except Exception:
        return 0.0

def get_disk_health_state(free_gb: Optional[float] = None) -> DiskHealthState:
    if free_gb is None:
        free_gb = get_free_disk_space_gb()
    if free_gb <= DISK_HALT_WRITES_GB:
        return DiskHealthState.HALTED
    elif free_gb <= DISK_CRITICAL_GB:
        return DiskHealthState.CRITICAL
    elif free_gb <= DISK_WARNING_GB:
        return DiskHealthState.WARNING
    return DiskHealthState.HEALTHY

def get_real_desktop_path() -> Path:
    onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
    if onedrive_desktop.exists():
        return onedrive_desktop
    std_desktop = Path.home() / "Desktop"
    std_desktop.mkdir(parents=True, exist_ok=True)
    return std_desktop
