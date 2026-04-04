"""
data_engine.py - CommandBuilder, DataParser, DataLogger, AnalyticsEngine
                 for STM32 Lab GUI v6.0
"""

import csv
import datetime
import os
from collections import deque
from typing import Optional, List, Dict

import numpy as np


# -- 1. Command Builder --------------------------------------------------------

class CommandBuilder:

    @staticmethod
    def range_cmd(v: int) -> str:
        return f"#RANGE:V={v};"

    @staticmethod
    def mode_cmd(m: str) -> str:
        return f"#MODE:T={m};"

    @staticmethod
    def vreg_cmd(v: float) -> str:
        return f"#VREG:V={round(max(0.0, min(12.0, v)), 1)};"

    @staticmethod
    def wave_type(wt: str) -> str:
        return f"#WAVE:T={wt};"

    @staticmethod
    def wave_freq(f: int) -> str:
        """Clamp to firmware-safe range (adjust if your STM32 build differs)."""
        return f"#WAVE:F={max(0, min(1_000_000, int(f)))};"

    @staticmethod
    def pid_cmd(kp: float, ki: float, kd: float, sp: float) -> str:
        """Send PID gains and setpoint to firmware."""
        return (f"#PID:P={kp:.4f},I={ki:.4f},"
                f"D={kd:.4f},SP={sp:.2f};")

    @staticmethod
    def pid_cfg_cmd(min_v: float, max_v: float, alpha: float) -> str:
        """Send PID safety limits and filter coefficient."""
        return f"#PID_CFG:MIN={min_v:.2f},MAX={max_v:.2f},A={alpha:.3f};"

    @staticmethod
    def boost_setpoint_cmd(sp: float) -> str:
        """Set boost converter setpoint (simple firmware command)."""
        sp = max(0.0, min(12.0, sp))
        return f"#BOOST:SP={sp:.2f};"


# -- 2. Parsed Message ---------------------------------------------------------

class ParsedMessage:
    def __init__(self, kind: str, fields: dict):
        self.kind   = kind
        self.fields = fields


# -- 3. Data Parser ------------------------------------------------------------

class DataParser:
    @staticmethod
    def parse(raw: str) -> Optional[ParsedMessage]:
        """Robustly parse #KIND:K1=V1,K2=V2; format from potentially noisy serial data."""
        raw = raw.strip()
        idx = raw.find("#")
        if idx < 0:
            return None
        
        # Strip everything before the first '#' and trailing ';'
        raw = raw[idx+1:].rstrip(";")
        if ":" not in raw:
            return None
            
        kind, rest = raw.split(":", 1)
        fields: Dict[str, str] = {}
        
        # Handle empty payload like #ACK:;
        if not rest.strip():
            return ParsedMessage(kind.strip(), fields)
            
        for pair in rest.split(","):
            if "=" in pair:
                try:
                    parts = pair.split("=", 1)
                    if len(parts) == 2:
                        k, v = parts
                        fields[k.strip()] = v.strip()
                except ValueError:
                    continue
                    
        return ParsedMessage(kind.strip(), fields)


# -- 4. Dynamic Data Logger ---------------------------------------------------

class DataLogger:
    def __init__(self, fieldnames: List[str]):
        self._file       = None
        self._writer     = None
        self._path       = ""
        self._count      = 0
        self._active     = False
        self._fieldnames = fieldnames

    def start(self, path: str):
        self._path   = path
        # Ensure directory exists before opening
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._file   = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self._fieldnames,
                                      extrasaction="ignore")
        self._writer.writeheader()
        self._active = True
        self._count  = 0

    def stop(self):
        self._active = False
        if self._file:
            self._file.flush()
            self._file.close()
            self._file = self._writer = None

    def log_dict(self, data_dict: dict):
        if not self._active or not self._writer:
            return
        
        # Auto-inject timestamp if not explicitly provided
        if "timestamp" not in data_dict and "timestamp" in self._fieldnames:
            data_dict["timestamp"] = datetime.datetime.now().isoformat(timespec="milliseconds")
            
        self._writer.writerow(data_dict)
        self._count += 1
        if self._count % 50 == 0:
            try:
                self._file.flush()
            except Exception:
                pass

    @property
    def is_active(self) -> bool: return self._active
    @property
    def count(self)     -> int:  return self._count
    @property
    def path(self)      -> str:  return self._path


# -- 5. Analytics Engine -------------------------------------------------------

class AnalyticsEngine:
    def __init__(self, window: int = 500, sample_period: float = 0.010):
        self._samples: deque = deque(maxlen=window)
        self.sample_period   = sample_period
        self.cal_coeffs: Optional[List[float]] = None

    def push(self, v: float):
        self._samples.append(v)

    def reset(self):
        self._samples.clear()

    def snapshot(self) -> list:
        return list(self._samples)

    def stats(self) -> dict:
        if not self._samples:
            return {}
        arr     = np.array(self._samples, dtype=float)
        n       = len(arr)
        mean    = float(np.mean(arr))
        std     = float(np.std(arr))
        mn      = float(np.min(arr))
        mx      = float(np.max(arr))
        vrms    = float(np.sqrt(np.mean(arr ** 2)))
        vpp     = mx - mn
        dom_freq = 0.0
        if n >= 4:
            mag  = np.abs(np.fft.rfft(arr - mean))
            frqs = np.fft.rfftfreq(n, d=self.sample_period)
            idx  = int(np.argmax(mag[1:])) + 1
            if idx < len(frqs):
                dom_freq = float(frqs[idx])
        return {
            "mean": mean, "std": std, "min": mn, "max": mx,
            "vrms": vrms, "vpp": vpp, "dom_freq": dom_freq, "n": n,
        }
