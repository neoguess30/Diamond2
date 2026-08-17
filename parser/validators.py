from __future__ import annotations
import re
from typing import Tuple

class TargetValidator:
    """Validates Telegram and Fragment username rules and constraints."""
    
    # Telegram rules: 4 to 32 characters, letters, numbers, underscores (Fragment allows 4+)
    USERNAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]{3,31}$')

    @classmethod
    def validate_username(cls, username: str) -> Tuple[bool, str]:
        if not username or not isinstance(username, str):
            return False, "Username cannot be empty"

        clean = username.strip().replace("@", "")
        
        if len(clean) < 4:
            return False, f"Username '@{clean}' is too short (Minimum 4 characters)"
        
        if len(clean) > 32:
            return False, f"Username '@{clean}' is too long (Maximum 32 characters)"

        if not cls.USERNAME_PATTERN.match(clean):
            if clean[0].isdigit() or clean[0] == '_':
                return False, f"Username '@{clean}' must start with a letter"
            return False, f"Username '@{clean}' contains invalid characters"

        return True, clean.lower()