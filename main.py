from __future__ import annotations
import sys
from app.application import Application
from tests.integration.self_test import run_self_test
from tests.integration.network_test import run_network_live_test
from tests.soak.soak_test import run_soak_test
from core.utils import (
    get_process_memory_mb_str,
    get_process_handles_count,
    get_free_disk_space_gb,
    get_disk_health_state
)
from parser.engine import HAS_LXML
from network.session import HAS_CURL_CFFI

try:
    import PyQt6
    HAS_PYQT6 = True
except ImportError:
    HAS_PYQT6 = False

def run_diagnostic_mode() -> int:
    print("=" * 65)
    print("🦅 FALCON // SYSTEM COMMAND - DEEP DIAGNOSTIC REPORT")
    print("=" * 65)
    print(f"Python Version  : {sys.version.split()[0]}")
    print(f"Platform        : {sys.platform}")
    print(f"Process RAM     : {get_process_memory_mb_str()}")
    print(f"Active Handles  : {get_process_handles_count()}")
    print(f"Desktop Storage : {get_free_disk_space_gb():.2f} GB Free")
    print(f"Disk Health     : {get_disk_health_state().value}")
    print(f"lxml C-Engine   : {'AVAILABLE' if HAS_LXML else 'FALLBACK (html.parser)'}")
    print(f"curl_cffi TLS   : {'ACTIVE' if HAS_CURL_CFFI else 'MISSING'}")
    print(f"PyQt6 GUI Engine: {'AVAILABLE' if HAS_PYQT6 else 'HEADLESS ONLY'}")
    print("=" * 65)
    return 0

def main() -> int:
    args = sys.argv[1:]
    if args:
        cmd = args[0].lower()
        if cmd in ["--network-test", "-network-test", "-net"]:
            target = args[1] if len(args) > 1 and not args[1].startswith("-") else "durov"
            return run_network_live_test(target_user=target)
        elif cmd in ["--test", "-test", "-t"]:
            return run_self_test()
        elif cmd in ["--soak", "-soak", "-s"]:
            hours = 24.0
            if len(args) > 1:
                try:
                    hours = float(args[1])
                except ValueError:
                    hours = 24.0
            return run_soak_test(hours=hours)
        elif cmd in ["--diagnostic", "-diagnostic", "-d"]:
            return run_diagnostic_mode()
        elif cmd in ["--headless", "-headless", "-h"]:
            pat = ""
            imp = ""
            if "--pattern" in args:
                idx = args.index("--pattern")
                if idx + 1 < len(args): pat = args[idx + 1]
            if "--import" in args:
                idx = args.index("--import")
                if idx + 1 < len(args): imp = args[idx + 1]
            app = Application()
            return app.run_headless(pattern=pat, import_file=imp)

    app = Application()
    return app.run_gui()

if __name__ == "__main__":
    raise SystemExit(main())