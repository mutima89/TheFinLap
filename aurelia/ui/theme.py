"""Design tokens, bundled fonts and the Qt stylesheet for the dark (default) and light themes.

The look is "grand hotel at night": warm ink surfaces, a champagne-gold accent, a serif display face
(Fraunces) for titles and a clean grotesque (Manrope) with tabular figures for everything else.
Both fonts ship in ``aurelia/assets/fonts`` under the SIL Open Font License.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

UI_FONT = "Manrope"
DISPLAY_FONT = "Fraunces"
FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str           # window ground
    surface: str      # cards
    surface2: str     # inputs, hovered rows, secondary panels
    border: str
    text: str
    text2: str
    muted: str
    teal: str         # primary accent (champagne gold); the name is kept for older call sites
    blue: str         # informational / secondary series
    amber: str        # warnings, budget markers
    good: str         # favourable
    bad: str          # unfavourable
    grid: str
    series: tuple[str, ...]
    side: str = "#0A0C11"         # sidebar ground
    surface3: str = "#1A1F29"     # selected nav item, raised controls
    on_accent: str = "#14110A"    # text on the gold accent
    accent_soft: str = "#2A2416"  # tinted gold background
    hero_a: str = "#2A2416"       # hero gradient stops
    hero_b: str = "#151820"
    good_soft: str = "#16302A"
    bad_soft: str = "#33211A"

    @property
    def gold(self) -> str:
        return self.teal


DARK = Palette(
    name="dark", bg="#0D1016", surface="#141820", surface2="#1A1F29", border="#232A36", text="#ECE7DC",
    text2="#B9BFCB", muted="#8A92A0", teal="#D9B66F", blue="#7FA7E8", amber="#E9A04F", good="#6CC4A1",
    bad="#E8735A", grid="#1F2530",
    series=("#D9B66F", "#7FA7E8", "#6CC4A1", "#C39BE0", "#E8735A", "#7FD1E0", "#9AA1AE"),
    side="#0A0C11", surface3="#1E2430", on_accent="#14110A", accent_soft="#2A2416", hero_a="#2C2516",
    hero_b="#151820", good_soft="#15302A", bad_soft="#36221B",
)
LIGHT = Palette(
    name="light", bg="#F6F3EC", surface="#FFFFFF", surface2="#F2EDE3", border="#E4DCCB", text="#1A1D24",
    text2="#424957", muted="#6E7583", teal="#A67C2E", blue="#2F62C2", amber="#B86A12", good="#1F8A63",
    bad="#C2502F", grid="#EDE6D8",
    series=("#A67C2E", "#2F62C2", "#1F8A63", "#7B4DB3", "#C2502F", "#13839A", "#6E7583"),
    side="#FBF9F4", surface3="#F0E8D8", on_accent="#FFFFFF", accent_soft="#F4EAD3", hero_a="#F3E6C8",
    hero_b="#FFFFFF", good_soft="#E2F2EA", bad_soft="#F8E5DD",
)
PALETTES = {"dark": DARK, "light": LIGHT}

_current: Palette = DARK
_fonts_loaded = False


def current() -> Palette:
    return _current


def set_current(name: str) -> Palette:
    global _current
    _current = PALETTES.get(name, DARK)
    return _current


def load_fonts() -> bool:
    """Register the bundled fonts with Qt (needs a QGuiApplication) and Matplotlib. Safe to call twice."""
    global _fonts_loaded
    if _fonts_loaded:
        return True
    from PySide6.QtGui import QFontDatabase
    ok = True
    for f in sorted(FONT_DIR.glob("*.ttf")):
        ok &= QFontDatabase.addApplicationFont(str(f)) != -1
        try:
            from matplotlib import font_manager
            font_manager.fontManager.addfont(str(f))
        except Exception:  # noqa: BLE001 – charts fall back to the default font
            pass
    _fonts_loaded = ok
    return ok


def ui_font(size: float = 13.5, weight: int = 400):
    from PySide6.QtGui import QFont
    f = QFont(UI_FONT)
    f.setPixelSize(max(1, int(round(size))))
    f.setWeight(QFont.Weight(weight))
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def display_font(size: float = 24, weight: int = 400):
    from PySide6.QtGui import QFont
    f = QFont(DISPLAY_FONT)
    f.setPixelSize(max(1, int(round(size))))
    f.setWeight(QFont.Weight(weight))
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def stylesheet(p: Palette, scale: float = 1.0) -> str:
    fs = int(round(13.5 * scale))
    ui = f'"{UI_FONT}", "Segoe UI", "Noto Sans", Arial'
    disp = f'"{DISPLAY_FONT}", Georgia, "Times New Roman", serif'
    dark = p.name == "dark"
    sel = "#2B3550" if dark else "#E9DFC8"
    return f"""
