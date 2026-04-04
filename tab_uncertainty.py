"""
tab_uncertainty.py - Uncertainty Quantification for STM32 Lab GUI v6.0

Roadmap item #7: Uncertainty Quantification & Error Bars
  * Computes confidence interval from ADC resolution + noise floor (std)
  * Displays +/- Delta V on a big readout
  * Renders shaded +/- 1 sigma / +/- 2 sigma / +/- 3 sigma uncertainty bands on the waveform plot
  * LaTeX snippet export: \SI{3.302 \pm 0.003}{\volt}
  * Updates live from the analytics engine at configurable rate
"""

import datetime
import math
from typing import Callable, Optional, List

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QDoubleSpinBox, QSpinBox,
    QGroupBox, QSplitter, QTextEdit, QCheckBox,
    QComboBox, QMessageBox, QFileDialog
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget


class UncertaintyTab(QWidget):
    """Live uncertainty quantification with LaTeX export."""

    ADC_BITS       = 12     # STM32 ADC resolution
    ADC_VREF       = 3.3    # reference voltage

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._stats_source: Callable[[], dict] = lambda: {}
        self._cal_coeffs: Optional[List[float]] = None
        self.sample_period = 0.010  # default

        # Uncertainty history for the rolling plot
        self._u_history: list = []

        self._refresh_timer = QTimer()
        self._refresh_timer.setInterval(500)   # 2 Hz
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start()

        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Uncertainty Quantification")
        self._header_strip = hdr

        self.btn_export_latex = QPushButton("EXPORT LaTeX")
        self.btn_export_latex.setObjectName("btn_warning")
        self.btn_export_latex.setFixedWidth(150)
        self.btn_export_latex.clicked.connect(self._export_latex)
        hdr_lay.addWidget(self.btn_export_latex)

        self.btn_copy = QPushButton("COPY SNIPPET")
        self.btn_copy.setFixedWidth(140)
        self.btn_copy.clicked.connect(self._copy_snippet)
        hdr_lay.addWidget(self.btn_copy)

        self.local_logger = LocalLoggerWidget("uncertainty", ["timestamp", "mean_v", "u_expanded", "k_factor", "snr_db"])
        hdr_lay.addStretch()
        hdr_lay.addWidget(self.local_logger)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: settings + big readout -------------------------------------
        left_w = QWidget()
        left_w.setMaximumWidth(340)
        l_lay = QVBoxLayout(left_w)
        l_lay.setContentsMargins(14, 14, 14, 14)
        l_lay.setSpacing(12)

        # Big +/- Delta V readout
        readout_grp = QGroupBox("MEASUREMENT WITH UNCERTAINTY")
        rl = QVBoxLayout(readout_grp)
        rl.setContentsMargins(12, 24, 12, 12)
        rl.setSpacing(6)
        self.lbl_main = QLabel("- V")
        self.lbl_main.setAlignment(Qt.AlignCenter)
        self.lbl_main.setFont(_ui_font(SZ_BIG, bold=True))
        self.lbl_main.setStyleSheet(
            f"color: {T.PRIMARY}; background: transparent; border: none;")
        self.lbl_uncertainty = QLabel("+/- -")
        self.lbl_uncertainty.setAlignment(Qt.AlignCenter)
        self.lbl_uncertainty.setFont(_ui_font(SZ_STAT))
        self.lbl_uncertainty.setStyleSheet(
            f"color: {T.ACCENT_AMBER}; background: transparent; border: none;")
        self.lbl_conf = QLabel("95% confidence interval")
        self.lbl_conf.setAlignment(Qt.AlignCenter)
        self.lbl_conf.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; background: transparent; border: none;")
        rl.addWidget(self.lbl_main)
        rl.addWidget(self.lbl_uncertainty)
        rl.addWidget(self.lbl_conf)
        l_lay.addWidget(readout_grp)

        # Parameters
        param_grp = QGroupBox("UNCERTAINTY PARAMETERS")
        pg_lay = QGridLayout(param_grp)
        pg_lay.setSpacing(8)
        pg_lay.setContentsMargins(12, 24, 12, 12)

        pg_lay.addWidget(ThemeLabel("ADC Bits:", "TEXT_MUTED", SZ_SM, bold=True), 0, 0)
        self.spin_bits = QSpinBox()
        self.spin_bits.setRange(8, 16)
        self.spin_bits.setValue(self.ADC_BITS)
        pg_lay.addWidget(self.spin_bits, 0, 1)

        pg_lay.addWidget(ThemeLabel("Vref:", "TEXT_MUTED", SZ_SM, bold=True), 1, 0)
        self.spin_vref = QDoubleSpinBox()
        self.spin_vref.setRange(1.0, 5.5)
        self.spin_vref.setValue(self.ADC_VREF)
        self.spin_vref.setSuffix(" V")
        self.spin_vref.setDecimals(2)
        pg_lay.addWidget(self.spin_vref, 1, 1)

        pg_lay.addWidget(ThemeLabel("Confidence:", "TEXT_MUTED", SZ_SM, bold=True), 2, 0)
        self.cmb_conf = QComboBox()
        self.cmb_conf.addItems(["68% (1 sigma)", "95% (2 sigma)", "99.7% (3 sigma)"])
        self.cmb_conf.setCurrentIndex(1)
        pg_lay.addWidget(self.cmb_conf, 2, 1)

        pg_lay.addWidget(ThemeLabel("Cal. correction:", "TEXT_MUTED", SZ_SM, bold=True), 3, 0)
        self.chk_cal = QCheckBox("Apply")
        self.chk_cal.setToolTip("Apply polynomial calibration coefficients if loaded")
        pg_lay.addWidget(self.chk_cal, 3, 1)

        l_lay.addWidget(param_grp)

        # Stat cards
        self.lbl_u_quant = QLabel("-")
        self.lbl_u_noise = QLabel("-")
        self.lbl_u_total = QLabel("-")
        self.lbl_u_snr   = QLabel("-")
        for lbl, name, col in [
            (self.lbl_u_quant, "U QUANT",  "ACCENT_BLUE"),
            (self.lbl_u_noise, "U NOISE",  "ACCENT_PUR"),
            (self.lbl_u_total, "U TOTAL",  "ACCENT_AMBER"),
            (self.lbl_u_snr,   "SNR EST",  "PRIMARY"),
        ]:
            l_lay.addWidget(ThemeCard(name, lbl, col))

        # LaTeX snippet box
        latex_grp = QGroupBox("LaTeX SNIPPET")
        ll = QVBoxLayout(latex_grp)
        ll.setContentsMargins(10, 20, 10, 10)
        self._latex_box = QTextEdit()
        self._latex_box.setReadOnly(True)
        self._latex_box.setFont(_ui_font(SZ_BODY))
        self._latex_box.setMaximumHeight(80)
        self._latex_box.setStyleSheet(
            f"background: {T.CARD_BG}; color: {T.ACCENT_AMBER}; border: 1px solid {T.BORDER};")
        ll.addWidget(self._latex_box)
        l_lay.addWidget(latex_grp)
        l_lay.addStretch()

        splitter.addWidget(left_w)

        # -- RIGHT: waveform with uncertainty bands ----------------------------
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(6)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)

        self._plot = pg.PlotWidget()
        self._plot.setLabel("left",   "Voltage (V) with +/- sigma bands", color=T.TEXT_MUTED)
        self._plot.setLabel("bottom", "Sample index",               color=T.TEXT_MUTED)
        self._plot.showGrid(x=True, y=True, alpha=0.12)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

        self._curve_main  = self._plot.plot(pen=pg.mkPen(T.ACCENT_BLUE, width=2))

        # Uncertainty band curves (FillBetweenItem needs PlotDataItem refs)
        self._band1_hi = self._plot.plot(pen=None)   # +1 sigma boundary
        self._band1_lo = self._plot.plot(pen=None)   # -1 sigma boundary
        self._band2_hi = self._plot.plot(pen=None)   # +k sigma boundary
        self._band2_lo = self._plot.plot(pen=None)   # -k sigma boundary

        self._curve_band1 = pg.FillBetweenItem(
            self._band1_lo, self._band1_hi,
            brush=pg.mkBrush(QColor(T.ACCENT_AMBER + "30")))
        self._curve_band2 = pg.FillBetweenItem(
            self._band2_lo, self._band2_hi,
            brush=pg.mkBrush(QColor(T.ACCENT_AMBER + "18")))
        self._plot.addItem(self._curve_band1)
        self._plot.addItem(self._curve_band2)

        # Rolling uncertainty history mini-plot
        self._plot2 = pg.PlotWidget()
        self._plot2.setFixedHeight(120)
        self._plot2.setLabel("left",   "+/- U (V)", color=T.TEXT_MUTED)
        self._plot2.setLabel("bottom", "Time",   color=T.TEXT_MUTED)
        self._plot2.showGrid(x=True, y=True, alpha=0.12)
        self._plot2.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot2.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._uhist_curve = self._plot2.plot(pen=pg.mkPen(T.PRIMARY, width=2))

        r_lay.addWidget(self._plot, stretch=1)
        r_lay.addWidget(self._plot2)

        splitter.addWidget(right_w)
        splitter.setSizes([320, 900])

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        if getattr(self, "local_logger", None):
            self.local_logger.update_theme()
        for p in (self._plot, self._plot2):
            p.setBackground(T.DARK_BG)
            p.getAxis("left").setTextPen(T.TEXT_MUTED)
            p.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self.lbl_main.setStyleSheet(
            f"color: {T.PRIMARY}; background: transparent; border: none;")
        self.lbl_uncertainty.setStyleSheet(
            f"color: {T.ACCENT_AMBER}; background: transparent; border: none;")

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    def set_stats_source(self, fn: Callable[[], dict]):
        self._stats_source = fn

    def set_calibration(self, coeffs):
        """Inject polynomial calibration coefficients."""
        self._cal_coeffs = coeffs

    # -- Computation -----------------------------------------------------------

    def _sigma_multiplier(self) -> float:
        """Return k factor for chosen confidence interval."""
        return [1.0, 2.0, 3.0][self.cmb_conf.currentIndex()]

    def _compute_uncertainty(self, data: np.ndarray) -> dict:
        n    = len(data)
        if n == 0:
            return {}

        # Quantization uncertainty (half-LSB, uniform distribution -> /sqrt(3))
        lsb         = self.spin_vref.value() / (2 ** self.spin_bits.value())
        u_quant     = lsb / (2.0 * math.sqrt(3))

        # Random noise uncertainty (std of the mean)
        std         = float(np.std(data))
        u_noise     = std / math.sqrt(n)

        # Apply calibration scaling if available
        if self.chk_cal.isChecked() and self._cal_coeffs:
            # Derivative of poly at mean -> error scaling factor
            mean = float(np.mean(data))
            # polyval order is highest-degree first (np.polyval convention)
            dp   = abs(np.polyval(np.polyder(self._cal_coeffs), mean))
            u_quant *= dp
            u_noise *= dp

        # Combined standard uncertainty
        u_combined  = math.sqrt(u_quant**2 + u_noise**2)

        # Expanded uncertainty at chosen confidence level
        k           = self._sigma_multiplier()
        u_expanded  = k * u_combined
        conf_label  = ["68%", "95%", "99.7%"][self.cmb_conf.currentIndex()]

        # Estimate SNR
        mean  = float(np.mean(data))
        snr_db = 20.0 * math.log10(abs(mean) / (std + 1e-12)) if std > 0 else 0.0

        return {
            "mean":       float(np.mean(data)),
            "u_quant":    u_quant,
            "u_noise":    u_noise,
            "u_combined": u_combined,
            "u_expanded": u_expanded,
            "k":          k,
            "conf":       conf_label,
            "std":        std,
            "n":          n,
            "snr_db":     snr_db,
        }

    # -- Live Refresh ----------------------------------------------------------

    def _refresh(self):
        raw  = self._dso_source()
        if len(raw) < 4:
            return
        arr  = np.array(raw, dtype=float)
        res  = self._compute_uncertainty(arr)
        if not res:
            return

        mean = res["mean"]
        u    = res["u_expanded"]
        self.lbl_main.setText(f"{mean:.4f} V")
        self.lbl_uncertainty.setText(f"+/- {u*1000:.3f} mV")
        self.lbl_conf.setText(f"{res['conf']} confidence (k={res['k']:.0f})")

        self.lbl_u_quant.setText(f"{res['u_quant']*1000:.4f} mV")
        self.lbl_u_noise.setText(f"{res['u_noise']*1000:.4f} mV")
        self.lbl_u_total.setText(f"{res['u_combined']*1000:.4f} mV")
        self.lbl_u_snr.setText(f"{res['snr_db']:.1f} dB")

        # Update LaTeX snippet
        self._generate_latex(mean, u, res["conf"])

        # Update waveform + bands
        xs = np.arange(len(arr))
        self._curve_main.setData(xs, arr)

        k   = self._sigma_multiplier()
        u_c = res["u_combined"]
        # Band 1: +/- 1 sigma
        self._band1_hi.setData(xs, arr + u_c)
        self._band1_lo.setData(xs, arr - u_c)
        # Band 2: +/- k sigma expanded
        self._band2_hi.setData(xs, arr + u_c * k)
        self._band2_lo.setData(xs, arr - u_c * k)

        # Rolling history
        self._u_history.append(u)
        if len(self._u_history) > 200:
            self._u_history = self._u_history[-200:]
        self._uhist_curve.setData(np.arange(len(self._u_history)), np.array(self._u_history))
        
        if getattr(self, "local_logger", None):
            self.local_logger.log({
                "mean_v": mean,
                "u_expanded": u,
                "k_factor": k,
                "snr_db": res["snr_db"]
            })

    # -- LaTeX -----------------------------------------------------------------

    def _generate_latex(self, mean: float, u: float, conf: str):
        snippet = (
            f"% Measurement with expanded uncertainty ({conf})\n"
            f"\\SI{{{mean:.4f} \\pm {u:.4f}}}{{\\volt}}\n\n"
            f"% Or with siunitx tabular format:\n"
            f"$({mean:.4f} \\pm {u:.4f})\\,\\mathrm{{V}}$"
        )
        self._latex_box.setPlainText(snippet)
        return snippet

    def _copy_snippet(self):
        from PyQt5.QtWidgets import QApplication
        QApplication.clipboard().setText(self._latex_box.toPlainText())

    def _export_latex(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export LaTeX Snippet",
            f"uncertainty_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.tex",
            "TeX Files (*.tex)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._latex_box.toPlainText())
            QMessageBox.information(self, "Exported", f"LaTeX snippet saved to:\n{path}")
