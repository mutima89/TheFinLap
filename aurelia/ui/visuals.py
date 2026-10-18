"""Hand-painted visual components: sparklines, gauges, season bars, bridge charts, range bars and hero panels.

They are drawn with QPainter (not Matplotlib) so they stay crisp at any DPI, follow the active theme and cost
nothing to redraw.
"""
from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient,
                           QFontMetrics)
from PySide6.QtWidgets import QFrame, QSizePolicy, QWidget, QToolTip

from . import theme


def _c(hex_: str, alpha: float | None = None) -> QColor:
    c = QColor(hex_)
    if alpha is not None:
        c.setAlphaF(alpha)
    return c


def _tone(p: theme.Palette, tone: str | None) -> str:
    return {"good": p.good, "bad": p.bad, "gold": p.teal, "blue": p.blue, "info": p.blue,
            "muted": p.muted}.get(tone or "gold", p.teal)


def short_money(v: float, prefix: str = "SAR ", digits: int = 2) -> str:
    a = abs(v)
    sign = "−" if v < 0 else ""
    if a >= 1e6:
        return f"{sign}{prefix}{a / 1e6:,.{digits}f}m"
    if a >= 1e3:
        return f"{sign}{prefix}{a / 1e3:,.0f}k"
    return f"{sign}{prefix}{a:,.0f}"


class Sparkline(QWidget):
    def __init__(self, height: int = 34):
        super().__init__()
        self.values: list[float] = []
        self.ref: list[float] | None = None
        self.tone: str | None = None
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, values: Sequence[float], ref: Sequence[float] | None = None, tone: str | None = None) -> None:
        self.values = [float(v) for v in values]
        self.ref = [float(v) for v in ref] if ref is not None else None
        self.tone = tone
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        if len(self.values) < 2:
            return
        p = theme.current()
        allv = self.values + (self.ref or [])
        lo, hi = min(allv), max(allv)
        span = (hi - lo) or 1.0
        w, h = self.width(), self.height()
        pad = 4

        def pts(vals):
            n = len(vals)
            return [QPointF(pad + i * (w - 2 * pad) / (n - 1), pad + (1 - (v - lo) / span) * (h - 2 * pad))
                    for i, v in enumerate(vals)]
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        if self.ref:
            pen = QPen(_c(p.muted, 0.6), 1, Qt.DashLine)
            qp.setPen(pen)
            path = QPainterPath(pts(self.ref)[0])
            for pt in pts(self.ref)[1:]:
                path.lineTo(pt)
            qp.drawPath(path)
        col = _c(_tone(p, self.tone))
        ps = pts(self.values)
        area = QPainterPath(QPointF(ps[0].x(), h))
        for pt in ps:
            area.lineTo(pt)
        area.lineTo(QPointF(ps[-1].x(), h))
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, _c(col.name(), 0.28))
        g.setColorAt(1, _c(col.name(), 0.0))
        qp.fillPath(area, QBrush(g))
        line = QPainterPath(ps[0])
        for pt in ps[1:]:
            line.lineTo(pt)
        qp.setPen(QPen(col, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        qp.drawPath(line)
        qp.setBrush(col)
        qp.drawEllipse(ps[-1], 2.6, 2.6)
        qp.end()


class Ring(QWidget):
    """A circular gauge, value in 0..100."""

    def __init__(self, size: int = 40, width: float = 4.0):
        super().__init__()
        self.value = 0.0
        self.w = width
        self.tone = "gold"
        self.center_text = ""
        self.setFixedSize(size, size)

    def set(self, value: float, tone: str = "gold", center_text: str = "") -> None:
        self.value = max(0.0, min(100.0, float(value)))
        self.tone = tone
        self.center_text = center_text
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.w / 2 + 1, self.w / 2 + 1, self.width() - self.w - 2, self.height() - self.w - 2)
        qp.setPen(QPen(_c(p.surface3), self.w, Qt.SolidLine, Qt.RoundCap))
        qp.drawArc(r, 0, 360 * 16)
        qp.setPen(QPen(_c(_tone(p, self.tone)), self.w, Qt.SolidLine, Qt.RoundCap))
        qp.drawArc(r, 90 * 16, -int(self.value / 100 * 360 * 16))
        if self.center_text:
            qp.setPen(_c(p.text))
            qp.setFont(theme.ui_font(self.height() * 0.3, 700))
            qp.drawText(self.rect(), Qt.AlignCenter, self.center_text)
        qp.end()


class ProgressLine(QWidget):
    def __init__(self, height: int = 6):
        super().__init__()
        self.frac = 0.0
        self.tone = "gold"
        self.marker: float | None = None
        self.setFixedHeight(height + (8 if False else 0))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, frac: float, tone: str = "gold", marker: float | None = None) -> None:
        self.frac = max(0.0, min(1.0, float(frac)))
        self.tone = tone
        self.marker = marker
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        qp.setPen(Qt.NoPen)
        qp.setBrush(_c(p.surface3))
        qp.drawRoundedRect(QRectF(0, 0, self.width(), h), h / 2, h / 2)
        qp.setBrush(_c(_tone(p, self.tone)))
        qp.drawRoundedRect(QRectF(0, 0, max(h, self.width() * self.frac), h), h / 2, h / 2)
        if self.marker is not None:
            x = self.width() * max(0.0, min(1.0, self.marker))
            qp.setBrush(_c(p.text))
            qp.drawRect(QRectF(x - 1, 0, 2, h))
        qp.end()


