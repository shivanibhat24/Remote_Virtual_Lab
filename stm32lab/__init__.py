"""
stm32lab/__init__.py - Headless API for STM32 Remote Electronics Lab v6.0

Allows the lab to be driven from a Jupyter notebook or Python script
without the GUI, returning pandas DataFrames where appropriate.

Usage
-----
from stm32lab import STM32Lab

lab = STM32Lab("COM3")          # or "/dev/ttyUSB0"
lab.set_mode("V")               # Voltmeter
lab.set_frequency(500)          # 500 Hz square wave
v   = lab.read_voltage()        # blocking read
df  = lab.sweep_bode(10, 10000) # returns pandas DataFrame
snap = lab.snapshot()           # raw DSO buffer as list
lab.close()

All methods are synchronous and blocking (suitable for notebooks).
Requires: pyserial, numpy. Optional: pandas.
"""

import time
import threading
import re
from typing import List, Optional, Tuple
from pathlib import Path

import serial
import serial.tools.list_ports
import numpy as np

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


# -- Low-level serial comms ---------------------------------------------------

class _SerialPort:
    BAUD = 115200

    def __init__(self, port: str, timeout: float = 2.0):
        self._port = serial.Serial(port, self.BAUD, timeout=timeout)
        self._buf  = ""
        self._lock = threading.Lock()

    def send(self, cmd: str):
        with self._lock:
            self._port.write(cmd.encode("ascii"))

    def read_until_semicolon(self, timeout: float = 2.0) -> Optional[str]:
        """Block until a ';'-terminated message is received."""
        t_end = time.time() + timeout
        while time.time() < t_end:
            if ";" in self._buf:
                msg, self._buf = self._buf.split(";", 1)
                return msg.strip() + ";"
            if self._port.in_waiting:
                chunk = self._port.read(self._port.in_waiting).decode("ascii", errors="ignore")
                self._buf += chunk
            else:
                time.sleep(0.005)
        return None

    def close(self):
        if self._port.is_open:
            self._port.close()


# -- Message parser (mirrors data_engine.DataParser) ---------------------------

def _parse(raw: str) -> Optional[dict]:
    """Parse a ';'-terminated message into {kind, fields}."""
    raw = raw.rstrip(";").strip()
    m   = re.match(r"#(\w+):(.+)", raw)
    if not m:
        return None
    kind   = m.group(1).upper()
    fields = {}
    for part in m.group(2).split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip()] = v.strip()
    return {"kind": kind, "fields": fields}


# -- STM32Lab - Public API -----------------------------------------------------

