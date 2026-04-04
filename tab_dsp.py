"""
tab_dsp.py - NumPy/SciPy Signal Processing Pipeline tab for STM32 Lab GUI v6.0

Visual pipeline builder:
  * Palette combobox -> add blocks to list
  * Blocks: Butterworth LP/HP/BP, Chebyshev I LP/HP, FIR Window,
            Hilbert Envelope, THD, SNR/SINAD, ENOB
  * Each block has parameter spinboxes (cutoff, order, ...)
  * "RUN PIPELINE" chains scipy operations on the current DSO buffer
  * Results plotted as overlay on DSO waveform + shown in stats table
"""

import math
from typing import Optional, List, Callable, Dict, Any

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QSpinBox, QGroupBox, QListWidget, QListWidgetItem,
    QSplitter, QTableWidget, QTableWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui  import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header, LocalLoggerWidget

try:
    from scipy import signal as sp_signal
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# -- Block Definitions --------------------------------------------------------
# Block Definitions
# -- Block Definitions --------------------------------------------------------

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
    "Hilbert Envelope": {
        "category": "Transform",
        "params": [],
        "info": "Analytic signal envelope via Hilbert transform"
    },
    "Measure THD": {
        "category": "Measure",
        "params": [("Fund Hz", 50.0, 1.0, 50000.0),
                   ("Harmonics", 5, 2, 20)],
        "info": "Total Harmonic Distortion (%)"
    },
    "Measure SNR": {
        "category": "Measure",
        "params": [("Fund Hz", 50.0, 1.0, 50000.0)],
        "info": "Signal-to-Noise Ratio (dB)"
    },
    "Measure ENOB": {
        "category": "Measure",
        "params": [("Fund Hz", 50.0, 1.0, 50000.0)],
        "info": "Effective Number of Bits"
    },
}


# -- Block Definitions --------------------------------------------------------
# Pipeline Block (data model)
# -- Block Definitions --------------------------------------------------------

class PipelineBlock:
    def __init__(self, name: str):
        self.name   = name
        self.defn   = BLOCK_DEFS[name]
        # Param values: list of floats matching defn["params"]
        self.values: List[float] = [p[1] for p in self.defn["params"]]

    def label(self) -> str:
        cat = self.defn["category"]
        return f"[{cat}]  {self.name}"


# -- Block Definitions --------------------------------------------------------
# DSP Pipeline Tab
# -- Block Definitions --------------------------------------------------------

