"""Blue Cench Chat design system: palettes, typography and the global QSS."""
from __future__ import annotations

from dataclasses import dataclass

FONT_STACK = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif'


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    sidebar: str
    surface: str
    surface2: str
    surface3: str
    border: str
    border_strong: str
    text: str
    muted: str
    faint: str
    primary: str
    primary_hover: str
    primary_soft: str
    cyan: str
    success: str
    warning: str
    danger: str
    bubble_out: str
    bubble_in: str
    on_primary: str = "#FFFFFF"


# Instagram-inspired: crisp white by default, true-black dark mode.
LIGHT = Palette(
    name="light",
    bg="#FFFFFF", sidebar="#FFFFFF", surface="#FFFFFF", surface2="#FAFAFA", surface3="#EFEFEF",
    border="#DBDBDB", border_strong="#C7C7C7",
    text="#0C1014", muted="#737373", faint="#A8A8A8",
    primary="#0095F6", primary_hover="#1877F2", primary_soft="#E0F1FF",
    cyan="#0095F6", success="#16A34A", warning="#E7790B", danger="#ED4956",
    bubble_out="#3797F0", bubble_in="#EFEFEF",
)

DARK = Palette(
    name="dark",
    bg="#000000", sidebar="#000000", surface="#121212", surface2="#1A1A1A", surface3="#262626",
    border="#262626", border_strong="#363636",
    text="#F5F5F5", muted="#A8A8A8", faint="#737373",
    primary="#0095F6", primary_hover="#1877F2", primary_soft="#0B2A44",
    cyan="#4CB5F9", success="#22C55E", warning="#F5A524", danger="#ED4956",
    bubble_out="#3797F0", bubble_in="#262626",
)

# Blue Cench signature: deep navy with electric-blue neon (from the brand showcase)
MIDNIGHT = Palette(
    name="midnight",
    bg="#060E24", sidebar="#08132E", surface="#0B1A3A", surface2="#0F2147", surface3="#162B57",
    border="#1B2F5C", border_strong="#27407A",
    text="#EAF2FF", muted="#9DB2D9", faint="#6A80AD",
    primary="#1E8BFF", primary_hover="#43A2FF", primary_soft="#10306A",
    cyan="#22D3EE", success="#22C55E", warning="#F5A524", danger="#FF5A6E",
    bubble_out="#1E8BFF", bubble_in="#132651",
)

THEMES = {"light": LIGHT, "dark": DARK, "midnight": MIDNIGHT}
THEME_NAMES = [("light", "Light"), ("dark", "Dark"), ("midnight", "Midnight Blue (signature)")]
BRAND_GRADIENT = "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1E6BFF, stop:1 #00C2FF)"

VERIFIED_BLUE = "#0095F6"
STORY_GRADIENT = "qlineargradient(x1:0, y1:1, x2:1, y2:0, stop:0 #FEDA75, stop:0.3 #FA7E1E, stop:0.55 #D62976, stop:0.8 #962FBF, stop:1 #4F5BD5)"

_current: Palette = LIGHT
REDUCE_MOTION = False
_scale = 1.0


def palette() -> Palette:
    return _current


def set_theme(name: str, font_scale: int = 100) -> Palette:
    global _current, _scale
    _current = THEMES.get(name, LIGHT)
    _scale = max(0.85, min(1.5, font_scale / 100))
    return _current


def px(size: float) -> int:
    return round(size * _scale)


def stylesheet() -> str:
    p = _current
    s = px
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: {s(13)}px;
    color: {p.text};
    outline: none;
}}
QMainWindow, QDialog, #AuthRoot {{ background: {p.bg}; }}
QWidget#Page, QWidget#PageInner, QStackedWidget#Pages {{ background: {p.bg}; }}
QToolTip {{
    background: {p.surface3}; color: {p.text}; border: 1px solid {p.border_strong};
    padding: 6px 8px; border-radius: 6px;
}}

