"""
tab_scpi.py  LXI/SCPI Command Server Tab for STM32 Lab GUI v6.0

Roadmap item #11: LXI/SCPI TCP server UI.
Shows server status, connected clients, command log, and lets the user
test queries interactively via a built-in terminal.
"""

import datetime
from typing import Callable, Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit,
    QGroupBox, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QMessageBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header
from scpi_server import SCPIServer


class SCPITab(QWidget):
    """LXI/SCPI Server management tab."""

    def __init__(self):
        super().__init__()
        self._header_strip: Optional[_HeaderStrip] = None
        self._server = SCPIServer()
        self._server.set_log_fn(self._log)

        self._poll_timer = QTimer()
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_status)

        self._build_ui()
        self._poll_timer.start()

    #  UI 

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        hdr, hdr_lay = make_header("LXI / SCPI Command Server")
        self._header_strip = hdr

        self.btn_start = QPushButton(" START SERVER")
        self.btn_start.setObjectName("btn_connect")
        self.btn_start.setFixedWidth(170)
        self.btn_start.clicked.connect(self._start_server)
        hdr_lay.addWidget(self.btn_start)

        self.btn_stop = QPushButton(" STOP")
        self.btn_stop.setObjectName("btn_disconnect")
        self.btn_stop.setFixedWidth(100)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop_server)
        hdr_lay.addWidget(self.btn_stop)

        root.addWidget(hdr)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        #  LEFT: server config + status 
        left_w = QWidget()
        left_w.setMaximumWidth(300)
        l_lay = QVBoxLayout(left_w)
        l_lay.setContentsMargins(14, 14, 14, 14)
        l_lay.setSpacing(12)

        cfg_grp = QGroupBox("SERVER CONFIGURATION")
        cg = QVBoxLayout(cfg_grp)
        cg.setContentsMargins(12, 24, 12, 12)
        cg.setSpacing(8)

        row_port = QHBoxLayout()
        row_port.addWidget(ThemeLabel("Port:", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_port = QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(5025)
        row_port.addWidget(self.spin_port)
        cg.addLayout(row_port)

        l_lay.addWidget(cfg_grp)

        # Status cards
        self.lbl_status   = QLabel("STOPPED")
        self.lbl_clients  = QLabel("0")
        self.lbl_commands = QLabel("0")
        self._stat_cards  = [
            ThemeCard("SERVER STATUS", self.lbl_status,   "ACCENT_RED"),
            ThemeCard("CLIENTS",       self.lbl_clients,  "ACCENT_BLUE"),
            ThemeCard("COMMANDS RX",   self.lbl_commands, "PRIMARY"),
        ]
        for card in self._stat_cards:
            l_lay.addWidget(card)

        # Quick SCPI reference
        ref_grp = QGroupBox("QUICK REFERENCE")
        rl = QVBoxLayout(ref_grp)
        rl.setContentsMargins(12, 24, 12, 12)
        commands = [
            ("*IDN?",         "Identify instrument"),
            ("MEAS:VOLT:DC?", "Read mean voltage"),
            ("MEAS:FREQ?",    "Read dominant freq"),
            ("MEAS:VOLT:AC?", "Read Vpp"),
            ("CONF:FREQ 500", "Set output 500 Hz"),
            ("TRAC:DATA?",    "Get DSO buffer"),
            ("*RST",          "Reset to default"),
            ("SYST:ERR?",     "Read error queue"),
        ]
        self._ref_table = QTableWidget(len(commands), 2)
        self._ref_table.setHorizontalHeaderLabels(["Command", "Description"])
        self._ref_table.horizontalHeader().setStretchLastSection(True)
        self._ref_table.verticalHeader().setVisible(False)
        self._ref_table.setMaximumHeight(220)
        self._ref_table.setFont(_ui_font(SZ_SM))
        for i, (cmd, desc) in enumerate(commands):
            ci = QTableWidgetItem(cmd)
            di = QTableWidgetItem(desc)
            ci.setForeground(QColor(T.ACCENT_AMBER))
            di.setForeground(QColor(T.TEXT_MUTED))
            self._ref_table.setItem(i, 0, ci)
            self._ref_table.setItem(i, 1, di)
        rl.addWidget(self._ref_table)
        l_lay.addWidget(ref_grp)
        l_lay.addStretch()
        splitter.addWidget(left_w)

        #  RIGHT: log + interactive terminal 
        right_w = QWidget()
        r_lay = QVBoxLayout(right_w)
        r_lay.setContentsMargins(8, 8, 8, 8)
        r_lay.setSpacing(8)

        log_grp = QGroupBox("SERVER LOG")
        ll = QVBoxLayout(log_grp)
        ll.setContentsMargins(10, 20, 10, 10)
        self._log_box = QTextEdit()
        self._log_box.setReadOnly(True)
        self._log_box.setFont(_ui_font(SZ_BODY))
        self._log_box.setStyleSheet(
            f"background: {T.DARK_BG}; color: {T.PRIMARY}; border: 1px solid {T.BORDER};")
        ll.addWidget(self._log_box)
        r_lay.addWidget(log_grp, stretch=1)

        # Interactive SCPI terminal
        term_grp = QGroupBox("INTERACTIVE SCPI TERMINAL  (test commands locally)")
        tl = QVBoxLayout(term_grp)
        tl.setContentsMargins(10, 20, 10, 10)
        trow = QHBoxLayout()
        self._term_input = QLineEdit()
        self._term_input.setFont(_ui_font(SZ_BODY))
        self._term_input.setPlaceholderText("*IDN?  or  MEAS:VOLT:DC?  ")
        self._term_input.returnPressed.connect(self._exec_local)
        trow.addWidget(self._term_input, stretch=1)
        btn_exec = QPushButton("SEND")
        btn_exec.setFixedWidth(80)
        btn_exec.clicked.connect(self._exec_local)
        trow.addWidget(btn_exec)
        self._term_output = QTextEdit()
        self._term_output.setReadOnly(True)
        self._term_output.setFont(_ui_font(SZ_BODY))
        self._term_output.setFixedHeight(100)
        self._term_output.setStyleSheet(
            f"background: {T.CARD_BG}; color: {T.ACCENT_CYAN}; border: 1px solid {T.BORDER};")
        tl.addLayout(trow)
        tl.addWidget(self._term_output)
        r_lay.addWidget(term_grp)
        splitter.addWidget(right_w)
        splitter.setSizes([280, 900])

        self._log(f"SCPI server ready. Port: {self.spin_port.value()}")
        self._log("Compatible with: pyvisa, LabVIEW, MATLAB, python-vxi11")

    #  Theme 

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        self._log_box.setStyleSheet(
            f"background: {T.DARK_BG}; color: {T.PRIMARY}; border: 1px solid {T.BORDER};")
        self._term_output.setStyleSheet(
            f"background: {T.CARD_BG}; color: {T.ACCENT_CYAN}; border: 1px solid {T.BORDER};")

    #  Public API 

    def set_send_fn(self, fn: Callable[[str], None]):
        self._server.dispatcher.set_send(fn)

    def set_stats_fn(self, fn: Callable[[], dict]):
        self._server.dispatcher.set_stats(fn)

    def set_snapshot_fn(self, fn: Callable[[], list]):
        self._server.dispatcher.set_snapshot(fn)

    #  Actions 

    def _start_server(self):
        port = self.spin_port.value()
        self._server = SCPIServer(port=port)
        self._server.set_log_fn(self._log)
        ok = self._server.start()
        if ok:
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.spin_port.setEnabled(False)
            self.lbl_status.setText("RUNNING")
            self.lbl_status.setStyleSheet(
                f"color: {T.PRIMARY}; font-size: {SZ_STAT}px; font-weight: 700; "
                f"font-family: {T.FONT_MONO}; background: transparent; border: none;")
        else:
            QMessageBox.critical(self, "Server Error",
                f"Could not start SCPI server on port {port}.\n"
                f"Try a different port or check firewall settings.")

    def _stop_server(self):
        self._server.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.spin_port.setEnabled(True)
        self.lbl_status.setText("STOPPED")
        self.lbl_status.setStyleSheet(
            f"color: {T.ACCENT_RED}; font-size: {SZ_STAT}px; font-weight: 700; "
            f"font-family: {T.FONT_MONO}; background: transparent; border: none;")

    def _exec_local(self):
        """Execute SCPI command locally via the dispatcher (no network needed)."""
        cmd = self._term_input.text().strip()
        if not cmd:
            return
        self._term_input.clear()
        response = self._server.dispatcher.handle(cmd)
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._term_output.append(
            f'<span style="color:{T.ACCENT_BLUE};">[{ts}] &gt;&gt; {cmd}</span>')
        if response:
            self._term_output.append(
                f'<span style="color:{T.ACCENT_CYAN};">    {response}</span>')

    def _poll_status(self):
        if self._server.is_running:
            self.lbl_clients.setText(str(self._server.client_count))

    _cmd_count = 0

    def _log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        col = T.PRIMARY if "started" in msg.lower() or "running" in msg.lower() else T.TEXT_MUTED
        if "error" in msg.lower() or "stopped" in msg.lower():
            col = T.ACCENT_RED
        if "client connected" in msg.lower():
            col = T.ACCENT_CYAN
        self._log_box.append(
            f'<span style="color:{col}; font-family:Consolas,monospace;">[{ts}] {msg}</span>')
        sb = self._log_box.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._cmd_count += 1
        self.lbl_commands.setText(str(self._cmd_count))
