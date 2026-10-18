"""Modelling Workbench: model library (A–H), dependency viewer, custom formulas and model warnings."""
from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QTabWidget, QListWidget, QListWidgetItem,
                               QSplitter, QTextBrowser, QTreeWidget, QTreeWidgetItem, QLineEdit, QComboBox,
                               QFormLayout, QDoubleSpinBox, QSpinBox)

from ...analysis import statements as stm, sensitivity as se
from ...core import expr as ex
from ...core import finance as fin
from ...core.finance import safe_div
from ...model.assumptions import SEGMENTS, SEGMENT_LABELS, DEPARTMENTS, DEPARTMENT_LABELS, get_path, validate
from ...model.engine import G
from ...persistence.db import now
from ..common import formatters, period_combo, period_slice, line_item_html, month_axis_labels
from ..widgets import Page, label, button, Table, Chart, error, money_formatter, confirm
from .. import theme

MODELS = [
    ("A", "Revenue driver model", "Bookings × price × mix, adjusted for cancellations, capacity and timing."),
    ("B", "Departmental profit model", "Revenue, cost of sales, payroll, other expenses and contribution by "
                                       "department."),
    ("C", "Hotel operating statement", "USALI-style statement from departmental revenue to EBITDA."),
    ("D", "Three-statement model", "Income statement, balance sheet and cash flow, linked and reconciled."),
    ("E", "Integrated 36-month forecast", "Monthly forecast of the key lines for the whole horizon."),
    ("F", "Working capital model", "Receivables, inventory, payables, VAT and deposits; cash conversion cycle."),
    ("G", "Capital expenditure model", "Asset purchases, depreciation, fixed-asset roll-forward and projects."),
    ("H", "Unit economics and contribution", "Contribution per occupied room, break-even and operating "
                                             "leverage."),
]


