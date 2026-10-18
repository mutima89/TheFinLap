"""Main window: sidebar navigation, top bar, global search and keyboard shortcuts."""
from __future__ import annotations

import importlib
import traceback

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
                               QStackedWidget, QComboBox, QPushButton, QStatusBar, QFrame, QLineEdit, QApplication)

from . import icons, theme
from .chrome import RankCard, SeasonStrip
from .state import AppState
from .widgets import label

# (key, sidebar title, module, class, section, icon)
PAGES = [
    ("home", "Command Center", "command_center", "CommandCenterPage", "Play", "home"),
    ("season", "Run the Month", "season", "SeasonPage", "Play", "play"),
    ("decisions", "Boardroom Cases", "decisions", "DecisionPage", "Play", "boardroom"),
    ("dashboard", "Hotel Dashboard", "dashboard", "DashboardPage", "Analyse", "building"),
    ("rm", "Revenue Management", "revenue", "RevenuePage", "Analyse", "revenue"),
    ("fpa", "FP&A and Variances", "fpa", "FPAPage", "Analyse", "fpa"),
    ("statements", "Financial Statements", "statements", "StatementsPage", "Analyse", "statements"),
    ("lab", "Scenario Lab", "scenario_lab", "ScenarioLabPage", "Analyse", "lab"),
    ("workbench", "Modelling Workbench", "workbench", "WorkbenchPage", "Analyse", "workbench"),
    ("risk", "Sensitivity and Risk", "risk", "RiskPage", "Analyse", "risk"),
    ("invest", "Investment Cases", "investment", "InvestmentPage", "Analyse", "invest"),
    ("learn", "Academy", "learning", "LearningPage", "Learn", "academy"),
    ("excel", "Excel Lab", "excel_lab", "ExcelLabPage", "Learn", "excel"),
    ("capstone", "Capstone", "capstone", "CapstonePage", "Learn", "capstone"),
    ("reports", "Reports and Portfolio", "reports", "ReportsPage", "Workspace", "reports"),
    ("glossary", "Glossary and Search", "glossary", "GlossaryPage", "Workspace", "glossary"),
    ("settings", "Settings and Data", "settings", "SettingsPage", "Workspace", "settings"),
]


class BrandMark(QWidget):
    """The gold "A" tile."""

    def __init__(self, size: int = 38):
        super().__init__()
        self.setFixedSize(size, size)

    def paintEvent(self, _e):  # noqa: N802
        from PySide6.QtGui import QPainter, QLinearGradient, QColor
        from PySide6.QtCore import QRectF
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, self.width(), self.height())
        g.setColorAt(0, QColor("#E6C77E"))
        g.setColorAt(1, QColor("#A8843F"))
        qp.setPen(Qt.NoPen)
        qp.setBrush(g)
        qp.drawRoundedRect(QRectF(self.rect()), 10, 10)
        qp.setPen(QColor("#14110A"))
        qp.setFont(theme.display_font(self.height() * 0.58, 600))
        qp.drawText(self.rect(), Qt.AlignCenter, "A")
        qp.end()


