"""
tab_journal.py - Experiment Journal for STM32 Lab GUI v6.0

A structured lab notebook docked inside the instrument:
  * Timestamped entries linked to waveform screenshots
  * Rich text editor (QTextEdit with HTML)
  * Timeline markers referencing capture positions
  * Export to Markdown or HTML (portable lab report)

WHY: Lab notebooks are mandatory in industry (FDA, ISO) and academia.
     Keeping notes inside the instrument eliminates time-synchronisation
     errors between notebook and measurement data.
"""

import datetime
import json
import os
from pathlib import Path
from typing import List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QListWidget,
    QListWidgetItem, QGroupBox, QSplitter,
    QLineEdit, QFileDialog, QMessageBox, QInputDialog
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header

JOURNAL_PATH = Path.home() / ".stm32lab" / "journal.json"


class JournalEntry:
    def __init__(self, title: str = "", content: str = "",
                 tags: str = "", ts: str = ""):
        self.ts      = ts or datetime.datetime.now().isoformat()
        self.title   = title or f"Entry {self.ts[:10]}"
        self.content = content
        self.tags    = tags

    def to_dict(self) -> dict:
        return {"ts": self.ts, "title": self.title,
                "content": self.content, "tags": self.tags}

    @classmethod
    def from_dict(cls, d: dict) -> "JournalEntry":
        return cls(d.get("title",""), d.get("content",""),
                   d.get("tags",""), d.get("ts",""))


class JournalStore:
    def __init__(self):
        self._entries: List[JournalEntry] = []
        self._load()

    def _load(self):
        if JOURNAL_PATH.exists():
            try:
                data = json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
                self._entries = [JournalEntry.from_dict(d) for d in data]
            except Exception:
                self._entries = []

    def save(self):
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        JOURNAL_PATH.write_text(
            json.dumps([e.to_dict() for e in self._entries], indent=2),
            encoding="utf-8"
        )

    def add(self, entry: JournalEntry):
        self._entries.insert(0, entry)
        self.save()

    def delete(self, idx: int):
        if 0 <= idx < len(self._entries):
            self._entries.pop(idx)
            self.save()

    def update(self, idx: int, entry: JournalEntry):
        if 0 <= idx < len(self._entries):
            self._entries[idx] = entry
            self.save()

    @property
    def entries(self) -> List[JournalEntry]:
        return self._entries


_STORE = JournalStore()


