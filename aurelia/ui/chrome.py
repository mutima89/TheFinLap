"""Window chrome that follows the Season: the top-bar strip and the sidebar rank card."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget

from .visuals import MonthTrack, ProgressLine, Ring, short_money
from .widgets import label

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def season_snapshot(db) -> dict:
    """Everything the chrome shows, with safe defaults when no season has been played yet."""
    from ..game import season as S
    sn = S.load(db) or S.new_season()
    hist = sn.history
    states = [h.get("verdict", "on") for h in hist]
    month = min(sn.month, 12)
    if sn.month <= 12:
        states.append("current")
    cash = None
    if hist:
        cash = hist[-1].get("actual", {}).get("closing_cash")
    title, nxt, lo, hi = S.title_for(sn.xp)
    return {"states": states, "month": month, "finished": sn.month > 12, "confidence": sn.confidence,
            "guest": sn.guest_score, "cash": cash, "xp": sn.xp, "title": title, "next_title": nxt,
            "xp_floor": lo, "xp_next": hi}


class _Stat(QWidget):
    def __init__(self, caption: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.cap = label(caption, "TopStatLabel")
        self.val = label("—", "TopStatValue")
        self.cap.setAlignment(Qt.AlignRight)
        self.val.setAlignment(Qt.AlignRight)
        v.addWidget(self.cap)
        v.addWidget(self.val)


class SeasonStrip(QWidget):
    def __init__(self, state):
        super().__init__()
        self.state = state
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(16)
        self.track = MonthTrack()
        self.track.setToolTip("Season FY2027: each pill is a month you have played")
        self.month_lbl = label("", "Muted")
        h.addWidget(self.track)
        h.addWidget(self.month_lbl)
        h.addStretch(1)
        self.cash = _Stat("Cash")
        self.guest = _Stat("Guest score")
        h.addWidget(self.cash)
        h.addWidget(self.guest)
        conf = QHBoxLayout()
        conf.setSpacing(8)
        self.ring = Ring(34, 3.5)
        self.conf = _Stat("Owner confidence")
        self.conf.cap.setAlignment(Qt.AlignLeft)
        self.conf.val.setAlignment(Qt.AlignLeft)
        conf.addWidget(self.ring)
        conf.addWidget(self.conf)
        h.addLayout(conf)
        self.refresh()

    def refresh(self) -> None:
        try:
            s = season_snapshot(self.state.db)
        except Exception:  # noqa: BLE001 – no season module or data yet
            self.setVisible(False)
            return
        self.setVisible(True)
        self.track.set(s["states"])
        self.month_lbl.setText("Season complete" if s["finished"]
                               else f"Month {s['month']} of 12 · {MONTHS[s['month'] - 1]}")
        self.cash.val.setText(short_money(s["cash"]) if s["cash"] is not None else "SAR —")
        self.guest.val.setText(f"{s['guest']:.1f} / 5")
        self.conf.val.setText(f"{s['confidence']:.0f}")
        tone = "good" if s["confidence"] >= 70 else ("gold" if s["confidence"] >= 45 else "bad")
        self.ring.set(s["confidence"], tone)


class RankCard(QFrame):
    def __init__(self, state):
        super().__init__()
        self.state = state
        self.setObjectName("RankCard")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)
        v.addWidget(label("YOUR TITLE", "Overline"))
        self.title = label("", "H2")
        v.addWidget(self.title)
        self.bar = ProgressLine(5)
        v.addWidget(self.bar)
        self.sub = label("", "Muted")
        self.sub.setWordWrap(True)
        v.addWidget(self.sub)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Earn XP by closing months well, meeting objectives and passing Academy checks.")
        self.refresh()

    def refresh(self) -> None:
        try:
            s = season_snapshot(self.state.db)
        except Exception:  # noqa: BLE001
            self.setVisible(False)
            return
        self.setVisible(True)
        self.title.setText(s["title"])
        if s["next_title"]:
            span = max(1, s["xp_next"] - s["xp_floor"])
            self.bar.set((s["xp"] - s["xp_floor"]) / span)
            self.sub.setText(f"{s['xp']:,} XP · {s['xp_next'] - s['xp']:,} to {s['next_title']}")
        else:
            self.bar.set(1.0)
            self.sub.setText(f"{s['xp']:,} XP · top of the ladder")

    def mousePressEvent(self, e):  # noqa: N802
        self.state.navigate.emit("home", None)
        super().mousePressEvent(e)