* {{ font-family: {ui}; font-size: {fs}px; color: {p.text}; }}
QMainWindow, QWidget#Page, QStackedWidget, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {p.bg}; }}
QWidget#PageBody {{ background: {p.bg}; }}

/* ---- sidebar ---------------------------------------------------------------------------- */
QWidget#Sidebar {{ background: {p.side}; border-right: 1px solid {p.border}; }}
QLabel#Brand {{ font-family: {disp}; font-size: {fs + 6}px; color: {p.text}; }}
QLabel#BrandSub {{ color: {p.muted}; font-size: {fs - 3}px; letter-spacing: 1.5px; }}
QListWidget#Nav {{ background: transparent; border: none; outline: none; padding: 2px 10px; }}
QListWidget#Nav::item {{ padding: 6px 10px; border-radius: 9px; color: {p.text2}; margin: 1px 0; border: none; }}
QListWidget#Nav::item:hover {{ background: {p.surface2}; color: {p.text}; }}
QListWidget#Nav::item:selected {{ background: {p.surface3}; color: {p.text}; font-weight: 600;
    border-left: 2px solid {p.teal}; }}
QListWidget#Nav::item:disabled {{ color: {p.muted}; font-size: {fs - 3}px; font-weight: 700; padding: 10px 10px 2px 10px;
    letter-spacing: 1.6px; background: transparent; }}
QFrame#RankCard {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; }}

/* ---- top bar ---------------------------------------------------------------------------- */
QFrame#TopBar {{ background: {p.bg}; border-bottom: 1px solid {p.border}; }}
QLineEdit#Search {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; padding: 7px 12px;
    color: {p.text}; }}
QLineEdit#Search:focus {{ border-color: {p.teal}; }}
QLabel#TopStatLabel {{ color: {p.muted}; font-size: {fs - 3}px; }}
QLabel#TopStatValue {{ font-weight: 600; font-size: {fs}px; }}

/* ---- type ------------------------------------------------------------------------------- */
QLabel#H1 {{ font-family: {disp}; font-size: {fs + 17}px; color: {p.text}; }}
QLabel#Display {{ font-family: {disp}; font-size: {fs + 24}px; color: {p.text}; }}
QLabel#H2 {{ font-family: {disp}; font-size: {fs + 6}px; color: {p.text}; }}
QLabel#H3 {{ font-size: {fs}px; font-weight: 600; color: {p.text}; }}
QLabel#Eyebrow {{ font-size: {fs - 2}px; font-weight: 700; color: {p.teal}; letter-spacing: 1.8px; }}
QLabel#Overline {{ font-size: {fs - 3}px; font-weight: 600; color: {p.muted}; letter-spacing: 1.6px; }}
QLabel#Muted {{ color: {p.muted}; }}
QLabel#Body {{ color: {p.text2}; line-height: 150%; }}
QLabel#Good {{ color: {p.good}; font-weight: 600; }}
QLabel#Bad {{ color: {p.bad}; font-weight: 600; }}
QLabel#Warn {{ color: {p.amber}; font-weight: 600; }}
QLabel#Quote {{ font-family: {disp}; font-size: {fs + 3}px; color: {p.text}; }}
QLabel#Chip {{ background: {p.surface2}; color: {p.text2}; border-radius: 6px; padding: 3px 8px; font-size: {fs - 3}px;
    font-weight: 700; letter-spacing: 0.8px; }}
QLabel#ChipGold {{ background: {p.teal}; color: {p.on_accent}; border-radius: 6px; padding: 3px 8px;
    font-size: {fs - 3}px; font-weight: 800; letter-spacing: 0.8px; }}
