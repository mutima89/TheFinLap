"""Investment appraisal and business cases.

Each case changes the hotel's assumptions, runs the engine with and without the
change, and turns the *incremental* results into after-tax cash flows:

  FCF_0 = − capex
  FCF_t = ΔEBITDA_t − tax_rate × (ΔEBITDA_t − tax depreciation_t) − Δworking capital_t   (t = 1..N)
  (+ terminal value in year N where the case is a going concern)

Years 1–3 come from the engine (36-month model). Later years extend year 3 at the
stated growth rate – this extrapolation is an explicit, editable assumption.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from ..core import finance as fin
from ..model.assumptions import baseline, SEGMENTS
from ..model.engine import simulate_cached, SimulationResult


@dataclass
class Param:
    key: str
    label: str
    value: float
    unit: str = "number"  # currency | pct | number | int | years
    help: str = ""


@dataclass
class Evaluation:
    table: pd.DataFrame
    cash_flows: list[float]
    npv: float
    irr: fin.IRRResult
    mirr: float | None
    payback: float | None
    discounted_payback: float | None
    pi: float | None
    roi: float | None
    recommendation: str
    reasons: list[str]
    assumptions: list[str]
    sensitivity: pd.DataFrame
    extra: dict = field(default_factory=dict)


def _wc(res: SimulationResult) -> np.ndarray:
    """Net operating working capital at each month end."""
    return (res.s("accounts_receivable") + res.s("inventory") - res.s("accounts_payable") - res.s("vat_payable")
            - res.s("deferred_revenue"))


def incremental_cash_flows(base_a: dict, case_a: dict, capex: float, life: int, tax_depr_life: int,
                           growth_after_y3: float, terminal_growth: float | None, discount: float,
                           extra_annual: Callable[[int], float] | None = None) -> tuple[pd.DataFrame, list[float]]:
    b, c = simulate_cached(base_a), simulate_cached(case_a)
    d_e = []
    d_wc_level = []
    for y in (1, 2, 3):
        sl = b.year_slice(y)
        d_e.append(c.total("ebitda", sl) - b.total("ebitda", sl))
        d_wc_level.append(float(_wc(c)[sl][-1] - _wc(b)[sl][-1]))
    rows = []
    flows = [-capex]
    rows.append({"Year": 0, "Capex": -capex, "ΔEBITDA": 0.0, "Tax depreciation": 0.0, "Tax": 0.0,
                 "ΔWorking capital": 0.0, "Terminal value": 0.0, "Free cash flow": -capex})
    prev_wc = 0.0
    for t in range(1, life + 1):
        de = d_e[t - 1] if t <= 3 else d_e[2] * (1 + growth_after_y3) ** (t - 3)
        if extra_annual:
            de += extra_annual(t)
        dep = capex / tax_depr_life if t <= tax_depr_life else 0.0
        tax = case_a["tax"]["income_tax_rate"] * (de - dep)
        wc_level = d_wc_level[min(t, 3) - 1] if t < life else 0.0  # released at the end
        dwc = wc_level - prev_wc
        prev_wc = wc_level
        tv = 0.0
        if terminal_growth is not None and t == life:
            fcf_pre = de - tax
            tv = fin.terminal_value_gordon(fcf_pre, discount, terminal_growth)
        fcf = de - tax - dwc + tv
        flows.append(fcf)
        rows.append({"Year": t, "Capex": 0.0, "ΔEBITDA": de, "Tax depreciation": dep, "Tax": -tax,
                     "ΔWorking capital": -dwc, "Terminal value": tv, "Free cash flow": fcf})
    return pd.DataFrame(rows), flows


def evaluate(flows: list[float], discount: float, table: pd.DataFrame, assumptions: list[str],
             finance_rate: float | None = None, reinvest_rate: float | None = None, life: int | None = None) -> Evaluation:
    npv = fin.npv(discount, flows)
    irr = fin.irr(flows)
    try:
        mirr = fin.mirr(flows, finance_rate or discount, reinvest_rate or discount)
    except fin.FinanceError:
        mirr = None
    pb = fin.payback_period(flows) if flows[0] < 0 else None
    dpb = fin.discounted_payback(discount, flows) if flows[0] < 0 else None
    pi = fin.profitability_index(discount, flows)
    roi = fin.roi(sum(x for x in flows[1:]), -flows[0]) if flows[0] < 0 else None
    reasons = []
    if npv > 0:
        rec = "Proceed – value-creating at the stated discount rate, subject to the risks below."
        reasons.append(f"NPV is positive ({npv:,.0f}) at {discount * 100:.1f}%.")
        if dpb is None or (life and dpb > 0.7 * life):
            rec = "Proceed with caution – value-creating but slow to recover."
            reasons.append("Discounted payback is long relative to the asset life, increasing exposure to "
                           "forecast error.")
    else:
        rec = "Do not proceed as specified – it destroys value at the stated discount rate."
        reasons.append(f"NPV is negative ({npv:,.0f}) at {discount * 100:.1f}%.")
    if irr.status == "multiple":
        reasons.append("IRR is not meaningful (multiple IRRs). Rely on NPV and MIRR.")
    elif irr.status == "none":
        reasons.append("No IRR exists for these cash flows. Rely on NPV.")
    else:
        reasons.append(f"IRR {irr.value * 100:.1f}% vs hurdle {discount * 100:.1f}%.")
    reasons.append("Decision is not based on accounting profit or payback alone; NPV is the primary criterion.")
    # sensitivity of NPV to the benefit stream and to capex
    sens = []
    for lab, fb, fc in (("Benefits −20%", 0.8, 1.0), ("Benefits −10%", 0.9, 1.0), ("Base", 1.0, 1.0),
                        ("Benefits +10%", 1.1, 1.0), ("Capex +20%", 1.0, 1.2), ("Discount rate +2 pts", 1.0, 1.0)):
        f2 = [flows[0] * fc] + [x * fb for x in flows[1:]]
        r = discount + (0.02 if "Discount" in lab else 0.0)
        sens.append({"Case": lab, "NPV": fin.npv(r, f2)})
    return Evaluation(table, flows, npv, irr, mirr, pb, dpb, pi, roi, rec, reasons, assumptions, pd.DataFrame(sens))


# ---------------------------------------------------------------------------
# Case library
# ---------------------------------------------------------------------------

@dataclass
class Case:
    key: str
    title: str
    category: str
    description: str
    params: list[Param]
    build: Callable[[dict, dict], Evaluation]

    def defaults(self) -> dict:
        return {p.key: p.value for p in self.params}


def _common(p: dict) -> tuple[float, int]:
    return float(p["discount"]), int(p["life"])


def _renovation(a: dict, p: dict) -> Evaluation:
    disc, life = _common(p)
    c = copy.deepcopy(a)
    c["capex"]["projects"] = c["capex"]["projects"] + [{
        "name": "Room refurbishment", "month": c["meta"]["start_month"], "amount": 0.0, "life_years": life,
        "ooo_rooms": p["ooo_rooms"], "ooo_months": int(p["ooo_months"]), "rate_uplift_pct": p["rate_uplift"],
        "demand_uplift_pct": p["demand_uplift"]}]
    tab, flows = incremental_cash_flows(a, c, p["capex"], life, life, a["undistributed"]["cost_inflation_pct"],
                                        None, disc)
    assumptions = [f"Capex {p['capex']:,.0f} at t=0, depreciated over {life} years for tax.",
                   f"{p['ooo_rooms']:.0f} rooms out of order for {p['ooo_months']:.0f} months during works.",
                   f"Afterwards: rates +{p['rate_uplift'] * 100:.1f}%, demand +{p['demand_uplift'] * 100:.1f}%.",
                   "Years 1–3 from the engine; later years extend year 3 at cost inflation.",
                   f"Discount rate {disc * 100:.1f}% (assumed WACC); no terminal value (finite asset life)."]
    return evaluate(flows, disc, tab, assumptions, life=life)


def _spa(a: dict, p: dict) -> Evaluation:
    disc, life = _common(p)
    c = copy.deepcopy(a)
    c["spa"]["therapists"] += int(p["therapists"])
    c["payroll"]["headcount"]["spa"] += int(p["therapists"])
    c["spa"]["treatments_per_occupied_room"] += p["capture_uplift"]
    c["spa"]["external_treatments_per_day"] += p["external_uplift"]
    c["spa"]["avg_treatment_price"] += p["price_uplift"]
    tab, flows = incremental_cash_flows(a, c, p["capex"], life, life, 0.02, None, disc)
    assumptions = [f"Capex {p['capex']:,.0f}; {int(p['therapists'])} extra therapists hired (payroll included).",
                   f"Capture +{p['capture_uplift']:.3f} treatments per occupied room; +{p['external_uplift']:.0f} "
                   f"external treatments/day; average price +{p['price_uplift']:,.0f}.",
                   "Capacity limits still apply: extra demand only converts if therapist capacity exists.",
                   f"Discount rate {disc * 100:.1f}%; life {life} years."]
    return evaluate(flows, disc, tab, assumptions, life=life)


def _chiller(a: dict, p: dict) -> Evaluation:
    """Replace vs repair: incremental flows of REPLACE relative to REPAIR."""
    disc, life = _common(p)
    c = copy.deepcopy(a)
    c["undistributed"]["energy_fixed_kwh"] *= (1 - p["energy_saving"])

    def maint_saving(t: int) -> float:
        repair_maint = p["repair_maint"] * (1 + p["repair_maint_growth"]) ** (t - 1)
        return repair_maint - p["replace_maint"]

    incremental_capex = p["replace_capex"] - p["repair_capex"]
    tab, flows = incremental_cash_flows(a, c, incremental_capex, life, life, 0.02, None, disc,
                                        extra_annual=maint_saving)
    eac_repair = fin.equivalent_annual_cost(disc, [-p["repair_capex"]] + [
        -p["repair_maint"] * (1 + p["repair_maint_growth"]) ** (t - 1) for t in range(1, life + 1)])
    eac_replace = fin.equivalent_annual_cost(disc, [-p["replace_capex"]] + [
        -p["replace_maint"] for _ in range(life)])
    assumptions = [f"Repair now {p['repair_capex']:,.0f}; repair-path maintenance {p['repair_maint']:,.0f}/yr "
                   f"growing {p['repair_maint_growth'] * 100:.0f}%/yr.",
                   f"Replace now {p['replace_capex']:,.0f}; maintenance {p['replace_maint']:,.0f}/yr; base-load "
                   f"energy −{p['energy_saving'] * 100:.0f}% (engine-calculated saving).",
                   "Cash flows are REPLACE minus REPAIR (incremental).",
                   f"Discount rate {disc * 100:.1f}%; comparison horizon {life} years."]
    ev = evaluate(flows, disc, tab, assumptions, life=life)
    ev.extra = {"EAC repair (excl. energy)": eac_repair, "EAC replace (excl. energy)": eac_replace}
    return ev


def _marketing(a: dict, p: dict) -> Evaluation:
    disc, life = _common(p)
    c = copy.deepcopy(a)
    c["campaigns"] = c["campaigns"] + [
        {"name": "Direct booking campaign", "segment": "leisure_direct", "start_month": c["meta"]["start_month"],
         "months": int(p["months"]), "spend_per_month": p["spend"], "demand_uplift_pct": p["direct_uplift"],
         "extra_commission_pct": 0.0},
        {"name": "OTA substitution", "segment": "leisure_ota", "start_month": c["meta"]["start_month"],
         "months": int(p["months"]), "spend_per_month": 0.0, "demand_uplift_pct": -p["ota_substitution"],
         "extra_commission_pct": 0.0}]
    tab, flows = incremental_cash_flows(a, c, 0.0, min(life, 3), 1, 0.0, None, disc)
    assumptions = [f"Spend {p['spend']:,.0f}/month for {int(p['months'])} months (expensed, inside ΔEBITDA).",
                   f"Direct leisure demand +{p['direct_uplift'] * 100:.0f}%; OTA demand −"
                   f"{p['ota_substitution'] * 100:.0f}% (guests switching channel, saving commission).",
                   "No uplift after the campaign ends (conservative).",
                   f"Discount rate {disc * 100:.1f}%."]
    ev = evaluate(flows, disc, tab, assumptions, life=3)
    if flows[0] == 0:
        ev.reasons.append("No upfront investment: PI and payback are not meaningful; judge on NPV of the "
                          "incremental flows.")
    return ev


def oasis_assumptions(rooms: int = 80) -> dict:
    """Fictional second property: Aurelia Oasis Resort (coastal resort, winter peak)."""
    a = baseline()
    a["meta"]["hotel_name"] = "Aurelia Oasis Resort"
    f = rooms / 150
    a["rooms"]["total_rooms"] = rooms
    a["rooms"]["out_of_order_rooms"] = 1
    a["rooms"]["seasonality"] = [1.30, 1.30, 1.20, 1.05, 0.85, 0.60, 0.55, 0.60, 0.80, 1.05, 1.25, 1.35]
    a["rooms"]["special_events"] = []
    for s in SEGMENTS:
        seg = a["segments"][s]
        seg["base_demand"] *= f * 0.95
        seg["published_rate"] *= 1.25
        seg["reference_rate"] *= 1.25
    a["segments"]["corporate"]["base_demand"] *= 0.4
    a["segments"]["leisure_direct"]["base_demand"] *= 1.6
    a["segments"]["leisure_ota"]["base_demand"] *= 1.4
    for k in a["payroll"]["headcount"]:
        a["payroll"]["headcount"][k] = int(round(a["payroll"]["headcount"][k] * 0.6))
    for k in ("ag_fixed_monthly", "it_fixed_monthly", "marketing_monthly", "pom_fixed_monthly",
              "energy_fixed_kwh", "water_other_utilities_monthly"):
        a["undistributed"][k] *= 0.6
    a["fees_fixed"]["insurance_monthly"] *= 0.6
    a["fees_fixed"]["property_tax_lease_monthly"] *= 0.5
    a["fnb"]["outside_covers_per_day"] = 30.0
    a["events"]["events_per_month"] = 6.0
    a["spa"]["therapists"] = 8
    a["spa"]["treatments_per_occupied_room"] = 0.14
    ob = a["opening_balance"]
    ob.update(cash=10_000_000.0, accounts_receivable=0.0, inventory=500_000.0, accounts_payable=0.0, vat_payable=0.0,
              deferred_revenue=0.0, tax_payable=0.0, share_capital=60_000_000.0,
              fixed_assets=[{"name": "Building", "cost": 110_000_000.0, "accumulated": 0.0, "life_years": 50},
                            {"name": "FF&E", "cost": 30_000_000.0, "accumulated": 0.0, "life_years": 7}])
    a["financing"].update(term_loan_opening=90_000_000.0, term_loan_monthly_repayment=375_000.0,
                          minimum_cash=5_000_000.0, revolver_limit=15_000_000.0)
    return a


def _expansion(a: dict, p: dict) -> Evaluation:
    disc, life = _common(p)
    oa = oasis_assumptions(int(p["rooms"]))
    for s in SEGMENTS:
        oa["segments"][s]["base_demand"] *= p["demand_factor"]
    res = simulate_cached(oa)
    rows = [{"Year": 0, "Capex": -p["price"], "ΔEBITDA": 0.0, "Tax depreciation": 0.0, "Tax": 0.0,
             "ΔWorking capital": -p["working_capital"], "Terminal value": 0.0,
             "Free cash flow": -p["price"] - p["working_capital"]}]
    flows = [-p["price"] - p["working_capital"]]
    e = [res.total("ebitda", res.year_slice(y)) for y in (1, 2, 3)]
    capex_y = [res.total("capex", res.year_slice(y)) for y in (1, 2, 3)]
    tax_dep = p["price"] * 0.8 / 40 + p["price"] * 0.2 / 7
    for t in range(1, life + 1):
        ebitda = e[t - 1] if t <= 3 else e[2] * (1 + p["growth"]) ** (t - 3)
        cx = capex_y[t - 1] if t <= 3 else capex_y[2] * (1 + p["growth"]) ** (t - 3)
        dep = tax_dep if t <= 7 else p["price"] * 0.8 / 40
        tax = oa["tax"]["income_tax_rate"] * max(ebitda - dep, 0)
        fcf = ebitda - tax - cx
        tv = fin.terminal_value_gordon(fcf, disc, p["terminal_growth"]) if t == life else 0.0
        wc = p["working_capital"] if t == life else 0.0
        flows.append(fcf + tv + wc)
        rows.append({"Year": t, "Capex": -cx, "ΔEBITDA": ebitda, "Tax depreciation": dep, "Tax": -tax,
                     "ΔWorking capital": wc, "Terminal value": tv, "Free cash flow": fcf + tv + wc})
    assumptions = [f"Acquisition price {p['price']:,.0f} plus working capital {p['working_capital']:,.0f}.",
                   f"Aurelia Oasis Resort: {int(p['rooms'])} rooms, resort seasonality, demand factor "
                   f"{p['demand_factor']:.2f} – fictional assumptions run through the same engine.",
                   f"EBITDA years 1–3 from the engine, then +{p['growth'] * 100:.1f}%/yr; ongoing FF&E capex "
                   "deducted.",
                   f"Terminal value (Gordon) at year {life} with {p['terminal_growth'] * 100:.1f}% growth – a large "
                   "share of value; treat with caution.",
                   f"Discount rate {disc * 100:.1f}% (higher than the core hotel: new-market risk)."]
    ev = evaluate(flows, disc, pd.DataFrame(rows), assumptions, life=life)
    tv_share = fin.npv(disc, [0.0] * life + [rows[-1]["Terminal value"]]) / max(
        sum(fin.npv(disc, [0.0] * t + [f]) for t, f in enumerate(flows) if f > 0), 1e-9)
    ev.extra = {"Share of positive PV from terminal value": tv_share, "oasis_result": res}
    return ev


def _laundry(a: dict, p: dict) -> Evaluation:
    disc, life = _common(p)
    c = copy.deepcopy(a)
    c["rooms_costs"]["laundry_per_occupied_room"] = p["new_cost_per_room"]
    c["payroll"]["headcount"]["rooms"] += int(p["extra_staff"])
    c["undistributed"]["water_other_utilities_monthly"] += p["extra_utilities"]
    tab, flows = incremental_cash_flows(a, c, p["capex"], life, life, 0.02, None, disc)
    assumptions = [f"Equipment {p['capex']:,.0f}, life {life} years.",
                   f"Outsourced laundry cost {a['rooms_costs']['laundry_per_occupied_room']:,.0f} → "
                   f"{p['new_cost_per_room']:,.0f} per occupied room.",
                   f"+{int(p['extra_staff'])} laundry staff and +{p['extra_utilities']:,.0f}/month utilities.",
                   "Savings scale with occupancy, so a demand downturn reduces the benefit."]
    return evaluate(flows, disc, tab, assumptions, life=life)


_P = Param
CASES: list[Case] = [
    Case("renovation", "Room refurbishment programme", "Renovation",
         "Refurbish guest rooms: rooms are out of order during works, then achieve higher rates and demand.",
         [_P("capex", "Capital expenditure", 18_000_000, "currency"), _P("ooo_rooms", "Rooms out of order", 30),
          _P("ooo_months", "Months of works", 3, "int"), _P("rate_uplift", "Rate uplift after works", 0.06, "pct"),
          _P("demand_uplift", "Demand uplift after works", 0.03, "pct"), _P("life", "Asset life (years)", 10, "int"),
          _P("discount", "Discount rate", 0.10, "pct")], _renovation),
    Case("spa", "Couples' hammam suite (new service)", "New service launch",
         "Convert space into a premium treatment suite with two extra therapists.",
         [_P("capex", "Fit-out cost", 2_500_000, "currency"), _P("therapists", "Extra therapists", 2, "int"),
          _P("capture_uplift", "Extra treatments per occupied room", 0.015),
          _P("external_uplift", "Extra external treatments per day", 3),
          _P("price_uplift", "Average price uplift", 40, "currency"), _P("life", "Life (years)", 8, "int"),
          _P("discount", "Discount rate", 0.10, "pct")], _spa),
    Case("chiller", "Chiller plant: repair vs replace", "Replacement vs repair",
         "The central chiller is ageing. Repair it cheaply now or replace it with an efficient unit?",
         [_P("repair_capex", "Repair cost now", 600_000, "currency"),
          _P("repair_maint", "Repair path maintenance / yr", 250_000, "currency"),
          _P("repair_maint_growth", "Repair maintenance growth / yr", 0.15, "pct"),
          _P("replace_capex", "Replacement cost now", 3_200_000, "currency"),
          _P("replace_maint", "Replacement maintenance / yr", 50_000, "currency"),
          _P("energy_saving", "Base-load energy saving", 0.12, "pct"), _P("life", "Horizon (years)", 15, "int"),
          _P("discount", "Discount rate", 0.09, "pct")], _chiller),
    Case("marketing", "Direct-booking marketing campaign", "Marketing investment",
         "Spend on brand.com marketing to win leisure guests directly and shift some away from OTAs.",
         [_P("spend", "Spend per month", 80_000, "currency"), _P("months", "Campaign months", 12, "int"),
          _P("direct_uplift", "Direct leisure demand uplift", 0.12, "pct"),
          _P("ota_substitution", "OTA demand substitution", 0.06, "pct"), _P("life", "Evaluation years", 3, "int"),
          _P("discount", "Discount rate", 0.10, "pct")], _marketing),
    Case("laundry", "In-house laundry equipment", "Equipment purchase",
         "Bring laundry in-house: buy equipment and hire staff to cut the cost per occupied room.",
         [_P("capex", "Equipment cost", 1_800_000, "currency"),
          _P("new_cost_per_room", "New laundry cost per occupied room", 14, "currency"),
          _P("extra_staff", "Extra staff", 4, "int"), _P("extra_utilities", "Extra utilities / month", 12_000,
                                                         "currency"),
          _P("life", "Life (years)", 8, "int"), _P("discount", "Discount rate", 0.10, "pct")], _laundry),
    Case("expansion", "Acquire Aurelia Oasis Resort (80 rooms)", "Expansion and capacity",
         "Multi-property expansion: acquire a fictional 80-room coastal resort and run it through the same engine.",
         [_P("price", "Acquisition price", 105_000_000, "currency"),
          _P("working_capital", "Initial working capital", 3_000_000, "currency"),
          _P("rooms", "Rooms", 80, "int"), _P("demand_factor", "Demand factor vs plan", 1.0),
          _P("growth", "EBITDA growth after year 3", 0.03, "pct"),
          _P("terminal_growth", "Terminal growth", 0.025, "pct"), _P("life", "Explicit forecast years", 10, "int"),
          _P("discount", "Discount rate", 0.11, "pct")], _expansion),
]
CASE_BY_KEY = {c.key: c for c in CASES}


def run_case(key: str, a: dict, params: dict | None = None) -> Evaluation:
    case = CASE_BY_KEY[key]
    p = case.defaults()
    if params:
        p.update(params)
    if p.get("discount", 0.1) <= -1:
        raise fin.FinanceError("Discount rate must be greater than −100%.")
    if int(p.get("life", 1)) < 1:
        raise fin.FinanceError("Life must be at least one year.")
    return case.build(a, p)


def custom_cash_flows(flows: list[float], discount: float) -> Evaluation:
    tab = pd.DataFrame({"Year": list(range(len(flows))), "Free cash flow": flows})
    return evaluate(flows, discount, tab, ["User-entered cash flows."], life=len(flows) - 1)


def group_consolidation(grand: SimulationResult, oasis: SimulationResult) -> pd.DataFrame:
    keys = [("total_revenue", "Total revenue"), ("gop", "GOP"), ("ebitda", "EBITDA"), ("net_income", "Net income"),
            ("cfo", "Operating cash flow")]
    rows = []
    for k, lab in keys:
        for y in (1, 2, 3):
            g = grand.total(k, grand.year_slice(y))
            o = oasis.total(k, oasis.year_slice(y))
            rows.append({"Line": lab, "Year": f"FY{2026 + y}", "The Aurelia Grand": g, "Aurelia Oasis": o,
                         "Group": g + o})
    return pd.DataFrame(rows)
