"""Integrated capstone: a messy but recoverable dataset and ten scored steps.

Data: model year 2 (2028) of the fictional 'actual world' (see fpa.actual_world_assumptions),
exported by month and segment, with deliberate, documented defects:

  * 3 exact duplicate rows
  * inconsistent segment labels ("Corp.", " corporate ", "OTA")
  * numbers stored as text with thousands separators
  * a missing room-revenue value (recoverable from the hotel control totals)
  * a room-nights typo (9,999) that exceeds capacity (recoverable from control totals)
  * a negative room-nights entry (sign error)
  * one revenue entry keyed in thousands (scale error)

The hotel-level control file is clean, so every defect can be recovered and the
cleaned data reconciles exactly. Truth values for every step come from the engine.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.kpis import safe_div
from ..model.assumptions import SEGMENTS, SEGMENT_LABELS, baseline
from ..model.engine import simulate_cached
from . import investment as inv
from .fpa import actual_world_assumptions
from .sensitivity import _apply

YEAR_SLICE = slice(12, 24)
LABELS = {v: k for k, v in SEGMENT_LABELS.items()}
ALIASES = {"corp.": "corporate", "corporate": "corporate", "ota": "leisure_ota", "leisure ota": "leisure_ota",
           "leisure – ota": "leisure_ota", "leisure – direct": "leisure_direct", "group": "group",
           "wholesale": "wholesale", "corporate (negotiated)": "corporate"}

RULES = {
    "dedupe": ("Remove exact duplicate rows", True),
    "labels": ("Normalise segment labels to the standard list", True),
    "text_numbers": ("Convert numbers stored as text (remove thousands separators)", True),
    "sign": ("Fix sign errors (negative room nights)", True),
    "recover": ("Recover missing or impossible values from the hotel control totals", True),
    "scale": ("Rescale entries keyed in thousands (implausible ADR)", True),
    "drop_any": ("Delete every row that has any issue", False),
    "impute_mean": ("Replace odd values with the segment average", False),
}
STEP_TITLES = ["1. Validate the data", "2. Build the KPIs", "3. Reconcile actual vs budget",
               "4. Forecast next quarter", "5. Integrated financial analysis", "6. Evaluate two decisions",
               "7. Quantify risk and sensitivity", "8. Design the management dashboard",
               "9. Write the executive recommendation", "10. Defend it in the meeting"]


# --------------------------------------------------------------------------- data
@lru_cache(maxsize=1)
def worlds():
    return simulate_cached(actual_world_assumptions()), simulate_cached(baseline())


def clean_truth() -> pd.DataFrame:
    a, _b = worlds()
    rows = []
    for m in range(12, 24):
        for s in SEGMENTS:
            rows.append({"month": str(a.months[m]), "segment": SEGMENT_LABELS[s],
                         "room_nights": round(float(a.segments[s]["room_nights"][m])),
                         "room_revenue": round(float(a.segments[s]["revenue"][m]), 2),
                         "commissions": round(float(a.segments[s]["commission"][m]), 2)})
    return pd.DataFrame(rows)


def hotel_controls() -> pd.DataFrame:
    a, _b = worlds()
    truth = clean_truth()
    g = truth.groupby("month", sort=False)
    out = pd.DataFrame({"month": [str(a.months[m]) for m in range(12, 24)],
                        "available_rooms": [round(float(a.s("available_rooms")[m])) for m in range(12, 24)]})
    out["occupied_rooms"] = g["room_nights"].sum().to_numpy()
    out["room_revenue"] = g["room_revenue"].sum().round(2).to_numpy()
    for k in ("total_revenue", "gop", "ebitda", "cfo"):
        out[k] = [round(float(a.s(k)[m]), 2) for m in range(12, 24)]
    out["closing_cash"] = [round(float(a.s("cash")[m]), 2) for m in range(12, 24)]
    return out


def budget_file() -> pd.DataFrame:
    _a, b = worlds()
    rows = []
    for m in range(12, 24):
        for s in SEGMENTS:
            rows.append({"month": str(b.months[m]), "segment": SEGMENT_LABELS[s],
                         "budget_room_nights": round(float(b.segments[s]["room_nights"][m])),
                         "budget_room_revenue": round(float(b.segments[s]["revenue"][m]), 2)})
    return pd.DataFrame(rows)


def messy_rooms() -> pd.DataFrame:
    df = clean_truth().astype(object)
    def idx(month, seg):
        return df.index[(df["month"] == month) & (df["segment"] == SEGMENT_LABELS[seg])][0]
    df.at[idx("2028-01", "corporate"), "segment"] = "Corp."
    df.at[idx("2028-06", "corporate"), "segment"] = " corporate "
    df.at[idx("2028-09", "leisure_ota"), "segment"] = "OTA"
    i = idx("2028-04", "leisure_direct")
    df.at[i, "room_revenue"] = f"{float(df.at[i, 'room_revenue']):,.2f}"
    i = idx("2028-11", "corporate")
    df.at[i, "room_nights"] = f"{int(df.at[i, 'room_nights']):,}"
    df.at[idx("2028-05", "wholesale"), "room_revenue"] = np.nan
    df.at[idx("2028-02", "group"), "room_nights"] = 9999
    i = idx("2028-07", "wholesale")
    df.at[i, "room_nights"] = -int(df.at[i, "room_nights"])
    i = idx("2028-08", "leisure_direct")
    df.at[i, "room_revenue"] = round(float(df.at[i, "room_revenue"]) / 1000, 3)
    dups = [df.loc[idx("2028-03", "group")], df.loc[idx("2028-07", "corporate")], df.loc[idx("2028-10", "leisure_ota")]]
    df = pd.concat([df, pd.DataFrame(dups)], ignore_index=True)
    order = df["month"].astype(str) + df.index.astype(str).str.zfill(3)
    return df.loc[order.sort_values().index].reset_index(drop=True)


DUPLICATES = 3
ISSUES = {"duplicates": 3, "labels": 3, "text_numbers": 2, "missing": 1, "impossible": 1, "sign": 1, "scale": 1}


def _num(v):
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").strip())
        except ValueError:
            return np.nan
    return float(v) if v is not None else np.nan


def apply_rules(raw: pd.DataFrame, rules: set[str], controls: pd.DataFrame | None = None) -> pd.DataFrame:
    """Apply the selected cleaning rules in a fixed, documented order."""
    df = raw.copy()
    controls = hotel_controls() if controls is None else controls
    if "drop_any" in rules:
        bad = df.duplicated(keep="first")
        for c in ("room_nights", "room_revenue"):
            bad |= df[c].apply(lambda v: isinstance(v, str) or v is None or (isinstance(v, float) and np.isnan(v)))
        bad |= ~df["segment"].isin(LABELS.keys())
        df = df[~bad].copy()
    if "dedupe" in rules:
        df = df.drop_duplicates(keep="first")
    if "labels" in rules:
        df["segment"] = [SEGMENT_LABELS.get(ALIASES.get(str(s).strip().lower(), ""), s) for s in df["segment"]]
    if "text_numbers" in rules:
        for c in ("room_nights", "room_revenue", "commissions"):
            df[c] = df[c].apply(_num)
    else:
        for c in ("room_nights", "room_revenue", "commissions"):
            df[c] = df[c].apply(lambda v: np.nan if isinstance(v, str) else v).astype(float)
    if "sign" in rules:
        df["room_nights"] = df["room_nights"].abs()
    if "scale" in rules:
        adr = df["room_revenue"] / df["room_nights"].replace(0, np.nan)
        mask = adr < 50
        df.loc[mask, "room_revenue"] = df.loc[mask, "room_revenue"] * 1000
    if "impute_mean" in rules:
        for c in ("room_nights", "room_revenue"):
            mean = df.groupby("segment")[c].transform("mean")
            df[c] = df[c].fillna(mean)
    if "recover" in rules:
        ctl = controls.set_index("month")
        for mth, g in df.groupby("month"):
            avail = ctl.at[mth, "available_rooms"]
            idx_bad = g.index[g["room_nights"] > avail]
            if len(idx_bad) == 1:
                others = g["room_nights"].drop(idx_bad).sum()
                df.at[idx_bad[0], "room_nights"] = ctl.at[mth, "occupied_rooms"] - others
            miss = g.index[g["room_revenue"].isna()]
            if len(miss) == 1:
                g2 = df.loc[g.index]
                df.at[miss[0], "room_revenue"] = round(ctl.at[mth, "room_revenue"] - g2["room_revenue"].drop(
                    miss).sum(), 2)
    return df.reset_index(drop=True)


def correct_rules() -> set[str]:
    return {k for k, (_l, ok) in RULES.items() if ok}


def kpis_from(df: pd.DataFrame, controls: pd.DataFrame | None = None) -> dict:
    controls = hotel_controls() if controls is None else controls
    rn = float(df["room_nights"].sum())
    rev = float(df["room_revenue"].sum())
    com = float(df["commissions"].sum())
    avail = float(controls["available_rooms"].sum())
    return {"occupancy": safe_div(rn, avail), "adr": safe_div(rev, rn), "revpar": safe_div(rev, avail),
            "net_adr": safe_div(rev - com, rn), "room_revenue": rev, "room_nights": rn}


# --------------------------------------------------------------------------- expected answers
@lru_cache(maxsize=1)
def expected() -> dict:
    a, b = worlds()
    truth = clean_truth()
    k = kpis_from(truth)
    bud = budget_file()
    brn, brev = float(bud["budget_room_nights"].sum()), float(bud["budget_room_revenue"].sum())
    badr = brev / brn
    rate_var = (k["adr"] - badr) * k["room_nights"]
    vol_var = (k["room_nights"] - brn) * badr
    fc_truth = float(a.s("rooms_revenue")[24:27].sum())
    q1 = float(truth[truth["month"].isin(["2028-01", "2028-02", "2028-03"])]["room_revenue"].sum())
    sl = YEAR_SLICE
    eb, cfo = a.total("ebitda", sl), a.total("cfo", sl)
    items = {"Interest paid": a.total("interest_expense", sl), "Tax paid": a.total("tax_paid", sl),
             "Working-capital increase": eb - a.total("interest_expense", sl) - a.total("tax_paid", sl) - cfo,
             "Capital expenditure": a.total("capex", sl)}
    gap_item = max(["Interest paid", "Tax paid", "Working-capital increase"], key=lambda x: abs(items[x]))
    base_a = actual_world_assumptions()
    ren = inv.run_case("renovation", base_a, {"capex": 18_000_000, "ooo_rooms": 15, "ooo_months": 6,
                                              "rate_uplift": 0.06, "demand_uplift": 0.03, "life": 10,
                                              "discount": 0.10})
    mkt = inv.run_case("marketing", base_a)
    down = simulate_cached(_apply(base_a, "segments.*.base_demand_mult", 0.9))
    d_eb = down.total("ebitda", sl) - eb
    return {"kpis": k, "budget_rn": brn, "budget_rev": brev, "rev_var": k["room_revenue"] - brev,
            "rate_var": rate_var, "vol_var": vol_var, "forecast_truth": fc_truth, "q1_last_year": q1,
            "ebitda": eb, "cfo": cfo, "gap_item": gap_item, "gap_items": items, "npv_a": ren.npv,
            "npv_b": mkt.npv, "down_ebitda_delta": d_eb, "down_pct": d_eb / eb}


# --------------------------------------------------------------------------- grading helpers
def _num_score(given: float | None, truth: float, tight: float = 0.01, loose: float = 0.05) -> float:
    if given is None:
        return 0.0
    err = abs(given - truth) / max(abs(truth), 1e-9)
    return 1.0 if err <= tight else (0.5 if err <= loose else 0.0)


def _text_rubric(text: str, must: dict[str, tuple[str, ...]], min_w: int = 40, max_w: int = 220) -> tuple[float,
                                                                                                         list[str]]:
    low = text.lower()
    words = re.findall(r"[A-Za-z0-9%']+", text)
    notes, hits = [], 0
    for name, keys in must.items():
        if any(k in low for k in keys):
            hits += 1
            notes.append(f"✓ {name}")
        else:
            notes.append(f"○ {name}")
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0].lower() if text.strip() else ""
    lead = "recommend" in first
    notes.append("✓ Leads with the recommendation" if lead else "○ Lead with the recommendation")
    length_ok = min_w <= len(words) <= max_w
    notes.append(f"{'✓' if length_ok else '○'} Length {len(words)} words ({min_w}–{max_w})")
    nums = bool(re.search(r"\d", text))
    notes.append("✓ Cites numbers" if nums else "○ Cite numbers")
    score = 0.5 * hits / max(1, len(must)) + 0.2 * lead + 0.15 * length_ok + 0.15 * nums
    return score, notes


DASHBOARD_KPIS = ["Occupancy", "ADR", "RevPAR", "Net RevPAR", "GOP margin", "EBITDA vs budget", "Closing cash",
                  "Cash conversion", "OTA share", "Labour cost %", "Number of emails sent", "Website page views",
                  "Social media followers", "Total revenue"]
DASHBOARD_ESSENTIAL = {"EBITDA vs budget", "Closing cash"}
DASHBOARD_GOOD = {"RevPAR", "Net RevPAR", "GOP margin", "Cash conversion", "OTA share", "Labour cost %", "Occupancy",
                  "ADR", "Total revenue"}
DASHBOARD_VANITY = {"Number of emails sent", "Website page views", "Social media followers"}

MEETING = [
    ("Owner", "Your forecast for next quarter: how confident are you?",
     ["Very confident; the model is accurate", "It is a range: the method, the key assumption (demand vs last year) "
      "and what would change it", "I would rather not commit to a number", "It matches the budget, so it is right"],
     1),
    ("GM", "If we cut rates 10% we will fill the hotel. Why not?",
     ["Agree, occupancy is what matters", "Price elasticity means volume rises less than price falls in most segments;"
      " I would test it on need dates only", "Rates are set by head office", "Because the budget says so"], 1),
    ("CFO", "EBITDA is positive. Why is cash not growing faster?",
     ["Accounting error", "Interest, tax and working-capital movements absorb part of EBITDA before it becomes cash",
      "Depreciation is a cash cost", "Revenue recognition timing only"], 1),
    ("Owner", "Your chosen project fails if the key assumption is 30% weaker. What then?",
     ["I would still proceed", "Show the break-even assumption, propose a stage gate and a fallback",
      "Cancel all investment", "Ask the GM"], 1),
]


@dataclass
class StepResult:
    score: float
    notes: list[str] = field(default_factory=list)


def grade_step(step: int, ans: dict) -> StepResult:
    e = expected()
    if step == 1:
        chosen = set(ans.get("rules", []))
        good = correct_rules()
        tp = len(chosen & good)
        f1 = safe_div(2 * tp, len(chosen) + len(good), 0.0)
        dup_ok = int(ans.get("duplicates", -1) or -1) == DUPLICATES
        cleaned = apply_rules(messy_rooms(), chosen)
        ok_rev = abs(float(cleaned["room_revenue"].sum()) - float(hotel_controls()["room_revenue"].sum())) < 1.0
        ok_rn = abs(float(cleaned["room_nights"].sum()) - float(hotel_controls()["occupied_rooms"].sum())) < 0.5
        notes = [f"Rule selection F1 {f1:.2f}.", f"Duplicates: {'correct' if dup_ok else f'there are {DUPLICATES}'}.",
                 f"Revenue reconciles to control totals: {'yes' if ok_rev else 'no'}; room nights: "
                 f"{'yes' if ok_rn else 'no'}."]
        for r in chosen - good:
            notes.append(f"'{RULES[r][0]}' destroys or fabricates data; document and recover instead.")
        for r in good - chosen:
            notes.append(f"Missing: {RULES[r][0]}.")
        return StepResult(0.5 * f1 + 0.2 * dup_ok + 0.15 * ok_rev + 0.15 * ok_rn, notes)
    if step == 2:
        k = e["kpis"]
        parts = [_num_score(ans.get("occupancy"), k["occupancy"], 0.005, 0.02), _num_score(ans.get("adr"), k["adr"]),
                 _num_score(ans.get("revpar"), k["revpar"]), _num_score(ans.get("net_adr"), k["net_adr"])]
        names = ["Occupancy", "ADR", "RevPAR", "Net ADR"]
        notes = [f"{n}: {'✓' if p == 1 else ('close' if p else '✗')}" for n, p in zip(names, parts)]
        return StepResult(sum(parts) / 4, notes)
    if step == 3:
        parts = [_num_score(ans.get("rev_var"), e["rev_var"], 0.01, 0.05),
                 _num_score(ans.get("rate_var"), e["rate_var"], 0.02, 0.08),
                 _num_score(ans.get("vol_var"), e["vol_var"], 0.02, 0.08),
                 1.0 if ans.get("fu") == ("F" if e["rev_var"] >= 0 else "U") else 0.0]
        notes = ["Total variance", "Rate variance (actual rooms)", "Volume variance (budget ADR)", "F/U verdict"]
        return StepResult(sum(parts) / 4, [f"{n}: {'✓' if p == 1 else ('close' if p else '✗')}"
                                           for n, p in zip(notes, parts)])
    if step == 4:
        given = ans.get("forecast")
        method = ans.get("method", "")
        m_sc = {"Seasonal (same quarter last year × growth)": 0.4, "Driver-based (rooms × occupancy × ADR)": 0.4,
                "Run-rate (last 3 months × 1)": 0.15, "Annual average ÷ 4": 0.15}.get(method, 0.0)
        err = abs((given or 0) - e["forecast_truth"]) / e["forecast_truth"]
        e_sc = 0.6 if err <= 0.08 else (0.35 if err <= 0.15 else 0.1 if given else 0.0)
        return StepResult(m_sc + e_sc, [f"Method score {m_sc:.2f} (seasonal or driver-based methods suit a seasonal "
                                        "business).", f"Error vs what actually happened: {err * 100:.1f}% "
                                        f"(actual {e['forecast_truth']:,.0f})."])
    if step == 5:
        parts = [_num_score(ans.get("ebitda"), e["ebitda"]), _num_score(ans.get("cfo"), e["cfo"]),
                 1.0 if ans.get("gap_item") == e["gap_item"] else 0.0]
        return StepResult(sum(parts) / 3, [f"EBITDA {'✓' if parts[0] == 1 else '✗'}", f"CFO {'✓' if parts[1] == 1 else '✗'}",
                                           f"Largest EBITDA→CFO item: {e['gap_item']}"])
    if step == 6:
        pa = _num_score(ans.get("npv_a"), e["npv_a"], 0.02, 0.1)
        pb = _num_score(ans.get("npv_b"), e["npv_b"], 0.02, 0.1)
        best = "A" if e["npv_a"] > e["npv_b"] else "B"
        choice = ans.get("choice")
        just = (ans.get("why") or "").lower()
        c_sc = 1.0 if choice == best else (0.6 if any(k in just for k in ("capital", "risk", "liquidity", "cash"))
                                           else 0.2)
        return StepResult(0.3 * pa + 0.3 * pb + 0.4 * c_sc,
                          [f"NPV A {'✓' if pa == 1 else '✗'} ({e['npv_a']:,.0f})",
                           f"NPV B {'✓' if pb == 1 else '✗'} ({e['npv_b']:,.0f})",
                           f"Higher-NPV option: {best}" + ("" if choice == best else
                                                          " — a different choice needs a capital or risk argument.")])
    if step == 7:
        p1 = _num_score(ans.get("down_delta"), e["down_ebitda_delta"], 0.02, 0.1)
        p2 = _num_score(ans.get("down_pct"), e["down_pct"], 0.03, 0.12)
        lev = (ans.get("insight") or "").lower()
        p3 = 1.0 if any(k in lev for k in ("leverage", "fixed cost", "fixed costs")) else 0.3
        return StepResult(0.4 * p1 + 0.3 * p2 + 0.3 * p3,
                          [f"EBITDA change at −10% demand: {e['down_ebitda_delta']:,.0f} "
                           f"({e['down_pct'] * 100:.1f}%)", "Insight should name operating leverage / fixed costs."])
    if step == 8:
        sel = set(ans.get("kpis", []))
        sc = 0.0
        notes = []
        if DASHBOARD_ESSENTIAL <= sel:
            sc += 0.4
        else:
            notes.append("An owner dashboard needs EBITDA vs budget and cash.")
        good = len(sel & DASHBOARD_GOOD)
        sc += min(0.4, 0.1 * good)
        vanity = sel & DASHBOARD_VANITY
        if vanity:
            notes.append("Vanity metrics do not inform decisions: " + ", ".join(sorted(vanity)))
        else:
            sc += 0.2
        if len(sel) != 6:
            notes.append("Choose exactly six KPIs.")
            sc *= 0.8
        return StepResult(min(1.0, sc), notes or ["Balanced dashboard: profit, cash, volume/price and efficiency."])
    if step == 9:
        sc, notes = _text_rubric(ans.get("text", ""), {
            "Names the chosen project and its NPV": ("npv", "refurb", "campaign", "marketing", "project"),
            "Explains the EBITDA/cash position": ("ebitda", "cash"),
            "States a key risk or assumption": ("risk", "assum", "sensitiv", "downside"),
            "Next step with owner or date": ("owner", "by ", "next", "week", "month")})
        return StepResult(sc, notes)
    if step == 10:
        picks = ans.get("answers", [])
        mcq = sum(1 for i, (_w, _q, _o, right) in enumerate(MEETING) if i < len(picks) and picks[i] == right)
        sc_t, notes = _text_rubric(ans.get("text", ""), {
            "Acknowledges uncertainty": ("range", "uncertain", "assum", "confidence"),
            "Explains the method": ("method", "seasonal", "driver", "last year"),
            "Offers how to monitor or update": ("monitor", "update", "pace", "review")}, 25, 160)
        notes.insert(0, f"Meeting questions: {mcq}/{len(MEETING)} strongest responses.")
        return StepResult(0.6 * mcq / len(MEETING) + 0.4 * sc_t, notes)
    raise ValueError(step)


# --------------------------------------------------------------------------- persistence
def save_step(db, step: int, answers: dict, result: StepResult) -> None:
    db.execute("INSERT INTO capstone (step, data, score, updated_at) VALUES (?,?,?,?) ON CONFLICT(step) DO UPDATE SET "
               "data=excluded.data, score=excluded.score, updated_at=excluded.updated_at",
               (str(step), json.dumps({"answers": answers, "notes": result.notes}, default=str), result.score,
                dt.datetime.now().isoformat(timespec="seconds")))


def step_scores(db) -> dict[int, float]:
    return {int(r["step"]): float(r["score"]) for r in db.query("SELECT step, score FROM capstone")}


def overall_score(db) -> float | None:
    s = step_scores(db)
    if len(s) < 10:
        return None
    return 100 * sum(s.values()) / 10


def export_dataset(out_dir: str | Path) -> list[Path]:
    from ..excel.workbooks import unique_path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, df in (("capstone_rooms_2028_RAW.csv", messy_rooms()), ("capstone_hotel_controls_2028.csv",
                                                                      hotel_controls()),
                     ("capstone_budget_2028.csv", budget_file())):
        p = unique_path(out / name)
        df.to_csv(p, index=False)
        paths.append(p)
    readme = unique_path(out / "capstone_README.txt")
    readme.write_text("Fictional training data for The Aurelia Grand (Aurelia Finance Lab). Not real hotel data and "
                      "not an industry benchmark.\nThe rooms file contains deliberate data-quality problems. The hotel "
                      "controls file is clean and can be used to recover them.\n", encoding="utf-8")
    paths.append(readme)
    return paths
