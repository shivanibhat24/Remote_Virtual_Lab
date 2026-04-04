"""
tab_mathchan.py - Differential / Math Channels for STM32 Lab GUI v6.0

Virtual channels from expressions on the DSO buffer (CH1), plus optional
synthesized test signals (sine, square, …) mixed with CH1 for addition,
subtraction, or multiplication. TEST is available in the expression namespace.
"""

import math
from typing import Callable, List, Optional

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QLabel,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QPushButton,
    QLineEdit,
    QDoubleSpinBox,
    QGroupBox,
    QSplitter,
    QCheckBox,
    QComboBox,
    QColorDialog,
    QFrame,
    QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

from themes import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header
from plot_trace_colors import TraceColorBar


def _synthesize_test(shape: str, freq_hz: float, amp: float, t: np.ndarray) -> np.ndarray:
    """Ideal test waveform aligned to time axis t (seconds)."""
    if shape == "none" or amp == 0.0:
        return np.zeros_like(t, dtype=float)
    f = max(float(freq_hz), 1e-9)
    w = 2.0 * math.pi * f * t
    if shape == "sine":
        return float(amp) * np.sin(w)
    if shape == "square":
        return float(amp) * np.sign(np.sin(w))
    if shape == "triangle":
        return float(amp) * (2.0 / math.pi) * np.arcsin(np.sin(w))
    if shape == "sawtooth":
        period = 1.0 / f
        ph = np.mod(t, period) / period
        return float(amp) * (2.0 * ph - 1.0)
    return np.zeros_like(t, dtype=float)


def _make_namespace(CH1: np.ndarray, sample_period: float) -> dict:
    n = len(CH1)
    t = np.arange(n, dtype=float) * float(sample_period)
    return {
        "CH1": CH1,
        "t": t,
        "n": n,
        "pi": math.pi,
        "e": math.e,
        "np": np,
        "sin": np.sin,
        "cos": np.cos,
        "tan": np.tan,
        "exp": np.exp,
        "log": np.log,
        "log10": np.log10,
        "sqrt": np.sqrt,
        "abs": np.abs,
        "cumsum": np.cumsum,
        "diff": lambda x: np.diff(x, prepend=x[0]),
        "sign": np.sign,
        "clip": np.clip,
        "fft_mag": lambda x: np.abs(np.fft.rfft(x - np.mean(x))),
        "mean": np.mean,
        "std": np.std,
        "max": np.max,
        "min": np.min,
        "zeros": np.zeros,
        "ones": np.ones,
        "linspace": np.linspace,
    }


class MathChannel:
    COLORS = [T.ACCENT_AMBER, T.PRIMARY, T.ACCENT_CYAN, T.ACCENT_PUR]

    def __init__(self, index: int):
        self.index = index
        self.name = f"M{index + 1}"
        self.expr = ""
        self.gain = 1.0
        self.offset = 0.0
        self.enabled = False
        self.color = self.COLORS[index % len(self.COLORS)]
        self._last_error = ""
        self.mix_enabled = False
        self.test_shape = "none"
        self.test_freq_hz = 50.0
        self.test_amp_v = 1.0
        self.mix_op = "add"

    def compute(self, ns: dict) -> Optional[np.ndarray]:
        if not self.enabled:
            return None
        t = ns["t"]
        test = _synthesize_test(self.test_shape, self.test_freq_hz, self.test_amp_v, t)
        local = dict(ns)
        local["TEST"] = test

        expr_use = (self.expr or "").strip()
        if self.mix_enabled and self.test_shape != "none":
            if not expr_use:
                if self.mix_op == "add":
                    expr_use = "CH1 + TEST"
                elif self.mix_op == "sub":
                    expr_use = "CH1 - TEST"
                else:
                    expr_use = "CH1 * TEST"
        if not expr_use:
            return None
        try:
            result = eval(expr_use, {"__builtins__": {}}, local)
            arr = np.asarray(result, dtype=float).ravel()
            if len(arr) != len(ns["CH1"]):
                arr = np.interp(
                    np.arange(len(ns["CH1"])),
                    np.linspace(0, max(len(arr) - 1, 1), len(arr)),
                    arr,
                )
            self._last_error = ""
            return arr * self.gain + self.offset
        except Exception as ex:
            self._last_error = str(ex)
            return None

    @property
    def last_error(self) -> str:
        return self._last_error


