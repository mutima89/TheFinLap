"""Executive Decision Room: management cases, option evaluation and reasoning rubric.

Every number shown in a case comes from the simulation engine: each option is a
change to a documented assumption set, and its consequence is the engine result
with the change minus the result without it.

Grading is a transparent, rule-based rubric over five dimensions (numerical
accuracy, evidence quality, commercial judgement, risk awareness, communication).
Several options in a case can be defensible: an option's base quality rises when the
justification states the conditions under which it is the right call. The rubric
detects structure and keywords; it cannot judge prose the way a person can, and the
app says so next to every score.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from ..core.kpis import safe_div
from ..model.assumptions import SEGMENTS, SEGMENT_LABELS, baseline
from ..model.engine import simulate_cached, SimulationResult
from . import investment as inv
from .fpa import actual_world_assumptions

WEIGHTS = {"numerical": 0.20, "evidence": 0.20, "judgement": 0.30, "risk": 0.15, "communication": 0.15}
DIMENSION_LABELS = {"numerical": "Numerical accuracy", "evidence": "Evidence quality",
                    "judgement": "Commercial judgement", "risk": "Risk awareness", "communication": "Communication"}
GENERIC_RISK = ("risk", "downside", "sensitiv", "assum", "uncertain", "monitor", "contingen", "scenario",
                "confirm", "pilot", "test", "review", "if ")


@dataclass
class Option:
    id: str
    label: str
    description: str
    apply: Callable[[dict], dict] | None
    quality: float
    condition_terms: tuple[str, ...] = ()
    defensible_if: str = ""
    outcome_note: str = ""
    keywords: tuple[str, ...] = ()
    params: dict = field(default_factory=dict)


@dataclass
class Case:
    id: str
    title: str
    category: str
    situation: str
    question: str
    base: Callable[[], dict]
    window: tuple[int, int]
    drivers: list[tuple[str, bool]]
    options: list[Option]
    metric: str = "ebitda"            # 'ebitda' | 'cash' | 'npv'
    risk_terms: tuple[str, ...] = ()
    investigate_next: list[str] = field(default_factory=list)
    reality: Callable[[dict], dict] | None = None
    reality_note: str = ""
    extra_evidence: Callable[["Case"], list[tuple[str, object]]] | None = None
    plan: Callable[[], dict] = baseline

    @property
    def sl(self) -> slice:
        return slice(*self.window)

    def window_label(self) -> str:
        r = simulate_cached(self.plan())
        return f"{r.months[self.window[0]]} – {r.months[self.window[1] - 1]}"


# --------------------------------------------------------------------------- helpers
def _campaign(name, segs, start, months, uplift=0.0, comm=0.0, spend=0.0):
    out = []
    for i, s in enumerate(segs):
        out.append({"name": name, "segment": s, "start_month": start, "months": months,
                    "spend_per_month": spend if i == 0 else 0.0, "demand_uplift_pct": uplift,
                    "extra_commission_pct": comm})
    return out


def _mod(fn: Callable[[dict], None]) -> Callable[[dict], dict]:
    def apply(a: dict) -> dict:
        b = copy.deepcopy(a)
        fn(b)
        return b
    return apply


def _set(**paths) -> Callable[[dict], dict]:
    def fn(a):
        for p, v in paths.items():
            keys = p.split("__")
            d = a
            for k in keys[:-1]:
                d = d[k]
            d[keys[-1]] = v(d[keys[-1]]) if callable(v) else v
    return _mod(fn)


def kpi_frame(results: dict[str, SimulationResult], sl: slice) -> pd.DataFrame:
    rows = [("Occupancy", "occupancy", "pct"), ("ADR", "adr", "cur"), ("Net ADR (after commission)", "net_adr", "cur"),
            ("RevPAR", "revpar", "cur"), ("OTA share of room nights", "ota_share", "pct"),
            ("Total revenue", "total_revenue", "cur"), ("Labour cost % revenue", "labour_cost_pct", "pct"),
            ("F&B cost of sales %", "fnb_cogs_pct", "pct"), ("GOP margin", "gop_margin", "pct"),
            ("EBITDA", "ebitda", "cur"), ("Cash conversion (CFO ÷ EBITDA)", "cash_conversion", "pct"),
            ("Closing cash", "closing_cash", "cur")]
    k = {n: r.kpis(sl) for n, r in results.items()}
    data = []
    for lab, key, unit in rows:
        row = {"KPI": lab, "unit": unit}
        for n in results:
            row[n] = k[n][key]
        data.append(row)
    return pd.DataFrame(data)


# --------------------------------------------------------------------------- evaluation
@dataclass
class OptionResult:
    option: Option
    components: list[tuple[str, float]]   # lines that add up to the total
    total: float
    info: dict[str, float]


def _ebitda_components(b: SimulationResult, c: SimulationResult, sl: slice) -> tuple[list, float]:
    d = lambda k: c.total(k, sl) - b.total(k, sl)  # noqa: E731
    comps = [("Δ Total revenue", d("total_revenue")),
             ("− Δ Departmental expenses", -d("total_dept_expenses")),
             ("− Δ Undistributed expenses", -d("total_undistributed")),
             ("− Δ Management fees", -d("mgmt_fees")),
             ("− Δ Fixed charges", -d("fixed_charges"))]
    return comps, d("ebitda")


def _cash_components(b: SimulationResult, c: SimulationResult, sl: slice) -> tuple[list, float]:
    """Change in net cash position (cash − revolver): borrowing more does not count as protecting cash."""
    d = lambda k: c.total(k, sl) - b.total(k, sl)  # noqa: E731
    comps = [("Δ Operating cash flow (CFO)", d("cfo")), ("Δ Investing cash flow (CFI)", d("cfi")),
             ("Δ Financing cash flow excl. revolver", d("cff") - d("revolver_draw"))]
    return comps, d("net_cash_flow") - d("revolver_draw")


def evaluate_option(case: Case, opt: Option, world: Callable[[dict], dict] | None = None) -> OptionResult:
    base_a = case.base()
    if world:
        base_a = world(base_a)
    if case.metric == "npv":
        p = dict(opt.params)
        ev = inv.run_case("renovation", base_a, p) if p.get("_case", "renovation") == "renovation" else None
        if ev is None or p.get("_skip"):
            return OptionResult(opt, [("Capex (year 0)", 0.0), ("PV of after-tax cash flows", 0.0)], 0.0,
                                {"IRR": float("nan")})
        pv = ev.npv - ev.cash_flows[0]
        defer = p.get("_defer_years", 0)
        f = 1 / (1 + p.get("discount", 0.10)) ** defer
        comps = [("Capex (year 0)", ev.cash_flows[0] * f), ("PV of after-tax cash flows", pv * f)]
        return OptionResult(opt, comps, ev.npv * f, {"IRR": ev.irr.value if ev.irr.value is not None else np.nan,
                                                     "Payback (yrs)": ev.payback or np.nan})
    b = simulate_cached(base_a)
    c = simulate_cached(opt.apply(base_a)) if opt.apply else b
    sl = case.sl
    comps, total = (_cash_components if case.metric == "cash" else _ebitda_components)(b, c, sl)
    sev = opt.params.get("_severance_months")
    if sev:
        ha, hc = base_a["payroll"]["headcount"], opt.apply(base_a)["payroll"]["headcount"]
        sal = base_a["payroll"]["monthly_salary"]
        cost = sum((ha[k] - hc[k]) * sal[k] for k in ha) * (1 + base_a["payroll"]["on_cost_pct"]) * sev
        comps = comps + [("− Severance (assumption, outside the engine)", -cost)]
        total -= cost
    scale = opt.params.get("_scale", 1.0)
    if scale != 1.0:
        comps = [(n, v * scale) for n, v in comps]
        total *= scale
    kb, kc = b.kpis(sl), c.kpis(sl)
    info = {"Δ Occupancy (pts)": ((kc["occupancy"] or 0) - (kb["occupancy"] or 0)) * 100,
            "Δ Net ADR": (kc["net_adr"] or 0) - (kb["net_adr"] or 0),
            "Δ EBITDA": (c.total("ebitda", sl) - b.total("ebitda", sl)) * scale,
            "Δ Closing cash": float(c.s("cash")[sl.stop - 1] - b.s("cash")[sl.stop - 1]) * scale,
            "Δ Revolver": float(c.s("revolver")[sl.stop - 1] - b.s("revolver")[sl.stop - 1]) * scale}
    return OptionResult(opt, comps, total, info)


def compare_options(case: Case) -> pd.DataFrame:
    rows = []
    for o in case.options:
        r = evaluate_option(case, o)
        row = {"Option": o.label}
        for n, v in r.components:
            row[n] = v
        row[metric_label(case)] = r.total
        row.update(r.info)
        rows.append(row)
    return pd.DataFrame(rows)


def metric_label(case: Case) -> str:
    return {"ebitda": "Δ EBITDA", "cash": "Δ Net cash position", "npv": "NPV"}[case.metric]


def evidence(case: Case) -> list[tuple[str, object]]:
    plan, now = simulate_cached(case.plan()), simulate_cached(case.base())
    out: list[tuple[str, object]] = [
        (f"Plan vs current situation ({case.window_label()})", kpi_frame({"Plan": plan, "Current": now}, case.sl))]
    if case.extra_evidence:
        out.extend(case.extra_evidence(case))
    return out


# --------------------------------------------------------------------------- rubric
@dataclass
class Submission:
    case_id: str
    option_id: str
    drivers: list[str]
    estimate: float | None
    justification: str
    viewed_evidence: bool = True
    ran_analysis: bool = True


@dataclass
class Grade:
    scores: dict[str, float]
    overall: float
    feedback: dict[str, list[str]]
    truth: float
    outcome: dict


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9%']+", text)


def grade(case: Case, sub: Submission) -> Grade:
    opt = next(o for o in case.options if o.id == sub.option_id)
    res = evaluate_option(case, opt)
    truth = res.total
    text = sub.justification.strip()
    low = text.lower()
    fb: dict[str, list[str]] = {k: [] for k in WEIGHTS}
    sc: dict[str, float] = {}

    # numerical accuracy
    if sub.estimate is None:
        sc["numerical"] = 0.0
        fb["numerical"].append("No estimate entered.")
    else:
        err = abs(sub.estimate - truth)
        tol = max(abs(truth) * 0.05, 20_000.0)
        if err <= tol:
            sc["numerical"] = 1.0
            fb["numerical"].append("Estimate within 5% of the engine result.")
        elif err <= max(abs(truth) * 0.15, 60_000.0):
            sc["numerical"] = 0.6
            fb["numerical"].append("Estimate within 15%: check that every component line was included with the "
                                   "right sign.")
        elif np.sign(sub.estimate) == np.sign(truth) and truth != 0:
            sc["numerical"] = 0.25
            fb["numerical"].append("Direction right, size wrong. Rebuild the total from the component lines.")
        else:
            sc["numerical"] = 0.0
            fb["numerical"].append("Estimate has the wrong sign or is far from the engine result. Costs reduce "
                                   "EBITDA: an increase in expenses enters with a minus sign.")
        fb["numerical"].append(f"Engine result for your option: {truth:,.0f}.")

    # evidence quality
    relevant = {d for d, r in case.drivers if r}
    chosen = set(sub.drivers)
    tp = len(relevant & chosen)
    prec = safe_div(tp, len(chosen), 0.0)
    rec = safe_div(tp, len(relevant), 0.0)
    f1 = safe_div(2 * prec * rec, prec + rec, 0.0)
    cites = bool(re.search(r"\d", text))
    ev = 0.5 * f1 + 0.25 * cites + 0.125 * sub.viewed_evidence + 0.125 * sub.ran_analysis
    sc["evidence"] = ev
    missed = sorted(relevant - chosen)
    extra = sorted(chosen - relevant)
    if missed:
        fb["evidence"].append("Relevant drivers you did not select: " + "; ".join(missed) + ".")
    if extra:
        fb["evidence"].append("Selected drivers that do not explain this case: " + "; ".join(extra) + ".")
    if not cites:
        fb["evidence"].append("Quote at least one number from the analysis in your justification.")
    if f1 == 1 and cites:
        fb["evidence"].append("Drivers correctly identified and quantified.")

    # commercial judgement
    cond_hit = any(t in low for t in opt.condition_terms)
    j = min(1.0, opt.quality + (0.2 if cond_hit else 0.0))
    sc["judgement"] = j
    if opt.quality >= 0.9:
        fb["judgement"].append("Strong option for this situation.")
    elif cond_hit:
        fb["judgement"].append("A defensible choice, and you stated the condition that makes it so.")
    if opt.defensible_if and not cond_hit and opt.quality < 0.9:
        fb["judgement"].append("This option can be defended " + opt.defensible_if + " — say so explicitly.")
    best = max(case.options, key=lambda o: o.quality)
    if best.id != opt.id:
        fb["judgement"].append(f"An experienced analyst would most likely recommend: {best.label}.")

    # risk awareness
    generic = sum(1 for t in GENERIC_RISK if t in low)
    specific = sum(1 for t in case.risk_terms if t in low)
    sc["risk"] = min(1.0, 0.25 * min(generic, 2) + 0.25 * min(specific, 2))
    if specific == 0:
        fb["risk"].append("Name the case-specific risk (e.g. " + ", ".join(case.risk_terms[:3]) + ").")
    if generic == 0:
        fb["risk"].append("State what could go wrong, the key assumption, or what you would monitor.")

    # communication
    words = _words(text)
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0].lower() if text else ""
    c = 0.0
    if "recommend" in first or any(k in first for k in opt.keywords):
        c += 0.4
    else:
        fb["communication"].append("Lead with the recommendation in the first sentence.")
    n = len(words)
    if 40 <= n <= 180:
        c += 0.3
    elif 20 <= n <= 250:
        c += 0.15
        fb["communication"].append(f"{n} words: aim for 40–180 for an executive note.")
    else:
        fb["communication"].append(f"{n} words: an executive justification needs 40–180 words.")
    if cites:
        c += 0.15
    if any(t in low for t in ("next step", "owner", " by ", "within", "week", "month", "review on", "deadline")):
        c += 0.15
    else:
        fb["communication"].append("Close with a next step, owner or date.")
    sc["communication"] = min(1.0, c)

    overall = 100 * sum(WEIGHTS[k] * sc[k] for k in WEIGHTS)
    return Grade(sc, round(overall, 1), fb, truth, outcome(case, opt, sub.estimate))


def outcome(case: Case, opt: Option, estimate: float | None = None) -> dict:
    expected = evaluate_option(case, opt).total
    if case.id == "budget_request":
        return {"expected": expected, "realised": budget_request_outcome(opt)["realised"], "note": opt.outcome_note,
                "reality_note": case.reality_note, "investigate_next": case.investigate_next}
    realised = evaluate_option(case, opt, case.reality).total if case.reality else expected
    return {"expected": expected, "realised": realised, "note": opt.outcome_note,
            "reality_note": case.reality_note if case.reality else
            "Conditions turned out as assumed, so the realised result equals the analysis.",
            "investigate_next": case.investigate_next}


# --------------------------------------------------------------------------- cases
def _fpa_base():
    a = actual_world_assumptions()
    for c in a["campaigns"]:
        if c["segment"] == "leisure_ota":
            c["months"] = 33
    return a


def _fpa_targeted(a):
    for c in a["campaigns"]:
        if c["segment"] == "leisure_ota":
            c["extra_commission_pct"] = 0.01   # renegotiated promotion terms
    a["fnb"]["food_cogs_pct"] = 0.30
    a["payroll"]["overtime_pct"] = 0.05


def _payroll_base():
    a = baseline()
    a["campaigns"] = _campaign("Regional demand slowdown", SEGMENTS, "2028-01", 12, uplift=-0.12)
    a["payroll"]["overtime_pct"] = 0.09
    return a


def _ota_base():
    a = baseline()
    a["campaigns"] = _campaign("OTA visibility campaign", ["leisure_ota"], "2028-01", 12, uplift=0.15, comm=0.06,
                               spend=120_000)
    return a


def _budget_base():
    return baseline()


def _cash_base():
    a = actual_world_assumptions()
    a["working_capital"]["dso_days"] = 62.0
    a["capex"]["projects"] = [{"name": "Lobby & F&B outlet refresh", "month": "2028-02", "amount": 12_000_000,
                               "life_years": 10}]
    return a


def _shock_base():
    a = baseline()
    a["campaigns"] = _campaign("Sudden demand shock", SEGMENTS, "2028-01", 6, uplift=-0.25)
    return a


def _challenge_base():
    return baseline()


def _group_base():
    return baseline()


def _group_block(start, nights, rooms, rate, fnb=180.0):
    def fn(a):
        a["rooms"]["group_blocks"] = list(a["rooms"].get("group_blocks", [])) + [
            {"start_date": start, "nights": nights, "rooms": rooms, "rate": rate, "fnb_per_room_night": fnb}]
    return _mod(fn)


def _group_evidence(case):
    r = simulate_cached(case.base())
    d = r.daily
    mask = (d["date"] >= "2027-11-08") & (d["date"] < "2027-11-14")
    view = pd.DataFrame({"Date": d.loc[mask, "date"].dt.strftime("%a %d %b"),
                         "Available": d.loc[mask, "available"],
                         "Forecast occupied (no group)": d.loc[mask, "occupied"],
                         "Unconstrained demand": sum(d.loc[mask, f"{s}_demand"] for s in SEGMENTS),
                         "Transient ADR": [safe_div(sum(d.at[i, f"{s}_revenue"] for s in SEGMENTS if s != "group"),
                                                    sum(d.at[i, f"{s}_rooms"] for s in SEGMENTS if s != "group"))
                                           for i in d.index[mask]]})
    return [("Requested nights: forecast without the group", view.reset_index(drop=True)),
            ("Request", "60 rooms × 6 nights from Mon 8 Nov 2027 at SAR 850 net, F&B SAR 180 per room night. "
                        "The Capital Season Gala Week (10–16 Nov) compresses demand on most of these nights.")]


def _budget_evidence(case):
    r = simulate_cached(case.base())
    sl = slice(12, 24)
    t = lambda k: r.total(k, sl)  # noqa: E731
    treat = t("spa_treatments")
    df = pd.DataFrame([
        {"Metric": "Spa revenue (model year 2)", "Value": t("spa_revenue")},
        {"Metric": "Treatments", "Value": treat},
        {"Metric": "Utilisation of therapist capacity", "Value": safe_div(treat, t("spa_capacity"))},
        {"Metric": "Average treatment price", "Value": safe_div(t("spa_revenue"), treat)},
        {"Metric": "Spa departmental profit", "Value": t("spa_profit")},
        {"Metric": "Contribution per extra treatment (price × (1 − product 8% − commission 10%))",
         "Value": r.assumptions["spa"]["avg_treatment_price"] * (1 - 0.08 - 0.10)}])
    return [("Spa economics", df),
            ("Request", "The Spa Manager asks for SAR 600,000 (SAR 50,000/month) of extra marketing for next year, "
                        "stating it will 'grow external guests by about 40%'. No test results, comparable campaigns or "
                        "tracking plan were provided.")]


def _invest_evidence(case):
    ev = inv.run_case("renovation", case.base())
    return [("Refurbishment business case (full programme)", ev.table),
            ("Key assumptions", "Capex SAR 18m; 30 rooms out of order for 3 months; +6% rate and +3% demand after "
                                "completion; 10-year life; 10% discount rate. The rate uplift is a forecast from the "
                                "Revenue Manager, not observed data.")]


def _challenge_evidence(case):
    r = simulate_cached(case.base())
    sl = slice(12, 24)
    seg = pd.DataFrame([{"Segment": SEGMENT_LABELS[s],
                         "Room nights": float(r.segments[s]["room_nights"][sl].sum()),
                         "ADR": safe_div(float(r.segments[s]["revenue"][sl].sum()),
                                         float(r.segments[s]["room_nights"][sl].sum()))} for s in SEGMENTS])
    return [("Segment mix, model year 2", seg),
            ("The challenge", "The General Manager: 'Your analysis says no to more wholesale. I want 85% occupancy. "
                              "Give the wholesalers 30 more rooms a night at SAR 600 net — empty rooms earn nothing.'")]


def _shock_evidence(case):
    plan, now = simulate_cached(case.plan()), simulate_cached(case.base())
    sl = slice(12, 24)
    m = [str(x) for x in plan.months[sl]]
    df = pd.DataFrame({"Month": m, "Forecast EBITDA (pre-shock)": plan.s("ebitda")[sl],
                       "Trend EBITDA after shock": now.s("ebitda")[sl]})
    return [("Monthly EBITDA: current forecast vs post-shock trend", df),
            ("What happened", "A regional travel disruption cut new bookings by about a quarter across all segments "
                              "from January 2028. Early signals suggest six months, but this is uncertain.")]


def _cash_evidence(case):
    r = simulate_cached(case.base())
    sl = slice(0, 24)
    df = pd.DataFrame({"Month": [str(x) for x in r.months[sl]], "EBITDA": r.s("ebitda")[sl],
                       "Operating cash flow": r.s("cfo")[sl], "Capex": r.s("capex")[sl],
                       "Receivables": r.s("accounts_receivable")[sl], "Closing cash": r.s("cash")[sl],
                       "Revolver": r.s("revolver")[sl]})
    return [("Cash and working capital by month", df)]


CASES: list[Case] = [
    Case("fpa_gap", "Occupancy above budget, EBITDA below", "FP&A",
         "Nine months into the year the hotel runs ahead of budget on occupancy, yet EBITDA is well behind. The "
         "owner asks for a plan for the next 12 months.",
         "Which action plan should management adopt?", _fpa_base, (9, 21),
         [("OTA share and commission rate", True), ("F&B food cost ratio", True), ("Overtime and payroll rate", True),
          ("Loss of a corporate account (segment mix)", True), ("Occupancy level", False),
          ("Depreciation", False), ("Interest rate on the term loan", False), ("Events volume", False)],
         [Option("targeted", "Targeted recovery plan", "Renegotiate the OTA promotion's extra commission from 3% to "
                 "1%, bring food cost back to 30% and overtime back to 5%.", _mod(_fpa_targeted), 1.0, ("targeted", "root cause", "driver"),
                 outcome_note="Fixes the three quantified drivers without touching service levels.",
                 keywords=("targeted", "recovery", "ota", "food cost", "overtime")),
          Option("payroll_cut", "Cut all payroll 5%", "Reduce headcount 5% in every department.",
                 _set(payroll__headcount=lambda h: {k: round(v * 0.95) for k, v in h.items()}), 0.4,
                 ("service", "temporary", "attrition"), "if it is done through attrition and protects guest-facing "
                 "roles", "Saves cost, but spreads cuts to departments that are not the problem.",
                 keywords=("cut", "payroll", "headcount")),
          Option("raise_rates", "Raise all rates 5%", "Increase published rates by 5% in every segment.",
                 _mod(lambda a: [a["segments"][s].__setitem__("published_rate", a["segments"][s]["published_rate"] *
                                                               1.05) for s in SEGMENTS]), 0.3,
                 ("elasticity", "compression"), "if demand is compressed enough that volume barely falls",
                 "Demand is price-sensitive; volume falls and the OTA mix problem remains.",
                 keywords=("raise", "rate", "price")),
          Option("wait", "Wait for year-end", "No action until the budget for next year.", None, 0.1,
                 ("seasonal",), "only if the variance were timing-related, which the evidence does not show",
                 "The drivers persist, so the gap persists.", keywords=("wait", "no action", "hold"))],
         risk_terms=("service", "guest", "ota", "commission", "corporate", "elasticity"),
         investigate_next=["Segment-level net ADR after commission by month.",
                           "Whether the lost corporate account can be replaced (pipeline, not hope).",
                           "Food cost by outlet and the stock count reconciliation.",
                           "Overtime by department versus occupancy: rota design or absence?"]),

    Case("group_displacement", "Group request during peak week", "Revenue Management",
         "A pharmaceutical association requests 60 rooms for 6 nights during gala week at SAR 850 net. Sales wants "
         "to accept: 'SAR 306,000 of guaranteed revenue'.",
         "How should the hotel respond?", _group_base, (10, 11),
         [("Transient demand on the requested nights", True), ("Displaced transient ADR", True),
          ("Group F&B spend", True), ("Commission on displaced business", True), ("Depreciation", False),
          ("Annual occupancy", False), ("Payroll increase", False)],
         [Option("accept", "Accept as offered", "60 rooms × 6 nights at SAR 850.",
                 _group_block("2027-11-08", 6, 60, 850.0), 0.2, ("relationship", "lifetime", "repeat"),
                 "if the account brings strong repeat business in low season", "Displaces higher-rated transient "
                 "demand during the compressed week.", keywords=("accept",)),
          Option("counter_rate", "Counter at SAR 1,250", "Same dates, rate raised to SAR 1,250.",
                 _group_block("2027-11-08", 6, 60, 1250.0), 1.0, ("displacement", "walk-away", "minimum"),
                 "",
                 "Recovers displaced contribution if the group accepts the rate.", keywords=("counter", "rate")),
          Option("alt_dates", "Offer alternative dates", "Move the block to 22–28 Nov at SAR 850.",
                 _group_block("2027-11-22", 6, 60, 850.0), 0.7, ("flexible", "need period", "shoulder"),
                 "if the group is flexible on dates and the rate cannot move",
                 outcome_note="Fills rooms that would otherwise be empty; little displacement.",
                 keywords=("alternative", "dates", "move")),
          Option("decline", "Decline", "Decline the request.", None, 0.5, ("unwilling", "transient"),
                 "if the group is unwilling to move or pay more", "No gain, no displacement.",
                 keywords=("decline",))],
         risk_terms=("displace", "attrition", "wash", "transient", "relationship"),
         investigate_next=["The group's historical pickup and attrition (wash) on past contracts.",
                           "Whether transient demand forecasts for gala week were accurate last year.",
                           "Meeting-room and F&B spend per group room night."]),

    Case("renovation", "Room refurbishment approval", "Investment",
         "Engineering and Revenue Management propose an SAR 18m refurbishment. The owner asks whether to approve "
         "it now, phase it, reduce its scope or defer it a year.",
         "Which version of the project should be approved?", baseline, (0, 36),
         [("Rate uplift after completion", True), ("Rooms out of order during works", True),
          ("Discount rate", True), ("Capex amount", True), ("Last year's occupancy", False),
          ("Accounting profit in year 1", False), ("Payback period alone", False)],
         [Option("full", "Approve full programme now", "SAR 18m, 30 rooms out for 3 months.", None, 0.5,
                 ("uplift", "competitor"), "if the 6% rate uplift is well evidenced", "Value roughly breaks even at "
                 "10%; result depends on the uplift.", keywords=("approve", "full"),
                 params={"capex": 18_000_000, "ooo_rooms": 30, "ooo_months": 3, "rate_uplift": 0.06,
                         "demand_uplift": 0.03, "life": 10, "discount": 0.10}),
          Option("phased", "Phase the works", "15 rooms out at a time over 6 months, same scope and cost.",
                 None, 0.9, ("low season", "phasing", "displacement"),
                 outcome_note="Same uplift, less displaced revenue during works.", keywords=("phase", "phased"),
                 params={"capex": 18_000_000, "ooo_rooms": 15, "ooo_months": 6, "rate_uplift": 0.06,
                         "demand_uplift": 0.03, "life": 10, "discount": 0.10}),
          Option("reduced", "Reduced scope", "SAR 11m soft refurbishment, +3.5% rate, 2 months.", None, 0.4,
                 ("scope", "capital", "uplift"), "if capital is constrained or the full uplift is doubtful",
                 "Lower risk, lower return.", keywords=("reduce", "scope"),
                 params={"capex": 11_000_000, "ooo_rooms": 30, "ooo_months": 2, "rate_uplift": 0.035,
                         "demand_uplift": 0.02, "life": 8, "discount": 0.10}),
          Option("defer", "Defer one year", "Same project a year later.", None, 0.3, ("cash", "liquidity"),
                 "if liquidity is tight this year", "Value is pushed back a year and product continues to age.",
                 keywords=("defer", "delay"),
                 params={"capex": 18_000_000, "ooo_rooms": 30, "ooo_months": 3, "rate_uplift": 0.06,
                         "demand_uplift": 0.03, "life": 10, "discount": 0.10, "_defer_years": 1})],
         metric="npv", risk_terms=("uplift", "overrun", "displace", "discount rate", "competitor"),
         investigate_next=["Evidence for the rate uplift: comparable refurbished hotels' rate index (STR-style).",
                           "Contractor quotes and a contingency of 10–15%.",
                           "Break-even rate uplift at which NPV = 0."],
         reality=lambda a: a, reality_note="Assumptions held in this run; try the Investment page to stress the "
                                           "uplift."),

    Case("payroll_demand", "Payroll above forecast while demand falls", "FP&A",
         "Overtime is running at 9% of payroll while bookings for next year are 12% below plan.",
         "How should labour be managed for next year?", _payroll_base, (12, 24),
         [("Overtime rate", True), ("Headcount by department", True), ("Occupied rooms and covers", True),
          ("Fixed vs variable labour", True), ("Depreciation", False), ("Room rates", False),
          ("Opening cash", False)],
         [Option("keep", "Keep current staffing", "No change.", None, 0.2, ("recovery", "temporary"),
                 "if the slowdown is clearly temporary and rehiring is costly", "Labour cost stays high as volume "
                 "falls.", keywords=("keep", "maintain")),
          Option("flex", "Flex the rota to demand", "Overtime back to 3%; F&B −6 and Rooms −4 through attrition.",
                 _set(payroll__overtime_pct=0.03,
                      payroll__headcount=lambda h: {**h, "fnb": h["fnb"] - 6, "rooms": h["rooms"] - 4}), 1.0,
                 ("attrition", "variable", "productivity"), outcome_note="Cost follows volume; service protected.",
                 keywords=("flex", "rota", "attrition")),
          Option("cut15", "Cut headcount 15% everywhere", "Immediate 15% reduction in all departments. Includes an assumed "
                 "severance of three months' pay (outside the engine).",
                 _set(payroll__headcount=lambda h: {k: round(v * 0.85) for k, v in h.items()}), 0.4,
                 ("severance", "service"), "only if the demand fall is permanent and severance is affordable",
                 "Largest saving on paper; service damage is not in the model.",
                 keywords=("cut", "reduce"), params={"_severance_months": 3}),
          Option("hire", "Hire to remove overtime", "Overtime to 3% by adding 5 rooms staff.",
                 _set(payroll__overtime_pct=0.03, payroll__headcount=lambda h: {**h, "rooms": h["rooms"] + 5}), 0.4,
                 ("overtime premium", "fatigue"), "if overtime is structural and demand is recovering",
                 "Adds fixed cost just as volume falls.", keywords=("hire",))],
         risk_terms=("service", "guest", "severance", "morale", "turnover"),
         investigate_next=["Labour hours per occupied room and per cover by month.",
                           "Overtime by person: is it concentrated in a few roles?",
                           "Forward bookings (pace) to test how long the slowdown lasts."],
         reality=lambda a: _deepen_campaign(a, -0.18),
         reality_note="The slowdown deepened to −18% instead of −12%, so volume-driven savings mattered more."),

    Case("ota_campaign", "OTA campaign: more bookings, less contribution", "Revenue Management",
         "Marketing reports a successful OTA visibility campaign: OTA room nights are up sharply. Finance notices net "
         "ADR falling.", "What should happen to the campaign?", _ota_base, (12, 24),
         [("OTA commission rate", True), ("Displacement of direct bookings", True), ("Campaign spend", True),
          ("Net ADR", True), ("Gross occupancy", False), ("F&B covers", False), ("Depreciation", False)],
         [Option("continue", "Continue as is", "Keep the campaign running.", None, 0.1, ("market share",),
                 "if it wins share in a market where the hotel is under-indexed", "Volume up, contribution down.",
                 keywords=("continue",)),
          Option("stop", "Stop the campaign", "End it now.", _mod(lambda a: a.__setitem__("campaigns", [])), 0.9,
                 ("contribution", "net adr"), "when its net contribution is negative",
                 "Recovers net contribution; volume falls back.", keywords=("stop", "end")),
          Option("renegotiate", "Renegotiate terms", "Extra commission cut to 1.5% and spend to SAR 30k/month.",
                 _mod(lambda a: [c.update(extra_commission_pct=0.015, spend_per_month=30_000) for c in
                                 a["campaigns"]]), 1.0, ("negotiat", "terms", "commission"),
                 "if the OTA agrees", "Keeps most of the volume at lower cost.", keywords=("renegotiat", "terms")),
          Option("redirect", "Redirect spend to direct", "Stop the OTA campaign; spend SAR 120k/month on direct "
                 "marketing (+12% direct demand).",
                 _mod(lambda a: a.__setitem__("campaigns", _campaign("Direct booking campaign", ["leisure_direct"],
                                                                     "2028-01", 12, uplift=0.12, spend=120_000))),
                 0.8, ("direct", "channel"), outcome_note="Shifts mix to the cheapest channel.",
                 keywords=("redirect", "direct"))],
         risk_terms=("commission", "parity", "visibility", "displace", "channel"),
         investigate_next=["Incrementality: how many OTA bookings would have booked direct anyway?",
                           "Net ADR by channel after all distribution costs.",
                           "Rate parity and billboard effect on direct bookings."]),

    Case("budget_request", "Spa asks for budget without evidence", "Business partnering",
         "The Spa Manager requests SAR 600k extra marketing for next year to grow external guests.",
         "How should finance respond?", _budget_base, (12, 24),
         [("Spa capacity and utilisation", True), ("Contribution per treatment", True),
          ("Evidence of marketing response", True), ("Hotel occupancy", False), ("Room ADR", False),
          ("Depreciation", False)],
         [Option("approve", "Approve in full", "SAR 50k/month; assume +40% external treatments.",
                 _set(undistributed__marketing_monthly=lambda v: v + 50_000,
                      spa__external_treatments_per_day=lambda v: v * 1.4), 0.1, ("strategic",),
                 "if the hotel has a strategic reason to build the spa brand", "Relies entirely on an untested "
                 "claim.", keywords=("approve",)),
          Option("decline", "Decline", "No extra budget.", None, 0.9, ("break-even", "contribution", "evidence"),
                 "", "No risk, but no learning.", keywords=("decline",)),
          Option("pilot", "Approve a 3-month pilot with KPIs", "SAR 150k over 3 months with tracked bookings and a "
                 "stop/go review.", _set(undistributed__marketing_monthly=lambda v: v + 50_000,
                                         spa__external_treatments_per_day=lambda v: v * 1.4), 0.8,
                 ("pilot", "kpi", "track", "stop/go"), "if the pilot is small and has a clear stop/go threshold", outcome_note="Caps the downside and buys evidence.",
                 keywords=("pilot", "test"), params={"_scale": 0.25}),
          Option("half", "Approve half", "SAR 25k/month; assume +20% external treatments.",
                 _set(undistributed__marketing_monthly=lambda v: v + 25_000,
                      spa__external_treatments_per_day=lambda v: v * 1.2), 0.3, ("compromise",),
                 "as a compromise if a stop/go review is attached", "Splits the difference without evidence.",
                 keywords=("half",))],
         risk_terms=("evidence", "capacity", "utilisation", "track", "kpi"),
         investigate_next=["Spa booking source data: how external guests find the spa today.",
                           "Capacity: can therapists absorb +40% external demand at peak times?",
                           "Results of comparable campaigns or a control period."],
         reality_note="External spa demand rose about 15%, not the 40% claimed. Options that committed the full "
                      "budget lost money; the pilot limited the loss to three months and produced the evidence to "
                      "stop."),

    Case("cash_squeeze", "Cash falling despite operating profit", "Treasury & working capital",
         "EBITDA is positive every month but the cash balance keeps falling and the revolver is being drawn.",
         "What is the best way to protect cash over the next two years?", _cash_base, (0, 24),
         [("Receivable days (DSO)", True), ("Capital expenditure", True), ("Debt repayments", True),
          ("Tax payments", True), ("Occupancy", False), ("Spa utilisation", False)],
         [Option("collect", "Enforce credit terms", "Bring DSO back to 45 days.",
                 _set(working_capital__dso_days=45.0), 1.0, ("dso", "collection", "credit"),
                 outcome_note="Releases cash tied up in receivables without hurting profit.",
                 keywords=("credit", "collect", "dso")),
          Option("defer_capex", "Defer the refresh project", "Move the SAR 12m project out of the 24-month window.",
                 _mod(lambda a: a["capex"].__setitem__("projects", [])), 0.8, ("non-essential", "defer"),
                 "if the project is not urgent for guests or safety", "Large cash saving; the asset keeps ageing.",
                 keywords=("defer", "capex")),
          Option("revolver", "Raise the cash buffer with the revolver", "Minimum cash target 25m, funded by debt.",
                 _set(financing__minimum_cash=25_000_000.0), 0.3, ("liquidity", "bridge"),
                 "as a short bridge while collections are fixed", "Cash rises but debt rises equally; the cause is "
                 "untouched.", keywords=("revolver", "borrow")),
          Option("cut_marketing", "Halve base marketing", "Base marketing cut 50%.",
                 _set(undistributed__marketing_monthly=lambda v: v * 0.5), 0.3, ("discretionary",),
                 "only as a small supplementary measure", "Small saving; may hurt demand later.",
                 keywords=("cut", "marketing"))],
         metric="cash", risk_terms=("receivable", "bad debt", "covenant", "liquidity", "customer"),
         investigate_next=["Aged debtors by account: which corporate/group accounts are late?",
                           "Covenant headroom on the term loan.",
                           "A 13-week cash forecast to check the timing of the pinch."]),

    Case("demand_shock", "Forecast revision after a demand shock", "Forecasting",
         "A sudden regional disruption cut new bookings by about 25%. The approved forecast assumes nothing "
         "happened.", "How should the forecast and plan be revised?", _shock_base, (12, 24),
         [("Booking pace", True), ("Variable vs fixed costs", True), ("Duration of the shock", True),
          ("Price elasticity", True), ("Depreciation", False), ("Opening balance sheet", False)],
         [Option("keep", "Keep the approved forecast", "No revision.", None, 0.0, (),
                 "never: a forecast must reflect known information",
                 "The forecast is now wrong by the size of the shock.", keywords=("keep",)),
          Option("revise", "Revise the forecast only", "Reflect the shock; no cost action.", None, 0.6,
                 ("transparen", "accuracy"), "if costs are already lean",
                 "Honest forecast, but the gap is not managed.", keywords=("revise",)),
          Option("revise_flex", "Revise and flex costs", "Reflect the shock and flex: overtime 2%, base marketing "
                 "−30%, hiring freeze (F&B −6, Rooms −5).",
                 _set(payroll__overtime_pct=0.02, undistributed__marketing_monthly=lambda v: v * 0.7,
                      payroll__headcount=lambda h: {**h, "fnb": h["fnb"] - 6, "rooms": h["rooms"] - 5}), 1.0,
                 ("flex", "variable", "contingency"), outcome_note="Forecast reflects reality and cost follows "
                 "volume.", keywords=("revise", "flex")),
          Option("discount", "Revise and cut rates 15%", "Stimulate demand with lower rates.",
                 _mod(lambda a: [a["segments"][s].__setitem__("discount_pct", min(0.6, a["segments"][s][
                     "discount_pct"] + 0.15)) for s in SEGMENTS]), 0.2, ("elasticity",),
                 "only if demand is highly price-elastic", "Price cuts recover little volume in a shock and "
                 "linger after it.", keywords=("discount", "rate"))],
         risk_terms=("duration", "pace", "uncertain", "scenario", "range"),
         investigate_next=["Pickup curves vs last year by segment, weekly.",
                           "A downside scenario where the shock lasts 12 months.",
                           "Which costs can flex within a month, and which cannot."],
         reality=lambda a: _extend_campaign(a, 1.5),
         reality_note="The shock lasted 9 months instead of 6, so all results are worse than first estimated."),

    Case("manager_challenge", "The GM challenges your recommendation", "Executive communication",
         "You advised against adding wholesale allocation. The GM disagrees in the meeting and wants 85% "
         "occupancy.", "How do you respond?", _challenge_base, (12, 24),
         [("Displacement of higher-rated segments", True), ("Wholesale net rate", True),
          ("Variable cost per occupied room", True), ("Occupancy target", False), ("Depreciation", False)],
         [Option("concede", "Concede and implement", "Wholesale +30 rooms/night at SAR 600 net.",
                 _mod(lambda a: a["segments"]["wholesale"].update(cap=(a["segments"]["wholesale"]["cap"] or 20) + 30,
                                                                  base_demand=a["segments"]["wholesale"]["base_demand"]
                                                                  + 30, published_rate=600 / (1 - a["segments"][
                                                                      "wholesale"]["discount_pct"])))
                 , 0.4, ("low season", "need period"), "if restricted to periods with spare capacity",
                 "Occupancy rises, but low-rated rooms displace better business in peak months.",
                 keywords=("concede", "implement", "agree")),
          Option("hold", "Hold your position with the numbers", "Present the displacement analysis; no change.", None,
                 0.5, ("displace", "evidence"), "with the numbers that show the displacement",
                 "Protects profit but may not resolve the disagreement.", keywords=("hold", "maintain")),
          Option("counter", "Counter-propose a fenced test", "+15 rooms at SAR 800 net with a review after 3 months.",
                 _mod(lambda a: a["segments"]["wholesale"].update(cap=(a["segments"]["wholesale"]["cap"] or 20) + 15,
                                                                  base_demand=a["segments"]["wholesale"]["base_demand"]
                                                                  + 15, published_rate=800 / (1 - a["segments"][
                                                                      "wholesale"]["discount_pct"])))
                 , 1.0, ("fence", "test", "review"), outcome_note="Meets the GM's goal halfway while protecting rate.",
                 keywords=("counter", "propose", "test")),
          Option("escalate", "Escalate to the owner", "Ask the owner to decide.", None, 0.1, ("governance",),
                 "only if there is a governance breach", "Damages the working relationship without new evidence.",
                 keywords=("escalate",))],
         risk_terms=("displace", "rate integrity", "parity", "relationship", "peak"),
         investigate_next=["Displacement by month: where does extra wholesale fill empty rooms vs crowd out "
                           "transient guests?", "Wholesale rate leakage to public channels (parity).",
                           "The GM's underlying objective: occupancy for owner reporting, or profit?"]),
]


def _deepen_campaign(a: dict, uplift: float) -> dict:
    b = copy.deepcopy(a)
    for c in b["campaigns"]:
        c["demand_uplift_pct"] = uplift
    return b


def _extend_campaign(a: dict, factor: float) -> dict:
    b = copy.deepcopy(a)
    for c in b["campaigns"]:
        c["months"] = int(round(c["months"] * factor))
    return b


_GROUP_EVIDENCE = {"group_displacement": _group_evidence, "budget_request": _budget_evidence,
                   "renovation": _invest_evidence, "manager_challenge": _challenge_evidence,
                   "demand_shock": _shock_evidence, "cash_squeeze": _cash_evidence}
for _c in CASES:
    if _c.id in _GROUP_EVIDENCE:
        _c.extra_evidence = _GROUP_EVIDENCE[_c.id]

CASE_BY_ID = {c.id: c for c in CASES}


def budget_request_outcome(opt: Option) -> dict:
    """Realised world for the spa request: external demand rose 15%, not the claimed 40%."""
    case = CASE_BY_ID["budget_request"]
    base = case.base()
    b = simulate_cached(base)
    sl = case.sl
    if opt.id == "decline":
        return {"realised": 0.0}
    extra = {"approve": 50_000, "pilot": 50_000, "half": 25_000}[opt.id]
    uplift = {"approve": 1.15, "pilot": 1.15, "half": 1.075}[opt.id]
    real = copy.deepcopy(base)
    real["undistributed"]["marketing_monthly"] += extra
    real["spa"]["external_treatments_per_day"] *= uplift
    c = simulate_cached(real)
    d = c.total("ebitda", sl) - b.total("ebitda", sl)
    return {"realised": d * opt.params.get("_scale", 1.0)}
