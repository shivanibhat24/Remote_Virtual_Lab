"""
tab_pid.py - PID Tuner tab for STM32 Lab GUI v6.0
Focuses on the Boost Converter closed-loop control.
"""

from typing import Optional, List, Callable
import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QGroupBox,
    QProgressBar, QSplitter
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header
from data_engine import CommandBuilder


class PidTunerTab(QWidget):
    """PID Tuning interface for Boost Converter / Voltage Regulator."""

    send_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._stat_cards:   List[ThemeCard]        = []
        
        # Data source injected by MainWindow (returns [PV_samples, SP_samples])
        self._data_source: Callable[[], tuple] = lambda: ([], [])
        
        self._build_ui()
        
        # Plotting timer
        self._timer = QTimer()
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_plot)
        self._timer.start()

    # -- UI Build --------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("PID Tuner (Boost Converter)")
        self._header_strip = hdr

        self.btn_apply = QPushButton("APPLY GAINS")
        self.btn_apply.setObjectName("btn_pid")
        self.btn_apply.setFixedWidth(140)
        self.btn_apply.clicked.connect(self._apply_gains)
        hdr_lay.addWidget(self.btn_apply)

        self.btn_apply_cfg = QPushButton("APPLY CONFIG")
        self.btn_apply_cfg.setObjectName("btn_warning")
        self.btn_apply_cfg.setFixedWidth(130)
        self.btn_apply_cfg.clicked.connect(self._apply_config)
        hdr_lay.addWidget(self.btn_apply_cfg)

        self.btn_reset = QPushButton("RESET")
        self.btn_reset.setObjectName("btn_disconnect")
        self.btn_reset.setFixedWidth(80)
        self.btn_reset.clicked.connect(self._reset_gains)
        hdr_lay.addWidget(self.btn_reset)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: Control Panel -----------------------------------------------
        ctrl_w = QWidget()
        ctrl_w.setMaximumWidth(280)
        c_lay  = QVBoxLayout(ctrl_w)
        c_lay.setContentsMargins(14, 14, 14, 14)
        c_lay.setSpacing(12)

        gain_grp = QGroupBox("PID GAINS")
        gl = QGridLayout(gain_grp)
        gl.setSpacing(10)
        gl.setContentsMargins(12, 22, 12, 12)
        c_lay.addWidget(gain_grp)

        def _row(gl_obj, label, widget, row):
            gl_obj.addWidget(ThemeLabel(label, "TEXT_MUTED", SZ_SM, bold=True), row, 0)
            gl_obj.addWidget(widget, row, 1)

        self.spin_p = QDoubleSpinBox()
        self.spin_p.setRange(0.000, 100.0)
        self.spin_p.setValue(1.5)
        self.spin_p.setSingleStep(0.1)
        _row(gl, "Kp (Gain):", self.spin_p, 0)

        self.spin_i = QDoubleSpinBox()
        self.spin_i.setRange(0.000, 100.0)
        self.spin_i.setValue(0.2)
        self.spin_i.setSingleStep(0.01)
        _row(gl, "Ki (Reset):", self.spin_i, 1)

        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(0.000, 100.0)
        self.spin_d.setValue(0.05)
        self.spin_d.setSingleStep(0.01)
        _row(gl, "Kd (Rate):", self.spin_d, 2)

        self.spin_sp = QDoubleSpinBox()
        self.spin_sp.setRange(0.0, 12.0)
        self.spin_sp.setValue(5.0)
        self.spin_sp.setSuffix(" V")
        _row(gl, "Setpoint:", self.spin_sp, 3)

        # Advanced Config Group
        cfg_grp = QGroupBox("ADVANCED CONFIG")
        cl = QGridLayout(cfg_grp)
        cl.setSpacing(10)
        cl.setContentsMargins(12, 22, 12, 12)
        c_lay.addWidget(cfg_grp)

        self.spin_v_min = QDoubleSpinBox()
        self.spin_v_min.setRange(0.0, 12.0)
        self.spin_v_min.setValue(0.0)
        self.spin_v_min.setSuffix(" V")
        _row(cl, "Out Min:", self.spin_v_min, 0)

        self.spin_v_max = QDoubleSpinBox()
        self.spin_v_max.setRange(0.0, 15.0)
        self.spin_v_max.setValue(12.0)
        self.spin_v_max.setSuffix(" V")
        _row(cl, "Out Max:", self.spin_v_max, 1)

        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setRange(0.0, 1.0)
        self.spin_alpha.setSingleStep(0.01)
        self.spin_alpha.setValue(0.3)
        self.spin_alpha.setToolTip("Input filter coefficient (Low-pass)")
        _row(cl, "Filter Alpha:", self.spin_alpha, 2)

        # Stat cards
        self.lbl_error = QLabel("- V")
        self.lbl_settle = QLabel("- s")
        self.lbl_overshoot = QLabel("- %")
        card_err = ThemeCard("ERROR",      self.lbl_error,     "ACCENT_RED")
        card_set = ThemeCard("SETTLE TIME", self.lbl_settle,    "ACCENT_BLUE")
        card_ovr = ThemeCard("OVERSHOOT",   self.lbl_overshoot, "ACCENT_AMBER")
        self._stat_cards = [card_err, card_set, card_ovr]
        c_lay.addWidget(card_err)
        c_lay.addWidget(card_set)
        c_lay.addWidget(card_ovr)
        c_lay.addStretch()
        splitter.addWidget(ctrl_w)

        # -- RIGHT: Response Plot ----------------------------------------------
        plot_w = QWidget()
        pl_lay = QVBoxLayout(plot_w)
        pl_lay.setContentsMargins(8, 8, 8, 8)
        pl_lay.setSpacing(4)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self._plot = pg.PlotWidget()
        self._plot.setLabel("left",   "Voltage (V)", color=T.TEXT_MUTED)
        self._plot.setLabel("bottom", "Samples",     color=T.TEXT_MUTED)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        
        self._curve_pv = self._plot.plot(pen=pg.mkPen(T.PRIMARY, width=2.5), name="Process Var")
        self._curve_sp = self._plot.plot(pen=pg.mkPen(T.TEXT_DIM, width=1.5, style=Qt.DashLine), name="Setpoint")
        
        pl_lay.addWidget(self._plot, stretch=1)
        splitter.addWidget(plot_w)
        splitter.setSizes([260, 800])

    # -- Public API ------------------------------------------------------------

    def set_data_source(self, fn: Callable[[], tuple]):
        self._data_source = fn

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        for card in self._stat_cards:
            card.update_theme()
        self._plot.setBackground(T.DARK_BG)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

    # -- Actions ---------------------------------------------------------------

    def _apply_gains(self):
        kp = self.spin_p.value()
        ki = self.spin_i.value()
        kd = self.spin_d.value()
        sp = self.spin_sp.value()
        cmd = CommandBuilder.pid_cmd(kp, ki, kd, sp)
        self.send_requested.emit(cmd)

    def _apply_config(self):
        vmin  = self.spin_v_min.value()
        vmax  = self.spin_v_max.value()
        alpha = self.spin_alpha.value()
        cmd = CommandBuilder.pid_cfg_cmd(vmin, vmax, alpha)
        self.send_requested.emit(cmd)

    def _reset_gains(self):
        self.spin_p.setValue(1.0)
        self.spin_i.setValue(0.0)
        self.spin_d.setValue(0.0)
        self.spin_sp.setValue(3.3)
        self._apply_gains()

    def _update_plot(self):
        pv_raw, sp_raw = self._data_source()
        if not pv_raw:
            return
        
        arr_pv = np.array(pv_raw, dtype=float)
        arr_sp = np.array(sp_raw, dtype=float) if sp_raw else np.full_like(arr_pv, self.spin_sp.value())
        
        self._curve_pv.setData(arr_pv)
        self._curve_sp.setData(arr_sp)
        
        # Online analysis (trailing metrics)
        n = len(arr_pv)
        if n > 10:
            sp_val = arr_sp[-1]
            pv_val = arr_pv[-1]
            error  = sp_val - pv_val
            self.lbl_error.setText(f"{error:+.3f} V")
            
            peak = np.max(arr_pv)
            if sp_val > 0.1:
                overshoot = max(0.0, (peak - sp_val) / sp_val * 100.0)
                self.lbl_overshoot.setText(f"{overshoot:.1f} %")
                
            tolerance = 0.05 * sp_val if sp_val > 0 else 0.1
            steady_indices = np.where(np.abs(arr_pv - sp_val) < tolerance)[0]
            if steady_indices.size > 0:
                self.lbl_settle.setText(f"In band")
            else:
                self.lbl_settle.setText("Settling...")
