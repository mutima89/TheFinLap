"""Colour tokens and Qt stylesheet for the dark (default) and light themes."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    text2: str
    muted: str
    teal: str
    blue: str
    amber: str
    good: str
    bad: str
    grid: str
    series: tuple[str, ...]


DARK = Palette(
    name="dark", bg="#0E1420", surface="#151D2B", surface2="#1C2636", border="#2A3648", text="#E6EBF2",
    text2="#AEB8C7", muted="#7D8899", teal="#2EC4B6", blue="#4C8DF6", amber="#F2B544", good="#3DD68C",
    bad="#F0616D", grid="#263244",
    series=("#2EC4B6", "#4C8DF6", "#F2B544", "#A78BFA", "#F0616D", "#7DD3FC", "#94A3B8"),
)
LIGHT = Palette(
    name="light", bg="#F3F5F9", surface="#FFFFFF", surface2="#EEF1F6", border="#D5DBE5", text="#14202E",
    text2="#3D4B5E", muted="#6B778A", teal="#0F9488", blue="#2563EB", amber="#B7791F", good="#15803D",
    bad="#C2333F", grid="#E3E7EE",
    series=("#0F9488", "#2563EB", "#B7791F", "#7C3AED", "#C2333F", "#0284C7", "#64748B"),
)
PALETTES = {"dark": DARK, "light": LIGHT}

_current: Palette = DARK


def current() -> Palette:
    return _current


def set_current(name: str) -> Palette:
    global _current
    _current = PALETTES.get(name, DARK)
    return _current


def stylesheet(p: Palette, scale: float = 1.0) -> str:
    fs = int(round(13 * scale))
    return f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", "Helvetica Neue", Arial; font-size: {fs}px; color: {p.text}; }}
QMainWindow, QWidget#Page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p.bg}; }}
QWidget#Sidebar {{ background: {p.surface}; border-right: 1px solid {p.border}; }}
QListWidget#Nav {{ background: transparent; border: none; outline: none; padding: 4px; }}
QListWidget#Nav::item {{ padding: 8px 12px; border-radius: 6px; color: {p.text2}; margin: 1px 4px; }}
QListWidget#Nav::item:selected {{ background: {p.surface2}; color: {p.text}; border-left: 3px solid {p.teal}; }}
QListWidget#Nav::item:hover {{ background: {p.surface2}; }}
QLabel#Brand {{ font-size: {fs + 4}px; font-weight: 700; color: {p.text}; padding: 14px 14px 2px 14px; }}
QLabel#BrandSub {{ color: {p.muted}; padding: 0 14px 10px 14px; font-size: {fs - 2}px; }}
QLabel#H1 {{ font-size: {fs + 9}px; font-weight: 650; }}
QLabel#H2 {{ font-size: {fs + 3}px; font-weight: 600; }}
QLabel#H3 {{ font-size: {fs + 1}px; font-weight: 600; color: {p.text2}; }}
QLabel#Muted {{ color: {p.muted}; }}
QLabel#Good {{ color: {p.good}; }}
QLabel#Bad {{ color: {p.bad}; }}
QLabel#Warn {{ color: {p.amber}; }}
QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#KPI {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; }}
QFrame#KPI:hover {{ border: 1px solid {p.teal}; }}
QLabel#KPIValue {{ font-size: {fs + 8}px; font-weight: 650; font-family: "Segoe UI Semibold", "Inter", "Noto Sans"; }}
QLabel#KPILabel {{ color: {p.muted}; font-size: {fs - 1}px; text-transform: uppercase; }}
QFrame#Banner {{ background: {p.surface2}; border-left: 3px solid {p.amber}; border-radius: 6px; }}
QFrame#TopBar {{ background: {p.surface}; border-bottom: 1px solid {p.border}; }}
QPushButton {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {p.teal}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.muted}; }}
QPushButton#Primary {{ background: {p.teal}; color: {"#06221F" if p.name == "dark" else "#FFFFFF"}; border: none; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {p.blue}; color: #FFFFFF; }}
QPushButton#Danger {{ border-color: {p.bad}; color: {p.bad}; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 6px; padding: 4px 6px; selection-background-color: {p.blue}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {p.teal}; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border}; selection-background-color: {p.surface2}; }}
QTableView, QTreeView, QTreeWidget, QListWidget {{ background: {p.surface}; alternate-background-color: {p.surface2};
    border: 1px solid {p.border}; border-radius: 6px; gridline-color: {p.grid}; selection-background-color: {p.blue}; selection-color: #FFFFFF; }}
QHeaderView::section {{ background: {p.surface2}; color: {p.text2}; border: none; border-bottom: 1px solid {p.border}; padding: 5px 6px; font-weight: 600; }}
QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 8px; background: {p.bg}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {p.text2}; padding: 7px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.teal}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QToolTip {{ background: {p.surface2}; color: {p.text}; border: 1px solid {p.border}; padding: 6px; }}
QSlider::groove:horizontal {{ height: 4px; background: {p.border}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {p.teal}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QProgressBar {{ background: {p.surface2}; border: 1px solid {p.border}; border-radius: 5px; text-align: center; height: 12px; }}
QProgressBar::chunk {{ background: {p.teal}; border-radius: 5px; }}
QGroupBox {{ border: 1px solid {p.border}; border-radius: 8px; margin-top: 14px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {p.text2}; font-weight: 600; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QStatusBar {{ background: {p.surface}; color: {p.muted}; border-top: 1px solid {p.border}; }}
QSplitter::handle {{ background: {p.border}; }}
QMenu {{ background: {p.surface}; border: 1px solid {p.border}; }}
QMenu::item:selected {{ background: {p.surface2}; }}
"""


def mpl_style(p: Palette) -> dict:
    return {
        "figure.facecolor": p.surface, "axes.facecolor": p.surface, "axes.edgecolor": p.border,
        "axes.labelcolor": p.text2, "axes.titlecolor": p.text, "xtick.color": p.muted, "ytick.color": p.muted,
        "grid.color": p.grid, "text.color": p.text, "legend.facecolor": p.surface, "legend.edgecolor": p.border,
        "legend.labelcolor": p.text2, "axes.prop_cycle": __import__("cycler").cycler(color=list(p.series)),
        "font.size": 9, "axes.titlesize": 10, "axes.titleweight": "bold", "axes.spines.top": False,
        "axes.spines.right": False, "axes.grid": True, "grid.linewidth": 0.6,
    }
