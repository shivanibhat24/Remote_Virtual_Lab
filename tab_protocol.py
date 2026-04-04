"""
tab_protocol.py - Protocol Decoder tab for STM32 Lab GUI v6.0

Decodes raw logic captures from the DSO ring buffer into human-readable
I2C / SPI / UART / 1-Wire transactions with:
  * Overlay text annotations on the waveform plot
  * Decoded transaction table (timing, address, data, ACK/NAK, CRC status)
  * Pure-Python bit-bang state machines - no extra library required
"""

import csv
from typing import Callable, List, Optional, Dict, Any, Tuple

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QSpinBox, QGroupBox, QSplitter, QTableWidget,
    QTableWidgetItem, QCheckBox, QMessageBox, QFileDialog,
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget
from plot_trace_colors import TraceColorBar


# 
# Bit-Bang Decoders (pure Python)
# 

def _to_digital(samples: np.ndarray, threshold: float) -> np.ndarray:
    """Convert analog samples to digital 0/1 using threshold."""
    return (samples >= threshold).astype(np.uint8)


def _find_edges(digital: np.ndarray) -> List[Tuple[int, str]]:
    """Return list of (index, 'rising'|'falling') for each edge."""
    edges = []
    for i in range(1, len(digital)):
        if digital[i - 1] == 0 and digital[i] == 1:
            edges.append((i, "rising"))
        elif digital[i - 1] == 1 and digital[i] == 0:
            edges.append((i, "falling"))
    return edges


def decode_uart(
    samples: np.ndarray,
    threshold: float,
    baud_rate: int,
    sample_rate: float,
    data_bits: int = 8,
    stop_bits: int = 1,
    parity: str = "None",
) -> List[Dict]:
    """UART: start bit + data + optional parity + stop; advances by full frame width."""
    digital = _to_digital(samples, threshold)
    if baud_rate <= 0 or sample_rate <= 0:
        return []
    sps = sample_rate / float(baud_rate)
    n = len(digital)
    results: List[Dict] = []
    i = 0
    data_bits = max(5, min(9, int(data_bits)))
    stop_bits = max(1, min(2, int(stop_bits)))
    parity_on = parity in ("Even", "Odd")

    min_frame = int(sps * (1 + data_bits + (1 if parity_on else 0) + stop_bits) + 1)

    while i < n - min_frame:
        if digital[i] == 1 and i + 1 < n and digital[i + 1] == 0:
            start = i + 1
            bits: List[int] = []
            ok = True
            for b in range(data_bits):
                centre = int(round(start + (b + 1.5) * sps))
                if centre >= n:
                    ok = False
                    break
                bits.append(int(digital[centre]))
            if not ok or len(bits) != data_bits:
                i += 1
                continue

            pbit = None
            if parity_on:
                pc = int(round(start + (data_bits + 1.5) * sps))
                if pc >= n:
                    i += 1
                    continue
                pbit = int(digital[pc])
                ones = sum(bits)
                if parity == "Even" and (ones + pbit) % 2 != 0:
                    crc = "PARITY ERR"
                elif parity == "Odd" and (ones + pbit) % 2 != 1:
                    crc = "PARITY ERR"
                else:
                    crc = "OK"
            else:
                crc = "-"

            byte_val = sum(bit << k for k, bit in enumerate(bits))
            if data_bits == 7:
                byte_val &= 0x7F
            t_ms = start / sample_rate * 1000
            ch = chr(byte_val) if 32 <= byte_val < 127 else "."
            results.append({
                "proto": "UART",
                "time_ms": f"{t_ms:.2f}",
                "info": f"0x{byte_val:02X}  '{ch}'",
                "ack": "-",
                "crc": crc,
            })
            i = int(round(start + (1 + data_bits + (1 if parity_on else 0) + stop_bits) * sps))
        else:
            i += 1
    return results


def decode_i2c(samples: np.ndarray, threshold: float, sample_rate: float) -> List[Dict]:
    """
    Single-channel SDA approximation: after a long idle HIGH, a falling edge is START;
    the following address+ACK window is split into 9 slices (8 data + ACK).
    True I2C needs SCL on a second channel for reliable decoding.
    """
    digital = _to_digital(samples, threshold)
    edges = _find_edges(digital)
    results: List[Dict] = []
    n = len(digital)
    min_idle = max(8, int(0.00005 * sample_rate)) if sample_rate > 0 else 8

    ei = 0
    while ei < len(edges):
        idx, kind = edges[ei]
        if kind != "falling":
            ei += 1
            continue
        run_high = 0
        j = idx - 1
        while j >= 0 and digital[j] == 1:
            run_high += 1
            j -= 1
        if run_high < min_idle:
            ei += 1
            continue
        if ei + 16 >= len(edges):
            break
        end_idx = edges[ei + 16][0]
        start_idx = idx
        width = end_idx - start_idx
        if width < 4:
            ei += 1
            continue
        bits: List[int] = []
        for k in range(9):
            a = start_idx + (k * width) // 9
            b = start_idx + ((k + 1) * width) // 9
            b = min(b, n)
            a = min(a, n - 1)
            if b <= a:
                bits.append(0)
            else:
                bits.append(1 if float(np.mean(digital[a:b])) >= 0.5 else 0)
        addr_byte = sum(b << (7 - k) for k, b in enumerate(bits[:8]))
        rw = "READ" if (addr_byte & 1) else "WRITE"
        addr = addr_byte >> 1
        ack_bit = bits[8] if len(bits) > 8 else 1
        ack = "ACK" if ack_bit == 0 else "NAK"
        t_ms = idx / sample_rate * 1000
        results.append({
            "proto": "I2C",
            "time_ms": f"{t_ms:.2f}",
            "info": f"{rw} 0x{addr:02X}",
            "ack": ack,
            "crc": "-",
        })
        ei += 9
    return results


