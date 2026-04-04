"""
tab_wavedb.py - Waveform Database & Search for STM32 Lab GUI v6.0

Every capture is hashed and stored in a local SQLite database with:
  * tags, notes, metadata (freq range, amplitude, date)
  * Search by: waveform hash/similarity, frequency range, date, tag, amplitude
  * Thumbnail waveform previews in search results
  * "Compare with current capture" overlay

WHY: Solves the universal "I saw this glitch before but can't find it" problem.
"""

import hashlib
import datetime
import sqlite3
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
import pyqtgraph as pg

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QDoubleSpinBox,
    QGroupBox, QListWidget, QListWidgetItem, QSplitter,
    QTextEdit, QMessageBox, QTabWidget, QDateEdit
)
from PyQt5.QtCore import Qt, QDate, pyqtSignal
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header
from plot_trace_colors import TraceColorBar

DB_PATH = Path.home() / ".stm32lab" / "wavedb.sqlite"


# 
# Database Layer
# 

class WaveformDatabase:
    """SQLite backend for waveform captures."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS waveforms (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ts        TEXT NOT NULL,
        wave_hash TEXT NOT NULL,
        tag       TEXT DEFAULT '',
        notes     TEXT DEFAULT '',
        freq_min  REAL DEFAULT 0,
        freq_max  REAL DEFAULT 0,
        amp_vpp   REAL DEFAULT 0,
        amp_mean  REAL DEFAULT 0,
        n_samples INTEGER DEFAULT 0,
        data_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ts   ON waveforms(ts);
    CREATE INDEX IF NOT EXISTS idx_tag  ON waveforms(tag);
    CREATE INDEX IF NOT EXISTS idx_hash ON waveforms(wave_hash);
    """

    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.executescript(self.SCHEMA)
        self._conn.commit()

    def save(self, samples: list, tag: str = "", notes: str = "", fs: float = 100.0) -> int:
        import json
        arr = np.array(samples, dtype=float)
        n   = len(arr)
        if n == 0:
            return -1

        # Hash of downsampled waveform (64 points)
        ds  = np.interp(np.linspace(0, n-1, 64), np.arange(n), arr)
        h   = hashlib.sha256(ds.tobytes()).hexdigest()[:16]

        # Stats
        # fs is nowpassed as an argument
        mag  = np.abs(np.fft.rfft(arr - np.mean(arr)))
        frqs = np.fft.rfftfreq(n, 1.0/fs)
        if len(mag) > 1:
            dom_bin  = int(np.argmax(mag[1:])) + 1
            freq_dom = float(frqs[min(dom_bin, len(frqs)-1)])
        else:
            freq_dom = 0.0

        cur = self._conn.execute(
            "INSERT INTO waveforms "
            "(ts, wave_hash, tag, notes, freq_min, freq_max, amp_vpp, amp_mean, n_samples, data_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                datetime.datetime.now().isoformat(),
                h, tag, notes,
                0.0,       # freq_min = DC (BUG-FIX: was freq_dom)
                freq_dom,  # freq_max = dominant frequency
                float(np.max(arr) - np.min(arr)),
                float(np.mean(arr)),
                n,
                json.dumps(arr.tolist()),
            )
        )
        self._conn.commit()
        return cur.lastrowid

    def search(self, tag: str = "", date_from: str = "",
               date_to: str = "", freq_min: float = 0,
               freq_max: float = 1e9, amp_min: float = -1e9,
               amp_max: float = 1e9) -> list:
        """Return matching rows as list of dicts."""
        clauses = []
        params  = []
        if tag:
            clauses.append("tag LIKE ?")
            params.append(f"%{tag}%")
        if date_from:
            clauses.append("ts >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("ts <= ?")
            params.append(date_to + "T23:59:59")
        clauses.append("freq_min >= ? AND freq_max <= ?")
        params += [freq_min, freq_max]
        clauses.append("amp_vpp >= ? AND amp_vpp <= ?")
        params += [amp_min, amp_max]
        where = " AND ".join(clauses) if clauses else "1"
        cur = self._conn.execute(
            f"SELECT id,ts,wave_hash,tag,notes,freq_min,amp_vpp,n_samples "
            f"FROM waveforms WHERE {where} ORDER BY ts DESC LIMIT 200",
            params
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def load(self, row_id: int) -> Optional[list]:
        import json
        cur = self._conn.execute(
            "SELECT data_json FROM waveforms WHERE id=?", (row_id,))
        row = cur.fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, row_id: int):
        self._conn.execute("DELETE FROM waveforms WHERE id=?", (row_id,))
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM waveforms").fetchone()[0]


# 
# Waveform Database Tab
# 

_DB = WaveformDatabase()   # singleton


class WaveformDBTab(QWidget):
    """Search, browse, and compare stored waveform captures."""

    overlay_requested = pyqtSignal(object)   # np.ndarray

    def __init__(self, settings=None):
        super().__init__()
        self._settings = settings
        self._trace_bar: Optional[TraceColorBar] = None
        self._header_strip: Optional[_HeaderStrip] = None
        self._dso_source: Callable[[], list] = lambda: []
        self._current_id: Optional[int] = None
        self.sample_period = 0.010 # default
        self._build_ui()
        self._refresh_search()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Waveform Database & Search")
        self._header_strip = hdr

        self.btn_save_cap = QPushButton("[*] SAVE CAPTURE")
        self.btn_save_cap.setFixedWidth(160)
        self.btn_save_cap.clicked.connect(self._save_current)
        hdr_lay.addWidget(self.btn_save_cap)

        self.btn_overlay = QPushButton("OVERLAY")
        self.btn_overlay.setObjectName("btn_warning")
        self.btn_overlay.setFixedWidth(110)
        self.btn_overlay.setEnabled(False)
        self.btn_overlay.clicked.connect(self._request_overlay)
        hdr_lay.addWidget(self.btn_overlay)

        self.btn_delete = QPushButton("DELETE")
        self.btn_delete.setObjectName("btn_disconnect")
        self.btn_delete.setFixedWidth(90)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete_selected)
        hdr_lay.addWidget(self.btn_delete)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: search controls ---------------------------------------------
        ctrl_w = QWidget()
        ctrl_w.setMaximumWidth(280)
        c_lay = QVBoxLayout(ctrl_w)
        c_lay.setContentsMargins(12, 12, 12, 12)
        c_lay.setSpacing(10)

        srch_grp = QGroupBox("SEARCH FILTERS")
        sg = QGridLayout(srch_grp)
        sg.setSpacing(6)
        sg.setContentsMargins(10, 22, 10, 10)

        sg.addWidget(ThemeLabel("Tag:", "TEXT_MUTED", SZ_SM, bold=True), 0, 0)
        self.txt_tag = QLineEdit()
        self.txt_tag.setPlaceholderText("any")
        sg.addWidget(self.txt_tag, 0, 1)

        sg.addWidget(ThemeLabel("Date from:", "TEXT_MUTED", SZ_SM, bold=True), 1, 0)
        self.date_from = QDateEdit()
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(QDate.currentDate().addDays(-30))
        sg.addWidget(self.date_from, 1, 1)

        sg.addWidget(ThemeLabel("Date to:", "TEXT_MUTED", SZ_SM, bold=True), 2, 0)
        self.date_to = QDateEdit()
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(QDate.currentDate())
        sg.addWidget(self.date_to, 2, 1)

        sg.addWidget(ThemeLabel("Freq min:", "TEXT_MUTED", SZ_SM, bold=True), 3, 0)
        self.spin_fmin = QDoubleSpinBox()
        self.spin_fmin.setRange(0, 100000)
        self.spin_fmin.setValue(0)
        self.spin_fmin.setSuffix(" Hz")
        sg.addWidget(self.spin_fmin, 3, 1)

        sg.addWidget(ThemeLabel("Freq max:", "TEXT_MUTED", SZ_SM, bold=True), 4, 0)
        self.spin_fmax = QDoubleSpinBox()
        self.spin_fmax.setRange(0, 200000)
        self.spin_fmax.setValue(200000)
        self.spin_fmax.setSuffix(" Hz")
        sg.addWidget(self.spin_fmax, 4, 1)

        sg.addWidget(ThemeLabel("Amp min:", "TEXT_MUTED", SZ_SM, bold=True), 5, 0)
        self.spin_amin = QDoubleSpinBox()
        self.spin_amin.setRange(-100, 100)
        self.spin_amin.setValue(0)
        self.spin_amin.setSuffix(" Vpp")
        sg.addWidget(self.spin_amin, 5, 1)

        c_lay.addWidget(srch_grp)

        btn_srch = QPushButton("SEARCH")
        btn_srch.clicked.connect(self._refresh_search)
        c_lay.addWidget(btn_srch)

        # DB stats
        self.lbl_count = QLabel("0 captures")
        self.lbl_count.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px;")
        c_lay.addWidget(self.lbl_count)

        # Tag for saving
        c_lay.addWidget(ThemeLabel("Tag new capture:", "TEXT_MUTED", SZ_SM, bold=True))
        self.txt_save_tag = QLineEdit()
        self.txt_save_tag.setPlaceholderText("optional tag")
        c_lay.addWidget(self.txt_save_tag)
        c_lay.addStretch()
        splitter.addWidget(ctrl_w)

        # -- RIGHT: results + preview ------------------------------------------
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(8)

        self._result_list = QListWidget()
        self._result_list.currentRowChanged.connect(self._on_selection_changed)
        r_lay.addWidget(self._result_list, stretch=1)

        # Preview plot
        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self._preview_plot = pg.PlotWidget()
        self._preview_plot.setFixedHeight(180)
        self._preview_plot.setLabel("left",   "V", color=T.TEXT_MUTED)
        self._preview_plot.setLabel("bottom", "samples", color=T.TEXT_MUTED)
        self._preview_plot.showGrid(x=True, y=True, alpha=0.12)
        self._preview_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._preview_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self._preview_curve = self._preview_plot.plot(
            pen=pg.mkPen(T.ACCENT_BLUE, width=2))
        r_lay.addWidget(self._preview_plot)

        wc = QHBoxLayout()
        wl = QLabel("Preview trace")
        wl.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-weight: 600;")
        wc.addWidget(wl)
        self._trace_bar = TraceColorBar(self._settings, "wavedb", self)
        self._trace_bar.add_trace(
            "preview", "Prv", "Database waveform preview", "ACCENT_BLUE",
            items=[self._preview_curve], width=2.0,
        )
        wc.addWidget(self._trace_bar)
        wc.addStretch()
        r_lay.addLayout(wc)

        # Notes field
        note_grp = QGroupBox("NOTES")
        nl = QVBoxLayout(note_grp)
        nl.setContentsMargins(8, 20, 8, 8)
        self._notes_box = QTextEdit()
        self._notes_box.setReadOnly(True)
        self._notes_box.setFixedHeight(90)
        self._notes_box.setFont(_ui_font(SZ_SM))
        nl.addWidget(self._notes_box)
        r_lay.addWidget(note_grp)

        splitter.addWidget(right_w)
        splitter.setSizes([260, 900])

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        self._preview_plot.setBackground(T.DARK_BG)
        self._preview_plot.getAxis("left").setTextPen(T.TEXT_MUTED)
        self._preview_plot.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        if self._trace_bar:
            self._trace_bar.refresh_theme_defaults_only()

    # -- Public API ------------------------------------------------------------

    def set_dso_source(self, fn: Callable[[], list]):
        self._dso_source = fn

    # -- Actions ---------------------------------------------------------------

    def _save_current(self):
        raw = self._dso_source()
        if len(raw) < 4:
            QMessageBox.information(self, "No Data",
                "DSO buffer is empty. Connect hardware first.")
            return
        tag = self.txt_save_tag.text().strip()
        row_id = _DB.save(raw, tag=tag, fs=1.0/self.sample_period)
        if row_id > 0:
            self._refresh_search()
            QMessageBox.information(self, "Saved",
                f"Capture saved to database (id={row_id}).")

    def _delete_selected(self):
        if self._current_id is None:
            return
        r = QMessageBox.question(self, "Delete",
            f"Delete capture id={self._current_id}?",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            _DB.delete(self._current_id)
            self._current_id = None
            self.btn_overlay.setEnabled(False)
            self.btn_delete.setEnabled(False)
            self._refresh_search()

    def _request_overlay(self):
        if self._current_id is None:
            return
        data = _DB.load(self._current_id)
        if data:
            self.overlay_requested.emit(np.array(data, dtype=float))

    def _refresh_search(self):
        tag     = self.txt_tag.text().strip()
        df      = self.date_from.date().toString("yyyy-MM-dd")
        dt      = self.date_to.date().toString("yyyy-MM-dd")
        rows    = _DB.search(
            tag=tag, date_from=df, date_to=dt,
            freq_min=self.spin_fmin.value(),
            freq_max=self.spin_fmax.value(),
            amp_min=self.spin_amin.value(),
        )
        self._result_list.clear()
        self._result_rows = rows
        for r in rows:
            ts    = r["ts"][:19]
            label = (f"[{r['id']:04d}]  {ts}  |  "
                     f"tag={r['tag'] or '-'}  |  "
                     f"Vpp={r['amp_vpp']:.2f}V  |  "
                     f"f~{r['freq_min']:.0f}Hz  |  n={r['n_samples']}")
            item  = QListWidgetItem(label)
            item.setForeground(QColor(T.TEXT))
            self._result_list.addItem(item)
        total = _DB.count()
        self.lbl_count.setText(f"{len(rows)} results  ({total} total captures)")

    def _on_selection_changed(self, row: int):
        if row < 0 or row >= len(getattr(self, "_result_rows", [])):
            return
        r = self._result_rows[row]
        self._current_id = r["id"]
        self.btn_overlay.setEnabled(True)
        self.btn_delete.setEnabled(True)
        # Load and preview
        data = _DB.load(r["id"])
        if data:
            arr = np.array(data, dtype=float)
            self._preview_curve.setData(np.arange(len(arr)), arr)
        self._notes_box.setPlainText(r.get("notes", ""))
