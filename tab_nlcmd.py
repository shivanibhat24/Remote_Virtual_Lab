"""
tab_nlcmd.py - Natural Language Command Interface for STM32 Lab GUI v6.0

Parses plain-English commands with a local regex/grammar engine (no API key):
  "set output to 3.3V"        -> #VREG:V=3.3;
  "show me a 500Hz square wave" -> #WAVE:T=SQ; + #WAVE:F=500;
  "what is the dominant frequency?" -> reads stats and responds
  "connect"                   -> triggers serial connect
  "disconnect"                -> serial disconnect

WHY: Accessibility + novelty - great for education + papers.
"""

import re
from typing import Callable, List, Optional, Tuple

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QTextEdit, QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header


# -- Grammar Engine -----------------------------------------------------------

_VOLT_PAT  = r"(\d+\.?\d*)\s*[vV](?:olt(?:s)?)?"
_FREQ_PAT  = r"(\d+\.?\d*)\s*(?:Hz|hz|KHz|kHz|khz)?"
_WAVE_MAP  = {"square": "SQ", "triangle": "TR", "sawtooth": "SA",
              "sine": "SI", "para": "PA", "parabola": "PA"}


def _parse_voltage(text: str) -> Optional[float]:
    m = re.search(_VOLT_PAT, text)
    return float(m.group(1)) if m else None