def decode_spi(
    samples: np.ndarray,
    threshold: float,
    sample_rate: float,
    spi_mode: int = 0,
) -> List[Dict]:
    """
    SPI on a single trace: treat clock edges (derived from SCK if present, else rising edges)
    as latch points and sample MOSI just before each active edge. spi_mode 0..3 = CPOL*2+CPHA.
    """
    digital = _to_digital(samples, threshold)
    edges = _find_edges(digital)
    spi_mode = int(spi_mode) & 3
    cpol, cpha = spi_mode >> 1, spi_mode & 1
    if cpol == 0 and cpha == 0:
        active = "rising"
    elif cpol == 0 and cpha == 1:
        active = "falling"
    elif cpol == 1 and cpha == 0:
        active = "falling"
    else:
        active = "rising"
    clk_idx = [idx for idx, k in edges if k == active]
    results: List[Dict] = []
    for bi in range(0, len(clk_idx) - 7, 8):
        bits: List[int] = []
        for j in range(8):
            idx = clk_idx[bi + j]
            sidx = max(0, idx - 1)
            bits.append(int(digital[sidx]))
        byte_val = sum(b << (7 - k) for k, b in enumerate(bits))
        t_ms = clk_idx[bi] / sample_rate * 1000
        results.append({
            "proto": "SPI",
            "time_ms": f"{t_ms:.2f}",
            "info": f"MOSI 0x{byte_val:02X}  (mode {spi_mode})",
            "ack": "-",
            "crc": "-",
        })
    return results


def decode_onewire(samples: np.ndarray, threshold: float, sample_rate: float) -> List[Dict]:
    """1-Wire reset / presence: master pulls low > ~480 µs."""
    digital = _to_digital(samples, threshold)
    results: List[Dict] = []
    i = 0
    n = len(digital)
    while i < n:
        if i > 0 and digital[i - 1] == 1 and digital[i] == 0:
            j = i
            while j < n and digital[j] == 0:
                j += 1
            low_us = (j - i) / sample_rate * 1e6 if sample_rate > 0 else 0.0
            if low_us > 480:
                t_ms = i / sample_rate * 1000
                results.append({
                    "proto": "1-Wire",
                    "time_ms": f"{t_ms:.2f}",
                    "info": f"RESET  {low_us:.0f} µs",
                    "ack": "-",
                    "crc": "-",
                })
                i = j
                continue
        i += 1
    return results


PROTOCOL_NAMES = ("I2C", "SPI", "UART", "1-Wire")


# 
# Protocol Decoder Tab
# 

