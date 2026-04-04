"""
tab_repl.py - Python REPL / Macro Engine for STM32 Lab GUI v6.0

Embeds a live Python console that exposes the full lab API:
    lab.send("#WAVE:F=500;")
    lab.snapshot()          -> list of floats (current DSO buffer)
    lab.sweep_freq(10, 100, steps=10)  -> list of results
    lab.stats()             -> dict

Includes:
  * Syntax-highlighted output (regex colour pass)
  * Save macro as .py script
  * Run a .py script file
  * Command history (Up/Down keys)
"""

import code
import datetime
import io
import os
import sys
import traceback
from pathlib import Path
from typing import Callable, List, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit,
    QLineEdit, QGroupBox, QFileDialog,
    QMessageBox, QSplitter
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QTextCharFormat, QFont, QSyntaxHighlighter, QTextDocument

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header


# 
# Minimal syntax highlighter (regex-based, no extra libs)
# 

import re

class _PythonHighlighter(QSyntaxHighlighter):
    KEYWORDS = r"\b(and|as|assert|async|await|break|class|continue|def|del|elif|else|" \
               r"except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|" \
               r"or|pass|raise|return|try|while|with|yield|True|False|None)\b"
    STRING1  = r"'[^'\\]*(?:\\.[^'\\]*)*'"
    STRING2  = r'"[^"\\]*(?:\\.[^"\\]*)*"'
    COMMENT  = r"#[^\n]*"
    NUMBER   = r"\b\d+\.?\d*\b"

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        def _fmt(color: str, bold: bool = False):
            f = QTextCharFormat()
            f.setForeground(QColor(color))
            if bold:
                f.setFontWeight(QFont.Bold)
            return f
        self._rules = [
            (re.compile(self.KEYWORDS), _fmt(T.ACCENT_PUR, bold=True)),
            (re.compile(self.STRING1),  _fmt(T.ACCENT_AMBER)),
            (re.compile(self.STRING2),  _fmt(T.ACCENT_AMBER)),
            (re.compile(self.COMMENT),  _fmt(T.TEXT_MUTED)),
            (re.compile(self.NUMBER),   _fmt(T.ACCENT_CYAN)),
        ]

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# 
# Lab API object exposed to the REPL namespace
# 

class LabAPI:
    """Proxy object exposed in the REPL as `lab`."""

    def __init__(self):
        self._send_fn: Callable[[str], None] = lambda _: None
        self._snapshot_fn: Callable[[], list] = lambda: []

    def send(self, cmd: str) -> None:
        """Send a raw command string to the STM32."""
        self._send_fn(cmd)

    def snapshot(self) -> list:
        """Return a copy of the current DSO buffer as a Python list."""
        return list(self._snapshot_fn())

    def stats(self) -> dict:
        """Return basic statistics on the current DSO buffer."""
        import numpy as np
        data = self.snapshot()
        if not data:
            return {}
        arr = np.array(data, dtype=float)
        return {
            "mean": float(np.mean(arr)),
            "std":  float(np.std(arr)),
            "min":  float(np.min(arr)),
            "max":  float(np.max(arr)),
            "n":    len(arr),
        }

    def sweep_freq(self, f_start: int, f_stop: int, steps: int = 10) -> list:
        """
        Sweep function-generator frequency from f_start to f_stop in `steps`.
        Returns list of (freq_hz, snapshot) tuples.
        NOTE: Blocking in REPL thread - use small steps.
        """
        import numpy as np
        import time
        freqs   = np.linspace(f_start, f_stop, steps, dtype=int)
        results = []
        for f in freqs:
            self._send_fn(f"#WAVE:F={int(f)};")
            time.sleep(0.25)   # settle
            results.append((int(f), self.snapshot()))
        return results


LAB_API = LabAPI()


# 
# REPL Tab
# 

