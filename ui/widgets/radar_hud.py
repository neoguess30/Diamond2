from __future__ import annotations
import math

try:
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtCore import Qt, QTimer, QPoint
    from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont
except ImportError:
    class QWidget:
        def __init__(self, parent=None): pass
        def setFixedSize(self, w, h): pass
        def width(self): return 145
        def height(self): return 72
        def update(self): pass
    class QTimer:
        def __init__(self, p=None): pass
        def start(self, ms): pass
        def stop(self): pass
        class timeout:
            @staticmethod
            def connect(s): pass
    class QPoint:
        def __init__(self, x=0, y=0): pass
    class QPainter:
        class RenderHint:
            Antialiasing = 1
        def __init__(self, *args): pass
        def setRenderHint(self, *args): pass
        def setPen(self, *args): pass
        def setBrush(self, *args): pass
        def drawRoundedRect(self, *args): pass
        def drawEllipse(self, *args): pass
        def drawLine(self, *args): pass
        def drawText(self, *args): pass
        def setFont(self, *args): pass
    class QPen:
        def __init__(self, *args, **kwargs): pass
    class QBrush:
        def __init__(self, *args, **kwargs): pass
    class QColor:
        def __init__(self, *args): pass
    class QFont:
        class Weight:
            Bold = 700
        def __init__(self, *args, **kwargs): pass
    class Qt:
        class PenStyle:
            DotLine = 1
            NoPen = 0
        class BrushStyle:
            NoBrush = 0

from ui.themes.colors import (
    DARK_CARD, DARK_BORDER, DARK_BORDER_HI,
    DARK_PRIMARY, DARK_STAT_AVAILABLE, DARK_STAT_AUCTION,
    DARK_TEXT, DARK_MUTED
)

class FalconRadarWidget(QWidget):
    """
    Falcon Radar HUD Component:
    Renders tactical radar sweep, active engine pulse, throughput telemetry, and signal reliability.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(145, 72)
        self.sweep_angle = 0.0
        self.throughput_str = "0.0/s"
        self.jobs_per_sec = 0.0
        self.signal_strength = 94
        self.radar_state = "IDLE"  # IDLE | SCANNING | DEGRADED

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_sweep)
        self.timer.start(50)

    def update_sweep(self):
        if self.radar_state == "SCANNING":
            self.sweep_angle = (self.sweep_angle + 7.5) % 360.0
        else:
            self.sweep_angle = (self.sweep_angle + 1.5) % 360.0
        self.update()

    def set_radar_telemetry(self, jobs_per_sec: float, health_state: str = "HEALTHY", engine_running: bool = False):
        self.jobs_per_sec = jobs_per_sec
        self.throughput_str = f"{jobs_per_sec:.1f}/s"
        
        if not engine_running:
            self.radar_state = "IDLE"
            self.signal_strength = 80
        elif health_state in ("DEGRADED", "STALLED"):
            self.radar_state = "DEGRADED"
            self.signal_strength = 65
        else:
            self.radar_state = "SCANNING"
            self.signal_strength = min(99, max(75, int(jobs_per_sec * 2.0) + 78))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw tactical container
        painter.setPen(QPen(QColor(DARK_BORDER), 1))
        painter.setBrush(QBrush(QColor(DARK_CARD)))
        painter.drawRoundedRect(0, 0, self.width() - 1, self.height() - 1, 4, 4)
        
        center_x = 36
        center_y = 36
        radius = 24
        
        # Grid range rings
        ring_color = DARK_PRIMARY if self.radar_state == "SCANNING" else DARK_STAT_AUCTION if self.radar_state == "DEGRADED" else DARK_BORDER_HI
        painter.setPen(QPen(QColor(ring_color), 1, Qt.PenStyle.DotLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(center_x, center_y), radius, radius)
        painter.drawEllipse(QPoint(center_x, center_y), int(radius * 0.5), int(radius * 0.5))
        
        # Radar sweep beam
        if self.radar_state == "SCANNING":
            rad = math.radians(self.sweep_angle)
            end_x = center_x + int(radius * math.cos(rad))
            end_y = center_y + int(radius * math.sin(rad))
            painter.setPen(QPen(QColor(DARK_PRIMARY), 2))
            painter.drawLine(center_x, center_y, end_x, end_y)

        # Center emitter dot
        blip_color = DARK_STAT_AVAILABLE if self.radar_state == "SCANNING" else DARK_STAT_AUCTION if self.radar_state == "DEGRADED" else DARK_MUTED
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(blip_color)))
        painter.drawEllipse(QPoint(center_x, center_y), 3, 3)
        
        # Telemetry Labels
        painter.setPen(QPen(QColor(DARK_PRIMARY)))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(72, 20, "FALCON RADAR")
        
        painter.setPen(QPen(QColor(DARK_TEXT)))
        painter.setFont(QFont("JetBrains Mono", 9, QFont.Weight.Bold))
        painter.drawText(72, 38, self.throughput_str)
        
        painter.setPen(QPen(QColor(DARK_MUTED)))
        painter.setFont(QFont("Segoe UI", 7))
        state_symbol = "◉ ))))" if self.radar_state == "SCANNING" else "⚠ !" if self.radar_state == "DEGRADED" else "○ IDLE"
        painter.drawText(72, 54, f"{state_symbol} {self.signal_strength}%")