class MainWindow(QMainWindow):
    def __init__(self, state: AppState):
        super().__init__()
        theme.load_fonts()
        self.state = state
        self.setWindowTitle("Aurelia Finance Lab")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)
        self.pages: dict[str, QWidget] = {}
        self.page_index: dict[str, int] = {}

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget()
        side.setObjectName("Sidebar")
        side.setFixedWidth(240)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 20, 0, 14)
        sl.setSpacing(0)
        brand = QHBoxLayout()
        brand.setContentsMargins(20, 0, 16, 8)
        brand.setSpacing(12)
        brand.addWidget(BrandMark())
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(label("Aurelia", "Brand"))
        names.addWidget(label("FINANCE LAB", "BrandSub"))
        brand.addLayout(names, 1)
        sl.addLayout(brand)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setFocusPolicy(Qt.StrongFocus)
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sl.addWidget(self.nav, 1)
        self.rank = RankCard(state)
        rk = QHBoxLayout()
        rk.setContentsMargins(12, 8, 12, 0)
        rk.addWidget(self.rank)
        sl.addLayout(rk)
        h.addWidget(side)

        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(64)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(28, 0, 20, 0)
        tl.setSpacing(18)
        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("Search   Ctrl+K")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._search)
        self.search.setFixedWidth(250)
        tl.addWidget(self.search)
        self.season_bar = SeasonStrip(state)
        tl.addWidget(self.season_bar, 1)
        self.scen_lbl = label("", "Muted")
        self.scen_lbl.setVisible(False)
        tl.addWidget(self.scen_lbl)
        self.cur_cb = QComboBox()
        self.cur_cb.addItems(["SAR", "USD"])
        self.cur_cb.setToolTip("Display currency. The model calculates in SAR; USD uses the configured FX rate.")
        self.cur_cb.setCurrentText(state.currency)
        self.cur_cb.currentTextChanged.connect(state.set_currency)
        self.cur_cb.setFixedWidth(78)
        tl.addWidget(self.cur_cb)
        self.theme_btn = QPushButton("Light theme" if state.theme == "dark" else "Dark theme")
        self.theme_btn.setObjectName("Ghost")
        self.theme_btn.setToolTip("Toggle light/dark theme (Ctrl+T)")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.clicked.connect(self.toggle_theme)
        tl.addWidget(self.theme_btn)
        ml.addWidget(top)
        self.stack = QStackedWidget()
        ml.addWidget(self.stack, 1)
        h.addWidget(main, 1)
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().setSizeGripEnabled(False)

        self._build_nav()
        self.nav.currentItemChanged.connect(self._nav_changed)

        state.navigate.connect(self.go)
        state.status.connect(lambda m: self.statusBar().showMessage(m, 6000))
        state.results_changed.connect(self._update_top)
        state.scenarios_changed.connect(self._update_top)

        self._shortcuts()
        self._update_top()
        start = state.db.get_setting("last_page", "home")
        self.go(start if any(p[0] == start for p in PAGES) else "home")

    # ---- pages -----------------------------------------------------------------------------
    def page(self, key: str) -> QWidget:
        if key not in self.pages:
            spec = next(p for p in PAGES if p[0] == key)
            try:
                module = importlib.import_module(f"aurelia.ui.pages.{spec[2]}")
                widget = getattr(module, spec[3])(self.state)
            except Exception:  # noqa: BLE001 – show a clear error page rather than crash
                from .widgets import Page
                widget = Page(spec[1], "This page failed to load.")
                widget.load_error = traceback.format_exc()
                widget.body.addWidget(label(widget.load_error, wrap=True))
            for cb in widget.findChildren(QComboBox):  # long item text must not widen the page
                cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                cb.setMinimumContentsLength(max(8, min(cb.minimumContentsLength() or 18, 18)))
            self.pages[key] = widget
            self.page_index[key] = self.stack.addWidget(widget)
        return self.pages[key]

    def _build_nav(self) -> None:
        p = theme.current()
        self.nav.blockSignals(True)
        cur = self.nav.currentItem().data(Qt.UserRole) if self.nav.currentItem() else None
        self.nav.clear()
        section = None
        for key, title, mod, cls, sec, ic in PAGES:
            if sec != section:
                hdr = QListWidgetItem(sec.upper())
                hdr.setFlags(Qt.NoItemFlags)
                self.nav.addItem(hdr)
                section = sec
            it = QListWidgetItem(icons.icon(ic, p.muted, 18, p.teal), "  " + title.replace("&&", "&"))
            it.setData(Qt.UserRole, key)
            it.setSizeHint(QSize(200, 30))
            self.nav.addItem(it)
            if key == cur:
                self.nav.setCurrentItem(it)
        self.nav.blockSignals(False)

    def go(self, key: str, payload=None) -> None:
        w = self.page(key)
        self.stack.setCurrentIndex(self.page_index[key])
        if hasattr(w, "refresh"):
            try:
                w.refresh()
            except Exception:  # noqa: BLE001
                self.statusBar().showMessage("Page refresh failed – see the error log in Settings.", 8000)
                w.refresh_error = traceback.format_exc()
                traceback.print_exc()
        if payload is not None and hasattr(w, "focus_item"):
            w.focus_item(payload)
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) == key:
                self.nav.blockSignals(True)
                self.nav.setCurrentRow(i)
                self.nav.blockSignals(False)
        self.state.db.set_setting("last_page", key)
        self.refresh_chrome()

    def refresh_chrome(self) -> None:
        """Update the season strip and rank card (after a month closes, XP changes, theme changes)."""
        for w in (self.season_bar, self.rank):
            try:
                w.refresh()
            except Exception:  # noqa: BLE001 – chrome must never block navigation
                pass

    def _nav_changed(self, cur, _prev) -> None:
        if cur is not None and cur.data(Qt.UserRole):
            self.go(cur.data(Qt.UserRole))

    def _update_top(self) -> None:
        dirty = " (unsaved changes)" if self.state.dirty else ""
        self.scen_lbl.setText(f"Scenario: {self.state.scenario_name}{dirty}   ")

    # ---- search & shortcuts -------------------------------------------------------------------
    def _search(self) -> None:
        q = self.search.text().strip()
        if q:
            self.go("glossary", q)

    def _shortcuts(self) -> None:
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.activated.connect(fn)
        sc("Ctrl+K", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Ctrl+Z", lambda: self.state.undo())
        sc("Ctrl+Y", lambda: self.state.redo())
        sc("Ctrl+S", self._save)
        sc("Ctrl+T", self.toggle_theme)
        sc("F1", lambda: self.go("glossary", "help"))
        for i, p in enumerate(PAGES[:9], start=1):
            sc(f"Ctrl+{i}", lambda k=p[0]: self.go(k))

    def _save(self) -> None:
        lab = self.page("lab")
        lab._save()

    def toggle_theme(self) -> None:
        new = "light" if self.state.theme == "dark" else "dark"
        apply_theme(QApplication.instance(), new)
        self.state.set_theme(new)
        self.theme_btn.setText("Light theme" if new == "dark" else "Dark theme")
        self._build_nav()
        self.refresh_chrome()
        cur = self.stack.currentWidget()
        if hasattr(cur, "refresh"):
            cur.refresh()

    def closeEvent(self, e):  # noqa: N802
        # Drafts are auto-saved continuously; nothing is lost on close.
        self.state.db.set_setting("window_geometry", [self.width(), self.height()])
        super().closeEvent(e)


def apply_theme(app: QApplication, name: str) -> None:
    theme.load_fonts()
    p = theme.set_current(name)
    app.setFont(theme.ui_font(13.5))
    scale = 1.0
    app.setStyleSheet(theme.stylesheet(p, scale))
