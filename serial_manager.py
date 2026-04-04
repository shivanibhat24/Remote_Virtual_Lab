"""
serial_manager.py - UART serial port management for STM32 Lab GUI v6.0
"""

import threading
from typing import Optional, List

import serial
import serial.tools.list_ports

from PyQt5.QtCore import QObject, pyqtSignal


class SerialSignals(QObject):
    message_received = pyqtSignal(str)
    connection_error = pyqtSignal(str)


class SerialManager:
    BAUD_RATE = 115200

    def __init__(self):
        self.signals  = SerialSignals()
        self._port:   Optional[serial.Serial]  = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._buffer  = ""

    def connect(self, port_name: str) -> bool:
        try:
            self._port    = serial.Serial(port_name, self.BAUD_RATE, timeout=0.1)
            self._running = True
            self._thread  = threading.Thread(target=self._reader_loop, daemon=True)
            self._thread.start()
            return True
        except serial.SerialException as e:
            self.signals.connection_error.emit(str(e))
            return False

    def disconnect(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._port and self._port.is_open:
            self._port.close()
        self._port = None

    @property
    def is_connected(self) -> bool:
        return self._port is not None and self._port.is_open

    def send(self, cmd: str):
        if not self.is_connected:
            return
        try:
            self._port.write(cmd.encode("ascii"))
        except serial.SerialException as e:
            self.signals.connection_error.emit(str(e))

    def _reader_loop(self):
        while self._running and self._port and self._port.is_open:
            try:
                raw = self._port.read(64).decode("ascii", errors="ignore")
                if raw:
                    self._buffer += raw
                    while ";" in self._buffer:
                        msg, self._buffer = self._buffer.split(";", 1)
                        msg = msg.strip()
                        if msg:
                            self.signals.message_received.emit(msg + ";")
            except serial.SerialException as e:
                self.signals.connection_error.emit(str(e))
                break

    @staticmethod
    def list_ports() -> List[str]:
        return [p.device for p in serial.tools.list_ports.comports()]
