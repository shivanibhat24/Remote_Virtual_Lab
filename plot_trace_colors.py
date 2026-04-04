"""
plot_trace_colors.py — Per-trace color pickers with theme defaults and persistence.

Uses SettingsManager keys: color_<prefix>_<trace_id> (hex strings, e.g. #55aaff).
"""

from __future__ import annotations

from typing import Callable, List, Optional, Union

import pyqtgraph as pg
from PyQt5.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QColorDialog,
    QSizePolicy,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

from themes import T


PlotItem = Union[pg.PlotDataItem, pg.InfiniteLine]


def _hex_from_theme_attr(attr: str) -> str:
    if attr.startswith("#"):
        return attr
    return str(getattr(T, attr, T.ACCENT_BLUE))


def _apply_pen(
    item: PlotItem,
    hex_color: str,
    width: float = 2.0,
    style: Qt.PenStyle = Qt.SolidLine,
    draw_line: bool = True,
) -> None:
    if draw_line:
        item.setPen(pg.mkPen(hex_color, width=width, style=style))
    else:
        item.setPen(None)
    if isinstance(item, pg.PlotDataItem):
        try:
            item.setSymbolBrush(pg.mkBrush(hex_color))
            item.setSymbolPen(pg.mkPen(hex_color, width=1))
        except Exception:
            pass


class TraceColorBar(QWidget):
    """
    Horizontal row: [Label] [swatch][↺] … for each registered trace.
    """

    def __init__(
        self,
        settings,
        storage_prefix: str,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._settings = settings
        self._prefix = storage_prefix
        self._rows: List[dict] = []
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 4)
        lay.setSpacing(6)
        self._layout = lay

    def _storage_key(self, trace_id: str) -> str:
        return f"color_{self._prefix}_{trace_id}"

    def _load_hex(self, trace_id: str, theme_attr: str) -> str:
        key = self._storage_key(trace_id)
        if self._settings:
            saved = self._settings.get(key)
            if isinstance(saved, str) and saved.startswith("#") and len(saved) >= 4:
                return saved
        return _hex_from_theme_attr(theme_attr)

    def _save_hex(self, trace_id: str, hex_color: str) -> None:
        if self._settings:
            self._settings.set(self._storage_key(trace_id), hex_color)
            self._settings.save()

    def _clear_saved(self, trace_id: str) -> None:
        if self._settings:
            self._settings.remove(self._storage_key(trace_id))
            self._settings.save()

    def add_trace(
        self,
        trace_id: str,
        short_label: str,
        tooltip: str,
        theme_attr: str,
        items: Optional[List[PlotItem]] = None,
        width: float = 2.0,
        style: Qt.PenStyle = Qt.SolidLine,
        draw_line: bool = True,
        extra_items: Optional[Callable[[], List[Optional[PlotItem]]]] = None,
    ) -> None:
        items = items or []
        hex0 = self._load_hex(trace_id, theme_attr)

        def collect() -> List[PlotItem]:
            out: List[PlotItem] = [it for it in items if it is not None]
            if extra_items:
                out.extend([x for x in extra_items() if x is not None])
            return out

        def apply_all(h: str) -> None:
            for it in collect():
                _apply_pen(it, h, width=width, style=style, draw_line=draw_line)

        apply_all(hex0)

        sw = QPushButton(short_label)
        sw.setFixedHeight(22)
        sw.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        sw.setToolTip(tooltip + " — click to pick; ↺ restores theme default")
        sw.setStyleSheet(
            f"QPushButton {{ background-color: {hex0}; color: #202020; "
            f"font-weight: 600; font-size: 10px; padding: 2px 8px; "
            f"border: 1px solid #888; border-radius: 4px; }}"
        )

        def pick():
            qc = QColorDialog.getColor(QColor(hex0), self, tooltip)
            if qc.isValid():
                h = qc.name()
                apply_all(h)
                self._save_hex(trace_id, h)
                sw.setStyleSheet(
                    f"QPushButton {{ background-color: {h}; color: #202020; "
                    f"font-weight: 600; font-size: 10px; padding: 2px 8px; "
                    f"border: 1px solid #888; border-radius: 4px; }}"
                )

        sw.clicked.connect(pick)

        rst = QPushButton("↺")
        rst.setFixedSize(22, 22)
        rst.setToolTip("Theme default")
        theme_hex = _hex_from_theme_attr(theme_attr)

        def reset():
            self._clear_saved(trace_id)
            apply_all(theme_hex)
            sw.setStyleSheet(
                f"QPushButton {{ background-color: {theme_hex}; color: #202020; "
                f"font-weight: 600; font-size: 10px; padding: 2px 8px; "
                f"border: 1px solid #888; border-radius: 4px; }}"
            )

        rst.clicked.connect(reset)

        wrap = QWidget()
        hl = QHBoxLayout(wrap)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)
        hl.addWidget(sw)
        hl.addWidget(rst)
        self._layout.addWidget(wrap)
        self._rows.append(
            {
                "id": trace_id,
                "theme_attr": theme_attr,
                "apply": apply_all,
                "sw": sw,
                "reset": reset,
                "collect": collect,
            }
        )

    def reapply_trace(self, trace_id: str) -> None:
        """Call after a lazy plot item (e.g. external overlay) is created."""
        for row in self._rows:
            if row["id"] != trace_id:
                continue
            h = self._load_hex(trace_id, row["theme_attr"])
            row["apply"](h)
            break

    def refresh_theme_defaults_only(self) -> None:
        """Re-apply theme color for traces with no saved override."""
        for row in self._rows:
            tid = row["id"]
            key = self._storage_key(tid)
            if self._settings and self._settings.get(key):
                continue
            h = _hex_from_theme_attr(row["theme_attr"])
            row["apply"](h)
            sw = row["sw"]
            sw.setStyleSheet(
                f"QPushButton {{ background-color: {h}; color: #202020; "
                f"font-weight: 600; font-size: 10px; padding: 2px 8px; "
                f"border: 1px solid #888; border-radius: 4px; }}"
            )
