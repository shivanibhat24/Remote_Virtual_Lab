"""
themes.py - All colour theme definitions for STM32 Lab GUI v6.0
13 themes: Dark, Cyberpunk, Amber Terminal, Nord, Solarized Dark, Light
           + 7 new: Matrix, Dracula, Ocean, Sunset, Midnight, HighContrast, RetroGreen
"""


class Theme:
    name         = "Dark"
    DARK_BG      = "#080c10"
    PANEL_BG     = "#0d1219"
    CARD_BG      = "#111820"
    BORDER       = "#1e2d3d"
    BORDER_HI    = "#2a4060"
    PRIMARY      = "#00ff88"
    ACCENT_BLUE  = "#00b4ff"
    ACCENT_AMBER = "#ffaa00"
    ACCENT_RED   = "#ff3355"
    ACCENT_PUR   = "#aa55ff"
    ACCENT_CYAN  = "#00e5ff"
    TEXT         = "#c8dae8"
    TEXT_MUTED   = "#4a6080"
    TEXT_DIM     = "#2a3a4a"
    FONT_UI      = "Inter, 'Segoe UI', Roboto, sans-serif"
    FONT_MONO    = "JetBrains Mono, Fira Code, Consolas, monospace"

class CyberpunkTheme(Theme):
    name         = "Cyberpunk"
    DARK_BG      = "#08010f"
    PANEL_BG     = "#0f0520"
    CARD_BG      = "#160830"
    BORDER       = "#2a0f4a"
    BORDER_HI    = "#5010a0"
    PRIMARY      = "#00ffcc"
    ACCENT_BLUE  = "#ff00ff"
    ACCENT_AMBER = "#ffee00"
    ACCENT_RED   = "#ff0055"
    ACCENT_PUR   = "#cc44ff"
    ACCENT_CYAN  = "#00eeff"
    TEXT         = "#e0c8ff"
    TEXT_MUTED   = "#5a3a7a"
    TEXT_DIM     = "#2a1a3a"
    FONT_UI      = "'Inter', 'Segoe UI', sans-serif"
    FONT_MONO    = "'JetBrains Mono', 'Fira Code', monospace"

class HighContrastTheme(Theme):
    name         = "High Contrast"
    DARK_BG      = "#000000"
    PANEL_BG     = "#0a0a0a"
    CARD_BG      = "#111111"
    BORDER       = "#444444"
    BORDER_HI    = "#888888"
    PRIMARY      = "#ffffff"
    ACCENT_BLUE  = "#00aaff"
    ACCENT_AMBER = "#ffcc00"
    ACCENT_RED   = "#ff2222"
    ACCENT_PUR   = "#cc88ff"
    ACCENT_CYAN  = "#00ffff"
    TEXT         = "#ffffff"
    TEXT_MUTED   = "#aaaaaa"
    TEXT_DIM     = "#555555"
    FONT_UI      = "Inter, 'Segoe UI', Roboto, sans-serif"
    FONT_MONO    = "JetBrains Mono, Fira Code, Consolas, monospace"

class ColourBlindTheme(Theme):
    """IBM colour-blind safe palette (deuteranopia/protanopia safe)."""
    name         = "Colour Blind Safe"
    DARK_BG      = "#0a0a0a"
    PANEL_BG     = "#121212"
    CARD_BG      = "#1e1e1e"
    BORDER       = "#333333"
    BORDER_HI    = "#555555"
    PRIMARY      = "#648fff"
    ACCENT_BLUE  = "#785ef0"
    ACCENT_AMBER = "#ffb000"
    ACCENT_RED   = "#fe6100"
    ACCENT_PUR   = "#dc267f"
    ACCENT_CYAN  = "#648fff"
    TEXT         = "#e0e0e0"
    TEXT_MUTED   = "#777777"
    TEXT_DIM     = "#444444"
    FONT_UI      = "Inter, 'Segoe UI', Roboto, sans-serif"
    FONT_MONO    = "JetBrains Mono, Fira Code, Cascadia Code, monospace"

class EverforestTheme(Theme):
    name         = "Everforest"
    DARK_BG      = "#272e33"
    PANEL_BG     = "#2d353b"
    CARD_BG      = "#343f44"
    BORDER       = "#3d484d"
    BORDER_HI    = "#475258"
    PRIMARY      = "#a7c080"
    ACCENT_BLUE  = "#7fbbb3"
    ACCENT_AMBER = "#dbbc7f"
    ACCENT_RED   = "#e67e80"
    ACCENT_PUR   = "#d699b6"
    ACCENT_CYAN  = "#83c092"
    TEXT         = "#d3c6aa"
    TEXT_MUTED   = "#859289"
    TEXT_DIM     = "#4f585e"
    FONT_UI      = "'Inter', 'Segoe UI', sans-serif"
    FONT_MONO    = "'JetBrains Mono', 'Fira Code', monospace"

