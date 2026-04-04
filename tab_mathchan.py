"""
tab_mathchan.py - Differential / Math Channels for STM32 Lab GUI v6.0

Roadmap item #14: Differential / Math Channels.
  * Virtual channels defined by Python expressions on the DSO buffer:
      CH2 = -CH1          (inverted)
      CH2 = CH1 - mean    (AC coupled)
      CH3 = cumsum(CH1)   (integrator)
      CH3 = diff(CH1)     (differentiator)
      CH3 = abs(CH1)      (rectifier)
      CH3 = CH1 * sin(2*pi*50*t)  (mixer / demodulator)
   Up to 4 independent math channels rendered as dotted overlay curves
   Independent per-channel gain/offset trim
   Expression namespace: CH1, t, pi, sin, cos, abs, sqrt, cumsum, diff, np
   Clear syntax error reporting in the UI

WHY: Differential signals (RS-485, LVDS) and computed channels (power,
     demodulation, integration) are fundamental in every electronics lab.
"""

import math
import traceback
from typing import Callable, List, Optional

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QDoubleSpinBox,
    QGroupBox, QSplitter, QCheckBox, QComboBox,
    QColorDialog, QMessageBox, QFrame
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header


# -- Safe eval namespace ------------------------------------------------------

def _make_namespace(CH1: np.ndarray, sample_period: float) -> dict:
    n = len(CH1)
    t = np.arange(n) * sample_period
    return {
        "CH1":    CH1,
        "t":      t,
        "n":      n,
        "pi":     math.pi,
        "e":      math.e,
        "np":     np,
        "sin":    np.sin,
        "cos":    np.cos,
        "tan":    np.tan,
        "exp":    np.exp,
        "log":    np.log,
        "log10":  np.log10,
        "sqrt":   np.sqrt,
        "abs":    np.abs,
        "cumsum": np.cumsum,
        "diff":   lambda x: np.diff(x, prepend=x[0]),
        "sign":   np.sign,
        "clip":   np.clip,
        "fft_mag":lambda x: np.abs(np.fft.rfft(x - np.mean(x))),
        "mean":   np.mean,
        "std":    np.std,
        "max":    np.max,
        "min":    np.min,
        "zeros":  np.zeros,
        "ones":   np.ones,
        "linspace": np.linspace,
    }


# -- Math Channel definition --------------------------------------------------

class MathChannel:
    COLORS = [T.ACCENT_AMBER, T.ACCENT_PUR, T.PRIMARY, T.ACCENT_CYAN]

    def __init__(self, index: int):
        self.index   = index
        self.name    = f"M{index+1}"
        self.expr    = ""
        self.gain    = 1.0
        self.offset  = 0.0
        self.enabled = False
        self.color   = self.COLORS[index % len(self.COLORS)]
        self._last_error = ""

    def compute(self, ns: dict) -> Optional[np.ndarray]:
        if not self.expr.strip() or not self.enabled:
            return None
        try:
            result = eval(self.expr, {"__builtins__": {}}, ns)
            arr = np.asarray(result, dtype=float).ravel()
            if len(arr) != len(ns["CH1"]):
                # Resize if expression returns different length (e.g. fft_mag)
                arr = np.interp(np.arange(len(ns["CH1"])),
                                np.linspace(0, len(arr)-1, len(arr)), arr)
            self._last_error = ""
            return arr * self.gain + self.offset
        except Exception as ex:
            self._last_error = str(ex)
            return None

    @property
    def last_error(self) -> str:
        return self._last_error


# -- Math Channels Tab --------------------------------------------------------

