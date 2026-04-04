"""
tab_remote.py  WebSocket Remote Viewer tab for STM32 Lab GUI v4.0
"""

import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QTextEdit, QGroupBox
)
from PyQt5.QtCore import pyqtSignal, Qt

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header
from remote_server import RemoteServer, HAS_WEBSOCKETS


class RemoteTab(QWidget):
    def __init__(self, server: RemoteServer):
        super().__init__()
        self._server = server
        self._header_strip: Optional[_HeaderStrip] = None
        self._build_ui()
        self._server.status_changed.connect(self._on_status)
        self._server.client_event.connect(self._on_client_event)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, _ = make_header("Remote Viewer")
        self._header_strip = hdr
        root.addWidget(hdr)

        content = QWidget()
        c_lay   = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(16)
        root.addWidget(content, stretch=1)

        if not HAS_WEBSOCKETS:
            w = QLabel("websockets library not found.\nRun:  pip install websockets")
            w.setAlignment(Qt.AlignCenter)
            w.setStyleSheet(f"color: {T.ACCENT_RED}; font-size: {SZ_LG}px;")
            c_lay.addStretch()
            c_lay.addWidget(w)
            c_lay.addStretch()
            return

        #  Server controls 
        srv_grp = QGroupBox("WEBSOCKET SERVER")
        sl      = QVBoxLayout(srv_grp)
        sl.setSpacing(10)
        sl.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(srv_grp)

        r1 = QHBoxLayout()
        sl.addLayout(r1)
        r1.addWidget(ThemeLabel("Port:", "TEXT_MUTED", SZ_BODY, bold=True))
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(8765)
        self.spin_port.setFixedWidth(100)
        r1.addWidget(self.spin_port)
        r1.addStretch()

        r2 = QHBoxLayout()
        sl.addLayout(r2)
        self.btn_start = QPushButton("START SERVER")
        self.btn_start.clicked.connect(self._start_server)
        self.btn_stop = QPushButton("STOP SERVER")
        self.btn_stop.setObjectName("btn_disconnect")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_server)
        r2.addWidget(self.btn_start)
        r2.addWidget(self.btn_stop)
        r2.addStretch()

        self.lbl_status = ThemeLabel("Server stopped", "TEXT_MUTED", SZ_BODY)
        sl.addWidget(self.lbl_status)

        #  Connection guide 
        guide_grp = QGroupBox("CONNECTION GUIDE")
        gl        = QVBoxLayout(guide_grp)
        gl.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(guide_grp)
        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setFixedHeight(175)
        guide.setFont(_ui_font(SZ_BODY))
        guide.setHtml(f"""
<pre style="color:{T.PRIMARY}; font-size:{SZ_BODY}px; line-height:1.7; font-family:Consolas,monospace;">
Connect with wscat:
  wscat -c ws://YOUR_IP:8765

Python viewer:
  import websockets, asyncio
  async def watch():
      async with websockets.connect("ws://YOUR_IP:8765") as ws:
          async for msg in ws: print(msg)
  asyncio.run(watch())

Get your IP:  ipconfig (Windows) / ifconfig (Linux/Mac)
Internet:     ngrok http 8765
</pre>""")
        gl.addWidget(guide)

        #  Activity log 
        act_grp = QGroupBox("CLIENT ACTIVITY")
        al      = QVBoxLayout(act_grp)
        al.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(act_grp, stretch=1)
        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setFont(_ui_font(SZ_BODY))
        al.addWidget(self.activity_log)

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()

    def _start_server(self):
        self._server._ws_port = self.spin_port.value()
        self._server.start()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _stop_server(self):
        self._server.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Server stopped")

    def _on_status(self, msg: str):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(f"color: {T.PRIMARY}; font-size: {SZ_BODY}px;")

    def _on_client_event(self, msg: str):
        ts    = datetime.datetime.now().strftime("%H:%M:%S")
        color = (T.PRIMARY if "connected" in msg and "dis" not in msg
                 else T.ACCENT_AMBER)
        self.activity_log.append(
            f'<span style="color:{T.TEXT_MUTED}">[{ts}]</span> '
            f'<span style="color:{color}">{msg}</span>'
        )
