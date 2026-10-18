"""Helpers shared by pages: period selection, impact tables, formula popups."""
from __future__ import annotations

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox, QWidget

from ..core.kpis import KPI_DEFINITIONS
from ..model.assumptions import DriverSpec, get_path
from ..model.engine import G, SimulationResult


def period_combo(n_months: int = 36, start_year: int = 2027) -> QComboBox:
    cb = QComboBox()
    years = (n_months + 11) // 12
    for y in range(years):
        cb.addItem(f"FY{start_year + y} (model year {y + 1})", ("year", y + 1))
    cb.addItem(f"All {n_months} months", ("all", None))
    cb.setToolTip("Period used for totals and KPIs on this page.")
    return cb


def period_slice(res: SimulationResult, data) -> slice:
    kind, val = data if data else ("year", 1)
    if kind == "year":
        return res.year_slice(val)
    return slice(None)


IMPACT_ROWS = [
    ("occupancy", "Occupancy", "pct"),
    ("adr", "ADR (gross)", "currency_d"),
    ("revpar", "RevPAR", "currency_d"),
    ("net_adr", "Net ADR (after commissions)", "currency_d"),
    ("rooms_revenue", "Room revenue", "currency"),
    ("total_revenue", "Total operating revenue", "currency"),
    ("contribution", "Departmental contribution", "currency"),
    ("gop", "Gross operating profit", "currency"),
    ("ebitda", "EBITDA", "currency"),
    ("ebitda_margin", "EBITDA margin", "pct"),
    ("net_income", "Net income", "currency"),
    ("cfo", "Operating cash flow", "currency"),
    ("closing_cash", "Closing cash", "currency"),
]


def impact_frame(state, base: SimulationResult, new: SimulationResult, sl: slice) -> pd.DataFrame:
    kb, kn = base.kpis(sl), new.kpis(sl)
    kb["cfo"], kn["cfo"] = base.total("cfo", sl), new.total("cfo", sl)
    rows = []
    for key, name, unit in IMPACT_ROWS:
        b, n = kb.get(key), kn.get(key)
        u = "currency" if unit.startswith("currency") else unit
        dec = 0 if unit == "currency_d" else None
        if b is None or n is None:
            delta, dpct = "n/a", "n/a"
        else:
            d = n - b
            if u == "pct":
                delta = f"{d * 100:+.1f} pts"
            else:
                delta = ("+" if d >= 0 else "−") + state.fmt(abs(d), u, dec)
            dpct = f"{(d / abs(b)) * 100:+.1f}%" if b not in (0, None) and u != "pct" else ""
        rows.append({"Metric": name, "Comparison": state.fmt(b, u, dec), "Working scenario": state.fmt(n, u, dec),
                     "Change": delta, "Change %": dpct, "_d": (n - b) if (b is not None and n is not None) else 0.0,
                     "_key": key})
    return pd.DataFrame(rows)


def kpi_formula_html(key: str) -> str:
    k = KPI_DEFINITIONS.get(key)
    if k is None:
        li = G.items.get(key)
        if li is None:
            return f"<p>No definition for {key}.</p>"
        return line_item_html(key)
    return (f"<h3>{k.name}</h3><p><b>Formula:</b> {k.formula}</p><p>{k.description}</p>"
            f"<p><b>Interpretation:</b> {'Higher is usually better.' if k.nature == 'higher_better' else ''}"
            f"{'Lower is usually better.' if k.nature == 'lower_better' else ''}"
            f"{'Neither higher nor lower is automatically better – read with rate, cost and mix.' if k.nature == 'context' else ''}"
            f"</p>")


def line_item_html(key: str, res: SimulationResult | None = None, state=None) -> str:
    li = G.items[key]
    up = G.upstream(key)
    down = G.downstream(key)
    html = f"<h3>{li.label}</h3><p><b>Formula:</b> {li.formula}</p>"
    html += f"<p><b>Calculated in node:</b> <code>{li.node}</code> – {G.nodes[li.node].description}</p>"
    if li.inputs:
        html += "<p><b>Assumption inputs:</b> " + ", ".join(f"<code>{i}</code>" for i in li.inputs) + "</p>"
    if up:
        html += "<p><b>Depends on line items:</b> " + ", ".join(G.items[u].label for u in up) + "</p>"
    if down:
        html += "<p><b>Feeds into:</b> " + ", ".join(sorted({G.items[d].label for d in down})) + "</p>"
    if res is not None and state is not None and key in res.series:
        y = res.year_slice(1)
        html += f"<p><b>Model year 1 total:</b> {state.fmt(float(res.series[key][y].sum()), li.unit if li.unit in ('currency','pct') else 'number')}</p>"
    return html