class MathChannelsTab(QWidget):
    """Differential / Math virtual channels for DSO data."""

    NUM_CHANNELS  = 4

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._channels: List[MathChannel] = [MathChannel(i) for i in range(self.NUM_CHANNELS)]
        self._plot_curves: List = []
        self.sample_period = 0.010  # default

        # Preset expressions
        self._presets = {
            "Invert":        "-CH1",
            "AC couple":     "CH1 - mean(CH1)",
            "Rectify":       "abs(CH1)",
            "Integrate Int":   "cumsum(CH1) * {dt}",
            "Differentiate": "diff(CH1) / {dt}",
            "Half-wave rect":"clip(CH1, 0, None)",
            "RMS envelope":  "sqrt(CH1**2)",
            "50Hz mix":      "CH1 * sin(2*pi*50*t)",
        }

        self._timer = QTimer()
        self._timer.setInterval(50)   # 20 Hz refresh
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Math / Differential Channels")
        self._header_strip = hdr

        self.btn_clear = QPushButton("CLEAR ALL")
        self.btn_clear.setObjectName("btn_disconnect")
        self.btn_clear.setFixedWidth(120)
        self.btn_clear.clicked.connect(self._clear_all)
        hdr_lay.addWidget(self.btn_clear)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        #  LEFT: channel config 
        left_w = QWidget()
        left_w.setMinimumWidth(350)
        left_w.setMaximumWidth(440)
        l_lay = QVBoxLayout(left_w)
        l_lay.setContentsMargins(12, 12, 12, 12)
        l_lay.setSpacing(10)

        # Channel rows
        self._chan_widgets = []
        for ch in self._channels:
            row_w = self._make_channel_row(ch)
            l_lay.addWidget(row_w)

        # Presets
        pre_grp = QGroupBox("EXPRESSION PRESETS")
        pg_lay = QHBoxLayout(pre_grp)
        pg_lay.setContentsMargins(10, 22, 10, 10)
        pg_lay.setSpacing(6)
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(["- select preset -"] + list(self._presets.keys()))
        pg_lay.addWidget(self.cmb_preset, stretch=1)
        btn_apply = QPushButton("APPLY TO M1")
        btn_apply.setFixedWidth(130)
        btn_apply.clicked.connect(self._apply_preset_m1)
        pg_lay.addWidget(btn_apply)
        l_lay.addWidget(pre_grp)

        # Namespace reference
        ref_grp = QGroupBox("EXPRESSION NAMESPACE")
        rl = QVBoxLayout(ref_grp)
        rl.setContentsMargins(12, 22, 12, 10)
        ref_text = (
            "CH1     - raw DSO buffer (ndarray)\n"
            "t       - time axis (seconds)\n"
            "n       - number of samples\n"
            "sin, cos, tan, exp, log, sqrt\n"
            "abs, cumsum, diff, clip, sign\n"
            "mean, std, min, max\n"
            "fft_mag(x) - magnitude spectrum\n"
            "np      - full numpy module\n"
            "pi, e   - mathematical constants"
        )
        ref_lbl = QLabel(ref_text)
        ref_lbl.setFont(_ui_font(SZ_SM))
        ref_lbl.setStyleSheet(
            f"color: {T.TEXT_MUTED}; background: {T.CARD_BG}; "
            f"padding: 8px; border: 1px solid {T.BORDER};")
        rl.addWidget(ref_lbl)
        l_lay.addWidget(ref_grp)
        l_lay.addStretch()
        splitter.addWidget(left_w)

        #  RIGHT: plot 
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(4)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left",   "Amplitude (V / computed)", color=T.TEXT_MUTED)
        self._plot.setLabel("bottom", "Sample",                   color=T.TEXT_MUTED)
        self._plot.showGrid(x=True, y=True, alpha=0.14)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

        # CH1 (raw) in cyan
        self._ch1_curve = self._plot.plot(
            pen=pg.mkPen(T.ACCENT_BLUE, width=1.5),
            name="CH1 (raw)")

        # One curve per math channel
        line_styles = [Qt.DashLine, Qt.DotLine, Qt.DashDotLine, Qt.DashDotDotLine]
        self._plot_curves = []
        for i, ch in enumerate(self._channels):
            c = self._plot.plot(
                pen=pg.mkPen(ch.color, width=2, style=line_styles[i]),
                name=ch.name)
            self._plot_curves.append(c)

        # Legend
        self._plot.addLegend(offset=(10, 10))

        r_lay.addWidget(self._plot, stretch=1)

        # Error strip
        self._err_lbl = QLabel("")
        self._err_lbl.setFont(_ui_font(SZ_SM))
        self._err_lbl.setStyleSheet(
            f"color: {T.ACCENT_RED}; background: transparent; border: none; padding: 4px;")
        r_lay.addWidget(self._err_lbl)

        splitter.addWidget(right_w)
        splitter.setSizes([400, 900])

    def _make_channel_row(self, ch: MathChannel) -> QGroupBox:
        grp = QGroupBox(f"MATH CHANNEL M{ch.index+1}")
        lay = QGridLayout(grp)
        lay.setContentsMargins(10, 22, 10, 10)
        lay.setSpacing(6)

        # Enable checkbox
        chk = QCheckBox("Enable")
        chk.setChecked(ch.enabled)
        chk.stateChanged.connect(lambda state, c=ch: setattr(c, "enabled", state == Qt.Checked))
        lay.addWidget(chk, 0, 0)

        # Colour button
        col_btn = QPushButton(" ")
        col_btn.setFixedWidth(32)
        col_btn.setFixedHeight(22)
        col_btn.setStyleSheet(f"background: {ch.color}; border: none;")
        def _pick_color(_, c=ch, b=col_btn):
            qc = QColorDialog.getColor(QColor(c.color), self, "Pick channel color")
            if qc.isValid():
                c.color = qc.name()
                b.setStyleSheet(f"background: {c.color}; border: none;")
        col_btn.clicked.connect(_pick_color)
        lay.addWidget(col_btn, 0, 1)

        # Expression input
        expr_lbl = QLabel("Expr (f(CH1)):")
        expr_lbl.setFont(_ui_font(SZ_SM))
        expr_lbl.setStyleSheet(f"color: {T.TEXT_MUTED}; background: transparent; border: none;")
        expr_inp = QLineEdit()
        expr_inp.setFont(_ui_font(SZ_BODY))
        expr_inp.setPlaceholderText(f"e.g.  -CH1   or  CH1 - mean(CH1)")
        expr_inp.setText(ch.expr)
        expr_inp.textChanged.connect(lambda text, c=ch: setattr(c, "expr", text))
        lay.addWidget(expr_lbl, 1, 0)
        lay.addWidget(expr_inp, 1, 1, 1, 3)

        # Gain / Offset trims
        gain_lbl = QLabel("Gain:")
        gain_lbl.setFont(_ui_font(SZ_SM))
        gain_lbl.setStyleSheet(f"color: {T.TEXT_MUTED}; background: transparent; border: none;")
        gain_spin = QDoubleSpinBox()
        gain_spin.setRange(-1000.0, 1000.0)
        gain_spin.setValue(ch.gain)
        gain_spin.setDecimals(3)
        gain_spin.setSuffix("x")
        gain_spin.valueChanged.connect(lambda v, c=ch: setattr(c, "gain", v))

        off_lbl = QLabel("Offset:")
        off_lbl.setFont(_ui_font(SZ_SM))
        off_lbl.setStyleSheet(f"color: {T.TEXT_MUTED}; background: transparent; border: none;")
        off_spin = QDoubleSpinBox()
        off_spin.setRange(-1000.0, 1000.0)
        off_spin.setValue(ch.offset)
        off_spin.setDecimals(3)
        off_spin.setSuffix(" V")
        off_spin.valueChanged.connect(lambda v, c=ch: setattr(c, "offset", v))

        lay.addWidget(gain_lbl,  2, 0)
        lay.addWidget(gain_spin, 2, 1)
        lay.addWidget(off_lbl,   2, 2)
        lay.addWidget(off_spin,  2, 3)

        self._chan_widgets.append({
            "chk": chk, "expr": expr_inp,
            "gain": gain_spin, "offset": off_spin,
        })
        return grp

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        self._plot.setBackground(T.DARK_BG)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    # -- Actions ---------------------------------------------------------------

    def _clear_all(self):
        for ch, w in zip(self._channels, self._chan_widgets):
            ch.expr    = ""
            ch.enabled = False
            w["expr"].setText("")
            w["chk"].setChecked(False)
        for c in self._plot_curves:
            c.setData([], [])

    def _apply_preset_m1(self):
        key = self.cmb_preset.currentText()
        if key in self._presets:
            expr = self._presets[key].format(dt=self.sample_period)
            self._channels[0].expr = expr
            self._chan_widgets[0]["expr"].setText(expr)
            self._channels[0].enabled = True
            self._chan_widgets[0]["chk"].setChecked(True)

    # -- Refresh ---------------------------------------------------------------

    def _refresh(self):
        raw = self._dso_source()
        if len(raw) < 4:
            return
        arr = np.array(raw, dtype=float)
        xs  = np.arange(len(arr))

        # Plot raw CH1
        self._ch1_curve.setData(xs, arr)

        # Build eval namespace
        ns = _make_namespace(arr, self.sample_period)

        errors = []
        for i, (ch, curve) in enumerate(zip(self._channels, self._plot_curves)):
            if not ch.enabled:
                curve.setData([], [])
                continue
            result = ch.compute(ns)
            if result is not None:
                # Update curve colour (may have been changed)
                curve.setPen(pg.mkPen(ch.color, width=2))
                curve.setData(xs, result)
            else:
                curve.setData([], [])
                if ch.last_error:
                    errors.append(f"M{ch.index+1}: {ch.last_error}")

        self._err_lbl.setText("  [WARNING]  " + "  |  ".join(errors) if errors else "")
