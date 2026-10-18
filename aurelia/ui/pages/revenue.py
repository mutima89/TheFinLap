"""Revenue Management workstation."""
from __future__ import annotations

import copy

import numpy as np
import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QTabWidget, QComboBox, QFormLayout, QDateEdit,
                               QSpinBox, QDoubleSpinBox, QTextBrowser)

from ...analysis import rm
from ...core.kpis import KPI_DEFINITIONS
from ...model.assumptions import SEGMENTS, SEGMENT_LABELS, SPEC_BY_PATH
from ..common import period_combo, period_slice, formatters, run_with_progress, month_axis_labels, spin_for, spin_value
from ..widgets import Page, card, label, button, Table, Chart, KPICard, money_formatter, pct_formatter, error
from .. import theme


class RevenuePage(Page):
    def __init__(self, state):
        super().__init__("Revenue Management",
                         "Rooms demand, pricing, channel economics and inventory controls. A price cut does not "
                         "automatically raise profit: outcomes depend on demand response, capacity, mix and "
                         "distribution costs.")
        self.state = state
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(label("Period:", "Muted"))
        self.period = period_combo()
        self.period.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.period)
        self.body.addLayout(top)
        self.cards = {}
        row = QHBoxLayout()
        for key, title in (("occupancy", "Occupancy"), ("adr", "ADR"), ("net_adr", "Net ADR"), ("revpar", "RevPAR"),
                           ("net_revpar", "Net RevPAR"), ("cancellation_rate", "Cancellations"),
                           ("ota_share", "OTA share")):
            c = KPICard(key, title, KPI_DEFINITIONS[key].formula)
            c.clicked.connect(lambda k: self.tabs.setCurrentIndex(self.tabs.count() - 1))
            c.setMinimumWidth(0)
            c.value.setStyleSheet("font-size: 21px;")
            self.cards[key] = c
            row.addWidget(c)
        self.body.addLayout(row)

        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._overview_tab()
        self._daily_tab()
        self._pace_tab()
        self._displacement_tab()
        self._pricing_tab()
        self._inventory_tab()
        self._formula_tab()
        state.results_changed.connect(self.refresh)
        state.theme_changed.connect(lambda _n: self.refresh())

    # ------------------------------------------------------------------ tabs
    def _overview_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        f, l = card()
        l.addWidget(label("Segment and channel economics", "H3"))
        l.addWidget(label("Net ADR = gross ADR after commissions. Contribution per room night = net ADR − variable "
                          "cost per occupied room (housekeeping, supplies, laundry, energy).", "Muted", wrap=True))
        self.seg_table = Table(min_height=190)
        l.addWidget(self.seg_table)
        lay.addWidget(f)
        row = QHBoxLayout()
        f2, l2 = card()
        l2.addWidget(label("Demand vs capacity by month (compression)", "H3"))
        self.ch_demand = Chart(2.6)
        l2.addWidget(self.ch_demand)
        f3, l3 = card()
        l3.addWidget(label("Room nights by segment", "H3"))
        self.ch_mix = Chart(2.6)
        l3.addWidget(self.ch_mix)
        row.addWidget(f2, 3)
        row.addWidget(f3, 2)
        lay.addLayout(row)
        lay.addStretch(1)
        self.tabs.addTab(w, "Overview")

    def _daily_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(label("Month:", "Muted"))
        self.day_month = QComboBox()
        self.day_month.currentIndexChanged.connect(self._refresh_daily)
        row.addWidget(self.day_month)
        row.addStretch(1)
        lay.addLayout(row)
        f, l = card()
        l.addWidget(label("Daily demand, inventory and occupied rooms", "H3"))
        self.ch_daily = Chart(3.0)
        l.addWidget(self.ch_daily)
        lay.addWidget(f)
        self.daily_table = Table(min_height=240)
        lay.addWidget(self.daily_table)
        self.tabs.addTab(w, "Daily view")

    def _pace_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(label("Stay month:", "Muted"))
        self.pace_month = QComboBox()
        self.pace_month.currentIndexChanged.connect(self._refresh_pace)
        row.addWidget(self.pace_month)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(label("Booking pace is derived from each segment's mean booking window (exponential lead-time "
                            "assumption). It explains pickup; it is not a statistical forecast.", "Muted", wrap=True))
        r2 = QHBoxLayout()
        f, l = card()
        l.addWidget(label("On-the-books curve", "H3"))
        self.ch_pace = Chart(2.6)
        l.addWidget(self.ch_pace)
        r2.addWidget(f, 1)
        f2, l2 = card()
        l2.addWidget(label("Forecast vs actual – FY2027 closed months", "H3"))
        l2.addWidget(label("Forecast = the approved budget's room nights; actual = closed months from the FP&A "
                           "actuals.", "Muted", wrap=True))
        self.acc_lbl = label("", wrap=True)
        l2.addWidget(self.acc_lbl)
        self.ch_acc = Chart(2.0)
        l2.addWidget(self.ch_acc)
        r2.addWidget(f2, 1)
        lay.addLayout(r2)
        self.pace_table = Table(min_height=220)
        lay.addWidget(self.pace_table)
        self.tabs.addTab(w, "Pace and forecast accuracy")

    def _displacement_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        f, l = card()
        l.addWidget(label("Group request – displacement analysis", "H3"))
        l.addWidget(label("The engine is run twice: with and without the contracted block. Displaced transient "
                          "business, lost commissions, F&B spend and EBITDA are all taken from the same model.",
                          "Muted", wrap=True))
        form = QFormLayout()
        self.g_date = QDateEdit(QDate(2027, 11, 10))
        self.g_date.setCalendarPopup(True)
        self.g_date.setDisplayFormat("ddd dd MMM yyyy")
        self.g_nights = QSpinBox()
        self.g_nights.setRange(1, 30)
        self.g_nights.setValue(4)
        self.g_rooms = QSpinBox()
        self.g_rooms.setRange(1, 1000)
        self.g_rooms.setValue(40)
        self.g_rate = QDoubleSpinBox()
        self.g_rate.setRange(0, 50000)
        self.g_rate.setValue(900)
        self.g_rate.setPrefix("SAR ")
        self.g_fnb = QDoubleSpinBox()
        self.g_fnb.setRange(0, 20000)
        self.g_fnb.setValue(150)
        self.g_fnb.setPrefix("SAR ")
        form.addRow("Arrival date", self.g_date)
        form.addRow("Nights", self.g_nights)
        form.addRow("Rooms per night", self.g_rooms)
        form.addRow("Group rate (excl. VAT)", self.g_rate)
        form.addRow("Banquet F&B per room night", self.g_fnb)
        l.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button("Evaluate request", self._run_displacement, primary=True))
        row.addWidget(button("Add block to working scenario", self._apply_block))
        row.addStretch(1)
        l.addLayout(row)
        self.disp_lbl = label("", wrap=True)
        l.addWidget(self.disp_lbl)
        lay.addWidget(f)
        self.disp_table = Table(min_height=200)
        lay.addWidget(self.disp_table)
        self.tabs.addTab(w, "Group displacement")

    def _pricing_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(label("Segment:", "Muted"))
        self.price_seg = QComboBox()
        for s in SEGMENTS:
            self.price_seg.addItem(SEGMENT_LABELS[s], s)
        row.addWidget(self.price_seg)
        row.addWidget(button("Compare candidate rates", self._run_pricing, primary=True))
        self.apply_rate_btn = button("Apply recommended rate", self._apply_rate)
        self.apply_rate_btn.setEnabled(False)
        row.addWidget(self.apply_rate_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(label("Each candidate rate is run through the full engine (demand response via elasticity, "
                            "capacity, cancellations, commissions, ancillary spend, variable costs and fees). The "
                            "recommendation maximises model-year-1 EBITDA – a model result under stated assumptions, "
                            "not a guarantee.", "Muted", wrap=True))
        f, l = card()
        self.ch_price = Chart(2.6)
        l.addWidget(self.ch_price)
        lay.addWidget(f)
        self.price_table = Table(min_height=240)
        lay.addWidget(self.price_table)
        self._price_df = None
        self.tabs.addTab(w, "Rate recommendations")

    def _inventory_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        top = QHBoxLayout()
        f, l = card()
        l.addWidget(label("Inventory allocation and overbooking", "H3"))
        form = QFormLayout()
        self.inv_editors = []
        for path in ("segments.group.cap", "segments.wholesale.cap", "rooms.overbooking_pct", "rooms.walk_cost",
                     "rooms.out_of_order_rooms"):
            spec = SPEC_BY_PATH[path]
            ed = spin_for(spec, 0)
            ed.editingFinished.connect(lambda s=spec, e=ed: self._apply_driver(s, e))
            self.inv_editors.append((spec, ed))
            form.addRow(spec.label, ed)
        l.addLayout(form)
        l.addWidget(label("Changes apply to the working scenario and recalculate everything.", "Muted", wrap=True))
        top.addWidget(f, 1)
        f2, l2 = card()
        l2.addWidget(label("Overbooking risk on a sold-out night (advanced)", "H3"))
        l2.addWidget(label("Expected value = expected occupied rooms × rate − expected walked guests × walk cost. "
                           "Show probability uses the hotel's blended cancellation and no-show rates.", "Muted",
                           wrap=True))
        self.ob_table = Table(min_height=200)
        l2.addWidget(self.ob_table)
        top.addWidget(f2, 1)
        lay.addLayout(top)
        f3, l3 = card()
        l3.addWidget(label("Minimum length of stay (MLOS) exercise", "H3"))
        l3.addWidget(label("A week with a compression night (night 4). Short stays over the peak block rooms for "
                           "guests who would stay longer. Try MLOS 1–3 and the conversion rate.", "Muted", wrap=True))
        row = QHBoxLayout()
        row.addWidget(label("MLOS on peak night:"))
        self.mlos = QSpinBox()
        self.mlos.setRange(1, 4)
        self.mlos.setValue(2)
        row.addWidget(self.mlos)
        row.addWidget(label("Short-stay guests converting to MLOS:"))
        self.mlos_conv = QDoubleSpinBox()
        self.mlos_conv.setRange(0, 100)
        self.mlos_conv.setValue(40)
        self.mlos_conv.setSuffix(" %")
        row.addWidget(self.mlos_conv)
        row.addWidget(button("Compare", self._run_mlos, primary=True))
        row.addStretch(1)
        l3.addLayout(row)
        self.mlos_lbl = label("", wrap=True)
        l3.addWidget(self.mlos_lbl)
        self.mlos_table = Table(min_height=200)
        l3.addWidget(self.mlos_table)
        lay.addWidget(f3)
        self.tabs.addTab(w, "Inventory controls")

    def _formula_tab(self):
        tb = QTextBrowser()
        html = "<h2>KPI definitions</h2><p>All KPIs exclude VAT. Room revenue is recognised on the night of stay." \
               "</p><table cellpadding=6>"
        for k in KPI_DEFINITIONS.values():
            html += f"<tr><td><b>{k.name}</b></td><td>{k.formula}</td><td>{k.description}</td></tr>"
        html += "</table><h3>Demand model</h3><p>Requests per day per segment = base demand × seasonality × " \
                "day-of-week factor × special-event multiplier × (1 + growth)^year × (realised rate ÷ reference " \
                "rate)^elasticity × campaign uplift × seeded noise. Requests are accepted in booking-window order " \
                "(longest lead first) until available rooms × (1 + overbooking) or a segment's cap is reached. " \
                "Cancellations free rooms; a configurable share is resold to remaining short-lead demand. " \
                "Limitations: constant elasticity, no competitor response, no length-of-stay controls in the main " \
                "engine (see the MLOS exercise), and segment lead times are averages.</p>"
        tb.setHtml(html)
        self.tabs.addTab(tb, "KPI formulas")

    # ------------------------------------------------------------------ actions
    def _run_displacement(self):
        try:
            d = rm.displacement_analysis(self.state.draft, self.g_date.date().toString("yyyy-MM-dd"),
                                         self.g_nights.value(), self.g_rooms.value(), self.g_rate.value(),
                                         self.g_fnb.value())
        except Exception as exc:  # noqa: BLE001
            error(self, "Displacement analysis", str(exc))
            return
        st = self.state
        self.disp_lbl.setText(
            f"<b>{d.recommendation}</b><br>Group room revenue {st.money(d.group_room_revenue)} · displaced room "
            f"nights {d.displaced_room_nights:,.1f} · Δ room revenue {st.money(d.delta_room_revenue)} · Δ total "
            f"revenue {st.money(d.delta_total_revenue)} · Δ departmental contribution "
            f"{st.money(d.delta_contribution)} · <b>Δ EBITDA {st.money(d.delta_ebitda)}</b>")
        cols = ["Available", "Other business without block", "Other business with block", "Group block rooms",
                "Displaced room nights"]
        self.disp_table.set(d.table, {**formatters(st, num_cols=cols),
                                      **formatters(st, money_cols=["Net room revenue without",
                                                                   "Net room revenue with"])})

    def _apply_block(self):
        a = copy.deepcopy(self.state.draft)
        a["rooms"].setdefault("group_blocks", []).append(
            {"start_date": self.g_date.date().toString("yyyy-MM-dd"), "nights": self.g_nights.value(),
             "rooms": float(self.g_rooms.value()), "rate": self.g_rate.value(),
             "fnb_per_room_night": self.g_fnb.value()})
        probs = self.state.replace_draft(a, "Added contracted group block")
        if probs:
            error(self, "Could not apply", "\n".join(probs))

    def _run_pricing(self):
        seg = self.price_seg.currentData()
        df = run_with_progress(self, "Evaluating candidate rates…", rm.rate_candidates_evaluation, self.state.draft,
                               seg)
        self._price_df = (seg, df)
        st = self.state
        self.price_table.set(df, {**formatters(st, money_cols=["Segment net revenue", "Total revenue", "EBITDA"],
                                               dec_money_cols=["Published rate", "ADR", "RevPAR"],
                                               pct_cols=["Rate change", "Occupancy"],
                                               int_cols=["Segment room nights"])})
        p = theme.current()
        ax = self.ch_price.new_axes()
        ax.plot(df["Rate change"] * 100, df["EBITDA"] * st.fx(), marker="o", color=p.teal, label="EBITDA")
        ax2 = ax.twinx()
        self.ch_price.style_axes(ax2)
        ax2.grid(False)
        ax2.plot(df["Rate change"] * 100, df["Occupancy"], marker="s", color=p.amber, label="Occupancy")
        ax2.yaxis.set_major_formatter(pct_formatter())
        ax.set_xlabel(f"{SEGMENT_LABELS[seg]} rate change vs current (%)")
        ax.yaxis.set_major_formatter(money_formatter())
        self.ch_price.legend(ax, loc="upper left")
        self.ch_price.legend(ax2, loc="upper right")
        self.ch_price.draw()
        self.apply_rate_btn.setEnabled(True)

    def _apply_rate(self):
        if not self._price_df:
            return
        seg, df = self._price_df
        best = df.loc[df["EBITDA"].idxmax(), "Published rate"]
        probs = self.state.set_driver(f"segments.{seg}.published_rate", round(float(best), 2),
                                      "Applied rate recommendation")
        if probs:
            error(self, "Could not apply", "\n".join(probs))

    def _apply_driver(self, spec, ed):
        val = spin_value(spec, ed)
        probs = self.state.set_driver(spec.path, val)
        if probs:
            error(self, "Invalid value", "\n".join(probs))

    def _run_mlos(self):
        base = rm.mlos_exercise(mlos=1)
        new = rm.mlos_exercise(mlos=self.mlos.value(), conversion_pct=self.mlos_conv.value() / 100)
        st = self.state
        d_rev = new.attrs["revenue"] - base.attrs["revenue"]
        self.mlos_lbl.setText(
            f"Without restriction: revenue {st.money(base.attrs['revenue'])}, refused requests "
            f"{base.attrs['refused']:.0f}. With MLOS {self.mlos.value()}: revenue {st.money(new.attrs['revenue'])}, "
            f"refused {new.attrs['refused']:.0f}. <b>Change {st.money(d_rev)}</b>. "
            + ("The restriction helps because displaced short stays are replaced by longer stays filling shoulder "
               "nights." if d_rev > 0 else "The restriction costs revenue: too few guests convert to the longer "
                                            "stay and peak rooms go unsold."))
        df = base[["Night", "Occupied", "Occupancy"]].rename(columns={"Occupied": "Occupied – no MLOS",
                                                                      "Occupancy": "Occ – no MLOS"})
        df["Occupied – with MLOS"] = new["Occupied"]
        df["Occ – with MLOS"] = new["Occupancy"]
        self.mlos_table.set(df, formatters(st, num_cols=["Occupied – no MLOS", "Occupied – with MLOS"],
                                           pct_cols=["Occ – no MLOS", "Occ – with MLOS"]))

    # ------------------------------------------------------------------ refresh
    def focus_item(self, key):
        self.tabs.setCurrentIndex(0)

    def refresh(self):
        st = self.state
        res = st.result
        sl = period_slice(res, self.period.currentData())
        k = res.kpis(sl)
        kc = st.compare_result.kpis(sl)
        for key, c in self.cards.items():
            unit = KPI_DEFINITIONS[key].unit
            v, b = k.get(key), kc.get(key)
            delta = ""
            if v is not None and b is not None and abs(v - b) > 1e-9:
                delta = f"{(v - b) * 100:+.1f} pts" if unit == "pct" else f"{'+' if v >= b else '−'}{st.money(abs(v - b), 0)}"
                delta += f" vs {st.compare_name}"
            c.set(st.fmt(v, unit, 0 if unit == "currency" else None), delta)
        seg = rm.segment_economics(res, sl)
        self.seg_table.set(seg.drop(columns=["key"]), {
            **formatters(st, money_cols=["Room revenue", "Net room revenue"],
                         dec_money_cols=["Gross ADR", "Net ADR", "Variable cost / RN", "Contribution / RN"],
                         pct_cols=["Mix %", "Commission %", "Cancellation %"],
                         int_cols=["Room nights", "Denied requests"])})
        self.seg_table.fit_height(6)
        p = theme.current()
        x = np.arange(res.months.size)
        ticks, labels = month_axis_labels(res, 6)
        ax = self.ch_demand.new_axes()
        av = res.s("available_rooms")
        ax.plot(x, res.s("room_demand") / av, color=p.amber, lw=1.6, label="Unconstrained requests ÷ available")
        ax.plot(x, res.s("occupied_rooms") / av, color=p.teal, lw=2, label="Occupancy")
        ax.axhline(1.0, color=p.bad, ls=":", lw=1)
        ax.yaxis.set_major_formatter(pct_formatter())
        ax.set_xticks(ticks, labels)
        self.ch_demand.legend(ax, loc="lower left")
        self.ch_demand.draw()
        ax = self.ch_mix.new_axes()
        vals = [float(res.segments[s]["room_nights"][sl].sum()) for s in SEGMENTS]
        ax.barh(range(len(SEGMENTS)), vals, color=list(p.series[:len(SEGMENTS)]))
        ax.set_yticks(range(len(SEGMENTS)), [SEGMENT_LABELS[s] for s in SEGMENTS], fontsize=8)
        ax.invert_yaxis()
        self.ch_mix.draw()

        for cb in (self.day_month, self.pace_month):
            cur = cb.currentIndex()
            cb.blockSignals(True)
            cb.clear()
            cb.addItems([m.strftime("%B %Y") for m in res.months])
            cb.setCurrentIndex(cur if 0 <= cur < res.months.size else 10)
            cb.blockSignals(False)
        self._refresh_daily()
        self._refresh_pace()
        for spec, ed in self.inv_editors:
            v = _get(st.draft, spec.path)
            ed.blockSignals(True)
            ed.setValue((v or 0) * 100 if spec.unit == "pct" else (v or 0))
            ed.blockSignals(False)
        # Overbooking table from blended show probability
        acc = res.total("bookings_accepted", sl)
        show_p = 1 - (res.total("cancellations", sl) + res.total("no_shows", sl)) / acc if acc else 0.9
        avail = st.draft["rooms"]["total_rooms"] - st.draft["rooms"]["out_of_order_rooms"]
        ob = rm.overbooking_table(avail, max(min(show_p, 0.999), 0.5), k["adr"] or 0, st.draft["rooms"]["walk_cost"])
        self.ob_table.set(ob, {**formatters(st, num_cols=["Expected arrivals", "Expected walks", "Expected occupied"],
                                            pct_cols=["P(at least one walk)"],
                                            money_cols=["Expected net value"])})
        if self.mlos_table.model_.rowCount() == 0:
            self._run_mlos()

    def _refresh_daily(self):
        res = self.state.result
        m = self.day_month.currentIndex()
        if m < 0:
            return
        d = res.daily[res.daily["month_idx"] == m]
        p = theme.current()
        ax = self.ch_daily.new_axes()
        x = np.arange(len(d))
        bottom = np.zeros(len(d))
        for i, s in enumerate(SEGMENTS):
            v = d[f"{s}_rooms"].to_numpy()
            ax.bar(x, v, bottom=bottom, color=p.series[i], label=SEGMENT_LABELS[s], width=0.8)
            bottom += v
        dem = sum(d[f"{s}_demand"].to_numpy() for s in SEGMENTS)
        ax.plot(x, dem, color=p.text2, lw=1.2, ls="--", label="Unconstrained requests")
        ax.plot(x, d["available"].to_numpy(), color=p.bad, lw=1.4, label="Available rooms")
        ax.set_xticks(x[::2], [dt.strftime("%a %d") for dt in d["date"]][::2], fontsize=7, rotation=45)
        self.ch_daily.legend(ax, loc="upper left", ncol=4)
        self.ch_daily.draw()
        rev = sum(d[f"{s}_revenue"] for s in SEGMENTS)
        com = sum(d[f"{s}_commission"] for s in SEGMENTS)
        tab = pd.DataFrame({"Date": [dt.strftime("%a %d %b") for dt in d["date"]], "Available": d["available"],
                            "Requests": dem, "Occupied": d["occupied"],
                            "Occupancy": d["occupied"] / d["available"].where(d["available"] > 0),
                            "ADR": rev / d["occupied"].where(d["occupied"] > 0),
                            "Net ADR": (rev - com) / d["occupied"].where(d["occupied"] > 0),
                            "Room revenue": rev, "Event multiplier": d["event_multiplier"]})
        self.daily_table.set(tab, {**formatters(self.state, num_cols=["Available", "Requests", "Occupied",
                                                                      "Event multiplier"],
                                                pct_cols=["Occupancy"], dec_money_cols=["ADR", "Net ADR"],
                                                money_cols=["Room revenue"])})

    def _refresh_pace(self):
        res = self.state.result
        m = self.pace_month.currentIndex()
        if m < 0:
            return
        pc = rm.pace_curve(res, m)
        self.pace_table.set(pc, formatters(self.state, int_cols=[c for c in pc.columns if c != "Days before arrival"]))
        p = theme.current()
        ax = self.ch_pace.new_axes()
        ax.plot(pc["Days before arrival"], pc["Total on the books"], marker="o", color=p.teal)
        ax.invert_xaxis()
        ax.set_xlabel("Days before arrival")
        ax.set_ylabel("Room nights on the books")
        self.ch_pace.draw()
        try:
            from ...analysis.fpa import build_fpa
            fp = build_fpa(self.state.store.get(self.state.db.get_setting("fpa_budget_scenario", "Base case"))
                           .assumptions, self.state.draft, self.state.db.get_setting("fpa_as_of", 9))
            act = fp.actual.s("occupied_rooms")[:fp.as_of]
            fc = fp.budget.s("occupied_rooms")[:fp.as_of]
            acc = rm.forecast_accuracy(act, fc)
            self.acc_lbl.setText(f"MAPE {acc['MAPE'] * 100:.1f}% · bias {acc['Bias (mean error)']:+,.0f} room "
                                 f"nights/month ({acc['Direction']}) · tracking signal {acc['Tracking signal']:+.2f}")
            ax = self.ch_acc.new_axes()
            xs = np.arange(fp.as_of)
            ax.bar(xs - 0.2, act, width=0.4, color=p.teal, label="Actual")
            ax.bar(xs + 0.2, fc, width=0.4, color=p.muted, label="Forecast (budget)")
            ax.set_xticks(xs, [mm.strftime("%b") for mm in fp.actual.months[:fp.as_of]], fontsize=7)
            self.ch_acc.legend(ax, loc="lower right")
            self.ch_acc.draw()
        except Exception as exc:  # noqa: BLE001
            self.acc_lbl.setText(f"Forecast accuracy unavailable: {exc}")


def _get(a, path):
    from ...model.assumptions import get_path
    return get_path(a, path)
