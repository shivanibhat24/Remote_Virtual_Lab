"""
scpi_server.py - LXI/SCPI TCP Command Server for STM32 Lab GUI v6.0

Roadmap item #11: LXI/SCPI Command Server
Exposes a SCPI-over-TCP server on port 5025 so the STM32 lab responds to
standard SCPI commands:
    *IDN?
    MEAS:VOLT:DC?
    CONF:FREQ <freq>
    CONF:VOLT:RANG <range>
    *RST
    SYST:ERR?

Compatible with pyvisa, LabVIEW, MATLAB Instrument Control Toolbox.
Uses only stdlib (socketserver)  no extra dependencies.
"""

import datetime
import socketserver
import threading
import logging
from typing import Callable, Optional

log = logging.getLogger("scpi")


# -- SCPI Dispatcher ----------------------------------------------------------

class SCPIDispatcher:
    """
    Parse incoming SCPI strings and dispatch to lab callbacks.
    All methods return a response string or '' for write-only commands.
    """

    IDN = "STM32 ELECTRONICS LAB,v6.0,SN00001,FW1.0"

    def __init__(self):
        self._send_fn:    Callable[[str], None] = lambda _: None
        self._stats_fn:   Callable[[], dict]    = lambda: {}
        self._snapshot_fn: Callable[[], list]   = lambda: []
        self._error_queue: list = []

    # -- Callback injection ----------------------------------------------------

    def set_send(self, fn: Callable[[str], None]):
        self._send_fn = fn

    def set_stats(self, fn: Callable[[], dict]):
        self._stats_fn = fn

    def set_snapshot(self, fn: Callable[[], list]):
        self._snapshot_fn = fn

    # -- SCPI Parse + Dispatch -------------------------------------------------

    def handle(self, raw: str) -> str:
        """Process one or more SCPI commands separated by ';'. Returns response."""
        responses = []
        for cmd in raw.strip().split(";"):
            cmd = cmd.strip()
            if not cmd:
                continue
            try:
                r = self._dispatch(cmd.upper())
                if r is not None:
                    responses.append(r)
            except Exception as e:
                self._error_queue.append(f"-222,\"Data out of range: {e}\"")
        return "\n".join(responses) if responses else ""

    def _dispatch(self, cmd: str) -> Optional[str]:
        # Identification
        if cmd == "*IDN?":
            return self.IDN
        if cmd == "*RST":
            self._send_fn("#MODE:T=V;")
            return None

        # System errors
        if cmd == "SYST:ERR?":
            if self._error_queue:
                return self._error_queue.pop(0)
            return "+0,\"No error\""

        # Measure voltage DC
        if cmd in ("MEAS:VOLT:DC?", "READ?", "FETC?", "MEAS:VOLT?"):
            s = self._stats_fn()
            v = s.get("mean", 0.0)
            return f"{v:.6E}"

        # Measure current DC
        if cmd in ("MEAS:CURR:DC?",):
            s = self._stats_fn()
            v = s.get("mean", 0.0)
            return f"{v:.6E}"

        # Measure frequency
        if cmd in ("MEAS:FREQ?",):
            s = self._stats_fn()
            f = s.get("dom_freq", 0.0)
            return f"{f:.6E}"

        # Measure Vpp
        if cmd == "MEAS:VOLT:AC?":
            s = self._stats_fn()
            vpp = s.get("vpp", 0.0)
            return f"{vpp:.6E}"

        # Configure frequency
        if cmd.startswith("CONF:FREQ ") or cmd.startswith("FREQ "):
            parts = cmd.split()
            if len(parts) >= 2:
                try:
                    freq = int(float(parts[-1]))
                    self._send_fn(f"#WAVE:F={freq};")
                except ValueError:
                    self._error_queue.append("-224,\"Illegal parameter value\"")
            return None

        # Configure voltage range
        if cmd.startswith("CONF:VOLT:RANG "):
            parts = cmd.split()
            if len(parts) >= 2:
                try:
                    rng = int(float(parts[-1]))
                    self._send_fn(f"#RANGE:V={rng};")
                except ValueError:
                    pass
            return None

        # Configure mode
        if cmd.startswith("CONF:VOLT:DC"):
            self._send_fn("#MODE:T=V;")
            return None
        if cmd.startswith("CONF:CURR:DC"):
            self._send_fn("#MODE:T=A;")
            return None

        # Waveform type
        if cmd.startswith("CONF:WAVE:TYPE "):
            parts = cmd.split()
            if len(parts) >= 2:
                self._send_fn(f"#WAVE:T={parts[-1]};")
            return None

        # Waveform data query (returns comma-separated samples)
        if cmd in ("TRAC:DATA?", "FETC:WAV?"):
            snap = self._snapshot_fn()
            return ",".join(f"{v:.6E}" for v in snap)

        # Data? - alias
        if cmd == "DATA?":
            s = self._stats_fn()
            v = s.get("mean", 0.0)
            return f"{v:.6E}"

        # Unknown command
        self._error_queue.append(f"-113,\"Undefined header: {cmd}\"")
        return None