QLabel#ChipBlue {{ background: {"#18233A" if dark else "#E4ECFA"}; color: {p.blue}; border-radius: 6px; padding: 3px 8px;
    font-size: {fs - 3}px; font-weight: 800; letter-spacing: 0.8px; }}
QLabel#ChipBad {{ background: {p.bad_soft}; color: {p.bad}; border-radius: 6px; padding: 3px 8px;
    font-size: {fs - 3}px; font-weight: 800; letter-spacing: 0.8px; }}
QLabel#ChipGood {{ background: {p.good}; color: {p.on_accent if dark else "#FFFFFF"}; border-radius: 11px;
    padding: 4px 12px; font-size: {fs - 2}px; font-weight: 800; }}

/* ---- surfaces --------------------------------------------------------------------------- */
QFrame#Card {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame#CardGold {{ background: {p.accent_soft}; border: 1px solid {"#4A3F24" if dark else "#E2CF9F"}; border-radius: 14px; }}
QFrame#Inset {{ background: {p.bg}; border: 1px solid {p.border}; border-radius: 11px; }}
QFrame#KPI {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 14px; }}
QFrame#KPI:hover {{ border: 1px solid {p.teal}; }}
QLabel#KPIValue {{ font-size: {fs + 11}px; font-weight: 600; color: {p.text}; }}
QLabel#KPILabel {{ color: {p.muted}; font-size: {fs - 1}px; }}
QFrame#Banner {{ background: {p.accent_soft}; border: 1px solid {"#4A3F24" if dark else "#E2CF9F"}; border-radius: 10px; }}
QFrame#Rule {{ background: {p.border}; max-height: 1px; min-height: 1px; border: none; }}

/* ---- buttons ---------------------------------------------------------------------------- */
QPushButton {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 10px; padding: 8px 16px;
    color: {p.text}; font-weight: 600; }}
QPushButton:hover {{ border-color: {p.teal}; color: {p.text}; }}
QPushButton:pressed {{ background: {p.surface2}; }}
QPushButton:disabled {{ color: {p.muted}; border-color: {p.border}; }}
QPushButton:checked {{ background: {p.accent_soft}; border: 1.5px solid {p.teal}; color: {p.teal}; }}
QPushButton#Primary {{ background: {p.teal}; color: {p.on_accent}; border: none; font-weight: 700; padding: 9px 18px; }}
QPushButton#Primary:hover {{ background: {"#E6C783" if dark else "#8E6923"}; }}
QPushButton#Primary:disabled {{ background: {p.surface2}; color: {p.muted}; }}
QPushButton#Hero {{ background: {p.teal}; color: {p.on_accent}; border: none; font-weight: 800; font-size: {fs + 2}px;
    padding: 14px 24px; border-radius: 12px; }}
QPushButton#Hero:hover {{ background: {"#E6C783" if dark else "#8E6923"}; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {p.text2}; padding: 6px 10px; }}
QPushButton#Ghost:hover {{ color: {p.teal}; }}
QPushButton#Danger {{ border-color: {p.bad}; color: {p.bad}; }}
QPushButton#Choice {{ background: transparent; border: 1px solid {p.border}; border-radius: 10px; padding: 10px 10px;
    color: {p.text2}; font-weight: 600; }}
QPushButton#Choice:hover {{ border-color: {p.teal}; color: {p.text}; }}
QPushButton#Choice:checked {{ background: {p.accent_soft}; border: 1.5px solid {p.teal}; color: {p.teal}; font-weight: 800; }}
QPushButton#Segment {{ background: transparent; border: none; border-radius: 8px; padding: 8px 0; color: {p.muted}; }}
QPushButton#Segment:checked {{ background: {p.surface3}; color: {p.text}; font-weight: 800; border: none; }}
QFrame#SegmentBox {{ background: {p.bg}; border: 1px solid {p.border}; border-radius: 11px; }}
QToolButton {{ background: transparent; border: none; border-radius: 8px; padding: 6px; }}
QToolButton:hover {{ background: {p.surface2}; }}