class ProtocolDecoderTab(QWidget):
    """Decode raw DSO captures into readable bus transactions."""

    def __init__(self, settings=None):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._annotations: List[pg.TextItem] = []
        self._uart_option_rows: List[QWidget] = []
        self._spi_mode_row: Optional[QWidget] = None
        self._settings = settings
        self._trace_bar: Optional[TraceColorBar] = None
        self._build_ui()

    @property
    def sample_period(self) -> float:
        sr = float(self.spin_srate.value())
        return 1.0 / max(sr, 1e-9)

    @sample_period.setter
    def sample_period(self, sp: float) -> None:
        if sp is None or sp <= 0:
            sp = 0.010
        hz = 1.0 / sp
        lo, hi = self.spin_srate.minimum(), self.spin_srate.maximum()
        hz = max(lo, min(hi, hz))
        self.spin_srate.blockSignals(True)
        self.spin_srate.setValue(hz)
        self.spin_srate.blockSignals(False)

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

        self.btn_export = QPushButton("EXPORT CSV")
        self.btn_export.setFixedWidth(110)
        self.btn_export.clicked.connect(self._export_csv)
        hdr_lay.addWidget(self.btn_export)

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

        def _row_widget(label, widget) -> QWidget:
            r = QHBoxLayout()
            r.setContentsMargins(0, 0, 0, 0)
            r.addWidget(ThemeLabel(label, "TEXT_MUTED", SZ_SM, bold=True))
            r.addWidget(widget, stretch=1)
            wrap = QWidget()
            wrap.setLayout(r)
            pg_lay.addWidget(wrap)
            return wrap

        self.cmb_proto = QComboBox()
        self.cmb_proto.addItems(list(PROTOCOL_NAMES))
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
        self._uart_option_rows.append(_row_widget("Baud (UART):", self.spin_baud))

        self.cmb_uart_bits = QComboBox()
        self.cmb_uart_bits.addItems(["8 data bits", "7 data bits"])
        self._uart_option_rows.append(_row_widget("UART width:", self.cmb_uart_bits))

        self.cmb_uart_parity = QComboBox()
        self.cmb_uart_parity.addItems(["None", "Even", "Odd"])
        self._uart_option_rows.append(_row_widget("UART parity:", self.cmb_uart_parity))

        self.spin_uart_stop = QSpinBox()
        self.spin_uart_stop.setRange(1, 2)
        self.spin_uart_stop.setValue(1)
        self.spin_uart_stop.setSuffix(" stop")
        self._uart_option_rows.append(_row_widget("UART stops:", self.spin_uart_stop))

        self.cmb_spi_mode = QComboBox()
        self.cmb_spi_mode.addItems([
            "0  CPOL=0 CPHA=0",
            "1  CPOL=0 CPHA=1",
            "2  CPOL=1 CPHA=0",
            "3  CPOL=1 CPHA=1",
        ])
        self._spi_mode_row = _row_widget("SPI mode:", self.cmb_spi_mode)

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

        def _line_to_spin(line):
            self.spin_threshold.blockSignals(True)
            self.spin_threshold.setValue(line.value())
            self.spin_threshold.blockSignals(False)

        def _spin_to_line(v):
            self._thresh_line.blockSignals(True)
            self._thresh_line.setValue(v)
            self._thresh_line.blockSignals(False)

        self._thresh_line.sigPositionChanged.connect(_line_to_spin)
        self.spin_threshold.valueChanged.connect(_spin_to_line)
        self._plot.addItem(self._thresh_line)
        r_lay.addWidget(self._plot, stretch=2)

        pc = QHBoxLayout()
        pcl = QLabel("Signal colors")
        pcl.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-weight: 600;")
        pc.addWidget(pcl)
        self._trace_bar = TraceColorBar(self._settings, "proto", self)
        self._trace_bar.add_trace(
            "wave", "Sig", "Decoded analog trace", "ACCENT_BLUE", items=[self._curve], width=2.0
        )
        self._trace_bar.add_trace(
            "thresh",
            "Thr",
            "Logic threshold line",
            "ACCENT_AMBER",
            items=[self._thresh_line],
            width=1.0,
            style=Qt.DashLine,
        )
        pc.addWidget(self._trace_bar)
        pc.addStretch()
        r_lay.addLayout(pc)

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
        if self._trace_bar:
            self._trace_bar.refresh_theme_defaults_only()

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    # -- Internal --------------------------------------------------------------

    def _on_proto_changed(self, proto: str):
        is_uart = proto == "UART"
        is_spi = proto == "SPI"
        for row in self._uart_option_rows:
            row.setEnabled(is_uart)
            row.setVisible(is_uart)
        if self._spi_mode_row is not None:
            self._spi_mode_row.setEnabled(is_spi)
            self._spi_mode_row.setVisible(is_spi)
        self.lbl_proto.setText(proto)

    def _clear(self):
        self._table.setRowCount(0)
        for ann in self._annotations:
            self._plot.removeItem(ann)
        self._annotations.clear()
        self.lbl_count.setText("0")

    def _export_csv(self):
        rows = self._table.rowCount()
        if rows == 0:
            QMessageBox.information(self, "Export", "No rows to export. Run decode first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export decoded transactions", "", "CSV (*.csv);;All (*)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([
                    self._table.horizontalHeaderItem(c).text()
                    for c in range(self._table.columnCount())
                ])
                for r in range(rows):
                    w.writerow([
                        (self._table.item(r, c).text() if self._table.item(r, c) else "")
                        for c in range(self._table.columnCount())
                    ])
        except OSError as e:
            QMessageBox.warning(self, "Export", str(e))

    def _run_decode(self):
        raw = self._dso_source()
        if len(raw) < 16:
            QMessageBox.information(self, "No Data",
                "DSO buffer is empty. Connect hardware or use Playback mode.")
            return

        samples = np.array(raw, dtype=float)
        threshold = self.spin_threshold.value()
        sample_rate = float(self.spin_srate.value())
        if sample_rate <= 0:
            QMessageBox.warning(self, "Sample rate", "Sample rate must be positive.")
            return
        proto = self.cmb_proto.currentText()
        baud = self.spin_baud.value()

        # Update plot
        n = len(samples)
        t_ms = np.arange(n, dtype=float) / sample_rate * 1000
        self._curve.setData(t_ms, samples)
        self._thresh_line.setValue(threshold)

        # Decode
        if proto == "UART":
            data_bits = 7 if self.cmb_uart_bits.currentIndex() == 1 else 8
            parity = self.cmb_uart_parity.currentText()
            results = decode_uart(
                samples, threshold, baud, sample_rate,
                data_bits=data_bits,
                stop_bits=self.spin_uart_stop.value(),
                parity=parity,
            )
        elif proto == "I2C":
            results = decode_i2c(samples, threshold, sample_rate)
        elif proto == "SPI":
            results = decode_spi(
                samples, threshold, sample_rate,
                spi_mode=self.cmb_spi_mode.currentIndex(),
            )
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
