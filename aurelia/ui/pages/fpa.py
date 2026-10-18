"""FP&A lab: budget, actuals, variances, flexible budgets, forecasts, versions and action plans."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QTabWidget, QComboBox, QFormLayout, QLineEdit,
                               QDateEdit, QTextEdit, QDoubleSpinBox, QInputDialog, QTextBrowser)

from ...analysis.fpa import build_fpa, Materiality, forecast_snapshot, PNL_LINES
from ...model.assumptions import DEPARTMENTS, DEPARTMENT_LABELS
from ...persistence.db import now
from ..common import formatters
from ..widgets import Page, card, label, button, Table, Chart, money_formatter, error, confirm, Banner
from .. import theme


class FPAPage(Page):
    def __init__(self, state):
        super().__init__("FP&A and Variance Analysis",
                         "Budget, actuals and forecast for FY2027. Actuals are closed through the selected month; "
                         "the latest estimate combines actuals with your working scenario for the remaining months.")
        self.state = state
        bar, bl = card(QHBoxLayout, 10)
        bl.addWidget(label("Budget scenario:", "Muted"))
        self.budget_cb = QComboBox()
        self.budget_cb.activated.connect(self._set_budget)
        bl.addWidget(self.budget_cb)
        bl.addWidget(label("Actuals closed through:", "Muted"))
        self.asof_cb = QComboBox()
        self.asof_cb.addItems([f"{m} 2027" for m in ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
                                                      "Oct", "Nov", "Dec")])
        self.asof_cb.activated.connect(self._set_asof)
        bl.addWidget(self.asof_cb)
        bl.addWidget(label("Materiality:", "Muted"))
        self.mat_abs = QDoubleSpinBox()
        self.mat_abs.setRange(0, 1e9)
        self.mat_abs.setPrefix("SAR ")
        self.mat_abs.setGroupSeparatorShown(True)
        self.mat_abs.setDecimals(0)
        self.mat_abs.setSingleStep(50000)
        self.mat_pct = QDoubleSpinBox()
        self.mat_pct.setRange(0, 100)
        self.mat_pct.setSuffix(" %")
        for w in (self.mat_abs, self.mat_pct):
            w.setKeyboardTracking(False)
            w.editingFinished.connect(self._set_materiality)
            bl.addWidget(w)
        bl.addStretch(1)
        self.body.addWidget(bar)
        self.banner = Banner()
        self.body.addWidget(self.banner)
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._perf_tab()
        self._rooms_tab()
        self._flex_tab()
        self._forecast_tab()
        self._budget_tab()
        self._actions_tab()
        state.results_changed.connect(self.refresh)
        state.scenarios_changed.connect(self.refresh)
        state.theme_changed.connect(lambda _n: self.refresh())

    # ------------------------------------------------------------------ data
    def data(self):
        st = self.state
        name = st.db.get_setting("fpa_budget_scenario", "Base case")
        if name not in st.store.names():
            name = "Base case"
        m = Materiality(st.db.get_setting("materiality_abs", 250_000.0), st.db.get_setting("materiality_pct", 0.05))
        return build_fpa(st.store.get(name).assumptions, st.draft, st.db.get_setting("fpa_as_of", 9), m)

    def _set_budget(self, _i):
        self.state.db.set_setting("fpa_budget_scenario", self.budget_cb.currentText())
        self.refresh()

    def _set_asof(self, i):
        self.state.db.set_setting("fpa_as_of", i + 1)
        self.refresh()

    def _set_materiality(self):
        self.state.db.set_setting("materiality_abs", self.mat_abs.value())
        self.state.db.set_setting("materiality_pct", self.mat_pct.value() / 100)
        self.refresh()

    # ------------------------------------------------------------------ tabs
    def _perf_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(label("Period:", "Muted"))
        self.per_cb = QComboBox()
        self.per_cb.addItem("Year to date (actual vs budget)", ("ytd", "budget"))
        self.per_cb.addItem("Close month (actual vs budget)", ("month", "budget"))
        self.per_cb.addItem("Full year: latest estimate vs budget", ("fy", "budget"))
        self.per_cb.addItem("Year to date (actual vs working forecast)", ("ytd", "forecast"))
        self.per_cb.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.per_cb)
        row.addStretch(1)
        lay.addLayout(row)
        self.var_table = Table(stretch_first=False, min_height=420)
        lay.addWidget(self.var_table)
        r2 = QHBoxLayout()
        f, l = card()
        l.addWidget(label("EBITDA bridge: budget → actual", "H3"))
        self.ch_bridge = Chart(2.8)
        l.addWidget(self.ch_bridge)
        r2.addWidget(f, 1)
        f2, l2 = card()
        l2.addWidget(label("Material variances – evidence", "H3"))
        l2.addWidget(label("Quantified driver attribution is separated from causes that still need confirming. "
                           "Residuals not explained by modelled drivers are shown as unexplained.", "Muted",
                           wrap=True))
        self.expl = QTextBrowser()
        self.expl.setMinimumHeight(260)
        l2.addWidget(self.expl)
        r2.addWidget(f2, 1)
        lay.addLayout(r2)
        self.tabs.addTab(w, "Performance vs budget")

    def _rooms_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Room revenue variance split into rate, mix and volume (YTD). Rate = Σ(ADR actual − ADR "
                            "budget) × RN actual; Mix = Σ(mix actual − mix budget) × total RN actual × ADR budget; "
                            "Volume = (RN actual − RN budget) × budget average ADR.", "Muted", wrap=True))
        self.rmv_lbl = label("", "H3")
        lay.addWidget(self.rmv_lbl)
        f, l = card()
        self.ch_rmv = Chart(2.4)
        l.addWidget(self.ch_rmv)
        lay.addWidget(f)
        self.rmv_table = Table(min_height=200)
        lay.addWidget(self.rmv_table)
        self.tabs.addTab(w, "Rate, mix and volume")

    def _flex_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Flexible budget = budgeted fixed cost + budgeted variable rate × ACTUAL activity. "
                            "Activity variance = flexible − static budget (caused by volume). Spending variance = "
                            "actual − flexible (caused by price or efficiency).", "Muted", wrap=True))
        self.flex_table = Table(min_height=200)
        lay.addWidget(self.flex_table)
        lay.addWidget(label("Payroll: rate (pay & overtime) and headcount (efficiency) variances, YTD", "H3"))
        self.pay_table = Table(min_height=240)
        lay.addWidget(self.pay_table)
        self.util_lbl = label("", wrap=True)
        lay.addWidget(self.util_lbl)
        self.tabs.addTab(w, "Flexible budget and payroll")

    def _forecast_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        r = QHBoxLayout()
        f, l = card()
        l.addWidget(label("FY2027 EBITDA by month: actual, latest estimate and budget", "H3"))
        self.ch_le = Chart(2.6)
        l.addWidget(self.ch_le)
        r.addWidget(f, 3)
        f2, l2 = card()
        l2.addWidget(label("Year-end estimates (EBITDA)", "H3"))
        self.rr_lbl = label("", wrap=True)
        l2.addWidget(self.rr_lbl)
        l2.addStretch(1)
        r.addWidget(f2, 2)
        lay.addLayout(r)
        lay.addWidget(label("Rolling 12-month forecast (working scenario, months after the close)", "H3"))
        self.roll_table = Table(min_height=240)
        lay.addWidget(self.roll_table)
        f3, l3 = card()
        l3.addWidget(label("Forecast versions and approval", "H3"))
        row = QHBoxLayout()
        row.addWidget(button("Save current LE as new version", self._new_version, primary=True))
        row.addWidget(button("Submit for approval", lambda: self._set_status("Submitted")))
        row.addWidget(button("Approve…", lambda: self._set_status("Approved")))
        row.addWidget(button("Reject…", lambda: self._set_status("Rejected")))
        row.addStretch(1)
        l3.addLayout(row)
        self.ver_table = Table(min_height=160)
        l3.addWidget(self.ver_table)
        lay.addWidget(f3)
        self.tabs.addTab(w, "Forecast and versions")

    def _budget_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Annual operating budget by month, from the budget scenario. Use the Scenario Lab to "
                            "build an alternative plan and select it above as the budget.", "Muted", wrap=True))
        self.bud_table = Table(min_height=420)
        lay.addWidget(self.bud_table)
        lay.addWidget(label("Departmental budgets (FY2027): revenue, payroll and contribution", "H3"))
        self.dept_table = Table(min_height=220)
        lay.addWidget(self.dept_table)
        self.tabs.addTab(w, "Budget")

    def _actions_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        f, l = card()
        l.addWidget(label("Corrective action plan", "H3"))
        form = QFormLayout()
        self.ap_title = QLineEdit()
        self.ap_title.setPlaceholderText("e.g. Renegotiate OTA promotion commission")
        self.ap_owner = QLineEdit()
        self.ap_owner.setPlaceholderText("e.g. Director of Revenue (role or name)")
        self.ap_due = QDateEdit(QDate.currentDate().addDays(30))
        self.ap_due.setCalendarPopup(True)
        self.ap_var = QComboBox()
        self.ap_var.addItems([lab for _k, lab, _n, _g in PNL_LINES])
        self.ap_notes = QTextEdit()
        self.ap_notes.setMaximumHeight(70)
        form.addRow("Action", self.ap_title)
        form.addRow("Owner", self.ap_owner)
        form.addRow("Due date", self.ap_due)
        form.addRow("Variance addressed", self.ap_var)
        form.addRow("Expected impact / notes", self.ap_notes)
        l.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button("Add action", self._add_action, primary=True))
        row.addWidget(button("Mark selected done", lambda: self._action_status("Done")))
        row.addWidget(button("Mark selected in progress", lambda: self._action_status("In progress")))
        row.addWidget(button("Delete selected", self._delete_action, danger=True))
        row.addStretch(1)
        l.addLayout(row)
        lay.addWidget(f)
        self.ap_table = Table(min_height=220)
        lay.addWidget(self.ap_table)
        self.tabs.addTab(w, "Action plans")

    # ------------------------------------------------------------------ actions
    def _new_version(self):
        name, ok = QInputDialog.getText(self, "Forecast version", "Version name:", QLineEdit.Normal,
                                        f"LE {now()[:10]} – {self.state.scenario_name}")
        if not ok or not name.strip():
            return
        snap = forecast_snapshot(self.data())
        self.state.db.execute("INSERT INTO forecast_versions(created_at, name, scenario_name, status, snapshot) "
                              "VALUES (?,?,?,?,?)", (now(), name.strip(), self.state.scenario_name, "Draft",
                                                     json.dumps(snap)))
        self.state.db.audit("forecast_version", note=f"Created forecast version '{name.strip()}'")
        self.refresh()

    def _selected_id(self, table):
        idx = table.currentIndex()
        if not idx.isValid():
            return None
        df = table.model_.df
        return int(df.iloc[idx.row()]["ID"]) if "ID" in df.columns else None

    def _set_status(self, status):
        vid = self._selected_id(self.ver_table)
        if vid is None:
            error(self, "Select a version", "Select a forecast version in the table first.")
            return
        approver = None
        if status in ("Approved", "Rejected"):
            approver, ok = QInputDialog.getText(self, status, "Approver (role or name):")
            if not ok or not approver.strip():
                return
        row = self.state.db.one("SELECT status FROM forecast_versions WHERE id = ?", (vid,))
        allowed = {"Submitted": ("Draft", "Rejected"), "Approved": ("Submitted",), "Rejected": ("Submitted",)}
        if row["status"] not in allowed[status]:
            error(self, "Workflow", f"A version must be {' or '.join(allowed[status])} before it can be {status}.")
            return
        self.state.db.execute("UPDATE forecast_versions SET status = ?, approved_by = ? WHERE id = ?",
                              (status, approver, vid))
        self.state.db.audit("forecast_status", note=f"Version {vid} → {status}" + (f" by {approver}" if approver
                                                                                     else ""))
        self.refresh()

    def _add_action(self):
        t, o = self.ap_title.text().strip(), self.ap_owner.text().strip()
        if not t or not o:
            error(self, "Missing information", "Every corrective action needs a description and a named owner.")
            return
        self.state.db.execute("INSERT INTO action_plans(created_at, title, owner, due_date, status, variance_ref, "
                              "notes) VALUES (?,?,?,?,?,?,?)",
                              (now(), t, o, self.ap_due.date().toString("yyyy-MM-dd"), "Open",
                               self.ap_var.currentText(), self.ap_notes.toPlainText()))
        self.ap_title.clear()
        self.ap_notes.clear()
        self.state.progress_changed.emit()
        self.refresh()

    def _action_status(self, status):
        aid = self._selected_id(self.ap_table)
        if aid is None:
            error(self, "Select an action", "Select an action in the table first.")
            return
        self.state.db.execute("UPDATE action_plans SET status = ? WHERE id = ?", (status, aid))
        self.refresh()

    def _delete_action(self):
        aid = self._selected_id(self.ap_table)
        if aid is not None and confirm(self, "Delete action", "Delete the selected action?"):
            self.state.db.execute("DELETE FROM action_plans WHERE id = ?", (aid,))
            self.refresh()

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        st = self.state
        names = st.store.names()
        self.budget_cb.blockSignals(True)
        self.budget_cb.clear()
        self.budget_cb.addItems(names)
        self.budget_cb.setCurrentText(st.db.get_setting("fpa_budget_scenario", "Base case"))
        self.budget_cb.blockSignals(False)
        self.asof_cb.blockSignals(True)
        self.asof_cb.setCurrentIndex(st.db.get_setting("fpa_as_of", 9) - 1)
        self.asof_cb.blockSignals(False)
        for w, v in ((self.mat_abs, st.db.get_setting("materiality_abs", 250_000.0)),
                     (self.mat_pct, st.db.get_setting("materiality_pct", 0.05) * 100)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)
        d = self.data()
        self.banner.set_text("Actuals are fictional training data generated by the engine from a hidden "
                             "'what actually happened' assumption set. Compare them with the budget to practise "
                             "variance analysis.")
        period, compare = self.per_cb.currentData()
        vt = d.variance_table(period, compare=compare)
        ref_col = "Budget" if compare == "budget" else "Forecast"
        nat = {"F/U": lambda r, v: "good" if v == "F" else ("bad" if v == "U" else None),
               "Variance": lambda r, v, df=vt: "good" if df.iloc[r]["F/U"] == "F" else (
                   "bad" if df.iloc[r]["F/U"] == "U" else None)}
        bold = [i for i, (k, *_r) in enumerate(PNL_LINES) if k in ("total_revenue", "total_dept_profit", "gop",
                                                                     "ebitda")]
        self.var_table.set(vt.drop(columns=["key"]), {**formatters(st, money_cols=["Actual", ref_col, "Variance"],
                                                                   pct_cols=["Variance %"])}, bold, nature=nat)
        self.var_table.fit_height(24)
        html = ""
        for e in d.explanations("ytd" if period != "month" else "month"):
            html += (f"<p><b>{e['line']}</b> – variance {st.money(e['variance'])} "
                     f"({'favourable' if e['fu'] == 'F' else 'unfavourable'})<br>")
            html += "".join(f"• {x}<br>" for x in e["evidence"])
            if e["to_confirm"]:
                html += "<i>To confirm (not established by the data):</i><br>" + "".join(
                    f"– {x}<br>" for x in e["to_confirm"])
            html += "</p>"
        self.expl.setHtml(html or "<p>No variances exceed the materiality thresholds.</p>")
        self._bridge(d)
        self._rooms(d)
        self._flex(d)
        self._forecast(d)
        self._budget(d)
        self._actions()

    def _bridge(self, d):
        p = theme.current()
        sl = d.ytd_slice()
        fx = self.state.fx()
        t = lambda r, k: r.total(k, sl) * fx  # noqa: E731
        A, B = d.actual, d.budget
        steps = [("Room revenue", t(A, "rooms_revenue") - t(B, "rooms_revenue")),
                 ("Other revenue", (t(A, "total_revenue") - t(A, "rooms_revenue")) - (
                     t(B, "total_revenue") - t(B, "rooms_revenue"))),
                 ("Commissions", -(t(A, "commissions") - t(B, "commissions"))),
                 ("Payroll", -sum(t(A, f"payroll_{x}") - t(B, f"payroll_{x}") for x in DEPARTMENTS)
                  - ((t(A, "fnb_labour") - t(A, "payroll_fnb")) - (t(B, "fnb_labour") - t(B, "payroll_fnb")))),
                 ("Cost of sales", -((t(A, "fnb_cogs") + t(A, "spa_costs") + t(A, "events_costs"))
                                     - (t(B, "fnb_cogs") + t(B, "spa_costs") + t(B, "events_costs")))),
                 ("Utilities", -(t(A, "utilities_expense") - t(B, "utilities_expense"))),
                 ("Marketing", -(t(A, "campaign_spend") - t(B, "campaign_spend")))]
        total = t(A, "ebitda") - t(B, "ebitda")
        steps.append(("Other", total - sum(s[1] for s in steps)))
        ax = self.ch_bridge.new_axes()
        start = t(B, "ebitda")
        ax.bar(0, start, color=p.muted)
        cum = start
        for i, (_n, v) in enumerate(steps, 1):
            ax.bar(i, v, bottom=cum if v >= 0 else cum + v, color=p.good if v >= 0 else p.bad)
            cum += v
        ax.bar(len(steps) + 1, cum, color=p.teal)
        ax.set_xticks(range(len(steps) + 2), ["Budget"] + [s[0] for s in steps] + ["Actual"], fontsize=7,
                      rotation=30)
        lo = min(start, cum) * 0.85
        ax.set_ylim(bottom=lo)
        ax.yaxis.set_major_formatter(money_formatter())
        self.ch_bridge.draw()

    def _rooms(self, d):
        st = self.state
        br = d.rooms_revenue_bridge(d.ytd_slice())
        self.rmv_lbl.setText(f"Total {st.money(br['total'])} = rate {st.money(br['rate'])} + mix "
                             f"{st.money(br['mix'])} + volume {st.money(br['quantity'])}")
        p = theme.current()
        ax = self.ch_rmv.new_axes()
        vals = [br["rate"], br["mix"], br["quantity"], br["total"]]
        ax.bar(["Rate", "Mix", "Volume", "Total"], [v * st.fx() for v in vals],
               color=[p.good if v >= 0 else p.bad for v in vals[:3]] + [p.teal])
        ax.yaxis.set_major_formatter(money_formatter())
        self.ch_rmv.draw()
        self.rmv_table.set(br["by_segment"], formatters(st, int_cols=["RN actual", "RN budget"],
                                                        pct_cols=["RN variance %"],
                                                        dec_money_cols=["ADR actual", "ADR budget"],
                                                        money_cols=["Revenue variance"]))

    def _flex(self, d):
        st = self.state
        sl = d.ytd_slice()
        fb = d.flexible_budget(sl)
        self.flex_table.set(fb, formatters(st, money_cols=["Static budget", "Flexible budget", "Actual",
                                                           "Activity variance", "Spending variance"]))
        pv = d.payroll_variances(sl)
        self.pay_table.set(pv, formatters(st, int_cols=["FTE actual", "FTE budget"],
                                          money_cols=["Cost per FTE / month actual", "Cost per FTE / month budget",
                                                      "Rate variance", "Headcount (efficiency) variance",
                                                      "Total variance"]))
        uv = d.utilities_variance(sl)
        self.util_lbl.setText(f"<b>Energy:</b> price effect {st.money(uv['price'])} (SAR {uv['price_actual']:.2f} vs "
                              f"{uv['price_budget']:.2f}/kWh), consumption effect {st.money(uv['consumption'])} "
                              f"({uv['kwh_actual']:,.0f} vs {uv['kwh_budget']:,.0f} kWh). Energy cost only; water "
                              "and inflation are excluded from this split.")

    def _forecast(self, d):
        st = self.state
        p = theme.current()
        fx = st.fx()
        ax = self.ch_le.new_axes()
        x = np.arange(12)
        le, bud = d.le("ebitda") * fx, d.budget.s("ebitda")[:12] * fx
        ax.bar(x[:d.as_of], le[:d.as_of], color=p.teal, label="Actual")
        ax.bar(x[d.as_of:], le[d.as_of:], color=p.blue, alpha=0.6, label="Forecast (working scenario)")
        ax.plot(x, bud, color=p.amber, marker="o", lw=1.4, label="Budget")
        ax.set_xticks(x, [m.strftime("%b") for m in d.actual.months[:12]])
        ax.yaxis.set_major_formatter(money_formatter())
        self.ch_le.legend(ax, loc="upper right")
        self.ch_le.draw()
        rr = d.run_rate()
        self.rr_lbl.setText(
            f"YTD actual: <b>{st.money(rr['ytd_actual'])}</b><br>Simple run-rate (YTD ÷ {d.as_of} × 12): "
            f"<b>{st.money(rr['run_rate_fy'])}</b><br>Latest estimate (actuals + forecast): "
            f"<b>{st.money(rr['latest_estimate'])}</b><br>Budget: <b>{st.money(rr['budget'])}</b><br><br>"
            "The run-rate ignores seasonality, so it misstates the year when the remaining months are seasonally "
            "different. The latest estimate uses the driver-based model instead.")
        rf = d.rolling_forecast(12)
        self.roll_table.set(rf, formatters(st, pct_cols=["Occupancy"], dec_money_cols=["ADR"],
                                           money_cols=["Total revenue", "GOP", "EBITDA", "Closing cash"]))
        rows = []
        for r in st.db.query("SELECT * FROM forecast_versions ORDER BY id DESC"):
            snap = json.loads(r["snapshot"] or "{}")
            le_e = sum(snap.get("le", {}).get("ebitda", [0]))
            rows.append({"ID": r["id"], "Version": r["name"], "Scenario": r["scenario_name"], "Status": r["status"],
                         "Approved/rejected by": r["approved_by"] or "", "Created": r["created_at"],
                         "LE EBITDA": le_e, "Closed through": f"month {snap.get('as_of', '')}"})
        self.ver_table.set(pd.DataFrame(rows or [{"ID": "", "Version": "No versions yet", "Scenario": "",
                                                  "Status": "", "Approved/rejected by": "", "Created": "",
                                                  "LE EBITDA": None, "Closed through": ""}]),
                           formatters(st, money_cols=["LE EBITDA"]))

    def _budget(self, d):
        st = self.state
        B = d.budget
        keys = [k for k, *_r in PNL_LINES if k != "cfo"]
        data = {"Line": [lab for k, lab, *_r in PNL_LINES if k != "cfo"]}
        for m in range(12):
            data[B.months[m].strftime("%b")] = [float(B.s(k)[m]) for k in keys]
        data["FY total"] = [float(B.s(k)[:12].sum()) for k in keys]
        df = pd.DataFrame(data)
        self.bud_table.set(df, formatters(st, money_cols=[c for c in df.columns if c != "Line"]),
                           [i for i, k in enumerate(keys) if k in ("total_revenue", "total_dept_profit", "gop",
                                                                   "ebitda")])
        sl = slice(0, 12)
        rev = {"rooms": "rooms_revenue", "fnb": "fnb_revenue", "spa": "spa_revenue", "events": "events_revenue"}
        prof = {"rooms": "rooms_profit", "fnb": "fnb_profit", "spa": "spa_profit", "events": "events_profit"}
        rows = []
        for dpt in DEPARTMENTS:
            rows.append({"Department": DEPARTMENT_LABELS[dpt], "FTE": B.assumptions["payroll"]["headcount"][dpt],
                         "Revenue": B.total(rev[dpt], sl) if dpt in rev else None,
                         "Payroll": B.total(f"payroll_{dpt}", sl),
                         "Contribution / cost": B.total(prof[dpt], sl) if dpt in prof else -B.total(
                             {"ag": "ag_expense", "sm": "sm_expense", "pom": "pom_expense"}[dpt], sl)})
        self.dept_table.set(pd.DataFrame(rows), formatters(st, int_cols=["FTE"], money_cols=["Revenue", "Payroll",
                                                                                              "Contribution / cost"]))

    def _actions(self):
        rows = [{"ID": r["id"], "Action": r["title"], "Owner": r["owner"], "Due": r["due_date"], "Status": r["status"],
                 "Variance": r["variance_ref"] or "", "Notes": r["notes"] or "",
                 "Overdue": "Yes" if r["status"] != "Done" and r["due_date"] < now()[:10] else ""}
                for r in self.state.db.query("SELECT * FROM action_plans ORDER BY due_date")]
        self.ap_table.set(pd.DataFrame(rows or [{"ID": "", "Action": "No actions yet", "Owner": "", "Due": "",
                                                 "Status": "", "Variance": "", "Notes": "", "Overdue": ""}]))
