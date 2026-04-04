"""
tab_playback.py - CSV / SQLite Playback tab for STM32 Lab GUI v6.0

Loads a previously recorded .csv or .db (SQLite) file and replays it at
adjustable speed through all live display widgets via a scrubber / timeline.

HOW IT WORKS
------------
* User picks a file (CSV or SQLite DB produced by the DataLogger)
* A QSlider scrubber spans the full row index
* A QTimer fires at the selected replay rate, advancing the row pointer
* Each row is unpacked into a ParsedMessage-like dict and emitted via
  the replay_row signal so MainWindow can feed it to existing tabs
"""

import csv
import sqlite3
from pathlib import Path
from typing import List, Optional, Dict

import numpy as np

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QComboBox,
    QGroupBox, QFileDialog, QMessageBox,
    QDoubleSpinBox, QSpinBox, QProgressBar, QSizePolicy
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header


class PlaybackTab(QWidget):
    """CSV / SQLite capture replay with adjustable scrubber."""

    # Emitted for each replayed row; dict matches DataLogger COLUMNS
    replay_row = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._rows:  List[dict] = []
        self._pos:   int        = 0
        self._playing = False

        self._timer = QTimer()
        self._timer.timeout.connect(self._tick)

        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("CSV / SQLite Playback")
        self._header_strip = hdr

        self.btn_open = QPushButton("OPEN FILE")
        self.btn_open.setObjectName("btn_warning")
        self.btn_open.setFixedWidth(120)
        self.btn_open.clicked.connect(self._open_file)
        hdr_lay.addWidget(self.btn_open)

        self.btn_play = QPushButton(">  PLAY")
        self.btn_play.setFixedWidth(100)
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self._play_pause)
        hdr_lay.addWidget(self.btn_play)

        self.btn_stop = QPushButton("[]  STOP")
        self.btn_stop.setObjectName("btn_disconnect")
        self.btn_stop.setFixedWidth(100)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)
        hdr_lay.addWidget(self.btn_stop)

        root.addWidget(hdr)

        content = QWidget()
        c_lay = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(14)
        root.addWidget(content, stretch=1)

        # -- File info ---------------------------------------------------------
        info_grp = QGroupBox("FILE INFO")
        ig_lay = QVBoxLayout(info_grp)
        ig_lay.setContentsMargins(12, 20, 12, 12)
        ig_lay.setSpacing(6)
        c_lay.addWidget(info_grp)

        self.lbl_file    = ThemeLabel("No file loaded", "TEXT_MUTED", SZ_BODY)
        self.lbl_rows    = ThemeLabel("Rows: -", "TEXT_MUTED", SZ_SM)
        self.lbl_columns = ThemeLabel("Columns: -", "TEXT_MUTED", SZ_SM)
        ig_lay.addWidget(self.lbl_file)
        ig_lay.addWidget(self.lbl_rows)
        ig_lay.addWidget(self.lbl_columns)

        # -- Timeline scrubber -------------------------------------------------
        tl_grp = QGroupBox("TIMELINE")
        tl_lay = QVBoxLayout(tl_grp)
        tl_lay.setContentsMargins(12, 20, 12, 12)
        tl_lay.setSpacing(8)
        c_lay.addWidget(tl_grp)

        self.scrubber = QSlider(Qt.Horizontal)
        self.scrubber.setRange(0, 0)
        self.scrubber.valueChanged.connect(self._on_scrub)
        tl_lay.addWidget(self.scrubber)

        pos_row = QHBoxLayout()
        self.lbl_pos = ThemeLabel("Row: 0 / 0", "TEXT_MUTED", SZ_SM)
        pos_row.addWidget(self.lbl_pos)
        pos_row.addStretch()
        self.lbl_ts  = ThemeLabel("-", "PRIMARY", SZ_SM)
        pos_row.addWidget(self.lbl_ts)
        tl_lay.addLayout(pos_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        tl_lay.addWidget(self.progress)

        # -- Playback speed ----------------------------------------------------
        speed_grp = QGroupBox("PLAYBACK SPEED")
        sg_lay = QHBoxLayout(speed_grp)
        sg_lay.setContentsMargins(12, 20, 12, 12)
        sg_lay.setSpacing(12)
        c_lay.addWidget(speed_grp)

        sg_lay.addWidget(ThemeLabel("Speed:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_speed = QDoubleSpinBox()
        self.spin_speed.setRange(0.1, 100.0)
        self.spin_speed.setValue(1.0)
        self.spin_speed.setSuffix("x")
        self.spin_speed.setDecimals(1)
        self.spin_speed.setFixedWidth(90)
        self.spin_speed.valueChanged.connect(self._update_timer_interval)
        sg_lay.addWidget(self.spin_speed)

        sg_lay.addWidget(ThemeLabel("Rows/tick:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_rows_tick = QSpinBox()
        self.spin_rows_tick.setRange(1, 100)
        self.spin_rows_tick.setValue(1)
        sg_lay.addWidget(self.spin_rows_tick)
        sg_lay.addStretch()

        # -- Current row stat cards --------------------------------------------
        cards_row = QHBoxLayout()
        c_lay.addLayout(cards_row)
        self.lbl_val  = QLabel("-")
        self.lbl_mode = QLabel("-")
        self.lbl_unit = QLabel("-")
        cards_row.addWidget(ThemeCard("VALUE", self.lbl_val,  "PRIMARY"))
        cards_row.addWidget(ThemeCard("MODE",  self.lbl_mode, "ACCENT_BLUE"))
        cards_row.addWidget(ThemeCard("UNIT",  self.lbl_unit, "ACCENT_AMBER"))
        c_lay.addStretch()

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()

    # -- File Loading ----------------------------------------------------------

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Capture File",
            str(Path.home()),
            "CSV / SQLite (*.csv *.db *.sqlite *.sqlite3);;All Files (*)"
        )
        if not path:
            return
        suffix = Path(path).suffix.lower()
        try:
            if suffix == ".csv":
                self._load_csv(path)
            else:
                self._load_sqlite(path)
        except Exception as e:
            QMessageBox.critical(self, "Load Error", str(e))

    def _load_csv(self, path: str):
        rows = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(dict(row))
        self._init_rows(rows, path)

    def _load_sqlite(self, path: str):
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        # Auto-detect first table (BUG-FIX: was hardcoded 'readings')
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid LIMIT 1")
        row = cur.fetchone()
        if row is None:
            conn.close()
            raise ValueError("No tables found in SQLite database.")
        table = row[0]
        cur = conn.execute(f"SELECT * FROM {table} ORDER BY rowid")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self._init_rows(rows, path)

    def _init_rows(self, rows: List[dict], path: str):
        self._rows   = rows
        self._pos    = 0
        n            = len(rows)
        self.scrubber.setRange(0, max(0, n - 1))
        self.scrubber.setValue(0)
        self.lbl_file.setText(Path(path).name)
        self.lbl_rows.setText(f"Rows: {n}")
        cols = list(rows[0].keys()) if rows else []
        self.lbl_columns.setText(f"Columns: {', '.join(cols)}")
        self.btn_play.setEnabled(n > 0)
        self.btn_stop.setEnabled(False)
        self._update_cards(rows[0] if rows else {})
        self._update_pos_label()

    # -- Playback engine -------------------------------------------------------

    def _play_pause(self):
        if self._playing:
            self._playing = False
            self._timer.stop()
            self.btn_play.setText(">  PLAY")
        else:
            if self._pos >= len(self._rows) - 1:
                self._pos = 0
                self.scrubber.setValue(0)
            self._playing = True
            self._update_timer_interval()
            self._timer.start()
            self.btn_play.setText("||  PAUSE")
            self.btn_stop.setEnabled(True)

    def _stop(self):
        self._playing = False
        self._timer.stop()
        self._pos = 0
        self.scrubber.setValue(0)
        self.btn_play.setText("  PLAY")
        self.btn_stop.setEnabled(False)

    def _tick(self):
        n = len(self._rows)
        if n == 0 or self._pos >= n:
            self._stop()
            return
        step = max(1, self.spin_rows_tick.value())
        for _ in range(step):
            if self._pos < n:
                row = self._rows[self._pos]
                self.replay_row.emit(row)
                self._pos += 1
        self.scrubber.blockSignals(True)
        self.scrubber.setValue(self._pos)
        self.scrubber.blockSignals(False)
        self._update_cards(self._rows[min(self._pos, n-1)])
        self._update_pos_label()
        if self._pos >= n:
            self._stop()

    def _update_timer_interval(self, _=None):
        # Base: 100 ms per row at 1
        base_ms = 100
        speed   = max(0.1, self.spin_speed.value())
        interval = max(10, int(base_ms / speed))
        self._timer.setInterval(interval)

    def _on_scrub(self, value: int):
        self._pos = value
        if self._rows:
            self._update_cards(self._rows[min(value, len(self._rows)-1)])
        self._update_pos_label()

    def _update_cards(self, row: dict):
        self.lbl_val.setText(str(row.get("value", "-")))
        self.lbl_mode.setText(str(row.get("mode", "-")))
        self.lbl_unit.setText(str(row.get("unit", "-")))
        self.lbl_ts.setText(str(row.get("timestamp", "")))

    def _update_pos_label(self):
        n = len(self._rows)
        self.lbl_pos.setText(f"Row: {self._pos} / {n}")
        pct = int(self._pos / n * 100) if n else 0
        self.progress.setValue(pct)