class DSPPipelineTab(QWidget):
    """Visual DSP signal processing pipeline builder."""

    # Emits processed signal array + measurement dict for overlaying on DSO
    overlay_ready = pyqtSignal(object)   # np.ndarray

    SAMPLE_RATE = 100.0   # Hz (1 / 0.010 s)

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._blocks:       List[PipelineBlock]    = []
        self._param_widgets: List[QWidget]         = []   # current param panel widgets
        self._selected_block_idx = -1
        self._dso_source: Callable[[], list] = lambda: []
        self._build_ui()

    # -- UI Build -------------------------------------------------------------
    # UI Build
    # -- UI Build -------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("DSP Signal Processing Pipeline")
        self._header_strip = hdr

        self.btn_run = QPushButton("> RUN PIPELINE")
        self.btn_run.setFixedWidth(180)
        self.btn_run.clicked.connect(self._run_pipeline)
        hdr_lay.addWidget(self.btn_run)

        self.btn_clear_pipeline = QPushButton("CLEAR")
        self.btn_clear_pipeline.setObjectName("btn_disconnect")
        self.btn_clear_pipeline.setFixedWidth(90)
        self.btn_clear_pipeline.clicked.connect(self._clear_pipeline)
        hdr_lay.addWidget(self.btn_clear_pipeline)

        self.local_logger = LocalLoggerWidget("dsp_pipeline", ["timestamp", "blocks_count", "snr_db", "thd_pct", "enob_bits"])
        hdr_lay.addStretch()
        hdr_lay.addWidget(self.local_logger)

        root.addWidget(hdr)

        if not HAS_SCIPY:
            msg = QLabel(
                "scipy not installed.\n"
                "Run:  pip install scipy\n"
                "Then restart the application."
            )
            msg.setAlignment(Qt.AlignCenter)
            msg.setStyleSheet(
                f"color: {T.ACCENT_RED}; font-size: 14px; font-family: {T.FONT_UI};"
            )
            root.addWidget(msg, stretch=1)
            return

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: palette + block list ----------------------------------------
        left_w = QWidget()
        left_w.setMaximumWidth(300)
        l_lay  = QVBoxLayout(left_w)
        l_lay.setContentsMargins(10, 10, 10, 10)
        l_lay.setSpacing(8)

        palette_row = QHBoxLayout()
        self.cmb_palette = QComboBox()
        self.cmb_palette.addItems(list(BLOCK_DEFS.keys()))
        palette_row.addWidget(self.cmb_palette, stretch=1)
        btn_add = QPushButton("ADD")
        btn_add.setFixedWidth(60)
        btn_add.clicked.connect(self._add_block)
        palette_row.addWidget(btn_add)
        l_lay.addLayout(palette_row)

        self.block_list = QListWidget()
        self.block_list.setDragDropMode(QListWidget.InternalMove)
        self.block_list.currentRowChanged.connect(self._on_block_selected)
        l_lay.addWidget(self.block_list, stretch=1)

        list_btns = QHBoxLayout()
        btn_up  = QPushButton("^")
        btn_up.setFixedWidth(50)
        btn_up.clicked.connect(self._move_up)
        btn_dn  = QPushButton("v")
        btn_dn.setFixedWidth(50)
        btn_dn.clicked.connect(self._move_down)
        btn_del = QPushButton("X")
        btn_del.setObjectName("btn_disconnect")
        btn_del.setFixedWidth(50)
        btn_del.clicked.connect(self._delete_block)
        list_btns.addWidget(btn_up)
        list_btns.addWidget(btn_dn)
        list_btns.addWidget(btn_del)
        list_btns.addStretch()
        l_lay.addLayout(list_btns)

        splitter.addWidget(left_w)

        # -- MIDDLE: parameter panel -------------------------------------------
        mid_w = QWidget()
        mid_w.setMaximumWidth(280)
        self._param_outer = QVBoxLayout(mid_w)
        self._param_outer.setContentsMargins(10, 10, 10, 10)
        self._param_outer.setSpacing(8)
        self._param_group = QGroupBox("BLOCK PARAMETERS")
        self._param_inner = QVBoxLayout(self._param_group)
        self._param_inner.setSpacing(8)
        self._param_inner.setContentsMargins(10, 22, 10, 10)
        self._param_outer.addWidget(self._param_group)
        self._param_inner.addWidget(ThemeLabel("Select a block ->", "TEXT_MUTED", SZ_BODY))
        self._param_outer.addStretch()
        splitter.addWidget(mid_w)

        # -- RIGHT: results + info ---------------------------------------------
        right_w = QWidget()
        r_lay   = QVBoxLayout(right_w)
        r_lay.setContentsMargins(10, 10, 10, 10)
        r_lay.setSpacing(8)

        self.lbl_status = QLabel("Pipeline idle")
        self.lbl_status.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {SZ_BODY}px; font-family: {T.FONT_UI};"
        )
        r_lay.addWidget(self.lbl_status)

        results_grp = QGroupBox("MEASUREMENT RESULTS")
        rl          = QVBoxLayout(results_grp)
        rl.setContentsMargins(10, 22, 10, 10)
        self._result_table = QTableWidget(0, 2)
        self._result_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self._result_table.horizontalHeader().setStretchLastSection(True)
        self._result_table.setMinimumHeight(200)
        rl.addWidget(self._result_table)
        r_lay.addWidget(results_grp)

        info_grp = QGroupBox("BLOCK INFO")
        il       = QVBoxLayout(info_grp)
        il.setContentsMargins(10, 22, 10, 10)
        self.lbl_block_info = QLabel("-")
        self.lbl_block_info.setWordWrap(True)
        self.lbl_block_info.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-family: {T.FONT_UI};"
        )
        il.addWidget(self.lbl_block_info)
        r_lay.addWidget(info_grp)
        r_lay.addStretch()
        splitter.addWidget(right_w)

        splitter.setSizes([280, 260, 400])

    # -- UI Build -------------------------------------------------------------
    # Public API
    # -- UI Build -------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        if getattr(self, "local_logger", None):
            self.local_logger.update_theme()

    # -- UI Build -------------------------------------------------------------
    # Block Management
    # -- UI Build -------------------------------------------------------------

    def _add_block(self):
        name  = self.cmb_palette.currentText()
        block = PipelineBlock(name)
        self._blocks.append(block)
        item = QListWidgetItem(block.label())
        # Colour-code by category
        cat = block.defn["category"]
        color_map = {"Filter": T.ACCENT_BLUE, "Transform": T.PRIMARY,
                     "Measure": T.ACCENT_AMBER}
        item.setForeground(QColor(color_map.get(cat, T.TEXT)))
        self.block_list.addItem(item)

    def _delete_block(self):
        row = self.block_list.currentRow()
        if row < 0: return
        self.block_list.takeItem(row)
        self._blocks.pop(row)
        self._clear_param_panel()

    def _move_up(self):
        row = self.block_list.currentRow()
        if row <= 0: return
        item = self.block_list.takeItem(row)
        self.block_list.insertItem(row - 1, item)
        self._blocks.insert(row - 1, self._blocks.pop(row))
        self.block_list.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.block_list.currentRow()
        if row < 0 or row >= self.block_list.count() - 1: return
        item = self.block_list.takeItem(row)
        self.block_list.insertItem(row + 1, item)
        self._blocks.insert(row + 1, self._blocks.pop(row))
        self.block_list.setCurrentRow(row + 1)

    def _clear_pipeline(self):
        self._blocks.clear()
        self.block_list.clear()
        self._clear_param_panel()

    # -- UI Build -------------------------------------------------------------
    # Parameter Panel
    # -- UI Build -------------------------------------------------------------

    def _on_block_selected(self, row: int):
        self._save_current_params()
        self._selected_block_idx = row
        self._clear_param_panel()
        if row < 0 or row >= len(self._blocks):
            return
        block = self._blocks[row]
        self.lbl_block_info.setText(block.defn["info"])
        self._param_group.setTitle(f"PARAMETERS - {block.name}")

        self._param_widgets = []
        for i, param_def in enumerate(block.defn["params"]):
            pname, default, pmin, pmax = param_def
            lbl = ThemeLabel(pname + ":", "TEXT_MUTED", SZ_SM)
            self._param_inner.addWidget(lbl)
            if isinstance(default, int) and isinstance(pmin, int):
                w = QSpinBox()
                w.setRange(int(pmin), int(pmax))
                w.setValue(int(block.values[i]))
                w.valueChanged.connect(lambda v, idx=i, b=block: self._on_param_change(b, idx, v))
            else:
                w = QDoubleSpinBox()
                w.setRange(float(pmin), float(pmax))
                w.setDecimals(2)
                w.setValue(float(block.values[i]))
                w.valueChanged.connect(lambda v, idx=i, b=block: self._on_param_change(b, idx, v))
            self._param_inner.addWidget(w)
            self._param_widgets.append(w)

    def _on_param_change(self, block: PipelineBlock, idx: int, value):
        if 0 <= idx < len(block.values):
            block.values[idx] = float(value)

    def _save_current_params(self):
        pass   # values are written live via _on_param_change

    def _clear_param_panel(self):
        for i in reversed(range(self._param_inner.count())):
            w = self._param_inner.itemAt(i).widget()
            if w:
                w.setParent(None)
        self._param_group.setTitle("BLOCK PARAMETERS")
        self._param_widgets = []
        self.lbl_block_info.setText("-")

    # -- UI Build -------------------------------------------------------------
    # Pipeline Execution
    # -- UI Build -------------------------------------------------------------

    def _run_pipeline(self):
        if not HAS_SCIPY:
            return
        raw = self._dso_source()
        if len(raw) < 8:
            QMessageBox.information(self, "No Data",
                "DSO buffer is empty - connect hardware or use Playback mode.")
            return

        x   = np.array(raw, dtype=float)
        fs  = self.SAMPLE_RATE
        results: Dict[str, str] = {}

        for block in self._blocks:
            name = block.name
            vals = block.values
            cat  = block.defn["category"]
            try:
                if cat == "Filter":
                    x = self._apply_filter(name, x, vals, fs)
                elif name == "Hilbert Envelope":
                    x = np.abs(sp_signal.hilbert(x))
                elif cat == "Measure":
                    self._apply_measure(name, x, vals, fs, results)
            except Exception as e:
                self.lbl_status.setText(f"Error in [{name}]: {e}")
                return

        # Emit overlay signal
        self.overlay_ready.emit(x)
        self.lbl_status.setText(
            f"Pipeline OK - {len(self._blocks)} blocks, {len(x)} samples")
        self._update_result_table(results)

        if getattr(self, "local_logger", None):
            self.local_logger.log({
                "blocks_count": len(self._blocks),
                "snr_db": results.get("SNR", ""),
                "thd_pct": results.get("THD", ""),
                "enob_bits": results.get("ENOB", "")
            })

    def _apply_filter(self, name: str, x: np.ndarray,
                      vals: List[float], fs: float) -> np.ndarray:
        nyq = fs / 2.0
        if name == "Butterworth LP":
            cutoff, order = vals[0] / nyq, int(vals[1])
            b, a = sp_signal.butter(order, min(cutoff, 0.999), btype="low")
        elif name == "Butterworth HP":
            cutoff, order = vals[0] / nyq, int(vals[1])
            b, a = sp_signal.butter(order, min(cutoff, 0.999), btype="high")
        elif name == "Butterworth BP":
            lo, hi, order = vals[0]/nyq, vals[1]/nyq, int(vals[2])
            lo = min(lo, 0.998); hi = min(hi, 0.999)
            if lo >= hi: hi = lo + 0.001
            b, a = sp_signal.butter(order, [lo, hi], btype="band")
        elif name == "Chebyshev I LP":
            cutoff, order, rp = vals[0]/nyq, int(vals[1]), vals[2]
            b, a = sp_signal.cheby1(order, rp, min(cutoff, 0.999), btype="low")
        elif name == "Chebyshev I HP":
            cutoff, order, rp = vals[0]/nyq, int(vals[1]), vals[2]
            b, a = sp_signal.cheby1(order, rp, min(cutoff, 0.999), btype="high")
        elif name == "FIR Window LP":
            cutoff, taps = vals[0]/nyq, int(vals[1]) | 1   # ensure odd (BUG-FIX: was vals[0+1])
            b = sp_signal.firwin(taps, min(cutoff, 0.999))
            return sp_signal.filtfilt(b, [1.0], x)
        else:
            return x
        return sp_signal.filtfilt(b, a, x)

    def _apply_measure(self, name: str, x: np.ndarray,
                       vals: List[float], fs: float,
                       results: Dict[str, str]):
        fund_hz = vals[0]
        freqs   = np.fft.rfftfreq(len(x), d=1.0/fs)
        Xf      = np.fft.rfft(x)
        mags    = np.abs(Xf)

        # Fundamental bin
        f_idx = int(np.argmin(np.abs(freqs - fund_hz)))
        f_idx = max(1, min(f_idx, len(mags) - 1))
        fund_power = mags[f_idx] ** 2

        if name == "Measure THD":
            n_harm = int(vals[1])
            harm_power = 0.0
            for h in range(2, n_harm + 2):
                hf  = fund_hz * h
                hi  = int(np.argmin(np.abs(freqs - hf)))
                hi  = min(hi, len(mags) - 1)
                harm_power += mags[hi] ** 2
            thd = 100.0 * math.sqrt(harm_power) / max(math.sqrt(fund_power), 1e-12)
            results["THD"] = f"{thd:.3f} %"

        elif name == "Measure SNR":
            signal_pow  = fund_power
            noise_pow   = max(np.sum(mags ** 2) - signal_pow, 1e-30)
            snr         = 10.0 * math.log10(signal_pow / noise_pow)
            results["SNR"] = f"{snr:.2f} dB"

        elif name == "Measure ENOB":
            signal_pow  = fund_power
            noise_pow   = max(np.sum(mags ** 2) - signal_pow, 1e-30)
            snr         = 10.0 * math.log10(signal_pow / noise_pow)
            sinad       = snr   # simplified - SINAD approx SNR for this approx
            enob        = (sinad - 1.76) / 6.02
            results["SINAD"] = f"{sinad:.2f} dB"
            results["ENOB"]  = f"{enob:.2f} bits"

    def _update_result_table(self, results: Dict[str, str]):
        self._result_table.setRowCount(0)
        for metric, value in results.items():
            row = self._result_table.rowCount()
            self._result_table.insertRow(row)
            mi = QTableWidgetItem(metric)
            vi = QTableWidgetItem(value)
            mi.setForeground(QColor(T.TEXT_MUTED))
            vi.setForeground(QColor(T.PRIMARY))
            self._result_table.setItem(row, 0, mi)
            self._result_table.setItem(row, 1, vi)
