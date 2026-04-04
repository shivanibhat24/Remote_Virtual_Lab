"""
tab_nlcmd.py - Natural Language Command Interface for STM32 Lab GUI v6.0

Parses plain-English commands with a local regex/grammar engine (no API key).
Commands update hardware via serial and are mirrored in the relevant tabs
(Function Gen, Voltage Reg, etc.) by the main window.

Examples:
  "set output to 3.3V"              -> #VREG:V=3.3;
  "square wave at 400kHz"           -> #WAVE:T=SQ; #WAVE:F=400000;
  "set the function generator to a 1 MHz sine wave" -> wave + freq
  "set frequency to 2500 Hz"        -> #WAVE:F=2500;
  "what is the dominant frequency?" -> reads stats (does not change FG)
"""

import re
from typing import Callable, List, Optional, Tuple

from nlp_intent import fuzzy_best_intent

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton,
    QTextEdit, QGroupBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from themes import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header


# -- Grammar engine -----------------------------------------------------------

_VOLT_PAT = r"(\d+\.?\d*)\s*[vV](?:olt(?:s)?)?"

_WAVE_MAP = {
    "square": "SQ",
    "triangle": "TR",
    "sawtooth": "SA",
    "sine": "SI",
    "para": "PA",
    "parabola": "PA",
    "half-wave": "HW",
    "half wave": "HW",
    "full-wave": "FW",
    "full wave": "FW",
    "sinc": "SN",
    "step": "ST",
    "staircase": "SC",
    "gaussian": "GA",
    "noise": "NO",
    "dc": "DC",
    "ground": "G",
}


def _parse_voltage(text: str) -> Optional[float]:
    m = re.search(_VOLT_PAT, text)
    return float(m.group(1)) if m else None


def _parse_freq(text: str) -> Optional[float]:
    """
    Parse frequency from free text: Hz, kHz/K/k, MHz/M, or bare number near 'freq'.
    """
    t = text.strip()

    m = re.search(r"(\d+\.?\d*)\s*(?:mhz|MHz)\b", t)
    if m:
        return float(m.group(1)) * 1e6

    m = re.search(r"(\d+\.?\d*)\s*k\s*hz\b", t, re.I)
    if m:
        return float(m.group(1)) * 1e3

    m = re.search(r"(\d+\.?\d*)\s*khz\b", t, re.I)
    if m:
        return float(m.group(1)) * 1e3

    m = re.search(r"(\d+\.?\d*)\s*k\b(?![a-zA-Z])", t, re.I)
    if m:
        return float(m.group(1)) * 1e3

    m = re.search(r"(\d+\.?\d*)\s*hz\b", t, re.I)
    if m:
        return float(m.group(1))

    m = re.search(r"(?:freq|frequency)\s*(?:to|=|:)?\s*(\d+\.?\d*)", t, re.I)
    if m:
        return float(m.group(1))

    m = re.search(r"(\d+\.?\d*)\s*(k?)\s*hz", t, re.I)
    if m:
        val = float(m.group(1))
        if m.group(2).lower() == "k":
            val *= 1e3
        return val

    return None


def _parse_wave(text: str) -> Optional[str]:
    tl = text.lower()
    # Longer phrases first
    keys = sorted(_WAVE_MAP.keys(), key=len, reverse=True)
    for word in keys:
        if word in tl:
            return _WAVE_MAP[word]
    return None


def _is_freq_query(text: str) -> bool:
    """True if user is asking for a measurement, not setting FG frequency."""
    tl = text.lower().strip()
    if re.search(r"\bdominant\s+frequenc|\bdominant\s+freq\b", tl):
        return True
    if re.search(r"\bfundamental\s+frequenc", tl):
        return True
    if re.match(
        r"^(what|which)\s+is\s+the\s+(dominant\s+)?frequenc", tl,
    ):
        return True
    if re.match(r"^(what|which)\s+is\s+the\s+frequency\?", tl) and "wave" not in tl:
        return True
    return False


