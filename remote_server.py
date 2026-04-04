"""
remote_server.py - WebSocket remote server for STM32 Lab GUI v6.0
"""

import asyncio
import threading
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


class RemoteServer(QObject):
    status_changed = pyqtSignal(str)
    client_event   = pyqtSignal(str)

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        super().__init__()
        self._host    = host
        self._ws_port = port
        self._clients: set = set()
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._stop_event = None

    def start(self):
        if not HAS_WEBSOCKETS:
            self.status_changed.emit("websockets not installed")
            return
        self._running = True
        self._thread  = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._loop and self._loop.is_running() and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def broadcast(self, msg: str):
        if self._loop and self._clients:
            asyncio.run_coroutine_threadsafe(self._async_broadcast(msg), self._loop)

    async def _async_broadcast(self, msg: str):
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send(msg)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    async def _handler(self, ws, *args):
        self._clients.add(ws)
        try:
            addr     = ws.remote_address
            addr_str = f"{addr[0]}:{addr[1]}" if isinstance(addr, tuple) else str(addr)
        except Exception:
            addr_str = "unknown"
        self.client_event.emit(f"Client connected: {addr_str}")
        try:
            async for _ in ws:
                pass
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            self.client_event.emit(f"Client disconnected: {addr_str}")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def serve():
            self._stop_event = asyncio.Event()
            async with websockets.serve(self._handler, self._host, self._ws_port):
                self.status_changed.emit(
                    f"Server ON  ws://{self._host}:{self._ws_port}")
                await self._stop_event.wait()

        try:
            self._loop.run_until_complete(serve())
        except Exception as e:
            self.status_changed.emit(f"Server error: {e}")