class JournalTab(QWidget):
    """Structured experiment journal tied to instrument captures."""

    attach_screenshot_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._current_idx: Optional[int] = None
        self._last_screenshot: Optional[str] = None
        self._build_ui()
        self._refresh_list()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Experiment Journal")
        self._header_strip = hdr

        self.btn_new = QPushButton("+ NEW ENTRY")
        self.btn_new.setObjectName("btn_connect")
        self.btn_new.setFixedWidth(130)
        self.btn_new.clicked.connect(self._new_entry)
        hdr_lay.addWidget(self.btn_new)

        self.btn_save_entry = QPushButton("SAVE")
        self.btn_save_entry.setObjectName("btn_warning")
        self.btn_save_entry.setFixedWidth(90)
        self.btn_save_entry.clicked.connect(self._save_current)
        hdr_lay.addWidget(self.btn_save_entry)

        self.btn_delete = QPushButton("DELETE")
        self.btn_delete.setObjectName("btn_disconnect")
        self.btn_delete.setFixedWidth(90)
        self.btn_delete.setEnabled(False)
        self.btn_delete.clicked.connect(self._delete_current)
        hdr_lay.addWidget(self.btn_delete)

        self.btn_export_md  = QPushButton("EXPORT MD")
        self.btn_export_md.setFixedWidth(120)
        self.btn_export_md.clicked.connect(lambda: self._export("md"))
        hdr_lay.addWidget(self.btn_export_md)

        self.btn_export_html = QPushButton("EXPORT HTML")
        self.btn_export_html.setFixedWidth(130)
        self.btn_export_html.clicked.connect(lambda: self._export("html"))
        hdr_lay.addWidget(self.btn_export_html)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- LEFT: entry list --------------------------------------------------
        list_w = QWidget()
        list_w.setMaximumWidth(280)
        ll = QVBoxLayout(list_w)
        ll.setContentsMargins(10, 10, 10, 10)
        ll.setSpacing(8)

        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search...")
        self._search.textChanged.connect(self._refresh_list)
        search_row.addWidget(self._search)
        ll.addLayout(search_row)

        self._entry_list = QListWidget()
        self._entry_list.currentRowChanged.connect(self._on_select)
        ll.addWidget(self._entry_list, stretch=1)
        splitter.addWidget(list_w)

        # -- RIGHT: editor -----------------------------------------------------
        ed_w = QWidget()
        el = QVBoxLayout(ed_w)
        el.setContentsMargins(10, 10, 10, 10)
        el.setSpacing(8)

        # Title + tags row
        meta_row = QHBoxLayout()
        self._title_edit = QLineEdit()
        self._title_edit.setPlaceholderText("Entry title")
        self._title_edit.setFont(QFont("Segoe UI", 12, QFont.Bold))
        meta_row.addWidget(self._title_edit, stretch=2)
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("tags, comma, separated")
        meta_row.addWidget(self._tags_edit, stretch=1)
        el.addLayout(meta_row)

        # Timestamp label
        self._ts_label = ThemeLabel("-", "TEXT_MUTED", SZ_SM)
        el.addWidget(self._ts_label)

        # Content editor
        self._editor = QTextEdit()
        self._editor.setFont(_ui_font(SZ_BODY))
        self._editor.setPlaceholderText(
            "Write your experiment notes here...\n\n"
            "- Describe your setup\n"
            "- Record observations\n"
            "- Note anomalies\n"
            "- Paste calibration values\n"
        )
        el.addWidget(self._editor, stretch=1)

        # Screenshot attachment
        att_row = QHBoxLayout()
        self._lbl_screenshot = ThemeLabel("No screenshot attached", "TEXT_MUTED", SZ_SM)
        att_row.addWidget(self._lbl_screenshot)
        att_row.addStretch()
        btn_ss = QPushButton("ATTACH SCREENSHOT")
        btn_ss.setFixedWidth(180)
        btn_ss.clicked.connect(self._attach_screenshot)
        att_row.addWidget(btn_ss)
        el.addLayout(att_row)

        splitter.addWidget(ed_w)
        splitter.setSizes([260, 900])

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()

    # -- Public API ------------------------------------------------------------

    def set_last_screenshot(self, path: str):
        """Called by MainWindow whenever a new screenshot is taken."""
        self._last_screenshot = path

    #  List management 

    def _refresh_list(self, query: str = ""):
        q = (query or self._search.text()).lower()
        self._entry_list.clear()
        self._filtered_indices = []
        for i, e in enumerate(_STORE.entries):
            if q and q not in e.title.lower() and q not in e.content.lower():
                continue
            ts_short = e.ts[:10]
            label    = f"[{ts_short}]  {e.title[:35]}"
            item     = QListWidgetItem(label)
            item.setForeground(QColor(T.TEXT))
            self._entry_list.addItem(item)
            self._filtered_indices.append(i)

    def _on_select(self, row: int):
        if row < 0 or row >= len(self._filtered_indices):
            return
        idx = self._filtered_indices[row]
        e   = _STORE.entries[idx]
        self._current_idx = idx
        self._title_edit.setText(e.title)
        self._tags_edit.setText(e.tags)
        self._ts_label.setText(f"Created: {e.ts[:19]}")
        self._editor.setHtml(e.content)
        self.btn_delete.setEnabled(True)

    # -- Entry CRUD ------------------------------------------------------------

    def _new_entry(self):
        e = JournalEntry()
        _STORE.add(e)
        self._refresh_list()
        self._entry_list.setCurrentRow(0)
        self._title_edit.setFocus()

    def _save_current(self):
        if self._current_idx is None:
            self._new_entry()
            return
        e = JournalEntry(
            title   = self._title_edit.text().strip() or "Untitled",
            content = self._editor.toHtml(),
            tags    = self._tags_edit.text().strip(),
            ts      = _STORE.entries[self._current_idx].ts,
        )
        _STORE.update(self._current_idx, e)
        self._refresh_list()

    def _delete_current(self):
        if self._current_idx is None:
            return
        r = QMessageBox.question(self, "Delete Entry",
            "Permanently delete this journal entry?",
            QMessageBox.Yes | QMessageBox.No)
        if r == QMessageBox.Yes:
            _STORE.delete(self._current_idx)
            self._current_idx = None
            self._editor.clear()
            self._title_edit.clear()
            self.btn_delete.setEnabled(False)
            self._refresh_list()

    def _attach_screenshot(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Attach Screenshot",
            self._last_screenshot or str(Path.home()),
            "Images (*.png *.jpg *.bmp)"
        )
        if path:
            self._lbl_screenshot.setText(os.path.basename(path))
            self._editor.insertHtml(
                f'<br><img src="{path}" width="600"><br>'
                f'<i style="color:{T.TEXT_MUTED}">Screenshot: {path}</i><br>'
            )

    # -- Export ----------------------------------------------------------------

    def _export(self, fmt: str):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Journal",
            str(Path.home() / f"stm32_journal.{fmt}"),
            f"{fmt.upper()} Files (*.{fmt})"
        )
        if not path:
            return
        try:
            if fmt == "md":
                lines = ["# STM32 Lab Experiment Journal\n"]
                for e in _STORE.entries:
                    lines += [
                        f"\n## {e.title}",
                        f"*{e.ts[:19]}*  *  Tags: `{e.tags}`\n",
                        # Strip HTML to plain text
                        e.content.replace("<br>", "\n").replace("</p>", "\n"),
                        "\n---\n",
                    ]
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            else:  # html
                lines = [
                    "<html><head><meta charset='utf-8'></head><body>",
                    f"<h1>STM32 Lab Experiment Journal</h1>",
                ]
                for e in _STORE.entries:
                    lines += [
                        f"<h2>{e.title}</h2>",
                        f"<p><small>{e.ts[:19]} | Tags: {e.tags}</small></p>",
                        e.content,
                        "<hr>",
                    ]
                lines.append("</body></html>")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
            QMessageBox.information(self, "Exported", f"Journal exported to:\n{path}")
        except Exception as ex:
            QMessageBox.critical(self, "Export Error", str(ex))
