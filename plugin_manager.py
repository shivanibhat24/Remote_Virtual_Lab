"""
plugin_manager.py - Drop-in plugin/extension system for STM32 Lab GUI v6.0

Place a .py file in ~/stm32lab/plugins/ exposing:
    plugin_info() -> dict   e.g. {"name": "My Plugin", "version": "1.0"}
    create_tab(main_window) -> QWidget

The PluginManager scans the directory on startup and on hot-reload, and
injects each plugin's tab into the QTabWidget.
"""

import importlib.util
import sys
import traceback
from pathlib import Path
from typing import List, Tuple

from PyQt5.QtWidgets import QWidget, QStackedWidget, QListWidget, QListWidgetItem
from PyQt5.QtCore import Qt

PLUGIN_DIR = Path.home() / "stm32lab" / "plugins"


class PluginManager:
    """Discovers, loads, and manages plugin tabs."""

    def __init__(self, sidebar: QListWidget, stacked: QStackedWidget, main_window):
        self._sidebar    = sidebar
        self._stacked    = stacked
        self._main       = main_window
        self._loaded:    List[Tuple[str, int, QListWidgetItem]] = []   # (name, tab_index, item)
        PLUGIN_DIR.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> List[str]:
        """Scan plugin dir and load every .py that hasn't been loaded yet."""
        log = []
        for py_file in sorted(PLUGIN_DIR.glob("*.py")):
            name = py_file.stem
            if any(n == name for n, _, _ in self._loaded):
                continue
            result = self._load_one(py_file)
            log.append(result)
        return log

    def reload_all(self) -> List[str]:
        """Remove all plugin tabs and reload from disk."""
        # Remove in reverse index order to avoid index shifting
        for name, idx, item in reversed(self._loaded):
            if 0 <= idx < self._stacked.count():
                widget = self._stacked.widget(idx)
                self._stacked.removeWidget(widget)
                widget.deleteLater()
                row = self._sidebar.row(item)
                self._sidebar.takeItem(row)
        self._loaded.clear()
        # Purge from sys.modules
        for key in list(sys.modules.keys()):
            if key.startswith("stm32_plugin_"):
                del sys.modules[key]
        return self.load_all()

    def _load_one(self, py_file: Path) -> str:
        module_name = f"stm32_plugin_{py_file.stem}"
        try:
            spec   = importlib.util.spec_from_file_location(module_name, py_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            info = module.plugin_info() if hasattr(module, "plugin_info") else {}
            tab_name = info.get("name", py_file.stem)

            if hasattr(module, "create_tab"):
                widget = module.create_tab(self._main)
                if isinstance(widget, QWidget):
                    self._stacked.addWidget(widget)
                    item = QListWidgetItem("  [Plug] " + tab_name)
                    idx = self._stacked.count() - 1
                    item.setData(Qt.UserRole, idx)
                    self._sidebar.addItem(item)
                    self._loaded.append((py_file.stem, idx, item))
                    return f"[SUCCESS] Plugin loaded: {tab_name}"
            return f"[WARNING] Plugin {py_file.stem}: no create_tab()"
        except Exception:
            return f"[ERROR] Plugin {py_file.stem} error:\n{traceback.format_exc()}"

    @property
    def plugin_dir(self) -> Path:
        return PLUGIN_DIR

    def status(self) -> str:
        if not self._loaded:
            return f"0 plugins  (dir: {PLUGIN_DIR})"
        names = ", ".join(n for n, _, _ in self._loaded)
        return f"{len(self._loaded)} plugin(s): {names}"