class Hero(QFrame):
    """A rounded panel with a soft radial glow; put any layout inside."""

    def __init__(self, tone: str = "gold"):
        super().__init__()
        self.tone = tone
        self.setAttribute(Qt.WA_StyledBackground, False)

    def paintEvent(self, e):  # noqa: N802
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        g = QRadialGradient(QPointF(r.right(), r.top()) if self.tone == "gold" else QPointF(r.left(), r.top()),
                            max(r.width(), r.height()) * 0.95)
        a = p.hero_a if self.tone == "gold" else (p.good_soft if self.tone == "good" else p.bad_soft)
        g.setColorAt(0, _c(a))
        g.setColorAt(0.75, _c(p.hero_b))
        g.setColorAt(1, _c(p.hero_b))
        path = QPainterPath()
        path.addRoundedRect(r, 18, 18)
        qp.fillPath(path, QBrush(g))
        border = {"gold": "#4A3F24", "good": "#23413A", "bad": "#4A2A22"}[self.tone] if p.name == "dark" \
            else {"gold": "#E2CF9F", "good": "#BFE1CF", "bad": "#EDC4B5"}[self.tone]
        qp.setPen(QPen(_c(border), 1))
        qp.drawPath(path)
        qp.end()
        super().paintEvent(e)


class Avatar(QWidget):
    def __init__(self, initials: str, size: int = 40):
        super().__init__()
        self.initials = initials
        self.setFixedSize(size, size)

    def paintEvent(self, _e):  # noqa: N802
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(Qt.NoPen)
        qp.setBrush(_c(p.surface3))
        qp.drawEllipse(QRectF(self.rect()))
        qp.setPen(_c(p.teal))
        qp.setFont(theme.ui_font(self.height() * 0.34, 800))
        qp.drawText(self.rect(), Qt.AlignCenter, self.initials)
        qp.end()


class MonthTrack(QWidget):
    """Twelve small pills showing season progress (played months coloured by verdict)."""

    def __init__(self):
        super().__init__()
        self.states: list[str] = ["future"] * 12
        self.setFixedSize(26 + 11 * 14 + 11 * 4, 8)

    def set(self, states: Sequence[str]) -> None:
        self.states = list(states)[:12] + ["future"] * max(0, 12 - len(states))
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        qp.setPen(Qt.NoPen)
        x = 0.0
        for s in self.states:
            w = 26.0 if s == "current" else 14.0
            col = {"beat": p.good, "on": p.blue, "missed": p.bad, "current": p.teal}.get(s, p.surface3)
            qp.setBrush(_c(col))
            qp.drawRoundedRect(QRectF(x, 1, w, 6), 3, 3)
            x += w + 4
        qp.end()

    def sizeHint(self):  # noqa: N802
        return QSize(26 + 11 * 14 + 11 * 4, 8)


