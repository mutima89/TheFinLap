"""Investment and business case evaluator."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QVBoxLayout, QWidget, QListWidget, QListWidgetItem, QFormLayout,
                               QDoubleSpinBox, QSpinBox, QLineEdit, QTabWidget)

from ...analysis import investment as inv
from ...core.finance import FinanceError
from ..common import formatters
from ..widgets import Page, card, label, button, Table, Chart, KPICard, money_formatter, error
from .. import theme


class InvestmentPage(Page):
    def __init__(self, state):
        super().__init__("Investment and Business Cases",
                         "Evaluate projects on incremental, after-tax cash flows. Benefits come from running the "
                         "hotel engine with and without the project. NPV is the primary decision rule; IRR, MIRR, "
                         "payback and PI are supporting measures.")
        self.state = state
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()
        self.case_list = QListWidget()
        self.case_list.setMinimumWidth(320)
        self.case_list.setMaximumWidth(340)
        for c in inv.CASES:
            it = QListWidgetItem(f"{c.title}\n   {c.category}")
            it.setData(Qt.UserRole, c.key)
            self.case_list.addItem(it)
        self.case_list.currentRowChanged.connect(self._select)
        left.addWidget(self.case_list)
        lay.addLayout(left)
        right = QVBoxLayout()
        self.case_title = label("", "H2")
        self.case_desc = label("", "Muted", wrap=True)
        right.addWidget(self.case_title)
        right.addWidget(self.case_desc)
        pf, pl = card()
        pl.addWidget(label("Assumptions (editable)", "H3"))
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        pl.addWidget(self.form_host)
        row = QHBoxLayout()
        row.addWidget(button("Evaluate", self._run, primary=True))
        row.addWidget(button("Reset assumptions", self._select_current))
        row.addStretch(1)
        pl.addLayout(row)
        right.addWidget(pf)
        cards = QGridLayout()
        self.cards = {}
        for i, (k, t) in enumerate((("npv", "NPV"), ("irr", "IRR"), ("mirr", "MIRR"), ("pb", "Payback"),
                                     ("dpb", "Disc. payback"), ("pi", "Profitability index"))):
            c = KPICard(k, t)
            self.cards[k] = c
            cards.addWidget(c, i // 3, i % 3)
        right.addLayout(cards)
        self.rec = label("", wrap=True)
        right.addWidget(self.rec)
        cf, cl = card()
        cl.addWidget(label("Incremental cash flows", "H3"))
        self.chart = Chart(2.4)
        cl.addWidget(self.chart)
        right.addWidget(cf)
        self.table = Table(min_height=240)
        right.addWidget(self.table)
        right.addWidget(label("NPV sensitivity", "H3"))
        self.sens = Table(min_height=170)
        right.addWidget(self.sens)
        self.extra = label("", wrap=True)
        right.addWidget(self.extra)
        self.group_table = Table(min_height=200)
        self.group_lbl = label("Group consolidation (The Aurelia Grand + Aurelia Oasis, before acquisition financing)",
                               "H3")
        right.addWidget(self.group_lbl)
        right.addWidget(self.group_table)
        lay.addLayout(right, 1)
        self.tabs.addTab(w, "Business case library")
        self._custom_tab()
        self._editors = {}
        self.case_list.setCurrentRow(0)

    def _custom_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Enter any cash-flow series (t = 0 first, comma separated). Unusual patterns are handled "
                            "safely: multiple IRRs and no-IRR cases are reported explicitly.", "Muted", wrap=True))
        row = QHBoxLayout()
        self.cf_in = QLineEdit("-1000000, 300000, 350000, 400000, 450000")
        self.cf_rate = QDoubleSpinBox()
        self.cf_rate.setRange(-99, 500)
        self.cf_rate.setValue(10)
        self.cf_rate.setSuffix(" %")
        row.addWidget(self.cf_in, 1)
        row.addWidget(label("Discount rate:"))
        row.addWidget(self.cf_rate)
        row.addWidget(button("Evaluate", self._run_custom, primary=True))
        lay.addLayout(row)
        self.cf_out = label("", wrap=True)
        lay.addWidget(self.cf_out)
        lay.addStretch(1)
        self.tabs.addTab(w, "Custom cash flows")

    def _run_custom(self):
        try:
            flows = [float(x.replace(" ", "")) for x in self.cf_in.text().split(",") if x.strip()]
            ev = inv.custom_cash_flows(flows, self.cf_rate.value() / 100)
        except (ValueError, FinanceError) as exc:
            self.cf_out.setText(f"<span style='color:#F0616D'>{exc}</span>")
            return
        irr = (f"{ev.irr.value * 100:.2f}%" if ev.irr.value is not None else ev.irr.message)
        self.cf_out.setText(
            f"NPV <b>{ev.npv:,.2f}</b> · IRR <b>{irr}</b> · MIRR "
            f"{'n/a' if ev.mirr is None else f'{ev.mirr * 100:.2f}%'} · payback "
            f"{'never' if ev.payback is None else f'{ev.payback:.2f} periods'} · discounted payback "
            f"{'never' if ev.discounted_payback is None else f'{ev.discounted_payback:.2f}'} · PI "
            f"{'n/a' if ev.pi is None else f'{ev.pi:.3f}'}<br><b>{ev.recommendation}</b><br>" +
            "<br>".join(ev.reasons))

    def _select_current(self):
        self._select(self.case_list.currentRow())

    def _select(self, row):
        if row < 0:
            return
        case = inv.CASES[row]
        self.case_title.setText(case.title)
        self.case_desc.setText(case.description)
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors = {}
        for p in case.params:
            if p.unit in ("int",):
                w = QSpinBox()
                w.setRange(0, 1000)
                w.setValue(int(p.value))
            else:
                w = QDoubleSpinBox()
                if p.unit == "pct":
                    w.setRange(-99, 500)
                    w.setDecimals(2)
                    w.setSuffix(" %")
                    w.setValue(p.value * 100)
                else:
                    w.setRange(-1e12, 1e12)
                    w.setDecimals(0 if p.unit == "currency" or float(p.value).is_integer() else 3)
                    w.setGroupSeparatorShown(True)
                    if p.unit == "currency":
                        w.setPrefix("SAR ")
                    w.setValue(p.value)
            w.setToolTip(p.help or p.label)
            self._editors[p.key] = (p, w)
            self.form.addRow(p.label, w)
        self._run()

    def _params(self):
        out = {}
        for k, (p, w) in self._editors.items():
            out[k] = w.value() / 100 if p.unit == "pct" else w.value()
        return out

    def _run(self):
        row = self.case_list.currentRow()
        if row < 0:
            return
        case = inv.CASES[row]
        st = self.state
        try:
            ev = inv.run_case(case.key, st.draft, self._params())
        except (FinanceError, ValueError) as exc:
            error(self, "Cannot evaluate", str(exc))
            return
        self.cards["npv"].set(st.money(ev.npv), "at the stated discount rate", ev.npv > 0)
        self.cards["irr"].set(f"{ev.irr.value * 100:.1f}%" if ev.irr.value is not None else "n/a",
                              "" if ev.irr.status == "ok" else ev.irr.status)
        self.cards["mirr"].set("n/a" if ev.mirr is None else f"{ev.mirr * 100:.1f}%")
        self.cards["pb"].set("never" if ev.payback is None else f"{ev.payback:.1f} yrs")
        self.cards["dpb"].set("never" if ev.discounted_payback is None else f"{ev.discounted_payback:.1f} yrs")
        self.cards["pi"].set("n/a" if ev.pi is None else f"{ev.pi:.2f}")
        self.rec.setText(f"<h3>{ev.recommendation}</h3>" + "".join(f"• {r}<br>" for r in ev.reasons) +
                         "<br><b>Assumptions driving this recommendation</b><br>" +
                         "".join(f"• {a}<br>" for a in ev.assumptions))
        cols = [c for c in ev.table.columns if c != "Year"]
        self.table.set(ev.table, formatters(st, money_cols=cols))
        self.sens.set(ev.sensitivity, formatters(st, money_cols=["NPV"]),
                      nature={"NPV": lambda r, v: "good" if v > 0 else "bad"})
        p = theme.current()
        ax = self.chart.new_axes()
        flows = np.array(ev.cash_flows) * st.fx()
        x = np.arange(len(flows))
        ax.bar(x, flows, color=[p.good if f >= 0 else p.bad for f in flows])
        ax.plot(x, np.cumsum(flows), color=p.amber, marker="o", lw=1.4, label="Cumulative")
        ax.axhline(0, color=p.text2, lw=0.8)
        ax.set_xlabel("Year")
        ax.yaxis.set_major_formatter(money_formatter())
        self.chart.legend(ax)
        self.chart.draw()
        extra = ""
        for k, v in ev.extra.items():
            if k == "oasis_result":
                continue
            extra += f"{k}: <b>{v * 100:.0f}%</b><br>" if "Share" in k else f"{k}: <b>{st.money(v)}</b><br>"
        self.extra.setText(extra)
        is_exp = "oasis_result" in ev.extra
        self.group_lbl.setVisible(is_exp)
        self.group_table.setVisible(is_exp)
        if is_exp:
            g = inv.group_consolidation(st.result, ev.extra["oasis_result"])
            self.group_table.set(g, formatters(st, money_cols=["The Aurelia Grand", "Aurelia Oasis", "Group"]))

    def refresh(self):
        self._run()
