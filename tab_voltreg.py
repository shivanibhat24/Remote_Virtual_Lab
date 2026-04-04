"""
tab_voltreg.py - Voltage Regulator tab for STM32 Lab GUI v6.0
"""

from collections import deque
from typing import Optional, List

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QDoubleSpinBox, QGroupBox,
)
from PyQt5.QtCore import QTimer, pyqtSignal, Qt

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget
from data_engine import CommandBuilder, ParsedMessage
from plot_trace_colors import TraceColorBar


class VoltageRegTab(QWidget):
    send_requested = pyqtSignal(str)

    def __init__(self, settings=None):
        super().__init__()
        self._settings = settings
        self._trace_bar: Optional[TraceColorBar] = None
        self._boost_history: deque = deque(maxlen=200)
        self._temp_history:  deque = deque(maxlen=200)
        self._stat_cards: List[ThemeCard] = []
        self._header_strip: Optional[_HeaderStrip] = None
        self._build_ui()
        self._trend_timer = QTimer()
        self._trend_timer.setInterval(500)
        self._trend_timer.timeout.connect(self._refresh_trend)
        self._trend_timer.start()

    def _build_ui(self):
        root  = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Voltage Regulator")
        self._header_strip = hdr
        
        self.local_logger = LocalLoggerWidget("voltreg", ["timestamp", "setpoint_v", "boost_v", "temp_c"])
        hdr_lay.addStretch()
        hdr_lay.addWidget(self.local_logger)
        
        root.addWidget(hdr)

        content = QWidget()
        c_lay   = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(16)
        root.addWidget(content, stretch=1)

        # -- Output voltage control --------------------------------------------
        ctrl_grp = QGroupBox("OUTPUT VOLTAGE CONTROL")
        cl       = QVBoxLayout(ctrl_grp)
        cl.setSpacing(10)
        cl.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(ctrl_grp)

        self.lbl_setpoint = QLabel("0.0 V")
        self.lbl_setpoint.setAlignment(Qt.AlignCenter)
        self.lbl_setpoint.setFont(_ui_font(SZ_SETPT, bold=True))
        cl.addWidget(self.lbl_setpoint)

        sr = QHBoxLayout()
        cl.addLayout(sr)
        self.sld_vreg = QSlider(1)   # Qt.Horizontal
        self.sld_vreg.setRange(0, 120)
        self.sld_vreg.setValue(0)
        sr.addWidget(self.sld_vreg, stretch=1)
        self.spin_vreg = QDoubleSpinBox()
        self.spin_vreg.setRange(0.0, 12.0)
        self.spin_vreg.setSingleStep(0.1)
        self.spin_vreg.setDecimals(1)
        self.spin_vreg.setSuffix(" V")
        self.spin_vreg.setFixedWidth(100)
        sr.addWidget(self.spin_vreg)

        self.sld_vreg.valueChanged.connect(lambda v: self.spin_vreg.setValue(v / 10.0))
        self.spin_vreg.valueChanged.connect(lambda v: self.sld_vreg.setValue(int(v * 10)))
        self.spin_vreg.valueChanged.connect(lambda v: self.lbl_setpoint.setText(f"{v:.1f} V"))

        pr = QHBoxLayout()
        cl.addLayout(pr)
        for v in [1.8, 3.3, 5.0, 9.0, 12.0]:
            btn = QPushButton(f"{v}V")
            btn.setFixedWidth(68)
            btn.clicked.connect(lambda _, val=v: self.spin_vreg.setValue(val))
            pr.addWidget(btn)
        pr.addStretch()

        self.btn_send = QPushButton("APPLY VOLTAGE")
        self.btn_send.setFixedHeight(42)
        self.btn_send.clicked.connect(self._on_send)
        cl.addWidget(self.btn_send)

        #  Live feedback 
        fb_grp = QGroupBox("LIVE FEEDBACK")
        fl     = QVBoxLayout(fb_grp)
        fl.setSpacing(10)
        fl.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(fb_grp)

        cards_row = QHBoxLayout()
        fl.addLayout(cards_row)
        self.lbl_boost = QLabel("- V")
        self.lbl_temp  = QLabel("- degC")
        card_b = ThemeCard("BOOST OUTPUT", self.lbl_boost, "ACCENT_AMBER")
        card_t = ThemeCard("TEMPERATURE",  self.lbl_temp,  "ACCENT_RED")
        self._stat_cards = [card_b, card_t]
        cards_row.addWidget(card_b)
        cards_row.addWidget(card_t)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self.trend_plot = pg.PlotWidget()
        self.trend_plot.setFixedHeight(160)
        self.trend_plot.showGrid(x=False, y=True, alpha=0.15)
        self.trend_plot.hideAxis("bottom")
        self.trend_plot.setLabel("left", "V / degC", color=T.TEXT_MUTED)
        self.trend_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._boost_curve = self.trend_plot.plot(
            pen=pg.mkPen(T.ACCENT_AMBER, width=2), name="Boost V")
        self._temp_curve  = self.trend_plot.plot(
            pen=pg.mkPen(T.ACCENT_RED,   width=2), name="Temp degC")
        self.trend_plot.addLegend(offset=(10, 5))
        fl.addWidget(self.trend_plot)

        vc = QHBoxLayout()
        vl = QLabel("Trace colors")
        vl.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-weight: 600;")
        vc.addWidget(vl)
        self._trace_bar = TraceColorBar(self._settings, "vreg", self)
        self._trace_bar.add_trace(
            "boost", "Bst", "Boost voltage trace", "ACCENT_AMBER",
            items=[self._boost_curve], width=2.0,
        )
        self._trace_bar.add_trace(
            "temp", "Tmp", "Temperature trace", "ACCENT_RED",
            items=[self._temp_curve], width=2.0,
        )
        vc.addWidget(self._trace_bar)
        vc.addStretch()
        fl.addLayout(vc)

        c_lay.addStretch()

        self._refresh_setpoint_color()

    def _refresh_setpoint_color(self):
        self.lbl_setpoint.setStyleSheet(
            f"color: {T.PRIMARY}; background: {T.CARD_BG}; "
            f"border: 1px solid {T.BORDER}; padding: 12px;"
        )

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        if getattr(self, "local_logger", None):
            self.local_logger.update_theme()
        for c in self._stat_cards:
            c.update_theme()
        self._refresh_setpoint_color()
        self.trend_plot.setBackground(T.DARK_BG)
        self.trend_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        if self._trace_bar:
            self._trace_bar.refresh_theme_defaults_only()

    def _on_send(self):
        self.send_requested.emit(CommandBuilder.vreg_cmd(self.spin_vreg.value()))

    def on_boost(self, msg: ParsedMessage):
        v = msg.fields.get("V", "")
        self.lbl_boost.setText(f"{v} V")
        try:
            fv = float(v)
            self._boost_history.append(fv)
            if getattr(self, "local_logger", None):
                self.local_logger.log({
                    "setpoint_v": self.spin_vreg.value(),
                    "boost_v": fv,
                    "temp_c": self._temp_history[-1] if self._temp_history else ""
                })
        except ValueError:
            pass

    def on_temp(self, msg: ParsedMessage):
        t = msg.fields.get("T", "")
        self.lbl_temp.setText(f"{t} degC")
        try:
            self._temp_history.append(float(t))
        except ValueError:
            pass

    def get_boost_history(self) -> list:
        """Expose boost history for PID tab."""
        return list(self._boost_history)

    def _refresh_trend(self):
        b = list(self._boost_history)
        t = list(self._temp_history)
        if b:
            self._boost_curve.setData(np.arange(len(b)), np.array(b))
        if t:
            self._temp_curve.setData(np.arange(len(t)), np.array(t))
