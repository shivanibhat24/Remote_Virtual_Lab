"""
tab_multimeter.py  Multimeter + DSO tab for STM32 Lab GUI v6.0

New in v6.0:
  * Dual vertical cursors with Delta T / Delta V readout panel
  * SVG export (publication-quality vector graphic)
  * Eye-diagram overlay toggle
  * Click-to-annotate: Ctrl+click on plot -> text label
"""

import os
import datetime
from collections import deque
from pathlib import Path
from typing import Optional, List, Callable

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QCheckBox, QSplitter, QMessageBox, QInputDialog,
    QMenu, QAction, QGroupBox
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QPointF
from PyQt5.QtGui import QFont, QColor

from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font
from widgets import ThemeLabel, ThemeCard, _HeaderStrip, make_header, LocalLoggerWidget
from data_engine import CommandBuilder, AnalyticsEngine, ParsedMessage


class MultimeterTab(QWidget):
    send_requested = pyqtSignal(str)

    DSO_SAMPLES   = 500
    PLOT_FPS      = 20
    MODE_MAP      = {"Voltmeter": "V", "Ammeter": "A", "DSO": "D", "Ground": "G"}
    RANGE_MAP     = {"12 V": 12, "16 V": 16, "24 V": 24}

    def __init__(self, analytics: AnalyticsEngine, screenshot_provider: Optional[Callable] = None):
        super().__init__()
        self._analytics = analytics
        self._screenshot_provider = screenshot_provider
        self._dso_buf: deque = deque(maxlen=self.DSO_SAMPLES)
        self._last_mode = "V"
        self._last_unit = "V"
        self.sample_period = 0.010  # default
        self._stat_cards:  List[ThemeCard]    = []
        self._header_strip: Optional[_HeaderStrip] = None

        # Annotations (click-to-add text items)
        self._annotations: List[pg.TextItem] = []

        # Eye diagram state
        self._eye_mode = False

        self._build_ui()
        self._build_timers()

    # -- UI Build --------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # header
        hdr, hdr_lay = make_header("Multimeter / DSO")
        self._header_strip = hdr

        hdr_lay.addWidget(ThemeLabel("MODE", "TEXT_MUTED", SZ_SM, bold=True))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems(self.MODE_MAP.keys())
        self.cmb_mode.setFixedWidth(120)
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        hdr_lay.addWidget(self.cmb_mode)

        hdr_lay.addSpacing(10)
        hdr_lay.addWidget(ThemeLabel("RANGE", "TEXT_MUTED", SZ_SM, bold=True))
        self.cmb_range = QComboBox()
        self.cmb_range.addItems(self.RANGE_MAP.keys())
        self.cmb_range.setFixedWidth(90)
        hdr_lay.addWidget(self.cmb_range)

        hdr_lay.addSpacing(10)
        self.btn_send = QPushButton("APPLY")
        self.btn_send.setFixedWidth(90)
        self.btn_send.clicked.connect(self._on_send)
        hdr_lay.addWidget(self.btn_send)

        self.btn_screenshot = QPushButton("CAPTURE")
        self.btn_screenshot.setObjectName("btn_warning")
        self.btn_screenshot.setFixedWidth(110)
        self.btn_screenshot.setToolTip("Save waveform as PNG (Selected folder)")
        self.btn_screenshot.clicked.connect(self._take_screenshot)
        hdr_lay.addWidget(self.btn_screenshot)

        self.btn_svg = QPushButton("SVG")
        self.btn_svg.setFixedWidth(70)
        self.btn_svg.setToolTip("Export waveform as SVG (publication quality)")
        self.btn_svg.clicked.connect(self._export_svg)
        hdr_lay.addWidget(self.btn_svg)

        self.btn_eye = QPushButton("EYE")
        self.btn_eye.setFixedWidth(70)
        self.btn_eye.setCheckable(True)
        self.btn_eye.setToolTip("Toggle eye diagram overlay")
        self.btn_eye.clicked.connect(self._toggle_eye)
        hdr_lay.addWidget(self.btn_eye)

        self.chk_cursors = QCheckBox("CURSORS")
        self.chk_cursors.setToolTip("Show dual Delta T / Delta V measurement cursors")
        self.chk_cursors.stateChanged.connect(self._toggle_cursors)
        hdr_lay.addWidget(self.chk_cursors)

        self.chk_auto = QCheckBox("AUTO")
        self.chk_auto.setToolTip("Auto-capture on stable waveform")
        hdr_lay.addWidget(self.chk_auto)
        
        self.local_logger = LocalLoggerWidget("multimeter", ["timestamp", "mode", "value_v", "value_a"])
        hdr_lay.addStretch()
        hdr_lay.addWidget(self.local_logger)
        
        root.addWidget(hdr)

        # splitter
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, stretch=1)

        # -- Reading panel -----------------------------------------------------
        rp     = QWidget()
        rp_lay = QHBoxLayout(rp)
        rp_lay.setContentsMargins(16, 12, 16, 12)
        rp_lay.setSpacing(12)

        val_w = QWidget()
        vl    = QVBoxLayout(val_w)
        vl.setContentsMargins(24, 16, 24, 16)
        vl.setSpacing(6)

        self.lbl_value = QLabel("- - -")
        self.lbl_value.setAlignment(Qt.AlignCenter)
        self.lbl_value.setFont(_ui_font(SZ_BIG, bold=True))

        self.lbl_unit = QLabel("SELECT MODE")
        self.lbl_unit.setAlignment(Qt.AlignCenter)
        self.lbl_unit.setFont(_ui_font(SZ_LG))

        vl.addWidget(self.lbl_value)
        vl.addWidget(self.lbl_unit)
        rp_lay.addWidget(val_w, stretch=2)

        # stat cards
        sg_w = QWidget()
        sg_w.setStyleSheet("background: transparent;")
        sg   = QGridLayout(sg_w)
        sg.setSpacing(6)
        sg.setContentsMargins(0, 0, 0, 0)

        self._stat_labels: dict = {}
        stat_defs = [
            ("MEAN",     "PRIMARY",      0, 0),
            ("STD DEV",  "ACCENT_PUR",   0, 1),
            ("MIN",      "ACCENT_BLUE",  1, 0),
            ("MAX",      "ACCENT_RED",   1, 1),
            ("VRMS",     "ACCENT_AMBER", 2, 0),
            ("VPP",      "ACCENT_CYAN",  2, 1),
            ("DOM FREQ", "TEXT",         3, 0),
            ("SAMPLES",  "TEXT_MUTED",   3, 1),
        ]
        for key, col_attr, row, col in stat_defs:
            val_lbl = QLabel("")
            card    = ThemeCard(key, val_lbl, col_attr)
            sg.addWidget(card, row, col)
            self._stat_labels[key] = val_lbl
            self._stat_cards.append(card)

        rp_lay.addWidget(sg_w, stretch=3)
        splitter.addWidget(rp)

        # -- DSO plot panel ----------------------------------------------------
        dso_w = QWidget()
        dp    = QVBoxLayout(dso_w)
        dp.setContentsMargins(16, 6, 16, 10)
        dp.setSpacing(4)

        # Cursor readout panel
        self._cursor_panel = QGroupBox("CURSOR MEASUREMENT")
        self._cursor_panel.setVisible(False)
        cp_lay = QHBoxLayout(self._cursor_panel)
        cp_lay.setContentsMargins(12, 18, 12, 8)
        cp_lay.setSpacing(20)
        self._lbl_c1    = QLabel("C1: - V")
        self._lbl_c2    = QLabel("C2: - V")
        self._lbl_dt    = QLabel("Delta T: - s")
        self._lbl_dv    = QLabel("Delta V: - V")
        self._lbl_freq  = QLabel("1/Delta T: - Hz")
        for lbl in (self._lbl_c1, self._lbl_c2, self._lbl_dt, self._lbl_dv, self._lbl_freq):
            lbl.setFont(_ui_font(SZ_BODY, bold=True))
            lbl.setStyleSheet(f"color: {T.ACCENT_CYAN}; background: transparent; border: none;")
            cp_lay.addWidget(lbl)
        cp_lay.addStretch()
        dp.addWidget(self._cursor_panel)

        # Plot header row
        dso_hdr = QHBoxLayout()
        dso_hdr.addWidget(ThemeLabel("DSO WAVEFORM", "TEXT_MUTED", SZ_SM, bold=True))
        dso_hdr.addStretch()
        dso_hdr.addWidget(ThemeLabel("TIME/DIV", "TEXT_MUTED", SZ_SM, bold=True))
        self.spin_timediv = QDoubleSpinBox()
        self.spin_timediv.setRange(0.005, 5.0)
        self.spin_timediv.setValue(0.1)
        self.spin_timediv.setSuffix(" s")
        self.spin_timediv.setSingleStep(0.05)
        self.spin_timediv.setDecimals(3)
        self.spin_timediv.setFixedWidth(120)
        self.spin_timediv.valueChanged.connect(self._apply_timediv)
        dso_hdr.addWidget(self.spin_timediv)
        dp.addLayout(dso_hdr)

        pg.setConfigOption("background", T.DARK_BG)
        pg.setConfigOption("foreground", T.TEXT_MUTED)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumHeight(200)
        self.plot_widget.setLabel("left",   "Amplitude (V)", color=T.TEXT_MUTED)
        self.plot_widget.setLabel("bottom", "Time (s)",      color=T.TEXT_MUTED)
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis("left").setTextPen(T.TEXT_MUTED)
        self.plot_widget.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        self.plot_widget.enableAutoRange(axis="y", enable=True)
        self.plot_widget.enableAutoRange(axis="x", enable=False)

        self._curve     = self.plot_widget.plot(pen=pg.mkPen(T.ACCENT_BLUE, width=2))
        self._overlay   = self.plot_widget.plot(pen=pg.mkPen(T.PRIMARY, width=1.5,
                                                             style=Qt.DashLine))
        self._eye_curves: List = []  # eye diagram overlay curves

        # Trigger line
        self._trig_line = pg.InfiniteLine(
            angle=0, movable=True,
            pen=pg.mkPen(T.ACCENT_AMBER, width=1, style=Qt.DashLine),
            label="TRIG {value:.2f}V",
            labelOpts={"color": T.ACCENT_AMBER, "position": 0.05}
        )
        self.plot_widget.addItem(self._trig_line)
        self._trig_line.setValue(1.0)

        # -- Dual cursors ------------------------------------------------------
        self._cursor1 = pg.InfiniteLine(
            angle=90, movable=True,
            pen=pg.mkPen(T.ACCENT_CYAN, width=1, style=Qt.DashLine),
            label="C1", labelOpts={"color": T.ACCENT_CYAN, "position": 0.9}
        )
        self._cursor2 = pg.InfiniteLine(
            angle=90, movable=True,
            pen=pg.mkPen(T.ACCENT_PUR, width=1, style=Qt.DashLine),
            label="C2", labelOpts={"color": T.ACCENT_PUR, "position": 0.8}
        )
        self._cursor1.setValue(-0.5)
        self._cursor2.setValue(-0.1)
        self._cursor1.sigPositionChanged.connect(self._update_cursor_readout)
        self._cursor2.sigPositionChanged.connect(self._update_cursor_readout)
        # Cursors added/removed dynamically via chk_cursors

        dp.addWidget(self.plot_widget, stretch=1)

        # Enable right-click context menu for annotations
        self.plot_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plot_widget.customContextMenuRequested.connect(self._plot_context_menu)

        splitter.addWidget(dso_w)
        splitter.setSizes([240, 400])

        self._on_mode_changed()
        self._apply_timediv()
        self._refresh_val_colors()

    # -- Theme Helpers ---------------------------------------------------------

    def _refresh_val_colors(self):
        self.lbl_value.setStyleSheet(
            f"color: {T.PRIMARY}; background: transparent; border: none;"
        )
        self.lbl_unit.setStyleSheet(
            f"color: {T.TEXT_MUTED}; background: transparent; border: none;"
        )

    def update_theme(self):
        if self._header_strip:
            self._header_strip.update_theme()
        if getattr(self, "local_logger", None):
            self.local_logger.update_theme()
        for card in self._stat_cards:
            card.update_theme()
        self._refresh_val_colors()
        self.plot_widget.setBackground(T.DARK_BG)
        self.plot_widget.getAxis("left").setTextPen(T.TEXT_MUTED)
        self.plot_widget.getAxis("bottom").setTextPen(T.TEXT_MUTED)
        # Refresh cursor readout labels
        for lbl in (self._lbl_c1, self._lbl_c2, self._lbl_dt, self._lbl_dv, self._lbl_freq):
            lbl.setStyleSheet(f"color: {T.ACCENT_CYAN}; background: transparent; border: none;")

    # -- Timers ----------------------------------------------------------------

    def _build_timers(self):
        self._plot_timer = QTimer()
        self._plot_timer.setInterval(1000 // self.PLOT_FPS)
        self._plot_timer.timeout.connect(self._refresh_plot)
        self._plot_timer.start()

        self._stats_timer = QTimer()
        self._stats_timer.setInterval(250)
        self._stats_timer.timeout.connect(self._refresh_stats)
        self._stats_timer.start()

    # -- Slots -----------------------------------------------------------------

    def _apply_timediv(self, _=None):
        self.plot_widget.setXRange(-10.0 * self.spin_timediv.value(), 0.0, padding=0)

    def _on_mode_changed(self):
        self.cmb_range.setEnabled(
            self.cmb_mode.currentText() in ("Voltmeter", "DSO"))

    def _on_send(self):
        mode_key  = self.cmb_mode.currentText()
        mode_char = self.MODE_MAP[mode_key]
        self.send_requested.emit(CommandBuilder.mode_cmd(mode_char))
        if mode_char in ("V", "D"):
            self.send_requested.emit(
                CommandBuilder.range_cmd(self.RANGE_MAP[self.cmb_range.currentText()]))

    # -- Screenshot / Export ---------------------------------------------------

    def _take_screenshot(self):
        # Use provider if available, else default to stm32lab/screenshots
        if self._screenshot_provider:
            dir_path = self._screenshot_provider()
        else:
            from pathlib import Path
            dir_path = Path.home() / "stm32lab" / "screenshots"
            dir_path.mkdir(parents=True, exist_ok=True)
            
        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = str(dir_path / f"waveform_{ts}.png")
        try:
            exp = pyqtgraph.exporters.ImageExporter(self.plot_widget.scene())
            if exp is None:
                raise RuntimeError("Could not create ImageExporter")
            try:
                exp.parameters()["width"] = 1280
            except Exception:
                pass
            exp.export(fname)
        except Exception as e:
            QMessageBox.warning(self, "Screenshot Error", str(e))

    def _export_svg(self):
        """Export waveform as SVG (publication-quality vector graphic). Item F."""
        if self._screenshot_provider:
            dir_path = self._screenshot_provider()
        else:
            from pathlib import Path
            dir_path = Path.home() / "stm32lab" / "screenshots"
            dir_path.mkdir(parents=True, exist_ok=True)

        ts    = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = str(dir_path / f"waveform_{ts}.svg")
        try:
            exp = pyqtgraph.exporters.SVGExporter(self.plot_widget.plotItem)
            exp.export(fname)
            QMessageBox.information(self, "SVG Exported",
                f"Saved to:\n{fname}")
        except Exception as e:
            QMessageBox.warning(self, "SVG Export Error", str(e))

    # -- Dual Cursors ----------------------------------------------------------

    def _toggle_cursors(self, state: int):
        """Show/hide dual cursors and the readout panel. Item D."""
        visible = state == Qt.Checked
        self._cursor_panel.setVisible(visible)
        if visible:
            self.plot_widget.addItem(self._cursor1)
            self.plot_widget.addItem(self._cursor2)
            self._update_cursor_readout()
        else:
            try:
                self.plot_widget.removeItem(self._cursor1)
                self.plot_widget.removeItem(self._cursor2)
            except Exception:
                pass

    def _update_cursor_readout(self, *_):
        """Recalculate Delta T / Delta V from cursor positions against the DSO buffer."""
        t1 = self._cursor1.value()
        t2 = self._cursor2.value()
        data = np.array(self._dso_buf, dtype=float)
        n    = len(data)
        if n == 0:
            return

        def _val_at_t(t: float) -> float:
            """Interpolate buffer value at time t (seconds, negative = past)."""
            idx = (t / self.sample_period) + (n - 1)
            idx = max(0.0, min(float(n - 1), idx))
            lo, hi = int(idx), min(int(idx) + 1, n - 1)
            frac = idx - lo
            return float(data[lo] * (1 - frac) + data[hi] * frac)

        v1 = _val_at_t(t1)
        v2 = _val_at_t(t2)
        dt = t2 - t1
        dv = v2 - v1
        freq_str = f"{1.0/abs(dt):.2f} Hz" if abs(dt) > 1e-9 else ""

        self._lbl_c1.setText(f"C1: {v1:.3f} V")
        self._lbl_c2.setText(f"C2: {v2:.3f} V")
        self._lbl_dt.setText(f"Delta T: {dt*1000:.2f} ms")
        self._lbl_dv.setText(f"Delta V: {dv:.3f} V")
        self._lbl_freq.setText(f"1/Delta T: {freq_str}")

    # -- Eye Diagram -----------------------------------------------------------

    def _toggle_eye(self, checked: bool):
        """Toggle eye diagram overlay (folds buffer by estimated period). Item E."""
        self._eye_mode = checked
        if not checked:
            for c in self._eye_curves:
                try:
                    self.plot_widget.removeItem(c)
                except Exception:
                    pass
            self._eye_curves.clear()

    def _draw_eye_diagram(self, data: np.ndarray):
        """Fold waveform by dominant period and overlay segments."""
        n = len(data)
        if n < 16:
            return

        # Estimate period via FFT
        mag  = np.abs(np.fft.rfft(data - data.mean()))
        frqs = np.fft.rfftfreq(n, d=self.sample_period)
        idx  = int(np.argmax(mag[1:])) + 1
        if idx >= len(frqs) or frqs[idx] < 0.5:
            return  # too low frequency for meaningful eye diagram
        period = 1.0 / frqs[idx]
        samples_per_period = max(4, int(round(period / self.sample_period)))

        # Remove old curves
        for c in self._eye_curves:
            try:
                self.plot_widget.removeItem(c)
            except Exception:
                pass
        self._eye_curves.clear()

        # Slice and overlay
        t_eye = np.linspace(0, period * 2, samples_per_period * 2)
        colors = [T.ACCENT_PUR, T.ACCENT_CYAN, T.PRIMARY, T.ACCENT_AMBER]
        seg_idx = 0
        i = 0
        while i + samples_per_period * 2 <= n:
            seg = data[i: i + samples_per_period * 2]
            t_s = np.linspace(0, period * 2, len(seg))
            col = colors[seg_idx % len(colors)]
            c   = self.plot_widget.plot(
                t_s, seg,
                pen=pg.mkPen(col + "55", width=1))
            self._eye_curves.append(c)
            i += samples_per_period
            seg_idx += 1
            if seg_idx > 20:   # cap for performance
                break

    # -- Annotations (click-to-add) --------------------------------------------

    def _plot_context_menu(self, pos):
        """Right-click context menu on plot for annotations. Item C."""
        menu = QMenu(self)
        act_add = QAction("Add Text Annotation Here", self)
        act_clr = QAction("Clear All Annotations", self)

        def _add():
            text, ok = QInputDialog.getText(self, "Annotation", "Label text:")
            if ok and text:
                # Map screen position  scene position  data coordinates
                scene_pos = self.plot_widget.plotItem.vb.mapSceneToView(
                    self.plot_widget.mapToScene(pos))
                ann = pg.TextItem(
                    text=text,
                    color=T.ACCENT_AMBER,
                    anchor=(0, 1),
                    border=pg.mkPen(T.BORDER),
                    fill=pg.mkBrush(T.CARD_BG + "cc"),
                )
                ann.setFont(_ui_font(SZ_SM))
                ann.setPos(scene_pos.x(), scene_pos.y())
                self.plot_widget.addItem(ann)
                self._annotations.append(ann)

        def _clear():
            for ann in self._annotations:
                try:
                    self.plot_widget.removeItem(ann)
                except Exception:
                    pass
            self._annotations.clear()

        act_add.triggered.connect(_add)
        act_clr.triggered.connect(_clear)
        menu.addAction(act_add)
        menu.addAction(act_clr)
        menu.exec_(self.plot_widget.mapToGlobal(pos))

    # -- Data Ingestion --------------------------------------------------------

    def on_data(self, msg: ParsedMessage):
        m = msg.fields.get("M", "")
        try:
            val = float(msg.fields.get("X", "0"))
        except ValueError:
            return
        self._analytics.push(val)
        if m == "V":
            self._last_mode = "V"; self._last_unit = "V"
            self.lbl_value.setText(f"{val:.3f}")
            self.lbl_unit.setText("VOLTS")
            self.lbl_value.setStyleSheet(
                f"color: {T.PRIMARY}; background: transparent; border: none;")
        elif m == "A":
            self._last_mode = "A"; self._last_unit = "A"
            self.lbl_value.setText(f"{val:.4f}")
            self.lbl_unit.setText("AMPERES")
            self.lbl_value.setStyleSheet(
                f"color: {T.ACCENT_BLUE}; background: transparent; border: none;")
        if getattr(self, "local_logger", None):
            self.local_logger.log({
                "mode": m,
                "value_v": val if m == "V" else "", 
                "value_a": val if m == "A" else ""
            })

    def on_dso_sample(self, value: float):
        self._dso_buf.append(value)
        if self.chk_auto.isChecked() and len(self._dso_buf) == self.DSO_SAMPLES:
            s = self._analytics.stats()
            if s and s.get("vpp", 0) > 0.1:
                self._take_screenshot()

    def get_dso_data(self) -> list:
        return list(self._dso_buf)

    def set_overlay(self, y_data):
        if y_data is None or len(y_data) == 0:
            self._overlay.setData([], [])
            return
        n = len(y_data)
        t = (np.arange(n, dtype=float) - (n - 1)) * self.SAMPLE_PERIOD
        self._overlay.setData(t, np.asarray(y_data, dtype=float))

    # -- Plot Refresh ----------------------------------------------------------

    def _refresh_plot(self):
        data = np.array(self._dso_buf, dtype=float)
        n    = len(data)
        if n == 0:
            return
        if self._eye_mode:
            self._draw_eye_diagram(data)
            self._curve.setData([], [])
        else:
            t = (np.arange(n, dtype=float) - (n - 1)) * self.sample_period
            self._curve.setData(t, data)
            self._apply_timediv()

        if self.chk_cursors.isChecked():
            self._update_cursor_readout()

    def update_theme(self):
        """Called by MainWindow to refresh fonts/colors when theme changes."""
        self.lbl_value.setFont(_mono_font(SZ_BIG, bold=True))
        self.lbl_unit.setFont(_ui_font(SZ_LG))
        self.lbl_unit.setStyleSheet(f"color: {T.TEXT_MUTED}; background: transparent;")
        
        # Refresh plot background if changed
        self.plot_widget.setBackground(T.DARK_BG)
        
        # Refresh any ThemeLabels/Cards (though recursive updater handles this, 
        # local update handles non-standard widgets)

    def _refresh_stats(self):
        s = self._analytics.stats()
        if not s:
            return
        fmts = {
            "MEAN":     f"{s['mean']:.3f} V",
            "STD DEV":  f"{s['std']:.4f} V",
            "MIN":      f"{s['min']:.3f} V",
            "MAX":      f"{s['max']:.3f} V",
            "VRMS":     f"{s['vrms']:.3f} V",
            "VPP":      f"{s['vpp']:.3f} V",
            "DOM FREQ": f"{s['dom_freq']:.1f} Hz",
            "SAMPLES":  str(s["n"]),
        }
        for key, txt in fmts.items():
            if key in self._stat_labels:
                self._stat_labels[key].setText(txt)
