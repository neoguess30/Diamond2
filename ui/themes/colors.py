from __future__ import annotations
from typing import Dict, Any

# ==============================================================================
# FALCON DARK PALETTE (90% Dark/Neutral, 7% Accent, 3% Status)
# ==============================================================================
DARK_BG        = "#080B10"  # Tactical deep background
DARK_PANEL     = "#0D1219"  # Surface panel
DARK_CARD      = "#111821"  # Elevated component
DARK_TABLE     = "#0A0E14"  # Stream table background
DARK_ROW_NORM  = "#0D1219"
DARK_ROW_ALT   = "#101620"
DARK_ROW_HOVER = "#151F2C"
DARK_ROW_SEL   = "#14283C"
DARK_BORDER    = "#1D2935"
DARK_BORDER_HI = "#35D6FF"

DARK_TEXT      = "#E8EEF5"  # Primary crisp text
DARK_SECONDARY = "#8493A5"  # Secondary muted metadata
DARK_MUTED     = "#566579"

DARK_PRIMARY   = "#35D6FF"  # Falcon Cyan
DARK_PURPLE    = "#7C6CFF"  # Intelligence Purple
DARK_EMERALD   = "#35D07F"  # Emerald Green
DARK_ACCENT    = "#35D6FF"

DARK_STAT_AVAILABLE   = "#35D07F"
DARK_STAT_AUCTION     = "#FFB84D"
DARK_STAT_SOLD        = "#7C6CFF"
DARK_STAT_TAKEN       = "#647890"
DARK_STAT_UNAVAILABLE = "#FF5570"
DARK_STAT_UNKNOWN     = "#FFB84D"
DARK_STAT_ERROR       = "#FF5570"

# ==============================================================================
# FALCON LIGHT PALETTE (Non-Blinding Off-White #F3F6F9 with Deep Cyan #079BC2)
# ==============================================================================
LIGHT_BG        = "#F3F6F9"  # Soft background
LIGHT_PANEL     = "#FFFFFF"  # Clean surface
LIGHT_CARD      = "#FFFFFF"  # Clean card
LIGHT_TABLE     = "#FFFFFF"
LIGHT_ROW_NORM  = "#FFFFFF"
LIGHT_ROW_ALT   = "#F6F9FC"
LIGHT_ROW_HOVER = "#EAF2F8"
LIGHT_ROW_SEL   = "#D8ECF8"
LIGHT_BORDER    = "#D8E1E8"
LIGHT_BORDER_HI = "#079BC2"

LIGHT_TEXT      = "#17212B"  # High contrast text
LIGHT_SECONDARY = "#657384"  # Muted secondary text
LIGHT_MUTED     = "#94A3B8"

LIGHT_PRIMARY   = "#079BC2"  # Deep contrast Cyan
LIGHT_PURPLE    = "#6657D9"  # Intelligence Purple
LIGHT_EMERALD   = "#168A55"  # Emerald Green
LIGHT_ACCENT    = "#079BC2"

LIGHT_STAT_AVAILABLE   = "#168A55"
LIGHT_STAT_AUCTION     = "#B87500"
LIGHT_STAT_SOLD        = "#6657D9"
LIGHT_STAT_TAKEN       = "#5A6E82"
LIGHT_STAT_UNAVAILABLE = "#D83A52"
LIGHT_STAT_UNKNOWN     = "#B87500"
LIGHT_STAT_ERROR       = "#D83A52"

class FalconThemeManager:
    """Manages active color palettes and customizable accent slots."""
    def __init__(self, is_dark: bool = True, accent_name: str = "cyan"):
        self.is_dark = is_dark
        self.accent_name = accent_name  # "cyan" | "purple" | "emerald"

    def get_accent_color(self) -> str:
        if self.accent_name == "purple":
            return DARK_PURPLE if self.is_dark else LIGHT_PURPLE
        elif self.accent_name == "emerald":
            return DARK_EMERALD if self.is_dark else LIGHT_EMERALD
        return DARK_PRIMARY if self.is_dark else LIGHT_PRIMARY

    def get_bg_color(self) -> str:
        return DARK_BG if self.is_dark else LIGHT_BG

    def get_panel_color(self) -> str:
        return DARK_PANEL if self.is_dark else LIGHT_PANEL

    def get_card_color(self) -> str:
        return DARK_CARD if self.is_dark else LIGHT_CARD

    def get_border_color(self) -> str:
        return DARK_BORDER if self.is_dark else LIGHT_BORDER

    def get_text_color(self) -> str:
        return DARK_TEXT if self.is_dark else LIGHT_TEXT

    def get_muted_color(self) -> str:
        return DARK_MUTED if self.is_dark else LIGHT_MUTED