def spin_for(spec: DriverSpec, value, parent: QWidget | None = None):
    """Create an input box for a driver; percentages are edited as 0–100."""
    if spec.unit == "int":
        w = QSpinBox(parent)
        w.setRange(int(spec.minimum), int(min(spec.maximum, 2**31 - 1)))
        w.setSingleStep(int(spec.step) or 1)
        w.setValue(int(value))
    else:
        w = QDoubleSpinBox(parent)
        if spec.unit == "pct":
            w.setDecimals(2)
            w.setRange(spec.minimum * 100, spec.maximum * 100)
            w.setSingleStep(spec.step * 100)
            w.setSuffix(" %")
            w.setValue(float(value) * 100)
        else:
            dec = 2 if spec.step < 1 else 0
            w.setDecimals(dec)
            w.setRange(spec.minimum, spec.maximum)
            w.setSingleStep(spec.step)
            w.setValue(float(value) if value is not None else 0.0)
            if spec.unit == "currency":
                w.setPrefix("SAR ")
            w.setGroupSeparatorShown(True)
    w.setToolTip(f"{spec.label}\n{spec.help}\nValid range: {spec.minimum:g} – {spec.maximum:g}"
                 + (" (as a fraction; shown here ×100)" if spec.unit == "pct" else ""))
    w.setAccessibleName(spec.label)
    w.setKeyboardTracking(False)
    return w


def spin_value(spec: DriverSpec, w) -> float:
    v = w.value()
    return v / 100.0 if spec.unit == "pct" else v


def month_axis_labels(res: SimulationResult, step: int = 3) -> tuple[np.ndarray, list[str]]:
    idx = np.arange(res.months.size)
    labels = [p.strftime("%b %y") for p in res.months]
    return idx[::step], labels[::step]


def driver_value(state, path: str):
    return get_path(state.draft, path)


def formatters(state, money_cols=(), pct_cols=(), num_cols=(), dec_money_cols=(), int_cols=()):
    """Build a column→formatter dict for Table.set()."""
    f = {}
    for c in money_cols:
        f[c] = lambda v: state.money(v) if v is not None and v == v else "n/a"
    for c in dec_money_cols:
        f[c] = lambda v: state.money(v, 0) if v is not None and v == v else "n/a"
    for c in pct_cols:
        f[c] = lambda v: "n/a" if v is None or v != v else f"{v * 100:.1f}%"
    for c in num_cols:
        f[c] = lambda v: "n/a" if v is None or v != v else f"{v:,.1f}"
    for c in int_cols:
        f[c] = lambda v: "n/a" if v is None or v != v else f"{v:,.0f}"
    return f


def run_with_progress(parent, title: str, fn, *args, **kwargs):
    """Run a long calculation with a modal progress dialog (cancellable where supported)."""
    from PySide6.QtWidgets import QProgressDialog, QApplication
    from PySide6.QtCore import Qt
    dlg = QProgressDialog(title, "Cancel", 0, 100, parent)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(200)
    dlg.setValue(0)

    def progress(i, n):
        dlg.setValue(int(i / max(n, 1) * 100))
        QApplication.processEvents()

    kwargs.setdefault("progress", progress)
    if "cancelled" in fn.__code__.co_varnames:
        kwargs.setdefault("cancelled", dlg.wasCanceled)
    try:
        return fn(*args, **kwargs)
    finally:
        dlg.setValue(100)
        dlg.close()


def fpa_data(state):
    """FP&A data with the user's saved budget scenario, close month and materiality settings."""
    from ..analysis.fpa import build_fpa, Materiality
    name = state.db.get_setting("fpa_budget_scenario", "Base case")
    if name not in state.store.names():
        name = "Base case"
    m = Materiality(state.db.get_setting("materiality_abs", 250_000.0), state.db.get_setting("materiality_pct", 0.05))
    return build_fpa(state.store.get(name).assumptions, state.draft, state.db.get_setting("fpa_as_of", 9), m), name
