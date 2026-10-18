"""Home dashboard: current business position, KPIs, alerts, trends and learning status."""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QHBoxLayout, QGridLayout

from ...core.kpis import KPI_DEFINITIONS
from ..common import period_combo, period_slice, month_axis_labels
from ..widgets import Page, KPICard, Chart, card, label, Banner, money_formatter, pct_formatter, button
from .. import theme

CARDS = [
    ("occupancy", "Occupancy", "pct"), ("adr", "ADR", "currency_d"), ("revpar", "RevPAR", "currency_d"),
    ("total_revenue", "Total revenue", "currency"), ("gop", "GOP", "currency"), ("ebitda", "EBITDA", "currency"),
    ("net_income", "Net income", "currency"), ("closing_cash", "Closing cash", "currency"),
]
SOURCE_PAGE = {"occupancy": "rm", "adr": "rm", "revpar": "rm", "total_revenue": "statements", "gop": "statements",
               "ebitda": "statements", "net_income": "statements", "closing_cash": "statements"}


class DashboardPage(Page):
    def __init__(self, state, extras=None):
        super().__init__("The Aurelia Grand – business position",
                         "150-room luxury hotel · Aurelia Hospitality Group · fictional training data. "
                         "Every figure below is calculated live from the working scenario.")
        self.state = state
        self.extras = extras if extras is not None else {
            "budget_lbl": self._budget_text, "learn_lbl": self._learn_text, "decisions_lbl": self._decisions_text,
            "recent_lbl": self._recent_text}
        top = QHBoxLayout()
        self.scenario_lbl = label("", "H3")
        top.addWidget(self.scenario_lbl)
        top.addStretch(1)
        top.addWidget(label("Period:", "Muted"))
        self.period = period_combo()
        self.period.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.period)
        self.body.addLayout(top)

        self.banner = Banner()
        self.body.addWidget(self.banner)

        self.cards = {}
        g = QGridLayout()
        g.setSpacing(10)
        for i, (key, title, unit) in enumerate(CARDS):
            kd = KPI_DEFINITIONS.get(key)
            c = KPICard(key, title, kd.formula if kd else "")
            c.clicked.connect(self._open_source)
            self.cards[key] = c
            g.addWidget(c, i // 4, i % 4)
        self.body.addLayout(g)

        row = QHBoxLayout()
        f1, l1 = card()
        l1.addWidget(label("Revenue and EBITDA by month", "H3"))
        self.ch_rev = Chart(2.6)
        l1.addWidget(self.ch_rev)
        f2, l2 = card()
        l2.addWidget(label("Occupancy, ADR and RevPAR", "H3"))
        self.ch_rm = Chart(2.6)
        l2.addWidget(self.ch_rm)
        row.addWidget(f1, 1)
        row.addWidget(f2, 1)
        self.body.addLayout(row)

        row2 = QHBoxLayout()
        f3, l3 = card()
        l3.addWidget(label("Departmental contribution (period)", "H3"))
        self.ch_dept = Chart(2.4)
        l3.addWidget(self.ch_dept)
        f4, l4 = card()
        l4.addWidget(label("Cash, debt and operating cash flow", "H3"))
        self.ch_cash = Chart(2.4)
        l4.addWidget(self.ch_cash)
        row2.addWidget(f3, 1)
        row2.addWidget(f4, 1)
        self.body.addLayout(row2)

        row3 = QHBoxLayout()
        fa, la = card()
        la.addWidget(label("Alerts and model checks", "H3"))
        self.alerts = label("", wrap=True)
        la.addWidget(self.alerts)
        la.addStretch(1)
        row3.addWidget(fa, 1)
        fb, lb = card()
        lb.addWidget(label("Budget and forecast status", "H3"))
        self.budget_lbl = label("", wrap=True)
        lb.addWidget(self.budget_lbl)
        lb.addWidget(button("Open FP&A lab", lambda: self.state.navigate.emit("fpa", None)))
        lb.addStretch(1)
        row3.addWidget(fb, 1)
        fc, lc = card()
        lc.addWidget(label("Learning and competencies", "H3"))
        self.learn_lbl = label("", wrap=True)
        lc.addWidget(self.learn_lbl)
        lc.addWidget(button("Continue learning path", lambda: self.state.navigate.emit("learn", None)))
        lc.addStretch(1)
        row3.addWidget(fc, 1)
        self.body.addLayout(row3)

        row4 = QHBoxLayout()
        fd, ld = card()
        ld.addWidget(label("Active business decisions", "H3"))
        self.decisions_lbl = label("", wrap=True)
        ld.addWidget(self.decisions_lbl)
        ld.addWidget(button("Open Executive Decision Room", lambda: self.state.navigate.emit("decisions", None)))
        ld.addStretch(1)
        row4.addWidget(fd, 1)
        fe, le = card()
        le.addWidget(label("Recent modelling work", "H3"))
        self.recent_lbl = label("", wrap=True)
        le.addWidget(self.recent_lbl)
        le.addStretch(1)
        row4.addWidget(fe, 1)
        self.body.addLayout(row4)
        self.body.addStretch(1)

        state.results_changed.connect(self.refresh)
        state.progress_changed.connect(self.refresh)
        state.theme_changed.connect(lambda _n: self.refresh())

    # ---- status panels ------------------------------------------------------------------
    def _budget_text(self) -> str:
        from ..common import fpa_data
        st = self.state
        fpa, bname = fpa_data(st)
        vt = fpa.variance_table("ytd").set_index("key")
        rr = fpa.run_rate("ebitda")
        e = vt.loc["ebitda"]
        mat = int((vt["Material"] == "Yes").sum())
        ver = st.db.one("SELECT name, status, created_at FROM forecast_versions ORDER BY id DESC")
        acts = st.db.one("SELECT COUNT(*) AS n FROM action_plans WHERE status IN ('Open', 'In progress')")
        return (f"YTD to {fpa.actual.months[fpa.as_of - 1]} vs <b>{bname}</b>: EBITDA {st.money(e['Actual'])} "
                f"({e['F/U']} {st.money(e['Variance'])}).<br>FY latest estimate {st.money(rr['latest_estimate'])} vs "
                f"budget {st.money(rr['budget'])}.<br>{mat} material variance(s); {acts['n'] if acts else 0} open "
                "action(s).<br>" + (f"Latest forecast version: {ver['name']} ({ver['status']})." if ver else
                                    "No forecast version saved yet."))

    def _learn_text(self) -> str:
        from ...learning import content as C, progress as P
        db = self.state.db
        tbs = C.topics_by_stage()
        nxt = None
        for stage in C.STAGES:
            if not P.stage_unlocked(db, stage, tbs):
                break
            for tid in tbs.get(stage, []):
                if not P.topic_complete(db, tid):
                    nxt = C.topic(tid)
                    break
            if nxt:
                break
        prof = P.competency_profile(db)
        dem = [c.label for c in prof if c.level == "Demonstrated"]
        dev = [c.label for c in prof if c.level == "Developing"]
        step = next((s for s in P.STEPS if nxt and not P.step_passed(db, nxt.id, s)), None) if nxt else None
        obj = (f"Current objective: <b>{nxt.title}</b> (stage {nxt.stage}) — next step: {step}." if nxt else
               "All unlocked topics are complete.")
        return (obj + f"<br>Demonstrated: {', '.join(dem) or 'none yet'}.<br>Developing: {', '.join(dev) or '—'}."
                "<br><span style='color:gray'>Practice feedback, not a qualification.</span>")

    def _decisions_text(self) -> str:
        from ...analysis.decisions import CASES
        db = self.state.db
        done = {r["case_id"] for r in db.query("SELECT DISTINCT case_id FROM decisions")}
        todo = [c for c in CASES if c.id not in done]
        last = db.one("SELECT case_id, scores, ts FROM decisions ORDER BY id DESC")
        txt = f"{len(todo)} of {len(CASES)} cases awaiting a decision"
        if todo:
            txt += ": " + "; ".join(c.title for c in todo[:3]) + ("…" if len(todo) > 3 else "")
        if last:
            import json
            title = next((c.title for c in CASES if c.id == last["case_id"]), last["case_id"])
            txt += f"<br>Last decision: {title} — score {json.loads(last['scores']).get('overall', 0):.0f}."
        return txt

    def _recent_text(self) -> str:
        rows = self.state.db.audit_entries(limit=6)
        out = []
        for r in rows:
            what = r["path"] or ""
            out.append(f"{r['ts'][5:16].replace('T', ' ')} · {r['action']} {what} {('— ' + r['note']) if r['note'] else ''}")
        wb = self.state.db.one("SELECT workbook, score, ts FROM workbook_grades ORDER BY id DESC")
        if wb:
            out.append(f"Last workbook grade: {wb['workbook']} {wb['score']:.0f}%")
        return "<br>".join(out) or "No modelling work recorded yet."

    def _open_source(self, key: str) -> None:
        self.state.navigate.emit(SOURCE_PAGE.get(key, "statements"), key)

    def refresh(self) -> None:
        st = self.state
        res, cmp_ = st.result, st.compare_result
        sl = period_slice(res, self.period.currentData())
        k, kc = res.kpis(sl), cmp_.kpis(sl)
        dirty = " · unsaved what-if changes" if st.dirty else ""
        self.scenario_lbl.setText(f"Working scenario: {st.scenario_name}{dirty}   |   compared with: {st.compare_name}")
        for key, _t, unit in CARDS:
            u = "currency" if unit.startswith("currency") else unit
            dec = 0 if unit == "currency_d" else None
            v, b = k.get(key), kc.get(key)
            if v is None or b is None:
                self.cards[key].set(st.fmt(v, u, dec), "")
                continue
            d = v - b
            nature = KPI_DEFINITIONS[key].nature if key in KPI_DEFINITIONS else "higher_better"
            good = None if abs(d) < 1e-9 or nature == "context" else (d > 0) == (nature != "lower_better")
            if u == "pct":
                txt = f"{d * 100:+.1f} pts vs {st.compare_name}"
            else:
                txt = ("+" if d >= 0 else "−") + st.fmt(abs(d), u, dec) + f" vs {st.compare_name}"
            self.cards[key].set(st.fmt(v, u, dec), txt if abs(d) > 1e-9 else f"= {st.compare_name}", good)

        problems = list(res.warnings) + [f"Check failed: {c.name}" for c in res.checks if not c.passed]
        self.banner.set_text(" ".join(res.warnings))
        n_ok = sum(c.passed for c in res.checks)
        alerts = []
        if problems:
            alerts += [f"⚠ {p}" for p in problems]
        min_cash = float(res.s("cash")[sl].min())
        if min_cash < st.draft["financing"]["minimum_cash"] + 1:
            alerts.append(f"⚠ Cash touches the minimum balance ({st.money(min_cash)}) in this period – "
                          "the revolver is funding operations.")
        if float(res.s("revolver")[sl].max()) > 0:
            alerts.append(f"⚠ Revolver peak draw {st.money(float(res.s('revolver')[sl].max()))}.")
        cc = k.get("cash_conversion")
        if cc is not None and cc < 0.6:
            alerts.append(f"• Cash conversion is {cc * 100:.0f}% of EBITDA – review working capital, capex, "
                          "interest and tax.")
        ota = k.get("ota_share")
        if ota is not None and ota > 0.25:
            alerts.append(f"• OTA share of room nights is {ota * 100:.0f}% – distribution cost exposure.")
        alerts.append(f"✓ {n_ok}/{len(res.checks)} integrity checks pass (balance sheet, cash, RE, debt, fixed "
                      "assets, revenue, inventory).")
        self.alerts.setText("<br>".join(alerts))

        for key, fn in self.extras.items():
            try:
                text = fn()
            except Exception as exc:  # noqa: BLE001 – keep dashboard alive, show reason
                text = f"Unavailable: {exc}"
            getattr(self, key).setText(text)
        self._charts(res, sl)

    def _charts(self, res, sl) -> None:
        p = theme.current()
        x = np.arange(res.months.size)
        ticks, labels = month_axis_labels(res, 6)
        fx = self.state.fx()
        ax = self.ch_rev.new_axes()
        ax.bar(x, res.s("total_revenue") * fx, color=p.blue, alpha=0.55, label="Revenue")
        ax.plot(x, res.s("ebitda") * fx, color=p.teal, lw=2, label="EBITDA")
        ax.plot(x, self.state.compare_result.s("ebitda") * fx, color=p.amber, lw=1.2, ls="--",
                label=f"EBITDA – {self.state.compare_name}")
        ax.axvspan((sl.start or 0) - 0.5, (sl.stop or res.months.size) - 0.5, color=p.teal, alpha=0.05)
        ax.yaxis.set_major_formatter(money_formatter())
        ax.set_xticks(ticks, labels)
        self.ch_rev.legend(ax, loc="upper left", ncol=3)
        self.ch_rev.draw()

        ax1 = self.ch_rm.new_axes()
        occ = res.s("occupied_rooms") / res.s("available_rooms")
        adr = np.divide(res.s("rooms_revenue"), res.s("occupied_rooms"), out=np.full(res.months.size, np.nan),
                        where=res.s("occupied_rooms") > 0)
        revpar = res.s("rooms_revenue") / res.s("available_rooms")
        ax1.fill_between(x, occ, color=p.teal, alpha=0.18)
        ax1.plot(x, occ, color=p.teal, lw=1.8, label="Occupancy (left)")
        ax1.yaxis.set_major_formatter(pct_formatter())
        ax1.set_ylim(0, 1.05)
        ax2 = ax1.twinx()
        self.ch_rm.style_axes(ax2)
        ax2.grid(False)
        ax2.plot(x, adr * fx, color=p.amber, lw=1.6, label="ADR (right)")
        ax2.plot(x, revpar * fx, color=p.blue, lw=1.6, label="RevPAR (right)")
        ax2.spines["right"].set_visible(True)
        ax1.set_xticks(ticks, labels)
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        leg = ax1.legend(h1 + h2, l1 + l2, frameon=False, fontsize=8, loc="lower left", ncol=3)
        for t in leg.get_texts():
            t.set_color(p.text2)
        self.ch_rm.draw()

        ax = self.ch_dept.new_axes()
        names = ["Rooms", "F&B", "Spa", "Events", "Other"]
        keys = ["rooms_profit", "fnb_profit", "spa_profit", "events_profit", "other_profit"]
        vals = [res.total(k_, sl) * fx for k_ in keys]
        cmpv = [self.state.compare_result.total(k_, sl) * fx for k_ in keys]
        y = np.arange(len(names))
        ax.barh(y + 0.18, vals, height=0.36, color=p.teal, label="Working")
        ax.barh(y - 0.18, cmpv, height=0.36, color=p.muted, alpha=0.6, label=self.state.compare_name)
        ax.set_yticks(y, names)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(money_formatter())
        self.ch_dept.legend(ax, loc="lower right")
        self.ch_dept.draw()

        ax = self.ch_cash.new_axes()
        ax.plot(x, res.s("cash") * fx, color=p.teal, lw=2, label="Cash")
        ax.plot(x, (res.s("term_loan") + res.s("revolver")) * fx, color=p.bad, lw=1.4, label="Debt")
        ax.bar(x, res.s("cfo") * fx, color=p.blue, alpha=0.5, label="Operating cash flow")
        ax.axhline(self.state.draft["financing"]["minimum_cash"] * fx, color=p.amber, ls=":", lw=1,
                   label="Minimum cash")
        ax.yaxis.set_major_formatter(money_formatter())
        ax.set_xticks(ticks, labels)
        self.ch_cash.legend(ax, loc="upper right", ncol=2)
        self.ch_cash.draw()
