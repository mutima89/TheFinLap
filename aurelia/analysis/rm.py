"""Revenue Management analytics built on the authoritative engine.

* Channel/segment economics (gross vs net ADR, contribution per room night)
* Booking pace and pickup curves
* Group displacement analysis (with/without the block, through the engine)
* Rate recommendation search (engine-evaluated candidate rates)
* Minimum length-of-stay (MLOS) stay-pattern exercise
* Overbooking risk table
* Forecast accuracy metrics
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core.finance import safe_div
from ..model.assumptions import SEGMENTS, SEGMENT_LABELS
from ..model.engine import simulate, simulate_cached, SimulationResult, _norm_cdf, _norm_pdf

TRANSIENT = ["corporate", "leisure_direct", "leisure_ota"]


def variable_cost_per_occupied_room(a: dict, year_idx: int = 0) -> float:
    rc = a["rooms_costs"]
    infl = (1 + a["undistributed"]["cost_inflation_pct"]) ** year_idx
    u = a["undistributed"]
    energy = u["energy_kwh_per_occupied_room"] * u["energy_price_per_kwh"]
    return (rc["housekeeping_per_occupied_room"] + rc["guest_supplies_per_occupied_room"]
            + rc["laundry_per_occupied_room"]) * infl + energy * infl


def segment_economics(res: SimulationResult, sl: slice) -> pd.DataFrame:
    a = res.assumptions
    vc = variable_cost_per_occupied_room(a)
    rows = []
    total_rn = float(res.s("occupied_rooms")[sl].sum())
    for s in SEGMENTS:
        seg = res.segments[s]
        rn = float(seg["room_nights"][sl].sum())
        rev = float(seg["revenue"][sl].sum())
        com = float(seg["commission"][sl].sum())
        dem = float(seg["demand"][sl].sum())
        acc = float(seg["accepted"][sl].sum())
        cxl = float(seg["cancelled"][sl].sum())
        adr = safe_div(rev, rn)
        net = safe_div(rev - com, rn)
        rows.append({
            "Segment": SEGMENT_LABELS[s], "key": s, "Room nights": rn, "Mix %": safe_div(rn, total_rn),
            "Gross ADR": adr, "Commission %": safe_div(com, rev),
            "Net ADR": net, "Variable cost / RN": vc if rn else None,
            "Contribution / RN": (net - vc) if net is not None else None,
            "Room revenue": rev, "Net room revenue": rev - com,
            "Cancellation %": safe_div(cxl, acc), "Denied requests": max(dem - acc, 0.0),
        })
    return pd.DataFrame(rows)


def pace_curve(res: SimulationResult, month_idx: int, lead_points=(120, 90, 60, 45, 30, 21, 14, 7, 3, 0)) -> pd.DataFrame:
    """On-the-books room nights by days before arrival for a stay month.

    Booking windows are modelled as exponential with each segment's mean lead
    time, so the share of final room nights already booked d days out is
    exp(−d / mean lead). This is an explainable approximation, not a statistical fit.
    """
    a = res.assumptions
    rows = []
    for d in lead_points:
        row = {"Days before arrival": d}
        tot = 0.0
        for s in SEGMENTS:
            final = float(res.segments[s]["room_nights"][month_idx])
            L = max(float(a["segments"][s]["lead_days"]), 1e-9)
            otb = final * math.exp(-d / L)
            row[SEGMENT_LABELS[s]] = otb
            tot += otb
        row["Total on the books"] = tot
        rows.append(row)
    df = pd.DataFrame(rows)
    df["Pickup since prior point"] = df["Total on the books"].diff().fillna(df["Total on the books"])
    return df


@dataclass
class DisplacementResult:
    table: pd.DataFrame
    group_room_revenue: float
    group_fnb_revenue: float
    displaced_room_nights: float
    displaced_room_revenue: float
    delta_room_revenue: float
    delta_total_revenue: float
    delta_contribution: float
    delta_ebitda: float
    recommendation: str
    with_block: SimulationResult
    without_block: SimulationResult


def displacement_analysis(a: dict, start_date: str, nights: int, rooms: float, rate: float,
                          fnb_per_room_night: float = 0.0) -> DisplacementResult:
    """Evaluate a group request by running the engine with and without the contracted block."""
    base = simulate_cached(a)
    b = copy.deepcopy(a)
    b["rooms"].setdefault("group_blocks", []).append(
        {"start_date": start_date, "nights": int(nights), "rooms": float(rooms), "rate": float(rate),
         "fnb_per_room_night": float(fnb_per_room_night)})
    new = simulate(b)
    d0, d1 = base.daily, new.daily
    mask = (d1["date"] >= pd.Timestamp(start_date)) & (d1["date"] < pd.Timestamp(start_date) + pd.Timedelta(days=nights))
    rows = []
    for i in np.where(mask)[0]:
        trans0 = sum(d0.at[i, f"{s}_rooms"] for s in SEGMENTS) - d0.at[i, "group_block"]
        trans1 = sum(d1.at[i, f"{s}_rooms"] for s in SEGMENTS) - d1.at[i, "group_block"]
        rev0 = sum(d0.at[i, f"{s}_revenue"] for s in SEGMENTS)
        rev1 = sum(d1.at[i, f"{s}_revenue"] for s in SEGMENTS)
        com0 = sum(d0.at[i, f"{s}_commission"] for s in SEGMENTS)
        com1 = sum(d1.at[i, f"{s}_commission"] for s in SEGMENTS)
        rows.append({"Date": d1.at[i, "date"].strftime("%a %d %b %Y"), "Available": d1.at[i, "available"],
                     "Other business without block": trans0, "Other business with block": trans1,
                     "Group block rooms": d1.at[i, "group_block"],
                     "Displaced room nights": max(trans0 - trans1, 0.0),
                     "Net room revenue without": rev0 - com0, "Net room revenue with": rev1 - com1})
    tab = pd.DataFrame(rows)
    disp = float(tab["Displaced room nights"].sum()) if len(tab) else 0.0
    t = lambda r, k: float(r.s(k).sum())  # noqa: E731
    group_rev = float(d1.loc[mask, "group_block"].sum()) * rate
    displaced_rev = sum(float((d0.loc[mask, f"{s}_revenue"] - d1.loc[mask, f"{s}_revenue"]).sum())
                        for s in SEGMENTS) + group_rev
    d_ebitda = t(new, "ebitda") - t(base, "ebitda")
    d_contrib = t(new, "total_dept_profit") - t(base, "total_dept_profit")
    if d_ebitda > 0 and disp > 0:
        rec = ("Accept: after displacing higher-rated business the block still adds EBITDA. Check whether the "
               "rate can be raised on the most displacing nights.")
    elif d_ebitda > 0:
        rec = "Accept: the block mostly fills rooms that would otherwise be empty."
    else:
        rec = ("Decline or counter-offer: the block displaces more contribution than it brings. Offer alternative "
               "(lower-demand) dates or a higher rate.")
    return DisplacementResult(tab, group_rev, float(fnb_per_room_night * d1.loc[mask, "group_block"].sum()), disp,
                              displaced_rev, t(new, "rooms_revenue") - t(base, "rooms_revenue"),
                              t(new, "total_revenue") - t(base, "total_revenue"), d_contrib, d_ebitda, rec, new, base)


def rate_candidates_evaluation(a: dict, segment: str, multipliers=(0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2),
                               year: int = 1, progress=None) -> pd.DataFrame:
    """Re-run the engine for alternative published rates of one segment and rank by EBITDA."""
    rows = []
    base_rate = a["segments"][segment]["published_rate"]
    for i, m in enumerate(multipliers):
        b = copy.deepcopy(a)
        b["segments"][segment]["published_rate"] = round(base_rate * m, 2)
        r = simulate_cached(b)
        sl = r.year_slice(year)
        k = r.kpis(sl)
        seg = r.segments[segment]
        rows.append({"Rate change": m - 1, "Published rate": base_rate * m,
                     "Segment room nights": float(seg["room_nights"][sl].sum()),
                     "Segment net revenue": float((seg["revenue"][sl] - seg["commission"][sl]).sum()),
                     "Occupancy": k["occupancy"], "ADR": k["adr"], "RevPAR": k["revpar"],
                     "Total revenue": k["total_revenue"], "EBITDA": k["ebitda"]})
        if progress:
            progress(i + 1, len(multipliers))
    df = pd.DataFrame(rows)
    best = df["EBITDA"].idxmax()
    df["Recommended"] = ["★" if i == best else "" for i in range(len(df))]
    return df


def mlos_exercise(capacity: int = 150, peak_night: int = 3, mlos: int = 1, conversion_pct: float = 0.4,
                  arrivals=(70, 75, 80, 110, 60, 55, 50), los_mix=(0.45, 0.30, 0.15, 0.10),
                  rate=(1100, 1100, 1150, 1600, 1150, 1050, 1000)) -> pd.DataFrame:
    """Stay-pattern model for a 7-night window.

    Arrival requests on each night have a length-of-stay mix (1–4 nights).
    Requests are accepted first-come by arrival night if every night of the stay
    has a free room. With an MLOS restriction of ``mlos`` nights, requests whose
    stay includes ``peak_night`` but are shorter than ``mlos`` are refused;
    ``conversion_pct`` of them extend to the minimum stay instead.
    """
    n = len(arrivals)
    occ = np.zeros(n + 4)
    rev = 0.0
    refused = 0.0
    for d in range(n):
        for li, p in enumerate(los_mix):
            los = li + 1
            req = arrivals[d] * p
            covers_peak = d <= peak_night < d + los
            if mlos > 1 and covers_peak and los < mlos:
                converted = req * conversion_pct
                refused += req - converted
                req, los = converted, mlos
            free = min(capacity - occ[d + k] for k in range(los))
            take = max(0.0, min(req, free))
            refused += req - take
            for k in range(los):
                occ[d + k] += take
                rev += take * rate[min(d + k, n - 1)]
    rows = [{"Night": f"Night {i + 1}" + (" (peak)" if i == peak_night else ""), "Occupied": occ[i],
             "Occupancy": occ[i] / capacity} for i in range(n)]
    df = pd.DataFrame(rows)
    df.attrs["revenue"] = rev
    df.attrs["room_nights"] = float(occ[:n].sum() + occ[n:].sum())
    df.attrs["refused"] = refused
    return df


def overbooking_table(capacity: float, bookings_show_prob: float, rate: float, walk_cost: float,
                      levels=range(0, 16)) -> pd.DataFrame:
    """Expected revenue minus expected walk cost for different overbooking levels on a sold-out night."""
    rows = []
    for extra in levels:
        n = capacity + extra
        mu = n * bookings_show_prob
        sigma = math.sqrt(max(n * bookings_show_prob * (1 - bookings_show_prob), 1e-9))
        z = (mu - capacity) / sigma
        walks = float((mu - capacity) * _norm_cdf(np.array([z]))[0] + sigma * _norm_pdf(np.array([z]))[0]) \
            if extra > 0 or mu > capacity else 0.0
        if extra == 0:
            walks = 0.0
        occupied = mu - walks
        p_walk = float(1 - _norm_cdf(np.array([(capacity + 0.5 - mu) / sigma]))[0]) if extra > 0 else 0.0
        rows.append({"Overbooked rooms": extra, "Expected arrivals": mu, "Expected walks": walks,
                     "P(at least one walk)": p_walk, "Expected occupied": occupied,
                     "Expected net value": occupied * rate - walks * walk_cost})
    df = pd.DataFrame(rows)
    best = df["Expected net value"].idxmax()
    df["Best"] = ["★" if i == best else "" for i in range(len(df))]
    return df


def forecast_accuracy(actual: np.ndarray, forecast: np.ndarray) -> dict:
    """MAPE, MAE, bias and tracking signal. Months with zero actuals are excluded from MAPE."""
    actual = np.asarray(actual, float)
    forecast = np.asarray(forecast, float)
    err = forecast - actual
    nz = actual != 0
    mape = float(np.mean(np.abs(err[nz] / actual[nz]))) if nz.any() else None
    mae = float(np.mean(np.abs(err))) if err.size else None
    bias = float(np.mean(err)) if err.size else None
    ts = safe_div(float(err.sum()), mae) if mae else None
    return {"MAPE": mape, "MAE": mae, "Bias (mean error)": bias, "Tracking signal": ts,
            "Direction": None if bias is None else ("over-forecast" if bias > 0 else "under-forecast"
                                                     if bias < 0 else "unbiased")}
