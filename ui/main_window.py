from __future__ import annotations
import sys
from datetime import datetime, timezone
from collections import deque
from typing import Dict, List, Any, Optional

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QSplitter, QTextEdit, QTableView, QHeaderView,
        QFileDialog, QLineEdit, QScrollArea, QAbstractItemView, QMenu, QMessageBox
    )
    from PyQt6.QtCore import Qt, QTimer, QUrl, QModelIndex
    from PyQt6.QtGui import QFont, QDesktopServices, QAction, QKeySequence, QShortcut
except ImportError:
    pass

from core.state.enums import EngineState
from core.config import UI_LOG_THROTTLE_SEC
from core.metrics import METRICS
from core.utils import get_process_memory_mb_str, get_system_ram_percent
from core.logger import logger
from ui.models.table_model import LiveScannerTableModel
from ui.models.filter_proxy import StatusFilterProxyModel
from ui.widgets.stat_card import StatCard
from ui.widgets.inspector import TargetInspectorPanel
from ui.widgets.radar_hud import FalconRadarWidget
from ui.widgets.telemetry_dialog import CacheTelemetryDialog
from ui.widgets.command_palette import CommandPaletteDialog
from ui.views.patterns_view import PatternsView
from ui.views.live_scanner_view import LiveScannerView
from ui.views.terminal_view import TerminalView
from ui.themes.colors import (
    DARK_BG, LIGHT_BG,
    DARK_PANEL, LIGHT_PANEL,
    DARK_CARD, LIGHT_CARD,
    DARK_BORDER, LIGHT_BORDER,
    DARK_TEXT, LIGHT_TEXT,
    DARK_PRIMARY, LIGHT_PRIMARY,
    DARK_PURPLE, LIGHT_PURPLE,
    DARK_MUTED, LIGHT_MUTED,
    DARK_STAT_AVAILABLE, LIGHT_STAT_AVAILABLE,
    DARK_STAT_AUCTION, LIGHT_STAT_AUCTION,
    DARK_STAT_UNAVAILABLE, LIGHT_STAT_UNAVAILABLE,
    DARK_STAT_SOLD, LIGHT_STAT_SOLD,
    DARK_STAT_TAKEN, LIGHT_STAT_TAKEN,
    DARK_STAT_UNKNOWN, LIGHT_STAT_UNKNOWN,
    DARK_STAT_ERROR, LIGHT_STAT_ERROR
)

