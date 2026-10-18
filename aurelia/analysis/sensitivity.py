"""Sensitivity, break-even, operating leverage and Monte Carlo analysis.

All evaluations re-run the authoritative engine; nothing is approximated with a
separate shortcut model. Monte Carlo exposes its distributions, random seed and
iteration count, and its output is a range of *scenario outcomes under stated
assumptions* – not a prediction.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ..core.finance import safe_div
from ..model.assumptions import get_path, set_path, SPEC_BY_PATH, validate, coerce_value, SEGMENTS
from ..model.engine import simulate_cached, simulate, SimulationResult

METRICS: dict[str, tuple[str, Callable[[SimulationResult, slice], float]]] = {
    "ebitda": ("EBITDA", lambda r, sl: r.total("ebitda", sl)),
    "total_revenue": ("Total revenue", lambda r, sl: r.total("total_revenue", sl)),
    "gop": ("GOP", lambda r, sl: r.total("gop", sl)),
    "net_income": ("Net income", lambda r, sl: r.total("net_income", sl)),
    "revpar": ("RevPAR", lambda r, sl: r.kpis(sl)["revpar"] or 0.0),
    "occupancy": ("Occupancy", lambda r, sl: r.kpis(sl)["occupancy"] or 0.0),
    "closing_cash": ("Closing cash", lambda r, sl: float(r.s("cash")[sl][-1])),
    "cfo": ("Operating cash flow", lambda r, sl: r.total("cfo", sl)),
}


def _apply(a: dict, path: str, value) -> dict:
    b = copy.deepcopy(a)
    if path == "segments.*.base_demand_mult":
        for s in SEGMENTS:
            b["segments"][s]["base_demand"] *= float(value)
        return b
    if path == "segments.*.rate_mult":
        for s in SEGMENTS:
            b["segments"][s]["published_rate"] *= float(value)
        return b
    set_path(b, path, coerce_value(path, value))
    return b


def one_way(a: dict, path: str, values, metric: str, sl: slice, progress=None) -> pd.DataFrame:
    rows = []
    fn = METRICS[metric][1]
    for i, v in enumerate(values):
        b = _apply(a, path, v)
        probs = validate(b)
        if probs:
            rows.append({"Input value": v, "Result": None, "Note": probs[0]})
        else:
            rows.append({"Input value": v, "Result": fn(simulate_cached(b), sl), "Note": ""})
        if progress:
            progress(i + 1, len(values))
    return pd.DataFrame(rows)


def two_way(a: dict, path_x: str, xs, path_y: str, ys, metric: str, sl: slice, progress=None) -> pd.DataFrame:
    fn = METRICS[metric][1]
    grid = np.full((len(ys), len(xs)), np.nan)
    n, k = len(xs) * len(ys), 0
    for i, y in enumerate(ys):
        for j, x in enumerate(xs):
            b = _apply(_apply(a, path_x, x), path_y, y)
            if not validate(b):
                grid[i, j] = fn(simulate_cached(b), sl)
            k += 1
            if progress:
                progress(k, n)
    return pd.DataFrame(grid, index=list(ys), columns=list(xs))


def tornado(a: dict, paths: list[str], metric: str, sl: slice, swing: float = 0.10, progress=None) -> pd.DataFrame:
    """Low/high results for ±swing (relative) on each driver, sorted by range."""
    fn = METRICS[metric][1]
    base = fn(simulate_cached(a), sl)
    rows = []
    for i, p in enumerate(paths):
        v = get_path(a, p)
        lo_v, hi_v = v * (1 - swing), v * (1 + swing)
        res = []
        for vv in (lo_v, hi_v):
            b = _apply(a, p, vv)
            res.append(None if validate(b) else fn(simulate_cached(b), sl))
        spec = SPEC_BY_PATH.get(p)
        rows.append({"Driver": spec.label if spec else p, "path": p, "Low input": lo_v, "High input": hi_v,
                     "Result at low": res[0], "Result at high": res[1], "Base": base,
                     "Range": abs((res[1] or base) - (res[0] or base))})
        if progress:
            progress(i + 1, len(paths))
    return pd.DataFrame(rows).sort_values("Range", ascending=False).reset_index(drop=True)


def break_even_demand(a: dict, sl: slice, metric: str = "ebitda", target: float = 0.0) -> dict:
    """Uniform demand multiplier at which the metric hits the target (bisection through the engine)."""
    fn = METRICS[metric][1]

    def f(mult):
        return fn(simulate_cached(_apply(a, "segments.*.base_demand_mult", round(mult, 6))), sl) - target

    lo, hi = 0.05, 3.0
    flo, fhi = f(lo), f(hi)
    if flo > 0:
        return {"multiplier": None, "note": "Target is met even with 5% of current demand."}
    if fhi < 0:
        return {"multiplier": None, "note": "Target not reachable even at 3× demand (capacity bound)."}
    for _ in range(40):
        mid = (lo + hi) / 2
        if f(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-4:
            break
    m = (lo + hi) / 2
    r = simulate_cached(_apply(a, "segments.*.base_demand_mult", round(m, 6)))
    return {"multiplier": m, "occupancy": r.kpis(sl)["occupancy"], "note": ""}


def operating_leverage(res: SimulationResult, sl: slice) -> dict:
    """Contribution, fixed costs and degree of operating leverage (contribution ÷ EBITDA).

    Contribution here = revenue − costs that vary with activity (commissions, rooms variable,
    F&B and spa direct costs, events direct costs, variable F&B labour, card fees, variable
    energy, % of revenue fees). Everything else is treated as fixed in the period.
    """
    t = lambda k: res.total(k, sl)  # noqa: E731
    a = res.assumptions
    u = a["undistributed"]
    var_energy = float((res.s("occupied_rooms")[sl] * u["energy_kwh_per_occupied_room"]
                        * u["energy_price_per_kwh"]).sum())
    variable = (t("commissions") + t("rooms_variable_costs") + t("walk_costs") + t("fnb_cogs") + t("fnb_other_exp")
                + (t("fnb_labour") - t("payroll_fnb")) + t("spa_costs") + t("events_costs") + t("other_costs")
                + t("card_fees") + var_energy + t("total_revenue") * (u["ag_pct_revenue"] + u["pom_pct_revenue"]
                                                                       + a["fees_fixed"]["base_mgmt_fee_pct"]))
    contribution = t("total_revenue") - variable
    ebitda = t("ebitda")
    fixed = contribution - ebitda
    return {"revenue": t("total_revenue"), "variable_costs": variable, "contribution": contribution,
            "contribution_margin": safe_div(contribution, t("total_revenue")), "fixed_costs": fixed,
            "ebitda": ebitda, "dol": safe_div(contribution, ebitda),
            "break_even_revenue": safe_div(fixed, safe_div(contribution, t("total_revenue")))}


@dataclass
class Distribution:
    path: str
    kind: str  # normal | triangular | uniform
    p1: float  # normal: mean multiplier, triangular: low, uniform: low
    p2: float  # normal: sd multiplier, triangular: mode, uniform: high
    p3: float = 0.0  # triangular: high

    def sample(self, rng: np.random.Generator, n: int) -> np.ndarray:
        if self.kind == "normal":
            return rng.normal(self.p1, self.p2, n)
        if self.kind == "triangular":
            return rng.triangular(self.p1, self.p2, self.p3, n)
        if self.kind == "uniform":
            return rng.uniform(self.p1, self.p2, n)
        raise ValueError(self.kind)

    def describe(self) -> str:
        spec = SPEC_BY_PATH.get(self.path)
        name = spec.label if spec else self.path
        if self.kind == "normal":
            return f"{name}: × Normal(mean {self.p1:g}, sd {self.p2:g})"
        if self.kind == "triangular":
            return f"{name}: × Triangular(low {self.p1:g}, mode {self.p2:g}, high {self.p3:g})"
        return f"{name}: × Uniform({self.p1:g}, {self.p2:g})"


DEFAULT_MC = [
    Distribution("segments.*.base_demand_mult", "normal", 1.0, 0.08),
    Distribution("segments.*.rate_mult", "triangular", 0.94, 1.0, 1.04),
    Distribution("payroll.overtime_pct", "triangular", 0.8, 1.0, 1.6),
    Distribution("undistributed.energy_price_per_kwh", "uniform", 0.95, 1.20),
]


def monte_carlo(a: dict, dists: list[Distribution], metric: str = "ebitda", iterations: int = 200, seed: int = 42,
                horizon_months: int = 12, progress=None, cancelled=lambda: False) -> dict:
    """Run the engine ``iterations`` times with multiplicative shocks drawn from ``dists``.

    The model horizon is shortened to ``horizon_months`` for speed; results refer to
    that period. Uses its own seeded generator so the run is reproducible.
    """
    rng = np.random.default_rng(int(seed))
    base_a = copy.deepcopy(a)
    base_a["meta"]["months"] = horizon_months
    draws = {i: d.sample(rng, iterations) for i, d in enumerate(dists)}
    fn = METRICS[metric][1]
    out = []
    skipped = 0
    for it in range(iterations):
        if cancelled():
            break
        b = copy.deepcopy(base_a)
        for i, d in enumerate(dists):
            m = float(draws[i][it])
            if d.path.startswith("segments.*"):
                b = _apply(b, d.path, max(m, 0.0))
            else:
                v = get_path(b, d.path)
                set_path(b, d.path, coerce_value(d.path, v * max(m, 0.0)))
        if validate(b):
            skipped += 1
            continue
        out.append(fn(simulate(b, validate=False), slice(None)))
        if progress:
            progress(it + 1, iterations)
    vals = np.array(out)
    base_val = fn(simulate_cached(base_a), slice(None))
    if vals.size == 0:
        return {"values": vals, "base": base_val, "skipped": skipped}
    return {"values": vals, "base": base_val, "skipped": skipped, "mean": float(vals.mean()),
            "p5": float(np.percentile(vals, 5)), "p50": float(np.percentile(vals, 50)),
            "p95": float(np.percentile(vals, 95)), "prob_below_base": float((vals < base_val).mean()),
            "prob_negative": float((vals < 0).mean()), "seed": seed, "iterations": int(vals.size),
            "assumptions": [d.describe() for d in dists], "horizon_months": horizon_months}
