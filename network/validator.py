from __future__ import annotations
import ipaddress
from urllib.parse import urlsplit
from typing import Tuple, Set

# Strict Least Privilege: Exactly 'fragment.com' and 'www.fragment.com' only
ALLOWED_FRAGMENT_HOSTS: Set[str] = {"fragment.com", "www.fragment.com"}

def is_safe_fragment_url(target_url: str) -> Tuple[bool, str]:
    """
    Strict URL validator ensuring target is safe against SSRF, Open Redirects, and Port injections.
    Enforces Strict Principle of Least Privilege:
    1. Must use HTTPS scheme only.
    2. Must not contain userinfo (username:password@host).
    3. Must not have custom non-standard ports (only None or 443).
    4. Must not be an IP address (loopback, private, or public IP).
    5. Host must be strictly in ALLOWED_FRAGMENT_HOSTS ('fragment.com', 'www.fragment.com').
       Arbitrary / unapproved subdomains are forbidden to eliminate attack surface.
    """
    if not target_url or not isinstance(target_url, str):
        return False, "Empty or invalid URL type"
    
    try:
        parsed = urlsplit(target_url.strip())
    except Exception as e:
        return False, f"URL parse error: {e}"

    if parsed.scheme.lower() != "https":
        return False, f"Insecure scheme '{parsed.scheme}'. HTTPS required."

    if parsed.username or parsed.password:
        return False, "Userinfo in URL is strictly forbidden."

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        return False, "Missing hostname in URL."

    # Prevent direct IP addressing (SSRF protection)
    try:
        ip = ipaddress.ip_address(hostname)
        return False, f"Direct IP destination forbidden: {ip}"
    except ValueError:
        pass  # Hostname is a domain string

    if parsed.port is not None and parsed.port != 443:
        return False, f"Non-standard HTTPS port forbidden: {parsed.port}"

    # Strict Least Privilege: Exactly fragment.com or www.fragment.com
    if hostname not in ALLOWED_FRAGMENT_HOSTS:
        return False, f"Unauthorized destination host '{hostname}'. Only exact 'fragment.com' and 'www.fragment.com' are permitted."

    return True, "OK"