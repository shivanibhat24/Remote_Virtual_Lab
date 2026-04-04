"""
tab_trigger.py - Triggered / Single-Shot Capture tab for STM32 Lab GUI v6.0

Implements:
  * Rising / Falling / Pulse-Width / Runt / External trigger modes
  * Pre-trigger ring buffer (shows what happened before the event)
  * Single-shot mode (arms once, auto-disarms after capture)
  * Configurable threshold (V) and holdoff (ms)
"""

from collections import deque
from typing import Optional, List, Callable

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QSpinBox, QGroupBox, QSplitter, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header


class TriggerTab(QWidget):
    """Real oscilloscope-style trigger engine with pre/post trigger buffer."""

    # States
    STATE_IDLE      = "IDLE"
    STATE_ARMED     = "ARMED"
    STATE_WAITING   = "WAITING"
    STATE_TRIGGERED = "TRIGGERED"

    def __init__(self):
        super().__init__()
        self.sample_period    = 0.010  # default
        self.PRE_TRIG_COUNT   = 100
        self.POST_TRIG_COUNT  = 200
        self.TOTAL_BUF        = self.PRE_TRIG_COUNT + self.POST_TRIG_COUNT

        self._header_strip: Optional[_HeaderStrip] = None
        self._stat_cards:   List[ThemeCard]        = []

        # Ring buffer always filling from live DSO
        self._ring: deque = deque(maxlen=self.TOTAL_BUF)
        # Frozen capture
        self._capture:    Optional[np.ndarray] = None
        self._trig_pos:   int = self.PRE_TRIG_COUNT

        self._state       = self.STATE_IDLE
        self._armed       = False
        self._single_shot = False

        self._prev_sample     = 0.0
        self._pw_start_idx    = -1
        self._holdoff_remaining = 0
        self._post_samples_needed = 0
        self.TOTAL_BUF        = self.PRE_TRIG_COUNT + self.POST_TRIG_COUNT

        # DSO source injected by MainWindow
        self._dso_source: Callable[[], list] = lambda: []

        # Polling timer
        self._poll_timer = QTimer()
        self._poll_timer.setInterval(20)   # 50 Hz evaluation
        self._poll_timer.timeout.connect(self._poll_trigger)
        self._poll_timer.start()

        self._build_ui()

    # -- UI Build --------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Triggered / Single-Shot Capture")
        self._header_strip = hdr

        self.btn_arm = QPushButton("[ ARM TRIGGER ]")
        self.btn_arm.setObjectName("btn_connect")
        self.btn_arm.setFixedWidth(120)
        self.btn_arm.clicked.connect(self._arm)
        hdr_lay.addWidget(self.btn_arm)

        self.btn_disarm = QPushButton("[] DISARM")
        self.btn_disarm.setObjectName("btn_disconnect")
        self.btn_disarm.setFixedWidth(120)
        self.btn_disarm.setEnabled(False)
        self.btn_disarm.clicked.connect(self._disarm)
        hdr_lay.addWidget(self.btn_disarm)

        self.btn_force = QPushButton("FORCE TRIG")
        self.btn_force.setObjectName("btn_warning")
        self.btn_force.setFixedWidth(130)
        self.btn_force.clicked.connect(self._force_trigger)
        hdr_lay.addWidget(self.btn_force)

        self.chk_single = QCheckBox("Single-shot")
        self.chk_single.setChecked(True)
        hdr_lay.addWidget(self.chk_single)

        root.addWidget(hdr)

        # -- Main layout -------------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: trigger settings --------------------------------------------
        ctrl_w = QWidget()
        ctrl_w.setMaximumWidth(260)
        c_lay  = QVBoxLayout(ctrl_w)
        c_lay.setContentsMargins(14, 14, 14, 14)
        c_lay.setSpacing(12)

        trig_grp = QGroupBox("TRIGGER SETTINGS")
        tg_lay   = QVBoxLayout(trig_grp)
        tg_lay.setSpacing(10)
        tg_lay.setContentsMargins(12, 22, 12, 12)
        c_lay.addWidget(trig_grp)

        def _row(label, widget):
            r = QHBoxLayout()
            r.addWidget(ThemeLabel(label, "TEXT_MUTED", SZ_SM, bold=True))
            r.addWidget(widget)
            tg_lay.addLayout(r)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([
            "Rising Edge", "Falling Edge",
            "Pulse Width", "Runt", "External"
        ])
        _row("Mode:", self.cmb_mode)

        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(-24.0, 24.0)
        self.spin_thresh.setValue(1.0)
        self.spin_thresh.setSuffix(" V")
        self.spin_thresh.setDecimals(3)
        _row("Threshold:", self.spin_thresh)

        self.spin_holdoff = QSpinBox()
        self.spin_holdoff.setRange(0, 10000)
        self.spin_holdoff.setValue(0)
        self.spin_holdoff.setSuffix(" ms")
        _row("Holdoff:", self.spin_holdoff)

        self.spin_pw_min = QDoubleSpinBox()
        self.spin_pw_min.setRange(0.001, 10.0)
        self.spin_pw_min.setValue(0.1)
        self.spin_pw_min.setSuffix(" s")
        self.spin_pw_min.setDecimals(3)
        _row("PW Min:", self.spin_pw_min)

        self.spin_pw_max = QDoubleSpinBox()
        self.spin_pw_max.setRange(0.001, 10.0)
        self.spin_pw_max.setValue(0.5)
        self.spin_pw_max.setSuffix(" s")
        self.spin_pw_max.setDecimals(3)
        _row("PW Max:", self.spin_pw_max)

        self.spin_runt = QDoubleSpinBox()
        self.spin_runt.setRange(0.001, 24.0)
        self.spin_runt.setValue(0.5)
        self.spin_runt.setSuffix(" V (runt)")
        self.spin_runt.setDecimals(3)
        _row("Runt Hi:", self.spin_runt)

        buf_grp = QGroupBox("BUFFER")
        bg_lay  = QVBoxLayout(buf_grp)
        bg_lay.setSpacing(6)
        bg_lay.setContentsMargins(12, 22, 12, 12)
        c_lay.addWidget(buf_grp)

        self.spin_pre = QSpinBox()
        self.spin_pre.setRange(10, 400)
        self.spin_pre.setValue(self.PRE_TRIG_COUNT)
        self.spin_pre.setSuffix(" samples pre")
        bg_lay.addWidget(self.spin_pre)

        self.spin_post = QSpinBox()
        self.spin_post.setRange(10, 400)
        self.spin_post.setValue(self.POST_TRIG_COUNT)
        self.spin_post.setSuffix(" samples post")
        bg_lay.addWidget(self.spin_post)

        # Stat cards
        self.lbl_state    = QLabel("IDLE")
        self.lbl_trig_val = QLabel("-")
        self.lbl_trig_t   = QLabel("-")
        card_s = ThemeCard("STATE",       self.lbl_state,    "TEXT_MUTED")
        card_v = ThemeCard("TRIG VALUE",  self.lbl_trig_val, "ACCENT_AMBER")
        card_t = ThemeCard("TRIG TIME",   self.lbl_trig_t,   "ACCENT_BLUE")
        self._stat_cards = [card_s, card_v, card_t]
        c_lay.addWidget(card_s)
        c_lay.addWidget(card_v)
        c_lay.addWidget(card_t)
        c_lay.addStretch()
        splitter.addWidget(ctrl_w)

        # -- RIGHT: capture plot -----------------------------------------------
        plot_w = QWidget()
        p_lay  = QVBoxLayout(plot_w)
        p_lay.setContentsMargins(8, 8, 8, 8)
        p_lay.setSpacing(4)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self._plot = pg.PlotWidget()
        self._plot.setLabel("left",   "Voltage (V)", color=T.TEXT_MUTED)
        self._plot.setLabel("bottom", "Time (s)",    color=T.TEXT_MUTED)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

        # Pre-trigger shaded region
        self._pre_region = pg.LinearRegionItem(
            values=[-self.PRE_TRIG_COUNT * self.sample_period, 0],
            movable=False,
            brush=pg.mkBrush(QColor(T.ACCENT_BLUE).darker(400))
        )
        self._plot.addItem(self._pre_region)

        # Trigger line
        self._trig_h_line = pg.InfiniteLine(
            angle=0, movable=False,
            pen=pg.mkPen(T.ACCENT_AMBER, width=1, style=Qt.DashLine),
            label="Threshold {value:.2f}V",
            labelOpts={"color": T.ACCENT_AMBER, "position": 0.05}
        )
        self._plot.addItem(self._trig_h_line)
        self._trig_h_line.setValue(1.0)

        self._trig_v_line = pg.InfiniteLine(
            angle=90, movable=False,
            pen=pg.mkPen(T.ACCENT_RED, width=1, style=Qt.DashLine)
        )
        self._plot.addItem(self._trig_v_line)
        self._trig_v_line.setValue(0.0)

        self._curve_pre  = self._plot.plot(
            pen=pg.mkPen(T.ACCENT_BLUE + "88", width=1.5))  # dimmed pre-trig
        self._curve_post = self._plot.plot(
            pen=pg.mkPen(T.ACCENT_BLUE, width=2))            # bright post-trig
        self._curve_live = self._plot.plot(
            pen=pg.mkPen(T.TEXT_DIM, width=1))               # rolling live view

        p_lay.addWidget(self._plot, stretch=1)
        splitter.addWidget(plot_w)
        splitter.setSizes([240, 800])

        # Live-preview timer (even when idle)
        self._live_timer = QTimer()
        self._live_timer.setInterval(50)
        self._live_timer.timeout.connect(self._update_live_plot)
        self._live_timer.start()

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    def push_sample(self, value: float):
        """Called by MainWindow for every new DSO sample."""
        self._ring.append(value)

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        for card in self._stat_cards:
            card.update_theme()
        self._plot.setBackground(T.DARK_BG)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

    # -- Arm / Disarm ----------------------------------------------------------

    def _arm(self):
        self._state         = self.STATE_ARMED
        self._armed         = True
        self._single_shot   = self.chk_single.isChecked()
        self._capture       = None
        self._holdoff_remaining = 0
        self._prev_sample   = 0.0
        self._post_samples  = 0
        self._collecting_post = False

        self.btn_arm.setEnabled(False)
        self.btn_disarm.setEnabled(True)
        self._set_state_label(self.STATE_ARMED)
        # Update threshold line
        self._trig_h_line.setValue(self.spin_thresh.value())

    def _disarm(self):
        self._armed           = False
        self._collecting_post = False
        self._state           = self.STATE_IDLE
        self.btn_arm.setEnabled(True)
        self.btn_disarm.setEnabled(False)
        self._set_state_label(self.STATE_IDLE)

    def _force_trigger(self):
        if self._state == self.STATE_ARMED:
            self._do_trigger(self._prev_sample)

    # -- Trigger Engine --------------------------------------------------------

    def _poll_trigger(self):
        """Evaluate the ring buffer for trigger conditions."""
        if not self._armed or self._state == self.STATE_TRIGGERED:
            return

        samples = self._dso_source()
        if not samples:
            return
        
        # We only look at the 'new' samples since last poll
        # In this simple implementation, we just take the last 10 samples
        # and push them into the ring.
        new_data = samples[-10:] if len(samples) >= 10 else samples

        for s in new_data:
            self._ring.append(s)

            if self._state == self.STATE_ARMED:
                # Check for trigger condition
                if self._check_condition(self._prev_sample, s):
                    self._do_trigger(s)
                self._prev_sample = s
            
            elif self._state == self.STATE_WAITING:
                # Collecting post-trigger samples
                self._post_samples_needed -= 1
                if self._post_samples_needed <= 0:
                    self._finalize_capture()
                    break

    def _check_condition(self, prev: float, current: float) -> bool:
        if self._holdoff_remaining > 0:
            self._holdoff_remaining -= 1
            return False

        thresh = self.spin_thresh.value()
        mode   = self.cmb_mode.currentText()
        
        if mode == "Rising Edge":
            return prev < thresh <= current
        elif mode == "Falling Edge":
            return prev > thresh >= current
        elif mode == "Pulse Width":
            # Pulse width tracker: measure time between two crossings
            pw_min = self.spin_pw_min.value()
            pw_max = self.spin_pw_max.value()
            
            # Start of pulse (rising edge)
            if prev < thresh <= current:
                self._pw_start_idx = 0 # reset duration counter
                return False
            
            # End of pulse (falling edge)
            if prev > thresh >= current and self._pw_start_idx >= 0:
                pw = self._pw_start_idx * self.sample_period
                self._pw_start_idx = -1
                return pw_min <= pw <= pw_max
            
            if self._pw_start_idx >= 0:
                self._pw_start_idx += 1
            return False
            
        elif mode == "Runt":
            runt_hi = self.spin_runt.value()
            return prev < thresh <= current and current < runt_hi
        
        return False

    def _do_trigger(self, trig_value: float):
        import datetime
        self._state = self.STATE_WAITING
        self._set_state_label(self.STATE_WAITING)

        self._post_samples_needed = self.spin_post.value()
        self.lbl_trig_val.setText(f"{trig_value:.3f} V")
        self.lbl_trig_t.setText(datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])

        # Holdoff
        holdoff_ms   = self.spin_holdoff.value()
        holdoff_ticks = int(holdoff_ms / (self.sample_period * 1000)) if holdoff_ms > 0 else 0
        self._holdoff_remaining = holdoff_ticks

    def _finalize_capture(self):
        self._state = self.STATE_TRIGGERED
        self._set_state_label(self.STATE_TRIGGERED)
        
        buf = list(self._ring)
        self._capture = np.array(buf, dtype=float)
        self._trig_pos = len(buf) - self.spin_post.value()
        
        self._draw_capture()
        
        if self._single_shot:
            self._disarm()
        else:
            # Auto-rearm
            self._arm()

    # -- Plot helpers ----------------------------------------------------------

    def _draw_capture(self):
        if self._capture is None or len(self._capture) == 0:
            return
        n     = len(self._capture)
        tp    = self._trig_pos
        dt    = self.sample_period
        # Time axis relative to trigger (trigger = t=0)
        t     = (np.arange(n) - tp) * dt

        pre   = self._capture[:tp]
        post  = self._capture[tp:]
        t_pre = t[:tp]
        t_post = t[tp:]

        self._curve_pre.setData(t_pre, pre)
        self._curve_post.setData(t_post, post)
        self._curve_live.setData([], [])

        # Vertical trigger line at t=0
        self._trig_v_line.setValue(0.0)
        # Pre-trigger region
        if len(t_pre) > 0:
            self._pre_region.setRegion([t_pre[0], 0])
        self._plot.enableAutoRange(axis="y", enable=True)

    def _update_live_plot(self):
        """Show rolling waveform when not triggered."""
        if self._state in (self.STATE_TRIGGERED,):
            return
        buf = list(self._ring)
        if not buf:
            return
        n = len(buf)
        t = (np.arange(n) - (n - 1)) * self.sample_period
        self._curve_live.setData(t, np.array(buf))

    def _set_state_label(self, state: str):
        colors = {
            self.STATE_IDLE:      T.TEXT_MUTED,
            self.STATE_ARMED:     T.ACCENT_BLUE,
            self.STATE_WAITING:   T.ACCENT_AMBER,
            self.STATE_TRIGGERED: T.ACCENT_RED,
        }
        col = colors.get(state, T.TEXT_MUTED)
        self.lbl_state.setText(state)
        self.lbl_state.setStyleSheet(
            f"color: {col}; font-size: {SZ_STAT}px; font-weight: 700; "
            f"font-family: {T.FONT_MONO}; background: transparent; border: none;"
        )