class MainWindow(QMainWindow):
    """
    FALCON COMMAND CENTER // TACTICAL INTELLIGENCE ENGINE
    Featuring instant mission-critical header telemetry, unified bottom hardware pulse,
    hero live scanner stream, and seamless F11 focus mode.
    """
    def __init__(self, controller: Any):
        super().__init__()
        self.setWindowTitle("🦅 FALCON COMMAND CENTER // INTELLIGENCE ENGINE")
        self.resize(1620, 940)
        self.setMinimumSize(1280, 720)
        
        self.controller = controller
        
        self.stats = {
            "TOTAL": 0,
            "UNAVAILABLE": 0,
            "AVAILABLE": 0,
            "AUCTION": 0,
            "SOLD": 0,
            "TAKEN": 0,
            "UNKNOWN": 0,
            "ERRORS": 0
        }
        self.is_dark = True
        self.focus_active = False
        self.active_accent = "cyan"  # "cyan" | "purple" | "emerald"
        self.log_buffer = deque(maxlen=200)
        
        self.table_model = LiveScannerTableModel(max_rows=1000, is_dark=self.is_dark, parent=self)
        self.proxy_model = StatusFilterProxyModel(parent=self)
        self.proxy_model.setSourceModel(self.table_model)
        
        self.init_ui()
        self.setup_keyboard_shortcuts()
        
        # Connect Controller Signals
        self.controller.writer.sig_batch_processed.connect(self.handle_scan_batch)
        self.controller.writer.sig_log.connect(self.queue_ui_log)
        self.controller.worker.sig_log.connect(self.queue_ui_log)
        self.controller.supervisor.sig_telemetry.connect(self.handle_telemetry)
        self.controller.supervisor.sig_log.connect(self.queue_ui_log)
        
        self.controller.register_writer_replacement_callback(self._on_writer_replaced)
        self.controller.register_worker_replacement_callback(self._on_worker_replaced)
        
        # Timers
        self.stat_debounce_timer = QTimer(self)
        self.stat_debounce_timer.timeout.connect(self.flush_debounced_stats)
        self.stat_debounce_timer.start(100)
        
        self.log_flush_timer = QTimer(self)
        self.log_flush_timer.timeout.connect(self.flush_ui_logs)
        self.log_flush_timer.start(int(UI_LOG_THROTTLE_SEC * 1000))
        
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

        self.update_control_states(state=EngineState.STOPPED)

    def setup_keyboard_shortcuts(self):
        self.shortcut_palette = QShortcut(QKeySequence("Ctrl+K"), self)
        self.shortcut_palette.activated.connect(self.open_command_palette)
        
        self.shortcut_f11 = QShortcut(QKeySequence("F11"), self)
        self.shortcut_f11.activated.connect(self.toggle_focus_shortcut)
        self.shortcut_focus = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self.shortcut_focus.activated.connect(self.toggle_focus_shortcut)

    def open_command_palette(self):
        commands = [
            ("Start Scanner Engine", "ENGINE", self.start_scanner),
            ("Pause Scanner Engine", "ENGINE", self.stop_scanner),
            ("Open Falcon Diagnostics HUD", "SYSTEM", self.open_cache_modal),
            ("Toggle Focus Mode (F11)", "VIEW", lambda: self.toggle_focus_mode(not self.focus_active)),
            ("Switch Theme (Dark / Light)", "VIEW", self.toggle_theme),
            ("Set Accent: Falcon Cyan", "THEME", lambda: self.set_accent("cyan")),
            ("Set Accent: Intelligence Purple", "THEME", lambda: self.set_accent("purple")),
            ("Set Accent: Emerald Green", "THEME", lambda: self.set_accent("emerald")),
            ("Export Console Logs to File", "LOGS", self.terminal_view.export_console_log),
            ("Clear Operator Console", "LOGS", self.terminal_view.clear_terminal),
            ("Trigger WAL Checkpoint", "DATABASE", self.open_cache_modal),
            ("Execute Graceful Shutdown", "POWER", self.close)
        ]
        dlg = CommandPaletteDialog(commands=commands, parent=self)
        dlg.exec()

    def set_accent(self, accent_name: str):
        self.active_accent = accent_name
        self.update_all_components_theme()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 8, 10, 8)
        
        main_layout.addLayout(self.create_top_bar())
        main_layout.addLayout(self.create_stats_cards())
        
        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.h_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 1. Patterns Panel (Compact Left)
        self.patterns_view = PatternsView(parent_gui=self)
        self.h_splitter.addWidget(self.patterns_view)
        
        # 2. Live Scanner (Hero Center - Takes Lion's share)
        self.scanner_view = LiveScannerView(parent_gui=self)
        self.h_splitter.addWidget(self.scanner_view)
        
        # 3. Falcon Vision (Target Intelligence Right)
        self.right_panel = TargetInspectorPanel(parent_gui=self)
        self.h_splitter.addWidget(self.right_panel)
        
        self.h_splitter.setSizes([300, 940, 380])
        self.v_splitter.addWidget(self.h_splitter)
        
        # 4. Operator Console (Collapsible Bottom)
        self.terminal_view = TerminalView(parent_gui=self)
        self.v_splitter.addWidget(self.terminal_view)
        self.v_splitter.setSizes([730, 130])
        
        main_layout.addWidget(self.v_splitter, 1)
        main_layout.addLayout(self.create_status_bar())

        self.apply_dark_theme()

    def create_top_bar(self) -> QHBoxLayout:
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(12)
        
        # Tactical Falcon Brand Header
        brand_v = QVBoxLayout()
        brand_v.setSpacing(0)
        
        brand_top = QHBoxLayout()
        lbl_mark = QLabel("🦅")
        lbl_mark.setFont(QFont("Segoe UI", 12))
        self.lbl_falcon = QLabel("FALCON COMMAND CENTER")
        self.lbl_falcon.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.lbl_falcon.setStyleSheet(f"color: {DARK_PRIMARY}; letter-spacing: 2px;")
        brand_top.addWidget(lbl_mark)
        brand_top.addWidget(self.lbl_falcon)
        brand_top.addStretch()
        
        self.lbl_sub = QLabel("INTELLIGENCE ENGINE // V32.0-SOVEREIGN")
        self.lbl_sub.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        self.lbl_sub.setStyleSheet(f"color: {DARK_MUTED}; letter-spacing: 1px;")
        
        brand_v.addLayout(brand_top)
        brand_v.addWidget(self.lbl_sub)
        top_bar.addLayout(brand_v)
        
        # Live Activity Pulse Banner
        self.lbl_mission_status = QLabel("○ STOPPED   0.0/s   HEALTHY   UPTIME 00:00:00")
        self.lbl_mission_status.setFont(QFont("JetBrains Mono", 10, QFont.Weight.Bold))
        self.lbl_mission_status.setStyleSheet(f"color: {DARK_MUTED}; background-color: {DARK_CARD}; padding: 6px 12px; border-radius: 4px; border: 1px solid {DARK_BORDER};")
        top_bar.addWidget(self.lbl_mission_status)
        
        top_bar.addStretch()
        
        # Falcon Radar Widget HUD
        self.radar_widget = FalconRadarWidget(self)
        top_bar.addWidget(self.radar_widget)
        
        # Control Action Buttons
        self.btn_state = QPushButton("START")
        self.btn_state.setFixedSize(110, 34)
        self.btn_state.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.btn_state.clicked.connect(self.toggle_engine_state)
        top_bar.addWidget(self.btn_state)
        
        btn_palette = QPushButton("CMD [Ctrl+K]")
        btn_palette.setFixedSize(105, 34)
        btn_palette.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        btn_palette.clicked.connect(self.open_command_palette)
        top_bar.addWidget(btn_palette)
        
        btn_diagnostics = QPushButton("⚡ DIAGNOSTICS")
        btn_diagnostics.setFixedSize(120, 34)
        btn_diagnostics.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        btn_diagnostics.clicked.connect(self.open_cache_modal)
        top_bar.addWidget(btn_diagnostics)
        
        self.btn_focus = QPushButton("FOCUS [F11]")
        self.btn_focus.setCheckable(True)
        self.btn_focus.setFixedSize(95, 34)
        self.btn_focus.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.btn_focus.clicked.connect(self.toggle_focus_mode)
        top_bar.addWidget(self.btn_focus)
        
        self.btn_theme = QPushButton("DARK")
        self.btn_theme.setFixedSize(70, 34)
        self.btn_theme.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self.btn_theme.clicked.connect(self.toggle_theme)
        top_bar.addWidget(self.btn_theme)
        
        return top_bar

    def update_clock(self):
        pass

    def toggle_engine_state(self):
        if self.controller.state == EngineState.RUNNING:
            self.stop_scanner()
        else:
            self.start_scanner()

    def update_control_states(self, state: EngineState):
        is_dark = self.is_dark
        primary = DARK_PRIMARY if is_dark else LIGHT_PRIMARY
        border = DARK_BORDER if is_dark else LIGHT_BORDER
        card_bg = DARK_CARD if is_dark else LIGHT_CARD
        
        if state == EngineState.RUNNING:
            self.btn_state.setText("● RUNNING")
            self.btn_state.setStyleSheet(f"background-color: {DARK_STAT_UNAVAILABLE if is_dark else LIGHT_STAT_UNAVAILABLE}; color: white; font-weight: bold; border-radius: 3px;")
        elif state in (EngineState.PAUSING, EngineState.DRAINING):
            self.btn_state.setText("◌ DRAINING...")
            self.btn_state.setStyleSheet(f"background-color: {card_bg}; color: {DARK_STAT_AUCTION if is_dark else LIGHT_STAT_AUCTION}; border: 1px solid {border}; border-radius: 3px;")
        elif state == EngineState.PAUSED:
            self.btn_state.setText("● PAUSED")
            self.btn_state.setStyleSheet(f"background-color: {primary}; color: {'#080B10' if is_dark else '#FFFFFF'}; font-weight: bold; border-radius: 3px;")
        elif state == EngineState.RECOVERING:
            self.btn_state.setText("↻ RECOVERING")
            self.btn_state.setStyleSheet(f"background-color: {DARK_PURPLE if is_dark else LIGHT_PURPLE}; color: white; font-weight: bold; border-radius: 3px;")
        else:
            self.btn_state.setText("START")
            self.btn_state.setStyleSheet(f"background-color: {primary}; color: {'#080B10' if is_dark else '#FFFFFF'}; font-weight: bold; border-radius: 3px;")

    def create_stats_cards(self) -> QHBoxLayout:
        grid = QHBoxLayout()
        grid.setSpacing(10)
        
        # Primary Metric Cards (Elevated)
        self.c_total       = StatCard("TOTAL", "0", DARK_MUTED if self.is_dark else LIGHT_MUTED, is_primary=True, parent_gui=self)
        self.c_available   = StatCard("AVAILABLE", "0", DARK_STAT_AVAILABLE if self.is_dark else LIGHT_STAT_AVAILABLE, is_primary=True, parent_gui=self)
        self.c_errors      = StatCard("ERRORS", "0", DARK_STAT_ERROR if self.is_dark else LIGHT_STAT_ERROR, is_primary=True, parent_gui=self)
        
        # Secondary Metric Cards
        self.c_auction     = StatCard("AUCTION", "0", DARK_STAT_AUCTION if self.is_dark else LIGHT_STAT_AUCTION, is_primary=False, parent_gui=self)
        self.c_sold        = StatCard("SOLD", "0", DARK_STAT_SOLD if self.is_dark else LIGHT_STAT_SOLD, is_primary=False, parent_gui=self)
        self.c_taken       = StatCard("TAKEN", "0", DARK_STAT_TAKEN if self.is_dark else LIGHT_STAT_TAKEN, is_primary=False, parent_gui=self)
        self.c_unavailable = StatCard("UNAVAILABLE", "0", DARK_STAT_UNAVAILABLE if self.is_dark else LIGHT_STAT_UNAVAILABLE, is_primary=False, parent_gui=self)
        self.c_unknown     = StatCard("UNKNOWN", "0", DARK_STAT_UNKNOWN if self.is_dark else LIGHT_STAT_UNKNOWN, is_primary=False, parent_gui=self)
        
        self.c_total.mousePressEvent       = lambda e: self.filter_stream("ALL")
        self.c_available.mousePressEvent   = lambda e: self.filter_stream("AVAILABLE")
        self.c_errors.mousePressEvent      = lambda e: self.filter_stream("ERROR")
        self.c_auction.mousePressEvent     = lambda e: self.filter_stream("AUCTION")
        self.c_sold.mousePressEvent        = lambda e: self.filter_stream("SOLD")
        self.c_taken.mousePressEvent       = lambda e: self.filter_stream("TAKEN")
        self.c_unavailable.mousePressEvent = lambda e: self.filter_stream("UNAVAILABLE")
        self.c_unknown.mousePressEvent     = lambda e: self.filter_stream("UNKNOWN")
        
        grid.addWidget(self.c_total, 2)
        grid.addWidget(self.c_available, 2)
        grid.addWidget(self.c_auction, 1)
        grid.addWidget(self.c_sold, 1)
        grid.addWidget(self.c_taken, 1)
        grid.addWidget(self.c_unavailable, 1)
        grid.addWidget(self.c_unknown, 1)
        grid.addWidget(self.c_errors, 1)
        return grid

    def create_status_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        self.lbl_status_bar = QLabel("RAM N/A │ QUEUE 0 │ SCANNER ✓ │ WRITER ✓ │ DB ✓ │ NETWORK ✓ │ ● HEALTHY")
        self.lbl_status_bar.setFont(QFont("JetBrains Mono", 9))
        bar.addWidget(self.lbl_status_bar)
        bar.addStretch()
        return bar

    def handle_scan_batch(self, batch: List[dict]):
        if not batch:
            return

        self.table_model.add_records_batch(batch)

        for res in batch:
            status_name = res["status"]
            pat_id = res.get("pat_id", "")
            
            self.stats["TOTAL"] += 1
            if status_name in self.stats:
                self.stats[status_name] += 1
            else:
                self.stats["UNKNOWN"] += 1
                
            if status_name == "ERROR":
                self.stats["ERRORS"] += 1
            
            if pat_id in self.patterns_view.pattern_cards:
                self.patterns_view.pattern_cards[pat_id].update_progress(is_avail=(status_name == "AVAILABLE"))

        scrollbar = self.scanner_view.table.verticalScrollBar()
        if scrollbar.value() >= (scrollbar.maximum() - 4):
            self.scanner_view.table.scrollToBottom()

    def flush_debounced_stats(self):
        deltas = METRICS.get_delta_60s()
        d_tot = f"▲ +{deltas.get('TOTAL', 0)}/m" if deltas.get('TOTAL', 0) > 0 else ""
        d_avl = f"▲ +{deltas.get('AVAILABLE', 0)}/m" if deltas.get('AVAILABLE', 0) > 0 else ""
        
        self.c_total.set_value_debounced(f"{self.stats['TOTAL']:,}", delta_str=d_tot)
        self.c_available.set_value_debounced(f"{self.stats['AVAILABLE']:,}", delta_str=d_avl)
        self.c_auction.set_value_debounced(f"{self.stats['AUCTION']:,}")
        self.c_sold.set_value_debounced(f"{self.stats['SOLD']:,}")
        self.c_taken.set_value_debounced(f"{self.stats['TAKEN']:,}")
        self.c_unavailable.set_value_debounced(f"{self.stats['UNAVAILABLE']:,}")
        self.c_unknown.set_value_debounced(f"{self.stats['UNKNOWN']:,}")
        self.c_errors.set_value_debounced(f"{self.stats['ERRORS']:,}")

    def queue_ui_log(self, text: str):
        self.log_buffer.append(text)

    def flush_ui_logs(self):
        if self.log_buffer:
            lines = []
            while self.log_buffer:
                msg = self.log_buffer.popleft()
                flt = self.terminal_view.active_log_filter
                if flt == "ERROR" and "❌" not in msg and "ERROR" not in msg and "🚨" not in msg:
                    continue
                elif flt == "NETWORK" and "Network" not in msg and "HTTP" not in msg and "429" not in msg and "TLS" not in msg:
                    continue
                elif flt == "DB" and "Database" not in msg and "DB" not in msg and "WAL" not in msg and "SQLite" not in msg:
                    continue
                elif flt == "SYSTEM" and "System" not in msg and "Engine" not in msg and "Supervisor" not in msg and "Watchdog" not in msg:
                    continue
                lines.append(msg)
            if lines:
                self.terminal_view.append_log_batch(lines)

    def handle_telemetry(self, tele: dict):
        uptime = tele.get("uptime", "00:00:00")
        delay = tele.get("delay", "1.20s")
        q_depth = tele.get("queue_depth", 0)
        health = tele.get("health_state", "HEALTHY")
        p95 = tele.get("p95_ms", 0.0)
        eff_rate = tele.get("effective_jobs_per_sec", 0.0)
        ram_str = tele.get("ram_str", "N/A")
        is_running = (self.controller.state == EngineState.RUNNING)
        
        self.radar_widget.set_radar_telemetry(eff_rate, health_state=health, engine_running=is_running)
        
        # State Indicators
        state_str = "● RUNNING" if is_running else "○ IDLE"
        if self.controller.state in (EngineState.PAUSING, EngineState.DRAINING):
            state_str = "◌ DRAINING"
        elif self.controller.state == EngineState.PAUSED:
            state_str = "● PAUSED"
        elif self.controller.state == EngineState.RECOVERING:
            state_str = "↻ RECOVERING"

        # 1. Update Top Banner Instant Telemetry
        self.lbl_mission_status.setText(f"{state_str}    {eff_rate:.1f} jobs/s    ● {health}    UPTIME {uptime}")
        status_color = DARK_STAT_AVAILABLE if (is_running and health == "HEALTHY") else DARK_STAT_AUCTION if (health in ("DEGRADED", "STALLED")) else DARK_STAT_ERROR if health == "FAILED" else DARK_MUTED
        self.lbl_mission_status.setStyleSheet(f"color: {status_color}; background-color: {DARK_CARD if self.is_dark else LIGHT_CARD}; padding: 6px 14px; border-radius: 4px; border: 1px solid {DARK_BORDER if self.is_dark else LIGHT_BORDER};")
        
        # 2. Update Unified Bottom Status Bar
        writer_ok = "✓" if not tele.get("db_degraded") else "✗"
        db_ok = "✓" if tele.get("db_health_state") == "HEALTHY" else "✗"
        net_ok = "✓" if tele.get("circuit_state") == "CLOSED" else "✗"
        scan_ok = "✓" if self.controller.worker.isRunning() else "✗"
        
        self.lbl_status_bar.setText(f"RAM {ram_str} │ QUEUE {q_depth:,} │ SCANNER {scan_ok} │ WRITER {writer_ok} │ DB {db_ok} │ NETWORK {net_ok} │ ● {health}")

    def filter_stream(self, status: str):
        self.proxy_model.set_filter_status(status)

    def open_cache_modal(self):
        dlg = CacheTelemetryDialog(is_dark=self.is_dark, parent=self)
        dlg.exec()

    def start_scanner(self):
        started = self.controller.start_engine()
        if started:
            self.update_control_states(state=EngineState.RUNNING)
            self.queue_ui_log(f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}  ✓ Engine started by operator (State: RUNNING).")

    def stop_scanner(self):
        self.controller.pause_engine()
        self.update_control_states(state=EngineState.PAUSED)
        self.queue_ui_log(f"{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}  ⚠ Engine paused (State: PAUSED).")

    def toggle_focus_shortcut(self):
        self.btn_focus.setChecked(not self.btn_focus.isChecked())
        self.toggle_focus_mode(self.btn_focus.isChecked())

    def toggle_focus_mode(self, checked: bool):
        self.focus_active = checked
        if checked:
            self.patterns_view.hide()
            self.terminal_view.hide()
            self.right_panel.hide()
            self.scanner_view.table.verticalHeader().setDefaultSectionSize(34)
            self.btn_focus.setText("EXIT [F11]")
        else:
            self.patterns_view.show()
            self.terminal_view.show()
            self.right_panel.show()
            self.scanner_view.table.verticalHeader().setDefaultSectionSize(36)
            self.btn_focus.setText("FOCUS [F11]")

    def toggle_theme(self):
        self.is_dark = not self.is_dark
        self.table_model.is_dark = self.is_dark
        if self.is_dark:
            self.apply_dark_theme()
            self.btn_theme.setText("DARK")
        else:
            self.apply_light_theme()
            self.btn_theme.setText("LIGHT")

    def apply_dark_theme(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {DARK_BG}; }}
            QLabel {{ color: {DARK_TEXT}; }}
            QPushButton {{ background-color: {DARK_CARD}; color: {DARK_TEXT}; border: 1px solid {DARK_BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ border-color: {DARK_PRIMARY}; }}
            QTextEdit {{ background-color: #06090D; color: {DARK_STAT_AVAILABLE}; font-family: 'JetBrains Mono'; font-size: 10px; border: 1px solid {DARK_BORDER}; }}
        """)
        self.update_all_components_theme()

    def apply_light_theme(self):
        self.setStyleSheet(f"""
            QMainWindow {{ background-color: {LIGHT_BG}; }}
            QLabel {{ color: {LIGHT_TEXT}; }}
            QPushButton {{ background-color: {LIGHT_CARD}; color: {LIGHT_TEXT}; border: 1px solid {LIGHT_BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ border-color: {LIGHT_PRIMARY}; }}
            QTextEdit {{ background-color: #FFFFFF; color: {LIGHT_STAT_AVAILABLE}; font-family: 'JetBrains Mono'; font-size: 10px; border: 1px solid {LIGHT_BORDER}; }}
        """)
        self.update_all_components_theme()

    def update_all_components_theme(self):
        self.scanner_view.apply_table_style()
        self.update_control_states(state=self.controller.state)
        for card in [self.c_total, self.c_available, self.c_errors, self.c_auction, self.c_sold, self.c_taken, self.c_unavailable, self.c_unknown]:
            card.update_style()
        if hasattr(self, 'right_panel'):
            self.right_panel.update_style()
        if hasattr(self, 'patterns_view'):
            self.patterns_view.update_theme()

    def _on_writer_replaced(self, new_writer: Any):
        try:
            new_writer.sig_batch_processed.connect(self.handle_scan_batch)
            new_writer.sig_log.connect(self.queue_ui_log)
            logger.info("MainWindow: Reconnected UI slots to replacement StorageWriterWorker signals.")
        except Exception as e:
            logger.error(f"MainWindow: Error reconnecting replacement writer signals: {e}")

    def _on_worker_replaced(self, new_worker: Any):
        try:
            new_worker.sig_log.connect(self.queue_ui_log)
            logger.info("MainWindow: Reconnected UI slots to replacement ScannerWorker signals.")
        except Exception as e:
            logger.error(f"MainWindow: Error reconnecting replacement worker signals: {e}")

    def closeEvent(self, event):
        try:
            self.stat_debounce_timer.stop()
            self.log_flush_timer.stop()
            self.clock_timer.stop()
            if hasattr(self, 'radar_widget') and hasattr(self.radar_widget, 'timer'):
                self.radar_widget.timer.stop()
            self.controller.shutdown_engine()
            event.accept()
        except Exception as e:
            logger.error(f"Exception during closeEvent sequence: {e}")
            event.accept()