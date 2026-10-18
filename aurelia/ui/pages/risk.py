"""Sensitivity, scenarios, break-even, Monte Carlo and forecast-error analysis."""
from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QTabWidget, QComboBox, QDoubleSpinBox, QSpinBox,
                               QTableWidget, QTableWidgetItem, QHeaderView)

from ...analysis import sensitivity as se, rm
from ...analysis.fpa import build_fpa
from ...model.assumptions import DRIVER_SPECS, SPEC_BY_PATH, get_path, HEADLINE_DRIVERS
from ...model.engine import simulate_cached
from ..common import period_combo, period_slice, formatters, run_with_progress, month_axis_labels
from ..widgets import Page, card, label, button, Table, Chart, money_formatter, error
from .. import theme

PSEUDO = [("segments.*.base_demand_mult", "All-segment demand (multiplier)"),
          ("segments.*.rate_mult", "All-segment rates (multiplier)")]
TORNADO = HEADLINE_DRIVERS + ["segments.group.base_demand", "fnb.dinner_capture", "spa.avg_treatment_price",
                              "payroll.on_cost_pct", "undistributed.ag_fixed_monthly",
                              "segments.leisure_ota.commission_pct"]


def _driver_combo():
    cb = QComboBox()
    for p, l in PSEUDO:
        cb.addItem(l, p)
    for s in DRIVER_SPECS:
        cb.addItem(s.label, s.path)
    return cb


def _metric_combo():
    cb = QComboBox()
    for k, (l, _f) in se.METRICS.items():
        cb.addItem(l, k)
    return cb