class WorkbenchPage(Page):
    def __init__(self, state):
        super().__init__("Modelling Workbench",
                         "Inspect and extend the model. Inputs (blue) are assumptions you can change; calculated "
                         "values come from the engine's dependency graph. Every formula is visible.")
        self.state = state
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._library_tab()
        self._graph_tab()
        self._formula_tab()
        self._warnings_tab()
        state.results_changed.connect(self.refresh)

    # ------------------------------------------------------------------ library
    def _library_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        self.model_list = QListWidget()
        self.model_list.setMaximumWidth(280)
        for code, title, _d in MODELS:
            it = QListWidgetItem(f"{code}. {title}")
            it.setData(Qt.UserRole, code)
            self.model_list.addItem(it)
        self.model_list.currentRowChanged.connect(lambda _r: self._show_model())
        lay.addWidget(self.model_list)
        right = QWidget()
        rl = QVBoxLayout(right)
        top = QHBoxLayout()
        self.model_title = label("", "H2")
        top.addWidget(self.model_title)
        top.addStretch(1)
        self.lib_period = period_combo()
        self.lib_period.currentIndexChanged.connect(self._show_model)
        top.addWidget(self.lib_period)
        rl.addLayout(top)
        self.model_desc = label("", "Muted", wrap=True)
        rl.addWidget(self.model_desc)
        self.model_inputs_lbl = label("Inputs (assumptions)", "H3")
        rl.addWidget(self.model_inputs_lbl)
        self.model_inputs = Table(min_height=150)
        rl.addWidget(self.model_inputs)
        rl.addWidget(label("Calculated outputs", "H3"))
        self.model_table = Table(min_height=300)
        rl.addWidget(self.model_table)
        self.model_chart = Chart(2.4)
        rl.addWidget(self.model_chart)
        # G: project editor, H: unit calculator
        self.extra = QWidget()
        self.extra_lay = QVBoxLayout(self.extra)
        self.extra_lay.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.extra)
        lay.addWidget(right, 1)
        self.tabs.addTab(w, "Model library A–H")
        self._build_project_editor()
        self._build_unit_calc()

    def _build_project_editor(self):
        self.proj_box = QWidget()
        f = QFormLayout(self.proj_box)
        self.p_name = QLineEdit("Lobby refurbishment")
        self.p_month = QComboBox()
        self.p_amount = QDoubleSpinBox()
        self.p_amount.setRange(0, 1e10)
        self.p_amount.setGroupSeparatorShown(True)
        self.p_amount.setDecimals(0)
        self.p_amount.setValue(5_000_000)
        self.p_amount.setPrefix("SAR ")
        self.p_life = QSpinBox()
        self.p_life.setRange(1, 60)
        self.p_life.setValue(10)
        self.p_ooo = QSpinBox()
        self.p_ooo.setRange(0, 2000)
        self.p_ooo_m = QSpinBox()
        self.p_ooo_m.setRange(0, 36)
        self.p_uplift = QDoubleSpinBox()
        self.p_uplift.setRange(-50, 100)
        self.p_uplift.setSuffix(" %")
        f.addRow("Project name", self.p_name)
        f.addRow("Month", self.p_month)
        f.addRow("Amount", self.p_amount)
        f.addRow("Useful life (years)", self.p_life)
        f.addRow("Rooms out of order during works", self.p_ooo)
        f.addRow("Months of works", self.p_ooo_m)
        f.addRow("Rate uplift after completion", self.p_uplift)
        row = QHBoxLayout()
        row.addWidget(button("Add project to working scenario", self._add_project, primary=True))
        row.addWidget(button("Remove all projects", self._clear_projects, danger=True))
        row.addStretch(1)
        f.addRow(row)

    def _build_unit_calc(self):
        self.unit_box = QWidget()
        f = QFormLayout(self.unit_box)
        self.u_price = QDoubleSpinBox()
        self.u_var = QDoubleSpinBox()
        self.u_fixed = QDoubleSpinBox()
        self.u_units = QDoubleSpinBox()
        for wdg, v in ((self.u_price, 650), (self.u_var, 150), (self.u_fixed, 120000), (self.u_units, 400)):
            wdg.setRange(0, 1e9)
            wdg.setGroupSeparatorShown(True)
            wdg.setValue(v)
            wdg.valueChanged.connect(self._unit_calc)
        f.addRow("Unit price", self.u_price)
        f.addRow("Variable cost per unit", self.u_var)
        f.addRow("Fixed costs per period", self.u_fixed)
        f.addRow("Expected units", self.u_units)
        self.u_out = label("", wrap=True)
        f.addRow(self.u_out)

    def _unit_calc(self):
        p, v, fx, u = self.u_price.value(), self.u_var.value(), self.u_fixed.value(), self.u_units.value()
        cm = p - v
        be = fin.break_even_units(fx, p, v)
        profit = cm * u - fx
        dol = fin.degree_of_operating_leverage(cm * u, profit)
        self.u_out.setText(
            f"Contribution per unit = {p:,.2f} − {v:,.2f} = <b>{cm:,.2f}</b>; margin "
            f"{(fin.contribution_margin_ratio(p, v) or 0) * 100:.1f}%<br>"
            f"Break-even units = {fx:,.0f} ÷ {cm:,.2f} = <b>{'not reachable' if be is None else f'{be:,.1f}'}</b><br>"
            f"Profit at {u:,.0f} units = {cm:,.2f} × {u:,.0f} − {fx:,.0f} = <b>{profit:,.0f}</b><br>"
            f"Operating leverage = contribution ÷ profit = <b>{'undefined (profit = 0)' if dol is None else f'{dol:.2f}×'}"
            f"</b> → a 10% change in units changes profit by about "
            f"{'n/a' if dol is None else f'{dol * 10:.0f}%'}.")

    def _add_project(self):
        import copy
        a = copy.deepcopy(self.state.draft)
        a["capex"]["projects"].append({"name": self.p_name.text().strip() or "Project",
                                       "month": self.p_month.currentText(), "amount": self.p_amount.value(),
                                       "life_years": self.p_life.value(), "ooo_rooms": self.p_ooo.value(),
                                       "ooo_months": self.p_ooo_m.value(),
                                       "rate_uplift_pct": self.p_uplift.value() / 100})
        probs = self.state.replace_draft(a, f"Added capex project {self.p_name.text()}")
        if probs:
            error(self, "Invalid project", "\n".join(probs))

    def _clear_projects(self):
        import copy
        if confirm(self, "Remove projects", "Remove all capex projects from the working scenario?"):
            a = copy.deepcopy(self.state.draft)
            a["capex"]["projects"] = []
            self.state.replace_draft(a, "Removed capex projects")

    def _show_model(self):
        it = self.model_list.currentItem()
        if it is None:
            return
        code = it.data(Qt.UserRole)
        st = self.state
        res = st.result
        sl = period_slice(res, self.lib_period.currentData())
        _c, title, desc = next(m for m in MODELS if m[0] == code)
        self.model_title.setText(f"{code}. {title}")
        self.model_desc.setText(desc)
        for i in reversed(range(self.extra_lay.count())):
            self.extra_lay.itemAt(i).widget().setParent(None)
        self.model_chart.setVisible(False)
        self.model_inputs.setVisible(True)
        self.model_inputs_lbl.setVisible(True)
        t = lambda k: res.total(k, sl)  # noqa: E731
        if code == "A":
            rows = []
            for s in SEGMENTS:
                sg = st.draft["segments"][s]
                rows.append({"Segment": SEGMENT_LABELS[s], "Type": "Input", "Published rate": sg["published_rate"],
                             "Discount": f"{sg['discount_pct'] * 100:.1f}%", "Base demand/day": sg["base_demand"],
                             "Elasticity": sg["elasticity"], "Cancellation": f"{sg['cancellation_pct'] * 100:.1f}%",
                             "No-show": f"{sg['no_show_pct'] * 100:.1f}%",
                             "Commission": f"{sg['commission_pct'] * 100:.1f}%",
                             "Cap": "none" if sg.get("cap") is None else f"{sg['cap']:.0f}"})
            self.model_inputs.set(pd.DataFrame(rows))
            rows = []
            for s in SEGMENTS:
                g = res.segments[s]
                rq, acc, cx, ns = (float(g[k][sl].sum()) for k in ("demand", "accepted", "cancelled", "no_show"))
                rn, rv, cm = (float(g[k][sl].sum()) for k in ("room_nights", "revenue", "commission"))
                rows.append({"Segment": SEGMENT_LABELS[s], "Type": "Calculated", "Requests": rq, "Accepted": acc,
                             "Denied (capacity/cap)": max(rq - acc, 0), "Cancelled": cx, "No-shows": ns,
                             "Room nights": rn, "Realised ADR": safe_div(rv, rn), "Room revenue": rv,
                             "Commission": cm, "Net room revenue": rv - cm})
            df = pd.DataFrame(rows)
            tot = {c: df[c].sum() for c in df.columns if c not in ("Segment", "Type", "Realised ADR")}
            tot.update({"Segment": "Total", "Type": "Calculated",
                        "Realised ADR": safe_div(tot["Room revenue"], tot["Room nights"])})
            df = pd.concat([df, pd.DataFrame([tot])], ignore_index=True)
            self.model_table.set(df, formatters(st, int_cols=["Requests", "Accepted", "Denied (capacity/cap)",
                                                              "Cancelled", "No-shows", "Room nights"],
                                                dec_money_cols=["Realised ADR"],
                                                money_cols=["Room revenue", "Commission", "Net room revenue"]),
                                 [len(df) - 1])
        elif code == "B":
            rows = []
            spec = {"rooms": ("rooms_revenue", "commissions", "rooms_variable_costs", "payroll_rooms", "rooms_profit"),
                    "fnb": ("fnb_revenue", "fnb_cogs", "fnb_other_exp", "fnb_labour", "fnb_profit"),
                    "spa": ("spa_revenue", None, "spa_costs", "payroll_spa", "spa_profit"),
                    "events": ("events_revenue", None, "events_costs", "payroll_events", "events_profit")}
            for d, (rv, cos, oth, pay, pr) in spec.items():
                r_ = t(rv)
                rows.append({"Department": DEPARTMENT_LABELS[d], "Revenue": r_,
                             "Cost of sales / commissions": t(cos) if cos else 0.0, "Other direct costs": t(oth),
                             "Payroll": t(pay), "Departmental profit": t(pr), "Margin": safe_div(t(pr), r_)})
            rows.append({"Department": "Other operated", "Revenue": t("other_revenue"),
                         "Cost of sales / commissions": 0.0, "Other direct costs": t("other_costs"), "Payroll": 0.0,
                         "Departmental profit": t("other_profit"), "Margin": safe_div(t("other_profit"),
                                                                                       t("other_revenue"))})
            df = pd.DataFrame(rows)
            self.model_inputs.set(pd.DataFrame([{"Department": DEPARTMENT_LABELS[d], "Type": "Input",
                                                 "FTE": st.draft["payroll"]["headcount"][d],
                                                 "Avg monthly salary": st.draft["payroll"]["monthly_salary"][d]}
                                                for d in DEPARTMENTS]))
            self.model_table.set(df, formatters(st, money_cols=list(df.columns[1:-1]), pct_cols=["Margin"]))
        elif code in ("C", "D"):
            self.model_inputs.setVisible(False)
            self.model_inputs_lbl.setVisible(False)
            df = stm.operating_statement(res) if code == "C" else stm.income_statement(res)
            view = df.drop(columns=["style", "key"])
            self.model_table.set(view, formatters(st, money_cols=list(view.columns[1:])),
                                 [i for i, s in enumerate(df["style"]) if s in ("b", "h")])
            if code == "D":
                b = QWidget()
                bl = QHBoxLayout(b)
                bl.addWidget(label(f"Balance sheet balances in every month: "
                                   f"{'YES' if all(c.passed for c in res.checks) else 'NO'} · "
                                   f"cash, retained earnings, debt and fixed-asset roll-forwards reconcile.", wrap=True))
                bl.addWidget(button("Open full statements", lambda: st.navigate.emit("statements", None)))
                self.extra_lay.addWidget(b)
        elif code == "E":
            self.model_inputs.setVisible(False)
            self.model_inputs_lbl.setVisible(False)
            keys = [("occupied_rooms", "Occupied rooms"), ("rooms_revenue", "Room revenue"),
                    ("total_revenue", "Total revenue"), ("gop", "GOP"), ("ebitda", "EBITDA"),
                    ("net_income", "Net income"), ("cfo", "Operating cash flow"), ("cash", "Closing cash")]
            data = {"Month": [m.strftime("%b %Y") for m in res.months]}
            for k, lab in keys:
                data[lab] = res.s(k)
            df = pd.DataFrame(data)
            self.model_table.set(df, formatters(st, int_cols=["Occupied rooms"],
                                                money_cols=[lab for k, lab in keys if k != "occupied_rooms"]))
            self.model_chart.setVisible(True)
            p = theme.current()
            ax = self.model_chart.new_axes()
            x = np.arange(res.months.size)
            ax.plot(x, res.s("ebitda") * st.fx(), color=p.teal, label="EBITDA")
            ax.plot(x, res.s("cfo") * st.fx(), color=p.blue, label="Operating cash flow")
            tk, lb = month_axis_labels(res, 6)
            ax.set_xticks(tk, lb)
            ax.yaxis.set_major_formatter(money_formatter())
            self.model_chart.legend(ax)
            self.model_chart.draw()
        elif code == "F":
            wc = st.draft["working_capital"]
            self.model_inputs.set(pd.DataFrame([
                {"Driver": "DSO (credit sales)", "Type": "Input", "Value": f"{wc['dso_days']:.0f} days"},
                {"Driver": "DPO (non-payroll costs)", "Type": "Input", "Value": f"{wc['dpo_days']:.0f} days"},
                {"Driver": "F&B inventory days", "Type": "Input", "Value": f"{st.draft['fnb']['inventory_days']:.0f} days"},
                {"Driver": "VAT payment lag", "Type": "Input",
                 "Value": f"{st.draft['tax']['vat_payment_lag_months']} month(s)"},
                {"Driver": "Minimum cash", "Type": "Input", "Value": st.money(st.draft['financing']['minimum_cash'])}]))
            data = {"Month": [m.strftime("%b %Y") for m in res.months]}
            for k, lab in (("accounts_receivable", "Receivables"), ("inventory", "Inventory"),
                           ("accounts_payable", "Payables"), ("vat_payable", "VAT payable"),
                           ("deferred_revenue", "Deposits")):
                data[lab] = res.s(k)
            df = pd.DataFrame(data)
            df["Net working capital"] = df["Receivables"] + df["Inventory"] - df["Payables"] - df["VAT payable"] \
                - df["Deposits"]
            days = res.months.days_in_month.to_numpy()
            dso = res.s("accounts_receivable") / (res.s("gross_billings") / days)
            df["DSO (all billings)"] = dso
            df["Closing cash"] = res.s("cash")
            self.model_table.set(df, {**formatters(st, money_cols=[c for c in df.columns if c not in (
                "Month", "DSO (all billings)")]), "DSO (all billings)": lambda v: f"{v:.1f} d"})
            b = QWidget()
            bl = QVBoxLayout(b)
            sl1 = res.year_slice(1)
            bl.addWidget(label(
                f"Year 1: EBITDA {st.money(res.total('ebitda', sl1))} → operating cash flow "
                f"{st.money(res.total('cfo', sl1))} (cash conversion "
                f"{(safe_div(res.total('cfo', sl1), res.total('ebitda', sl1)) or 0) * 100:.0f}%). "
                "Differences come from working-capital movements, interest and tax.", wrap=True))
            self.extra_lay.addWidget(b)
        elif code == "G":
            projs = st.draft["capex"]["projects"]
            self.model_inputs.set(pd.DataFrame(
                [{"Project": p_["name"], "Type": "Input", "Month": p_["month"], "Amount": st.money(p_["amount"]),
                  "Life": p_.get("life_years"), "OOO rooms": p_.get("ooo_rooms", 0),
                  "Months": p_.get("ooo_months", 0), "Rate uplift": f"{p_.get('rate_uplift_pct', 0) * 100:.1f}%"}
                 for p_ in projs] or [{"Project": "No planned projects", "Type": "", "Month": "", "Amount": "",
                                       "Life": "", "OOO rooms": "", "Months": "", "Rate uplift": ""}]))
            years = sorted({m.year for m in res.months})
            rows = []
            for i, y in enumerate(years):
                s_ = res.year_slice(i + 1)
                rows.append({"Year": f"FY{y}", "Opening NBV": float(res.s("fa_gross_opening")[s_][0]),
                             "Capex": res.total("capex", s_), "Depreciation": res.total("depreciation", s_),
                             "Closing NBV": float(res.s("fa_nbv")[s_][-1])})
            self.model_table.set(pd.DataFrame(rows), formatters(st, money_cols=["Opening NBV", "Capex",
                                                                                 "Depreciation", "Closing NBV"]))
            self.p_month.clear()
            self.p_month.addItems([str(m) for m in res.months])
            self.extra_lay.addWidget(self.proj_box)
        elif code == "H":
            ol = se.operating_leverage(res, sl)
            occ = t("occupied_rooms")
            avail = t("available_rooms")
            cpr = safe_div(ol["contribution"], occ)
            be_occ = safe_div(safe_div(ol["fixed_costs"], cpr), avail) if cpr else None
            self.model_inputs.setVisible(False)
            self.model_inputs_lbl.setVisible(False)
            rows = [
                {"Measure": "Total revenue per occupied room", "Value": st.money(safe_div(ol["revenue"], occ), 0),
                 "Formula": "Total revenue ÷ occupied rooms"},
                {"Measure": "Variable cost per occupied room", "Value": st.money(safe_div(ol["variable_costs"], occ), 0),
                 "Formula": "Activity-driven costs ÷ occupied rooms"},
                {"Measure": "Contribution per occupied room", "Value": st.money(cpr, 0),
                 "Formula": "Revenue − variable costs, per occupied room"},
                {"Measure": "Contribution margin", "Value": f"{(ol['contribution_margin'] or 0) * 100:.1f}%",
                 "Formula": "Contribution ÷ revenue"},
                {"Measure": "Fixed costs (period)", "Value": st.money(ol["fixed_costs"]),
                 "Formula": "Contribution − EBITDA"},
                {"Measure": "Break-even occupancy (EBITDA = 0)",
                 "Value": "n/a" if be_occ is None else f"{be_occ * 100:.1f}%",
                 "Formula": "Fixed costs ÷ contribution per room ÷ available rooms (holds mix & rate constant)"},
                {"Measure": "Degree of operating leverage", "Value": "n/a" if ol["dol"] is None else f"{ol['dol']:.2f}×",
                 "Formula": "Contribution ÷ EBITDA"},
            ]
            self.model_table.set(pd.DataFrame(rows))
            self.extra_lay.addWidget(label("Unit economics calculator (any product or service)", "H3"))
            self.extra_lay.addWidget(self.unit_box)
            self._unit_calc()

    # ------------------------------------------------------------------ dependency graph
    def _graph_tab(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Calculation node / line item"])
        self.tree.itemSelectionChanged.connect(self._show_item)
        split.addWidget(self.tree)
        right = QWidget()
        rl = QVBoxLayout(right)
        self.item_html = QTextBrowser()
        self.item_html.setMinimumHeight(220)
        rl.addWidget(self.item_html)
        self.item_chart = Chart(2.4)
        rl.addWidget(self.item_chart)
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        lay.addWidget(split)
        for n in G.order():
            node = QTreeWidgetItem([f"{n.name} – {n.description}"])
            node.setData(0, Qt.UserRole, None)
            for key, li in n.outputs.items():
                c = QTreeWidgetItem([f"{li.label}   [{key}]"])
                c.setData(0, Qt.UserRole, key)
                node.addChild(c)
            self.tree.addTopLevelItem(node)
        self.tabs.addTab(w, "Dependency viewer")

    def _show_item(self):
        items = self.tree.selectedItems()
        if not items or items[0].data(0, Qt.UserRole) is None:
            return
        key = items[0].data(0, Qt.UserRole)
        st = self.state
        res = st.result
        html = line_item_html(key, res, st)
        li = G.items[key]
        vals = []
        for path in li.inputs:
            if "*" in path:
                pre, post = path.split("*")
                for s in SEGMENTS:
                    try:
                        vals.append(f"{pre}{s}{post} = {get_path(st.draft, f'{pre}{s}{post}'.strip('.'))}")
                    except (KeyError, TypeError):
                        pass
            else:
                try:
                    v = get_path(st.draft, path)
                    vals.append(f"{path} = {v if not isinstance(v, (list, dict)) else '[structured]'}")
                except (KeyError, TypeError):
                    pass
        if vals:
            html += "<p><b>Current input values:</b><br>" + "<br>".join(vals) + "</p>"
        html += f"<p><b>Line-item key for custom formulas:</b> <code>{key}</code></p>"
        self.item_html.setHtml(html)
        p = theme.current()
        ax = self.item_chart.new_axes()
        x = np.arange(res.months.size)
        ax.plot(x, res.s(key), color=p.teal)
        tk, lb = month_axis_labels(res, 6)
        ax.set_xticks(tk, lb)
        ax.set_title(li.label)
        if li.unit == "currency":
            ax.yaxis.set_major_formatter(money_formatter())
        self.item_chart.draw()

    # ------------------------------------------------------------------ custom formulas
    def _formula_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Build your own metric from line-item keys (see the dependency viewer). Values are "
                            "period totals of the working scenario. Example: <code>ebitda / total_revenue</code> or "
                            "<code>SAFEDIV(commissions, rooms_revenue, 0)</code>. Functions: MIN, MAX, ABS, ROUND, IF, "
                            "SAFEDIV. Formulas are evaluated by a restricted, safe evaluator.", "Muted", wrap=True))
        row = QHBoxLayout()
        self.f_name = QLineEdit()
        self.f_name.setPlaceholderText("Metric name, e.g. Payroll per occupied room")
        self.f_expr = QLineEdit()
        self.f_expr.setPlaceholderText("Expression")
        self.f_period = period_combo()
        row.addWidget(self.f_name, 1)
        row.addWidget(self.f_expr, 2)
        row.addWidget(self.f_period)
        row.addWidget(button("Evaluate", self._eval_formula))
        row.addWidget(button("Save metric", self._save_formula, primary=True))
        lay.addLayout(row)
        self.f_result = label("", wrap=True)
        lay.addWidget(self.f_result)
        lay.addWidget(label("Saved metrics (live)", "H3"))
        self.f_table = Table(min_height=200)
        lay.addWidget(self.f_table)
        lay.addWidget(button("Delete selected metric", self._delete_formula, danger=True))
        lay.addStretch(1)
        self.tabs.addTab(w, "Custom formulas")

    def _names(self, sl):
        res = self.state.result
        return {k: float(v[sl].sum()) if k not in ("cash", "fa_nbv", "term_loan", "revolver") else float(v[sl][-1])
                for k, v in res.series.items()}

    def _eval_formula(self):
        res = self.state.result
        sl = period_slice(res, self.f_period.currentData())
        try:
            v = ex.evaluate(self.f_expr.text(), self._names(sl))
            used = ex.names_in(self.f_expr.text())
            self.f_result.setText(f"Result: <b>{v:,.4f}</b>  ·  inputs used: " + ", ".join(
                f"{G.items[u].label} = {self._names(sl)[u]:,.0f}" for u in sorted(used) if u in G.items))
            return True
        except ex.ExprError as exc:
            self.f_result.setText(f"<span style='color:#F0616D'>Formula error: {exc}</span>")
            return False

    def _save_formula(self):
        if not self.f_name.text().strip():
            error(self, "Name required", "Give the metric a name.")
            return
        if not self._eval_formula():
            return
        try:
            self.state.db.execute("INSERT INTO custom_metrics(name, expression, created_at) VALUES (?,?,?)",
                                  (self.f_name.text().strip(), self.f_expr.text().strip(), now()))
            self.state.db.audit("custom_metric", note=f"{self.f_name.text().strip()} = {self.f_expr.text().strip()}")
        except Exception as exc:  # noqa: BLE001
            error(self, "Could not save", str(exc))
        self.refresh()

    def _delete_formula(self):
        idx = self.f_table.currentIndex()
        if not idx.isValid():
            return
        name = self.f_table.model_.df.iloc[idx.row()]["Metric"]
        self.state.db.execute("DELETE FROM custom_metrics WHERE name = ?", (name,))
        self.refresh()

    # ------------------------------------------------------------------ warnings
    def _warnings_tab(self):
        self.warn_html = QTextBrowser()
        self.tabs.addTab(self.warn_html, "Model warnings")

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        if self.model_list.currentRow() < 0:
            self.model_list.setCurrentRow(0)
        self._show_model()
        st = self.state
        res = st.result
        rows = []
        for r in st.db.query("SELECT * FROM custom_metrics ORDER BY id"):
            vals = {}
            for y in (1, 2, 3):
                try:
                    vals[f"FY{2026 + y}"] = ex.evaluate(r["expression"], self._names(res.year_slice(y)))
                except ex.ExprError as exc:
                    vals[f"FY{2026 + y}"] = f"error: {exc}"
            rows.append({"Metric": r["name"], "Expression": r["expression"], **vals})
        self.f_table.set(pd.DataFrame(rows or [{"Metric": "No saved metrics", "Expression": ""}]),
                         {"*": lambda v: f"{v:,.4f}" if abs(v) < 100 else f"{v:,.0f}"})
        probs = validate(st.draft)
        html = "<h3>Input validation</h3>" + ("<p>All inputs valid.</p>" if not probs else
                                              "<ul>" + "".join(f"<li>{p}</li>" for p in probs) + "</ul>")
        html += "<h3>Model warnings</h3>" + ("<p>None.</p>" if not res.warnings else
                                             "<ul>" + "".join(f"<li>{w}</li>" for w in res.warnings) + "</ul>")
        a = st.draft
        soft = []
        for s in SEGMENTS:
            sg = a["segments"][s]
            if sg["elasticity"] < -3:
                soft.append(f"{SEGMENT_LABELS[s]}: elasticity {sg['elasticity']} is extreme; small price moves will "
                            "swing demand heavily. Treat outputs with caution.")
            ratio = sg["published_rate"] * (1 - sg["discount_pct"]) / sg["reference_rate"]
            if ratio > 1.5 or ratio < 0.5:
                soft.append(f"{SEGMENT_LABELS[s]}: realised rate is {ratio:.1f}× the market reference – outside the "
                            "range where a constant-elasticity demand curve is credible.")
        if a["rooms"]["overbooking_pct"] > 0.1:
            soft.append("Overbooking above 10% is aggressive; walk costs and reputation risk are not fully modelled.")
        if a["rooms"]["demand_noise_sd"] == 0:
            soft.append("Demand noise is off: results are fully deterministic (useful for teaching, less realistic).")
        html += "<h3>Reliability notes</h3>" + ("<p>No reliability concerns detected.</p>" if not soft else
                                                "<ul>" + "".join(f"<li>{x}</li>" for x in soft) + "</ul>")
        html += "<h3>Integrity checks</h3><ul>" + "".join(
            f"<li>{'✓' if c.passed else '✗'} {c.name} (max diff {c.max_abs_error:.6f})</li>" for c in res.checks) + "</ul>"
        self.warn_html.setHtml(html)