class REPLTab(QWidget):
    """Embedded Python REPL with full lab API access."""

    send_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._history:      List[str] = []
        self._hist_idx:     int       = -1

        # Build an interactive console namespace
        self._namespace = {
            "lab":      LAB_API,
            "np":       __import__("numpy"),
            "datetime": datetime,
            "print":    self._repl_print,
        }
        try:
            import pandas as pd
            self._namespace["pd"] = pd
        except ImportError:
            pass

        self._console = code.InteractiveConsole(locals=self._namespace)
        self._build_ui()

        # Wire LAB_API to signals
        LAB_API._send_fn = self.send_requested.emit

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Python REPL / Macro Engine")
        self._header_strip = hdr

        self.btn_save = QPushButton("SAVE MACRO")
        self.btn_save.setObjectName("btn_warning")
        self.btn_save.setFixedWidth(130)
        self.btn_save.clicked.connect(self._save_macro)
        hdr_lay.addWidget(self.btn_save)

        self.btn_run_file = QPushButton("RUN FILE")
        self.btn_run_file.setFixedWidth(100)
        self.btn_run_file.clicked.connect(self._run_file)
        hdr_lay.addWidget(self.btn_run_file)

        self.btn_clear = QPushButton("CLEAR")
        self.btn_clear.setObjectName("btn_disconnect")
        self.btn_clear.setFixedWidth(80)
        self.btn_clear.clicked.connect(self._clear_output)
        hdr_lay.addWidget(self.btn_clear)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        #  Output console 
        out_grp = QGroupBox("OUTPUT")
        ol = QVBoxLayout(out_grp)
        ol.setContentsMargins(8, 20, 8, 8)
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(_ui_font(SZ_BODY))
        self._output.setStyleSheet(
            f"background: {T.DARK_BG}; color: {T.PRIMARY}; "
            f"border: 1px solid {T.BORDER}; font-family: Consolas, monospace;"
        )
        ol.addWidget(self._output)
        splitter.addWidget(out_grp)

        #  Script editor 
        ed_grp = QGroupBox("SCRIPT EDITOR  (Ctrl+Enter to run)")
        el = QVBoxLayout(ed_grp)
        el.setContentsMargins(8, 20, 8, 8)
        self._editor = QTextEdit()
        self._editor.setFont(_ui_font(SZ_BODY))
        self._editor.setStyleSheet(
            f"background: {T.PANEL_BG}; color: {T.TEXT}; "
            f"border: 1px solid {T.BORDER}; font-family: Consolas, monospace;"
        )
        self._editor.setPlaceholderText(
            "# Type or paste Python code here\n"
            "# lab.send('#WAVE:F=500;')\n"
            "# data = lab.snapshot()\n"
            "# print(lab.stats())\n"
        )
        self._highlighter = _PythonHighlighter(self._editor.document())
        el.addWidget(self._editor)
        splitter.addWidget(ed_grp)
        splitter.setSizes([400, 200])

        #  Single-line REPL input 
        input_grp = QGroupBox("COMMAND INPUT  (Enter to execute)")
        il = QVBoxLayout(input_grp)
        il.setContentsMargins(8, 20, 8, 8)
        irow = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setFont(_ui_font(SZ_BODY))
        self._input.setPlaceholderText(">>> ")
        self._input.returnPressed.connect(self._exec_line)
        self._input.installEventFilter(self)
        irow.addWidget(self._input, stretch=1)
        btn_exec = QPushButton("EXEC")
        btn_exec.setFixedWidth(70)
        btn_exec.clicked.connect(self._exec_line)
        irow.addWidget(btn_exec)
        btn_run_editor = QPushButton("RUN EDITOR")
        btn_run_editor.setFixedWidth(110)
        btn_run_editor.clicked.connect(self._exec_editor)
        irow.addWidget(btn_run_editor)
        il.addLayout(irow)
        root.addWidget(input_grp)

        # Welcome banner
        self._print_output(
            f"STM32 Lab Python REPL\n"
            f"Available: lab, np" + (", pd" if "pd" in self._namespace else "") + "\n"
            f"Type help(lab) for API reference.\n",
            T.ACCENT_CYAN
        )

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        self._output.setStyleSheet(
            f"background: {T.DARK_BG}; color: {T.PRIMARY}; "
            f"border: 1px solid {T.BORDER}; font-family: Consolas, monospace;"
        )
        self._editor.setStyleSheet(
            f"background: {T.PANEL_BG}; color: {T.TEXT}; "
            f"border: 1px solid {T.BORDER}; font-family: Consolas, monospace;"
        )

    # -- Public API ------------------------------------------------------------

    def set_snapshot_source(self, fn: Callable[[], list]):
        LAB_API._snapshot_fn = fn

    # -- REPL execution --------------------------------------------------------

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        from PyQt5.QtGui import QKeyEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up and self._history:
                self._hist_idx = max(0, self._hist_idx - 1)
                self._input.setText(self._history[self._hist_idx])
                return True
            elif key == Qt.Key_Down and self._history:
                self._hist_idx = min(len(self._history), self._hist_idx + 1)
                self._input.setText(
                    self._history[self._hist_idx]
                    if self._hist_idx < len(self._history) else "")
                return True
        return super().eventFilter(obj, event)

    def _exec_line(self):
        line = self._input.text().strip()
        if not line:
            return
        self._history.append(line)
        self._hist_idx = len(self._history)
        self._input.clear()
        self._print_output(f">>> {line}", T.ACCENT_BLUE)
        self._run_code(line)

    def _exec_editor(self):
        code_text = self._editor.toPlainText().strip()
        if not code_text:
            return
        self._print_output("--- Running editor script ---", T.TEXT_MUTED)
        self._run_code(code_text, multiline=True)

    def _run_code(self, code_text: str, multiline: bool = False):
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = _StringCapture()
        sys.stderr = _StringCapture()
        try:
            if multiline:
                exec(compile(code_text, "<editor>", "exec"), self._namespace)
            else:
                self._console.push(code_text)
        except Exception:
            self._print_output(traceback.format_exc(), T.ACCENT_RED)
        finally:
            out = sys.stdout.getvalue()
            err = sys.stderr.getvalue()
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            if out:
                self._print_output(out.rstrip(), T.PRIMARY)
            if err:
                self._print_output(err.rstrip(), T.ACCENT_RED)

    def _repl_print(self, *args, **kwargs):
        text = " ".join(str(a) for a in args)
        self._print_output(text, T.PRIMARY)

    def _print_output(self, text: str, color: str = None):
        col = color or T.TEXT
        self._output.append(
            f'<span style="color:{col}; font-family:Consolas,monospace; '
            f'white-space:pre;">{_html_escape(text)}</span>'
        )
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_output(self):
        self._output.clear()

    # -- Macro file ops --------------------------------------------------------

    def _save_macro(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Macro",
            str(Path.home() / f"stm32_macro_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.py"),
            "Python Scripts (*.py)"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                header = (
                    "# STM32 Lab Macro  -  auto-generated\n"
                    "# Run headlessly: python this_file.py\n"
                    "# Or paste into the REPL editor.\n\n"
                )
                f.write(header + self._editor.toPlainText())
            self._print_output(f"Macro saved: {path}", T.ACCENT_AMBER)

    def _run_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Script", str(Path.home()),
            "Python Scripts (*.py)"
        )
        if path:
            with open(path, "r", encoding="utf-8") as f:
                code_text = f.read()
            self._editor.setPlainText(code_text)
            self._print_output(f"Loaded: {path}", T.TEXT_MUTED)
            self._exec_editor()


class _StringCapture(io.StringIO):
    pass


def _html_escape(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
                .replace(" ", "&nbsp;"))
