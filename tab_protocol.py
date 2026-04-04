"""
tab_protocol.py - Protocol Decoder tab for STM32 Lab GUI v6.0

Decodes raw logic captures from the DSO ring buffer into human-readable
I2C / SPI / UART / 1-Wire transactions with:
  * Overlay text annotations on the waveform plot
  * Decoded transaction table (timing, address, data, ACK/NAK, CRC status)
  * Pure-Python bit-bang state machines - no extra library required
"""

import datetime
import math
from collections import deque
from typing import Callable, List, Optional, Dict, Any

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QSpinBox, QGroupBox, QSplitter, QTableWidget,
    QTableWidgetItem, QCheckBox, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget


# 
# Bit-Bang Decoders (pure Python)
# 

def _to_digital(samples: np.ndarray, threshold: float) -> np.ndarray:
    """Convert analog samples to digital 0/1 using threshold."""
    return (samples >= threshold).astype(np.uint8)


def _find_edges(digital: np.ndarray) -> List[tuple]:
    """Return list of (index, 'rising'|'falling') for each edge."""
    edges = []
    for i in range(1, len(digital)):
        if digital[i-1] == 0 and digital[i] == 1:
            edges.append((i, "rising"))
        elif digital[i-1] == 1 and digital[i] == 0:
            edges.append((i, "falling"))
    return edges


def decode_uart(samples: np.ndarray, threshold: float,
                baud_rate: int, sample_rate: float) -> List[Dict]:
    """Simple UART decoder  detects start bit and samples 8 data bits."""
    digital  = _to_digital(samples, threshold)
    sps      = sample_rate / baud_rate   # samples per symbol
    results  = []
    i        = 0
    n        = len(digital)

    while i < n - int(sps * 10):
        # look for falling edge (start bit)
        if digital[i] == 1 and digital[i+1] == 0:
            start = i + 1
            # sample 8 data bits at centres
            bits = []
            for b in range(8):
                centre = int(start + (b + 1.5) * sps)
                if centre < n:
                    bits.append(int(digital[centre]))
            byte_val = sum(bit << idx for idx, bit in enumerate(bits))
            t_ms = start / sample_rate * 1000
            results.append({
                "proto":  "UART",
                "time_ms": f"{t_ms:.2f}",
                "info":    f"0x{byte_val:02X}  '{chr(byte_val) if 32<=byte_val<127 else '.'}'",
                "ack":     "-",
                "crc":     "-",
            })
            i = int(start + sps * 10)
        else:
            i += 1
    return results


def decode_i2c(samples: np.ndarray, threshold: float,
               sample_rate: float) -> List[Dict]:
    """
    Simple I2C decoder.
    Treats the single DSO channel as SDA; detects START/STOP + address byte.
    (Full clock-channel decode would need a 2-ch DSO  this is single-channel approx.)
    """
    digital = _to_digital(samples, threshold)
    edges   = _find_edges(digital)
    results = []

    # Look for a highlow (START) transition when we've had a long stable high
    i = 0
    while i < len(edges) - 9:
        idx, kind = edges[i]
        if kind == "falling":
            # Collect next 9 edges for address + ACK
            chunk = edges[i:i+18]
            bits  = []
            for j in range(0, min(16, len(chunk)), 2):
                hi_idx = chunk[j][0]
                if hi_idx < len(digital):
                    bits.append(int(digital[hi_idx]))
            if len(bits) >= 8:
                addr_byte = sum(b << (7 - k) for k, b in enumerate(bits[:8]))
                rw   = "READ " if (addr_byte & 1) else "WRITE"
                addr = addr_byte >> 1
                ack  = "ACK" if (len(bits) > 8 and bits[8] == 0) else "NAK"
                t_ms = idx / sample_rate * 1000
                results.append({
                    "proto":   "I2C",
                    "time_ms": f"{t_ms:.2f}",
                    "info":    f"{rw} 0x{addr:02X}",
                    "ack":     ack,
                    "crc":     "-",
                })
            i += 9
        else:
            i += 1
    return results


def decode_spi(samples: np.ndarray, threshold: float,
               sample_rate: float) -> List[Dict]:
    """SPI decoder  single channel MOSI approximation."""
    digital = _to_digital(samples, threshold)
    edges   = _find_edges(digital)
    results = []
    i       = 0
    while i + 8 < len(edges):
        bits = []
        base = edges[i][0]
        for j in range(8):
            if i + j < len(edges):
                bits.append(1 if edges[i+j][1] == "rising" else 0)
        byte_val = sum(b << (7-k) for k, b in enumerate(bits))
        t_ms = base / sample_rate * 1000
        results.append({
            "proto":   "SPI",
            "time_ms": f"{t_ms:.2f}",
            "info":    f"MOSI 0x{byte_val:02X}",
            "ack":     "-",
            "crc":     "-",
        })
        i += 8
    return results


