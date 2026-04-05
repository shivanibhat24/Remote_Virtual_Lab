"""
tab_multimeter_enhanced.py - Enhanced Multimeter + DSP Filters for STM32 Lab GUI v6.0

Enhanced Features:
  * Advanced DSP filters: Butterworth, Chebyshev, FIR, Notch, Moving Average
  * Real-time waveform filtering with visual feedback
  * Multiple filter chains with cascade support
  * Filter statistics and frequency analysis
  * Export filtered waveforms
"""

import os
import datetime
from collections import deque
from pathlib import Path
from typing import Optional, List, Callable, Dict, Any

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QCheckBox, QSplitter, QMessageBox, QInputDialog,
    QMenu, QAction, QGroupBox, QListWidget, QListWidgetItem,
    QSpinBox, QTableWidget, QTableWidgetItem
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF
from PyQt5.QtGui import QFont, QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget
from data_engine import CommandBuilder, AnalyticsEngine, ParsedMessage
from plot_trace_colors import TraceColorBar

try:
    from scipy import signal as sp_signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# DSP Filter Definitions
FILTER_DEFS: Dict[str, Dict[str, Any]] = {
    "None": {
        "category": "Bypass",
        "params": [],
        "info": "No filtering - raw signal"
    },
    "Butterworth LP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0), ("Order", 4, 1, 12)],
        "info": "Low-pass Butterworth filter (zero-phase)"
    },
    "Butterworth HP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0), ("Order", 4, 1, 12)],
        "info": "High-pass Butterworth filter (zero-phase)"
    },
    "Butterworth BP": {
        "category": "Filter",
        "params": [("Low Hz", 50.0, 0.1, 50000.0),
                   ("High Hz", 500.0, 0.1, 50000.0),
                   ("Order", 4, 1, 10)],
        "info": "Band-pass Butterworth filter"
    },
    "Chebyshev I LP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0),
                   ("Order", 4, 1, 12),
                   ("Ripple dB", 0.5, 0.01, 10.0)],
        "info": "Low-pass Chebyshev Type I (equiripple)"
    },
    "Chebyshev I HP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0),
                   ("Order", 4, 1, 12),
                   ("Ripple dB", 0.5, 0.01, 10.0)],
        "info": "High-pass Chebyshev Type I (equiripple)"
    },
    "FIR Window LP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0),
                   ("Taps", 51, 3, 511)],
        "info": "FIR low-pass with Hamming window"
    },
    "Moving Average": {
        "category": "Smooth",
        "params": [("Window", 16, 3, 501)],
        "info": "Centered moving average filter"
    },
    "Savitzky-Golay": {
        "category": "Smooth",
        "params": [("Window", 11, 5, 101), ("Order", 3, 1, 5)],
        "info": "Savitzky–Golay smoothing (window must be odd)"
    },
    "Notch": {
        "category": "Filter",
        "params": [("Center Hz", 60.0, 0.5, 50000.0), ("Q", 30.0, 1.0, 200.0)],
        "info": "IIR notch filter (removes narrowband interference)"
    },
    "DC Block": {
        "category": "Filter",
        "params": [("Cutoff Hz", 1.0, 0.01, 5000.0)],
        "info": "High-pass to remove DC offset"
    },
    "Median Filter": {
        "category": "Noise",
        "params": [("Window", 5, 3, 51)],
        "info": "Median filter (removes impulse noise)"
    },
    "Gaussian Filter": {
        "category": "Smooth",
        "params": [("Sigma", 1.0, 0.1, 10.0)],
        "info": "Gaussian smoothing filter"
    }
}