class STM32Lab:
    """
    Headless control API for the STM32 Remote Electronics Lab.

    Parameters
    ----------
    port : str
        Serial port (e.g. 'COM3' on Windows, '/dev/ttyUSB0' on Linux/Mac).
    timeout : float
        Read timeout for blocking calls (seconds).
    """

    MODE_MAP  = {"V": "Voltmeter", "A": "Ammeter", "D": "DSO", "G": "Ground"}
    RANGE_MAP = {12: "#RANGE:V=12;", 16: "#RANGE:V=16;", 24: "#RANGE:V=24;"}

    def __init__(self, port: str, timeout: float = 2.0):
        self._sp      = _SerialPort(port, timeout)
        self._timeout = timeout
        self._buf: List[float] = []
        self._buf_size = 500
        self._running  = True
        self._mode     = "V"

        # Background reader thread fills self._buf
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        # Let the firmware settle
        time.sleep(0.3)

    # -- Background reader -----------------------------------------------------

    def _read_loop(self):
        while self._running:
            msg = self._sp.read_until_semicolon(timeout=0.5)
            if msg is None:
                continue
            parsed = _parse(msg)
            if parsed and parsed["kind"] == "DATA":
                try:
                    val = float(parsed["fields"].get("X", "0"))
                    self._buf.append(val)
                    if len(self._buf) > self._buf_size:
                        self._buf = self._buf[-self._buf_size:]
                except ValueError:
                    pass

    # -- Configuration ---------------------------------------------------------

    def set_mode(self, mode: str):
        """Set instrument mode: 'V'=Voltmeter, 'A'=Ammeter, 'D'=DSO, 'G'=Ground."""
        self._mode = mode.upper()[:1]
        self._sp.send(f"#MODE:T={self._mode};")
        time.sleep(0.05)

    def set_range(self, voltage: int = 12):
        """Set voltage range: 12, 16, or 24 V."""
        cmd = self.RANGE_MAP.get(voltage, "#RANGE:V=12;")
        self._sp.send(cmd)
        time.sleep(0.05)

    def set_frequency(self, freq_hz: int):
        """Set function generator output frequency in Hz."""
        self._sp.send(f"#WAVE:F={int(freq_hz)};")
        time.sleep(0.05)

    def set_wave_type(self, wave: str):
        """Set waveform type: 'SQ'=square, 'TR'=triangle, 'SA'=sawtooth, 'SI'=sine."""
        self._sp.send(f"#WAVE:T={wave.upper()};")
        time.sleep(0.05)

    def set_voltage(self, volts: float):
        """Set regulated voltage output."""
        self._sp.send(f"#VREG:V={volts:.2f};")
        time.sleep(0.05)

    def send_raw(self, cmd: str):
        """Send a raw command string."""
        if not cmd.endswith(";"):
            cmd += ";"
        self._sp.send(cmd)

    # -- Measurements ----------------------------------------------------------

    def snapshot(self) -> List[float]:
        """Return a copy of the current DSO buffer (up to 500 samples)."""
        return list(self._buf)

    def wait_samples(self, n: int = 100, timeout: float = 5.0) -> List[float]:
        """Block until at least n samples are in the buffer, then return them."""
        t_end = time.time() + timeout
        while len(self._buf) < n and time.time() < t_end:
            time.sleep(0.05)
        return list(self._buf[-n:])

    def read_voltage(self, n_avg: int = 20) -> float:
        """Read mean voltage from n_avg samples (blocking)."""
        samples = self.wait_samples(n_avg)
        return float(np.mean(samples)) if samples else 0.0

    def read_stats(self) -> dict:
        """Return statistics dict: mean, std, min, max, vrms, vpp, dom_freq, n."""
        arr = np.array(self._buf, dtype=float)
        n   = len(arr)
        if n == 0:
            return {}
        mean = float(np.mean(arr))
        std  = float(np.std(arr))
        mag  = np.abs(np.fft.rfft(arr - mean))
        frqs = np.fft.rfftfreq(n, d=0.010)
        dom_freq = float(frqs[int(np.argmax(mag[1:])) + 1]) if len(mag) > 1 else 0.0
        return {
            "mean":     mean,
            "std":      std,
            "min":      float(np.min(arr)),
            "max":      float(np.max(arr)),
            "vrms":     float(np.sqrt(np.mean(arr**2))),
            "vpp":      float(np.max(arr) - np.min(arr)),
            "dom_freq": dom_freq,
            "n":        n,
        }

    # -- Sweep utilities -------------------------------------------------------

    def sweep_freq(self, f_start: int, f_stop: int,
                   steps: int = 20, settle_s: float = 0.3,
                   samples_per_step: int = 50):
        """
        Sweep frequency from f_start to f_stop Hz.

        Returns pandas DataFrame (if pandas available) or list of dicts:
            [{"freq_hz": ..., "mean_v": ..., "vpp": ..., "dom_freq": ...}]
        """
        freqs   = np.linspace(f_start, f_stop, steps, dtype=int)
        results = []
        for f in freqs:
            self.set_frequency(int(f))
            time.sleep(settle_s)
            self._buf.clear()
            time.sleep(settle_s)
            samps = self.wait_samples(samples_per_step, timeout=settle_s * 4)
            s     = self.read_stats()
            results.append({
                "freq_hz":  int(f),
                "mean_v":   s.get("mean", 0.0),
                "vpp":      s.get("vpp",  0.0),
                "dom_freq": s.get("dom_freq", 0.0),
                "n":        s.get("n", 0),
            })
            print(f"  {int(f):8d} Hz  ->  Vpp={s.get('vpp',0):.3f}V  "
                  f"dom={s.get('dom_freq',0):.1f}Hz")

        if HAS_PANDAS:
            return pd.DataFrame(results)
        return results

    def sweep_bode(self, f_start: int = 10, f_stop: int = 100_000,
                   steps: int = 30, settle_s: float = 0.25):
        """
        Bode-sweep: record gain (dB) vs frequency.
        Uses a fixed V_ref = first reading as 0 dB reference.

        Returns DataFrame with columns: freq_hz, vpp, gain_db
        """
        # Reference at f_start
        self.set_frequency(f_start)
        time.sleep(settle_s * 2)
        self._buf.clear()
        time.sleep(settle_s)
        ref_samps = self.wait_samples(50)
        v_ref     = float(np.max(ref_samps) - np.min(ref_samps)) if ref_samps else 1.0
        v_ref     = max(v_ref, 1e-6)

        freqs   = np.geomspace(f_start, f_stop, steps, dtype=float)
        results = []
        for f in freqs:
            self.set_frequency(int(f))
            time.sleep(settle_s)
            self._buf.clear()
            time.sleep(settle_s)
            samps = self.wait_samples(50)
            arr   = np.array(samps, dtype=float)
            vpp   = float(np.max(arr) - np.min(arr)) if len(arr) else 0.0
            gain  = 20 * np.log10(max(vpp, 1e-9) / v_ref)
            results.append({"freq_hz": float(f), "vpp": vpp, "gain_db": float(gain)})
            print(f"  {int(f):8d} Hz  Vpp={vpp:.3f}V  Gain={gain:+.1f} dB")

        if HAS_PANDAS:
            return pd.DataFrame(results)
        return results

    # -- Utilities -------------------------------------------------------------

    def reset(self):
        """Send *RST equivalent to reset instrument to defaults."""
        self._sp.send("#MODE:T=V;")
        self._sp.send("#WAVE:F=100;")
        self._sp.send("#WAVE:T=SQ;")
        time.sleep(0.1)

    def close(self):
        """Close the serial connection."""
        self._running = False
        self._sp.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def __repr__(self):
        return (f"STM32Lab(port={self._sp._port.port!r}, "
                f"connected={self._sp._port.is_open}, "
                f"buf={len(self._buf)} samples)")

    # -- Class methods ---------------------------------------------------------

    @classmethod
    def list_ports(cls) -> List[str]:
        """List available serial ports."""
        return [p.device for p in serial.tools.list_ports.comports()]
