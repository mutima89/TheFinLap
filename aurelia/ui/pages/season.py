"""Run the Month: the Season game loop. Briefing and levers → projection → close the month → results."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QPushButton, QScrollArea, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget)

from ...game import season as S
from ...model.assumptions import SEGMENT_LABELS
from .. import icons, theme
from ..chrome import MONTHS
from ..visuals import Avatar, BridgeChart, Hero, RangeBar, short_money
from ..widgets import card, confirm, label

KIND_CHIP = {"market": ("MARKET", "ChipBlue"), "decision": ("DECIDE", "ChipGold"), "issue": ("ISSUE", "ChipBad")}
STAFFING = [("lean", "Lean"), ("standard", "Standard"), ("premium", "Premium")]


def _scroll(widget: QWidget) -> QScrollArea:
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.NoFrame)
    sa.setWidget(widget)
    return sa


def _clear(lay) -> None:
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear(it.layout())


def _hrule() -> QFrame:
    f = QFrame()
    f.setObjectName("Rule")
    return f


class BriefCard(QFrame):
    """One briefing item; decision and issue cards carry exclusive choice buttons."""

    def __init__(self, c, chosen: str | None, on_choice):
        super().__init__()
        self.card = c
        self.setObjectName("CardGold" if c.kind == "decision" else "Card")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(9)
        top = QHBoxLayout()
        top.setSpacing(8)
        text, obj = KIND_CHIP.get(c.kind, ("NOTE", "Chip"))
        top.addWidget(label(text, obj))
        if getattr(c, "source", ""):
            top.addWidget(label(c.source, "Muted"))
        top.addStretch(1)
        v.addLayout(top)
        v.addWidget(label(c.title, "H3", wrap=True))
        v.addWidget(label(c.body, "Body", wrap=True))
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        if c.choices:
            row = QGridLayout()
            row.setSpacing(8)
            for i, ch in enumerate(c.choices):
                cid, lab_, hint = ch[0], ch[1], (ch[2] if len(ch) > 2 else "")
                b = QPushButton(lab_)
                b.setObjectName("Choice")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(hint)
                b.setProperty("choice", cid)
                b.setChecked(cid == chosen)
                self.group.addButton(b)
                row.addWidget(b, 0, i)
            v.addLayout(row)
            self.hint = label("", "Muted", wrap=True)
            v.addWidget(self.hint)
            self.group.buttonClicked.connect(lambda b: (self._show_hint(b), on_choice(c.id, b.property("choice"))))
            if chosen:
                for b in self.group.buttons():
                    if b.isChecked():
                        self._show_hint(b)

    def _show_hint(self, b):
        self.hint.setText(b.toolTip())


class LeverRow(QWidget):
    def __init__(self, text: str, value: float, on_change):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)
        lab_ = label(text)
        lab_.setFixedWidth(170)
        h.addWidget(lab_)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(-20, 20)
        self.slider.setValue(int(round(value * 100)))
        self.slider.setPageStep(2)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.setAccessibleName(f"{text} rate against market")
        h.addWidget(self.slider, 1)
        self.out = label("")
        self.out.setFixedWidth(84)
        self.out.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.out)
        self.slider.valueChanged.connect(lambda v: (self._show(v), on_change()))
        self._show(self.slider.value())

    def _show(self, v: int):
        p = theme.current()
        self.out.setText("At market" if v == 0 else f"{v:+d}%")
        self.out.setStyleSheet(f"font-weight: 700; color: {p.teal if v > 0 else (p.blue if v < 0 else p.text)};")

    def value(self) -> float:
        return self.slider.value() / 100.0


class SeasonPage(QWidget):
    def __init__(self, state):
        super().__init__()
        self.setObjectName("Page")
        self.state = state
        self.season = S.load(state.db) or S.new_season()
        self.choices: dict[str, str] = {}
        self.levers = S.Levers.default()
        self._last_record: dict | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.views = QStackedWidget()
        root.addWidget(self.views)
        self.turn = QWidget()
        self.results = QWidget()
        self.review = QWidget()
        for w in (self.turn, self.results, self.review):
            w.setObjectName("PageBody")
            self.views.addWidget(_scroll(w))
        self._build_turn()
        self._build_results()
        self._build_review()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(220)
        self._timer.timeout.connect(self._project)

    # ---- turn view -------------------------------------------------------------------------
    def _build_turn(self):
        v = QVBoxLayout(self.turn)
        v.setContentsMargins(32, 22, 32, 28)
        v.setSpacing(18)
        head = QHBoxLayout()
        head.setSpacing(16)
        self.t_title = label("", "H1")
        self.t_meta = label("", "Muted")
        head.addWidget(self.t_title)
        head.addWidget(self.t_meta, 0, Qt.AlignBottom)
        head.addStretch(1)
        self.t_done = label("", "Muted")
        head.addWidget(self.t_done, 0, Qt.AlignBottom)
        v.addLayout(head)

        cols = QHBoxLayout()
        cols.setSpacing(22)
        # briefing
        bw = QWidget()
        bw.setFixedWidth(430)
        self.brief = QVBoxLayout(bw)
        self.brief.setContentsMargins(0, 0, 0, 0)
        self.brief.setSpacing(14)
        cols.addWidget(bw, 0, Qt.AlignTop)

        # levers
        lv, ll = card(margins=24, spacing=16)
        lh = QHBoxLayout()
        lh.addWidget(label("Your levers", "H2"))
        lh.addSpacing(8)
        lh.addWidget(label("Room rates are set against the market for each segment", "Muted"), 0, Qt.AlignBottom)
        lh.addStretch(1)
        reset = QPushButton("Reset")
        reset.setObjectName("Ghost")
        reset.setCursor(Qt.PointingHandCursor)
        reset.clicked.connect(self._reset_levers)
        lh.addWidget(reset)
        ll.addLayout(lh)
        self.rate_rows: dict[str, LeverRow] = {}
        for seg in S.RATE_SEGMENTS:
            r = LeverRow(SEGMENT_LABELS.get(seg, seg), self.levers.rate_position.get(seg, 0.0), self._changed)
            self.rate_rows[seg] = r
            ll.addWidget(r)
        ll.addWidget(_hrule())
        g = QGridLayout()
        g.setHorizontalSpacing(24)
        g.setVerticalSpacing(8)
        g.addWidget(label("Staffing level", "H3"), 0, 0)
        seg_box = QFrame()
        seg_box.setObjectName("SegmentBox")
        sb = QHBoxLayout(seg_box)
        sb.setContentsMargins(4, 4, 4, 4)
        sb.setSpacing(4)
        self.staff_group = QButtonGroup(self)
        for key, text in STAFFING:
            b = QPushButton(text)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("key", key)
            self.staff_group.addButton(b)
            sb.addWidget(b)
        self.staff_group.buttonClicked.connect(lambda _b: self._changed())
        g.addWidget(seg_box, 1, 0)
        self.staff_note = label("", "Muted", wrap=True)
        g.addWidget(self.staff_note, 2, 0)
        g.addWidget(label("Marketing this month", "H3"), 0, 1)
        mk = QHBoxLayout()
        self.mkt = QSlider(Qt.Horizontal)
        self.mkt.setRange(0, 40)  # × SAR 10k
        self.mkt.setCursor(Qt.PointingHandCursor)
        self.mkt.setAccessibleName("Marketing spend this month")
        self.mkt_out = label("")
        self.mkt_out.setFixedWidth(92)
        self.mkt_out.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        mk.addWidget(self.mkt, 1)
        mk.addWidget(self.mkt_out)
        g.addLayout(mk, 1, 1)
        g.addWidget(label("Spend lifts direct bookings, mostly next month.", "Muted", wrap=True), 2, 1)
        self.mkt.valueChanged.connect(lambda v: (self.mkt_out.setText(f"SAR {v * 10:,}k"), self._changed()))
        g.setColumnStretch(0, 1)
        g.setColumnStretch(1, 1)
        ll.addLayout(g)
        ll.addStretch(1)
        coach = QFrame()
        coach.setObjectName("Inset")
        cl = QHBoxLayout(coach)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(12)
        ic = label("")
        ic.setPixmap(icons.pixmap("info", theme.current().teal, 18))
        cl.addWidget(ic, 0, Qt.AlignTop)
        self.coach = label("", "Body", wrap=True)
        cl.addWidget(self.coach, 1)
        ll.addWidget(coach)
        cols.addWidget(lv, 1)

        # projection
        pw = QWidget()
        pw.setFixedWidth(340)
        pr = QVBoxLayout(pw)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.setSpacing(14)
        pc, pl = card(margins=20, spacing=12)
        pl.addWidget(label("Projected month", "H2"))
        pl.addWidget(label("EBITDA range across likely demand outcomes", "Muted", wrap=True))
        self.range = RangeBar()
        pl.addWidget(self.range)
        rr = QHBoxLayout()
        self.p_low = label("", "Muted")
        self.p_likely = label("")
        self.p_high = label("", "Muted")
        rr.addWidget(self.p_low)
        rr.addStretch(1)
        rr.addWidget(self.p_likely)
        rr.addStretch(1)
        rr.addWidget(self.p_high)
        pl.addLayout(rr)
        pl.addWidget(_hrule())
        self.p_grid = QGridLayout()
        self.p_grid.setVerticalSpacing(10)
        self.p_vals = {}
        for i, (k, t) in enumerate((("occupancy", "Occupancy"), ("adr", "ADR"), ("revpar", "RevPAR"),
                                     ("closing_cash", "Closing cash"), ("guest_score", "Guest score"))):
            self.p_grid.addWidget(label(t, "Body"), i, 0)
            val = label("—")
            val.setAlignment(Qt.AlignRight)
            val.setStyleSheet("font-weight: 600;")
            self.p_vals[k] = val
            self.p_grid.addWidget(val, i, 1)
        pl.addLayout(self.p_grid)
        pr.addWidget(pc)
        st, stl = card(margins=18, spacing=8)
        stl.addWidget(label("STAKES THIS TURN", "Overline"))
        self.stakes = label("", "Body", wrap=True)
        stl.addWidget(self.stakes)
        pr.addWidget(st)
        pr.addStretch(1)
        self.close_btn = QPushButton("Close the month")
        self.close_btn.setObjectName("Hero")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setLayoutDirection(Qt.RightToLeft)
        self.close_btn.clicked.connect(self._close_month)
        pr.addWidget(self.close_btn)
        cols.addWidget(pw, 0)
        v.addLayout(cols, 1)

    def _reset_levers(self):
        self.levers = S.Levers.default()
        self._load_levers()
        self._changed()

    def _load_levers(self):
        for seg, row in self.rate_rows.items():
            row.slider.blockSignals(True)
            row.slider.setValue(int(round(self.levers.rate_position.get(seg, 0.0) * 100)))
            row._show(row.slider.value())
            row.slider.blockSignals(False)
        for b in self.staff_group.buttons():
            b.setChecked(b.property("key") == self.levers.staffing)
        self.mkt.blockSignals(True)
        self.mkt.setValue(int(round(self.levers.marketing / 10_000)))
        self.mkt.blockSignals(False)
        self.mkt_out.setText(f"SAR {self.mkt.value() * 10:,}k")

    def _read_levers(self) -> S.Levers:
        lv = S.Levers.default()
        lv.rate_position = {seg: r.value() for seg, r in self.rate_rows.items()}
        b = self.staff_group.checkedButton()
        lv.staffing = b.property("key") if b else "standard"
        lv.marketing = float(self.mkt.value() * 10_000)
        return lv

    def _choice(self, card_id: str, choice_id: str):
        self.choices[card_id] = choice_id
        self._changed()

    def _changed(self):
        self.levers = self._read_levers()
        notes = {"lean": "Lean rosters cut payroll, but guest scores suffer when the hotel is busy.",
                 "standard": "Standard rosters match the budget.",
                 "premium": "Premium service costs more and lifts guest scores, which support future demand."}
        self.staff_note.setText(notes.get(self.levers.staffing, ""))
        self._update_done()
        self._timer.start()

    def _update_done(self):
        need = [c for c in self._cards if c.choices]
        done = sum(1 for c in need if c.id in self.choices)
        self.t_done.setText(f"{done} of {len(need)} decisions made" if need else "No decisions needed this month")
        self.close_btn.setEnabled(done == len(need))
        self.close_btn.setToolTip("" if done == len(need) else "Decide every briefing item first")

    def _project(self):
        try:
            pj = S.project(self.season, self.levers, self.choices)
        except Exception as exc:  # noqa: BLE001 – keep the turn usable even if a projection fails
            self.coach.setText(f"Projection unavailable: {exc}")
            return
        self.range.set(pj.low, pj.likely, pj.high, pj.budget_ebitda)
        self.p_low.setText(short_money(pj.low))
        self.p_high.setText(short_money(pj.high))
        p = theme.current()
        self.p_likely.setText(f"{short_money(pj.likely)} likely")
        self.p_likely.setStyleSheet(f"color: {p.teal}; font-weight: 800; font-size: 15px;")
        k = pj.kpis
        self.p_vals["occupancy"].setText(f"{k['occupancy'] * 100:.1f}%")
        self.p_vals["adr"].setText(f"SAR {k['adr']:,.0f}")
        self.p_vals["revpar"].setText(f"SAR {k['revpar']:,.0f}")
        self.p_vals["closing_cash"].setText(short_money(k["closing_cash"]))
        self.p_vals["guest_score"].setText(f"{k['guest_score']:.1f}")
        self.coach.setText(getattr(pj, "coach", "") or self._coach_text(pj))

    def _coach_text(self, pj) -> str:
        gap = pj.likely - pj.budget_ebitda
        if gap >= 0:
            return (f"Your plan is projected {short_money(gap)} above budget. The range is wide because demand is "
                    "uncertain; the low end is what a soft month would look like.")
        return (f"Your plan is projected {short_money(-gap)} below budget. Look at where rates sit against the "
                "market, and whether payroll matches the demand you expect.")

    def _close_month(self):
        if not self.close_btn.isEnabled():
            return
        if not confirm(self, "Close the month", f"Lock in your decisions for {MONTHS[self.season.month - 1]}? "
                                                "You cannot change them afterwards."):
            return
        rec = S.close_month(self.season, self.levers, self.choices)
        S.save(self.state.db, self.season)
        self._last_record = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
        self.choices = {}
        self._show_results(self._last_record)
        w = self.window()
        if hasattr(w, "refresh_chrome"):
            w.refresh_chrome()

    # ---- results view ----------------------------------------------------------------------
    def _build_results(self):
        v = QVBoxLayout(self.results)
        v.setContentsMargins(32, 22, 32, 28)
        v.setSpacing(20)
        head = QHBoxLayout()
        head.addWidget(label("MONTH CLOSE", "Overline"), 0, Qt.AlignBottom)
        head.addSpacing(12)
        self.r_title = label("", "H1")
        head.addWidget(self.r_title)
        head.addStretch(1)
        self.next_btn = QPushButton("")
        self.next_btn.setObjectName("Primary")
        self.next_btn.setCursor(Qt.PointingHandCursor)
        self.next_btn.setLayoutDirection(Qt.RightToLeft)
        self.next_btn.clicked.connect(self._next)
        head.addWidget(self.next_btn)
        v.addLayout(head)
        cols = QHBoxLayout()
        cols.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(20)
        self.r_hero = Hero("good")
        hh = QHBoxLayout(self.r_hero)
        hh.setContentsMargins(30, 26, 30, 26)
        hh.setSpacing(36)
        hv = QVBoxLayout()
        hv.setSpacing(6)
        self.r_verdict = label("", "ChipGood")
        hv.addWidget(self.r_verdict, 0, Qt.AlignLeft)
        hv.addSpacing(4)
        hv.addWidget(label("EBITDA for the month", "Muted"))
        self.r_ebitda = label("", "Display")
        hv.addWidget(self.r_ebitda)
        self.r_vs = label("", "Good")
        hv.addWidget(self.r_vs)
        hh.addLayout(hv)
        hh.addStretch(1)
        self.r_stats = QGridLayout()
        self.r_stats.setHorizontalSpacing(30)
        hh.addLayout(self.r_stats)
        left.addWidget(self.r_hero)
        bc, bl = card(margins=22, spacing=12)
        bh = QHBoxLayout()
        bh.addWidget(label("From budget to actual", "H2"))
        bh.addSpacing(10)
        bh.addWidget(label("EBITDA bridge, SAR thousands", "Muted"), 0, Qt.AlignBottom)
        bh.addStretch(1)
        bl.addLayout(bh)
        self.bridge = BridgeChart(300)
        bl.addWidget(self.bridge)
        note = QFrame()
        note.setObjectName("Inset")
        nl = QHBoxLayout(note)
        nl.setContentsMargins(14, 12, 14, 12)
        nl.setSpacing(12)
        ic = label("")
        ic.setPixmap(icons.pixmap("search", theme.current().blue, 18))
        nl.addWidget(ic, 0, Qt.AlignTop)
        self.r_note = label("", "Body", wrap=True)
        self.r_note.setTextFormat(Qt.RichText)
        nl.addWidget(self.r_note, 1)
        bl.addWidget(note)
        left.addWidget(bc, 1)
        cols.addLayout(left, 1)

        right_w = QWidget()
        right_w.setFixedWidth(380)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(16)
        qc, ql = card(margins=20, spacing=12)
        who = QHBoxLayout()
        who.setSpacing(12)
        who.addWidget(Avatar("LR", 40))
        wl = QVBoxLayout()
        wl.setSpacing(0)
        wl.addWidget(label("Layla Rahman", "H3"))
        wl.addWidget(label("Asset manager (fictional)", "Muted"))
        who.addLayout(wl, 1)
        ql.addLayout(who)
        self.r_quote = label("", "Quote", wrap=True)
        ql.addWidget(self.r_quote)
        right.addWidget(qc)
        cc, self.r_carried = card(margins=18, spacing=12)
        self.r_carried.addWidget(label("CARRIED INTO NEXT MONTH", "Overline"))
        self.r_carried_box = QVBoxLayout()
        self.r_carried_box.setSpacing(10)
        self.r_carried.addLayout(self.r_carried_box)
        right.addWidget(cc)
        self.r_ach_box = QVBoxLayout()
        self.r_ach_box.setSpacing(12)
        right.addLayout(self.r_ach_box)
        right.addStretch(1)
        cols.addWidget(right_w, 0)
        v.addLayout(cols, 1)

    def _show_results(self, r: dict):
        p = theme.current()
        m = r["month"]
        self.r_title.setText(r.get("label") or f"{MONTHS[m - 1]} 2027")
        if self.season.month > 12 or getattr(self.season, "over", False):
            self.next_btn.setText("See the season review")
        else:
            self.next_btn.setText(f"Go to {MONTHS[self.season.month - 1]}")
        self.next_btn.setIcon(icons.icon("arrow-right", p.on_accent, 15))
        a, b = r["actual"], r["budget"]
        verdict = r.get("verdict", "on")
        self.r_hero.tone = {"beat": "good", "missed": "bad"}.get(verdict, "gold")
        self.r_hero.update()
        self.r_verdict.setText({"beat": "Beat budget", "missed": "Missed budget"}.get(verdict, "On budget"))
        self.r_verdict.setStyleSheet("" if verdict == "beat" else
                                     f"background: {p.bad if verdict == 'missed' else p.teal}; color: {p.on_accent};")
        self.r_ebitda.setText(short_money(a["ebitda"]))
        d = a["ebitda"] - b["ebitda"]
        pct = d / abs(b["ebitda"]) * 100 if b["ebitda"] else 0
        self.r_vs.setText(f"{'+' if d >= 0 else '−'}{short_money(abs(d))} ({pct:+.1f}%) against a budget of "
                          f"{short_money(b['ebitda'])}")
        self.r_vs.setObjectName("Good" if d >= 0 else "Bad")
        self.r_vs.style().unpolish(self.r_vs)
        self.r_vs.style().polish(self.r_vs)
        _clear(self.r_stats)
        conf_after = self.season.confidence
        conf_before = conf_after - r.get("confidence_delta", 0)
        stats = [("Occupancy", f"{a['occupancy'] * 100:.1f}%", f"{(a['occupancy'] - b['occupancy']) * 100:+.1f} pts",
                  a["occupancy"] >= b["occupancy"]),
                 ("ADR", f"SAR {a['adr']:,.0f}", f"{(a['adr'] - b['adr']) / b['adr'] * 100:+.1f}%", a["adr"] >= b["adr"]),
                 ("Owner confidence", f"{conf_before:.0f} → {conf_after:.0f}", f"{r.get('confidence_delta', 0):+.0f}",
                  r.get("confidence_delta", 0) >= 0)]
        for i, (t, val, dl, good) in enumerate(stats):
            self.r_stats.addWidget(label(t, "Muted"), 0, i)
            vl = label(val)
            vl.setStyleSheet("font-size: 21px; font-weight: 600;")
            self.r_stats.addWidget(vl, 1, i)
            self.r_stats.addWidget(label(dl, "Good" if good else "Bad"), 2, i)
        self.bridge.set(("Budget", b["ebitda"]), [tuple(x) for x in r["bridge"]], ("Actual", a["ebitda"]))
        meas = r.get("measured", [])
        unex = r.get("unexplained", [])
        html = ""
        if meas:
            html += f"<b style='color:{p.text}'>Measured</b> by the model: " + " ".join(meas[:3])
        if unex:
            html += f"<br><b style='color:{p.text}'>Not explained</b> by the data: " + " ".join(unex[:2])
        self.r_note.setText(html or "Every movement in the bridge comes straight from the engine's line items.")
        self.r_quote.setText(f"“{r.get('owner_quote', '')}”")
        _clear(self.r_carried_box)
        dot = {"good": p.good, "bad": p.bad, "info": p.blue}
        for tone, text in r.get("carried", []) or [("info", "Nothing carries over from this month.")]:
            row = QHBoxLayout()
            row.setSpacing(10)
            d_ = label("●")
            d_.setStyleSheet(f"color: {dot.get(tone, p.blue)}; font-size: 10px;")
            row.addWidget(d_, 0, Qt.AlignTop)
            row.addWidget(label(text, wrap=True), 1)
            w = QWidget()
            w.setLayout(row)
            self.r_carried_box.addWidget(w)
        _clear(self.r_ach_box)
        for title, desc in r.get("achievements", []):
            f = QFrame()
            f.setObjectName("CardGold")
            fl = QHBoxLayout(f)
            fl.setContentsMargins(18, 16, 18, 16)
            fl.setSpacing(16)
            badge = label("")
            badge.setFixedSize(48, 48)
            badge.setAlignment(Qt.AlignCenter)
            badge.setPixmap(icons.pixmap("star", p.on_accent, 26))
            badge.setStyleSheet(f"background: {p.teal}; border-radius: 13px;")
            fl.addWidget(badge)
            tv = QVBoxLayout()
            tv.setSpacing(3)
            tv.addWidget(label(f"SKILL EARNED · +{r.get('xp_gained', 0)} XP", "Overline"))
            tv.addWidget(label(title, "H2"))
            tv.addWidget(label(desc, "Muted", wrap=True))
            fl.addLayout(tv, 1)
            self.r_ach_box.addWidget(f)
        if not r.get("achievements"):
            f, fl = card(margins=18, spacing=4)
            fl.addWidget(label(f"+{r.get('xp_gained', 0)} XP", "H2"))
            fl.addWidget(label("Beat budget, meet objectives and keep guests happy to earn skills.", "Muted",
                               wrap=True))
            self.r_ach_box.addWidget(f)
        self.views.setCurrentIndex(1)

    def _next(self):
        if self.season.month > 12 or getattr(self.season, "over", False):
            self._show_review()
        else:
            self.refresh()

    # ---- season review ---------------------------------------------------------------------
    def _build_review(self):
        v = QVBoxLayout(self.review)
        v.setContentsMargins(32, 26, 32, 28)
        v.setSpacing(20)
        self.rv_hero = Hero("gold")
        hl = QHBoxLayout(self.rv_hero)
        hl.setContentsMargins(34, 30, 34, 30)
        hl.setSpacing(30)
        gv = QVBoxLayout()
        gv.addWidget(label("SEASON REVIEW · FY2027", "Eyebrow"))
        self.rv_title = label("", "Display")
        gv.addWidget(self.rv_title)
        self.rv_sub = label("", "Body", wrap=True)
        gv.addWidget(self.rv_sub)
        hl.addLayout(gv, 1)
        self.rv_grade = label("")
        self.rv_grade.setAlignment(Qt.AlignCenter)
        self.rv_grade.setFixedSize(132, 132)
        hl.addWidget(self.rv_grade)
        v.addWidget(self.rv_hero)
        sc, self.rv_lines = card(margins=24, spacing=10)
        v.addWidget(sc)
        row = QHBoxLayout()
        row.addStretch(1)
        nb = QPushButton("Start a new season")
        nb.setObjectName("Primary")
        nb.setCursor(Qt.PointingHandCursor)
        nb.clicked.connect(self._new_season)
        row.addWidget(nb)
        v.addLayout(row)
        v.addStretch(1)

    def _show_review(self):
        p = theme.current()
        rv = S.final_review(self.season)
        self.rv_title.setText(rv.get("headline") or f"{rv.get('title', '')}")
        self.rv_sub.setText(" ".join(rv.get("summary", [])[:1]))
        self.rv_grade.setText(rv.get("grade", "—"))
        self.rv_grade.setStyleSheet(f"background: {p.teal}; color: {p.on_accent}; border-radius: 30px; "
                                    f"font-family: '{theme.DISPLAY_FONT}'; font-size: 68px;")
        _clear(self.rv_lines)
        self.rv_lines.addWidget(label("How the year went", "H2"))
        for line in rv.get("summary", []):
            self.rv_lines.addWidget(label(f"•  {line}", "Body", wrap=True))
        self.rv_lines.addWidget(label("Practice feedback on a fictional hotel, not a qualification.", "Muted"))
        self.views.setCurrentIndex(2)

    def _new_season(self):
        if not confirm(self, "Start a new season", "Start FY2027 again with a new set of events? Your XP and title "
                                                   "are kept; this season's months are archived."):
            return
        xp = self.season.xp
        self.season = S.new_season()
        self.season.xp = xp
        S.save(self.state.db, self.season)
        self.refresh()
        w = self.window()
        if hasattr(w, "refresh_chrome"):
            w.refresh_chrome()

    # ---- page protocol ---------------------------------------------------------------------
    def focus_item(self, payload):
        if payload == "review" and self.season.month > 12:
            self._show_review()

    def refresh(self) -> None:
        self.season = S.load(self.state.db) or self.season
        sn = self.season
        if sn.month > 12 or getattr(sn, "over", False):
            if self.views.currentIndex() != 1:
                self._show_review()
            return
        m = sn.month
        p = theme.current()
        self.t_title.setText(f"{MONTHS[m - 1]} 2027")
        budget = S.season_series(sn)["budget"][m - 1]
        self.t_meta.setText(f"Month {m} of 12 · budget EBITDA {short_money(budget)}")
        self._cards = S.briefing(sn)
        self.choices = {k: v for k, v in self.choices.items() if any(c.id == k for c in self._cards)}
        _clear(self.brief)
        self.brief.addWidget(label("BRIEFING", "Overline"))
        for c in self._cards:
            self.brief.addWidget(BriefCard(c, self.choices.get(c.id), self._choice))
        self.brief.addStretch(1)
        self._load_levers()
        self.stakes.setText(getattr(S, "STAKES_TEXT", "Beat budget to raise owner confidence; miss by more than 5% "
                                                    "and it falls. Breach the lenders' cash floor and the season "
                                                    "ends."))
        self.close_btn.setIcon(icons.icon("arrow-right", p.on_accent, 16))
        self._changed()
        self._timer.stop()
        self._project()
        self.views.setCurrentIndex(0)
