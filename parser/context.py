from __future__ import annotations
from typing import Any, Tuple, Optional

STATUS_SELECTORS = [
    ".tm-section-header-status",
    ".table-cell-status",
    ".tm-status-avail",
    ".tm-status-available",
    ".tm-status-unavail",
    ".tm-status-unavailable",
    ".tm-status-taken",
    ".tm-status-auction",
    ".tm-status-sold",
    ".tm-value-avail",
    ".tm-value-unavail",
    ".item-status",
    ".status-badge",
    ".tm-status",
    "[class*='status']"
]

TARGET_CONTAINER_SELECTORS = [
    ".tm-section",
    ".tm-header-section",
    ".tm-main-content",
    "main",
    "[data-username]",
    ".tm-list-item"
]

class ContextExtractor:
    """
    P0 Strict Target Context Extractor:
    Isolates target container to eliminate false-positives from footer/promo/sidebar.
    Strictly returns is_verified=False if no legitimate target container exists.
    """
    
    @staticmethod
    def extract_context(soup: Any) -> Tuple[bool, Any, str, str, str]:
        """
        Returns:
            (is_verified, context_node, full_text, status_element_str, btn_texts)
        """
        target_context = None
        for sel in TARGET_CONTAINER_SELECTORS:
            target_context = soup.select_one(sel)
            if target_context:
                break

        # P0 Gate: If no valid target container is identified, do NOT fall back to full page soup
        if not target_context:
            return False, None, "", "", ""

        context_node = target_context
        full_text = context_node.get_text(" ", strip=True)

        status_elements = []
        for sel in STATUS_SELECTORS:
            for el in context_node.select(sel):
                st_text = el.get_text(" ", strip=True)
                if st_text:
                    status_elements.append(st_text)

        status_element_str = " ".join(status_elements).lower()
        btn_texts = " ".join([btn.get_text(" ", strip=True).lower() for btn in context_node.select("button, a.btn, a.tm-btn, .btn-primary")])

        return True, context_node, full_text, status_element_str, btn_texts