class EnhancedMultimeterTab(QWidget):
    send_requested = pyqtSignal(str)

    DSO_SAMPLES   = 1000
    PLOT_FPS      = 20
    MODE_MAP      = {"Voltmeter": "V", "Ammeter": "A", "DSO": "D", "Ground": "G"}
    RANGE_MAP     = {"12 V": 12, "16 V": 16, "24 V": 24}

    def __init__(
        self,
        analytics: AnalyticsEngine,
        screenshot_provider: Optional[Callable] = None,
        settings=None,
    ):
        super().__init__()
        self._settings = settings
        self._analytics = analytics
        self._screenshot_provider = screenshot_provider
        self._external_overlays: dict = {"dsp": None, "wavedb": None}
        self._trace_bar = None
        self._dso_buf: deque = deque(maxlen=self.DSO_SAMPLES)
        self._filtered_buf: deque = deque(maxlen=self.DSO_SAMPLES)
        self._last_mode = "V"
        self._last_unit = "V"
        self.sample_period = 0.010  # default
        self._stat_cards: List[ThemeCard]    = []
        self._header_strip: Optional[_HeaderStrip] = None

        # DSP Filter state
        self._filter_chain: List[str] = []
        self._filter_params: Dict[str, List[float]] = {}
        self._filter_enabled = False
        self._show_filtered = True
        self._current_filter = "None"

        self._build_ui()
        self._refresh_val_colors()
        self._setup_dsp_filters()

    # -- UI Build --------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Enhanced Multimeter + DSP Filters")
        self._header_strip = hdr

        # Mode and Range controls
        mode_w = QWidget()
        mode_lay = QHBoxLayout(mode_w)
        mode_lay.setContentsMargins(0, 0, 0, 0)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(["Voltmeter", "Ammeter", "DSO", "Ground"])
        self.cmb_mode.currentTextChanged.connect(self._on_mode_changed)
        mode_lay.addWidget(QLabel("Mode:"))
        mode_lay.addWidget(self.cmb_mode)

        self.cmb_range = QComboBox()
        self.cmb_range.addItems(list(self.RANGE_MAP.keys()))
        self.cmb_range.setCurrentText("12 V")
        self.cmb_range.currentTextChanged.connect(self._on_range_changed)
        mode_lay.addWidget(QLabel("Range:"))
        mode_lay.addWidget(self.cmb_range)

        self.btn_send = QPushButton("SEND")
        self.btn_send.clicked.connect(self._on_send)
        mode_lay.addWidget(self.btn_send)
        mode_lay.addStretch()
        hdr_lay.addWidget(mode_w)

        # DSP Filter controls
        filter_w = QWidget()
        filter_lay = QVBoxLayout(filter_w)
        filter_lay.setContentsMargins(14, 14, 14, 14)
        filter_lay.setSpacing(12)

        # Filter Chain
        chain_grp = QGroupBox("Filter Chain")
        chain_lay = QVBoxLayout(chain_grp)
        chain_lay.setContentsMargins(12, 22, 12, 12)

        self.lst_filter_chain = QListWidget()
        self.lst_filter_chain.setMaximumHeight(120)
        chain_lay.addWidget(self.lst_filter_chain)

        # Filter selection and parameters
        filter_ctrl_lay = QHBoxLayout()
        
        # Filter selection
        filter_sel_w = QWidget()
        filter_sel_lay = QVBoxLayout(filter_sel_w)
        filter_sel_lay.addWidget(QLabel("Add Filter:"))
        
        self.cmb_filter = QComboBox()
        self.cmb_filter.addItems(list(FILTER_DEFS.keys()))
        self.cmb_filter.currentTextChanged.connect(self._on_filter_selected)
        filter_sel_lay.addWidget(self.cmb_filter)
        
        self.btn_add_filter = QPushButton("Add to Chain")
        self.btn_add_filter.clicked.connect(self._add_filter_to_chain)
        filter_sel_lay.addWidget(self.btn_add_filter)
        
        filter_ctrl_lay.addWidget(filter_sel_w)

        # Filter parameters
        self.grp_filter_params = QGroupBox("Filter Parameters")
        param_lay = QGridLayout(self.grp_filter_params)
        param_lay.setContentsMargins(12, 22, 12, 12)
        param_lay.setSpacing(10)
        self.grp_filter_params.setVisible(False)
        
        self._filter_param_widgets = []
        filter_ctrl_lay.addWidget(self.grp_filter_params)
        
        chain_lay.addLayout(filter_ctrl_lay)
        filter_lay.addWidget(chain_grp)

        # Filter control buttons
        filter_btn_lay = QHBoxLayout()
        self.btn_clear_chain = QPushButton("Clear Chain")
        self.btn_clear_chain.clicked.connect(self._clear_filter_chain)
        filter_btn_lay.addWidget(self.btn_clear_chain)
        
        self.btn_toggle_filter = QPushButton("Disable Filters")
        self.btn_toggle_filter.clicked.connect(self._toggle_filters)
        self.btn_toggle_filter.setCheckable(True)
        self.btn_toggle_filter.setChecked(True)
        filter_btn_lay.addWidget(self.btn_toggle_filter)
        
        self.btn_show_raw = QPushButton("Show Raw")
        self.btn_show_raw.clicked.connect(self._toggle_display_mode)
        self.btn_show_raw.setCheckable(True)
        self.btn_show_raw.setChecked(False)
        filter_btn_lay.addWidget(self.btn_show_raw)
        
        filter_btn_lay.addStretch()
        filter_lay.addLayout(filter_btn_lay)

        # Display and statistics
        display_w = QWidget()
        display_lay = QVBoxLayout(display_w)
        display_lay.setContentsMargins(14, 14, 14, 14)
        display_lay.setSpacing(12)

        # Value display
        val_w = QWidget()
        val_lay = QVBoxLayout(val_w)
        val_lay.setContentsMargins(0, 0, 0, 0)

        self.lbl_value = QLabel("---")
        self.lbl_value.setAlignment(Qt.AlignCenter)
        self.lbl_value.setFont(_mono_font(SZ_BIG, bold=True))

        self.lbl_unit = QLabel("SELECT MODE")
        self.lbl_unit.setAlignment(Qt.AlignCenter)
        self.lbl_unit.setFont(_ui_font(SZ_LG))

        val_lay.addWidget(self.lbl_value)
        val_lay.addWidget(self.lbl_unit)
        display_lay.addWidget(val_w, stretch=2)

        # Filter statistics
        self.grp_filter_stats = QGroupBox("Filter Statistics")
        stats_lay = QGridLayout(self.grp_filter_stats)
        stats_lay.setContentsMargins(12, 22, 12, 12)
        stats_lay.setSpacing(10)

        self.lbl_snr = QLabel("--- dB")
        self.lbl_thd = QLabel("--- %")
        self.lbl_enob = QLabel("--- bits")
        self.lbl_phase_delay = QLabel("--- samples")

        stats_lay.addWidget(ThemeLabel("SNR:", "TEXT_MUTED", SZ_SM, bold=True), 0, 0)
        stats_lay.addWidget(self.lbl_snr, 0, 1)
        stats_lay.addWidget(ThemeLabel("THD:", "TEXT_MUTED", SZ_SM, bold=True), 1, 0)
        stats_lay.addWidget(self.lbl_thd, 1, 1)
        stats_lay.addWidget(ThemeLabel("ENOB:", "TEXT_MUTED", SZ_SM, bold=True), 2, 0)
        stats_lay.addWidget(self.lbl_enob, 2, 1)
        stats_lay.addWidget(ThemeLabel("Phase Delay:", "TEXT_MUTED", SZ_SM, bold=True), 3, 0)
        stats_lay.addWidget(self.lbl_phase_delay, 3, 1)

        display_lay.addWidget(self.grp_filter_stats)
        display_lay.addStretch()

        # Plot
        plot_w = QWidget()
        plot_lay = QVBoxLayout(plot_w)
        plot_lay.setContentsMargins(8, 8, 8, 8)
        plot_lay.setSpacing(4)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(300)
        self.plot_widget.setLabel("left",   "Amplitude (V)", color=T.TEXT_MUTED)
        self.plot_widget.setLabel("bottom", "Time (s)",      color=T.TEXT_MUTED)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis("left").setTextPen(T.TEXT_MUTED)
        self.plot_widget.getAxis("bottom").setTextPen(T.TEXT_MUTED)

        # Multiple curves for different signals
        self._curve_raw = self.plot_widget.plot(pen=pg.mkPen(T.TEXT_DIM, width=1.0, style=Qt.DashLine), name="Raw")
        self._curve_filtered = self.plot_widget.plot(pen=pg.mkPen(T.PRIMARY, width=2.0), name="Filtered")
        self._curve_envelope = self.plot_widget.plot(pen=pg.mkPen(T.ACCENT_AMBER, width=1.5), name="Envelope")

        plot_lay.addWidget(self.plot_widget, stretch=1)

        # Trace color controls
        pc = QHBoxLayout()
        pl = QLabel("Trace colors")
        pl.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-weight: 600;")
        pc.addWidget(pl)
        self._trace_bar = TraceColorBar(self._settings, "multimeter", self)
        self._trace_bar.add_trace(
            "raw", "Raw", "Unfiltered signal", "TEXT_DIM",
            items=[self._curve_raw], width=1.0, style=Qt.DashLine,
        )
        self._trace_bar.add_trace(
            "filtered", "Filtered", "Filtered signal", "PRIMARY",
            items=[self._curve_filtered], width=2.0,
        )
        self._trace_bar.add_trace(
            "envelope", "Envelope", "Signal envelope", "ACCENT_AMBER",
            items=[self._curve_envelope], width=1.5,
        )
        pc.addWidget(self._trace_bar)
        pc.addStretch()
        plot_lay.addLayout(pc)

        # Add widgets to layout
        root.addWidget(hdr)
        root.addLayout(mode_lay)
        
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(filter_w)
        splitter.addWidget(display_w)
        splitter.addWidget(plot_w)
        splitter.setSizes([300, 200, 800])
        root.addWidget(splitter, stretch=1)

        # Timer for plot updates
        self._plot_timer = QTimer()
        self._plot_timer.setInterval(1000 // self.PLOT_FPS)
        self._plot_timer.timeout.connect(self._update_plot)
        self._plot_timer.start()

    # -- DSP Filter Setup -----------------------------------------------------

    def _setup_dsp_filters(self):
        """Initialize DSP filter parameters"""
        for filter_name in FILTER_DEFS:
            self._filter_params[filter_name] = [0.0] * len(FILTER_DEFS[filter_name]["params"])

    def _on_filter_selected(self, filter_name: str):
        """Update parameter widgets when filter is selected"""
        filter_def = FILTER_DEFS[filter_name]
        
        # Clear existing parameter widgets
        for widget in self._filter_param_widgets:
            widget.deleteLater()
        self._filter_param_widgets.clear()
        
        if not filter_def["params"]:
            self.grp_filter_params.setTitle("No Parameters")
            self.grp_filter_params.setVisible(True)
            return
            
        self.grp_filter_params.setTitle(f"{filter_name} Parameters")
        param_lay = self.grp_filter_params.layout()
        
        for i, (param_name, default_val, min_val, max_val) in enumerate(filter_def["params"]):
            label = ThemeLabel(f"{param_name}:", "TEXT_MUTED", SZ_SM, bold=True)
            param_lay.addWidget(label, i, 0)
            
            if isinstance(default_val, float):
                spin = QDoubleSpinBox()
                spin.setRange(min_val, max_val)
                spin.setValue(self._filter_params[filter_name][i] if self._filter_params[filter_name] else default_val)
                spin.setSingleStep(0.1 if "Hz" in param_name else 1.0)
                spin.setSuffix(" Hz" if "Hz" in param_name else (" dB" if "dB" in param_name else ""))
            else:
                spin = QSpinBox()
                spin.setRange(int(min_val), int(max_val))
                spin.setValue(int(self._filter_params[filter_name][i] if self._filter_params[filter_name] else default_val))
                
            spin.valueChanged.connect(lambda v, idx=i, fn=filter_name: self._on_param_changed(fn, idx, v))
            param_lay.addWidget(spin, i, 1)
            self._filter_param_widgets.append(spin)

        self.grp_filter_params.setVisible(True)

    def _on_param_changed(self, filter_name: str, param_idx: int, value):
        """Store filter parameter value"""
        self._filter_params[filter_name][param_idx] = float(value)

    def _add_filter_to_chain(self):
        """Add selected filter to the processing chain"""
        filter_name = self.cmb_filter.currentText()
        if filter_name not in self._filter_chain:
            self._filter_chain.append(filter_name)
            item = QListWidgetItem(filter_name)
            item.setToolTip(FILTER_DEFS[filter_name]["info"])
            self.lst_filter_chain.addItem(item)
            
            # Store current parameters
            self._filter_params[filter_name] = [
                float(widget.value()) for widget in self._filter_param_widgets
            ]

    def _clear_filter_chain(self):
        """Clear all filters from the chain"""
        self._filter_chain.clear()
        self.lst_filter_chain.clear()
        self._filtered_buf.clear()

    def _toggle_filters(self):
        """Enable/disable filter processing"""
        self._filter_enabled = self.btn_toggle_filter.isChecked()
        self.btn_toggle_filter.setText("Enable Filters" if not self._filter_enabled else "Disable Filters")

    def _toggle_display_mode(self):
        """Switch between raw and filtered display"""
        self._show_filtered = not self.btn_show_raw.isChecked()
        self.btn_show_raw.setText("Show Filtered" if not self._show_filtered else "Show Raw")

    def _apply_filters(self, data: np.ndarray) -> np.ndarray:
        """Apply filter chain to data"""
        if not self._filter_enabled or not self._filter_chain:
            return data
            
        filtered = data.copy()
        
        for filter_name in self._filter_chain:
            if filter_name == "None":
                continue
                
            params = self._filter_params.get(filter_name, [])
            filtered = self._apply_single_filter(filtered, filter_name, params)
            
        return filtered

    def _apply_single_filter(self, data: np.ndarray, filter_name: str, params: List[float]) -> np.ndarray:
        """Apply a single filter to data"""
        if not HAS_SCIPY or len(data) < 10:
            return data
            
        try:
            if filter_name == "Butterworth LP":
                sos = sp_signal.butter(int(params[1]), params[0], btype='low', analog=False, output='sos')
                return sp_signal.sosfiltfilt(sos, data)
                
            elif filter_name == "Butterworth HP":
                sos = sp_signal.butter(int(params[1]), params[0], btype='high', analog=False, output='sos')
                return sp_signal.sosfiltfilt(sos, data)
                
            elif filter_name == "Butterworth BP":
                sos = sp_signal.butter(int(params[2]), [params[0], params[1]], btype='band', analog=False, output='sos')
                return sp_signal.sosfiltfilt(sos, data)
                
            elif filter_name == "Chebyshev I LP":
                sos = sp_signal.cheby1(int(params[1]), params[2], params[0], btype='low', analog=False, output='sos')
                return sp_signal.sosfiltfilt(sos, data)
                
            elif filter_name == "Chebyshev I HP":
                sos = sp_signal.cheby1(int(params[1]), params[2], params[0], btype='high', analog=False, output='sos')
                return sp_signal.sosfiltfilt(sos, data)
                
            elif filter_name == "FIR Window LP":
                taps = sp_signal.firwin(int(params[1]), params[0], window='hamming')
                return np.convolve(data, taps, mode='same')
                
            elif filter_name == "Moving Average":
                window = int(params[0])
                if window % 2 == 0:
                    window += 1  # Make odd for symmetry
                return np.convolve(data, np.ones(window)/window, mode='same')
                
            elif filter_name == "Savitzky-Golay":
                window = int(params[0])
                order = int(params[1])
                if window % 2 == 0:
                    window += 1  # Make odd
                return sp_signal.savgol_filter(data, window, order)
                
            elif filter_name == "Notch":
                w0 = 2 * np.pi * params[0]
                Q = params[1]
                b, a = sp_signal.iirnotch(w0, Q)
                return sp_signal.filtfilt(b, a, data)
                
            elif filter_name == "DC Block":
                sos = sp_signal.butter(2, params[0], btype='high', analog=False, output='sos')
                return sp_signal.sosfiltfilt(sos, data)
                
            elif filter_name == "Median Filter":
                from scipy.ndimage import median_filter
                return median_filter(data, size=int(params[0]))
                
            elif filter_name == "Gaussian Filter":
                from scipy.ndimage import gaussian_filter1d
                return gaussian_filter1d(data, sigma=params[0])
                
        except Exception as e:
            print(f"Filter error {filter_name}: {e}")
            return data
            
        return data

    def _calculate_filter_stats(self, raw_data: np.ndarray, filtered_data: np.ndarray):
        """Calculate filter performance statistics"""
        if len(raw_data) < 100 or not HAS_SCIPY:
            self.lbl_snr.setText("--- dB")
            self.lbl_thd.setText("--- %")
            self.lbl_enob.setText("--- bits")
            self.lbl_phase_delay.setText("--- samples")
            return
            
        try:
            # SNR calculation
            signal_power = np.var(filtered_data)
            noise_power = np.var(raw_data - filtered_data)
            snr_db = 10 * np.log10(signal_power / noise_power) if noise_power > 1e-10 else 60.0
            self.lbl_snr.setText(f"{snr_db:.1f} dB")
            
            # THD calculation (for periodic signals)
            fft_raw = np.fft.fft(raw_data)
            fft_filtered = np.fft.fft(filtered_data)
            
            # Find fundamental frequency
            freqs = np.fft.fftfreq(len(raw_data), d=self.sample_period)
            fund_idx = np.argmax(np.abs(fft_filtered[1:len(fft_filtered)//2])) + 1
            
            if fund_idx < len(fft_filtered) // 2:
                fund_power = np.abs(fft_filtered[fund_idx])**2
                total_power = np.sum(np.abs(fft_filtered[1:len(fft_filtered)//2])**2)
                thd_percent = 100 * np.sqrt((total_power - fund_power) / fund_power) if fund_power > 0 else 0
                self.lbl_thd.setText(f"{thd_percent:.2f} %")
            
            # ENOB calculation
            if noise_power > 0:
                enob = (snr_db - 1.76) / 6.02  # Effective number of bits
                self.lbl_enob.setText(f"{enob:.1f} bits")
            
            # Phase delay (group delay for FIR filters)
            if self._filter_chain and "FIR" in self._filter_chain[-1]:
                taps = int(self._filter_params["FIR Window LP"][1]) if "FIR Window LP" in self._filter_params else 51
                phase_delay = (taps - 1) // 2
                self.lbl_phase_delay.setText(f"{phase_delay} samples")
            else:
                self.lbl_phase_delay.setText("N/A")
                
        except Exception as e:
            print(f"Stats calculation error: {e}")

    # -- Existing Methods (Enhanced) ------------------------------------------

    def _on_mode_changed(self):
        mode_key = self.cmb_mode.currentText()
        mode_char = self.MODE_MAP[mode_key]
        
        # Update unit display based on selected mode
        if mode_char == "V":
            self.lbl_unit.setText("VOLTS")
            self.lbl_value.setStyleSheet(
                f"color: {T.PRIMARY}; background: transparent; border: none;")
        elif mode_char == "A":
            self.lbl_unit.setText("AMPERES")
            self.lbl_value.setStyleSheet(
                f"color: {T.ACCENT_BLUE}; background: transparent; border: none;")
        elif mode_char == "D":
            self.lbl_unit.setText("VOLTS")
            self.lbl_value.setStyleSheet(
                f"color: {T.PRIMARY}; background: transparent; border: none;")
        elif mode_char == "G":
            self.lbl_unit.setText("GND")
            self.lbl_value.setStyleSheet(
                f"color: {T.TEXT_MUTED}; background: transparent; border: none;")
        else:
            self.lbl_unit.setText("SELECT MODE")
            self.lbl_value.setStyleSheet(
                f"color: {T.TEXT_MUTED}; background: transparent; border: none;")
        
        # Update range dropdown availability
        self.cmb_range.setEnabled(
            mode_char in ("V", "D"))
        
        # Clear value display when mode changes
        self.lbl_value.setText("---")

    def _on_send(self):
        mode_key  = self.cmb_mode.currentText()
        mode_char = self.MODE_MAP[mode_key]
        self.send_requested.emit(CommandBuilder.mode_cmd(mode_char))
        if mode_char in ("V", "D"):
            self.send_requested.emit(
                CommandBuilder.range_cmd(self.RANGE_MAP[self.cmb_range.currentText()]))

    def _on_range_changed(self):
        pass  # Range change handled in _on_send

    def on_data(self, msg: ParsedMessage):
        """Process incoming data and apply filters"""
        if msg.mode not in ("V", "A", "D"):
            return
            
        val = float(msg.value) if msg.value else 0.0
        
        # Update last mode/unit tracking
        if msg.mode != self._last_mode:
            self._last_mode = msg.mode
            if msg.mode == "V":
                self._last_unit = "V"
            elif msg.mode == "A":
                self._last_unit = "A"
                
        self._analytics.push(val)
        
        # Add to DSO buffer
        if msg.mode == "D":
            self._dso_buf.append(val)
            
        # Apply filters
        if len(self._dso_buf) > 0:
            raw_array = np.array(list(self._dso_buf))
            filtered_array = self._apply_filters(raw_array)
            
            # Update filtered buffer
            self._filtered_buf.clear()
            self._filtered_buf.extend(filtered_array.tolist())
            
            # Calculate filter statistics
            self._calculate_filter_stats(raw_array, filtered_array)

        # Update display
        if msg.mode == "V":
            self._last_mode = "V"; self._last_unit = "V"
            self.lbl_value.setText(f"{val:.3f}")
            self.lbl_value.setStyleSheet(
                f"color: {T.PRIMARY}; background: transparent; border: none;")
        elif msg.mode == "A":
            self._last_mode = "A"; self._last_unit = "A"
            self.lbl_value.setText(f"{val:.4f}")
            self.lbl_value.setStyleSheet(
                f"color: {T.ACCENT_BLUE}; background: transparent; border: none;")
        if getattr(self, "local_logger", None):
            self.local_logger.log_row({
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "mode": self._last_mode,
                "value_v": val if msg.mode == "V" else "",
                "value_a": val if msg.mode == "A" else ""
            })

    def _update_plot(self):
        """Update plot with filtered and raw data"""
        if len(self._dso_buf) == 0:
            return
            
        # Get data arrays
        raw_array = np.array(list(self._dso_buf))
        filtered_array = np.array(list(self._filtered_buf)) if self._filtered_buf else raw_array
        
        # Time axis
        n = min(len(raw_array), len(filtered_array))
        t = (np.arange(n, dtype=float) - (n - 1)) * self.sample_period
        
        # Update curves
        if self._show_filtered and len(filtered_array) > 0:
            self._curve_filtered.setData(t, filtered_array[:n])
            self._curve_raw.setVisible(True)
            self._curve_filtered.setVisible(True)
        else:
            self._curve_raw.setData(t, raw_array[:n])
            self._curve_raw.setVisible(True)
            self._curve_filtered.setVisible(False)
            
        # Calculate and show envelope
        if len(filtered_array) > 100:
            try:
                from scipy.signal import hilbert
                analytic_signal = hilbert(filtered_array[:n])
                envelope = np.abs(analytic_signal)
                self._curve_envelope.setData(t, envelope)
            except:
                self._curve_envelope.setData([], [])
        else:
            self._curve_envelope.setData([], [])

    def _refresh_val_colors(self):
        if self._header_strip:
            self._header_strip.update_theme()
        for card in self._stat_cards:
            card.update_theme()
        self.lbl_value.setFont(_mono_font(SZ_BIG, bold=True))
        self.lbl_unit.setFont(_ui_font(SZ_LG))
        self.plot_widget.setBackground(T.DARK_BG)
        self.plot_widget.getAxis("left").setTextPen(T.TEXT_MUTED)
        self.plot_widget.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        if self._trace_bar:
            self._trace_bar.refresh_theme_defaults_only()

    def update_theme(self):
        self._refresh_val_colors()

    def set_data_source(self, fn: Callable[[], tuple]):
        """Set data source for DSO mode"""
        self._data_source = fn

    def get_dso_buffer(self) -> deque:
        """Get current DSO buffer for external processing"""
        return self._dso_buf

    def get_filtered_buffer(self) -> deque:
        """Get current filtered buffer for external processing"""
        return self._filtered_buf