/* ---------- typography ---------- */
QLabel[role="h1"] {{ font-size: {s(26)}px; font-weight: 700; letter-spacing: -0.3px; }}
QLabel[role="h2"] {{ font-size: {s(18)}px; font-weight: 650; }}
QLabel[role="h3"] {{ font-size: {s(14)}px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {p.muted}; }}
QLabel[role="faint"] {{ color: {p.faint}; font-size: {s(12)}px; }}
QLabel[role="eyebrow"] {{ color: {p.cyan}; font-size: {s(11)}px; font-weight: 700; letter-spacing: 1.2px; }}
QLabel[role="stat"] {{ font-size: {s(26)}px; font-weight: 700; }}
QLabel[role="mono"] {{ font-family: "Cascadia Mono", Consolas, "DejaVu Sans Mono", monospace; font-size: {s(13)}px; }}
QLabel[role="safety"] {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: {s(24)}px; font-weight: 600;
    color: {p.cyan}; letter-spacing: 2px; }}
QLabel[role="error"] {{ color: {p.danger}; }}
QLabel[role="success"] {{ color: {p.success}; }}
QLabel[role="warning"] {{ color: {p.warning}; }}
QLabel[role="link"] {{ color: {p.primary}; }}

/* ---------- sidebar ---------- */
#Sidebar {{ background: {p.sidebar}; border-right: 1px solid {p.border}; }}
#SidebarBrand {{ font-size: {s(17)}px; font-weight: 800; letter-spacing: 0.5px; }}
QPushButton#NavButton {{
    text-align: left; padding: 9px 12px; border: none; border-radius: 9px;
    background: transparent; color: {p.muted}; font-weight: 500;
}}
QPushButton#NavButton:hover {{ background: {p.surface2}; color: {p.text}; }}
QPushButton#NavButton:checked {{ background: {p.primary_soft}; color: {p.text}; font-weight: 600; }}
#NavBadge {{ background: {p.primary}; color: white; border-radius: 9px; padding: 1px 6px;
    font-size: {s(11)}px; font-weight: 700; }}
#TopBar {{ background: {p.bg}; border-bottom: 1px solid {p.border}; }}

/* ---------- cards ---------- */
QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame#Card[accent="true"] {{ border: 1px solid {p.border_strong}; }}
QFrame#SoftCard {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 12px; }}
QFrame#Hero {{
    border-radius: 16px; border: 1px solid {p.border};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.primary_soft}, stop:1 {p.surface});
}}
QFrame#PostCard {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}
QLabel#StoryRing {{ border-radius: 34px; padding: 3px; background: {STORY_GRADIENT}; }}
QLabel#Tick {{ background: transparent; }}
QPushButton[variant="follow"] {{ background: {p.primary}; border: none; color: white; border-radius: 8px;
    padding: 6px 16px; }}
QPushButton[variant="follow"]:hover {{ background: {p.primary_hover}; }}
QPushButton[variant="following"] {{ background: {p.surface3}; border: none; color: {p.text}; border-radius: 8px;
    padding: 6px 16px; }}
QFrame#CallWindow {{ background: #0C1014; }}
QFrame#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {p.surface3}; border: 1px solid transparent; border-radius: 8px;
    padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {p.border}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.faint}; background: {p.surface}; border-color: {p.border}; }}
