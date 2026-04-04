"""
stm32_lab_gui.py - STM32 Remote Electronics Lab v6.0
======================================================
Major v6.0 upgrade: 5 new modules + 14 bug fixes on top of v5.0.

New tabs (v6.0):
  Uncertainty Quantification (#7), SCPI/LXI Server (#11),
  Power Profile Analyser (#12), Production Test Mode (#13),
  Math / Differential Channels (#14)

New infrastructure (v6.0):
  * Dual vertical cursors Delta T / Delta V on DSO plot (Item D)
  * SVG waveform export via pyqtgraph.exporters.SVGExporter (Item F)
  * Eye diagram overlay toggle (Item E)
  * Click-to-annotate text labels on DSO plot (Item C)
  * LaTeX uncertainty snippet export
  * SCPI TCP server on port 5025 (stdlib only, no extras)
  * Power V^2/R, energy, sleep/wake annotated timeline
  * Production test PASS/FAIL + SQLite/CSV logging
  * Math channels with sandboxed eval (CH1 arithmetic, integral, d/dt)

Requirements:
    pip install PyQt5 pyserial pyqtgraph numpy websockets
    Optional extras: scipy scikit-learn pandas
"""

import sys
import os
import csv
import asyncio
import threading
import datetime
import logging
from collections import deque
from pathlib import Path
from typing import Optional, List

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters

import serial
import serial.tools.list_ports

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QSlider, QTextEdit, QFrame, QSizePolicy,
    QMessageBox, QGroupBox, QFileDialog, QCheckBox,
    QLineEdit, QSplitter, QProgressBar, QStatusBar,
    QAction, QMenu, QShortcut, QDialog,
    QListWidget, QListWidgetItem, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor, QPalette, QKeySequence


# -- Core modules --------------------------------------------------------------
from themes   import T, THEMES, set_theme, Theme
from styles   import (build_stylesheet, _mono_font, _ui_font,
                      SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG,
                      SZ_STAT, SZ_SETPT, SZ_BIG)
from widgets  import ThemeLabel, ThemeCard, _HeaderStrip, make_header
from data_engine    import (CommandBuilder, DataParser,
                             DataLogger, AnalyticsEngine, ParsedMessage)
from serial_manager import SerialManager
from mqtt_bridge    import MqttBridge
from settings_manager import SettingsManager
from plugin_manager   import PluginManager

# -- Feature tabs --------------------------------------------------------------
from tab_multimeter  import MultimeterTab
from tab_funcgen     import FunctionGenTab
from tab_voltreg     import VoltageRegTab
from tab_cloud      import CloudTab
from tab_connection  import ConnectionTab
from tab_bode        import BodePlotTab
from tab_trigger     import TriggerTab
from tab_dsp         import DSPPipelineTab
from tab_protocol    import ProtocolDecoderTab
from tab_playback    import PlaybackTab
from tab_repl        import REPLTab
from tab_nlcmd       import NLCommandTab
from tab_wavedb      import WaveformDBTab
from tab_anomaly     import AnomalyDetectorTab
from tab_calibration import CalibrationWizard, load_calibration
from tab_journal      import JournalTab
from tab_pid         import PidTunerTab
# v6.0 new tabs
from tab_uncertainty  import UncertaintyTab
from tab_scpi         import SCPITab
from tab_power        import PowerProfileTab
from tab_prodtest     import ProdTestTab
from tab_mathchan     import MathChannelsTab

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("stm32lab")


# -- Settings Dialog Class ------------------------------------------------------

class SettingsDialog(QDialog):
    """Modern UI for system-wide configuration."""
    def __init__(self, settings_manager: SettingsManager, current_theme: str):
        super().__init__()
        self.setWindowTitle("Global System Settings")
        self.setFixedWidth(420)
        self.settings = settings_manager
        
        from themes import THEMES
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Theme
        t_grp = QGroupBox("APPEARANCE")
        tl = QVBoxLayout(t_grp)
        tl.setContentsMargins(10, 20, 10, 10)
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(list(THEMES.keys()))
        self.cmb_theme.setCurrentText(current_theme)
        tl.addWidget(ThemeLabel("System Theme:", "TEXT_MUTED", SZ_SM, bold=True))
        tl.addWidget(self.cmb_theme)
        layout.addWidget(t_grp)
        
        # Sampling
        s_grp = QGroupBox("DATA ACQUISITION")
        sl = QVBoxLayout(s_grp)
        sl.setContentsMargins(10, 20, 10, 10)
        self.spin_sp = QDoubleSpinBox()
        self.spin_sp.setRange(0.001, 1.0)
        self.spin_sp.setDecimals(3)
        self.spin_sp.setSuffix(" s (period)")
        self.spin_sp.setValue(self.settings.get("sample_period", 0.010))
        sl.addWidget(ThemeLabel("Global Sampling Period:", "TEXT_MUTED", SZ_SM, bold=True))
        sl.addWidget(self.spin_sp)
        layout.addWidget(s_grp)
        
        # Buttons
        btns = QHBoxLayout()
        self.btn_save = QPushButton("SAVE & APPLY")
        self.btn_save.setObjectName("btn_connect")
        self.btn_save.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("CANCEL")
        self.btn_cancel.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_save)
        layout.addLayout(btns)

    def get_values(self):
        return {
            "theme": self.cmb_theme.currentText(),
            "sample_period": self.spin_sp.value()
        }