class SeasonBars(QWidget):
    """Monthly EBITDA bars against budget: played months coloured by result, the current month outlined, future
    months show the budget as a quiet bar."""

    month_clicked = Signal(int)

    def __init__(self, height: int = 190):
        super().__init__()
        self.labels: list[str] = []
        self.actual: list[float | None] = []
        self.budget: list[float] = []
        self.current: int | None = None
        self.setMinimumHeight(height)
        self.setMouseTracking(True)
        self._rects: list[QRectF] = []

    def set(self, labels, actual, budget, current: int | None) -> None:
        self.labels, self.actual, self.budget, self.current = list(labels), list(actual), list(budget), current
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        if not self.labels:
            return
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        n = len(self.labels)
        lab_h = 22
        top_pad = 18
        h = self.height() - lab_h - top_pad
        vals = [v for v in self.actual if v is not None] + list(self.budget)
        hi = max(max(vals), 1.0) * 1.05
        gap = 10.0
        bw = (self.width() - gap * (n - 1)) / n
        self._rects = []
        qp.setFont(theme.ui_font(11, 500))
        for i in range(n):
            x = i * (bw + gap)
            b = self.budget[i]
            a = self.actual[i] if i < len(self.actual) else None
            v = a if a is not None else b
            bh = max(3.0, h * max(v, 0) / hi)
            r = QRectF(x, top_pad + h - bh, bw, bh)
            self._rects.append(QRectF(x, top_pad, bw, h))
            path = QPainterPath()
            path.addRoundedRect(r, 6, 6)
            if a is not None:
                col = p.good if a >= b else p.bad
                qp.fillPath(path, _c(col))
                # budget tick
                by = top_pad + h - h * max(b, 0) / hi
                qp.setPen(QPen(_c(p.text, 0.85), 2))
                qp.drawLine(QPointF(x + 3, by), QPointF(x + bw - 3, by))
            elif self.current == i:
                qp.setPen(QPen(_c(p.teal), 1.6, Qt.DashLine))
                qp.setBrush(Qt.NoBrush)
                qp.drawPath(path)
            else:
                qp.fillPath(path, _c(p.surface3))
            qp.setPen(_c(p.teal if self.current == i else (p.muted if a is not None else p.muted)))
            f = theme.ui_font(11, 800 if self.current == i else 500)
            qp.setFont(f)
            qp.drawText(QRectF(x - 4, top_pad + h + 4, bw + 8, lab_h), Qt.AlignHCenter | Qt.AlignTop, self.labels[i])
        qp.end()

    def mouseMoveEvent(self, e):  # noqa: N802
        for i, r in enumerate(self._rects):
            if r.contains(e.position()):
                a = self.actual[i] if i < len(self.actual) else None
                b = self.budget[i]
                txt = f"{self.labels[i]}\nBudget EBITDA {short_money(b)}"
                if a is not None:
                    txt += f"\nActual {short_money(a)} ({(a - b) / abs(b) * 100:+.1f}%)" if b else ""
                QToolTip.showText(e.globalPosition().toPoint(), txt, self)
                return
        QToolTip.hideText()


