"""Command Center: the home screen. Next turn, season so far, objectives, the owner's view and what to learn next."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ...game import season as S
from .. import icons, theme
from ..chrome import MONTHS
from ..visuals import Avatar, Hero, ProgressLine, SeasonBars, short_money
from ..widgets import KPICard, Page, card, clear_layout, label


def next_topic(db):
    from ...learning import content as C, progress as P
    tbs = C.topics_by_stage()
    for stage in C.STAGES:
        if not P.stage_unlocked(db, stage, tbs):
            return None
        for tid in tbs.get(stage, []):
            if not P.topic_complete(db, tid):
                return C.topic(tid)
    return None


class CommandCenterPage(Page):
    def __init__(self, state):
        super().__init__("", "")
        self.title_label.setVisible(False)
        self.state = state
        self.body.setContentsMargins(36, 28, 36, 32)
        self.body.setSpacing(22)

        cols = QHBoxLayout()
        cols.setSpacing(26)
        left = QVBoxLayout()
        left.setSpacing(22)
        right = QVBoxLayout()
        right.setSpacing(18)
        cols.addLayout(left, 1)
        side = QWidget()
        side.setFixedWidth(350)
        side.setLayout(right)
        right.setContentsMargins(0, 0, 0, 0)
        cols.addWidget(side, 0, Qt.AlignTop)
        self.body.addLayout(cols)

        # hero
        self.hero = Hero("gold")
        hl = QHBoxLayout(self.hero)
        hl.setContentsMargins(32, 28, 32, 28)
        hl.setSpacing(24)
        txt = QVBoxLayout()
        txt.setSpacing(10)
        self.hero_eyebrow = label("YOUR NEXT TURN", "Eyebrow")
        self.hero_title = label("", "Display")
        self.hero_title.setWordWrap(True)
        self.hero_body = label("", "Body", wrap=True)
        self.hero_body.setMaximumWidth(660)
        txt.addWidget(self.hero_eyebrow)
        txt.addWidget(self.hero_title)
        txt.addWidget(self.hero_body)
        hl.addLayout(txt, 1)
        self.hero_btn = QPushButton("")
        self.hero_btn.setObjectName("Hero")
        self.hero_btn.setCursor(Qt.PointingHandCursor)
        self.hero_btn.setLayoutDirection(Qt.RightToLeft)
        self.hero_btn.clicked.connect(self._hero_clicked)
        hl.addWidget(self.hero_btn, 0, Qt.AlignBottom)
        left.addWidget(self.hero)

        # KPI cards
        g = QGridLayout()
        g.setSpacing(16)
        self.k_ebitda = KPICard("ebitda", "EBITDA to date", "Earnings before interest, tax, depreciation and "
                                "amortisation for the months you have played, against the same months' budget.")
        self.k_revpar = KPICard("revpar", "RevPAR to date", "Room revenue per available room.")
        self.k_occ = KPICard("occupancy", "Occupancy to date", "Occupied rooms ÷ available rooms.")
        self.k_cash = KPICard("cash", "Cash vs lenders' floor",
                              "The lenders require cash to stay above the floor. Breaching it ends the season.")
        self.cash_bar = ProgressLine(8)
        self.k_cash.layout().addWidget(self.cash_bar)
        for i, k in enumerate((self.k_ebitda, self.k_revpar, self.k_occ, self.k_cash)):
            k.value.setStyleSheet("font-size: 22px;")
            k.setMinimumWidth(0)
            k.clicked.connect(lambda _k: self.state.navigate.emit("season", None))
            g.addWidget(k, 0, i)
        left.addLayout(g)

        # season chart
        sc, sl = card(margins=22, spacing=12)
        head = QHBoxLayout()
        head.addWidget(label("The season so far", "H2"))
        head.addSpacing(10)
        head.addWidget(label("EBITDA by month against budget", "Muted"), 0, Qt.AlignBottom)
        head.addStretch(1)
        sl.addLayout(head)
        self.bars = SeasonBars(200)
        sl.addWidget(self.bars)
        leg = QHBoxLayout()
        leg.setSpacing(18)
        p = theme.current()
        self._dots = []
        for key, text in (("good", "Beat budget"), ("bad", "Missed budget"), ("surface3", "Budget, still to play")):
            dot = label("■")
            self._dots.append((dot, key))
            leg.addWidget(dot)
            leg.addWidget(label(text, "Muted"))
            leg.addSpacing(6)
        leg.addStretch(1)
        self._legend = leg
        sl.addLayout(leg)
        left.addWidget(sc)
        left.addStretch(1)

        # objectives
        oc, self.obj_lay = card(margins=20, spacing=12)
        self.obj_title = label("Objectives", "H2")
        self.obj_lay.addWidget(self.obj_title)
        self.obj_box = QVBoxLayout()
        self.obj_box.setSpacing(14)
        self.obj_lay.addLayout(self.obj_box)
        right.addWidget(oc)

        # owner
        qc, ql = card(margins=20, spacing=12)
        who = QHBoxLayout()
        who.setSpacing(12)
        who.addWidget(Avatar("LR", 40))
        wl = QVBoxLayout()
        wl.setSpacing(0)
        wl.addWidget(label("Layla Rahman", "H3"))
        wl.addWidget(label("Asset manager for the owners (fictional)", "Muted"))
        who.addLayout(wl, 1)
        ql.addLayout(who)
        self.quote = label("", "Quote", wrap=True)
        ql.addWidget(self.quote)
        right.addWidget(qc)

        # learning
        lc, ll = card(margins=20, spacing=10)
        ll.addWidget(label("LEARN BEFORE YOU PLAY", "Overline"))
        self.learn_title = label("", "H2", wrap=True)
        self.learn_body = label("", "Body", wrap=True)
        ll.addWidget(self.learn_title)
        ll.addWidget(self.learn_body)
        b = QPushButton("Open the Academy")
        b.setObjectName("Ghost")
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(f"text-align: left; padding-left: 0; color: {p.teal};")
        b.clicked.connect(self._open_lesson)
        ll.addWidget(b, 0, Qt.AlignLeft)
        right.addWidget(lc)
        right.addStretch(1)

    # ---------------------------------------------------------------------------------------
    def _season(self):
        return S.load(self.state.db) or S.new_season()

    def _hero_clicked(self):
        sn = self._season()
        if sn.finished:
            self.state.navigate.emit("season", "review")
        else:
            self.state.navigate.emit("season", None)

    def _open_lesson(self):
        t = next_topic(self.state.db)
        self.state.navigate.emit("learn", t.id if t else None)

    def refresh(self) -> None:
        p = theme.current()
        sn = self._season()
        db = self.state.db
        hist = sn.history
        # hero
        if sn.finished:
            rv = S.final_review(sn)
            self.hero_eyebrow.setText("SEASON COMPLETE")
            self.hero_title.setText(f"FY2027 closed · grade {rv['grade']}")
            self.hero_body.setText(" ".join(rv.get("summary", [])[:2]))
            self.hero_btn.setText("Review the season")
        else:
            m = sn.month
            cards = S.briefing(sn)
            budget = S.season_series(sn)["budget"][m - 1]
            self.hero_eyebrow.setText("YOUR NEXT TURN" if hist else "YOUR FIRST TURN")
            self.hero_title.setText(f"{MONTHS[m - 1]} at The Aurelia Grand")
            items = "; ".join(c.title for c in cards[:3])
            self.hero_body.setText(f"On your desk: {items}. The owners expect EBITDA of {short_money(budget)} this month.")
            self.hero_btn.setText(f"Start {MONTHS[m - 1]}")
        self.hero_btn.setIcon(icons.icon("arrow-right", p.on_accent, 16))

        # KPIs
        ser = S.season_series(sn)
        played = [h for h in hist]
        if played:
            act = [h["actual"] for h in played]
            bud = [h["budget"] for h in played]
            e_a, e_b = sum(a["ebitda"] for a in act), sum(b["ebitda"] for b in bud)
            d = (e_a - e_b) / abs(e_b) if e_b else 0
            self.k_ebitda.set(short_money(e_a), f"{d * 100:+.1f}% vs budget", d >= 0,
                              spark=[a["ebitda"] for a in act], spark_ref=[b["ebitda"] for b in bud])
            rp = sum(a["revpar"] * 1 for a in act) / len(act)
            rb = sum(b["revpar"] for b in bud) / len(bud)
            self.k_revpar.set(f"SAR {rp:,.0f}", f"{(rp - rb) / rb * 100:+.1f}% vs budget", rp >= rb,
                              spark=[a["revpar"] for a in act], spark_ref=[b["revpar"] for b in bud])
            oa = sum(a["occupancy"] for a in act) / len(act)
            ob = sum(b["occupancy"] for b in bud) / len(bud)
            self.k_occ.set(f"{oa * 100:.1f}%", f"{(oa - ob) * 100:+.1f} pts vs budget", oa >= ob,
                           spark=[a["occupancy"] for a in act], spark_ref=[b["occupancy"] for b in bud])
            cash = act[-1].get("closing_cash")
        else:
            b1 = ser["budget"][0]
            self.k_ebitda.set(short_money(sum(ser["budget"])), "Full-year budget")
            self.k_revpar.set("—", "After your first month")
            self.k_occ.set("—", "After your first month")
            cash = None
            _ = b1
        floor = S.CASH_FLOOR
        cash = sn.cash
        if cash is not None:
            self.k_cash.set(short_money(cash), f"{short_money(cash - floor)} headroom", cash >= floor)
            self.cash_bar.set(min(1.0, cash / (floor * 1.6)), "blue", marker=floor / (floor * 1.6))
        else:
            self.k_cash.set("—", f"Floor: {short_money(floor)}")
            self.cash_bar.set(0.0, "blue")

        for dot, key in self._dots:
            dot.setStyleSheet(f"color: {getattr(p, key)}; font-size: 15px;")
        # season bars
        cur = None if sn.finished else sn.month - 1
        self.bars.set([lab[:3] for lab in ser["labels"]], ser["actual"], ser["budget"], cur)

        # objectives
        clear_layout(self.obj_box)
        q = (min(sn.month, 12) - 1) // 3 + 1
        self.obj_title.setText(f"Q{q} objectives")
        tone = {"met": "good", "on_track": "good", "at_risk": "gold", "missed": "bad"}
        col = {"met": p.good, "on_track": p.good, "at_risk": p.teal, "missed": p.bad}
        for ob in S.objectives(sn):
            row = QVBoxLayout()
            row.setSpacing(6)
            top = QHBoxLayout()
            top.addWidget(label(ob.label, wrap=True), 1)
            v = label(ob.value_text)
            v.setStyleSheet(f"color: {col.get(ob.status, p.text)}; font-weight: 700;")
            top.addWidget(v, 0, Qt.AlignTop)
            row.addLayout(top)
            bar = ProgressLine(5)
            bar.set(ob.progress, tone.get(ob.status, "gold"))
            row.addWidget(bar)
            w = QWidget()
            w.setLayout(row)
            self.obj_box.addWidget(w)

        # owner quote
        if hist:
            self.quote.setText(f"“{hist[-1].get('owner_quote', '')}”")
        else:
            self.quote.setText("“Welcome aboard. Run the hotel month by month, keep the cash above the lenders’ floor, "
                               "and show me you can price with discipline.”")

        # learning
        t = next_topic(db)
        if t:
            self.learn_title.setText(t.title)
            self.learn_body.setText(f"Stage {t.stage} · {t.competency}. Each lesson has a worked example from the "
                                    "same engine that runs your season.")
        else:
            self.learn_title.setText("Every unlocked lesson is complete")
            self.learn_body.setText("Try a Boardroom case or the Capstone to prove it under pressure.")
