"""Reusable widgets: KPI cards, charts, tables, banners, formula popups."""
from __future__ import annotations

import re
from typing import Callable, Iterable

import matplotlib

matplotlib.use("QtAgg")
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, Signal  # noqa: E402
from PySide6.QtGui import QColor, QFont  # noqa: E402
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QTableView, QHeaderView,  # noqa: E402
                               QSizePolicy, QMessageBox, QScrollArea, QGridLayout, QPushButton, QDialog,
                               QTextBrowser, QDialogButtonBox, QAbstractItemView)

from . import theme  # noqa: E402

_NUMERIC_TEXT = re.compile(r"^(SAR |USD |[-+−]?[\d.]|n/a$)")


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    if wrap:
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def card(layout_cls=QVBoxLayout, margins: int = 20, spacing: int = 10) -> tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("Card")
    lay = layout_cls(f)
    lay.setContentsMargins(margins, margins, margins, margins)
    lay.setSpacing(spacing)
    return f, lay


def button(text: str, slot: Callable | None = None, primary: bool = False, danger: bool = False,
           tip: str = "") -> QPushButton:
    b = QPushButton(text if "&&" in text else text.replace("&", "&&"))  # a single & would become a mnemonic
    if primary:
        b.setObjectName("Primary")
    if danger:
        b.setObjectName("Danger")
    if slot:
        b.clicked.connect(slot)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class Page(QScrollArea):
    """A scrollable page with a title, subtitle and vertical content layout."""

    def __init__(self, title: str, subtitle: str = "", eyebrow: str = ""):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("Page")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(36, 26, 36, 32)
        self.body.setSpacing(18)
        head = QVBoxLayout()
        head.setSpacing(6)
        if eyebrow:
            head.addWidget(label(eyebrow.upper(), "Eyebrow"))
        self.title_label = label(title, "H1")
        head.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = label(subtitle, "Body", wrap=True)
            self.subtitle_label.setMaximumWidth(980)
            head.addWidget(self.subtitle_label)
        self.body.addLayout(head)
        self.setWidget(inner)

    def refresh(self) -> None:  # overridden by pages
        pass


class KPICard(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, title: str, tooltip: str = ""):
        super().__init__()
        self.key = key
        self.setObjectName("KPI")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip + "\n\nClick to open the source analysis.")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(4)
        self.title = label(title, "KPILabel")
        self.value = label("—", "KPIValue")
        self.delta = label("", "Muted")
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        lay.addWidget(self.delta)
        from .visuals import Sparkline
        self.spark = Sparkline()
        self.spark.setVisible(False)
        lay.addWidget(self.spark)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(150)

    def set(self, value: str, delta: str = "", good: bool | None = None, spark: list[float] | None = None,
            spark_ref: list[float] | None = None) -> None:
        self.value.setText(value)
        self.delta.setText(delta)
        if spark is not None and len(spark) > 1:
            self.spark.set(spark, spark_ref, None if good is None else ("good" if good else "bad"))
            self.spark.setVisible(True)
        self.delta.setObjectName("Muted" if good is None else ("Good" if good else "Bad"))
        self.delta.style().unpolish(self.delta)
        self.delta.style().polish(self.delta)

    def mousePressEvent(self, e):  # noqa: N802
        self.clicked.emit(self.key)
        super().mousePressEvent(e)


class Banner(QFrame):
    def __init__(self, text: str = ""):
        super().__init__()
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        self.text = label(text, wrap=True)
        lay.addWidget(self.text)

    def set_text(self, text: str) -> None:
        self.text.setText(text)
        self.setVisible(bool(text))


def money_formatter(currency: str = "SAR") -> FuncFormatter:
    def f(x, _pos):
        ax = abs(x)
        if ax >= 1e6:
            return f"{x / 1e6:,.1f}m"
        if ax >= 1e3:
            return f"{x / 1e3:,.0f}k"
        return f"{x:,.0f}"
    return FuncFormatter(f)


def pct_formatter() -> FuncFormatter:
    return FuncFormatter(lambda x, _p: f"{x * 100:.0f}%")


