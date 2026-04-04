"""
tab_bode.py - Impedance Analyser / Bode Plot tab for STM32 Lab GUI v6.0

HOW IT WORKS
------------
1. User sets start/stop frequency, steps/decade, dwell time.
2. "START SWEEP" builds a log-spaced frequency list.
3. A QTimer fires every dwell_ms ms:
   - Sends #WAVE:F={freq}; to the function generator.
   - Waits one more dwell period for the DSO buffer to settle.
   - Reads the DSO buffer snapshot (injected via set_dso_source()).
   - Computes gain (dB) and phase () via FFT cross-correlation with
     a synthetic reference at the same frequency.
4. Results are plotted live and can be exported as CSV.
"""

import csv
import datetime
import math
from typing import Optional, List, Callable

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox,
    QComboBox, QGroupBox, QProgressBar, QSplitter,
    QFileDialog, QMessageBox, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from themes  import T
from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget
from data_engine import CommandBuilder


class BodePlotTab(QWidget):
    """Impedance Analyser / Bode Plot Generator."""

    send_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._stat_cards:   List[ThemeCard]        = []
        self.sample_period = 0.010 # default

        # DSO data source injected by MainWindow
        self._dso_source: Callable[[], list] = lambda: []

        # Sweep state
        self._freqs:     List[float] = []
        self._gains_db:  List[float] = []
        self._phases_deg: List[float] = []
        self._sweep_idx  = 0
        self._sweeping   = False
        self._settle_phase = False   # True = waiting for settle; False = sampling

        self._sweep_timer = QTimer()
        self._sweep_timer.setSingleShot(True)
        self._sweep_timer.timeout.connect(self._sweep_step)

        self._build_ui()

    # -- UI Build -------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Impedance Analyser / Bode Plot")
        self._header_strip = hdr

        self.btn_sweep = QPushButton("> START SWEEP")
        self.btn_sweep.setFixedWidth(160)
        self.btn_sweep.clicked.connect(self._start_sweep)
        hdr_lay.addWidget(self.btn_sweep)

        self.btn_stop = QPushButton("[ ] STOP")
        self.btn_stop.setObjectName("btn_disconnect")
        self.btn_stop.setFixedWidth(100)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_sweep)
        hdr_lay.addWidget(self.btn_stop)

        self.local_logger = LocalLoggerWidget("bode_sweep", ["timestamp", "frequency_hz", "gain_db", "phase_deg"])
        hdr_lay.addStretch()
        hdr_lay.addWidget(self.local_logger)

        root.addWidget(hdr)

        # -- Main splitter: left params / right plots --------------------------
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: parameter panel ---------------------------------------------
        params_w = QWidget()
        params_w.setMaximumWidth(280)
        p_lay = QVBoxLayout(params_w)
        p_lay.setContentsMargins(14, 14, 14, 14)
        p_lay.setSpacing(12)

        sweep_grp = QGroupBox("SWEEP PARAMETERS")
        sg_lay    = QGridLayout(sweep_grp)
        sg_lay.setSpacing(8)
        sg_lay.setContentsMargins(12, 22, 12, 12)
        p_lay.addWidget(sweep_grp)

        def _add_row(label, widget, row):
            sg_lay.addWidget(ThemeLabel(label, "TEXT_MUTED", SZ_SM, bold=True), row, 0)
            sg_lay.addWidget(widget, row, 1)

        self.spin_f_start = QDoubleSpinBox()
        self.spin_f_start.setRange(1, 50000)
        self.spin_f_start.setValue(10)
        self.spin_f_start.setSuffix(" Hz")
        self.spin_f_start.setDecimals(0)
        _add_row("Start Freq", self.spin_f_start, 0)

        self.spin_f_stop = QDoubleSpinBox()
        self.spin_f_stop.setRange(1, 100000)
        self.spin_f_stop.setValue(1000)
        self.spin_f_stop.setSuffix(" Hz")
        self.spin_f_stop.setDecimals(0)
        _add_row("Stop Freq", self.spin_f_stop, 1)

        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(3, 50)
        self.spin_steps.setValue(10)
        self.spin_steps.setSuffix(" /decade")
        _add_row("Steps", self.spin_steps, 2)

        self.spin_dwell = QSpinBox()
        self.spin_dwell.setRange(50, 5000)
        self.spin_dwell.setValue(200)
        self.spin_dwell.setSuffix(" ms")
        _add_row("Dwell", self.spin_dwell, 3)

        self.spin_vin = QDoubleSpinBox()
        self.spin_vin.setRange(0.01, 24.0)
        self.spin_vin.setValue(3.3)
        self.spin_vin.setSuffix(" V (ref)")
        self.spin_vin.setDecimals(2)
        _add_row("V_in (ref)", self.spin_vin, 4)

        # progress
        self.progress = QProgressBar()
        self.progress.setValue(0)
        p_lay.addWidget(self.progress)

        # stat cards
        self.lbl_cur_freq  = QLabel("-")
        self.lbl_cur_gain  = QLabel("-")
        self.lbl_cur_phase = QLabel("-")
        card_f = ThemeCard("FREQ (Hz)",  self.lbl_cur_freq,  "ACCENT_BLUE")
        card_g = ThemeCard("GAIN (dB)",  self.lbl_cur_gain,  "PRIMARY")
        card_p = ThemeCard("PHASE (deg)",  self.lbl_cur_phase, "ACCENT_AMBER")
        self._stat_cards = [card_f, card_g, card_p]
        p_lay.addWidget(card_f)
        p_lay.addWidget(card_g)
        p_lay.addWidget(card_p)

        self.lbl_status = ThemeLabel("Idle", "TEXT_MUTED", SZ_BODY)
        p_lay.addWidget(self.lbl_status)
        p_lay.addStretch()
        splitter.addWidget(params_w)

        # -- RIGHT: two stacked plots ------------------------------------------
        plots_w = QWidget()
        pl_lay  = QVBoxLayout(plots_w)
        pl_lay.setContentsMargins(8, 8, 8, 8)
        pl_lay.setSpacing(4)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)

        # Gain plot
        self._gain_plot = pg.PlotWidget()
        self._gain_plot.setLabel("left",   "Gain (dB)",    color=T.TEXT_MUTED)
        self._gain_plot.setLabel("bottom", "Frequency (Hz)", color=T.TEXT_MUTED)
        self._gain_plot.setLogMode(x=True, y=False)
        self._gain_plot.showGrid(x=True, y=True, alpha=0.15)
        self._gain_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._gain_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._gain_plot.addLine(y=0,
            pen=pg.mkPen(T.TEXT_DIM, width=1, style=Qt.DashLine))  # 0 dB ref
        self._gain_curve = self._gain_plot.plot(
            pen=pg.mkPen(T.PRIMARY, width=2),
            symbol="o", symbolSize=5, symbolBrush=T.PRIMARY)
        pl_lay.addWidget(self._gain_plot, stretch=1)

        # Phase plot
        self._phase_plot = pg.PlotWidget()
        self._phase_plot.setLabel("left",   "Phase (deg)",    color=T.TEXT_MUTED)
        self._phase_plot.setLabel("bottom", "Frequency (Hz)", color=T.TEXT_MUTED)
        self._phase_plot.setLogMode(x=True, y=False)
        self._phase_plot.showGrid(x=True, y=True, alpha=0.15)
        self._phase_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._phase_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._phase_plot.setYRange(-180, 180)
        # +/- 90 deg guide lines
        for deg in (-90, 0, 90):
            self._phase_plot.addLine(y=deg,
                pen=pg.mkPen(T.TEXT_DIM, width=1, style=Qt.DashLine))
        self._phase_curve = self._phase_plot.plot(
            pen=pg.mkPen(T.ACCENT_AMBER, width=2),
            symbol="o", symbolSize=5, symbolBrush=T.ACCENT_AMBER)
        pl_lay.addWidget(self._phase_plot, stretch=1)

        splitter.addWidget(plots_w)
        splitter.setSizes([260, 800])

    # -- Public API -----------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        """Inject a callable that returns the current DSO buffer snapshot."""
        self._dso_source = fn

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        if getattr(self, "local_logger", None):
            self.local_logger.update_theme()
        for card in self._stat_cards:
            card.update_theme()
        for plot in (self._gain_plot, self._phase_plot):
            plot.setBackground(T.DARK_BG)
            plot.getAxis("left").setTextPen(T.TEXT_MUTED)
            plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

    # -- Sweep Engine ---------------------------------------------------------

    def _build_freq_list(self) -> List[float]:
        f_start  = self.spin_f_start.value()
        f_stop   = self.spin_f_stop.value()
        steps    = self.spin_steps.value()
        n_decades = math.log10(f_stop / f_start) if f_stop > f_start else 1
        n_points  = max(3, int(round(n_decades * steps)))
        return list(np.logspace(math.log10(f_start), math.log10(f_stop), n_points))

    def _start_sweep(self):
        self._freqs       = self._build_freq_list()
        self._gains_db    = []
        self._phases_deg  = []
        self._sweep_idx   = 0
        self._sweeping    = True
        self._settle_phase = False

        self.progress.setMaximum(len(self._freqs))
        self.progress.setValue(0)
        self.btn_sweep.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._gain_curve.setData([], [])
        self._phase_curve.setData([], [])

        self.lbl_status.setText(f"Sweeping 0 / {len(self._freqs)}")
        self._sweep_timer.start(50)   # kick off immediately

    def _stop_sweep(self):
        self._sweeping = False
        self._sweep_timer.stop()
        self.btn_sweep.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Stopped")

    def _sweep_step(self):
        if not self._sweeping or self._sweep_idx >= len(self._freqs):
            self._finish_sweep()
            return

        freq     = self._freqs[self._sweep_idx]
        dwell_ms = self.spin_dwell.value()

        if not self._settle_phase:
            # Send frequency command and schedule a settle wait
            self.send_requested.emit(CommandBuilder.wave_freq(int(round(freq))))
            self._settle_phase = True
            self._sweep_timer.start(dwell_ms)
        else:
            # Settle done  sample and compute
            self._settle_phase = False
            gain_db, phase_deg = self._compute_bode(freq)
            self._gains_db.append(gain_db)
            self._phases_deg.append(phase_deg)

            if getattr(self, "local_logger", None):
                self.local_logger.log({
                    "frequency_hz": freq,
                    "gain_db": gain_db,
                    "phase_deg": phase_deg
                })

            # Update stat cards
            self.lbl_cur_freq.setText(f"{freq:.1f}")
            self.lbl_cur_gain.setText(f"{gain_db:.2f}")
            self.lbl_cur_phase.setText(f"{phase_deg:.1f}")

            # Update plots
            f_arr = np.array(self._freqs[:len(self._gains_db)])
            self._gain_curve.setData(f_arr, np.array(self._gains_db))
            self._phase_curve.setData(f_arr, np.array(self._phases_deg))

            self._sweep_idx += 1
            self.progress.setValue(self._sweep_idx)
            self.lbl_status.setText(f"Sweeping {self._sweep_idx} / {len(self._freqs)}")
            self._sweep_timer.start(10)   # small gap between points

    def _compute_bode(self, freq: float):
        """Compute gain (dB) and phase (deg) from DSO buffer vs reference."""
        samples  = self._dso_source()
        v_in_ref = self.spin_vin.value()

        if len(samples) < 8:
            return 0.0, 0.0

        y = np.array(samples, dtype=float)
        n = len(y)
        dt = self.sample_period

        # FFT-based approach  find the bin closest to freq
        freqs = np.fft.rfftfreq(n, d=dt)
        Y     = np.fft.rfft(y)

        if len(freqs) < 2:
            return 0.0, 0.0

        # Find nearest bin
        idx = int(np.argmin(np.abs(freqs - freq)))
        if idx == 0:
            idx = 1
        idx = min(idx, len(Y) - 1)

        # Magnitude of output at freq
        v_out_mag = np.abs(Y[idx]) * 2.0 / n   # two-sided  one-sided

        # Gain
        v_out_mag = max(v_out_mag, 1e-9)
        v_in_ref  = max(v_in_ref, 1e-9)
        gain_db   = 20.0 * math.log10(v_out_mag / v_in_ref)

        # Phase relative to a pure-cosine reference at freq
        ref_phase = 0.0   # reference is at 0 deg
        out_phase = math.degrees(np.angle(Y[idx]))
        phase_deg  = out_phase - ref_phase
        # Wrap to [-180, 180]
        while phase_deg >  180: phase_deg -= 360
        while phase_deg < -180: phase_deg += 360

        return gain_db, phase_deg

    def _finish_sweep(self):
        self._sweeping = False
        self.btn_sweep.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText(
            f"Complete - {len(self._gains_db)} points")