def _is_volt_query(text: str) -> bool:
    tl = text.lower().strip()
    if re.match(r"^(what|read|measure)\b", tl):
        if re.search(r"\b(volt|voltage|vrms|rms)\b", tl):
            return True
    return False


def _wants_wave_with_freq(text: str) -> bool:
    """Both waveform shape and numeric frequency are present; user intent is to set FG."""
    if _is_freq_query(text):
        return False
    f = _parse_freq(text)
    w = _parse_wave(text)
    if f is None or w is None:
        return False
    tl = text.lower()
    # Reject if looks like pure question with numbers
    if tl.startswith("what ") and "set" not in tl and "make" not in tl and "show" not in tl:
        return False
    return True


class NLGrammar:
    """Rule-based NLP for lab commands. No external API required."""

    def __init__(
        self,
        stats_fn: Callable,
        send_fn: Callable,
        connect_fn: Callable,
        disconnect_fn: Callable,
    ):
        self._stats_fn = stats_fn
        self._send_fn = send_fn
        self._connect_fn = connect_fn
        self._disconnect_fn = disconnect_fn

        freq_fragment = (
            r"(\d+\.?\d*)\s*(?:mhz|MHz|khz|k\s*hz|KHz|Hz|hz|\bk\b)"
        )
        self._rules: List[Tuple[re.Pattern, Callable]] = [
            (re.compile(r"(set|output|vreg|voltage).{0,35}(" + _VOLT_PAT + r")", re.I), self._cmd_vreg),
            (
                re.compile(
                    r"(square|triangle|sawtooth|sine|parabola|para|half[- ]?wave|full[- ]?wave)\s*wave.{0,50}?"
                    + freq_fragment,
                    re.I,
                ),
                self._cmd_wave_full_regex,
            ),
            (
                re.compile(
                    freq_fragment + r".{0,35}(square|triangle|sawtooth|sine|parabola|para)\s*wave?",
                    re.I,
                ),
                self._cmd_wave_full_regex_rev,
            ),
            (
                re.compile(
                    r"(set|change|make|show|give|use|apply|put).{0,50}(square|triangle|sawtooth|sine|parabola).{0,50}?"
                    + freq_fragment,
                    re.I,
                ),
                self._cmd_wave_full_phrase,
            ),
            (
                re.compile(r"(set|change|adjust).{0,20}(freq|frequency).{0,20}" + freq_fragment, re.I),
                self._cmd_freq_regex,
            ),
            (
                re.compile(r"(square|triangle|sawtooth|sine|parabola|para)\s*wave", re.I),
                self._cmd_wave_type,
            ),
            (re.compile(r"\bconnect\b", re.I), self._cmd_connect),
            (re.compile(r"\bdisconnect\b", re.I), self._cmd_disconnect),
            (re.compile(r"\bhelp\b", re.I), self._cmd_help),
        ]

    def process(self, text: str) -> Tuple[str, List[str]]:
        text = text.strip()
        if not text:
            return ("", [])

        if _is_volt_query(text):
            return self._cmd_query_volt(text, None)

        if _is_freq_query(text):
            return self._cmd_query_freq(text, None)

        if _wants_wave_with_freq(text):
            return self._emit_wave(_parse_wave(text) or "SQ", _parse_freq(text) or 100.0)

        fz = fuzzy_best_intent(text)
        if fz:
            got = self._try_fuzzy_dispatch(fz, text)
            if got is not None:
                return got

        for pattern, handler in self._rules:
            m = pattern.search(text)
            if m:
                return handler(text, m)

        return ("I didn't understand that. Type 'help' for examples.", [])

    def _try_fuzzy_dispatch(
        self, intent: str, text: str
    ) -> Optional[Tuple[str, List[str]]]:
        """Map fuzzy intent to command if slots parse from user text; else None."""
        if intent == "help":
            return self._cmd_help(text, None)
        if intent == "connect":
            return self._cmd_connect(text, None)
        if intent == "disconnect":
            return self._cmd_disconnect(text, None)
        if intent == "vreg":
            if _parse_voltage(text) is None:
                return None
            return self._cmd_vreg(text, None)
        if intent == "wave_freq":
            wf = _parse_wave(text)
            ff = _parse_freq(text)
            if wf is None or ff is None:
                return None
            return self._emit_wave(wf, ff)
        if intent == "freq_only":
            if _parse_freq(text) is None:
                return None
            return self._cmd_freq_regex(text, None)
        if intent == "wave_type":
            if _parse_wave(text) is None:
                return None
            return self._cmd_wave_type(text, None)
        return None

    def _emit_wave(self, wave_code: str, freq_hz: float) -> Tuple[str, List[str]]:
        freq_i = int(round(max(0.0, freq_hz)))
        cmds = [f"#WAVE:T={wave_code};", f"#WAVE:F={freq_i};"]
        for c in cmds:
            self._send_fn(c)
        inv = {v: k for k, v in _WAVE_MAP.items()}
        wave_name = inv.get(wave_code, wave_code)
        pretty = f"{freq_i:,} Hz" if freq_i < 1_000_000 else f"{freq_i / 1e6:.3g} MHz"
        return (f"Setting {wave_name} wave at {pretty}", cmds)

    def _cmd_vreg(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        v = _parse_voltage(text)
        if v is None:
            return ("Could not parse voltage value.", [])
        v = max(0.0, min(12.0, v))
        cmd = f"#VREG:V={v:.1f};"
        self._send_fn(cmd)
        return (f"Setting output voltage to {v:.1f} V", [cmd])

    def _cmd_wave_full_regex(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        wave_code = _parse_wave(text) or "SQ"
        freq = _parse_freq(text)
        if freq is None:
            return ("Could not parse frequency.", [])
        return self._emit_wave(wave_code, freq)

    def _cmd_wave_full_regex_rev(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        return self._cmd_wave_full_regex(text, m)

    def _cmd_wave_full_phrase(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        return self._cmd_wave_full_regex(text, m)

    def _cmd_freq_regex(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        freq = _parse_freq(text)
        if freq is None:
            return ("Could not parse frequency.", [])
        freq_i = int(round(freq))
        cmd = f"#WAVE:F={freq_i};"
        self._send_fn(cmd)
        return (f"Setting frequency to {freq_i:,} Hz", [cmd])

    def _cmd_wave_type(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        if re.match(r"^\s*(what|which|how|why)\b", text, re.I):
            return (
                "For scope readings ask: 'what is the dominant frequency?'. "
                "To set the generator shape: e.g. 'sine wave' or 'square wave at 400 kHz'.",
                [],
            )
        wave_code = _parse_wave(text) or "SQ"
        cmd = f"#WAVE:T={wave_code};"
        self._send_fn(cmd)
        inv = {v: k for k, v in _WAVE_MAP.items()}
        wave_name = inv.get(wave_code, wave_code)
        return (f"Setting {wave_name} wave (frequency unchanged)", [cmd])

    def _cmd_query_freq(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        s = self._stats_fn()
        if not s:
            return ("No data available yet.", [])
        f = s.get("dom_freq", 0)
        return (f"Dominant frequency: {f:.2f} Hz  (from {s.get('n', 0)} samples)", [])

    def _cmd_query_volt(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        s = self._stats_fn()
        if not s:
            return ("No data available yet.", [])
        mean = s.get("mean", 0)
        vrms = s.get("vrms", 0)
        return (f"Mean: {mean:.3f} V    VRMS: {vrms:.3f} V", [])

    def _cmd_connect(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        self._connect_fn()
        return ("Attempting to connect...", [])

    def _cmd_disconnect(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        self._disconnect_fn()
        return ("Disconnecting...", [])

    def _cmd_help(self, text: str, m: Optional[re.Match]) -> Tuple[str, List[str]]:
        msg = (
            "Examples:\n"
            "  'set output to 3.3V'\n"
            "  'square wave at 400 kHz'  /  '400kHz square wave'\n"
            "  Paraphrases work too: 'hook up the board', 'give me a sine 50 hz'\n"
            "  'set frequency to 2500 Hz'\n"
            "  'triangle wave'\n"
            "  'what is the dominant frequency?'\n"
            "  'connect'  /  'disconnect'\n"
        )
        return (msg, [])


# -- NL Command tab ------------------------------------------------------------

class NLCommandTab(QWidget):
    """Natural Language Command Interface - no API key required."""

    send_requested = pyqtSignal(str)
    connect_requested = pyqtSignal()
    disconnect_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._history: List[str] = []
        self._hist_idx = -1
        self._stats_fn: Callable = lambda: {}
        self._grammar = NLGrammar(
            stats_fn=lambda: self._stats_fn(),
            send_fn=self.send_requested.emit,
            connect_fn=self.connect_requested.emit,
            disconnect_fn=self.disconnect_requested.emit,
        )
        self._build_ui()

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

        log_grp = QGroupBox("CONVERSATION")
        ll = QVBoxLayout(log_grp)
        ll.setContentsMargins(10, 20, 10, 10)
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(_ui_font(SZ_BODY))
        ll.addWidget(self._log)
        c_lay.addWidget(log_grp, stretch=1)

        sugg_grp = QGroupBox("QUICK COMMANDS")
        sl = QHBoxLayout(sugg_grp)
        sl.setContentsMargins(10, 20, 10, 10)
        sl.setSpacing(8)
        for label in [
            "3.3V Output",
            "5V Output",
            "Square 100Hz",
            "400kHz square wave",
            "What is the dominant frequency?",
            "Help",
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda _, t=label: self._submit(t))
            sl.addWidget(btn)
        sl.addStretch()
        c_lay.addWidget(sugg_grp)

        in_grp = QGroupBox("TYPE A COMMAND")
        il = QHBoxLayout(in_grp)
        il.setContentsMargins(10, 20, 10, 10)
        il.setSpacing(8)
        self._input = QLineEdit()
        self._input.setFont(_ui_font(SZ_BODY))
        self._input.setPlaceholderText(
            "e.g. set output to 3.3V  |  square wave at 400 kHz  |  what is the dominant frequency?"
        )
        self._input.returnPressed.connect(lambda: self._submit(self._input.text()))
        self._input.installEventFilter(self)
        il.addWidget(self._input, stretch=1)
        btn_send = QPushButton("SEND [ENTER]")
        btn_send.setFixedWidth(100)
        btn_send.clicked.connect(lambda: self._submit(self._input.text()))
        il.addWidget(btn_send)
        c_lay.addWidget(in_grp)

        try:
            import rapidfuzz  # noqa: F401
            _nlp_note = "Fuzzy NL (rapidfuzz) enabled for paraphrases."
        except ImportError:
            _nlp_note = "Install rapidfuzz for better paraphrase matching: pip install rapidfuzz"
        self._log_append("Lab AI ready. Type a command below or click a Quick Command.", T.ACCENT_CYAN)
        self._log_append(_nlp_note, T.TEXT_MUTED)

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()

    def set_stats_source(self, fn: Callable):
        self._stats_fn = fn

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent

        if obj is self._input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Up and self._history:
                self._hist_idx = max(0, self._hist_idx - 1)
                self._input.setText(self._history[self._hist_idx])
                return True
            if event.key() == Qt.Key_Down:
                self._hist_idx = min(len(self._history), self._hist_idx + 1)
                self._input.setText(
                    self._history[self._hist_idx] if self._hist_idx < len(self._history) else ""
                )
                return True
        return super().eventFilter(obj, event)

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
            f'<span style="color:{color}; font-family:Consolas,monospace;">' f"{esc}</span>"
        )
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
