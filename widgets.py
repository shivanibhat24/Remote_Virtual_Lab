"""
widgets.py - Reusable theme-aware widgets for STM32 Lab GUI v6.0
ThemeLabel, ThemeCard, _HeaderStrip, make_header
"""

from PyQt5.QtWidgets import QLabel, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog, QMessageBox
from themes import T
from data_engine import DataLogger
import datetime
from pathlib import Path
from themes  import T
from styles import SZ_XS, SZ_SM, SZ_BODY, SZ_MD, SZ_LG, SZ_STAT, SZ_SETPT, SZ_BIG, _mono_font, _ui_font


class ThemeLabel(QLabel):
    """A QLabel that stores its colour role and re-styles on update_theme()."""
    def __init__(self, text: str, color_attr: str = "TEXT",
                 size: int = SZ_BODY, bold: bool = False, mono: bool = False):
        super().__init__(text)
        self._color_attr = color_attr
        self._size       = size
        self._bold       = bold
        self._mono       = mono
        self.update_theme()

    def update_theme(self):
        col = getattr(T, self._color_attr, T.TEXT)
        ff  = T.FONT_MONO if self._mono else T.FONT_UI
        wt  = "font-weight: bold;" if self._bold else "font-weight: normal;"
        self.setStyleSheet(
            f"color: {col}; font-size: {self._size}px; {wt} font-family: {ff};"
        )


class ThemeCard(QWidget):
    """Stat card with title label + value label; re-styles on update_theme()."""
    def __init__(self, label_text: str, value_label: QLabel,
                 value_color_attr: str = "PRIMARY"):
        super().__init__()
        self._value_label      = value_label
        self._value_color_attr = value_color_attr
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)
        self._lbl = QLabel(label_text.upper())
        lay.addWidget(self._lbl)
        lay.addWidget(value_label)
        self.update_theme()

    def update_theme(self):
        self.setStyleSheet(
            f"QWidget {{ background: {T.CARD_BG}; border: 1px solid {T.BORDER}; }}"
        )
        self._lbl.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; font-weight: 700; "
            f"font-family: {T.FONT_UI}; background: transparent; border: none;"
        )
        col = getattr(T, self._value_color_attr, T.PRIMARY)
        self._value_label.setStyleSheet(
            f"color: {col}; font-size: {SZ_STAT}px; font-weight: 700; "
            f"font-family: {T.FONT_MONO}; background: transparent; border: none;"
        )


class _HeaderStrip(QWidget):
    """Horizontal header bar with a title on the left and optional widgets."""
    def __init__(self, title: str):
        super().__init__()
        self._title = title
        self.setFixedHeight(48)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(16, 0, 16, 0)
        self._lbl = QLabel(title.upper())
        self._lay.addWidget(self._lbl)
        self._lay.addStretch()
        self.update_theme()

    def layout(self):           # expose the internal layout
        return self._lay

    def update_theme(self):
        self.setStyleSheet(
            f"background: {T.PANEL_BG}; border-bottom: 1px solid {T.BORDER};"
        )
        self._lbl.setStyleSheet(
            f"color: {T.TEXT_MUTED}; font-size: {SZ_SM}px; "
            f"font-weight: 700; font-family: {T.FONT_UI};"
        )


def make_header(title: str) -> tuple:
    """Returns (strip_widget, layout) - layout pre-populated with title label."""
    w = _HeaderStrip(title)
    return w, w.layout()


class LocalLoggerWidget(QWidget):
    """A compact recording widget that binds to its own dynamic DataLogger."""
    def __init__(self, filename_prefix: str, fieldnames: list[str]):
        super().__init__()
        self._prefix = filename_prefix
        self._logger = DataLogger(fieldnames)
        
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        
        self.btn_rec = QPushButton("[ RECORD CSV ]")
        self.btn_rec.clicked.connect(self._toggle_rec)
        # Give it a small fixed width so it looks consistently like a toggle button
        self.btn_rec.setFixedWidth(140)
        lay.addWidget(self.btn_rec)
        
    def _toggle_rec(self):
        if not self._logger.is_active:
            dir_path = Path.home() / "stm32lab" / "logs"
            dir_path.mkdir(parents=True, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Isolated CSV",
                str(dir_path / f"{self._prefix}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"),
                "CSV Files (*.csv);;All Files (*)"
            )
            if path:
                try:
                    self._logger.start(path)
                    self.btn_rec.setText("[ STOP RECORDING ]")
                    self.btn_rec.setStyleSheet(f"color: {T.ACCENT_RED}; font-weight: bold; border: 1px solid {T.ACCENT_RED};")
                except Exception as e:
                    QMessageBox.critical(self, "Logger Error", str(e))
        else:
            self._logger.stop()
            self.btn_rec.setText("[ RECORD CSV ]")
            self.btn_rec.setStyleSheet("")

    def log(self, data_dict: dict):
        if self._logger.is_active:
            self._logger.log_dict(data_dict)
            
    def update_theme(self):
        if not self._logger.is_active:
            self.btn_rec.setStyleSheet("")