def decode_onewire(samples: np.ndarray, threshold: float,
                   sample_rate: float) -> List[Dict]:
    """1-Wire reset presence pulse detector."""
    digital = _to_digital(samples, threshold)
    edges   = _find_edges(digital)
    results = []
    for idx, kind in edges:
        if kind == "falling":
            # Measure low duration
            j = idx
            while j < len(digital) and digital[j] == 0:
                j += 1
            low_us = (j - idx) / sample_rate * 1e6
            if low_us > 480:
                t_ms = idx / sample_rate * 1000
                results.append({
                    "proto":   "1-Wire",
                    "time_ms": f"{t_ms:.2f}",
                    "info":    f"RESET pulse  {low_us:.0f} us",
                    "ack":     "-",
                    "crc":     "-",
                })
    return results


DECODERS = {
    "I2C":    decode_i2c,
    "SPI":    decode_spi,
    "UART":   decode_uart,
    "1-Wire": decode_onewire,
}


# 
# Protocol Decoder Tab
# 

class ProtocolDecoderTab(QWidget):
    """Decode raw DSO captures into readable bus transactions."""

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._annotations: List[pg.TextItem] = []
        self.sample_period = 0.010 # default
        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Protocol Decoder")
        self._header_strip = hdr

        self.btn_decode = QPushButton("> DECODE")
        self.btn_decode.setFixedWidth(130)
        self.btn_decode.clicked.connect(self._run_decode)
        hdr_lay.addWidget(self.btn_decode)

        self.btn_clear = QPushButton("CLEAR")
        self.btn_clear.setObjectName("btn_disconnect")
        self.btn_clear.setFixedWidth(90)
        self.btn_clear.clicked.connect(self._clear)
        hdr_lay.addWidget(self.btn_clear)

        self.local_logger = LocalLoggerWidget("protocol_decoder", ["timestamp", "protocol", "info", "ack_crc"])
        hdr_lay.addStretch()
        hdr_lay.addWidget(self.local_logger)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: settings ----------------------------------------------------
        ctrl_w = QWidget()
        ctrl_w.setMaximumWidth(260)
        c_lay = QVBoxLayout(ctrl_w)
        c_lay.setContentsMargins(14, 14, 14, 14)
        c_lay.setSpacing(12)

        proto_grp = QGroupBox("PROTOCOL")
        pg_lay = QVBoxLayout(proto_grp)
        pg_lay.setSpacing(8)
        pg_lay.setContentsMargins(12, 22, 12, 12)
        c_lay.addWidget(proto_grp)

        def _row(label, widget):
            r = QHBoxLayout()
            r.addWidget(ThemeLabel(label, "TEXT_MUTED", SZ_SM, bold=True))
            r.addWidget(widget)
            pg_lay.addLayout(r)

        self.cmb_proto = QComboBox()
        self.cmb_proto.addItems(list(DECODERS.keys()))
        self.cmb_proto.currentTextChanged.connect(self._on_proto_changed)
        _row("Protocol:", self.cmb_proto)

        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.01, 24.0)
        self.spin_threshold.setValue(1.65)
        self.spin_threshold.setSuffix(" V")
        self.spin_threshold.setDecimals(2)
        _row("Threshold:", self.spin_threshold)

        self.spin_baud = QSpinBox()
        self.spin_baud.setRange(110, 3_000_000)
        self.spin_baud.setValue(9600)
        self.spin_baud.setSuffix(" baud")
        self._baud_row_widget = self.spin_baud
        _row("Baud (UART):", self.spin_baud)

        self.spin_srate = QDoubleSpinBox()
        self.spin_srate.setRange(1.0, 1_000_000.0)
        self.spin_srate.setValue(100.0)
        self.spin_srate.setSuffix(" Hz")
        self.spin_srate.setDecimals(1)
        _row("Sample Rate:", self.spin_srate)

        self.chk_overlay = QCheckBox("Show overlay on plot")
        self.chk_overlay.setChecked(True)
        pg_lay.addWidget(self.chk_overlay)

        # stat cards
        self.lbl_count  = QLabel("0")
        self.lbl_proto  = QLabel("-")
        card_c = ThemeCard("TRANSACTIONS", self.lbl_count, "PRIMARY")
        card_p = ThemeCard("PROTOCOL",     self.lbl_proto, "ACCENT_BLUE")
        c_lay.addWidget(card_c)
        c_lay.addWidget(card_p)
        c_lay.addStretch()
        splitter.addWidget(ctrl_w)

        # -- RIGHT: waveform + table -------------------------------------------
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(6)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self._plot = pg.PlotWidget()
        self._plot.setLabel("left",   "Voltage (V)", color=T.TEXT_MUTED)
        self._plot.setLabel("bottom", "Time (ms)",   color=T.TEXT_MUTED)
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._curve = self._plot.plot(pen=pg.mkPen(T.ACCENT_BLUE, width=2))

        # Threshold line
        self._thresh_line = pg.InfiniteLine(
            angle=0, movable=True,
            pen=pg.mkPen(T.ACCENT_AMBER, width=1, style=Qt.DashLine),
            label="Threshold {value:.2f}V",
            labelOpts={"color": T.ACCENT_AMBER, "position": 0.9}
        )
        self._thresh_line.setValue(1.65)
        self._thresh_line.sigPositionChanged.connect(
            lambda l: self.spin_threshold.setValue(l.value()))
        self._plot.addItem(self._thresh_line)
        r_lay.addWidget(self._plot, stretch=2)

        # Transaction table
        tbl_grp = QGroupBox("DECODED TRANSACTIONS")
        tbl_lay = QVBoxLayout(tbl_grp)
        tbl_lay.setContentsMargins(8, 20, 8, 8)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Protocol", "Time (ms)", "Info", "ACK/CRC"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setMinimumHeight(160)
        self._table.setFont(_ui_font(SZ_SM))
        tbl_lay.addWidget(self._table)
        r_lay.addWidget(tbl_grp, stretch=1)

        splitter.addWidget(right_w)
        splitter.setSizes([240, 900])

        self._on_proto_changed(self.cmb_proto.currentText())

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        if getattr(self, "local_logger", None):
            self.local_logger.update_theme()
        self._plot.setBackground(T.DARK_BG)
        self._plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    # -- Internal --------------------------------------------------------------

    def _on_proto_changed(self, proto: str):
        self.spin_baud.setEnabled(proto == "UART")
        self.lbl_proto.setText(proto)

    def _clear(self):
        self._table.setRowCount(0)
        for ann in self._annotations:
            self._plot.removeItem(ann)
        self._annotations.clear()
        self.lbl_count.setText("0")

    def _run_decode(self):
        raw = self._dso_source()
        if len(raw) < 16:
            QMessageBox.information(self, "No Data",
                "DSO buffer is empty. Connect hardware or use Playback mode.")
            return

        samples     = np.array(raw, dtype=float)
        threshold   = self.spin_threshold.value()
        sample_rate = 1.0 / self.sample_period
        proto       = self.cmb_proto.currentText()
        baud        = self.spin_baud.value()

        # Update plot
        n = len(samples)
        t_ms = np.arange(n, dtype=float) / sample_rate * 1000
        self._curve.setData(t_ms, samples)
        self._thresh_line.setValue(threshold)

        # Decode
        if proto == "UART":
            results = decode_uart(samples, threshold, baud, sample_rate)
        elif proto == "I2C":
            results = decode_i2c(samples, threshold, sample_rate)
        elif proto == "SPI":
            results = decode_spi(samples, threshold, sample_rate)
        elif proto == "1-Wire":
            results = decode_onewire(samples, threshold, sample_rate)
        else:
            results = []

        # Populate table
        self._clear()
        colors = {"I2C": T.ACCENT_BLUE, "SPI": T.PRIMARY,
                  "UART": T.ACCENT_AMBER, "1-Wire": T.ACCENT_PUR}
        col = colors.get(proto, T.TEXT)

        for r in results:
            row = self._table.rowCount()
            self._table.insertRow(row)
            items = [
                QTableWidgetItem(r["proto"]),
                QTableWidgetItem(r["time_ms"]),
                QTableWidgetItem(r["info"]),
                QTableWidgetItem(f"{r['ack']}  {r['crc']}"),
            ]
            for item in items:
                item.setForeground(QColor(col))
            for c_idx, item in enumerate(items):
                self._table.setItem(row, c_idx, item)

            # Overlay annotation
            if self.chk_overlay.isChecked():
                try:
                    t_x = float(r["time_ms"])
                    ann = pg.TextItem(
                        text=r["info"],
                        color=col,
                        anchor=(0, 1),
                    )
                    ann.setFont(_ui_font(SZ_SM))
                    self._plot.addItem(ann)
                    ann.setPos(t_x, threshold + 0.2)
                    self._annotations.append(ann)
                except Exception:
                    pass

        self.lbl_count.setText(str(len(results)))

        if getattr(self, "local_logger", None) and results:
            for r in results:
                self.local_logger.log({
                    "protocol": r["proto"],
                    "info": r["info"],
                    "ack_crc": f"{r['ack']} {r['crc']}"
                })
