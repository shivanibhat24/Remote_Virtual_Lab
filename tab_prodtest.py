"""
tab_prodtest.py - Production Test Mode for STM32 Lab GUI v6.0

Roadmap item #13: Production Test Mode.
  * Full-screen PASS / FAIL display (visible from across the bench)  
  * JSON test spec editor: {"Vcc": {"min": 3.2, "max": 3.4, "unit": "V"}}
  * Serial number / barcode input (keyboard or scanner)
  * Auto-logging of every test result to SQLite + CSV
  * Multi-parameter test run with per-parameter PASS/FAIL indicators
  * Configurable auto-run on new serial number entry (Enter key)

WHY: Compliance testing (IEC, CE) requires traceable test records.
     Nobody wants to re-type results into a spreadsheet.
"""

import csv
import datetime
import json
import sqlite3
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit,
    QGroupBox, QSplitter, QTableWidget, QTableWidgetItem,
    QMessageBox, QFileDialog, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header


LOG_DIR = Path.home() / ".stm32lab" / "prodtest"


# -- Test Logger (SQLite + CSV) ------------------------------------------------

class TestLogger:
    DB_PATH  = LOG_DIR / "prodtest.sqlite"
    CSV_PATH = LOG_DIR / "prodtest.csv"

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS results (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         TEXT NOT NULL,
        serial     TEXT NOT NULL,
        spec_name  TEXT NOT NULL,
        param      TEXT NOT NULL,
        measured   REAL,
        limit_min  REAL,
        limit_max  REAL,
        pass_fail  TEXT NOT NULL
    );
    """

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.DB_PATH), check_same_thread=False)
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

        # CSV  write header only if new
        if not self.CSV_PATH.exists():
            with open(self.CSV_PATH, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(
                    ["timestamp", "serial", "spec_name", "parameter",
                     "measured", "limit_min", "limit_max", "pass_fail"])

    def log(self, serial: str, spec_name: str, param: str,
            measured: float, limit_min: float, limit_max: float,
            pass_fail: str):
        ts = datetime.datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO results "
            "(ts, serial, spec_name, param, measured, limit_min, limit_max, pass_fail) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (ts, serial, spec_name, param, measured, limit_min, limit_max, pass_fail)
        )
        self._conn.commit()
        with open(self.CSV_PATH, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [ts, serial, spec_name, param, measured, limit_min, limit_max, pass_fail])

    def recent(self, n: int = 50) -> list:
        cur = self._conn.execute(
            "SELECT ts, serial, param, measured, pass_fail "
            "FROM results ORDER BY id DESC LIMIT ?", (n,))
        return cur.fetchall()


_LOGGER = TestLogger()


# -- Production Test Tab ------------------------------------------------------

DEFAULT_SPEC = """{
  "Vcc": {
    "min": 3.15, "max": 3.45, "unit": "V",
    "description": "Supply voltage"
  },
  "Vref": {
    "min": 1.20, "max": 1.25, "unit": "V",
    "description": "Reference voltage"
  },
  "Freq": {
    "min": 490, "max": 510, "unit": "Hz",
    "description": "PWM frequency"
  }
}"""


class ProdTestTab(QWidget):
    """Full-screen PASS/FAIL production test module."""

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._stats_source: Callable[[], dict] = lambda: {}
        self._spec: Dict = {}
        self._current_serial = ""
        self._last_overall: Optional[bool] = None
        self.sample_period = 0.010  # default

        self._build_ui()
        self._load_spec(DEFAULT_SPEC)

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Production Test Mode")
        self._header_strip = hdr

        self.btn_run = QPushButton("> RUN TEST")
        self.btn_run.setObjectName("btn_connect")
        self.btn_run.setFixedWidth(140)
        self.btn_run.clicked.connect(self._run_test)
        hdr_lay.addWidget(self.btn_run)

        self.btn_export = QPushButton("EXPORT CSV")
        self.btn_export.setObjectName("btn_warning")
        self.btn_export.setFixedWidth(130)
        self.btn_export.clicked.connect(self._export_csv)
        hdr_lay.addWidget(self.btn_export)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        #  LEFT: spec + serial input 
        left_w = QWidget()
        left_w.setMaximumWidth(360)
        l_lay = QVBoxLayout(left_w)
        l_lay.setContentsMargins(14, 14, 14, 14)
        l_lay.setSpacing(12)

        # Serial / DUT id
        sn_grp = QGroupBox("DUT SERIAL NUMBER")
        sn_lay = QVBoxLayout(sn_grp)
        sn_lay.setContentsMargins(12, 22, 12, 12)
        sn_row = QHBoxLayout()
        self.txt_serial = QLineEdit()
        self.txt_serial.setFont(_ui_font(SZ_LG))
        self.txt_serial.setPlaceholderText("Scan or type DUT serial...")
        self.txt_serial.returnPressed.connect(self._run_test)
        sn_row.addWidget(self.txt_serial, stretch=1)
        sn_lay.addLayout(sn_row)
        l_lay.addWidget(sn_grp)

        # Spec editor
        spec_grp = QGroupBox("TEST SPECIFICATION  (JSON)")
        spec_lay = QVBoxLayout(spec_grp)
        spec_lay.setContentsMargins(10, 22, 10, 10)
        self._spec_editor = QTextEdit()
        self._spec_editor.setFont(_ui_font(SZ_BODY))
        self._spec_editor.setMaximumHeight(220)
        self._spec_editor.setStyleSheet(
            f"background: {T.CARD_BG}; color: {T.ACCENT_AMBER}; border: none;")
        spec_lay.addWidget(self._spec_editor)
        btn_apply = QPushButton("APPLY SPEC")
        btn_apply.clicked.connect(self._apply_spec)
        spec_lay.addWidget(btn_apply)
        l_lay.addWidget(spec_grp)

        # Result table
        hist_grp = QGroupBox("RECENT RESULTS")
        hl = QVBoxLayout(hist_grp)
        hl.setContentsMargins(10, 22, 10, 10)
        self._hist_table = QTableWidget(0, 5)
        self._hist_table.setHorizontalHeaderLabels(
            ["Time", "Serial", "Param", "Value", "P/F"])
        self._hist_table.horizontalHeader().setStretchLastSection(True)
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setFont(_ui_font(SZ_SM))
        hl.addWidget(self._hist_table)
        l_lay.addWidget(hist_grp, stretch=1)
        splitter.addWidget(left_w)

        #  RIGHT: big PASS/FAIL + per-param breakdown 
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(16, 16, 16, 16)
        r_lay.setSpacing(14)

        # Big label
        self.lbl_verdict = QLabel("READY")
        self.lbl_verdict.setAlignment(Qt.AlignCenter)
        self.lbl_verdict.setFont(_ui_font(SZ_BIG * 2, bold=True))
        self.lbl_verdict.setMinimumHeight(200)
        self.lbl_verdict.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.lbl_verdict.setStyleSheet(
            f"color: {T.TEXT_MUTED}; background: {T.PANEL_BG}; "
            f"border-radius: 8px; border: 2px solid {T.BORDER};")
        r_lay.addWidget(self.lbl_verdict, stretch=2)

        # Per-parameter breakdown
        self.lbl_serial_display = QLabel("S/N: -")
        self.lbl_serial_display.setFont(_ui_font(SZ_LG, bold=True))
        self.lbl_serial_display.setStyleSheet(
            f"color: {T.TEXT_MUTED}; background: transparent; border: none;")
        r_lay.addWidget(self.lbl_serial_display)

        self._param_grid = QGridLayout()
        self._param_grid.setSpacing(6)
        r_lay.addLayout(self._param_grid)
        r_lay.addStretch()

        splitter.addWidget(right_w)
        splitter.setSizes([340, 900])

        self._spec_editor.setPlainText(DEFAULT_SPEC)

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    def set_stats_source(self, fn: Callable[[], dict]):
        self._stats_source = fn

    # -- Spec Management -------------------------------------------------------

    def _load_spec(self, text: str):
        try:
            self._spec = json.loads(text)
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, "JSON Error", str(e))
            return
        self._spec_editor.setPlainText(json.dumps(self._spec, indent=2))

    def _apply_spec(self):
        self._load_spec(self._spec_editor.toPlainText())

    # -- Test Execution --------------------------------------------------------

    def _run_test(self):
        if not self._spec:
            QMessageBox.information(self, "No Spec", "Apply a test specification first.")
            return

        serial = self.txt_serial.text().strip()
        if not serial:
            serial = f"DUT-{datetime.datetime.now().strftime('%H%M%S')}"

        self._current_serial = serial
        self.lbl_serial_display.setText(f"S/N: {serial}")

        # Get measurements from analytics
        s     = self._stats_source()
        snap  = self._dso_source()
        arr   = np.array(snap, dtype=float) if snap else np.zeros(1)
        mean  = float(np.mean(arr))

        # Estimate frequency
        n  = max(2, len(arr))
        sr = 1.0 / self.sample_period  # Hz sample rate
        mag  = np.abs(np.fft.rfft(arr - mean))
        frqs = np.fft.rfftfreq(n, 1.0/sr)
        dom_freq = float(frqs[int(np.argmax(mag[1:])) + 1]) if len(mag) > 1 else 0.0

        # Map spec parameter names to measured values
        MEAS_MAP = {
            "vcc":   mean,
            "vref":  mean,
            "voltage": mean,
            "volt":  mean,
            "v":     mean,
            "freq":  dom_freq,
            "frequency": dom_freq,
        }

        overall_pass = True
        results: list = []

        for param, limits in self._spec.items():
            lo  = limits.get("min", float("-inf"))
            hi  = limits.get("max", float("inf"))
            unit = limits.get("unit", "")
            key  = param.lower().replace(" ", "")
            for mk, mv in MEAS_MAP.items():
                if mk in key or key in mk:
                    measured = mv
                    break
            else:
                measured = mean   # fallback to mean voltage

            passed = lo <= measured <= hi
            if not passed:
                overall_pass = False
            results.append((param, measured, lo, hi, unit, passed))

        # Update big verdict
        if overall_pass:
            self.lbl_verdict.setText("PASS")
            self.lbl_verdict.setStyleSheet(
                f"color: {T.PRIMARY}; background: #0a2a0a; "
                f"border-radius: 8px; border: 3px solid {T.PRIMARY}; font-weight: 900;")
        else:
            self.lbl_verdict.setText("FAIL")
            self.lbl_verdict.setStyleSheet(
                f"color: {T.ACCENT_RED}; background: #2a0a0a; "
                f"border-radius: 8px; border: 3px solid {T.ACCENT_RED}; font-weight: 900;")
        self._last_overall = overall_pass

        # Update param grid
        self._clear_param_grid()
        for row_i, (param, meas, lo, hi, unit, passed) in enumerate(results):
            col = T.PRIMARY if passed else T.ACCENT_RED
            pf  = "PASS" if passed else "FAIL"

            name_lbl = QLabel(param)
            meas_lbl = QLabel(f"{meas:.4f} {unit}")
            lim_lbl  = QLabel(f"[{lo} ... {hi}]")
            pf_lbl   = QLabel(pf)
            for lbl in (name_lbl, meas_lbl, lim_lbl, pf_lbl):
                lbl.setFont(_ui_font(SZ_BODY, bold=True))
                lbl.setStyleSheet(f"color: {col}; background: transparent; border: none;")
            self._param_grid.addWidget(name_lbl, row_i, 0)
            self._param_grid.addWidget(meas_lbl, row_i, 1)
            self._param_grid.addWidget(lim_lbl,  row_i, 2)
            self._param_grid.addWidget(pf_lbl,   row_i, 3)

            # Log
            _LOGGER.log(serial, "spec", param, meas, lo, hi, "PASS" if passed else "FAIL")

        self._refresh_history()

    def _clear_param_grid(self):
        while self._param_grid.count():
            item = self._param_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # -- History Table ---------------------------------------------------------

    def _refresh_history(self):
        rows = _LOGGER.recent(40)
        self._hist_table.setRowCount(len(rows))
        for i, (ts, serial, param, meas, pf) in enumerate(rows):
            col = T.PRIMARY if pf == "PASS" else T.ACCENT_RED
            items = [ts[-8:], serial, param, f"{meas:.4f}", pf]
            for j, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(col))
                self._hist_table.setItem(i, j, item)

    # -- Export ----------------------------------------------------------------

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Test Log",
            str(Path.home() / "prodtest_log.csv"),
            "CSV Files (*.csv)")
        if path:
            import shutil
            shutil.copy2(str(_LOGGER.CSV_PATH), path)
            QMessageBox.information(self, "Exported", f"Test log saved to:\n{path}")
