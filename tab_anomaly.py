"""
tab_anomaly.py - AI Anomaly Detector for STM32 Lab GUI v6.0

Trains a small offline model on "normal" waveform segments and flags
deviations in real time with a colour-coded anomaly score overlay.

Model: IsolationForest (scikit-learn) with sliding-window features.
Fallback: 3-sigma Gaussian model if sklearn is not installed.
No cloud, no internet required.

WHY: Predictive maintenance, quality control, fault detection.
     Nobody has done this on a Bluepill capture pipeline. Publishable.
"""

import datetime
import math
from collections import deque
from typing import Callable, List, Optional

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox,
    QGroupBox, QSplitter, QProgressBar, QCheckBox, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header

try:
    from sklearn.ensemble import IsolationForest
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


# -- Feature extractor (sliding window) ---------------------------------------

def _make_features(samples: np.ndarray, window: int = 32) -> np.ndarray:
    """
    Extract statistical features from sliding windows.
    Returns (n_windows, 5) array.
    """
    n = len(samples)
    rows = []
    step = max(1, window // 4)
    for i in range(0, n - window, step):
        seg  = samples[i:i+window]
        mean = float(np.mean(seg))
        std  = float(np.std(seg))
        rms  = float(np.sqrt(np.mean(seg**2)))
        vpp  = float(np.max(seg) - np.min(seg))
        mag  = np.abs(np.fft.rfft(seg - mean))
        dom  = float(mag[1:].max()) if len(mag) > 1 else 0.0
        rows.append([mean, std, rms, vpp, dom])
    return np.array(rows, dtype=float) if rows else np.zeros((1, 5))


class _GaussianDetector:
    """Fallback 3-sigma Gaussian anomaly detector."""
    def __init__(self):
        self._mu  = None
        self._sig = None

    def fit(self, X: np.ndarray):
        self._mu  = np.mean(X, axis=0)
        self._sig = np.std(X, axis=0) + 1e-9

    def score_samples(self, X: np.ndarray) -> np.ndarray:
        # Returns negative z-score max (lower = more anomalous, like IsolationForest)
        z = np.abs((X - self._mu) / self._sig)
        return -z.max(axis=1)

    def predict(self, X: np.ndarray) -> np.ndarray:
        # 1 = normal, -1 = anomaly (matches sklearn API)
        scores = self.score_samples(X)
        return np.where(scores < -3.0, -1, 1)


# -- Anomaly Detector Tab -----------------------------------------------------

class AnomalyDetectorTab(QWidget):
    """Real-time AI anomaly detection on captured waveforms."""

    MODEL_BACKEND = "IsolationForest" if HAS_SKLEARN else "3-sigma Gaussian"

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._model = None
        self._trained = False
        self._score_history: deque = deque(maxlen=500)
        self._anomaly_regions: List = []

        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(200)   # 5 Hz scoring
        self._refresh_timer.timeout.connect(self._score_live)
        self._event_count = 0   # BUG-FIX: initialize before first score_live call

        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("AI Anomaly Detector")
        self._header_strip = hdr

        self.btn_train = QPushButton("TRAIN on current buffer")
        self.btn_train.setObjectName("btn_warning")
        self.btn_train.setFixedWidth(210)
        self.btn_train.clicked.connect(self._train)
        hdr_lay.addWidget(self.btn_train)

        self.btn_monitor = QPushButton("> MONITOR")
        self.btn_monitor.setFixedWidth(130)
        self.btn_monitor.setEnabled(False)
        self.btn_monitor.clicked.connect(self._toggle_monitor)
        hdr_lay.addWidget(self.btn_monitor)

        self.btn_reset = QPushButton("RESET MODEL")
        self.btn_reset.setObjectName("btn_disconnect")
        self.btn_reset.setFixedWidth(130)
        self.btn_reset.clicked.connect(self._reset)
        hdr_lay.addWidget(self.btn_reset)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: settings ----------------------------------------------------
        ctrl_w = QWidget()
        ctrl_w.setMaximumWidth(260)
        c_lay = QVBoxLayout(ctrl_w)
        c_lay.setContentsMargins(14, 14, 14, 14)
        c_lay.setSpacing(12)

        model_grp = QGroupBox("MODEL SETTINGS")
        mg_lay = QVBoxLayout(model_grp)
        mg_lay.setSpacing(8)
        mg_lay.setContentsMargins(12, 22, 12, 12)
        c_lay.addWidget(model_grp)

        def _row(label, widget):
            r = QHBoxLayout()
            r.addWidget(ThemeLabel(label, "TEXT_MUTED", SZ_SM, bold=True))
            r.addWidget(widget)
            mg_lay.addLayout(r)

        self.spin_win = QSpinBox()
        self.spin_win.setRange(8, 256)
        self.spin_win.setValue(32)
        self.spin_win.setSuffix(" samples")
        _row("Window:", self.spin_win)

        self.spin_contam = QDoubleSpinBox()
        self.spin_contam.setRange(0.001, 0.5)
        self.spin_contam.setValue(0.05)
        self.spin_contam.setDecimals(3)
        self.spin_contam.setSuffix(" (contamination)")
        _row("Contam:", self.spin_contam)

        self.spin_thresh = QDoubleSpinBox()
        self.spin_thresh.setRange(0.01, 1.0)
        self.spin_thresh.setValue(0.5)
        self.spin_thresh.setDecimals(2)
        self.spin_thresh.setSuffix(" (score threshold)")
        _row("Threshold:", self.spin_thresh)

        mg_lay.addWidget(ThemeLabel(
            f"Backend: {self.MODEL_BACKEND}", "TEXT_MUTED", SZ_SM))
        if not HAS_SKLEARN:
            mg_lay.addWidget(ThemeLabel(
                "pip install scikit-learn for IsolationForest",
                "ACCENT_AMBER", SZ_SM))

        # Stat cards
        self.lbl_status  = QLabel("Not trained")
        self.lbl_score   = QLabel("-")
        self.lbl_events  = QLabel("0")
        self._stat_cards = [
            ThemeCard("MODEL STATUS",  self.lbl_status,  "TEXT_MUTED"),
            ThemeCard("ANOMALY SCORE", self.lbl_score,   "ACCENT_RED"),
            ThemeCard("EVENTS",        self.lbl_events,  "ACCENT_AMBER"),
        ]
        for card in self._stat_cards:
            c_lay.addWidget(card)
        c_lay.addStretch()
        splitter.addWidget(ctrl_w)

        # -- RIGHT: waveform + score plots -------------------------------------
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(6)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)

        # Waveform plot
        self._wave_plot = pg.PlotWidget()
        self._wave_plot.setLabel("left",   "Voltage (V)", color=T.TEXT_MUTED)
        self._wave_plot.setLabel("bottom", "Sample",      color=T.TEXT_MUTED)
        self._wave_plot.showGrid(x=True, y=True, alpha=0.12)
        self._wave_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._wave_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._wave_curve = self._wave_plot.plot(
            pen=pg.mkPen(T.ACCENT_BLUE, width=2))
        r_lay.addWidget(self._wave_plot, stretch=2)

        # Score plot
        self._score_plot = pg.PlotWidget()
        self._score_plot.setLabel("left",   "Anomaly Score", color=T.TEXT_MUTED)
        self._score_plot.setLabel("bottom", "Sample",        color=T.TEXT_MUTED)
        self._score_plot.showGrid(x=True, y=True, alpha=0.12)
        self._score_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._score_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._score_plot.setYRange(0, 1)
        self._score_plot.addLine(
            y=0.5, pen=pg.mkPen(T.ACCENT_RED, width=1, style=Qt.DashLine))
        self._score_curve = self._score_plot.plot(
            pen=pg.mkPen(T.ACCENT_AMBER, width=2))
        self._threshold_line = pg.InfiniteLine(
            angle=0, movable=True,
            pen=pg.mkPen(T.ACCENT_RED, width=1, style=Qt.DashLine),
            label="Threshold {value:.2f}")
        self._threshold_line.setValue(0.5)
        self._score_plot.addItem(self._threshold_line)
        r_lay.addWidget(self._score_plot, stretch=1)

        splitter.addWidget(right_w)
        splitter.setSizes([240, 900])

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        for card in self._stat_cards:
            card.update_theme()
        for p in (self._wave_plot, self._score_plot):
            p.setBackground(T.DARK_BG)
            p.getAxis("left").setTextPen(T.TEXT_MUTED)
            p.getAxis("bottom").setTextPen(T.TEXT_MUTED)

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    # -- Training --------------------------------------------------------------

    def _train(self):
        raw = self._dso_source()
        if len(raw) < self.spin_win.value() * 2:
            QMessageBox.information(self, "Insufficient Data",
                "Need at least 2.0x window size samples in the DSO buffer.")
            return
        arr  = np.array(raw, dtype=float)
        X    = _make_features(arr, self.spin_win.value())
        cont = self.spin_contam.value()
        if HAS_SKLEARN:
            self._model = IsolationForest(
                n_estimators=100,
                contamination=cont,
                random_state=42
            )
        else:
            self._model = _GaussianDetector()
        self._model.fit(X)
        self._trained = True
        self._event_count = 0
        self.lbl_status.setText("TRAINED")
        self.lbl_status.setStyleSheet(
            f"color: {T.PRIMARY}; font-size: {SZ_STAT}px; font-weight: 700; "
            f"font-family: {T.FONT_MONO}; background: transparent; border: none;")
        self.btn_monitor.setEnabled(True)
        self._score_history.clear()

    def _reset(self):
        self._trained = False
        self._model   = None
        self._refresh_timer.stop()
        self.btn_monitor.setText("> MONITOR")
        self.btn_monitor.setEnabled(False)
        self.lbl_status.setText("Not trained")
        self.lbl_score.setText("-")
        self.lbl_events.setText("0")
        self._score_history.clear()
        self._score_curve.setData([], [])

    def _toggle_monitor(self):
        if self._refresh_timer.isActive():
            self._refresh_timer.stop()
            self.btn_monitor.setText("> MONITOR")
        else:
            self._refresh_timer.start()
            self.btn_monitor.setText("|| PAUSE")

    # -- Live scoring ----------------------------------------------------------

    def _score_live(self):
        if not self._trained or self._model is None:
            return
        raw = self._dso_source()
        if len(raw) < self.spin_win.value():
            return

        arr  = np.array(raw, dtype=float)
        X    = _make_features(arr, self.spin_win.value())

        # Normalise score to [0, 1] (IsolationForest gives negative scores)
        raw_scores = self._model.score_samples(X)
        s_min, s_max = raw_scores.min(), raw_scores.max()
        norm = (raw_scores - s_min) / (s_max - s_min + 1e-9)
        # Invert: higher value = more anomalous
        norm = 1.0 - norm

        latest_score = float(norm[-1])
        self._score_history.append(latest_score)

        thresh = self.spin_thresh.value()
        self._threshold_line.setValue(thresh)

        is_anomaly = latest_score > thresh
        if is_anomaly:
            if not hasattr(self, "_event_count"):
                self._event_count = 0
            self._event_count += 1
            self.lbl_events.setText(str(self._event_count))
            self.lbl_score.setStyleSheet(
                f"color: {T.ACCENT_RED}; font-size: {SZ_STAT}px; "
                f"font-weight: 700; font-family: {T.FONT_MONO}; "
                f"background: transparent; border: none;")
        else:
            self.lbl_score.setStyleSheet(
                f"color: {T.PRIMARY}; font-size: {SZ_STAT}px; "
                f"font-weight: 700; font-family: {T.FONT_MONO}; "
                f"background: transparent; border: none;")
        self.lbl_score.setText(f"{latest_score:.3f}")

        # Update plots
        self._wave_curve.setData(np.arange(len(arr)), arr)
        scores_arr = np.array(self._score_history, dtype=float)
        self._score_curve.setData(np.arange(len(scores_arr)), scores_arr)