class RosePineTheme(Theme):
    name         = "Rose Pine"
    DARK_BG      = "#191724"
    PANEL_BG     = "#1f1d2e"
    CARD_BG      = "#26233a"
    BORDER       = "#403d52"
    BORDER_HI    = "#524f67"
    PRIMARY      = "#ebbcba"
    ACCENT_BLUE  = "#31748f"
    ACCENT_AMBER = "#f6c177"
    ACCENT_RED   = "#eb6f92"
    ACCENT_PUR   = "#c4a7e7"
    ACCENT_CYAN  = "#9ccfd8"
    TEXT         = "#e0def4"
    TEXT_MUTED   = "#908caa"
    TEXT_DIM     = "#6e6a86"
    FONT_UI      = "'Outfit', 'Inter', sans-serif"
    FONT_MONO    = "'JetBrains Mono', 'Fira Code', monospace"

class MonokaiProTheme(Theme):
    name         = "Monokai Pro"
    DARK_BG      = "#2d2a2e"
    PANEL_BG     = "#221f22"
    CARD_BG      = "#343034"
    BORDER       = "#403e41"
    BORDER_HI    = "#5b595c"
    PRIMARY      = "#ffd866"
    ACCENT_BLUE  = "#78dce8"
    ACCENT_AMBER = "#ff6188"
    ACCENT_RED   = "#fc9867"
    ACCENT_PUR   = "#ab9df2"
    ACCENT_CYAN  = "#a9dc76"
    TEXT         = "#fcfcfa"
    TEXT_MUTED   = "#939293"
    TEXT_DIM     = "#5b595c"
    FONT_UI      = "'Inter', 'Segoe UI', sans-serif"
    FONT_MONO    = "'JetBrains Mono', 'Fira Code', monospace"

class SynthwaveTheme(Theme):
    name         = "Synthwave '84"
    DARK_BG      = "#262335"
    PANEL_BG     = "#241b2f"
    CARD_BG      = "#2a2139"
    BORDER       = "#44355a"
    BORDER_HI    = "#ff7edb"
    PRIMARY      = "#f92aad"
    ACCENT_BLUE  = "#2de2e6"
    ACCENT_AMBER = "#f8d800"
    ACCENT_RED   = "#fe4450"
    ACCENT_PUR   = "#a06cf8"
    ACCENT_CYAN  = "#3ae9ce"
    TEXT         = "#ffffff"
    TEXT_MUTED   = "#72f1b8"
    TEXT_DIM     = "#34294f"
    FONT_UI      = "'Inter', 'Segoe UI', sans-serif"
    FONT_MONO    = "'JetBrains Mono', 'Cascadia Code', monospace"

class GitHubDimmedTheme(Theme):
    name         = "GitHub Dimmed"
    DARK_BG      = "#22272e"
    PANEL_BG     = "#1c2128"
    CARD_BG      = "#2d333b"
    BORDER       = "#444c56"
    BORDER_HI    = "#545d68"
    PRIMARY      = "#539bf5"
    ACCENT_BLUE  = "#316dca"
    ACCENT_AMBER = "#c69026"
    ACCENT_RED   = "#f47067"
    ACCENT_PUR   = "#b392f0"
    ACCENT_CYAN  = "#39c5bb"
    TEXT         = "#adbac7"
    TEXT_MUTED   = "#768390"
    TEXT_DIM     = "#545d68"
    FONT_UI      = "'Inter', 'Segoe UI', sans-serif"
    FONT_MONO    = "'JetBrains Mono', 'Fira Code', monospace"

class NotebookTheme(Theme):
    name         = "Paper Notebook"
    DARK_BG      = "#fdfaf3"
    PANEL_BG     = "#f5f2e9"
    CARD_BG      = "#ffffff"
    BORDER       = "#e6e3d8"
    BORDER_HI    = "#d6d2c4"
    PRIMARY      = "#1c4e80"
    ACCENT_BLUE  = "#0091d5"
    ACCENT_AMBER = "#ea6a47"
    ACCENT_RED   = "#bc5a45"
    ACCENT_PUR   = "#6e4a9e"
    ACCENT_CYAN  = "#4a86e8"
    TEXT         = "#2c3e50"
    TEXT_MUTED   = "#7f8c8d"
    TEXT_DIM     = "#bdc3c7"
    FONT_UI      = "Georgia, 'Times New Roman', serif"
    FONT_MONO    = "'Consolas', 'Courier New', monospace"


THEMES: dict = {
    "Dark":               Theme,
    "Everforest":         EverforestTheme,
    "Rose Pine":          RosePineTheme,
    "Monokai Pro":        MonokaiProTheme,
    "Synthwave '84":      SynthwaveTheme,
    "GitHub Dimmed":      GitHubDimmedTheme,
    "Paper Notebook":     NotebookTheme,
    "Cyberpunk":          CyberpunkTheme,
    "High Contrast":      HighContrastTheme,
    "Colour Blind Safe":  ColourBlindTheme,
}

# Global mutable theme instance  all widgets read T at paint time
T: Theme = Theme()

def set_theme(cls) -> None:
    for attr in dir(cls):
        if not attr.startswith("__") and not callable(getattr(cls, attr)):
            setattr(T, attr, getattr(cls, attr))
