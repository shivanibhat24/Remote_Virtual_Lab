"""
tab_dsp_enhanced.py - Enhanced DSP tab with live signal visualization for STM32 Lab GUI v6.0

Enhanced Features:
  * Live signal display showing raw and filtered signals
  * Real-time waveform visualization with multiple traces
  * Before/after comparison for filter effects
  * Live statistics and performance metrics
  * Interactive filter parameter adjustment
"""

import math
from typing import Optional, List, Callable, Dict, Any

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QSpinBox, QGroupBox, QListWidget, QListWidgetItem,
    QSplitter, QTableWidget, QTableWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header, LocalLoggerWidget

try:
    from scipy import signal as sp_signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# Block Definitions
BLOCK_DEFS: Dict[str, Dict[str, Any]] = {
    "Butterworth LP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0), ("Order", 4, 1, 12)],
        "info": "Low-pass Butterworth filter (filtfilt, zero-phase)"
    },
    "Butterworth HP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0), ("Order", 4, 1, 12)],
        "info": "High-pass Butterworth filter"
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
        "info": "Low-pass Chebyshev Type I"
    },
    "Chebyshev I HP": {
        "category": "Filter",
        "params": [("Cutoff Hz", 100.0, 0.1, 50000.0),
                   ("Order", 4, 1, 12),
                   ("Ripple dB", 0.5, 0.01, 10.0)],
        "info": "High-pass Chebyshev Type I"
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
        "info": "Centered moving average (same length as input)"
    },
    "Savitzky-Golay": {
        "category": "Smooth",
        "params": [("Window", 11, 5, 101), ("Order", 3, 1, 5)],
        "info": "Savitzky–Golay smoothing (window must be odd)"
    },
    "Notch": {
        "category": "Filter",
        "params": [("Center Hz", 60.0, 0.5, 50000.0), ("Q", 30.0, 1.0, 200.0)],
        "info": "IIR notch (removes narrowband interference, e.g. mains)"
    },
    "DC Block (HPF)": {
        "category": "Filter",
        "params": [("Cutoff Hz", 1.0, 0.01, 5000.0), ("Order", 2, 1, 6)],
        "info": "High-pass to remove DC and slow drift"
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

class PipelineBlock:
    def __init__(self, name: str, defn: Dict[str, Any]):
        self.name = name
        self.defn = defn
        self.values = [p[1] for p in defn["params"]]

class EnhancedDSPTab(QWidget):
    """Enhanced DSP tab with live signal visualization"""
    
    # Emits processed signal array + measurement dict for overlaying on DSO
    overlay_ready = pyqtSignal(object)   # np.ndarray
    
    def __init__(self):
        super().__init__()
        self._blocks: List[PipelineBlock]    = []
        self._param_widgets: List[QWidget]         = []   # current param panel widgets
        self._selected_block_idx = -1
        self._dso_source: Callable[[], list] = lambda: []
        self._sample_period: float = 0.010
        self._filter_enabled = True
        self._header_strip: Optional[_HeaderStrip] = None
        
        # Live signal buffers
        self._raw_buffer: List[float] = []
        self._filtered_buffer: List[float] = []
        self._max_display_points = 1000
        
        # Live statistics
        self._live_stats = {
            'snr_db': 0.0,
            'thd_percent': 0.0,
            'enob_bits': 0.0,
            'rms_raw': 0.0,
            'rms_filtered': 0.0,
            'peak_raw': 0.0,
            'peak_filtered': 0.0
        }
        
        self._build_ui()

    # -- UI Build --------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Enhanced DSP Signal Processing")
        self._header_strip = hdr

        # Filter controls
        filter_w = QWidget()
        filter_lay = QVBoxLayout(filter_w)
        filter_lay.setContentsMargins(14, 14, 14, 14)
        filter_lay.setSpacing(12)

        # Filter chain list
        chain_grp = QGroupBox("Filter Chain")
        chain_lay = QVBoxLayout(chain_grp)
        chain_lay.setContentsMargins(12, 22, 12, 12)

        self.lst_blocks = QListWidget()
        self.lst_blocks.setMaximumHeight(150)
        chain_lay.addWidget(self.lst_blocks)

        # Filter selection
        filter_sel_w = QWidget()
        filter_sel_lay = QVBoxLayout(filter_sel_w)
        filter_sel_lay.addWidget(QLabel("Add Block:"))
        
        self.cmb_block = QComboBox()
        self.cmb_block.addItems(list(BLOCK_DEFS.keys()))
        self.cmb_block.currentTextChanged.connect(self._on_block_selected)
        filter_sel_lay.addWidget(self.cmb_block)
        
        self.btn_add = QPushButton("Add to Chain")
        self.btn_add.clicked.connect(self._add_block)
        filter_sel_lay.addWidget(self.btn_add)
        
        filter_ctrl_lay = QHBoxLayout()
        filter_ctrl_lay.addWidget(filter_sel_w)
        chain_lay.addLayout(filter_ctrl_lay)

        # Parameter panel
        self._param_outer = QVBoxLayout(filter_w)
        self._param_group = QGroupBox("BLOCK PARAMETERS")
        self._param_inner = QVBoxLayout(self._param_group)
        self._param_inner.setSpacing(8)
        self._param_inner.setContentsMargins(10, 22, 12, 12)
        self._param_outer.addWidget(self._param_group)
        filter_lay.addWidget(self._param_outer)

        # Control buttons
        control_btn_lay = QHBoxLayout()
        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.clicked.connect(self._clear_all)
        control_btn_lay.addWidget(self.btn_clear)
        
        self.btn_run = QPushButton("RUN PIPELINE")
        self.btn_run.setObjectName("btn_primary")
        self.btn_run.clicked.connect(self._run_pipeline)
        control_btn_lay.addWidget(self.btn_run)
        
        self.btn_toggle = QPushButton("Disable Filters")
        self.btn_toggle.clicked.connect(self._toggle_filters)
        self.btn_toggle.setCheckable(True)
        self.btn_toggle.setChecked(True)
        control_btn_lay.addWidget(self.btn_toggle)
        
        control_btn_lay.addStretch()
        filter_lay.addLayout(control_btn_lay)
        root.addLayout(filter_lay)

        # Live signal display
        signal_w = QWidget()
        signal_lay = QVBoxLayout(signal_w)
        signal_lay.setContentsMargins(14, 14, 14, 14)
        signal_lay.setSpacing(12)

        # Signal plot
        plot_grp = QGroupBox("Live Signal Display")
        plot_lay = QVBoxLayout(plot_grp)
        plot_lay.setContentsMargins(12, 22, 12, 12)
        plot_lay.setSpacing(8)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(350)
        self.plot_widget.setLabel("left", "Amplitude (V)", color=T.TEXT_MUTED)
        self.plot_widget.setLabel("bottom", "Time (s)", color=T.TEXT_MUTED)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis("left").setTextPen(T.TEXT_MUTED)
        self.plot_widget.getAxis("bottom").setTextPen(T.TEXT_MUTED)

        # Multiple curves for different signals
        self._curve_raw = self.plot_widget.plot(
            pen=pg.mkPen(T.TEXT_DIM, width=1.5, style=Qt.DashLine), 
            name="Raw Signal"
        )
        self._curve_filtered = self.plot_widget.plot(
            pen=pg.mkPen(T.PRIMARY, width=2.0), 
            name="Filtered Signal"
        )
        self._curve_envelope = self.plot_widget.plot(
            pen=pg.mkPen(T.ACCENT_AMBER, width=1.5), 
            name="Envelope"
        )

        plot_lay.addWidget(self.plot_widget, stretch=1)
        signal_lay.addWidget(plot_grp)

        # Live statistics
        stats_grp = QGroupBox("Live Statistics")
        stats_lay = QGridLayout(stats_grp)
        stats_lay.setContentsMargins(12, 22, 12, 12)
        stats_lay.setSpacing(10)

        # RMS values
        stats_lay.addWidget(ThemeLabel("RMS Raw:", "TEXT_MUTED", SZ_SM, bold=True), 0, 0)
        self.lbl_rms_raw = QLabel("0.000 V")
        stats_lay.addWidget(self.lbl_rms_raw, 0, 1)
        
        stats_lay.addWidget(ThemeLabel("RMS Filtered:", "TEXT_MUTED", SZ_SM, bold=True), 1, 0)
        self.lbl_rms_filtered = QLabel("0.000 V")
        stats_lay.addWidget(self.lbl_rms_filtered, 1, 1)
        
        # Peak values
        stats_lay.addWidget(ThemeLabel("Peak Raw:", "TEXT_MUTED", SZ_SM, bold=True), 2, 0)
        self.lbl_peak_raw = QLabel("0.000 V")
        stats_lay.addWidget(self.lbl_peak_raw, 2, 1)
        
        stats_lay.addWidget(ThemeLabel("Peak Filtered:", "TEXT_MUTED", SZ_SM, bold=True), 3, 0)
        self.lbl_peak_filtered = QLabel("0.000 V")
        stats_lay.addWidget(self.lbl_peak_filtered, 3, 1)
        
        # Filter performance
        stats_lay.addWidget(ThemeLabel("SNR:", "TEXT_MUTED", SZ_SM, bold=True), 0, 2)
        self.lbl_snr = QLabel("--- dB")
        stats_lay.addWidget(self.lbl_snr, 0, 3)
        
        stats_lay.addWidget(ThemeLabel("THD:", "TEXT_MUTED", SZ_SM, bold=True), 1, 2)
        self.lbl_thd = QLabel("--- %")
        stats_lay.addWidget(self.lbl_thd, 1, 3)
        
        stats_lay.addWidget(ThemeLabel("ENOB:", "TEXT_MUTED", SZ_SM, bold=True), 2, 2)
        self.lbl_enob = QLabel("--- bits")
        stats_lay.addWidget(self.lbl_enob, 2, 3)
        
        # Status
        stats_lay.addWidget(ThemeLabel("Status:", "TEXT_MUTED", SZ_SM, bold=True), 0, 3)
        self.lbl_status = QLabel("Pipeline idle")
        stats_lay.addWidget(self.lbl_status, 1, 3)
        
        signal_lay.addWidget(stats_grp)

        # Results table
        results_grp = QGroupBox("Processing Results")
        results_lay = QVBoxLayout(results_grp)
        results_lay.setContentsMargins(12, 22, 12, 12)
        
        self._result_table = QTableWidget(0, 2)
        self._result_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self._result_table.setMaximumHeight(150)
        results_lay.addWidget(self._result_table)
        signal_lay.addWidget(results_grp)

        root.addWidget(signal_w, stretch=1)
        hdr_lay.addWidget(self.btn_run)
        root.addWidget(hdr)

        # Timer for live updates
        self._update_timer = QTimer()
        self._update_timer.setInterval(50)  # 20 FPS update
        self._update_timer.timeout.connect(self._update_live_display)
        self._update_timer.start()

    # -- Block Management ----------------------------------------------------

    def _on_block_selected(self, block_name: str):
        """Update parameter widgets when block is selected"""
        block_def = BLOCK_DEFS.get(block_name, {})
        
        # Clear existing parameter widgets
        for widget in self._param_widgets:
            widget.deleteLater()
        self._param_widgets.clear()
        
        if not block_def.get("params"):
            self._param_group.setTitle("No Parameters")
            self._param_group.setVisible(True)
            return
            
        self._param_group.setTitle(f"{block_name} Parameters")
        param_lay = self._param_inner.layout()
        
        for i, (param_name, default_val, min_val, max_val) in enumerate(block_def["params"]):
            label = ThemeLabel(f"{param_name}:", "TEXT_MUTED", SZ_SM, bold=True)
            param_lay.addWidget(label, i, 0)
            
            if isinstance(default_val, float):
                spin = QDoubleSpinBox()
                spin.setRange(min_val, max_val)
                spin.setValue(default_val)
                spin.setSingleStep(0.1 if "Hz" in param_name else 1.0)
                spin.setSuffix(" Hz" if "Hz" in param_name else (" dB" if "dB" in param_name else ""))
            else:
                spin = QSpinBox()
                spin.setRange(int(min_val), int(max_val))
                spin.setValue(int(default_val))
                
            spin.valueChanged.connect(lambda v, idx=i, b=block_name: self._on_param_change(b, idx, v))
            param_lay.addWidget(spin, i, 1)
            self._param_widgets.append(spin)

        self._param_group.setVisible(True)

    def _on_param_change(self, block_name: str, idx: int, value):
        """Store block parameter value"""
        if self._selected_block_idx >= 0 and self._selected_block_idx < len(self._blocks):
            block = self._blocks[self._selected_block_idx]
            if 0 <= idx < len(block.values):
                block.values[idx] = float(value)

    def _add_block(self):
        """Add selected block to pipeline"""
        block_name = self.cmb_block.currentText()
        block_def = BLOCK_DEFS[block_name]
        block = PipelineBlock(block_name, block_def)
        
        self._blocks.append(block)
        item = QListWidgetItem(block_name)
        item.setToolTip(block_def["info"])
        self.lst_blocks.addItem(item)
        
        # Select the newly added block
        self._selected_block_idx = len(self._blocks) - 1
        self.lst_blocks.setCurrentRow(self._selected_block_idx)
        self._on_block_selected(block_name)

    def _clear_all(self):
        """Clear all blocks and reset display"""
        self._blocks.clear()
        self.lst_blocks.clear()
        self._raw_buffer.clear()
        self._filtered_buffer.clear()
        self._selected_block_idx = -1
        self._clear_param_panel()
        self._reset_live_stats()

    def _toggle_filters(self):
        """Enable/disable filter processing"""
        self._filter_enabled = self.btn_toggle.isChecked()
        self.btn_toggle.setText("Enable Filters" if not self._filter_enabled else "Disable Filters")

    def _reset_live_stats(self):
        """Reset live statistics"""
        self._live_stats = {
            'snr_db': 0.0,
            'thd_percent': 0.0,
            'enob_bits': 0.0,
            'rms_raw': 0.0,
            'rms_filtered': 0.0,
            'peak_raw': 0.0,
            'peak_filtered': 0.0
        }

    # -- Signal Processing ----------------------------------------------------

    def _run_pipeline(self):
        """Process current DSO buffer through filter chain"""
        if not HAS_SCIPY:
            QMessageBox.warning(self, "SciPy Missing", 
                "DSP processing requires SciPy. Install with: pip install scipy")
            return
            
        raw = self._dso_source()
        if len(raw) < 8:
            QMessageBox.information(self, "No Data",
                "DSO buffer is empty - connect hardware or use Playback mode.")
            return

        x = np.asarray(raw, dtype=float)
        fs = 1.0 / max(self._sample_period, 1e-12)
        results = {}

        # Apply all blocks in sequence
        for block in self._blocks:
            name = block.name
            vals = block.values
            cat = block.defn["category"]
            
            try:
                if cat == "Filter":
                    x = self._apply_filter(name, x, vals, fs)
                elif cat == "Smooth":
                    x = self._apply_smooth(name, x, vals, fs)
                elif name == "Hilbert Envelope":
                    x = np.abs(sp_signal.hilbert(x))
                elif cat == "Measure":
                    self._apply_measure(name, x, vals, fs, results)
                    
            except Exception as e:
                self.lbl_status.setText(f"Error in [{name}]: {e}")
                return

        # Update live buffers
        self._raw_buffer = raw[-self._max_display_points:].copy()
        self._filtered_buffer = x[-self._max_display_points:].copy()

        # Calculate live statistics
        self._calculate_live_stats(raw[-self._max_display_points:], x[-self._max_display_points:])

        # Emit overlay signal
        self.overlay_ready.emit(x)
        self.lbl_status.setText(
            f"Pipeline OK - {len(self._blocks)} blocks, {len(x)} samples")
        self._update_result_table(results)

    def _apply_filter(self, name: str, x: np.ndarray, vals: List[float], fs: float) -> np.ndarray:
        """Apply a single filter to data"""
        nyq = fs / 2.0
        
        if name == "Butterworth LP":
            cutoff, order = vals[0] / nyq, int(vals[1])
            b, a = sp_signal.butter(order, min(cutoff, 0.999), btype='low')
            return sp_signal.filtfilt(b, a, x)
            
        elif name == "Butterworth HP":
            cutoff, order = vals[0] / nyq, int(vals[1])
            b, a = sp_signal.butter(order, min(cutoff, 0.999), btype='high')
            return sp_signal.filtfilt(b, a, x)
            
        elif name == "Butterworth BP":
            lo, hi, order = vals[0]/nyq, vals[1]/nyq, int(vals[2])
            lo = min(lo, 0.998); hi = min(hi, 0.999)
            if lo >= hi: hi = lo + 0.001
            b, a = sp_signal.butter(order, [lo, hi], btype='band')
            return sp_signal.filtfilt(b, a, x)
            
        elif name == "Chebyshev I LP":
            cutoff, order, rp = vals[0] / nyq, int(vals[1]), vals[2]
            b, a = sp_signal.cheby1(order, rp, min(cutoff, 0.999), btype='low')
            return sp_signal.filtfilt(b, a, x)
            
        elif name == "Chebyshev I HP":
            cutoff, order, rp = vals[0] / nyq, int(vals[1]), vals[2]
            b, a = sp_signal.cheby1(order, rp, min(cutoff, 0.999), btype='high')
            return sp_signal.filtfilt(b, a, x)
            
        elif name == "FIR Window LP":
            cutoff, taps = vals[0] / nyq, int(vals[1]) | 1  # ensure odd taps
            b = sp_signal.firwin(taps, min(max(cutoff, 1e-6), 0.999), window='hamming')
            return sp_signal.filtfilt(b, [1.0], x)
            
        elif name == "Moving Average":
            window = int(vals[0])
            if window % 2 == 0:
                window += 1  # Make odd for symmetry
            return np.convolve(x, np.ones(window)/window, mode='same')
            
        elif name == "Savitzky-Golay":
            window, order = int(vals[0]), int(vals[1])
            if window % 2 == 0:
                window += 1  # Make odd
            return sp_signal.savgol_filter(x, window, order)
            
        elif name == "Notch":
            w0 = 2 * np.pi * vals[0]
            Q = vals[1]
            b, a = sp_signal.iirnotch(w0, Q)
            return sp_signal.filtfilt(b, a, x)
            
        elif name == "DC Block (HPF)":
            cutoff, order = vals[0] / nyq, int(vals[1])
            b, a = sp_signal.butter(order, cutoff, btype='high')
            return sp_signal.filtfilt(b, a, x)
            
        return x

    def _apply_smooth(self, name: str, x: np.ndarray, vals: List[float], fs: float) -> np.ndarray:
        """Apply smoothing filter"""
        if name == "Savitzky-Golay":
            window, order = int(vals[0]), int(vals[1])
            if window % 2 == 0:
                window += 1  # Make odd
            return sp_signal.savgol_filter(x, window, order)
        else:
            return x

    def _apply_measure(self, name: str, x: np.ndarray, vals: List[float], fs: float, results: Dict[str, str]):
        """Apply measurement block"""
        if name == "SNR/SINAD":
            # Calculate Signal-to-Noise Ratio
            signal_power = np.var(x)
            noise_power = np.var(np.diff(x))
            snr_db = 10 * np.log10(signal_power / noise_power) if noise_power > 1e-10 else 60.0
            results["SNR"] = f"{snr_db:.1f} dB"
        elif name == "THD":
            # Total Harmonic Distortion
            fft_x = np.fft.fft(x)
            freqs = np.fft.fftfreq(len(x), d=1/fs)
            
            # Find fundamental
            fund_idx = np.argmax(np.abs(fft_x[1:len(fft_x)//2])) + 1
            if fund_idx < len(fft_x) // 2:
                fund_power = np.abs(fft_x[fund_idx])**2
                total_power = np.sum(np.abs(fft_x[1:len(fft_x)//2])**2)
                thd_percent = 100 * np.sqrt((total_power - fund_power) / fund_power) if fund_power > 0 else 0
                results["THD"] = f"{thd_percent:.2f} %"
        elif name == "ENOB":
            # Effective Number of Bits
            fft_x = np.fft.fft(x)
            signal_power = np.sum(np.abs(fft_x[1:len(fft_x)//2])**2)
            noise_power = np.sum(np.abs(fft_x[len(fft_x)//2+1:])**2)
            if noise_power > 0:
                snr_db = 10 * np.log10(signal_power / noise_power)
                enob = (snr_db - 1.76) / 6.02
                results["ENOB"] = f"{enob:.1f} bits"

    def _calculate_live_stats(self, raw_data: np.ndarray, filtered_data: np.ndarray):
        """Calculate live statistics for display"""
        if len(raw_data) == 0:
            return
            
        # RMS values
        self._live_stats['rms_raw'] = np.sqrt(np.mean(raw_data**2))
        self._live_stats['rms_filtered'] = np.sqrt(np.mean(filtered_data**2))
        
        # Peak values
        self._live_stats['peak_raw'] = np.max(np.abs(raw_data))
        self._live_stats['peak_filtered'] = np.max(np.abs(filtered_data))
        
        # SNR calculation
        signal_power = np.var(filtered_data)
        noise_power = np.var(raw_data - filtered_data)
        if noise_power > 1e-10:
            self._live_stats['snr_db'] = 10 * np.log10(signal_power / noise_power)
        else:
            self._live_stats['snr_db'] = 60.0
            
        # THD calculation (simplified for live display)
        try:
            from scipy.signal import hilbert
            analytic_signal = hilbert(filtered_data)
            envelope = np.abs(analytic_signal)
            
            # Estimate fundamental frequency
            fft_filtered = np.fft.fft(filtered_data)
            fund_idx = np.argmax(np.abs(fft_filtered[1:len(fft_filtered)//2])) + 1
            
            if fund_idx < len(fft_filtered) // 2:
                fund_power = np.abs(fft_filtered[fund_idx])**2
                total_power = np.sum(np.abs(fft_filtered[1:len(fft_filtered)//2])**2)
                self._live_stats['thd_percent'] = 100 * np.sqrt((total_power - fund_power) / fund_power) if fund_power > 0 else 0
        except:
            pass
            
        # ENOB calculation
        if noise_power > 0:
            snr_db = self._live_stats['snr_db']
            self._live_stats['enob_bits'] = (snr_db - 1.76) / 6.02

    def _update_live_display(self):
        """Update live signal display and statistics"""
        if len(self._raw_buffer) == 0:
            return
            
        # Time axis
        n = min(len(self._raw_buffer), len(self._filtered_buffer))
        t = (np.arange(n, dtype=float) - (n - 1)) * self._sample_period
        
        # Update signal curves
        self._curve_raw.setData(t, self._raw_buffer[:n])
        
        if self._filter_enabled and len(self._filtered_buffer) > 0:
            self._curve_filtered.setData(t, self._filtered_buffer[:n])
            self._curve_filtered.setVisible(True)
        else:
            self._curve_filtered.setVisible(False)
            
        # Update envelope (simplified)
        if self._filter_enabled and len(self._filtered_buffer) > 100:
            try:
                from scipy.signal import hilbert
                analytic_signal = hilbert(self._filtered_buffer[:n])
                envelope = np.abs(analytic_signal)
                self._curve_envelope.setData(t, envelope)
                self._curve_envelope.setVisible(True)
            except:
                self._curve_envelope.setVisible(False)
        else:
            self._curve_envelope.setVisible(False)
            
        # Update statistics display
        self.lbl_rms_raw.setText(f"{self._live_stats['rms_raw']:.3f} V")
        self.lbl_rms_filtered.setText(f"{self._live_stats['rms_filtered']:.3f} V")
        self.lbl_peak_raw.setText(f"{self._live_stats['peak_raw']:.3f} V")
        self.lbl_peak_filtered.setText(f"{self._live_stats['peak_filtered']:.3f} V")
        self.lbl_snr.setText(f"{self._live_stats['snr_db']:.1f} dB")
        self.lbl_thd.setText(f"{self._live_stats['thd_percent']:.2f} %")
        self.lbl_enob.setText(f"{self._live_stats['enob_bits']:.1f} bits")

    def _update_result_table(self, results: Dict[str, str]):
        """Update results table"""
        self._result_table.setRowCount(0)
        for metric, value in results.items():
            row = self._result_table.rowCount()
            self._result_table.insertRow(row)
            self._result_table.setItem(row, 0, QTableWidgetItem(metric))
            self._result_table.setItem(row, 1, QTableWidgetItem(value))

    def _clear_param_panel(self):
        """Clear parameter panel"""
        for i in reversed(range(self._param_inner.count())):
            w = self._param_inner.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._param_group.setTitle("BLOCK PARAMETERS")
        self._param_widgets = []

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        """Set data source for DSO mode"""
        self._dso_source = fn

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        self.plot_widget.setBackground(T.DARK_BG)
        self.plot_widget.getAxis("left").setTextPen(T.TEXT_MUTED)
        self.plot_widget.getAxis("bottom").setTextPen(T.TEXT_MUTED)