QPushButton[variant="primary"] {{ background: {p.primary}; border: 1px solid {p.primary}; color: {p.on_primary}; }}
QPushButton[variant="primary"]:hover {{ background: {p.primary_hover}; border-color: {p.primary_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {p.primary_soft}; border-color: {p.primary_soft}; color: {p.muted}; }}
QPushButton[variant="danger"] {{ background: transparent; border: 1px solid {p.danger}; color: {p.danger}; }}
QPushButton[variant="danger"]:hover {{ background: {p.danger}; color: white; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {p.muted}; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface2}; color: {p.text}; }}
QPushButton[variant="link"] {{ background: transparent; border: none; color: {p.primary}; padding: 2px; font-weight: 600; }}
QPushButton[variant="link"]:hover {{ text-decoration: underline; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
QToolButton:hover {{ background: {p.surface3}; }}
QToolButton:checked {{ background: {p.primary_soft}; }}

/* ---------- inputs ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px;
    padding: 9px 11px; selection-background-color: {p.primary};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {{
    border: 1px solid {p.primary};
}}
QLineEdit[invalid="true"] {{ border: 1px solid {p.danger}; }}
QLineEdit:disabled {{ color: {p.faint}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {p.surface2}; border: 1px solid {p.border_strong};
    selection-background-color: {p.primary_soft}; padding: 4px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {p.border_strong};
    background: {p.surface2}; }}
QCheckBox::indicator:checked {{ background: {p.primary}; border-color: {p.primary}; }}

/* ---------- lists / tables ---------- */
QListWidget, QTreeWidget, QTableWidget {{
    background: transparent; border: none;
}}
QListWidget::item {{ border-radius: 10px; padding: 0px; margin: 1px 0; }}
QListWidget::item:selected {{ background: {p.primary_soft}; }}
QListWidget::item:hover:!selected {{ background: {p.surface2}; }}
QHeaderView::section {{ background: {p.surface}; color: {p.muted}; border: none;
    border-bottom: 1px solid {p.border}; padding: 8px; font-weight: 600; }}
QTableWidget {{ gridline-color: {p.border}; }}
QTableWidget::item {{ padding: 6px; border-bottom: 1px solid {p.border}; }}
QTableWidget::item:selected {{ background: {p.primary_soft}; color: {p.text}; }}

/* ---------- progress / scroll ---------- */
QProgressBar {{ background: {p.surface3}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 4px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.primary}, stop:1 {p.cyan}); }}
QProgressBar[state="done"]::chunk {{ background: {p.success}; }}
QProgressBar[state="error"]::chunk {{ background: {p.danger}; }}
QProgressBar[state="paused"]::chunk {{ background: {p.warning}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p.faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- pills ---------- */
QLabel#Pill {{ border-radius: 10px; padding: 3px 9px; font-size: {s(11)}px; font-weight: 700; }}
QLabel#Pill[tone="neutral"] {{ background: {p.surface3}; color: {p.muted}; }}
QLabel#Pill[tone="primary"] {{ background: {p.primary_soft}; color: {p.primary_hover}; }}
QLabel#Pill[tone="success"] {{ background: rgba(34,197,94,0.14); color: {p.success}; }}
QLabel#Pill[tone="warning"] {{ background: rgba(245,165,36,0.15); color: {p.warning}; }}
QLabel#Pill[tone="danger"]  {{ background: rgba(240,79,95,0.15); color: {p.danger}; }}
QLabel#Pill[tone="cyan"]    {{ background: rgba(34,211,238,0.13); color: {p.cyan}; }}

/* ---------- chat ---------- */
QFrame#BubbleOut {{ border-radius: 18px; border-bottom-right-radius: 6px;
    background: {BRAND_GRADIENT}; }}
QFrame#BubbleIn {{ background: {p.bubble_in}; border: none; border-radius: 18px;
    border-bottom-left-radius: 6px; }}
QFrame#BubbleOut QLabel {{ color: #FFFFFF; }}
QFrame#ReplyQuote {{ background: rgba(0,0,0,0.18); border-left: 3px solid {p.cyan}; border-radius: 6px; }}
QFrame#Composer {{ background: {p.surface}; border-top: 1px solid {p.border}; }}
QFrame#ChatHeader {{ background: {p.surface}; border-bottom: 1px solid {p.border}; }}
QFrame#DropZone {{ border: 2px dashed {p.border_strong}; border-radius: 16px; background: {p.surface}; }}
QFrame#DropZone[active="true"] {{ border-color: {p.primary}; background: {p.primary_soft}; }}
QMenu {{ background: {p.surface2}; border: 1px solid {p.border_strong}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.primary_soft}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}
QTabBar::tab {{ background: transparent; color: {p.muted}; padding: 8px 14px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.primary}; }}
QTabWidget::pane {{ border: none; }}
#Toast {{ background: {p.surface3}; border: 1px solid {p.border_strong}; border-radius: 12px; }}
"""