class MathChannelsTab(QWidget):
    """Differential / Math virtual channels for DSO data."""

    NUM_CHANNELS = 4

    def __init__(self, settings=None):
        super().__init__()
        self._settings = settings
        self._ch1_trace_bar: Optional[TraceColorBar] = None
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._channels: List[MathChannel] = [MathChannel(i) for i in range(self.NUM_CHANNELS)]
        self._plot_curves: List = []
        self.sample_period = 0.010

        self._presets = {
            "Invert": "-CH1",
            "AC couple": "CH1 - mean(CH1)",
            "Rectify": "abs(CH1)",
            "Integrate": "cumsum(CH1) * {dt}",
            "Differentiate": "diff(CH1) / {dt}",
            "Half-wave rect": "clip(CH1, 0, None)",
            "CH1 + TEST (manual)": "CH1 + TEST",
            "CH1 * TEST (ring mod)": "CH1 * TEST",
            "50 Hz mix": "CH1 * sin(2*pi*50*t)",
        }

        self._timer = QTimer()
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        self._build_ui()

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

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QFrame.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_w = QWidget()
        left_w.setMinimumWidth(360)
        left_scroll.setWidget(left_w)
        l_lay = QVBoxLayout(left_w)
        l_lay.setContentsMargins(12, 12, 12, 12)
        l_lay.setSpacing(12)

        hint = QLabel(
            "CH1 = live DSO buffer. Enable a row, optionally mix a synthesized TEST "
            "(sine/square/…) with Add/Sub/Mul — leave expression empty to use CH1±*TEST."
        )
        hint.setWordWrap(True)
        hint.setFont(_ui_font(SZ_SM))
        hint.setStyleSheet(f"color: {T.TEXT_MUTED}; padding: 4px;")
        l_lay.addWidget(hint)

        self._chan_widgets = []
        for ch in self._channels:
            l_lay.addWidget(self._make_channel_row(ch))

        pre_grp = QGroupBox("EXPRESSION PRESETS")
        pg_lay = QHBoxLayout(pre_grp)
        pg_lay.setContentsMargins(10, 22, 10, 10)
        pg_lay.setSpacing(8)
        self.cmb_preset = QComboBox()
        self.cmb_preset.addItems(["- select preset -"] + list(self._presets.keys()))
        pg_lay.addWidget(self.cmb_preset, stretch=1)
        self.cmb_preset_target = QComboBox()
        for i in range(self.NUM_CHANNELS):
            self.cmb_preset_target.addItem(f"M{i + 1}")
        self.cmb_preset_target.setFixedWidth(56)
        pg_lay.addWidget(ThemeLabel("→", "TEXT_MUTED", SZ_SM))
        pg_lay.addWidget(self.cmb_preset_target)
        btn_apply = QPushButton("APPLY")
        btn_apply.setFixedWidth(88)
        btn_apply.clicked.connect(self._apply_preset_selected)
        pg_lay.addWidget(btn_apply)
        l_lay.addWidget(pre_grp)

        ref_grp = QGroupBox("NAMESPACE")
        rl = QVBoxLayout(ref_grp)
        rl.setContentsMargins(12, 22, 12, 10)
        ref_text = (
            "CH1, TEST — arrays (V vs time); t — seconds; n — length\n"
            "sin, cos, cumsum, diff, mean, abs, clip, np …"
        )
        ref_lbl = QLabel(ref_text)
        ref_lbl.setFont(_ui_font(SZ_SM))
        ref_lbl.setStyleSheet(
            f"color: {T.TEXT_MUTED}; background: {T.CARD_BG}; "
            f"padding: 10px; border: 1px solid {T.BORDER}; border-radius: 4px;"
        )
        ref_lbl.setWordWrap(True)
        rl.addWidget(ref_lbl)
        l_lay.addWidget(ref_grp)
        l_lay.addStretch()

        splitter.addWidget(left_scroll)

        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(6)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left", "Amplitude (V)", color=T.TEXT_MUTED)
        self._plot.setLabel("bottom", "Time (s)", color=T.TEXT_MUTED)
        self._plot.showGrid(x=True, y=True, alpha=0.14)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

        self._ch1_curve = self._plot.plot(
            pen=pg.mkPen(T.ACCENT_BLUE, width=1.5),
            name="CH1 (raw)",
        )

        line_styles = [Qt.DashLine, Qt.DotLine, Qt.DashDotLine, Qt.DashDotDotLine]
        self._plot_curves = []
        for i, ch in enumerate(self._channels):
            c = self._plot.plot(
                pen=pg.mkPen(ch.color, width=2, style=line_styles[i]),
                name=ch.name,
            )
            self._plot_curves.append(c)

        self._plot.addLegend(offset=(10, 10))
        r_lay.addWidget(self._plot, stretch=1)

        mc = QHBoxLayout()
        ml = QLabel("CH1 trace (math rows keep their own color buttons)")
        ml.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-weight: 600;")
        mc.addWidget(ml)
        self._ch1_trace_bar = TraceColorBar(self._settings, "math", self)
        self._ch1_trace_bar.add_trace(
            "ch1", "CH1", "Raw DSO input on this plot", "ACCENT_BLUE",
            items=[self._ch1_curve], width=1.5,
        )
        mc.addWidget(self._ch1_trace_bar)
        mc.addStretch()
        r_lay.addLayout(mc)

        self._err_lbl = QLabel("")
        self._err_lbl.setFont(_ui_font(SZ_SM))
        self._err_lbl.setStyleSheet(
            f"color: {T.ACCENT_RED}; background: transparent; border: none; padding: 4px;"
        )
        self._err_lbl.setWordWrap(True)
        r_lay.addWidget(self._err_lbl)

        splitter.addWidget(right_w)
        splitter.setSizes([420, 880])

    def _make_channel_row(self, ch: MathChannel) -> QGroupBox:
        grp = QGroupBox(f"MATH {ch.name}")
        grp.setStyleSheet(
            f"QGroupBox {{ font-weight: 600; color: {T.TEXT}; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}"
        )
        lay = QGridLayout(grp)
        lay.setContentsMargins(12, 22, 12, 12)
        lay.setHorizontalSpacing(8)
        lay.setVerticalSpacing(8)

        chk = QCheckBox("Enable")
        chk.setChecked(ch.enabled)
        chk.stateChanged.connect(lambda state, c=ch: setattr(c, "enabled", state == Qt.Checked))
        lay.addWidget(chk, 0, 0)

        col_btn = QPushButton(" ")
        col_btn.setFixedSize(28, 22)
        col_btn.setStyleSheet(f"background: {ch.color}; border: 1px solid {T.BORDER}; border-radius: 3px;")

        def _pick_color(_, c=ch, b=col_btn):
            qc = QColorDialog.getColor(QColor(c.color), self, "Channel color")
            if qc.isValid():
                c.color = qc.name()
                b.setStyleSheet(f"background: {c.color}; border: 1px solid {T.BORDER}; border-radius: 3px;")

        col_btn.clicked.connect(_pick_color)
        lay.addWidget(col_btn, 0, 1)

        mix_chk = QCheckBox("Mix test signal")
        mix_chk.setChecked(ch.mix_enabled)
        mix_chk.stateChanged.connect(lambda s, c=ch: setattr(c, "mix_enabled", s == Qt.Checked))
        lay.addWidget(mix_chk, 0, 2, 1, 2)

        shape_lbl = ThemeLabel("Test shape:", "TEXT_MUTED", SZ_SM)
        cmb_shape = QComboBox()
        cmb_shape.addItems(["none", "sine", "square", "triangle", "sawtooth"])
        cmb_shape.setCurrentText(ch.test_shape)
        cmb_shape.currentTextChanged.connect(lambda t, c=ch: setattr(c, "test_shape", t))
        lay.addWidget(shape_lbl, 1, 0)
        lay.addWidget(cmb_shape, 1, 1)

        op_lbl = ThemeLabel("Operation:", "TEXT_MUTED", SZ_SM)
        cmb_op = QComboBox()
        cmb_op.addItems(["add", "sub", "mul"])
        cmb_op.setCurrentText(ch.mix_op)
        cmb_op.currentTextChanged.connect(lambda t, c=ch: setattr(c, "mix_op", t))
        lay.addWidget(op_lbl, 1, 2)
        lay.addWidget(cmb_op, 1, 3)

        freq_lbl = ThemeLabel("Test f (Hz):", "TEXT_MUTED", SZ_SM)
        sp_freq = QDoubleSpinBox()
        sp_freq.setRange(0.001, 10_000_000.0)
        sp_freq.setDecimals(3)
        sp_freq.setValue(ch.test_freq_hz)
        sp_freq.valueChanged.connect(lambda v, c=ch: setattr(c, "test_freq_hz", v))
        amp_lbl = ThemeLabel("Test amp (V):", "TEXT_MUTED", SZ_SM)
        sp_amp = QDoubleSpinBox()
        sp_amp.setRange(-100.0, 100.0)
        sp_amp.setDecimals(3)
        sp_amp.setValue(ch.test_amp_v)
        sp_amp.valueChanged.connect(lambda v, c=ch: setattr(c, "test_amp_v", v))
        lay.addWidget(freq_lbl, 2, 0)
        lay.addWidget(sp_freq, 2, 1)
        lay.addWidget(amp_lbl, 2, 2)
        lay.addWidget(sp_amp, 2, 3)

        expr_lbl = ThemeLabel("Expression:", "TEXT_MUTED", SZ_SM)
        expr_inp = QLineEdit()
        expr_inp.setFont(_ui_font(SZ_BODY))
        expr_inp.setPlaceholderText("Empty + mix → CH1+TEST; or e.g. CH1 + 0.5*TEST")
        expr_inp.setText(ch.expr)
        expr_inp.textChanged.connect(lambda text, c=ch: setattr(c, "expr", text))
        lay.addWidget(expr_lbl, 3, 0)
        lay.addWidget(expr_inp, 3, 1, 1, 3)

        btn_fill = QPushButton("Set expr: CH1+TEST")
        btn_fill.setStyleSheet(f"color: {T.PRIMARY}; font-size: {SZ_XS}px;")
        btn_fill.clicked.connect(lambda _, e=expr_inp: e.setText("CH1 + TEST"))
        lay.addWidget(btn_fill, 4, 1, 1, 2)

        gain_lbl = ThemeLabel("Gain", "TEXT_MUTED", SZ_SM)
        gain_spin = QDoubleSpinBox()
        gain_spin.setRange(-1000.0, 1000.0)
        gain_spin.setValue(ch.gain)
        gain_spin.setDecimals(3)
        gain_spin.setSuffix(" ×")
        gain_spin.valueChanged.connect(lambda v, c=ch: setattr(c, "gain", v))
        off_lbl = ThemeLabel("Offset", "TEXT_MUTED", SZ_SM)
        off_spin = QDoubleSpinBox()
        off_spin.setRange(-1000.0, 1000.0)
        off_spin.setValue(ch.offset)
        off_spin.setDecimals(3)
        off_spin.setSuffix(" V")
        off_spin.valueChanged.connect(lambda v, c=ch: setattr(c, "offset", v))
        lay.addWidget(gain_lbl, 5, 0)
        lay.addWidget(gain_spin, 5, 1)
        lay.addWidget(off_lbl, 5, 2)
        lay.addWidget(off_spin, 5, 3)

        self._chan_widgets.append(
            {
                "chk": chk,
                "mix_chk": mix_chk,
                "expr": expr_inp,
                "gain": gain_spin,
                "offset": off_spin,
                "shape": cmb_shape,
                "op": cmb_op,
                "tfreq": sp_freq,
                "tamp": sp_amp,
            }
        )
        return grp

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        self._plot.setBackground(T.DARK_BG)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        if self._ch1_trace_bar:
            self._ch1_trace_bar.refresh_theme_defaults_only()

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    def _clear_all(self):
        for ch, w in zip(self._channels, self._chan_widgets):
            ch.expr = ""
            ch.enabled = False
            ch.mix_enabled = False
            ch.test_shape = "none"
            w["expr"].setText("")
            w["chk"].setChecked(False)
            w["mix_chk"].setChecked(False)
            w["shape"].setCurrentText("none")
        for c in self._plot_curves:
            c.setData([], [])

    def _apply_preset_selected(self):
        key = self.cmb_preset.currentText()
        if key not in self._presets:
            return
        idx = self.cmb_preset_target.currentIndex()
        expr = self._presets[key].format(dt=self.sample_period)
        ch = self._channels[idx]
        w = self._chan_widgets[idx]
        ch.expr = expr
        w["expr"].setText(expr)
        ch.enabled = True
        w["chk"].setChecked(True)

    def _refresh(self):
        raw = self._dso_source()
        if len(raw) < 4:
            return
        arr = np.array(raw, dtype=float)
        ns = _make_namespace(arr, self.sample_period)
        t_axis = ns["t"]

        self._ch1_curve.setData(t_axis, arr)

        errors = []
        for i, (ch, curve) in enumerate(zip(self._channels, self._plot_curves)):
            if not ch.enabled:
                curve.setData([], [])
                continue
            result = ch.compute(ns)
            if result is not None:
                curve.setPen(pg.mkPen(ch.color, width=2))
                curve.setData(t_axis, result)
            else:
                curve.setData([], [])
                if ch.last_error:
                    errors.append(f"{ch.name}: {ch.last_error}")

        self._err_lbl.setText("  |  ".join(errors) if errors else "")
