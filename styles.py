"""
styles.py  Stylesheet builder + font constants for STM32 Lab GUI v4.0
All colours are sourced from the live global T (themes.T).
"""

from themes import T


#  Font stacks (Moved to themes.py)

#  Named sizes 
SZ_XS   = 10
SZ_SM   = 11
SZ_BODY = 13
SZ_MD   = 14
SZ_LG   = 16
SZ_STAT = 24
SZ_SETPT= 34
SZ_BIG  = 52

from PyQt5.QtGui import QFont

def _mono_font(pt_size: int, bold: bool = False) -> QFont:
    """Return a QFont using the theme's preferred mono family."""
    f = QFont()
    # Use the first family in the stack
    family = T.FONT_MONO.split(',')[0].strip().replace("'", "").replace("\"", "")
    f.setFamily(family)
    f.setPointSize(pt_size)
    f.setBold(bold)
    return f


def _ui_font(pt_size: int, bold: bool = False) -> QFont:
    """Return a QFont using the theme's preferred UI family."""
    f = QFont()
    # Use the first family in the stack
    family = T.FONT_UI.split(',')[0].strip().replace("'", "").replace("\"", "")
    f.setFamily(family)
    f.setPointSize(pt_size)
    f.setBold(bold)
    return f


def build_stylesheet() -> str:
    """Build a complete Qt stylesheet from the current theme T."""
    return f"""
* {{ outline: none; font-family: {T.FONT_UI}; font-size: {SZ_BODY}px; color: {T.TEXT}; }}

QMainWindow, QDialog {{ background: {T.DARK_BG}; }}
QWidget {{ background: {T.DARK_BG}; color: {T.TEXT}; }}

/*  Tabs  */
QTabWidget::pane {{ border: 1px solid {T.BORDER}; background: {T.DARK_BG}; border-top: none; }}
QTabBar {{ background: {T.DARK_BG}; }}
QTabBar::tab {{
    background: {T.DARK_BG}; color: {T.TEXT_MUTED};
    border: 1px solid {T.BORDER}; border-bottom: none;
    padding: 8px 16px; margin-right: 2px;
    font-size: {SZ_SM}px; font-weight: 700; min-width: 90px;
}}
QTabBar::tab:selected {{
    background: {T.PANEL_BG}; color: {T.PRIMARY};
    border-top: 2px solid {T.PRIMARY}; border-bottom: 1px solid {T.PANEL_BG};
}}
QTabBar::tab:hover:!selected {{ color: {T.TEXT}; background: {T.CARD_BG}; }}

/*  Buttons  */
QPushButton {{
    background: transparent; color: {T.PRIMARY}; border: 1px solid {T.PRIMARY};
    border-radius: 3px; padding: 8px 20px;
    font-size: {SZ_SM}px; font-weight: 700; font-family: {T.FONT_UI};
}}
QPushButton:hover  {{ background: {T.PRIMARY}; color: {T.DARK_BG}; }}
QPushButton:pressed {{ background: {T.ACCENT_BLUE}; color: {T.DARK_BG}; }}
QPushButton:disabled {{ color: {T.TEXT_DIM}; border-color: {T.TEXT_DIM}; }}
QPushButton#btn_connect    {{ color: {T.ACCENT_BLUE}; border-color: {T.ACCENT_BLUE}; }}
QPushButton#btn_connect:hover {{ background: {T.ACCENT_BLUE}; color: {T.DARK_BG}; }}
QPushButton#btn_disconnect {{ color: {T.ACCENT_RED}; border-color: {T.ACCENT_RED}; }}
QPushButton#btn_disconnect:hover {{ background: {T.ACCENT_RED}; color: {T.DARK_BG}; }}
QPushButton#btn_warning    {{ color: {T.ACCENT_AMBER}; border-color: {T.ACCENT_AMBER}; }}
QPushButton#btn_warning:hover {{ background: {T.ACCENT_AMBER}; color: {T.DARK_BG}; }}
QPushButton#btn_pid        {{ color: {T.ACCENT_PUR}; border-color: {T.ACCENT_PUR}; }}
QPushButton#btn_pid:hover  {{ background: {T.ACCENT_PUR}; color: {T.DARK_BG}; }}

/*  Inputs  */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {T.CARD_BG}; color: {T.TEXT}; border: 1px solid {T.BORDER};
    border-radius: 3px; padding: 6px 10px; font-size: {SZ_MD}px; min-height: 28px;
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border-color: {T.ACCENT_BLUE};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {T.CARD_BG}; color: {T.TEXT};
    border: 1px solid {T.BORDER_HI}; selection-background-color: {T.BORDER_HI};
    font-size: {SZ_MD}px;
}}

/*  Slider  */
QSlider::groove:horizontal {{ background: {T.BORDER}; height: 4px; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {T.ACCENT_BLUE}; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px; border: 2px solid {T.DARK_BG};
}}
QSlider::sub-page:horizontal {{ background: {T.ACCENT_BLUE}; border-radius: 2px; }}

/*  Text areas  */
QTextEdit {{
    background: {T.DARK_BG}; color: {T.PRIMARY};
    border: 1px solid {T.BORDER};
    font-family: {T.FONT_MONO}; font-size: {SZ_BODY}px;
    selection-background-color: {T.BORDER_HI};
}}

/*  Group boxes  */
QGroupBox {{
    border: 1px solid {T.BORDER}; margin-top: 20px;
    font-size: {SZ_SM}px; font-weight: 700; color: {T.TEXT_MUTED};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 8px; }}

/*  Checkbox  */
QCheckBox {{ color: {T.TEXT}; spacing: 8px; font-size: {SZ_BODY}px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {T.BORDER_HI}; background: {T.CARD_BG}; border-radius: 3px;
}}
QCheckBox::indicator:checked {{ background: {T.PRIMARY}; border-color: {T.PRIMARY}; }}

/*  Scrollbar  */
QScrollBar:vertical {{ background: {T.DARK_BG}; width: 7px; border: none; }}
QScrollBar::handle:vertical {{ background: {T.BORDER_HI}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/*  Status bar  */
QStatusBar {{
    background: {T.PANEL_BG}; color: {T.TEXT_MUTED};
    border-top: 1px solid {T.BORDER};
    font-size: {SZ_SM}px; font-family: {T.FONT_MONO};
}}

/*  Splitter  */
QSplitter::handle {{ background: {T.BORDER}; width: 1px; height: 1px; }}

/*  Progress bar  */
QProgressBar {{
    background: {T.CARD_BG}; border: 1px solid {T.BORDER}; border-radius: 3px;
    text-align: center; color: {T.TEXT}; font-size: {SZ_SM}px;
}}
QProgressBar::chunk {{ background: {T.PRIMARY}; border-radius: 2px; }}

/*  Menu  */
QMenuBar {{
    background: {T.PANEL_BG}; color: {T.TEXT};
    border-bottom: 1px solid {T.BORDER}; font-size: {SZ_BODY}px; padding: 2px;
    font-family: {T.FONT_UI};
}}
QMenuBar::item:selected {{ background: {T.BORDER_HI}; border-radius: 3px; }}
QMenu {{
    background: {T.CARD_BG}; color: {T.TEXT};
    border: 1px solid {T.BORDER_HI}; font-size: {SZ_BODY}px; padding: 4px 0;
}}
QMenu::item {{ padding: 8px 24px; }}
QMenu::item:selected {{ background: {T.BORDER_HI}; }}
QMenu::separator {{ height: 1px; background: {T.BORDER}; margin: 4px 0; }}

/*  List widget (Sidebar)  */
QListWidget {{
    background: {T.PANEL_BG}; color: {T.TEXT_MUTED};
    border: none; border-right: 1px solid {T.BORDER};
    font-size: {SZ_BODY}px; outline: none; padding: 4px;
}}
QListWidget::item {{
    padding: 10px 16px; margin: 2px 4px; border-radius: 6px;
}}
QListWidget::item:selected {{
    background: {T.BORDER_HI}; color: {T.PRIMARY}; font-weight: 700;
}}
QListWidget::item:hover:!selected {{
    background: {T.CARD_BG}; color: {T.TEXT};
}}

/*  Table widget  */
QTableWidget {{
    background: {T.CARD_BG}; color: {T.TEXT};
    border: 1px solid {T.BORDER}; gridline-color: {T.BORDER};
    font-size: {SZ_SM}px;
}}
QTableWidget::item:selected {{ background: {T.BORDER_HI}; }}
QHeaderView::section {{
    background: {T.PANEL_BG}; color: {T.TEXT_MUTED};
    border: 1px solid {T.BORDER}; padding: 4px 8px;
    font-size: {SZ_SM}px; font-weight: 700;
}}
"""
