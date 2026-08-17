from __future__ import annotations
from typing import Optional
from core.errors.categories import ErrorCategory

class FailureClassifier:
    """Categorizes protocol, transport, and application errors cleanly."""
    
    @classmethod
    def classify_exception(cls, exc: Exception) -> ErrorCategory:
        err_str = str(exc).lower()
        if "timeout" in err_str or "timed out" in err_str:
            return ErrorCategory.TIMEOUT
        elif "ssl" in err_str or "tls" in err_str or "certificate" in err_str or "handshake" in err_str:
            return ErrorCategory.TLS_ERROR
        return ErrorCategory.NETWORK_TRANSIENT

    @classmethod
    def classify_http_status(cls, status_code: int) -> Optional[ErrorCategory]:
        if status_code == 200:
            return None
        elif status_code == 429:
            return ErrorCategory.HTTP_429
        elif 500 <= status_code <= 599:
            return ErrorCategory.HTTP_5XX
        elif 400 <= status_code <= 499:
            return ErrorCategory.HTTP_4XX
        return ErrorCategory.NETWORK_TRANSIENT