# 
#  MAIN WINDOW  v6.0
# 

class MainWindow(QMainWindow):
    def _sync_settings(self):
        """Propagate settings (like sample_period) to all tabs."""
        sp = self._settings.get("sample_period", 0.010)
        self._analytics.sample_period = sp
        self.tab_mm.sample_period       = sp
        self.tab_power.sample_period    = sp
        self.tab_prodtest.sample_period = sp
        self.tab_mathchan.sample_period   = sp
        self.tab_uncertainty.sample_period = sp
        self.tab_trig.sample_period        = sp
        self.tab_proto.sample_period       = sp
        self.tab_bode.sample_period        = sp
        self.tab_wavedb.sample_period      = sp
        if hasattr(self, "tab_pid"):
            self.tab_pid.sample_period     = sp
        log.info(f"Settings synced: sample_period={sp}")


    def __init__(self):
        super().__init__()
        self._settings  = SettingsManager()
        self._serial    = SerialManager()
        self._parser    = DataParser()
        self._analytics = AnalyticsEngine(window=500)
        self._server    = MqttBridge()
        
        self._cloud_timer = QTimer()
        self._cloud_timer.setInterval(300)
        self._cloud_timer.timeout.connect(self._publish_cloud)
        self._cloud_timer.start()
        self._msg_count = 0
        self._last_screenshot = ""
        self._screenshot_dir  = None
        self._current_theme   = "Dark"

        # Auto-reconnect state
        self._auto_reconnect_port = ""
        self._auto_reconnect_timer = QTimer()
        self._auto_reconnect_timer.setInterval(1000)
        self._auto_reconnect_timer.timeout.connect(self._try_reconnect)

        self.setWindowTitle("STM32  REMOTE  ELECTRONICS  LAB  v6.0")
        self.resize(
            self._settings.get("win_w", 1280),
            self._settings.get("win_h", 870)
        )
        self.setMinimumSize(960, 640)

        self._build_menubar()
        self._build_ui()
        self._wire_signals()
        self._build_shortcuts()
        self._refresh_ports()
        self._load_settings()

        # Detect OS colour scheme and apply default theme
        self._apply_os_theme()
        self._override_theme_from_settings()

        # Serial auto-detect: select last used port if available
        last_port = self._settings.get("last_port", "")
        if last_port:
            idx = self.tab_conn.cmb_port.findText(last_port)
            if idx >= 0:
                self.tab_conn.cmb_port.setCurrentIndex(idx)

        # Status bar clock
        self._sb_timer = QTimer()
        self._sb_timer.setInterval(1000)
        self._sb_timer.timeout.connect(self._update_statusbar)
        self._sb_timer.start()

        # Sync settings to tabs
        self._sync_settings()

        # Load and apply calibration
        cal = load_calibration()
        if cal:
            self._analytics.cal_coeffs = cal
            log.info(f"Loaded calibration: {cal}")

        # Load plugins
        self._plugin_mgr = PluginManager(self.sidebar, self.stacked, self)
        plugin_log = self._plugin_mgr.load_all()
        for line in plugin_log:
            log.info(line)

    # -- OS theme auto-detect -----------------------------------------------

    def _apply_os_theme(self):
        """Auto-detect OS dark/light mode and set appropriate default."""
        try:
            hints = QApplication.instance().styleHints()
            # colorScheme() returns Qt.ColorScheme.Dark / Light (Qt 6.5+)
            if hasattr(hints, "colorScheme"):
                scheme = hints.colorScheme()
                if str(scheme) == "ColorScheme.Light":
                    set_theme(THEMES["Light"])
                    self.setStyleSheet(build_stylesheet())
                    return
        except Exception:
            pass
        # Default: Dark
        self._apply_theme(Theme)

    def _override_theme_from_settings(self):
        saved = self._settings.get("theme", "")
        if saved and saved in THEMES:
            self._apply_theme(THEMES[saved])

    # -- Theme -------------------------------------------------------------

    def _apply_theme(self, theme_cls):
        set_theme(theme_cls)
        self.setStyleSheet(build_stylesheet())
        
        # Globally reset the Qt Palette to prevent default dialogs/lists from retaining stale colors
        pal = QPalette()
        pal.setColor(QPalette.Window,          QColor(T.DARK_BG))
        pal.setColor(QPalette.WindowText,      QColor(T.TEXT))
        pal.setColor(QPalette.Base,            QColor(T.PANEL_BG))
        pal.setColor(QPalette.AlternateBase,   QColor(T.CARD_BG))
        pal.setColor(QPalette.Text,            QColor(T.TEXT))
        pal.setColor(QPalette.Button,          QColor(T.PANEL_BG))
        pal.setColor(QPalette.ButtonText,      QColor(T.TEXT))
        pal.setColor(QPalette.Highlight,       QColor(T.BORDER_HI))
        pal.setColor(QPalette.HighlightedText, QColor(T.TEXT))
        pal.setColor(QPalette.ToolTipBase,     QColor(T.CARD_BG))
        pal.setColor(QPalette.ToolTipText,     QColor(T.TEXT))
        QApplication.instance().setPalette(pal)

        self._repaint_live_widgets()
        self._current_theme = theme_cls.name if hasattr(theme_cls, "name") else "Dark"
        self._settings.set("theme", self._current_theme)

    def _repaint_live_widgets(self):
        _all_tabs = [
            self.tab_mm, self.tab_fg, self.tab_vreg,
            self.tab_cloud, self.tab_conn,
            self.tab_bode, self.tab_trig, self.tab_dsp,
            self.tab_proto, self.tab_playback, self.tab_repl,
            self.tab_nlcmd, self.tab_wavedb, self.tab_anomaly,
            self.tab_cal, self.tab_journal, self.tab_pid,
            # v6.0
            self.tab_uncertainty, self.tab_scpi,
            self.tab_power, self.tab_prodtest, self.tab_mathchan,
        ]
        
        # 1. Update logo and labels
        self._logo_lbl.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {SZ_LG}px; "
            f"font-weight: 700; font-family: {T.FONT_UI};")
            
        # 2. Update Sidebar (Categories & Tabs)
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            # Categories have no UserRole data
            if item.data(Qt.UserRole) is None:
                item.setFont(_ui_font(SZ_SM, bold=True))
                item.setForeground(QColor(T.PRIMARY))
            else:
                # Tab names
                item.setForeground(QColor(T.TEXT))

        # 3. Recursive update on all components
        for tab in _all_tabs:
            if hasattr(tab, "update_theme"):
                tab.update_theme()
            # Also find all children that have update_theme
            from PyQt5.QtWidgets import QWidget
            for child in tab.findChildren(QWidget):
                if hasattr(child, "update_theme"):
                    child.update_theme()
                    
        # 4. Search global children as fallback
        for lbl in self.findChildren(ThemeLabel):
            lbl.update_theme()
        for card in self.findChildren(ThemeCard):
            card.update_theme()
        for hs in self.findChildren(_HeaderStrip):
            hs.update_theme()
        for lw in self.findChildren(LocalLoggerWidget):
            lw.update_theme()
        for plot in self.findChildren(pg.PlotWidget):
            plot.setBackground(T.DARK_BG)

        self.lbl_sb_conn.setStyleSheet(
            f"font-family: {T.FONT_MONO}; font-size: {SZ_SM}px; color: {T.TEXT_MUTED};")
        self.lbl_sb_msgs.setStyleSheet(
            f"font-family: {T.FONT_MONO}; font-size: {SZ_SM}px; color: {T.TEXT_MUTED};")
        self.lbl_sb_log.setStyleSheet(
            f"font-family: {T.FONT_MONO}; font-size: {SZ_SM}px; color: {T.TEXT_MUTED};")
        self.lbl_sb_time.setStyleSheet(
            f"font-family: {T.FONT_MONO}; font-size: {SZ_SM}px; color: {T.TEXT_DIM};")

        # Refresh custom colors applied during _build_ui
        if hasattr(self, "_logo_lbl"):
            self._logo_lbl.setStyleSheet(
                f"color: {T.PRIMARY}; font-size: {SZ_LG}px; "
                f"font-weight: 700; font-family: {T.FONT_UI};")
                
        if hasattr(self, "sidebar"):
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                # If there's no UserRole data, it's a category header
                if item.data(Qt.UserRole) is None:
                    item.setForeground(QColor(T.PRIMARY))

    #  Menu 

    def _build_menubar(self):
        mb = self.menuBar()

        # Themes menu
        tm = mb.addMenu("Themes")
        for name, cls in THEMES.items():
            act = QAction(name, self)
            act.triggered.connect(lambda _, c=cls: self._apply_theme(c))
            tm.addAction(act)

        # Tools menu
        tools_menu = mb.addMenu("Tools")
        act_plugins = QAction("Plugin Directory", self)
        act_plugins.triggered.connect(self._open_plugin_dir)
        tools_menu.addAction(act_plugins)
        act_reload  = QAction("Reload Plugins", self)
        act_reload.triggered.connect(self._reload_plugins)
        tools_menu.addAction(act_reload)
        tools_menu.addSeparator()
        act_settings = QAction("Settings", self)
        act_settings.triggered.connect(self._open_settings)
        tools_menu.addAction(act_settings)

        # Help menu
        hm = mb.addMenu("Help")
        act_shortcuts = QAction("Keyboard Shortcuts  (F1)", self)
        act_shortcuts.triggered.connect(self._show_shortcuts)
        hm.addAction(act_shortcuts)
        ab = QAction("About v6.0", self)
        ab.triggered.connect(self._show_about)
        hm.addAction(ab)

    # -- UI ----------------------------------------------------------------

    def _build_ui(self):
        # Title bar
        self._title_bar = QWidget()
        self._title_bar.setFixedHeight(44)
        tb_lay = QHBoxLayout(self._title_bar)
        tb_lay.setContentsMargins(18, 0, 18, 0)

        self._logo_lbl = QLabel("STM32  //  REMOTE ELECTRONICS LAB  v6.0")
        self._logo_lbl.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {SZ_LG}px; "
            f"font-weight: 700; font-family: {T.FONT_UI};")
        tb_lay.addWidget(self._logo_lbl)
        tb_lay.addStretch()

        self.btn_screenshot = QPushButton(" [ Capture View ] ")
        self.btn_screenshot.setToolTip("Save a screenshot of the currently active panel")
        self.btn_screenshot.setStyleSheet(
            f"background: {T.CARD_BG}; color: {T.TEXT}; border: 1px solid {T.BORDER}; "
            f"border-radius: 4px; padding: 6px 12px; font-weight: bold; font-family: {T.FONT_UI};"
        )
        self.btn_screenshot.clicked.connect(self._global_screenshot)
        tb_lay.addWidget(self.btn_screenshot)

        central = QWidget()
        self.setCentralWidget(central)
        main_lay = QVBoxLayout(central)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)
        main_lay.addWidget(self._title_bar)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        main_lay.addWidget(self.splitter, stretch=1)

        self.sidebar = QListWidget()
        self.sidebar.setFocusPolicy(Qt.NoFocus)
        self.sidebar.setMinimumWidth(180)
        self.sidebar.setMaximumWidth(240)
        self.sidebar.currentRowChanged.connect(self._on_sidebar_changed)
        self.splitter.addWidget(self.sidebar)

        self.stacked = QStackedWidget()
        self.splitter.addWidget(self.stacked)
        self.splitter.setSizes([200, 1000])

        # -- Instantiate all tabs -------------------------------------------
        self.tab_mm       = MultimeterTab(self._analytics, screenshot_provider=self._ensure_screenshot_dir)
        self.tab_fg       = FunctionGenTab()
        self.tab_vreg     = VoltageRegTab()
        self.tab_cloud    = CloudTab(self._server)
        self.tab_conn     = ConnectionTab()
        self.tab_bode     = BodePlotTab()
        self.tab_trig     = TriggerTab()
        self.tab_dsp      = DSPPipelineTab()
        self.tab_proto    = ProtocolDecoderTab()
        self.tab_playback = PlaybackTab()
        self.tab_repl     = REPLTab()
        self.tab_nlcmd    = NLCommandTab()
        self.tab_wavedb   = WaveformDBTab()
        self.tab_pid      = PidTunerTab()
        self.tab_anomaly  = AnomalyDetectorTab()
        self.tab_cal      = CalibrationWizard()
        self.tab_journal  = JournalTab()
        # v6.0 new tabs
        self.tab_uncertainty = UncertaintyTab()
        self.tab_scpi        = SCPITab()
        self.tab_power       = PowerProfileTab()
        self.tab_prodtest    = ProdTestTab()
        self.tab_mathchan    = MathChannelsTab()

        # -- Add tabs to Sidebar -----------------------------------------------
        def add_category(name):
            item = QListWidgetItem(name.upper())
            item.setFlags(Qt.NoItemFlags)
            font = _ui_font(SZ_SM, bold=True)
            item.setFont(font)
            item.setForeground(QColor(T.PRIMARY))
            self.sidebar.addItem(item)
            
        def add_tab(tab_instance, name):
            self.stacked.addWidget(tab_instance)
            item = QListWidgetItem("  " + name)
            item.setData(Qt.UserRole, self.stacked.count() - 1)
            self.sidebar.addItem(item)

        add_category("Instruments")
        add_tab(self.tab_mm,       "Multimeter")
        add_tab(self.tab_fg,       "Function Gen")
        add_tab(self.tab_vreg,     "Voltage Reg")
        add_tab(self.tab_bode,     "Bode Plot")
        add_tab(self.tab_trig,     "Trigger")
        add_tab(self.tab_dsp,      "DSP Pipeline")
        add_tab(self.tab_proto,    "Protocol")
        add_tab(self.tab_playback, "Playback")
        add_tab(self.tab_pid,      "PID Tuner")

        add_category("Analysis")
        add_tab(self.tab_mathchan,    "Math Channels")
        add_tab(self.tab_power,       "Power Profiler")
        add_tab(self.tab_uncertainty, "Uncertainty")
        add_tab(self.tab_repl,        "Python REPL")
        add_tab(self.tab_nlcmd,       "NL Command")

        add_category("Logging & Test")
        add_tab(self.tab_wavedb,   "Waveform DB")
        add_tab(self.tab_anomaly,  "AI Anomaly")
        add_tab(self.tab_cal,      "Calibration")
        add_tab(self.tab_journal,  "Journal")
        add_tab(self.tab_prodtest, "Prod Test")

        add_category("Infrastructure")
        add_tab(self.tab_scpi,     "SCPI Server")
        add_tab(self.tab_cloud,    "Cloud Relay")
        add_tab(self.tab_conn,     "Connection")
        
        self._select_tab_index(0)

        # -- Status bar ----------------------------------------------------
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_sb_conn = QLabel("OFFLINE")
        self.lbl_sb_msgs = QLabel("RX: 0")
        self.lbl_sb_time = QLabel("")
        self.lbl_sb_log  = QLabel("")
        for s in [QLabel("  |  ")]:
            s.setStyleSheet(f"color: {T.TEXT_DIM};")
        sb.addWidget(self.lbl_sb_conn)
        sb.addWidget(QLabel("  |  "))
        sb.addWidget(self.lbl_sb_msgs)
        sb.addWidget(QLabel("  |  "))
        sb.addWidget(self.lbl_sb_log)
        sb.addPermanentWidget(self.lbl_sb_time)

    def _ensure_screenshot_dir(self) -> Path:
        """Prompt for a directory if not set for the session, then return Path."""
        from pathlib import Path
        if self._screenshot_dir is not None:
            return Path(self._screenshot_dir)

        # First capture of the session: Prompt User
        default_dir = str(Path.home() / "stm32lab" / "screenshots")
        Path(default_dir).mkdir(parents=True, exist_ok=True)
        
        selected = QFileDialog.getExistingDirectory(
            self, "Select Screenshot Save Location (Session)",
            default_dir
        )
        
        if selected:
            self._screenshot_dir = selected
        else:
            # User cancelled: use default for this session to avoid repeated prompts
            self._screenshot_dir = default_dir
            
        return Path(self._screenshot_dir)

    def _global_screenshot(self):
        import pyqtgraph as pg
        import pyqtgraph.exporters
        import datetime
        from pathlib import Path
        
        current_widget = self.stacked.currentWidget()
        if current_widget is None: return
        
        if current_widget == self.tab_mm:
            self.tab_mm._take_screenshot()
            return
            
        dir_path = self._ensure_screenshot_dir()
        dir_path.mkdir(parents=True, exist_ok=True)
        fname = f"capture_{datetime.datetime.now().strftime('%Y%h%d_%H%M%S')}.png"
        path = str(dir_path / fname)

        plots = current_widget.findChildren(pg.PlotWidget)
        if plots:
            try:
                exporter = pg.exporters.ImageExporter(plots[0].plotItem)
                exporter.export(path)
                self.statusBar().showMessage(f"Plot saved to: {path}", 5000)
                self._last_screenshot = path
                return
            except Exception:
                pass
                
        # Fallback to grabbing the entire widget surface
        pixmap = current_widget.grab()
        pixmap.save(path, "PNG")
        self.statusBar().showMessage(f"Panel saved to: {path}", 5000)

    def _on_sidebar_changed(self, row: int):
        item = self.sidebar.item(row)
        if item is None: return
        idx = item.data(Qt.UserRole)
        if idx is not None:
             self.stacked.setCurrentIndex(idx)
             
    def _select_tab_index(self, tab_idx: int):
        for i in range(self.sidebar.count()):
             item = self.sidebar.item(i)
             if item.data(Qt.UserRole) == tab_idx:
                 self.sidebar.setCurrentRow(i)
                 break

    # -- Keyboard Shortcuts ------------------------------------------------

    def _build_shortcuts(self):
        def _sc(key, fn):
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(fn)

        # Space = pause/resume DSO plot timer
        _sc("Space", self._toggle_dso_pause)
        # S = global screenshot
        _sc("S", self._global_screenshot)
        # C = connect/disconnect toggle
        _sc("C", self._shortcut_connect)
        # Tab switching: 1-9 selects tab 0-8
        for i in range(9):
            _sc(str(i + 1), lambda idx=i: self._select_tab_index(idx))
        # F1 = shortcuts help
        _sc("F1", self._show_shortcuts)
        # Ctrl+S = save journal
        _sc("Ctrl+S", self.tab_journal._save_current)

    def _toggle_dso_pause(self):
        timer = getattr(self.tab_mm, "_plot_timer", None)
        if timer:
            if timer.isActive():
                timer.stop()
                self.statusBar().showMessage("DSO PAUSED  (Space to resume)", 3000)
            else:
                timer.start()
                self.statusBar().showMessage("DSO RUNNING", 2000)

    def _shortcut_connect(self):
        if self._serial.is_connected:
            self._on_disconnect()
        else:
            port = self.tab_conn.cmb_port.currentText()
            if port:
                self._on_connect(port)

    # -- Signals -----------------------------------------------------------

    def _wire_signals(self):
        dso_snapshot = self._analytics.snapshot

        # Serial sends from all tabs
        for tab in [self.tab_mm, self.tab_fg, self.tab_vreg,
                    self.tab_repl, self.tab_nlcmd]:
            if hasattr(tab, "send_requested"):
                tab.send_requested.connect(self._send_command)

        # Serial connect/disconnect
        self.tab_conn.connect_requested.connect(self._on_connect)
        self.tab_conn.disconnect_requested.connect(self._on_disconnect)
        self.tab_conn.refresh_requested.connect(self._refresh_ports)

        # NL command interface
        self.tab_nlcmd.connect_requested.connect(
            lambda: self._on_connect(self.tab_conn.cmb_port.currentText()))
        self.tab_nlcmd.disconnect_requested.connect(self._on_disconnect)
        self.tab_nlcmd.set_stats_source(self._analytics.stats)

        # REPL snapshot source
        self.tab_repl.set_snapshot_source(dso_snapshot)

        # DSO sources for analysis tabs
        self.tab_bode.set_dso_source(dso_snapshot)
        self.tab_trig.set_dso_source(dso_snapshot)
        self.tab_dsp.set_dso_source(dso_snapshot)
        self.tab_proto.set_dso_source(dso_snapshot)
        self.tab_anomaly.set_dso_source(dso_snapshot)
        self.tab_cal.set_dso_source(dso_snapshot)
        self.tab_wavedb.set_dso_source(dso_snapshot)
        # v6.0 tabs
        self.tab_uncertainty.set_dso_source(self._analytics.snapshot)
        self.tab_uncertainty.set_stats_source(lambda: self._analytics.stats)

        # Calibration feedback
        self.tab_cal.calibration_updated.connect(self._on_calibration_updated)
        self.tab_power.set_dso_source(dso_snapshot)
        self.tab_prodtest.set_dso_source(dso_snapshot)
        self.tab_prodtest.set_stats_source(self._analytics.stats)
        self.tab_mathchan.set_dso_source(dso_snapshot)

        # SCPI server wiring
        self.tab_scpi.set_send_fn(self._send_command)
        self.tab_scpi.set_stats_fn(self._analytics.stats)
        self.tab_scpi.set_snapshot_fn(dso_snapshot)

        # Bode send
        self.tab_bode.send_requested.connect(self._send_command)

        # Cloud command routing
        self._server.command_received.connect(self._on_cloud_command)

        # DSP overlay
        self.tab_dsp.overlay_ready.connect(self._on_dsp_overlay)

        # Waveform DB overlay
        self.tab_wavedb.overlay_requested.connect(self._on_wavedb_overlay)

        # Playback row replay
        self.tab_playback.replay_row.connect(self._on_playback_row)
        
        # PID source
        self.tab_pid.set_data_source(lambda: (
            list(self._analytics._samples),
            [self.tab_pid.spin_sp.value()] * len(self._analytics._samples)
        ))

        # Serial data
        self._serial.signals.message_received.connect(self._on_message)
        self._serial.signals.connection_error.connect(self._on_serial_error)

    # -- Serial ------------------------------------------------------------

    def _on_connect(self, port: str):
        if not port:
            return
        if self._serial.connect(port):
            self.tab_conn.set_connected(port)
            self.tab_conn.log(f"Connected to {port} @ 115200 baud", T.PRIMARY)
            self.lbl_sb_conn.setText(f"ONLINE  {port}")
            self.lbl_sb_conn.setStyleSheet(
                f"color: {T.PRIMARY}; font-family: {T.FONT_MONO}; font-size: {SZ_SM}px;"
)
            self._auto_reconnect_port = port
            self._settings.set("last_port", port)
        else:
            self.tab_conn.log(f"Failed to connect to {port}", T.ACCENT_RED)

    def _on_disconnect(self):
        self._serial.disconnect()
        self.tab_conn.set_disconnected()
        self.tab_conn.log("Disconnected", T.TEXT_MUTED)
        self.lbl_sb_conn.setText("OFFLINE")
        self.lbl_sb_conn.setStyleSheet(
            f"color: {T.ACCENT_RED}; font-family: {T.FONT_MONO}; font-size: {SZ_SM}px;"
        )
        # Start auto-reconnect polling
        if self._auto_reconnect_port:
            self._auto_reconnect_timer.start()

    def _try_reconnect(self):
        """Attempt to reconnect to the last known port (1 s polling)."""
        if self._serial.is_connected:
            self._auto_reconnect_timer.stop()
            return
        ports = SerialManager.list_ports()
        if self._auto_reconnect_port in ports:
            log.info(f"Auto-reconnect: {self._auto_reconnect_port}")
            self._auto_reconnect_timer.stop()
            self._on_connect(self._auto_reconnect_port)

    def _refresh_ports(self):
        self.tab_conn.update_ports(SerialManager.list_ports())

    def _send_command(self, cmd: str):
        self._serial.send(cmd)
        self.tab_conn.log(f"[TX] {cmd}", T.ACCENT_BLUE)

    def _on_calibration_updated(self, coeffs: list):
        """Update analytics engine with new calibration coefficients."""
        if not coeffs:
            self._analytics.cal_coeffs = None
            log.info("Calibration cleared")
        else:
            self._analytics.cal_coeffs = coeffs
            log.info(f"Calibration updated: {coeffs}")

    # -- Settings Dialog -----------------------------------------------------------

    @staticmethod
    def get_settings_dialog(settings_manager, current_theme):
        return SettingsDialog(settings_manager, current_theme)

    def _on_message(self, raw: str):
        self._msg_count += 1
        self.tab_conn.log(f"[RX] {raw.strip()}", T.TEXT_MUTED)

        msg = self._parser.parse(raw)
        if msg is None:
            return

        if msg.kind == "DATA":
            self.tab_mm.on_data(msg)
            try:
                val = float(msg.fields.get("X", "0"))
                self._analytics.push(val)
                self.tab_mm.on_dso_sample(val)
                self.tab_trig.push_sample(val)
            except ValueError:
                pass
        elif msg.kind == "BOOST":
            self.tab_pid.on_data(msg)
        elif msg.kind == "ACK":
            self.statusBar().showMessage(f"Device: {msg.fields.get('M','ACK')}", 2000)
        elif msg.kind == "ERR":
            self.statusBar().showMessage(f"Error: {msg.fields.get('M','Unknown')}", 5000)
            self.tab_vreg.on_boost(msg)
        elif msg.kind == "TEMP":
            self.tab_vreg.on_temp(msg)
        elif msg.kind == "ACK":
            self.tab_conn.log(f"[ACK] {raw.strip()}", T.PRIMARY)
        elif msg.kind == "ERR":
            self.tab_conn.log(f"[ERR] {raw.strip()}", T.ACCENT_RED)

    def _on_serial_error(self, msg: str):
        self.tab_conn.log(f"[ERR] Serial: {msg}", T.ACCENT_RED)
        self._on_disconnect()

    def _on_dsp_overlay(self, arr):
        """DSP pipeline result: overlay on DSO plot."""
        try:
            n  = len(arr)
            sp = self.tab_mm.sample_period
            t  = (np.arange(n, dtype=float) - (n - 1)) * sp
            # Use a second curve if it exists; otherwise plot() creates one
            if not hasattr(self, "_dsp_overlay_curve"):
                self._dsp_overlay_curve = self.tab_mm.plot_widget.plot(
                    pen=pg.mkPen(T.ACCENT_PUR, width=1.5, style=Qt.DashLine))
            self._dsp_overlay_curve.setData(t, arr)
        except Exception as e:
            log.warning(f"DSP overlay error: {e}")

    def _on_wavedb_overlay(self, arr):
        """Waveform DB comparison overlay on DSO plot."""
        try:
            n  = len(arr)
            sp = self.tab_mm.sample_period
            t  = (np.arange(n, dtype=float) - (n - 1)) * sp
            if not hasattr(self, "_wavedb_overlay_curve"):
                self._wavedb_overlay_curve = self.tab_mm.plot_widget.plot(
                    pen=pg.mkPen(T.ACCENT_AMBER, width=1.5, style=Qt.DotLine))
            self._wavedb_overlay_curve.setData(t, arr)
        except Exception as e:
            log.warning(f"WaveDB overlay error: {e}")

    def _on_playback_row(self, row: dict):
        """Feed a replayed row into the analytics/DSO pipeline."""
        try:
            val = float(row.get("value", "0"))
            self._analytics.push(val)
            self.tab_mm.on_dso_sample(val)
            # Build a fake ParsedMessage for the multimeter
            mode = str(row.get("mode", "V"))
            msg  = ParsedMessage("DATA", {"M": mode[:1], "X": str(val)})
            self.tab_mm.on_data(msg)
        except Exception:
            pass

    # -- Settings persistence ----------------------------------------------

    def _load_settings(self):
        """Restore saved widget values after UI is built."""
        widget_map = {
            "mm_mode":       self.tab_mm.cmb_mode,
            "mm_range":      self.tab_mm.cmb_range,
            "fg_freq":       self.tab_fg.spin_freq,
            "vreg_voltage":  self.tab_vreg.spin_vreg,
            "conn_port":     self.tab_conn.cmb_port,
            "bode_f_start":  self.tab_bode.spin_f_start,
            "bode_f_stop":   self.tab_bode.spin_f_stop,
        }
        self._settings.restore_widget_values(widget_map)

    def _save_settings(self):
        widget_map = {
            "mm_mode":       self.tab_mm.cmb_mode,
            "mm_range":      self.tab_mm.cmb_range,
            "fg_freq":       self.tab_fg.spin_freq,
            "vreg_voltage":  self.tab_vreg.spin_vreg,
            "conn_port":     self.tab_conn.cmb_port,
            "bode_f_start":  self.tab_bode.spin_f_start,
            "bode_f_stop":   self.tab_bode.spin_f_stop,
        }
        self._settings.save_widget_values(widget_map)
        geo = self.geometry()
        self._settings.set_geometry(geo.x(), geo.y(), geo.width(), geo.height())
        self._settings.set("win_w", geo.width())
        self._settings.set("win_h", geo.height())
        self._settings.save()

    # -- Status bar --------------------------------------------------------

    def _update_statusbar(self):
        self.lbl_sb_msgs.setText(f"RX: {self._msg_count}")
        self.lbl_sb_time.setText(
            datetime.datetime.now().strftime("  %Y-%m-%d  %H:%M:%S  "))

    def _publish_cloud(self):
        if self._server.is_running:
            self._server.publish_data(self._analytics.snapshot(), self._analytics.stats())

    def _on_cloud_command(self, cmd: str):
        if hasattr(self, "tab_scpi") and self.tab_scpi._server:
            self.tab_scpi._server.dispatcher.handle(cmd)

    # -- Help dialogs ------------------------------------------------------

    def _show_shortcuts(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        dlg.resize(480, 420)
        lay = QVBoxLayout(dlg)
        t   = QTextEdit()
        t.setReadOnly(True)
        t.setFont(_ui_font(SZ_BODY))
        t.setHtml(f"""
<pre style="color:{T.PRIMARY}; font-family:Consolas,monospace; line-height:1.8;">
  <b style="color:{T.ACCENT_CYAN}">GLOBAL</b>
  Space        Pause / Resume DSO plot
  S            Save waveform screenshot (PNG)
  C            Connect / Disconnect serial port
  F1           This help dialog
  Ctrl+S       Save current journal entry

  <b style="color:{T.ACCENT_CYAN}">TAB SWITCHING</b>
  1            Multimeter
  2            Function Generator
  3            Voltage Regulator
  4            Bode Plot
  5            Trigger
  6            DSP Pipeline
  7            Protocol Decoder
  8            Playback
  9            Python REPL

  <b style="color:{T.ACCENT_CYAN}">DSO QUICK TIPS</b>
  Drag the amber dashed line  ->  set trigger level
  Two vertical cursors        ->  place in the Multimeter tab
  Right-click plot            ->  pyqtgraph options
</pre>""")
        lay.addWidget(t)
        btn = QPushButton("CLOSE")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn, alignment=Qt.AlignRight)
        dlg.exec_()

    def _show_about(self):
        QMessageBox.information(self, "About STM32 Lab v6.0",
            "STM32 Remote Electronics Lab v6.0\n\n"
            "Controls STM32 Bluepill over UART.\n\n"
            "v6.0 Features:\n"
            "  * Protocol Decoder (I2C/SPI/UART/1-Wire)\n"
            "  * Bode Plot / Impedance Analyser\n"
            "  * Triggered / Single-Shot Capture\n"
            "  * DSP Pipeline (Butterworth, Chebyshev, FIR, Hilbert...)\n"
            "  * CSV / SQLite Playback with scrubber\n"
            "  * Python REPL with lab.send() / lab.snapshot()\n"
            "  * Natural Language Commands (no API key)\n"
            "  * Waveform Database & Search (SQLite)\n"
            "  * Uncertainty Quantification (+/- 1-sigma)\n"
            "  * SCPI / LXI Server (Port 5025)\n"
            "  * Power Profile & Energy Track\n"
            "  * Production Test PASS/FAIL Mode\n"
            "  * Math Channels & Differential Analysis\n"
            "  * AI Anomaly Detector (IsolationForest / 3-sigma)\n"
            "  * Calibration Wizard (polynomial fitting)\n"
            "  * Experiment Journal (Markdown/HTML export)\n"
            "  * 14 themes including Colour-Blind Safe (IBM palette)\n"
            "  * Plugin drop-in system (~/stm32lab/plugins/)\n\n"
            "All analysis is local - no cloud, no API keys.")

    # -- Plugin helpers ----------------------------------------------------

    def _open_plugin_dir(self):
        import subprocess
        d = str(self._plugin_mgr.plugin_dir)
        self._plugin_mgr.plugin_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(f'explorer "{d}"', shell=True)

    def _reload_plugins(self):
        log_lines = self._plugin_mgr.reload_all()
        msg = "\n".join(log_lines) or "No plugins found."
        QMessageBox.information(self, "Plugin Reload", msg)

    def _open_settings(self):
        """Invoke the new professional settings UI."""
        dlg = SettingsDialog(self._settings, self._current_theme)
        if dlg.exec_():
            vals = dlg.get_values()
            self._settings.set("theme", vals["theme"])
            self._settings.set("sample_period", vals["sample_period"])
            self._settings.save()
            
            # Hot-reload 
            self._apply_theme(THEMES[vals["theme"]])
            self._sync_settings()
            self.statusBar().showMessage("Settings saved and applied.", 4000)

    # -- Close -------------------------------------------------------------

    def closeEvent(self, event):
        self._save_settings()
        self._serial.disconnect()
        self._server.disconnect_cloud()
        event.accept()


# 
#  ENTRY POINT
# 

def main():
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except AttributeError:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("STM32 Remote Lab v6.0")
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(T.DARK_BG))
    pal.setColor(QPalette.WindowText,      QColor(T.TEXT))
    pal.setColor(QPalette.Base,            QColor(T.PANEL_BG))
    pal.setColor(QPalette.AlternateBase,   QColor(T.CARD_BG))
    pal.setColor(QPalette.Text,            QColor(T.TEXT))
    pal.setColor(QPalette.Button,          QColor(T.PANEL_BG))
    pal.setColor(QPalette.ButtonText,      QColor(T.TEXT))
    pal.setColor(QPalette.Highlight,       QColor(T.BORDER_HI))
    pal.setColor(QPalette.HighlightedText, QColor(T.TEXT))
    pal.setColor(QPalette.ToolTipBase,     QColor(T.CARD_BG))
    pal.setColor(QPalette.ToolTipText,     QColor(T.TEXT))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
