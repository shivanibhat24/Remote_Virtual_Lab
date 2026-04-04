"""
tab_power.py - Power Profile Analyser for STM32 Lab GUI v6.0

Roadmap item #12: Power Profile Analyser.
  * Real-time V x I instantaneous power waveform
  * Energy accumulator (Joules -> mWh)
  * Sleep/Wake transition detection via threshold crossing
  * Annotated timeline markers on the power trace
  * State-time breakdown: % time in each state
  * Charge accumulation (mAh)

NOTE: Without a 2-channel DSO (voltage on CH1, current on CH2) this tab
uses a single-channel proxy:  power = V^2 / R (ohms-law estimate) with
user-settable load resistance, or direct current if mode=Ammeter.
"""

import math
import datetime
from collections import deque
from typing import Callable, List, Optional

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox,
    QGroupBox, QSplitter, QComboBox, QCheckBox, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget


# -- State Detector -----------------------------------------------------------
# State Detector
# 

class _StateDetector:
    """Threshold-hysteresis sleep/wake detector."""

    def __init__(self, wake_threshold: float = 0.5, hysteresis: float = 0.05):
        self.wake_threshold = wake_threshold
        self.hysteresis     = hysteresis
        self._state         = "sleep"
        self._transitions   = []  # list of (sample_idx, "sleep" -> "wake" | "wake" -> "sleep")

    def push(self, power_w: float, idx: int):
        if self._state == "sleep" and power_w > self.wake_threshold + self.hysteresis:
            self._state = "wake"
            self._transitions.append((idx, "sleep -> wake"))
        elif self._state == "wake" and power_w < self.wake_threshold - self.hysteresis:
            self._state = "sleep"
            self._transitions.append((idx, "wake -> sleep"))

    def reset(self):
        self._state       = "sleep"
        self._transitions = []

    @property
    def current_state(self) -> str:
        return self._state

    @property
    def transitions(self):
        return list(self._transitions)


# -- Power Profile Tab --------------------------------------------------------
# Power Profile Tab
# 