class BridgeChart(QWidget):
    """Waterfall from a start value to an end value through signed steps."""

    def __init__(self, height: int = 280):
        super().__init__()
        self.start = ("Budget", 0.0)
        self.end = ("Actual", 0.0)
        self.steps: list[tuple[str, float]] = []
        self.setMinimumHeight(height)
        self.unit_div = 1e3
        self.unit_fmt = "{:,.0f}"

    def set(self, start: tuple[str, float], steps: Sequence[tuple[str, float]], end: tuple[str, float]) -> None:
        self.start, self.steps, self.end = start, [(s, float(v)) for s, v in steps], end
        self.update()

    def _fmt(self, v: float, signed: bool = False) -> str:
        s = self.unit_fmt.format(abs(v) / self.unit_div)
        if signed:
            return ("+" if v >= 0 else "−") + s
        return ("−" if v < 0 else "") + s

    def paintEvent(self, _e):  # noqa: N802
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        cols = [self.start] + self.steps + [self.end]
        n = len(cols)
        # running levels
        levels = [self.start[1]]
        run = self.start[1]
        for _, v in self.steps:
            run += v
            levels.append(run)
        tops = [self.start[1]] + [max(levels[i], levels[i + 1]) for i in range(len(self.steps))] + [self.end[1]]
        bots = [0.0] + [min(levels[i], levels[i + 1]) for i in range(len(self.steps))] + [0.0]
        hi = max(tops) * 1.08 or 1.0
        lo = min(0.0, min(bots))
        lab_h = 46
        val_h = 20
        top = val_h
        h = self.height() - lab_h - top
        gap = 14.0
        bw = (self.width() - gap * (n - 1)) / n

        def y(v):
            return top + (hi - v) / (hi - lo) * h
        fm = QFontMetrics(theme.ui_font(11.5, 500))
        for i, (name, v) in enumerate(cols):
            x = i * (bw + gap)
            if i == 0 or i == n - 1:
                col = p.muted if i == 0 else p.teal
                r = QRectF(x, y(tops[i]), bw, max(2.0, y(0) - y(tops[i])))
                val_txt, val_col = self._fmt(v), (p.text if i == 0 else p.teal)
            else:
                col = p.good if v >= 0 else p.bad
                r = QRectF(x, y(tops[i]), bw, max(3.0, y(bots[i]) - y(tops[i])))
                val_txt, val_col = self._fmt(v, signed=True), col
            path = QPainterPath()
            path.addRoundedRect(r, 5, 5)
            qp.fillPath(path, _c(col, 0.55 if i == 0 else 1.0))
            if 0 < i < n:
                # connector from previous level
                prev_level = levels[i - 1] if i - 1 < len(levels) else levels[-1]
                qp.setPen(QPen(_c(p.muted, 0.5), 1, Qt.DotLine))
                qp.drawLine(QPointF(x - gap, y(prev_level)), QPointF(x, y(prev_level)))
            qp.setPen(_c(val_col))
            qp.setFont(theme.ui_font(12, 700))
            qp.drawText(QRectF(x - 10, r.top() - val_h, bw + 20, val_h - 2), Qt.AlignHCenter | Qt.AlignBottom,
                        val_txt)
            qp.setPen(_c(p.text if i in (0, n - 1) else p.muted))
            qp.setFont(theme.ui_font(11.5, 600 if i in (0, n - 1) else 500))
            text = fm.elidedText(name, Qt.ElideRight, int((bw + 10) * 2))
            qp.drawText(QRectF(x - 5, y(lo) + 6, bw + 10, lab_h), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)
        qp.end()


class RangeBar(QWidget):
    """low–likely–high band with a budget marker."""

    def __init__(self):
        super().__init__()
        self.low = self.likely = self.high = self.budget = 0.0
        self.setFixedHeight(54)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set(self, low: float, likely: float, high: float, budget: float) -> None:
        self.low, self.likely, self.high, self.budget = low, likely, high, budget
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = theme.current()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        vals = [self.low, self.likely, self.high, self.budget]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.25 or 1.0
        lo, hi = lo - pad, hi + pad
        w = self.width()

        def x(v):
            return (v - lo) / (hi - lo) * w
        qp.setPen(Qt.NoPen)
        qp.setBrush(_c(p.surface3))
        qp.drawRoundedRect(QRectF(0, 18, w, 10), 5, 5)
        g = QLinearGradient(x(self.low), 0, x(self.high), 0)
        g.setColorAt(0, _c(p.teal, 0.25))
        lk = (self.likely - self.low) / ((self.high - self.low) or 1)
        g.setColorAt(max(0.01, min(0.99, lk)), _c(p.teal, 1.0))
        g.setColorAt(1, _c(p.teal, 0.25))
        qp.setBrush(QBrush(g))
        qp.drawRoundedRect(QRectF(x(self.low), 18, max(4.0, x(self.high) - x(self.low)), 10), 5, 5)
        qp.setBrush(_c(p.text))
        qp.drawEllipse(QPointF(x(self.likely), 23), 6, 6)
        qp.setBrush(_c(p.teal))
        qp.drawEllipse(QPointF(x(self.likely), 23), 4, 4)
        bx = x(self.budget)
        qp.setPen(QPen(_c(p.text), 2))
        qp.drawLine(QPointF(bx, 10), QPointF(bx, 36))
        qp.setFont(theme.ui_font(11, 600))
        qp.drawText(QRectF(bx - 40, 37, 80, 16), Qt.AlignHCenter, "Budget")
        qp.end()
