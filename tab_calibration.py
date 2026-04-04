"""
tab_calibration.py - Automated Calibration Wizard for STM32 Lab GUI v6.0

Step-by-step wizard that:
  1. Guides user through applying known reference voltages
  2. Records the measured ADC reading at each point
  3. Fits a polynomial correction curve (numpy.polyfit, degree 1-3)
  4. Shows R^2 and residual plot
  5. Saves coefficients to ~/.stm32lab/calibration.json
  6. Coefficients are applied to future readings via the analytics engine

WHY: ADC linearity errors in Bluepill are ~1-2 LSB INL.
     Calibration can reduce measurement error by 10.
"""

import json
import math
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox,
    QGroupBox, QTableWidget, QTableWidgetItem, QMessageBox,
    QSplitter
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header
from plot_trace_colors import TraceColorBar

CAL_PATH = Path.home() / ".stm32lab" / "calibration.json"


def load_calibration() -> Optional[List[float]]:
    """Load polynomial coefficients [c0, c1, ] or None."""
    if CAL_PATH.exists():
        try:
            return json.loads(CAL_PATH.read_text())
        except Exception:
            pass
    return None


def apply_calibration(value: float, coeffs: List[float]) -> float:
    """Evaluate polynomial correction: value_corrected = poly(value)."""
    return float(np.polyval(coeffs, value))


