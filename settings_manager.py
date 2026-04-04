"""
settings_manager.py - JSON settings persistence for STM32 Lab GUI v6.0

Saves/restores: theme, serial port, all spinbox/combobox values, window geometry.
Path: ~/.stm32lab/settings.json
"""

import json
import os
from pathlib import Path
from typing import Any, Dict

_SETTINGS_DIR  = Path.home() / ".stm32lab"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"


class SettingsManager:
    """Lightweight JSON key-value settings store."""

    def __init__(self):
        _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, Any] = {}
        self.load()
        if "sample_period" not in self._data:
            self._data["sample_period"] = 0.010  # 100 Hz default

    # -- Persistence -----------------------------------------------------------

    def load(self) -> None:
        if _SETTINGS_FILE.exists():
            try:
                with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def save(self) -> None:
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            print(f"[settings] save error: {e}")

    # -- Accessors -------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get_geometry(self) -> dict:
        return self._data.get("window_geometry", {})

    def set_geometry(self, x: int, y: int, w: int, h: int) -> None:
        self._data["window_geometry"] = {"x": x, "y": y, "w": w, "h": h}

    # -- Widget helpers --------------------------------------------------------

    def restore_widget_values(self, widget_map: dict) -> None:
        """
        widget_map: { "key": widget }
        For each key found in settings, calls setValue/setCurrentText on widget.
        """
        from PyQt5.QtWidgets import (QSpinBox, QDoubleSpinBox,
                                     QComboBox, QCheckBox, QLineEdit, QSlider)
        for key, w in widget_map.items():
            val = self._data.get(key)
            if val is None:
                continue
            try:
                if isinstance(w, (QSpinBox, QSlider)):
                    w.setValue(int(val))
                elif isinstance(w, QDoubleSpinBox):
                    w.setValue(float(val))
                elif isinstance(w, QComboBox):
                    idx = w.findText(str(val))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                elif isinstance(w, QCheckBox):
                    w.setChecked(bool(val))
                elif isinstance(w, QLineEdit):
                    w.setText(str(val))
            except Exception:
                pass

    def save_widget_values(self, widget_map: dict) -> None:
        from PyQt5.QtWidgets import (QSpinBox, QDoubleSpinBox,
                                     QComboBox, QCheckBox, QLineEdit, QSlider)
        for key, w in widget_map.items():
            try:
                if isinstance(w, (QSpinBox, QSlider)):
                    self._data[key] = w.value()
                elif isinstance(w, QDoubleSpinBox):
                    self._data[key] = w.value()
                elif isinstance(w, QComboBox):
                    self._data[key] = w.currentText()
                elif isinstance(w, QCheckBox):
                    self._data[key] = w.isChecked()
                elif isinstance(w, QLineEdit):
                    self._data[key] = w.text()
            except Exception:
                pass
