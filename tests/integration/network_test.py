from __future__ import annotations
import time
from parser.parser import FragmentParser
from network.session import HAS_CURL_CFFI
from network.client import NetworkEngine
from network.controller import CentralizedNetworkController

def run_network_live_test(target_user: str = "durov") -> int:
    """Live Network Integration Probe using curl_cffi and TLS Impersonation."""
    print("=" * 75)
    print("🦅 FALCON // LIVE NETWORK TLS IMPERSONATION PROBE")
    print("=" * 75)

    if not HAS_CURL_CFFI:
        print("❌ FAILED: 'curl_cffi' is NOT installed. Live network probe requires curl_cffi.")
        print("   Install it using: pip install curl_cffi")
        return 1

    print(f"[*] Dispatching live TLS probe to Fragment.com for target: @{target_user} ...")
    net_ctrl = CentralizedNetworkController(initial_delay=1.0)
    net_eng = NetworkEngine(controller=net_ctrl)

    start_t = time.monotonic()
    status_code, content, headers, latency, err_cat = net_eng.fetch(target_user, correlation_id="live_probe")
    net_eng.close()

    elapsed = (time.monotonic() - start_t) * 1000

    print(f"[*] Response Status Code : {status_code}")
    print(f"[*] Network Latency      : {latency:.1f} ms (Total: {elapsed:.1f} ms)")
    print(f"[*] Payload Size         : {len(content):,} bytes")

    if status_code == 200 and content:
        status, conf, price, reason, detail, _ = FragmentParser.parse_html(content, target_user)
        print(f"[*] Live Target Status   : {status.value}")
        print(f"[*] Confidence Score     : {conf:.1f}%")
        print(f"[*] Price / Detail       : {price or detail}")
        print("=" * 75)
        print("🟢 LIVE NETWORK TEST PASSED SUCCESSFULLY")
        print("=" * 75)
        return 0
    else:
        print(f"❌ Live probe failed or intercepted: HTTP {status_code} ({err_cat.value})")
        print("=" * 75)
        return 1