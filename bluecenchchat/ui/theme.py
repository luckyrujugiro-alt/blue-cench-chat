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


DARK = Palette(
    name="dark",
    bg="#070B14", sidebar="#0A1020", surface="#0E1526", surface2="#131C30", surface3="#1A2540",
    border="#1C2742", border_strong="#2A3A5E",
    text="#E7EEF9", muted="#8C9AB6", faint="#5E6B86",
    primary="#2F7BFF", primary_hover="#4A8DFF", primary_soft="#13264D",
    cyan="#22D3EE", success="#22C55E", warning="#F5A524", danger="#F04F5F",
    bubble_out="#1D4ED8", bubble_in="#16203A",
)

LIGHT = Palette(
    name="light",
    bg="#F3F6FB", sidebar="#FFFFFF", surface="#FFFFFF", surface2="#F1F4FA", surface3="#E7ECF5",
    border="#DFE5F0", border_strong="#C9D3E4",
    text="#0E1726", muted="#56637A", faint="#8D98AD",
    primary="#2563EB", primary_hover="#1D4ED8", primary_soft="#E3ECFF",
    cyan="#0891B2", success="#16A34A", warning="#D97706", danger="#DC2626",
    bubble_out="#2563EB", bubble_in="#EEF2F8",
)

_current: Palette = DARK
REDUCE_MOTION = False
_scale = 1.0


def palette() -> Palette:
    return _current


def set_theme(name: str, font_scale: int = 100) -> Palette:
    global _current, _scale
    _current = LIGHT if name == "light" else DARK
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
    border-radius: 16px; border: 1px solid {p.border_strong};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.primary_soft}, stop:1 {p.surface});
}}
QFrame#Divider {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px;
    padding: 8px 14px; font-weight: 600;
}}
QPushButton:hover {{ background: {p.surface3}; border-color: {p.border_strong}; }}
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
QFrame#BubbleOut {{ background: {p.bubble_out}; border-radius: 14px; border-bottom-right-radius: 4px; }}
QFrame#BubbleIn {{ background: {p.bubble_in}; border: 1px solid {p.border}; border-radius: 14px;
    border-bottom-left-radius: 4px; }}
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
