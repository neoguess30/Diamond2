from __future__ import annotations
import re
from typing import Optional, Any

RE_USD_PRICE   = re.compile(r'(?:\$|usd|usdt)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:usd|usdt|\$)', re.IGNORECASE)
RE_TON_PRICE   = re.compile(r'(?:💎|ton)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:ton|💎)', re.IGNORECASE)
RE_GEN_PRICE   = re.compile(r'(?:price|bid|minimum bid|current bid)\s*:\s*([\d,]+(?:\.\d+)?)\s*(ton|usd)?', re.IGNORECASE)
RE_OWNER_MATCH = re.compile(r'(?:owned\s+by|owner)\s*:?\s*@?([a-z0-9_]{3,32})', re.IGNORECASE)

class MetadataExtractor:
    """Extracts TON/USD prices and ownership handles from DOM context or text."""
    
    @classmethod
    def detect_price(cls, text: str, soup: Optional[Any] = None, context_node: Optional[Any] = None) -> str:
        if context_node is not None:
            for row in context_node.select(".table-row, .tm-table-row, tr, .tm-list-item, div"):
                row_text = row.get_text(" ", strip=True)
                row_lower = row_text.lower()
                if any(bad in row_lower for bad in ["step", "fee", "tax", "commission", "network", "chars", "character", "ends in"]):
                    continue
                if any(target in row_lower for target in ["minimum bid", "current bid", "buy now", "price", "highest bid", "winning bid", "sold for"]):
                    val_el = row.select_one(".table-cell-value, .tm-value, .value, .tm-cell-value, .icon-ton, [class*='value']")
                    val_text = val_el.get_text(" ", strip=True) if val_el else row_text
                    num_match = re.search(r'([\d,]+(?:\.\d+)?)', val_text)
                    if num_match:
                        clean_num = num_match.group(1).rstrip('.')
                        if clean_num and clean_num != "0":
                            if "$" in val_text or "usd" in row_lower:
                                return f"${clean_num} USD"
                            return f"{clean_num} TON"
            
            for p_el in context_node.select(".tm-section-header-value, .tm-header-price, .tm-price, .tm-value.icon-before, .table-cell-value.tm-value"):
                p_text = p_el.get_text(" ", strip=True)
                if not p_text:
                    continue
                p_lower = p_text.lower()
                if any(bad in p_lower for bad in ["step", "fee", "tax"]):
                    continue
                num_match = re.search(r'([\d,]+(?:\.\d+)?)', p_text)
                if num_match:
                    clean_num = num_match.group(1).rstrip('.')
                    if clean_num:
                        if "$" in p_text or "usd" in p_lower:
                            return f"${clean_num} USD"
                        return f"{clean_num} TON"

        if not text:
            return ""

        labeled_match = re.search(r'(?:current bid|minimum bid|buy now price|buy now|price|highest bid|sold for|sold)\s*[:\-]?\s*(?:💎|\$|ton|usd|usdt)?\s*([\d,]+(?:\.\d+)?)\s*(ton|💎|usd|usdt|\$)?', text, re.IGNORECASE)
        if labeled_match:
            num = labeled_match.group(1)
            curr = (labeled_match.group(2) or "").lower()
            if num:
                if 'usd' in curr or '$' in text[max(0, labeled_match.start() - 5):labeled_match.end() + 5]:
                    return f"${num} USD"
                return f"{num} TON"

        for ton_match in RE_TON_PRICE.finditer(text):
            start_pos = ton_match.start()
            prefix = text[max(0, start_pos - 25):start_pos].lower()
            if any(bad in prefix for bad in ["step", "fee", "tax", "commission"]):
                continue
            num = ton_match.group(1) or ton_match.group(2)
            if num:
                return f"{num} TON"

        usd_match = RE_USD_PRICE.search(text)
        if usd_match:
            num = usd_match.group(1) or usd_match.group(2)
            if num:
                return f"${num} USD"
            
        gen_match = RE_GEN_PRICE.search(text)
        if gen_match:
            num = gen_match.group(1)
            curr = gen_match.group(2)
            if curr:
                return f"{num} {curr.upper()}"
            return f"{num} TON" if "💎" in text or "ton" in text.lower() else f"${num} USD"

        return ""

    @classmethod
    def detect_owner(cls, text: str) -> str:
        owner_match = RE_OWNER_MATCH.search(text)
        if owner_match:
            return f"OWNER: @{owner_match.group(1)}"
        return ""