/* ---- inputs ----------------------------------------------------------------------------- */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit {{
    background: {p.surface2}; border: 1px solid {p.border}; border-radius: 9px; padding: 4px 8px; min-height: 24px;
    selection-background-color: {sel}; selection-color: {p.text}; }}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {p.teal}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px;
    selection-background-color: {p.surface3}; selection-color: {p.text}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 16px; border: none; background: transparent; }}

/* ---- tables and lists ------------------------------------------------------------------- */
QTableView, QTreeView, QTreeWidget, QListWidget {{ background: {p.surface}; alternate-background-color: {p.surface};
    border: 1px solid {p.border}; border-radius: 12px; gridline-color: transparent; outline: none;
    selection-background-color: {p.surface3}; selection-color: {p.text}; }}
QTableView::item, QTreeView::item {{ padding: 4px 8px; border-bottom: 1px solid {p.grid}; }}
QTableView::item:selected, QTreeView::item:selected {{ background: {p.surface3}; color: {p.text}; }}
QListWidget::item {{ padding: 7px 8px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {p.surface3}; color: {p.text}; }}
QListWidget::item:hover {{ background: {p.surface2}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: {p.surface}; color: {p.muted}; border: none; border-bottom: 1px solid {p.border};
    padding: 8px 8px; font-weight: 700; font-size: {fs - 2}px; }}
QTableCornerButton::section {{ background: {p.surface}; border: none; }}

/* ---- tabs ------------------------------------------------------------------------------- */
QTabWidget::pane {{ border: none; background: transparent; top: 0px; }}
QTabBar {{ qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {p.muted}; padding: 9px 2px; margin-right: 22px;
    border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.teal}; }}

/* ---- misc ------------------------------------------------------------------------------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border}; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {p.muted}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border}; border-radius: 3px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ width: 0; height: 0;
    background: transparent; }}
QToolTip {{ background: {p.surface3}; color: {p.text}; border: 1px solid {p.border}; padding: 7px 9px;
    border-radius: 8px; }}
QSlider::groove:horizontal {{ height: 4px; background: {p.border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {p.teal}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {"#F3D98F" if dark else p.teal}; width: 18px; height: 18px; margin: -7px 0;
    border-radius: 9px; border: 3px solid {p.accent_soft}; }}
QProgressBar {{ background: {p.surface2}; border: none; border-radius: 3px; text-align: center; max-height: 6px;
    color: transparent; }}
QProgressBar::chunk {{ background: {p.teal}; border-radius: 3px; }}
QGroupBox {{ border: 1px solid {p.border}; border-radius: 12px; margin-top: 16px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px; color: {p.text2}; font-weight: 700; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1.5px solid {p.muted};
    background: transparent; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {p.teal}; border-color: {p.teal}; }}
QStatusBar {{ background: {p.bg}; color: {p.muted}; border-top: 1px solid {p.border}; }}
QSplitter::handle {{ background: transparent; }}
QMenu {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.surface3}; }}
QMessageBox, QDialog, QInputDialog {{ background: {p.surface}; }}
QTextBrowser {{ background: {p.surface}; border: 1px solid {p.border}; border-radius: 12px; padding: 6px; }}
"""


def mpl_style(p: Palette) -> dict:
    return {
        "figure.facecolor": p.surface, "axes.facecolor": p.surface, "axes.edgecolor": p.border,
        "axes.labelcolor": p.muted, "axes.titlecolor": p.text, "xtick.color": p.muted, "ytick.color": p.muted,
        "grid.color": p.grid, "text.color": p.text, "legend.facecolor": p.surface, "legend.edgecolor": p.surface,
        "legend.labelcolor": p.text2, "axes.prop_cycle": __import__("cycler").cycler(color=list(p.series)),
        "font.family": [UI_FONT, "DejaVu Sans"], "font.size": 9, "axes.titlesize": 10.5, "axes.titleweight": "semibold",
        "axes.titlelocation": "left", "axes.titlepad": 10, "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.grid": True, "axes.grid.axis": "y", "grid.linewidth": 0.8,
        "xtick.major.size": 0, "ytick.major.size": 0, "lines.linewidth": 2.0, "lines.solid_capstyle": "round",
        "patch.linewidth": 0, "axes.axisbelow": True,
    }