def _parse_freq(text: str) -> Optional[float]:
    m = re.search(r"(\d+\.?\d*)\s*(k?hz)", text, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        if "k" in m.group(2).lower():
            val *= 1000
        return val
    m2 = re.search(r"(\d+)", text)
    return float(m2.group(1)) if m2 else None


def _parse_wave(text: str) -> Optional[str]:
    for word, code in _WAVE_MAP.items():
        if word in text.lower():
            return code
    return None


class NLGrammar:
    """Rule-based NLP for lab commands. No external API required."""

    RULES: List[Tuple[re.Pattern, Callable]] = []  # built in __init__

    def __init__(self, stats_fn: Callable, send_fn: Callable,
                 connect_fn: Callable, disconnect_fn: Callable):
        self._stats_fn       = stats_fn
        self._send_fn        = send_fn
        self._connect_fn     = connect_fn
        self._disconnect_fn  = disconnect_fn

        self._rules: List[Tuple[re.Pattern, Callable]] = [
            # Voltage output
            (re.compile(r"(set|output|vreg|voltage).{0,20}(" + _VOLT_PAT + r")", re.I),
             self._cmd_vreg),
            # Wave type + freq
            (re.compile(r"(square|triangle|parabola|sine)\s*wave.{0,30}" + _FREQ_PAT, re.I),
             self._cmd_wave_full),
            # Freq only
            (re.compile(r"(set|change|freq|frequency).{0,15}" + _FREQ_PAT, re.I),
             self._cmd_freq),
            # Wave type only
            (re.compile(r"(square|triangle|parabola|sine)\s*wave", re.I),
             self._cmd_wave_type),
            # Frequency query
            (re.compile(r"(what|dominant|frequency|freq)", re.I),
             self._cmd_query_freq),
            # Voltage query
            (re.compile(r"(what|read|measure).{0,20}(volt|voltage|V\b)", re.I),
             self._cmd_query_volt),
            # Connect
            (re.compile(r"\bconnect\b", re.I),
             self._cmd_connect),
            # Disconnect
            (re.compile(r"\bdisconnect\b", re.I),
             self._cmd_disconnect),
            # Help
            (re.compile(r"\bhelp\b", re.I),
             self._cmd_help),
        ]

    def process(self, text: str) -> Tuple[str, List[str]]:
        """
        Returns (human_response, list_of_commands_sent).
        """
        text = text.strip()
        for pattern, handler in self._rules:
            m = pattern.search(text)
            if m:
                return handler(text, m)
        return ("I didn't understand that. Type 'help' for examples.", [])

    # -- Handlers --------------------------------------------------------------

    def _cmd_vreg(self, text, m):
        v = _parse_voltage(text)
        if v is None:
            return ("Could not parse voltage value.", [])
        v = max(0.0, min(12.0, v))
        cmd = f"#VREG:V={v:.1f};"
        self._send_fn(cmd)
        return (f"Setting output voltage to {v:.1f} V", [cmd])

    def _cmd_wave_full(self, text, m):
        wave_code = _parse_wave(text) or "SQ"
        freq      = _parse_freq(text) or 100
        cmds      = [f"#WAVE:T={wave_code};", f"#WAVE:F={int(freq)};"]
        for c in cmds:
            self._send_fn(c)
        wave_name = {v: k for k, v in _WAVE_MAP.items()}.get(wave_code, wave_code)
        return (f"Setting {wave_name} wave at {int(freq)} Hz", cmds)

    def _cmd_freq(self, text, m):
        freq = _parse_freq(text) or 100
        cmd  = f"#WAVE:F={int(freq)};"
        self._send_fn(cmd)
        return (f"Setting frequency to {int(freq)} Hz", [cmd])

    def _cmd_wave_type(self, text, m):
        wave_code = _parse_wave(text) or "SQ"
        cmd       = f"#WAVE:T={wave_code};"
        self._send_fn(cmd)
        wave_name = {v: k for k, v in _WAVE_MAP.items()}.get(wave_code, wave_code)
        return (f"Setting {wave_name} wave", [cmd])

    def _cmd_query_freq(self, text, m):
        s = self._stats_fn()
        if not s:
            return ("No data available yet.", [])
        f = s.get("dom_freq", 0)
        return (f"Dominant frequency: {f:.2f} Hz  (from {s.get('n',0)} samples)", [])

    def _cmd_query_volt(self, text, m):
        s = self._stats_fn()
        if not s:
            return ("No data available yet.", [])
        mean = s.get("mean", 0)
        vrms = s.get("vrms", 0)
        return (f"Mean: {mean:.3f} V    VRMS: {vrms:.3f} V", [])

    def _cmd_connect(self, text, m):
        self._connect_fn()
        return ("Attempting to connect...", [])

    def _cmd_disconnect(self, text, m):
        self._disconnect_fn()
        return ("Disconnecting...", [])

    def _cmd_help(self, text, m):
        msg = (
            "Examples:\n"
            "  'set output to 3.3V'\n"
            "  'show me a 500Hz square wave'\n"
            "  'what is the dominant frequency?'\n"
            "  'set frequency to 1kHz'\n"
            "  'triangle wave'\n"
            "  'connect'  /  'disconnect'\n"
        )
        return (msg, [])


# -- NL Command Tab -----------------------------------------------------------

class NLCommandTab(QWidget):
    """Natural Language Command Interface - no API key required."""

    send_requested       = pyqtSignal(str)
    connect_requested    = pyqtSignal()
    disconnect_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._history: List[str] = []
        self._hist_idx = -1
        self._stats_fn: Callable = lambda: {}
        self._grammar  = NLGrammar(
            stats_fn      = lambda: self._stats_fn(),
            send_fn       = self.send_requested.emit,
            connect_fn    = self.connect_requested.emit,
            disconnect_fn = self.disconnect_requested.emit,
        )
        self._build_ui()

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("Natural Language Command")
        self._header_strip = hdr
        root.addWidget(hdr)

        content = QWidget()
        c_lay = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(14)
        root.addWidget(content, stretch=1)

        # Conversation log
        log_grp = QGroupBox("CONVERSATION")
        ll = QVBoxLayout(log_grp)
        ll.setContentsMargins(10, 20, 10, 10)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(_ui_font(SZ_BODY))
        ll.addWidget(self._log)
        c_lay.addWidget(log_grp, stretch=1)

        # Suggested commands
        sugg_grp = QGroupBox("QUICK COMMANDS")
        sl = QHBoxLayout(sugg_grp)
        sl.setContentsMargins(10, 20, 10, 10)
        sl.setSpacing(8)
        for label in ["3.3V Output", "5V Output", "Square 100Hz",
                      "Triangle 500Hz", "What is the frequency?", "Help"]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda _, t=label: self._submit(t))
            sl.addWidget(btn)
        sl.addStretch()
        c_lay.addWidget(sugg_grp)

        # Input row
        in_grp = QGroupBox("TYPE A COMMAND")
        il = QHBoxLayout(in_grp)
        il.setContentsMargins(10, 20, 10, 10)
        il.setSpacing(8)
        self._input = QLineEdit()
        self._input.setFont(_ui_font(SZ_BODY))
        self._input.setPlaceholderText(
            "e.g.  set output to 3.3V  |  show me a 500Hz square wave  |  help")
        self._input.returnPressed.connect(lambda: self._submit(self._input.text()))
        self._input.installEventFilter(self)
        il.addWidget(self._input, stretch=1)
        btn_send = QPushButton("SEND [ENTER]")
        btn_send.setFixedWidth(100)
        btn_send.clicked.connect(lambda: self._submit(self._input.text()))
        il.addWidget(btn_send)
        c_lay.addWidget(in_grp)

        self._log_append("Lab AI ready. Type a command below or click a Quick Command.", T.ACCENT_CYAN)

    # -- Theme -----------------------------------------------------------------

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()

    # -- Public API ------------------------------------------------------------

    def set_stats_source(self, fn: Callable):
        self._stats_fn = fn

    # -- History navigation ----------------------------------------------------

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up and self._history:
                self._hist_idx = max(0, self._hist_idx - 1)
                self._input.setText(self._history[self._hist_idx])
                return True
            elif event.key() == Qt.Key_Down:
                self._hist_idx = min(len(self._history), self._hist_idx + 1)
                self._input.setText(
                    self._history[self._hist_idx]
                    if self._hist_idx < len(self._history) else "")
                return True
        return super().eventFilter(obj, event)

    # -- Core ------------------------------------------------------------------

    def _submit(self, text: str):
        text = text.strip()
        if not text:
            return
        self._history.append(text)
        self._hist_idx = len(self._history)
        self._input.clear()
        self._log_append(f"You: {text}", T.ACCENT_BLUE)
        response, cmds = self._grammar.process(text)
        self._log_append(f"Lab: {response}", T.PRIMARY)
        for cmd in cmds:
            self._log_append(f"  -> Sent: {cmd}", T.TEXT_MUTED)

    def _log_append(self, text: str, color: str):
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._log.append(
            f'<span style="color:{color}; font-family:Consolas,monospace;">'
            f'{esc}</span>'
        )
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
