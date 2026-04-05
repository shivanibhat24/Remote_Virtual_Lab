"""
tab_connection.py  Serial Connection Manager tab for STM32 Lab GUI v4.0
"""

import datetime
from typing import Optional, List

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTextEdit,
    QGroupBox, QCheckBox
)
from PyQt5.QtCore import pyqtSignal

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, _HeaderStrip, make_header

_MAX_LOG_LINES = 5000   # BUG-FIX: prevent memory growth


class ConnectionTab(QWidget):
    connect_requested    = pyqtSignal(str)
    disconnect_requested = pyqtSignal()
    refresh_requested    = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._log_line_count = 0
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, _ = make_header("Connection Manager")
        self._header_strip = hdr
        root.addWidget(hdr)

        content = QWidget()
        c_lay   = QVBoxLayout(content)
        c_lay.setContentsMargins(16, 16, 16, 16)
        c_lay.setSpacing(16)
        root.addWidget(content, stretch=1)

        #  Port selection 
        port_grp = QGroupBox("SERIAL PORT")
        pl       = QVBoxLayout(port_grp)
        pl.setSpacing(10)
        pl.setContentsMargins(14, 22, 14, 14)
        c_lay.addWidget(port_grp)

        pr = QHBoxLayout()
        pl.addLayout(pr)
        pr.addWidget(ThemeLabel("Port:", "TEXT_MUTED", SZ_BODY, bold=True))
        self.cmb_port = QComboBox()
        self.cmb_port.setMinimumWidth(200)
        pr.addWidget(self.cmb_port)
        btn_r = QPushButton("REFRESH")
        btn_r.setFixedWidth(100)
        btn_r.clicked.connect(self.refresh_requested.emit)
        pr.addWidget(btn_r)
        pr.addStretch()

        br = QHBoxLayout()
        pl.addLayout(br)
        self.btn_connect = QPushButton("CONNECT")
        self.btn_connect.setObjectName("btn_connect")
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_disconnect = QPushButton("DISCONNECT")
        self.btn_disconnect.setObjectName("btn_disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.clicked.connect(self.disconnect_requested.emit)
        br.addWidget(self.btn_connect)
        br.addWidget(self.btn_disconnect)
        br.addStretch()

        sr = QHBoxLayout()
        pl.addLayout(sr)
        self.lbl_dot  = QLabel("[+]")
        self.lbl_dot.setStyleSheet(f"color: {T.ACCENT_RED}; font-size: {SZ_LG}px;")
        self.lbl_conn = ThemeLabel("Disconnected", "TEXT_MUTED", SZ_BODY)
        sr.addWidget(self.lbl_dot)
        sr.addWidget(self.lbl_conn)
        sr.addStretch()

        #  Communication log 
        log_grp = QGroupBox("COMMUNICATION LOG")
        ll      = QVBoxLayout(log_grp)
        ll.setContentsMargins(14, 22, 14, 14)
        ll.setSpacing(8)
        c_lay.addWidget(log_grp, stretch=1)

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setFont(_ui_font(SZ_BODY))
        ll.addWidget(self.log_box)

        lc = QHBoxLayout()
        ll.addLayout(lc)
        btn_cl = QPushButton("CLEAR")
        btn_cl.setFixedWidth(90)
        btn_cl.clicked.connect(self._clear_log)
        self.chk_scroll = QCheckBox("Auto-scroll")
        self.chk_scroll.setChecked(True)
        lc.addWidget(btn_cl)
        lc.addStretch()
        lc.addWidget(self.chk_scroll)

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()

    def _on_connect(self):
        port_text = self.cmb_port.currentText()
        if not port_text:
            return
        
        # Extract actual port name from descriptive text
        port = port_text.split(' - ')[0] if ' - ' in port_text else port_text
        
        # Validate it's a USB device
        if not self._is_usb_device(port):
            self.log(f"Port {port} is not a recognized USB device", T.ACCENT_AMBER)
            return
        
        self.connect_requested.emit(port)
    
    def _is_usb_device(self, port: str) -> bool:
        """Check if the connected device is a USB device."""
        try:
            import serial.tools.list_ports
            port_info = None
            for p in serial.tools.list_ports.comports():
                if p.device == port:
                    port_info = p
                    break
            
            if not port_info:
                return False
            
            # Allow any USB device (check if it's a USB serial device)
            is_usb_device = port_info.vid is not None and port_info.vid != 0
            
            # Also check common USB serial device identifiers
            usb_identifiers = ['USB', 'SERIAL', 'CH340', 'CP210', 'FTDI', 'PL2303', 'CDC', 'ACM', 
                             'STM32', 'STLINK', 'ARDUINO', 'ESP32', 'ESP8266']
            has_usb_identifier = any(identifier in port_info.description.upper() for identifier in usb_identifiers)
            
            return is_usb_device or has_usb_identifier
        except:
            return False

    def set_connected(self, port: str):
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.cmb_port.setEnabled(False)
        self.lbl_dot.setStyleSheet(f"color: {T.PRIMARY}; font-size: {SZ_LG}px;")
        self.lbl_conn.setText(f"Connected    {port}    115200 baud")
        self.lbl_conn.setStyleSheet(f"color: {T.PRIMARY}; font-size: {SZ_BODY}px;")

    def set_disconnected(self):
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.cmb_port.setEnabled(True)
        self.lbl_dot.setStyleSheet(f"color: {T.ACCENT_RED}; font-size: {SZ_LG}px;")
        self.lbl_conn.setText("Disconnected")
        self.lbl_conn.setStyleSheet(f"color: {T.TEXT_MUTED}; font-size: {SZ_BODY}px;")

    def update_ports(self, ports: List[str]):
        current = self.cmb_port.currentText()
        self.cmb_port.clear()
        self.cmb_port.addItems(ports)
        idx = self.cmb_port.findText(current)
        if idx >= 0:
            self.cmb_port.setCurrentIndex(idx)

    def log(self, text: str, color: Optional[str] = None):
        # BUG-FIX: limit log to _MAX_LOG_LINES to prevent OOM
        if self._log_line_count >= _MAX_LOG_LINES:
            self._clear_log()
        col  = color or T.PRIMARY
        ts   = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        html = (f'<span style="color:{T.TEXT_MUTED}">[{ts}]</span> '
                f'<span style="color:{col}">{text}</span>')
        self.log_box.append(html)
        self._log_line_count += 1
        if self.chk_scroll.isChecked():
            sb = self.log_box.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _clear_log(self):
        self.log_box.clear()
        self._log_line_count = 0
