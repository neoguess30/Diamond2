from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict
from core.errors.categories import ErrorCategory

@dataclass
class NetworkResponse:
    """Encapsulates raw transport response data, headers, and protocol categorization."""
    status_code: int
    content: bytes
    headers: Dict[str, str] = field(default_factory=dict)
    latency_ms: float = 0.0
    error_category: ErrorCategory = ErrorCategory.NETWORK_TRANSIENT
    redirect_count: int = 0
    final_url: str = ""

    @property
    def is_success(self) -> bool:
        return self.status_code == 200 and len(self.content) > 0

    @property
    def is_rate_limited(self) -> bool:
        return self.status_code == 429 or self.error_category == ErrorCategory.HTTP_429

    @property
    def is_circuit_open(self) -> bool:
        return self.error_category == ErrorCategory.CIRCUIT_OPEN