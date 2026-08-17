from __future__ import annotations
from core.state.enums import VerificationMode, FragmentStatus

class ScannerPolicy:
    """Encapsulates execution policies for the scanning engine."""
    
    @staticmethod
    def should_verify_smart(mode: VerificationMode, status: FragmentStatus) -> bool:
        if mode == VerificationMode.ALWAYS:
            return True
        elif mode == VerificationMode.SMART and status == FragmentStatus.AVAILABLE:
            return True
        return False