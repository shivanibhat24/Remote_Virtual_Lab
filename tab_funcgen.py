"""
tab_funcgen.py - Function Generator tab for STM32 Lab GUI v6.0
"""

from typing import Optional

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QComboBox, QSpinBox, QSlider, QGroupBox,
    QTabWidget
)
from PyQt5.QtCore import Qt, pyqtSignal

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import _HeaderStrip, make_header
from data_engine import CommandBuilder


class FunctionGenTab(QWidget):
    send_requested = pyqtSignal(str)

    WAVE_MAP = {
        "Square": "SQ", "Triangle": "TR", "Parabola": "PA",
        "Sine": "SI", "Half-Wave": "HW", "Full-Wave": "FW",
        "Sawtooth": "SA", "Sinc": "SN", "Step": "ST",
        "Staircase": "SC", "Gaussian": "GA", "Noise": "NO",
        "DC": "DC", "Ground": "G"
    }
    _WAVE_COLOR_ATTRS = {
        "Square":    "ACCENT_BLUE",
        "Triangle":  "PRIMARY",
        "Parabola":  "ACCENT_AMBER",
        "Sine":      "ACCENT_CYAN",
        "Half-Wave": "ACCENT_RED",
        "Full-Wave": "ACCENT_PUR",
        "Sawtooth":  "ACCENT_BLUE",
        "Sinc":      "ACCENT_CYAN",
        "Step":      "PRIMARY",
        "Staircase": "ACCENT_AMBER",
        "Gaussian":  "ACCENT_PUR",
        "Noise":     "ACCENT_RED",
        "DC":        "TEXT_MUTED",
        "Ground":    "TEXT_MUTED",
    }

    def __init__(self):
        super().__init__()
        self._current_wave = "Square"
        self._header_strip: Optional[_HeaderStrip] = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, _ = make_header("Function Generator")
        self._header_strip = hdr
        root.addWidget(hdr)

        content = QWidget()
        c_lay   = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(16)
        root.addWidget(content, stretch=1)

        # -- Waveform selector (Tabbed) ----------------------------------------
        self._tabs = QTabWidget()
        c_lay.addWidget(self._tabs)
        
        # 1. PRIMARY TAB
        page_primary = QWidget()
        lay_primary = QHBoxLayout(page_primary)
        lay_primary.setContentsMargins(10, 10, 10, 10)
        lay_primary.setSpacing(10)
        self._tabs.addTab(page_primary, "PRIMARY")
        
        # 2. OTHER TAB (Advanced Set)
        page_other = QWidget()
        lay_other = QGridLayout(page_other) # Grid for many buttons
        lay_other.setContentsMargins(10, 10, 10, 10)
        lay_other.setSpacing(8)
        self._tabs.addTab(page_other, "OTHER")

        self._wave_btns: dict = {}
        primary_list = ["Square", "Triangle", "Parabola"]
        other_list   = [w for w in self.WAVE_MAP if w not in primary_list]

        for name in primary_list:
            btn = QPushButton(name.upper())
            btn.setCheckable(True)
            btn.setFixedHeight(50)
            col = getattr(T, self._WAVE_COLOR_ATTRS[name], T.PRIMARY)
            btn.setStyleSheet(self._wave_btn_style(col))
            btn.clicked.connect(lambda _, n=name: self._select_wave(n))
            lay_primary.addWidget(btn)
            self._wave_btns[name] = btn

        row, col_idx = 0, 0
        for name in other_list:
            btn = QPushButton(name.upper())
            btn.setCheckable(True)
            btn.setFixedHeight(34)
            color_val = getattr(T, self._WAVE_COLOR_ATTRS[name], T.PRIMARY)
            btn.setStyleSheet(self._wave_btn_style(color_val, sz=SZ_XS))
            btn.clicked.connect(lambda _, n=name: self._select_wave(n))
            lay_other.addWidget(btn, row, col_idx)
            self._wave_btns[name] = btn
            col_idx += 1
            if col_idx > 3:
                col_idx = 0
                row += 1

        pg.setConfigOption("background", T.CARD_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self._wave_preview = pg.PlotWidget()
        self._wave_preview.setFixedHeight(130)
        self._wave_preview.hideAxis("left")
        self._wave_preview.hideAxis("bottom")
        self._wave_preview.setBackground(T.CARD_BG)
        self._wave_preview.setMouseEnabled(x=False, y=False)
        self._preview_curve = self._wave_preview.plot(
            pen=pg.mkPen(T.ACCENT_BLUE, width=2.5))
        c_lay.addWidget(self._wave_preview)

        # -- Frequency control -------------------------------------------------
        freq_grp = QGroupBox("FREQUENCY")
        fg_lay   = QVBoxLayout(freq_grp)
        fg_lay.setSpacing(10)
        fg_lay.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(freq_grp)

        freq_row = QHBoxLayout()
        fg_lay.addLayout(freq_row)
        self.sld_freq = QSlider(Qt.Horizontal)
        self.sld_freq.setRange(0, 1000)
        self.sld_freq.setValue(100)
        freq_row.addWidget(self.sld_freq, stretch=1)
        self.spin_freq = QSpinBox()
        self.spin_freq.setRange(0, 1000)
        self.spin_freq.setValue(100)
        self.spin_freq.setSuffix(" Hz")
        self.spin_freq.setFixedWidth(110)
        freq_row.addWidget(self.spin_freq)

        self.spin_freq.valueChanged.connect(self.sld_freq.setValue)
        self.sld_freq.valueChanged.connect(self.spin_freq.setValue)
        self.spin_freq.valueChanged.connect(self._update_preview)

        ctrl_row = QHBoxLayout()
        fg_lay.addLayout(ctrl_row)

        self.btn_send = QPushButton("APPLY SETTINGS")
        self.btn_send.setFixedHeight(42)
        self.btn_send.clicked.connect(self._on_send)
        ctrl_row.addWidget(self.btn_send, stretch=2)

        self.cmb_pulse_type = QComboBox()
        self.cmb_pulse_type.addItems(["HALF-CYCLE", "FULL-CYCLE"])
        self.cmb_pulse_type.setFixedHeight(42)
        self.cmb_pulse_type.setFixedWidth(110)
        self.cmb_pulse_type.setToolTip("Pulse precision: Trigger 0.5 or 1.0 logic cycles")
        ctrl_row.addWidget(self.cmb_pulse_type)

        self.btn_pulse = QPushButton("PULSE")
        self.btn_pulse.setObjectName("btn_warning")
        self.btn_pulse.setFixedHeight(42)
        self.btn_pulse.setToolTip("Trigger a single waveform one-shot pulse")
        self.btn_pulse.clicked.connect(self._on_pulse)
        ctrl_row.addWidget(self.btn_pulse, stretch=1)

        c_lay.addStretch()
        self._select_wave("Square")

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _wave_btn_style(col: str, sz: int = SZ_SM) -> str:
        return f"""
            QPushButton {{
                color:{col}; border:1px solid {col}; background:transparent;
                font-size:{sz}px; font-weight:700; font-family:{T.FONT_UI};
            }}
            QPushButton:checked {{ background:{col}; color:{T.DARK_BG}; }}
            QPushButton:hover   {{ background:{col}33; }}
        """

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        self._wave_preview.setBackground(T.CARD_BG)
        for name, btn in self._wave_btns.items():
            col = getattr(T, self._WAVE_COLOR_ATTRS[name], T.PRIMARY)
            btn.setStyleSheet(self._wave_btn_style(col))
        self._update_preview()

    def _select_wave(self, name: str):
        for n, b in self._wave_btns.items():
            b.setChecked(n == name)
        self._current_wave = name
        self._update_preview()

    def _update_preview(self):
        name  = self._current_wave
        freq  = self.spin_freq.value() or 1
        t     = np.linspace(0, 2 / freq, 500)
        phase = 2 * np.pi * freq * t
        
        if name == "Square":
            y = np.sign(np.sin(phase))
        elif name == "Triangle":
            y = 2 * np.arcsin(np.sin(phase)) / np.pi
        elif name == "Sawtooth":
            y = 2 * (t * freq - np.floor(0.5 + t * freq))
        elif name == "Parabola":
            y = np.sin(phase) ** 2 * np.sign(np.sin(phase))
        elif name == "Sine":
            y = np.sin(phase)
        elif name == "Half-Wave":
            y = np.maximum(0, np.sin(phase))
        elif name == "Full-Wave":
            y = np.abs(np.sin(phase))
        elif name == "Sinc":
            y = np.sinc(freq * t * 4 - 4)
        elif name == "Step":
            y = np.where(t > 1/(2*freq), 1.0, 0.0)
        elif name == "Staircase":
            y = np.floor(t * freq * 5) / 5
        elif name == "Gaussian":
            y = np.exp(-((t*freq - 1)**2) / 0.1)
        elif name == "Noise":
            y = np.random.normal(0, 0.4, size=len(t))
        elif name == "DC":
            y = np.ones_like(t) * 0.5
        else:
            y = np.zeros_like(t)
        col = getattr(T, self._WAVE_COLOR_ATTRS.get(name, "PRIMARY"), T.PRIMARY)
        self._preview_curve.setPen(pg.mkPen(col, width=2.5))
        self._preview_curve.setData(t, y)

    def _on_send(self):
        self.send_requested.emit(CommandBuilder.wave_type(self.WAVE_MAP[self._current_wave]))
        self.send_requested.emit(CommandBuilder.wave_freq(self.spin_freq.value()))

    def _on_pulse(self):
        """Trigger a single pulse command (Half or Full cycle)."""
        mode = "H" if self.cmb_pulse_type.currentText() == "HALF-CYCLE" else "F"
        # Command syntax: #FG_PULSE:[H/F]
        self.send_requested.emit(f"#FG_PULSE:{mode}")
