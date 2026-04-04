"""
tab_cloud.py - MQTT Cloud Relay tab for STM32 Lab GUI v6.0
Replaces the local network WebSocket viewer.
"""

import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QGroupBox, QLineEdit
)
from PyQt5.QtCore import Qt

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header
from mqtt_bridge import MqttBridge, HAS_MQTT


class CloudTab(QWidget):
    def __init__(self, bridge: MqttBridge):
        super().__init__()
        self._bridge = bridge
        self._header_strip: Optional[_HeaderStrip] = None
        self._has_visited = False
        self._build_ui()
        self._bridge.status_changed.connect(self._on_status)
        self._bridge.log_event.connect(self._on_log_event)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, _ = make_header("Cloud Relay (NAT Traversal)")
        self._header_strip = hdr
        root.addWidget(hdr)

        content = QWidget()
        c_lay   = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(16)
        root.addWidget(content, stretch=1)

        if not HAS_MQTT:
            w = QLabel("paho-mqtt library not found.\nRun:  pip install paho-mqtt")
            w.setAlignment(Qt.AlignCenter)
            w.setStyleSheet(f"color: {T.ACCENT_RED}; font-size: {SZ_LG}px;")
            c_lay.addStretch()
            c_lay.addWidget(w)
            c_lay.addStretch()
            return

        # -- Server controls ---------------------------------------------------
        srv_grp = QGroupBox("CLOUD BROKER RELAY")
        sl      = QVBoxLayout(srv_grp)
        sl.setSpacing(10)
        sl.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(srv_grp)

        r1 = QHBoxLayout()
        sl.addLayout(r1)
        r1.addWidget(ThemeLabel("Global Session ID:", "TEXT_MUTED", SZ_BODY, bold=True))
        
        self.txt_session = QLineEdit()
        self.txt_session.setText(self._bridge.session_id)
        self.txt_session.setReadOnly(True)
        self.txt_session.setFont(_ui_font(SZ_LG, bold=True))
        self.txt_session.setFixedWidth(200)
        self.txt_session.setAlignment(Qt.AlignCenter)
        r1.addWidget(self.txt_session)
        r1.addStretch()

        r2 = QHBoxLayout()
        sl.addLayout(r2)
        self.btn_start = QPushButton("CONNECT TO CLOUD")
        self.btn_start.clicked.connect(self._start_server)
        self.btn_start.setFixedHeight(40)
        
        self.btn_stop = QPushButton("DISCONNECT")
        self.btn_stop.setObjectName("btn_disconnect")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_server)
        self.btn_stop.setFixedHeight(40)
        
        r2.addWidget(self.btn_start)
        r2.addWidget(self.btn_stop)
        r2.addStretch()

        self.lbl_status = ThemeLabel("Status: OFFLINE", "TEXT_MUTED", SZ_BODY)
        sl.addWidget(self.lbl_status)

        guide_grp = QGroupBox("HOW TO USE")
        gl        = QVBoxLayout(guide_grp)
        gl.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(guide_grp)
        guide = QTextEdit()
        guide.setReadOnly(True)
        guide.setFixedHeight(140)
        guide.setFont(_ui_font(SZ_BODY))
        guide.setHtml(f"""
<pre style="color:{T.PRIMARY}; font-size:{SZ_BODY}px; line-height:1.7; font-family:Consolas,monospace;">
1. Send the `global_dashboard.html` file to your professor/colleague anywhere in the world.
2. They do not need Python. They simply double-click the file to open it in Chrome/Safari.
3. Once they open it, they type the 6-character Session ID above into their browser.
4. They will see the live oscilloscope and be able to remote-control your physical board seamlessly without port-forwarding!
</pre>""")
        gl.addWidget(guide)

        # -- Activity log ------------------------------------------------------
        act_grp = QGroupBox("CLOUD ACTIVITY DIALOG")
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
        if hasattr(self, "txt_session"):
            self.txt_session.setStyleSheet(
                f"color: {T.PRIMARY}; background: {T.DARK_BG}; "
                f"border: 1px solid {T.BORDER}; border-radius: 4px; padding: 4px;"
            )

    def _start_server(self):
        self._bridge.connect_cloud()
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)

    def _stop_server(self):
        self._bridge.disconnect_cloud()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.lbl_status.setText("Status: OFFLINE")

    def prompt_session_id(self):
        """Called by MainWindow on visit."""
        if self._has_visited:
            return
        self._has_visited = True
        
        msg = (f"A new random Session ID has been generated: <b>{self._bridge.session_id}</b><br><br>"
               "Do you want to continue with this session ID for your remote dashboard?")
        
        res = QMessageBox.question(self, "MQTT Session", msg, 
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        
        if res == QMessageBox.No:
            # Let them change it
            new_id, ok = QInputDialog.getText(self, "Change Session ID", 
                                              "Enter new Session ID (alphanumeric):",
                                              text=self._bridge.session_id)
            if ok and new_id.strip():
                self._bridge.set_session_id(new_id.strip())
                self.txt_session.setText(new_id.strip())
                self._on_log_event(f"[SYSTEM] Session ID changed to: {new_id.strip()}", T.ACCENT_CYAN)
        else:
            self._on_log_event(f"[SYSTEM] Continuing with random ID: {self._bridge.session_id}", T.ACCENT_CYAN)

    def _on_status(self, msg: str):
        self.lbl_status.setText(msg)
        self.lbl_status.setStyleSheet(f"color: {T.PRIMARY}; font-size: {SZ_BODY}px; font-weight: bold;")

    def _on_log_event(self, msg: str, color: Optional[str] = None):
        ts    = datetime.datetime.now().strftime("%H:%M:%S")
        if color is None:
            color = T.TEXT_MUTED if "disconnected" in msg else T.ACCENT_CYAN
            if "Command" in msg:
                color = T.ACCENT_AMBER
        self.activity_log.append(
            f'<span style="color:{T.TEXT_MUTED}">[{ts}]</span> '
            f'<span style="color:{color}">{msg}</span>'
        )