class RiskPage(Page):
    def __init__(self, state):
        super().__init__("Sensitivity and Risk",
                         "How sensitive are results to the assumptions? Every point is a full engine run. Scenario "
                         "assumptions are choices; Monte Carlo ranges show outcomes under stated distributions – "
                         "neither is a prediction of the future.")
        self.state = state
        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(label("Period:", "Muted"))
        self.period = period_combo()
        top.addWidget(self.period)
        self.body.addLayout(top)
        self.tabs = QTabWidget()
        self.body.addWidget(self.tabs, 1)
        self._one_way_tab()
        self._two_way_tab()
        self._tornado_tab()
        self._breakeven_tab()
        self._scenarios_tab()
        self._mc_tab()
        self._error_tab()
        state.results_changed.connect(self._refresh_light)

    def _sl(self):
        return period_slice(self.state.result, self.period.currentData())

    # ---- one-way
    def _one_way_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.ow_driver = _driver_combo()
        self.ow_metric = _metric_combo()
        self.ow_lo = QDoubleSpinBox()
        self.ow_hi = QDoubleSpinBox()
        self.ow_n = QSpinBox()
        for s_, v in ((self.ow_lo, -20), (self.ow_hi, 20)):
            s_.setRange(-95, 500)
            s_.setSuffix(" %")
            s_.setValue(v)
        self.ow_n.setRange(3, 21)
        self.ow_n.setValue(9)
        for wdg, lab in ((self.ow_driver, "Driver"), (self.ow_metric, "Metric"), (self.ow_lo, "From"),
                         (self.ow_hi, "To"), (self.ow_n, "Steps")):
            row.addWidget(label(lab + ":", "Muted"))
            row.addWidget(wdg)
        row.addWidget(button("Run", self._run_one_way, primary=True))
        row.addStretch(1)
        lay.addLayout(row)
        f, l = card()
        self.ow_chart = Chart(2.8)
        l.addWidget(self.ow_chart)
        lay.addWidget(f)
        self.ow_table = Table(min_height=220)
        lay.addWidget(self.ow_table)
        self.tabs.addTab(w, "One-variable")

    def _base_value(self, path):
        if path.startswith("segments.*"):
            return 1.0
        return float(get_path(self.state.draft, path) or 0)

    def _run_one_way(self):
        path = self.ow_driver.currentData()
        base = self._base_value(path)
        rel = np.linspace(self.ow_lo.value() / 100, self.ow_hi.value() / 100, self.ow_n.value())
        values = [base * (1 + r) for r in rel]
        spec = SPEC_BY_PATH.get(path)
        if spec and spec.unit == "int":
            values = sorted({int(round(v)) for v in values})
        metric = self.ow_metric.currentData()
        df = run_with_progress(self, "Running sensitivity…", se.one_way, self.state.draft, path, values, metric,
                               self._sl())
        unit_money = metric not in ("occupancy",)
        df.insert(1, "Change vs current", [(v / base - 1) if base else None for v in df["Input value"]])
        self.ow_table.set(df, {**formatters(self.state, pct_cols=["Change vs current"]),
                               "Input value": lambda v: f"{v:,.4g}",
                               "Result": (lambda v: self.state.money(v) if v is not None else "invalid")
                               if unit_money else (lambda v: f"{v * 100:.1f}%" if v is not None else "invalid")})
        p = theme.current()
        ax = self.ow_chart.new_axes()
        ok = df["Result"].notna()
        ax.plot(df["Input value"][ok], df["Result"][ok] * (self.state.fx() if unit_money else 1), marker="o",
                color=p.teal)
        ax.axvline(base, color=p.amber, ls=":", lw=1)
        ax.set_xlabel(self.ow_driver.currentText())
        ax.set_ylabel(se.METRICS[metric][0])
        if unit_money:
            ax.yaxis.set_major_formatter(money_formatter())
        self.ow_chart.draw()

    # ---- two-way
    def _two_way_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.tw_x = _driver_combo()
        self.tw_y = _driver_combo()
        self.tw_y.setCurrentIndex(1)
        self.tw_metric = _metric_combo()
        self.tw_range = QDoubleSpinBox()
        self.tw_range.setRange(1, 90)
        self.tw_range.setValue(15)
        self.tw_range.setSuffix(" %")
        for wdg, lab in ((self.tw_x, "Columns"), (self.tw_y, "Rows"), (self.tw_metric, "Metric"),
                         (self.tw_range, "± range")):
            row.addWidget(label(lab + ":", "Muted"))
            row.addWidget(wdg)
        row.addWidget(button("Run 5×5 grid", self._run_two_way, primary=True))
        row.addStretch(1)
        lay.addLayout(row)
        f, l = card()
        self.tw_chart = Chart(3.4)
        l.addWidget(self.tw_chart)
        lay.addWidget(f)
        self.tw_table = Table(min_height=180)
        lay.addWidget(self.tw_table)
        self.tabs.addTab(w, "Two-variable heatmap")

    def _run_two_way(self):
        px, py = self.tw_x.currentData(), self.tw_y.currentData()
        if px == py:
            error(self, "Two drivers", "Choose two different drivers.")
            return
        r = self.tw_range.value() / 100
        rel = np.linspace(-r, r, 5)
        bx, by = self._base_value(px), self._base_value(py)
        xs, ys = [bx * (1 + v) for v in rel], [by * (1 + v) for v in rel]
        metric = self.tw_metric.currentData()
        grid = run_with_progress(self, "Running 25 scenarios…", se.two_way, self.state.draft, px, xs, py, ys, metric,
                                 self._sl())
        p = theme.current()
        ax = self.tw_chart.new_axes()
        import matplotlib.colors as mcolors
        cmap = mcolors.LinearSegmentedColormap.from_list("aur", [p.bad, p.surface2, p.teal])
        im = ax.imshow(grid.values, cmap=cmap, aspect="auto", origin="lower")
        ax.set_xticks(range(5), [f"{v:,.3g}" for v in xs], fontsize=7)
        ax.set_yticks(range(5), [f"{v:,.3g}" for v in ys], fontsize=7)
        ax.set_xlabel(self.tw_x.currentText())
        ax.set_ylabel(self.tw_y.currentText())
        ax.grid(False)
        money = metric != "occupancy"
        for i in range(5):
            for j in range(5):
                v = grid.values[i, j]
                ax.text(j, i, "n/a" if np.isnan(v) else (f"{v / 1e6:.1f}m" if money else f"{v * 100:.0f}%"),
                        ha="center", va="center", fontsize=7, color=p.text)
        self.tw_chart.figure.colorbar(im, ax=ax, shrink=0.8)
        self.tw_chart.draw()
        df = grid.copy()
        df.columns = [f"{c:,.4g}" for c in df.columns]
        df.insert(0, "Rows \\ columns", [f"{v:,.4g}" for v in ys])
        self.tw_table.set(df.reset_index(drop=True), {"*": (lambda v: self.state.money(v)) if money else
                                                      (lambda v: f"{v * 100:.1f}%")})

    # ---- tornado
    def _tornado_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.to_metric = _metric_combo()
        self.to_swing = QDoubleSpinBox()
        self.to_swing.setRange(1, 50)
        self.to_swing.setValue(10)
        self.to_swing.setSuffix(" %")
        row.addWidget(label("Metric:", "Muted"))
        row.addWidget(self.to_metric)
        row.addWidget(label("Swing each driver ±", "Muted"))
        row.addWidget(self.to_swing)
        row.addWidget(button("Run tornado", self._run_tornado, primary=True))
        row.addStretch(1)
        lay.addLayout(row)
        f, l = card()
        self.to_chart = Chart(3.6)
        l.addWidget(self.to_chart)
        lay.addWidget(f)
        self.to_table = Table(min_height=200)
        lay.addWidget(self.to_table)
        self.tabs.addTab(w, "Tornado")

    def _run_tornado(self):
        metric = self.to_metric.currentData()
        df = run_with_progress(self, "Running tornado…", se.tornado, self.state.draft, TORNADO, metric, self._sl(),
                               self.to_swing.value() / 100)
        p = theme.current()
        ax = self.to_chart.new_axes()
        base = df["Base"].iloc[0]
        fx = self.state.fx() if metric != "occupancy" else 1
        y = np.arange(len(df))
        lo = (df["Result at low"].fillna(base) - base) * fx
        hi = (df["Result at high"].fillna(base) - base) * fx
        ax.barh(y, lo, color=p.bad, label=f"Driver −{self.to_swing.value():.0f}%")
        ax.barh(y, hi, color=p.teal, label=f"Driver +{self.to_swing.value():.0f}%")
        ax.set_yticks(y, df["Driver"], fontsize=7)
        ax.invert_yaxis()
        ax.axvline(0, color=p.text2, lw=0.8)
        if metric != "occupancy":
            ax.xaxis.set_major_formatter(money_formatter())
        self.to_chart.legend(ax, loc="lower right")
        self.to_chart.draw()
        st = self.state
        money = metric != "occupancy"
        fmt = (lambda v: st.money(v)) if money else (lambda v: f"{v * 100:.1f}%")
        self.to_table.set(df.drop(columns=["path"]), {"Low input": lambda v: f"{v:,.4g}",
                                                      "High input": lambda v: f"{v:,.4g}",
                                                      "Result at low": fmt, "Result at high": fmt, "Base": fmt,
                                                      "Range": fmt})

    # ---- break-even
    def _breakeven_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(button("Calculate break-even and operating leverage", self._run_be, primary=True))
        row.addStretch(1)
        lay.addLayout(row)
        self.be_lbl = label("", wrap=True)
        lay.addWidget(self.be_lbl)
        f, l = card()
        self.be_chart = Chart(2.8)
        l.addWidget(self.be_chart)
        lay.addWidget(f)
        lay.addStretch(1)
        self.tabs.addTab(w, "Break-even and leverage")

    def _run_be(self):
        st = self.state
        sl = self._sl()
        ol = se.operating_leverage(st.result, sl)
        be = run_with_progress(self, "Searching break-even…", lambda progress=None: se.break_even_demand(
            st.draft, sl))
        k = st.result.kpis(sl)
        txt = (f"Contribution {st.money(ol['contribution'])} ({(ol['contribution_margin'] or 0) * 100:.1f}% of "
               f"revenue) − fixed costs {st.money(ol['fixed_costs'])} = EBITDA {st.money(ol['ebitda'])}.<br>"
               f"Degree of operating leverage: <b>{'n/a' if ol['dol'] is None else f'{ol['dol']:.2f}×'}</b> – a 1% "
               f"change in revenue at constant mix moves EBITDA by about "
               f"{'n/a' if ol['dol'] is None else f'{ol['dol']:.1f}%'}.<br>"
               f"Break-even revenue (EBITDA = 0, constant margin): <b>{st.money(ol['break_even_revenue'])}</b>.<br>")
        if be["multiplier"] is not None:
            txt += (f"Engine-based break-even: EBITDA reaches zero when demand falls to "
                    f"<b>{be['multiplier'] * 100:.0f}%</b> of plan (occupancy ≈ {be['occupancy'] * 100:.1f}% vs "
                    f"{(k['occupancy'] or 0) * 100:.1f}% now). This includes all non-linear effects (capacity, mix, "
                    "incentive fees).")
        else:
            txt += be["note"]
        self.be_lbl.setText(txt)
        p = theme.current()
        ax = self.be_chart.new_axes()
        rev = np.linspace(0, ol["revenue"] * 1.4, 50) * st.fx()
        cm = ol["contribution_margin"] or 0
        ax.plot(rev, rev, color=p.blue, label="Revenue")
        ax.plot(rev, ol["fixed_costs"] * st.fx() + rev * (1 - cm), color=p.bad, label="Total costs")
        ax.axhline(ol["fixed_costs"] * st.fx(), color=p.amber, ls=":", label="Fixed costs")
        if ol["break_even_revenue"]:
            ax.axvline(ol["break_even_revenue"] * st.fx(), color=p.teal, ls="--", label="Break-even")
        ax.xaxis.set_major_formatter(money_formatter())
        ax.yaxis.set_major_formatter(money_formatter())
        ax.set_xlabel("Revenue (constant mix)")
        self.be_chart.legend(ax, loc="upper left")
        self.be_chart.draw()

    # ---- scenarios
    def _scenarios_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Saved scenarios compared on the same metrics. The shaded band is the range across "
                            "scenarios – a spread of chosen assumptions, not a confidence interval.", "Muted",
                            wrap=True))
        f, l = card()
        self.sc_chart = Chart(3.0)
        l.addWidget(self.sc_chart)
        lay.addWidget(f)
        self.sc_table = Table(min_height=200)
        lay.addWidget(self.sc_table)
        self.tabs.addTab(w, "Scenario comparison")

    def _refresh_scenarios(self):
        st = self.state
        sl = self._sl()
        res_list = [(s.name, simulate_cached(s.assumptions)) for s in st.store.list()]
        res_list.append(("Working draft", st.result))
        rows = []
        for name, r in res_list:
            k = r.kpis(sl)
            rows.append({"Scenario": name, "Occupancy": k["occupancy"], "ADR": k["adr"], "RevPAR": k["revpar"],
                         "Revenue": k["total_revenue"], "EBITDA": k["ebitda"], "EBITDA margin": k["ebitda_margin"],
                         "Net income": k["net_income"], "Min cash": float(r.s("cash")[sl].min())})
        self.sc_table.set(pd.DataFrame(rows), formatters(st, pct_cols=["Occupancy", "EBITDA margin"],
                                                         dec_money_cols=["ADR", "RevPAR"],
                                                         money_cols=["Revenue", "EBITDA", "Net income", "Min cash"]))
        p = theme.current()
        ax = self.sc_chart.new_axes()
        x = np.arange(st.result.months.size)
        arr = np.array([r.s("ebitda") for _n, r in res_list]) * st.fx()
        ax.fill_between(x, arr.min(axis=0), arr.max(axis=0), color=p.teal, alpha=0.15, label="Scenario range")
        for i, (n, r) in enumerate(res_list):
            ax.plot(x, r.s("ebitda") * st.fx(), lw=2 if n == "Working draft" else 1, label=n,
                    color=p.series[i % len(p.series)])
        tk, lb = month_axis_labels(st.result, 6)
        ax.set_xticks(tk, lb)
        ax.yaxis.set_major_formatter(money_formatter())
        ax.set_title("Monthly EBITDA by scenario")
        self.sc_chart.legend(ax, loc="upper left", ncol=3)
        self.sc_chart.draw()

    # ---- Monte Carlo
    def _mc_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Optional advanced analysis. Each iteration draws multiplicative shocks for the drivers "
                            "below and re-runs the engine for 12 months. Distributions, seed and iteration count are "
                            "shown and stored with the result.", "Muted", wrap=True))
        self.mc_dists = QTableWidget(len(se.DEFAULT_MC), 5)
        self.mc_dists.setHorizontalHeaderLabels(["Driver (multiplier on current value)", "Distribution", "p1", "p2",
                                                 "p3 (triangular high)"])
        self.mc_dists.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i, d in enumerate(se.DEFAULT_MC):
            lab = dict(PSEUDO).get(d.path) or SPEC_BY_PATH[d.path].label
            it = QTableWidgetItem(lab)
            it.setData(256, d.path)
            self.mc_dists.setItem(i, 0, it)
            self.mc_dists.setItem(i, 1, QTableWidgetItem(d.kind))
            for j, v in enumerate((d.p1, d.p2, d.p3), start=2):
                self.mc_dists.setItem(i, j, QTableWidgetItem(f"{v:g}"))
        self.mc_dists.setMaximumHeight(170)
        lay.addWidget(self.mc_dists)
        row = QHBoxLayout()
        self.mc_metric = _metric_combo()
        self.mc_iter = QSpinBox()
        self.mc_iter.setRange(20, 5000)
        self.mc_iter.setValue(300)
        self.mc_seed = QSpinBox()
        self.mc_seed.setRange(0, 2**31 - 1)
        self.mc_seed.setValue(42)
        for wdg, lab in ((self.mc_metric, "Metric"), (self.mc_iter, "Iterations"), (self.mc_seed, "Seed")):
            row.addWidget(label(lab + ":", "Muted"))
            row.addWidget(wdg)
        row.addWidget(button("Run simulation", self._run_mc, primary=True))
        row.addStretch(1)
        lay.addLayout(row)
        self.mc_lbl = label("", wrap=True)
        lay.addWidget(self.mc_lbl)
        f, l = card()
        self.mc_chart = Chart(2.8)
        l.addWidget(self.mc_chart)
        lay.addWidget(f)
        self.tabs.addTab(w, "Monte Carlo")

    def _run_mc(self):
        dists = []
        try:
            for i in range(self.mc_dists.rowCount()):
                path = self.mc_dists.item(i, 0).data(256)
                kind = self.mc_dists.item(i, 1).text().strip().lower()
                p1, p2, p3 = (float(self.mc_dists.item(i, j).text()) for j in (2, 3, 4))
                if kind not in ("normal", "triangular", "uniform"):
                    raise ValueError(f"Unknown distribution '{kind}'")
                if kind == "triangular" and not (p1 <= p2 <= p3):
                    raise ValueError("Triangular needs low ≤ mode ≤ high")
                if kind == "uniform" and p1 > p2:
                    raise ValueError("Uniform needs low ≤ high")
                if kind == "normal" and p2 < 0:
                    raise ValueError("Standard deviation must be ≥ 0")
                dists.append(se.Distribution(path, kind, p1, p2, p3))
        except ValueError as exc:
            error(self, "Distribution settings", str(exc))
            return
        metric = self.mc_metric.currentData()
        out = run_with_progress(self, "Running Monte Carlo…", se.monte_carlo, self.state.draft, dists, metric,
                                self.mc_iter.value(), self.mc_seed.value())
        if out["values"].size == 0:
            self.mc_lbl.setText("No valid iterations (all draws produced invalid inputs).")
            return
        st = self.state
        money = metric != "occupancy"
        f = (lambda v: st.money(v)) if money else (lambda v: f"{v * 100:.1f}%")
        self.mc_lbl.setText(
            f"{out['iterations']} iterations (seed {out['seed']}, {out['horizon_months']} months, "
            f"{out['skipped']} invalid draws skipped). Base {f(out['base'])} · mean {f(out['mean'])} · "
            f"P5 {f(out['p5'])} · P50 {f(out['p50'])} · P95 {f(out['p95'])}.<br>"
            f"Probability below base: {out['prob_below_base'] * 100:.0f}% · probability negative: "
            f"{out['prob_negative'] * 100:.1f}%.<br>Assumptions: " + "; ".join(out["assumptions"]) +
            "<br><i>The range reflects the stated distributions only; real outcomes can fall outside it.</i>")
        p = theme.current()
        ax = self.mc_chart.new_axes()
        vals = out["values"] * (st.fx() if money else 1)
        ax.hist(vals, bins=30, color=p.teal, alpha=0.75)
        for q, c in (("p5", p.bad), ("p50", p.text2), ("p95", p.good)):
            ax.axvline(out[q] * (st.fx() if money else 1), color=c, ls="--", lw=1, label=q.upper())
        ax.axvline(out["base"] * (st.fx() if money else 1), color=p.amber, lw=1.5, label="Base")
        if money:
            ax.xaxis.set_major_formatter(money_formatter())
        self.mc_chart.legend(ax)
        self.mc_chart.draw()

    # ---- forecast error
    def _error_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Forecast error and bias: the budget (forecast) compared with closed actual months. "
                            "Positive bias = over-forecasting.", "Muted", wrap=True))
        self.err_table = Table(min_height=240)
        lay.addWidget(self.err_table)
        lay.addStretch(1)
        self.tabs.addTab(w, "Forecast error")

    def _refresh_error(self):
        st = self.state
        d = build_fpa(st.store.get(st.db.get_setting("fpa_budget_scenario", "Base case")).assumptions, st.draft,
                      st.db.get_setting("fpa_as_of", 9))
        rows = []
        for k, lab in (("occupied_rooms", "Occupied rooms"), ("rooms_revenue", "Room revenue"),
                       ("total_revenue", "Total revenue"), ("total_dept_expenses", "Departmental expenses"),
                       ("ebitda", "EBITDA")):
            m = rm.forecast_accuracy(d.actual.s(k)[:d.as_of], d.budget.s(k)[:d.as_of])
            rows.append({"Measure": lab, "MAPE": m["MAPE"], "MAE": m["MAE"], "Bias (mean error)": m["Bias (mean error)"],
                         "Tracking signal": m["Tracking signal"], "Direction": m["Direction"]})
        self.err_table.set(pd.DataFrame(rows), {**formatters(st, pct_cols=["MAPE"]),
                                                "MAE": lambda v: f"{v:,.0f}", "Bias (mean error)": lambda v: f"{v:+,.0f}",
                                                "Tracking signal": lambda v: f"{v:+.2f}"})

    def _refresh_light(self):
        if self.isVisible():
            self.refresh()

    def refresh(self):
        self._refresh_scenarios()
        self._refresh_error()
