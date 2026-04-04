"""
Lightweight intent matching for NL commands (no cloud LLM).

Uses rapidfuzz when installed (better paraphrase tolerance); otherwise difflib.
Slot values (frequency, voltage, wave type) are always parsed from the user's
actual text, not from the matched exemplar.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

try:
    from rapidfuzz import fuzz

    def _score(a: str, b: str) -> float:
        return float(fuzz.token_set_ratio(a, b))

except ImportError:

    def _score(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100.0


def _normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^\w\s\.]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s


# (intent_id, exemplar_phrase)
_INTENT_EXEMPLARS: List[Tuple[str, str]] = []

for phrase in [
    "set output to five volts",
    "output three point three volts",
    "regulator at twelve v",
    "change voltage to nine",
    "vreg five volts",
    "set the supply to 3v",
]:
    _INTENT_EXEMPLARS.append(("vreg", phrase))

for phrase in [
    "square wave at four hundred kilohertz",
    "sine wave one megahertz",
    "triangle at five hundred hz",
    "give me a square wave 1000 hz",
    "make a sine 50 hz",
    "set function generator to triangle 2 khz",
    "fg sine 1 mhz",
    "oscillator square 400k",
    "waveform sawtooth 200 hz",
]:
    _INTENT_EXEMPLARS.append(("wave_freq", phrase))

for phrase in [
    "set frequency to 2500",
    "change freq to 1 khz",
    "adjust frequency 60 hz",
    "tune to 440 hz",
    "set the tone to 1000 hertz",
]:
    _INTENT_EXEMPLARS.append(("freq_only", phrase))

for phrase in [
    "square wave only",
    "switch to sine wave",
    "triangle waveform please",
    "use sawtooth",
    "parabola wave",
]:
    _INTENT_EXEMPLARS.append(("wave_type", phrase))

for phrase in [
    "connect to device",
    "open serial port",
    "hook up the board",
    "plug in and connect",
    "start connection",
    "link serial",
]:
    _INTENT_EXEMPLARS.append(("connect", phrase))

for phrase in [
    "disconnect serial",
    "close the port",
    "unplug connection",
    "stop connection",
]:
    _INTENT_EXEMPLARS.append(("disconnect", phrase))

for phrase in [
    "help me",
    "what can you do",
    "show commands",
    "list examples",
]:
    _INTENT_EXEMPLARS.append(("help", phrase))


# Minimum score (0–100) to trust fuzzy intent
FUZZY_THRESHOLD = 72.0


def fuzzy_best_intent(user_text: str) -> Optional[str]:
    """
    Return intent id best matching user_text, or None if below threshold.
    """
    if len(user_text.strip()) < 2:
        return None
    u = _normalize(user_text)
    best_intent: Optional[str] = None
    best_score = 0.0
    for intent, exemplar in _INTENT_EXEMPLARS:
        e = _normalize(exemplar)
        s = _score(u, e)
        if s > best_score:
            best_score = s
            best_intent = intent
    if best_intent is not None and best_score >= FUZZY_THRESHOLD:
        return best_intent
    return None