class Chart(QWidget):
    """Matplotlib figure that re-styles itself with the active theme."""

    def __init__(self, height: float = 3.0, width: float = 6.0):
        super().__init__()
        self.figure = Figure(figsize=(width, height), dpi=100, layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.setMinimumHeight(int(height * 80))
        p = theme.current()
        self.figure.set_facecolor(p.surface)
        self.figure.text(0.5, 0.5, "The chart appears once the analysis has run.", ha="center", va="center",
                         color=p.muted, fontsize=9)

    def new_axes(self, nrows: int = 1, ncols: int = 1):
        self.figure.clear()
        with matplotlib.rc_context(theme.mpl_style(theme.current())):
            self.figure.set_facecolor(theme.current().surface)
            axes = self.figure.subplots(nrows, ncols)
        for ax in np.atleast_1d(axes).ravel():
            self.style_axes(ax)
        return axes

    @staticmethod
    def style_axes(ax) -> None:
        p = theme.current()
        ax.set_facecolor(p.surface)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(p.border)
        ax.tick_params(colors=p.muted, labelsize=8.5, length=0, pad=6)
        ax.grid(True, axis="y", color=p.grid, linewidth=0.8)
        ax.grid(False, axis="x")
        ax.set_axisbelow(True)
        ax.title.set_color(p.text)
        ax.title.set_fontsize(10.5)
        ax.title.set_fontweight("semibold")
        ax.xaxis.label.set_color(p.text2)
        ax.yaxis.label.set_color(p.text2)

    def legend(self, ax, **kw) -> None:
        p = theme.current()
        leg = ax.legend(frameon=False, fontsize=8, **kw)
        for t in leg.get_texts():
            t.set_color(p.text2)

    def draw(self) -> None:
        self.canvas.draw_idle()


class DataFrameModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, formatters: dict | None = None,
                 nature: dict | None = None):
        super().__init__()
        self.df = df if df is not None else pd.DataFrame()
        self.formatters = formatters or {}
        self.nature = nature or {}  # column -> callable(row, value) -> 'good'|'bad'|None
        self.bold_rows: set[int] = set()

    def set(self, df: pd.DataFrame, formatters: dict | None = None, bold_rows: Iterable[int] = ()) -> None:
        self.beginResetModel()
        self.df = df
        if formatters is not None:
            self.formatters = formatters
        self.bold_rows = set(bold_rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.df)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.df.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        col = self.df.columns[index.column()]
        val = self.df.iat[index.row(), index.column()]
        if role == Qt.DisplayRole:
            fmt = self.formatters.get(col) or self.formatters.get("*")
            if fmt is not None and not isinstance(val, str):
                try:
                    return fmt(val)
                except (TypeError, ValueError):
                    return str(val)
            if isinstance(val, float):
                return "n/a" if np.isnan(val) else f"{val:,.0f}"
            return "" if val is None else str(val)
        if role == Qt.TextAlignmentRole:
            if isinstance(val, (int, float, np.number)) and not isinstance(val, bool):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            if index.column() > 0 and isinstance(val, str) and _NUMERIC_TEXT.match(val):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role == Qt.FontRole and index.row() in self.bold_rows:
            f = QFont(theme.UI_FONT)
            f.setWeight(QFont.Bold)
            return f
        if role == Qt.ForegroundRole and col in self.nature:
            verdict = self.nature[col](index.row(), val)
            p = theme.current()
            if verdict == "good":
                return QColor(p.good)
            if verdict == "bad":
                return QColor(p.bad)
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.TextAlignmentRole and orientation == Qt.Horizontal:
            if section > 0 and len(self.df):
                v = self.df.iat[0, section]
                numeric = (isinstance(v, (int, float, np.number)) and not isinstance(v, bool)) or \
                    (isinstance(v, str) and bool(_NUMERIC_TEXT.match(v)))
                if numeric:
                    return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self.df.columns[section])
        return str(self.df.index[section]) if not isinstance(self.df.index, pd.RangeIndex) else None


class Table(QTableView):
    def __init__(self, stretch_first: bool = False, min_height: int = 180):
        super().__init__()
        self.model_ = DataFrameModel()
        self.setModel(self.model_)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.setShowGrid(False)
        self.setFrameShape(QFrame.NoFrame)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.horizontalHeader().setHighlightSections(False)
        self.stretch_first = stretch_first
        self.setMinimumHeight(min_height)
        self.setSortingEnabled(False)

    def set(self, df: pd.DataFrame, formatters: dict | None = None, bold_rows: Iterable[int] = (),
            nature: dict | None = None) -> None:
        if nature is not None:
            self.model_.nature = nature
        self.model_.set(df.reset_index(drop=True) if not isinstance(df.index, pd.RangeIndex) else df,
                        formatters, bold_rows)
        hh = self.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setStretchLastSection(not self.stretch_first)
        if self.stretch_first and len(df.columns):
            hh.setSectionResizeMode(0, QHeaderView.Stretch)

    def fit_height(self, max_rows: int = 30) -> None:
        rows = min(self.model_.rowCount(), max_rows)
        h = 38 + rows * 34 + 22  # header + rows + room for a horizontal scrollbar
        self.setMinimumHeight(h)
        self.setMaximumHeight(h if self.model_.rowCount() <= max_rows else 16777215)


def info_dialog(parent: QWidget, title: str, html: str) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(620, 460)
    lay = QVBoxLayout(dlg)
    tb = QTextBrowser()
    tb.setOpenExternalLinks(False)
    tb.setHtml(html)
    lay.addWidget(tb)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    bb.rejected.connect(dlg.reject)
    bb.accepted.connect(dlg.accept)
    lay.addWidget(bb)
    dlg.exec()


def confirm(parent: QWidget, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.Cancel,
                                QMessageBox.Cancel) == QMessageBox.Yes


def error(parent: QWidget, title: str, text: str) -> None:
    QMessageBox.warning(parent, title, text)


def grid(widgets: list[QWidget], columns: int) -> QGridLayout:
    g = QGridLayout()
    g.setSpacing(10)
    for i, w in enumerate(widgets):
        g.addWidget(w, i // columns, i % columns)
    return g