class PowerProfileTab(QWidget):
    """Real-time power profiling from voltage/current DSO data."""

    HISTORY = 1000
    sample_period = 0.010   # 100 Hz default (updated by main GUI)

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []

        self._power_buf: deque = deque(maxlen=self.HISTORY)
        self._time_buf:  deque = deque(maxlen=self.HISTORY)
        self._energy_j   = 0.0
        self._charge_c   = 0.0
        self._t_elapsed  = 0.0
        self._t_sleep    = 0.0
        self._t_wake     = 0.0
        self._sample_idx = 0
        self._annotations: list = []

        self._detector = _StateDetector()

        self._monitor = False
        self._timer = QTimer()
        self._timer.setInterval(200)   # 5 Hz refresh
        self._timer.timeout.connect(self._refresh)

        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Power Profile Analyser")
        self._header_strip = hdr

        self.btn_monitor = QPushButton("> MONITOR")
        self.btn_monitor.setObjectName("btn_connect")
        self.btn_monitor.setFixedWidth(140)
        self.btn_monitor.clicked.connect(self._toggle_monitor)
        hdr_lay.addWidget(self.btn_monitor)

        self.btn_reset = QPushButton("RESET")
        self.btn_reset.setObjectName("btn_disconnect")
        self.btn_reset.setFixedWidth(90)
        self.btn_reset.clicked.connect(self._reset)
        hdr_lay.addWidget(self.btn_reset)

        self.local_logger = LocalLoggerWidget("power_profile", ["timestamp", "inst_mw", "avg_mw", "energy_mwh", "charge_mah", "state"])
        hdr_lay.addStretch()
        hdr_lay.addWidget(self.local_logger)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: settings ----------------------------------------------------
        ctrl_w = QWidget()
        ctrl_w.setMaximumWidth(280)
        c_lay = QVBoxLayout(ctrl_w)
        c_lay.setContentsMargins(14, 14, 14, 14)
        c_lay.setSpacing(12)

        mode_grp = QGroupBox("POWER ESTIMATION MODE")
        mg = QVBoxLayout(mode_grp)
        mg.setContentsMargins(12, 24, 12, 12)
        mg.setSpacing(8)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([
            "V/R  (single voltage channel)",
            "V  I  (dual channel  use overlay)",
        ])
        mg.addWidget(self.cmb_mode)

        row_r = QHBoxLayout()
        row_r.addWidget(ThemeLabel("Load R:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_r = QDoubleSpinBox()
        self.spin_r.setRange(0.1, 100_000)
        self.spin_r.setValue(100.0)
        self.spin_r.setSuffix(" Ohm")
        self.spin_r.setDecimals(1)
        row_r.addWidget(self.spin_r)
        mg.addLayout(row_r)

        row_v = QHBoxLayout()
        row_v.addWidget(ThemeLabel("Vref:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_vref = QDoubleSpinBox()
        self.spin_vref.setRange(0.0, 24.0)
        self.spin_vref.setValue(3.3)
        self.spin_vref.setSuffix(" V")
        self.spin_vref.setDecimals(2)
        row_v.addWidget(self.spin_vref)
        mg.addLayout(row_v)

        c_lay.addWidget(mode_grp)

        thresh_grp = QGroupBox("SLEEP/WAKE THRESHOLD")
        tg = QVBoxLayout(thresh_grp)
        tg.setContentsMargins(12, 24, 12, 12)
        tg.setSpacing(8)
        row_t = QHBoxLayout()
        row_t.addWidget(ThemeLabel("Threshold:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(0.0, 100.0)
        self.spin_thresh.setValue(1.0)
        self.spin_thresh.setSuffix(" mW")
        self.spin_thresh.setDecimals(3)
        self.spin_thresh.valueChanged.connect(
            lambda v: setattr(self._detector, "wake_threshold", v * 1e-3))
        row_t.addWidget(self.spin_thresh)
        tg.addLayout(row_t)
        row_h = QHBoxLayout()
        row_h.addWidget(ThemeLabel("Hysteresis:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_hyst = QDoubleSpinBox()
        self.spin_hyst.setRange(0.0, 10.0)
        self.spin_hyst.setValue(0.1)
        self.spin_hyst.setSuffix(" mW")
        self.spin_hyst.setDecimals(3)
        self.spin_hyst.valueChanged.connect(
            lambda v: setattr(self._detector, "hysteresis", v * 1e-3))
        row_h.addWidget(self.spin_hyst)
        tg.addLayout(row_h)
        c_lay.addWidget(thresh_grp)

        # Stat cards
        self.lbl_power_now  = QLabel("- W")
        self.lbl_power_avg  = QLabel("- W")
        self.lbl_energy     = QLabel("- mWh")
        self.lbl_charge     = QLabel("- mAh")
        self.lbl_state      = QLabel("SLEEP")
        self.lbl_wake_pct   = QLabel("- %")
        for lbl, name, col in [
            (self.lbl_power_now, "INST POWER", "PRIMARY"),
            (self.lbl_power_avg, "AVG POWER",  "ACCENT_BLUE"),
            (self.lbl_energy,    "ENERGY",      "ACCENT_AMBER"),
            (self.lbl_charge,    "CHARGE",      "ACCENT_PUR"),
            (self.lbl_state,     "STATE",        "ACCENT_CYAN"),
            (self.lbl_wake_pct,  "% AWAKE",     "ACCENT_RED"),
        ]:
            c_lay.addWidget(ThemeCard(name, lbl, col))

        c_lay.addStretch()
        splitter.addWidget(ctrl_w)

        # -- RIGHT: plots ------------------------------------------------------
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(6)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)

        # Main power plot
        self._power_plot = pg.PlotWidget()
        self._power_plot.setLabel("left",   "Power (mW)", color=T.TEXT_MUTED)
        self._power_plot.setLabel("bottom", "Sample",     color=T.TEXT_MUTED)
        self._power_plot.showGrid(x=True, y=True, alpha=0.14)
        self._power_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._power_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        # Threshold line
        self._thresh_line = self._power_plot.addLine(
            y=self.spin_thresh.value(),
            pen=pg.mkPen(T.ACCENT_RED, width=1, style=Qt.DashLine))
        self._power_curve = self._power_plot.plot(
            pen=pg.mkPen(T.PRIMARY, width=2))
        r_lay.addWidget(self._power_plot, stretch=2)

        # Energy accumulation mini-plot
        self._energy_plot = pg.PlotWidget()
        self._energy_plot.setFixedHeight(120)
        self._energy_plot.setLabel("left",   "Energy (mWh)", color=T.TEXT_MUTED)
        self._energy_plot.setLabel("bottom", "Sample",       color=T.TEXT_MUTED)
        self._energy_plot.showGrid(x=True, y=True, alpha=0.14)
        self._energy_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._energy_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._energy_curve = self._energy_plot.plot(
            pen=pg.mkPen(T.ACCENT_AMBER, width=2))
        self._energy_buf: list = []
        r_lay.addWidget(self._energy_plot)

        splitter.addWidget(right_w)
        splitter.setSizes([260, 900])

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        if getattr(self, "local_logger", None):
            self.local_logger.update_theme()
        for p in (self._power_plot, self._energy_plot):
            p.setBackground(T.DARK_BG)
            p.getAxis("left").setTextPen(T.TEXT_MUTED)
            p.getAxis("bottom").setTextPen(T.TEXT_MUTED)

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    # -- Actions ---------------------------------------------------------------

    def _toggle_monitor(self):
        if self._timer.isActive():
            self._timer.stop()
            self.btn_monitor.setText("> MONITOR")
        else:
            self._timer.start()
            self.btn_monitor.setText("|| PAUSE")

    def _reset(self):
        self._power_buf.clear()
        self._time_buf.clear()
        self._energy_j  = 0.0
        self._charge_c  = 0.0
        self._t_elapsed = 0.0
        self._t_sleep   = 0.0
        self._t_wake    = 0.0
        self._sample_idx = 0
        self._energy_buf.clear()
        self._detector.reset()
        self._power_curve.setData([], [])
        self._energy_curve.setData([], [])
        for ann in self._annotations:
            try:
                self._power_plot.removeItem(ann)
            except Exception:
                pass
        self._annotations.clear()

    # -- Core Refresh ----------------------------------------------------------

    def _refresh(self):
        raw = self._dso_source()
        if len(raw) < 4:
            return
        arr = np.array(raw, dtype=float)
        n   = len(arr)

        # Compute power per sample
        if "V/R" in self.cmb_mode.currentText():
            R = max(0.001, self.spin_r.value())
            power_w = arr ** 2 / R
        else:
            # V x I: use vref as current proxy (I = V/Rload)
            R = max(0.001, self.spin_r.value())
            vref = self.spin_vref.value()
            power_w = arr * (vref / R)

        # Process each new sample
        prev_idx = self._sample_idx
        for i, p in enumerate(power_w):
            idx = prev_idx + i
            self._power_buf.append(p * 1000)  # mW
            self._time_buf.append(idx)
            self._energy_j  += p * self.sample_period
            self._charge_c  += abs(p / max(0.001, self.spin_vref.value())) * self.sample_period
            self._t_elapsed += self.sample_period

            state_before = self._detector.current_state
            self._detector.push(p, idx)
            state_after  = self._detector.current_state

            if state_after == "wake":
                self._t_wake  += self.sample_period
            else:
                self._t_sleep += self.sample_period

            # Add transition annotation
            if state_before != state_after:
                ann = pg.TextItem(
                    text=f"{'WAKE UP' if state_after == 'wake' else 'SLEEP'}",
                    color=T.ACCENT_CYAN if state_after == "wake" else T.TEXT_MUTED,
                    anchor=(0.5, 1),
                )
                ann.setFont(_ui_font(SZ_SM, bold=True))
                self._power_plot.addItem(ann)
                ann.setPos(idx, float(np.max(list(self._power_buf))))
                self._annotations.append(ann)

        self._sample_idx += n
        self._energy_buf.append(self._energy_j * 1000 / 3600)  # mWh

        # Update plots
        pb = np.array(self._power_buf, dtype=float)
        tb = np.array(self._time_buf, dtype=float)
        self._power_curve.setData(tb, pb)
        self._energy_curve.setData(np.arange(len(self._energy_buf)),
                                   np.array(self._energy_buf))
        self._thresh_line.setValue(self.spin_thresh.value())

        # Update stat cards
        inst_mw = float(power_w[-1]) * 1000
        avg_mw  = float(np.mean(pb)) if len(pb) else 0.0
        self.lbl_power_now.setText(f"{inst_mw:.3f} mW")
        self.lbl_power_avg.setText(f"{avg_mw:.3f} mW")
        self.lbl_energy.setText(f"{self._energy_j * 1000 / 3600:.4f} mWh")
        self.lbl_charge.setText(f"{self._charge_c * 1000 / 3600:.4f} mAh")
        self.lbl_state.setText(self._detector.current_state.upper())
        wake_pct = (self._t_wake / max(1e-9, self._t_elapsed)) * 100
        self.lbl_wake_pct.setText(f"{wake_pct:.1f}%")
        col = T.PRIMARY if self._detector.current_state == "wake" else T.TEXT_MUTED
        self.lbl_state.setStyleSheet(
            f"color: {col}; font-size: {SZ_STAT}px; font-weight: 700; "
            f"font-family: {T.FONT_MONO}; background: transparent; border: none;")

        if getattr(self, "local_logger", None):
            self.local_logger.log({
                "inst_mw": inst_mw,
                "avg_mw": avg_mw,
                "energy_mwh": self._energy_j * 1000 / 3600,
                "charge_mah": self._charge_c * 1000 / 3600,
                "state": self._detector.current_state.upper()
            })