class CalibrationWizard(QWidget):
    """Multi-step polynomial calibration wizard."""
    calibration_updated = pyqtSignal(list)

    def __init__(self, settings=None):
        super().__init__()
        self._settings = settings
        self._trace_bar: Optional[TraceColorBar] = None
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []

        # Cal data: list of (ref_voltage, measured_mean)
        self._cal_points: List[Tuple[float, float]] = []
        self._coeffs: Optional[List[float]] = None

        existing = load_calibration()
        if existing:
            self._coeffs = existing

        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Calibration Wizard")
        self._header_strip = hdr

        self.btn_reset_cal = QPushButton("RESET CALIBRATION")
        self.btn_reset_cal.setObjectName("btn_disconnect")
        self.btn_reset_cal.setFixedWidth(190)
        self.btn_reset_cal.clicked.connect(self._reset)
        hdr_lay.addWidget(self.btn_reset_cal)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: wizard steps ------------------------------------------------
        left_w = QWidget()
        left_w.setMaximumWidth(320)
        l_lay = QVBoxLayout(left_w)
        l_lay.setContentsMargins(14, 14, 14, 14)
        l_lay.setSpacing(12)

        # Step 1: add calibration point
        step1_grp = QGroupBox("STEP 1 - ADD CALIBRATION POINT")
        s1_lay = QVBoxLayout(step1_grp)
        s1_lay.setSpacing(8)
        s1_lay.setContentsMargins(12, 22, 12, 12)
        l_lay.addWidget(step1_grp)

        r1 = QHBoxLayout()
        r1.addWidget(ThemeLabel("Reference V:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_ref = QDoubleSpinBox()
        self.spin_ref.setRange(0.0, 20.0)
        self.spin_ref.setValue(3.3)
        self.spin_ref.setSuffix(" V")
        self.spin_ref.setDecimals(4)
        r1.addWidget(self.spin_ref)
        s1_lay.addLayout(r1)

        s1_lay.addWidget(ThemeLabel(
            "Apply this voltage to the ADC input, then click:", "TEXT_MUTED", SZ_SM))

        self.btn_add_point = QPushButton("[ RECORD POINT ]")
        self.btn_add_point.setObjectName("btn_connect")
        self.btn_add_point.clicked.connect(self._add_point)
        s1_lay.addWidget(self.btn_add_point)

        # Current reading
        self.lbl_cur_reading = ThemeLabel("Current reading: -", "TEXT_MUTED", SZ_BODY)
        s1_lay.addWidget(self.lbl_cur_reading)

        # Calibration points table
        tbl_grp = QGroupBox("CALIBRATION POINTS")
        tl = QVBoxLayout(tbl_grp)
        tl.setContentsMargins(10, 20, 10, 10)
        self._tbl = QTableWidget(0, 2)
        self._tbl.setHorizontalHeaderLabels(["Reference (V)", "Measured (V)"])
        self._tbl.horizontalHeader().setStretchLastSection(True)
        self._tbl.setMaximumHeight(180)
        self._tbl.setFont(_ui_font(SZ_SM))
        tl.addWidget(self._tbl)

        remove_row = QHBoxLayout()
        btn_del = QPushButton("REMOVE SELECTED")
        btn_del.setObjectName("btn_disconnect")
        btn_del.clicked.connect(self._remove_selected)
        remove_row.addWidget(btn_del)
        remove_row.addStretch()
        tl.addLayout(remove_row)
        l_lay.addWidget(tbl_grp)

        # Step 2: fit
        step2_grp = QGroupBox("STEP 2 - FIT POLYNOMIAL")
        s2_lay = QVBoxLayout(step2_grp)
        s2_lay.setSpacing(8)
        s2_lay.setContentsMargins(12, 22, 12, 12)
        l_lay.addWidget(step2_grp)

        r2 = QHBoxLayout()
        r2.addWidget(ThemeLabel("Degree:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_degree = QSpinBox()
        self.spin_degree.setRange(1, 4)
        self.spin_degree.setValue(1)
        r2.addWidget(self.spin_degree)
        s2_lay.addLayout(r2)

        self.btn_fit = QPushButton("FIT & SAVE")
        self.btn_fit.setObjectName("btn_warning")
        self.btn_fit.clicked.connect(self._fit_and_save)
        s2_lay.addWidget(self.btn_fit)

        # Status cards
        self.lbl_r2     = QLabel("-")
        self.lbl_max_err= QLabel("-")
        self.lbl_coeffs = QLabel("-")
        l_lay.addWidget(ThemeCard("R^2",      self.lbl_r2,      "PRIMARY"))
        l_lay.addWidget(ThemeCard("MAX ERROR",self.lbl_max_err, "ACCENT_RED"))
        l_lay.addStretch()
        splitter.addWidget(left_w)

        # -- RIGHT: residual plot ----------------------------------------------
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(8)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)

        # Fit curve plot
        self._fit_plot = pg.PlotWidget()
        self._fit_plot.setLabel("left",   "Corrected V", color=T.TEXT_MUTED)
        self._fit_plot.setLabel("bottom", "Measured V",  color=T.TEXT_MUTED)
        self._fit_plot.showGrid(x=True, y=True, alpha=0.15)
        self._fit_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._fit_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        # Ideal 1:1 line
        self._ideal_curve = self._fit_plot.plot(
            pen=pg.mkPen(T.TEXT_DIM, width=1, style=Qt.DashLine))
        self._fit_curve = self._fit_plot.plot(
            pen=pg.mkPen(T.PRIMARY, width=2.5),
            symbol="o", symbolSize=7, symbolBrush=T.PRIMARY)
        r_lay.addWidget(self._fit_plot, stretch=1)

        # Residuals plot
        self._res_plot = pg.PlotWidget()
        self._res_plot.setLabel("left",   "Residual (V)", color=T.TEXT_MUTED)
        self._res_plot.setLabel("bottom", "Measured V",   color=T.TEXT_MUTED)
        self._res_plot.showGrid(x=True, y=True, alpha=0.15)
        self._res_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._res_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._res_plot.addLine(
            y=0, pen=pg.mkPen(T.TEXT_DIM, width=1, style=Qt.DashLine))
        self._res_curve = self._res_plot.plot(
            pen=None,
            symbol="o", symbolSize=8, symbolBrush=T.ACCENT_AMBER)
        r_lay.addWidget(self._res_plot, stretch=1)

        cw = QHBoxLayout()
        clb = QLabel("Trace colors")
        clb.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-weight: 600;")
        cw.addWidget(clb)
        self._trace_bar = TraceColorBar(self._settings, "calibration", self)
        self._trace_bar.add_trace(
            "ideal", "1:1", "Ideal 1:1 line", "TEXT_DIM",
            items=[self._ideal_curve], width=1.0, style=Qt.DashLine,
        )
        self._trace_bar.add_trace(
            "fit", "Fit", "Fitted calibration curve", "PRIMARY",
            items=[self._fit_curve], width=2.5,
        )
        self._trace_bar.add_trace(
            "res", "Res", "Residuals (symbols)", "ACCENT_AMBER",
            items=[self._res_curve], width=1.0, draw_line=False,
        )
        cw.addWidget(self._trace_bar)
        cw.addStretch()
        r_lay.addLayout(cw)

        # Coefficients display
        coeff_grp = QGroupBox("CORRECTION POLYNOMIAL")
        cl = QVBoxLayout(coeff_grp)
        cl.setContentsMargins(10, 20, 10, 10)
        self._coeff_label = QLabel("No calibration loaded")
        self._coeff_label.setFont(_ui_font(SZ_SM))
        self._coeff_label.setStyleSheet(
            f"color: {T.ACCENT_AMBER}; white-space: pre;")
        cl.addWidget(self._coeff_label)
        r_lay.addWidget(coeff_grp)

        splitter.addWidget(right_w)
        splitter.setSizes([300, 900])

        # Show existing calibration
        if self._coeffs:
            self._show_coeffs(self._coeffs)

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        for p in (self._fit_plot, self._res_plot):
            p.setBackground(T.DARK_BG)
            p.getAxis("left").setTextPen(T.TEXT_MUTED)
            p.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        if self._trace_bar:
            self._trace_bar.refresh_theme_defaults_only()

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    def get_coefficients(self) -> Optional[List[float]]:
        return self._coeffs

    # -- Actions ---------------------------------------------------------------

    def _add_point(self):
        raw = self._dso_source()
        if len(raw) < 4:
            QMessageBox.information(self, "No Data",
                "DSO buffer is empty. Connect hardware and let samples accumulate.")
            return
        measured = float(np.mean(raw))
        ref      = self.spin_ref.value()
        self._cal_points.append((ref, measured))
        self.lbl_cur_reading.setText(f"Current reading: {measured:.4f} V")
        self._refresh_table()

    def _remove_selected(self):
        row = self._tbl.currentRow()
        if row >= 0 and row < len(self._cal_points):
            self._cal_points.pop(row)
            self._refresh_table()

    def _refresh_table(self):
        self._tbl.setRowCount(0)
        for ref, meas in self._cal_points:
            r = self._tbl.rowCount()
            self._tbl.insertRow(r)
            ref_item  = QTableWidgetItem(f"{ref:.4f}")
            meas_item = QTableWidgetItem(f"{meas:.4f}")
            ref_item.setForeground(QColor(T.ACCENT_BLUE))
            meas_item.setForeground(QColor(T.PRIMARY))
            self._tbl.setItem(r, 0, ref_item)
            self._tbl.setItem(r, 1, meas_item)

    def _fit_and_save(self):
        n = len(self._cal_points)
        if n < 2:
            QMessageBox.warning(self, "Too Few Points",
                "Add at least 2 calibration points before fitting.")
            return
        refs  = np.array([p[0] for p in self._cal_points])
        meas  = np.array([p[1] for p in self._cal_points])
        deg   = min(self.spin_degree.value(), n - 1)

        # Fit polynomial: ref = poly(measured)
        coeffs = np.polyfit(meas, refs, deg).tolist()

        # R
        predicted = np.polyval(coeffs, meas)
        ss_res    = np.sum((refs - predicted)**2)
        ss_tot    = np.sum((refs - np.mean(refs))**2)
        r2        = 1.0 - ss_res / (ss_tot + 1e-12)
        residuals = refs - predicted
        max_err   = float(np.max(np.abs(residuals)))

        self._coeffs = coeffs
        self.lbl_r2.setText(f"{r2:.6f}")
        self.lbl_max_err.setText(f"+/- {max_err*1000:.2f} mV")

        # Save
        CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        CAL_PATH.write_text(json.dumps(coeffs))

        # Update plots
        m_lin = np.linspace(min(meas), max(meas), 200)
        self._ideal_curve.setData(m_lin, m_lin)   # 1:1
        self._fit_curve.setData(meas, refs)
        self._res_curve.setData(meas, residuals)

        self._show_coeffs(coeffs)
        self.calibration_updated.emit(coeffs)
        QMessageBox.information(self, "Calibration Saved",
            f"Polynomial degree {deg}  R^2={r2:.6f}\n"
            f"Saved to {CAL_PATH}\n\n"
            f"Coefficients: {[f'{c:.6f}' for c in coeffs]}")

    def _show_coeffs(self, coeffs: List[float]):
        terms = []
        deg   = len(coeffs) - 1
        for i, c in enumerate(coeffs):
            p = deg - i
            if p == 0:
                terms.append(f"{c:+.6f}")
            elif p == 1:
                terms.append(f"{c:+.6f} * x")
            else:
                terms.append(f"{c:+.6f} * x^{p}")
        self._coeff_label.setText("V_corrected = " + " + ".join(terms).replace("+ -", "- "))

    def _reset(self):
        self._cal_points.clear()
        self._coeffs = None
        self._tbl.setRowCount(0)
        self.lbl_r2.setText("-")
        self.lbl_max_err.setText("-")
        self._coeff_label.setText("No calibration")
        self._fit_curve.setData([], [])
        self._res_curve.setData([], [])
        if CAL_PATH.exists():
            CAL_PATH.unlink()
        self.calibration_updated.emit([])