# -- TCP Request Handler -------------------------------------------------------

_DISPATCHER = SCPIDispatcher()   # module-level singleton


class _SCPIHandler(socketserver.StreamRequestHandler):
    def handle(self):
        addr = f"{self.client_address[0]}:{self.client_address[1]}"
        log.info(f"SCPI client connected: {addr}")
        if hasattr(self.server, "_on_connect"):
            self.server._on_connect(addr)
        try:
            for raw_line in self.rfile:
                line = raw_line.decode("ascii", errors="ignore").strip()
                if not line:
                    continue
                log.debug(f"SCPI << {line}")
                response = _DISPATCHER.handle(line)
                if response:
                    log.debug(f"SCPI >> {response}")
                    self.wfile.write((response + "\n").encode("ascii"))
                    self.wfile.flush()
        except Exception as e:
            log.debug(f"SCPI handler error: {e}")
        finally:
            if hasattr(self.server, "_on_disconnect"):
                self.server._on_disconnect(addr)
            log.info(f"SCPI client disconnected: {addr}")


# -- Server Manager -----------------------------------------------------------

class SCPIServer:
    """Threaded TCP SCPI server on port 5025."""

    DEFAULT_PORT = 5025

    def __init__(self, port: int = DEFAULT_PORT):
        self._port    = port
        self._server: Optional[socketserver.TCPServer] = None
        self._thread: Optional[threading.Thread]       = None
        self._running = False
        self._clients: list = []
        self._log_fn: Callable[[str], None] = print
        self.dispatcher = _DISPATCHER

    def set_log_fn(self, fn: Callable[[str], None]):
        self._log_fn = fn

    def start(self) -> bool:
        if self._running:
            return True
        try:
            self._server = socketserver.ThreadingTCPServer(
                ("0.0.0.0", self._port), _SCPIHandler, bind_and_activate=False)
            self._server.allow_reuse_address = True
            self._server.server_bind()
            self._server.server_activate()
            self._server._on_connect    = self._on_client_connect
            self._server._on_disconnect = self._on_client_disconnect
            self._running = True
            self._thread  = threading.Thread(
                target=self._server.serve_forever, daemon=True)
            self._thread.start()
            self._log_fn(f"SCPI server started on port {self._port}")
            return True
        except Exception as e:
            self._log_fn(f"SCPI server error: {e}")
            return False

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._running = False
        self._log_fn("SCPI server stopped")

    def _on_client_connect(self, addr: str):
        self._clients.append(addr)
        self._log_fn(f"Client connected: {addr}")

    def _on_client_disconnect(self, addr: str):
        if addr in self._clients:
            self._clients.remove(addr)
        self._log_fn(f"Client disconnected: {addr}")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)
