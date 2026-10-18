"""FP&A: actuals, budget, forecasts, variance analysis and corrective actions.

Data sets
---------
* **Budget** – the approved FY2027 budget, produced by the engine from the
  budget scenario (default: Base case).
* **Actuals** – the "real" year as it unfolded. They are produced by the same
  engine from a hidden set of *actual-world* assumptions (a lost corporate
  account, an unbudgeted OTA promotion, higher overtime, energy and food
  costs, slower collections and different random demand). Only months up to the
  close month are treated as actual.
* **Forecast / latest estimate (LE)** – actual months + the working scenario for
  the remaining months.

Variance sign convention: Variance = Actual − Budget. Classification as
favourable (F) or unfavourable (U) depends on the nature of the line item.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..core.finance import safe_div
from ..model.assumptions import baseline, SEGMENTS, SEGMENT_LABELS, DEPARTMENTS, DEPARTMENT_LABELS
from ..model.engine import simulate_cached, SimulationResult

DEFAULT_AS_OF = 9  # Jan–Sep 2027 closed


def actual_world_assumptions() -> dict:
    """The fictional 'what actually happened' assumption set used to generate actuals."""
    a = baseline()
    a["rooms"]["random_seed"] = 7
    a["campaigns"] = [
        {"name": "Key corporate account lost (actual event)", "segment": "corporate", "start_month": "2027-04",
         "months": 33, "spend_per_month": 0.0, "demand_uplift_pct": -0.18, "extra_commission_pct": 0.0},
        {"name": "Unbudgeted OTA visibility promotion", "segment": "leisure_ota", "start_month": "2027-03",
         "months": 7, "spend_per_month": 60000.0, "demand_uplift_pct": 0.30, "extra_commission_pct": 0.03},
    ]
    a["payroll"]["overtime_pct"] = 0.09
    a["payroll"]["headcount"]["fnb"] = 74
    a["undistributed"]["energy_price_per_kwh"] = 0.33
    a["fnb"]["food_cogs_pct"] = 0.32
    a["working_capital"]["dso_days"] = 55.0
    a["spa"]["treatments_per_occupied_room"] = 0.065
    return a


# (key, label, nature, statement group)
PNL_LINES = [
    ("rooms_revenue", "Room revenue", "revenue", "Revenue"),
    ("fnb_revenue", "F&B revenue", "revenue", "Revenue"),
    ("spa_revenue", "Spa revenue", "revenue", "Revenue"),
    ("events_revenue", "Events revenue", "revenue", "Revenue"),
    ("other_revenue", "Other revenue", "revenue", "Revenue"),
    ("total_revenue", "Total revenue", "revenue", "Revenue"),
    ("commissions", "Commissions & distribution", "expense", "Departmental expenses"),
    ("rooms_variable_costs", "Rooms variable costs", "expense", "Departmental expenses"),
    ("fnb_cogs", "F&B cost of sales", "expense", "Departmental expenses"),
    ("fnb_labour", "F&B payroll", "expense", "Departmental expenses"),
    ("payroll_rooms", "Rooms payroll", "expense", "Departmental expenses"),
    ("total_dept_expenses", "Total departmental expenses", "expense", "Departmental expenses"),
    ("total_dept_profit", "Departmental profit", "profit", "Profit"),
    ("ag_expense", "Administrative & general", "expense", "Undistributed"),
    ("sm_expense", "Sales & marketing", "expense", "Undistributed"),
    ("pom_expense", "Property operation & maintenance", "expense", "Undistributed"),
    ("utilities_expense", "Utilities", "expense", "Undistributed"),
    ("it_expense", "Information & telecom", "expense", "Undistributed"),
    ("gop", "Gross operating profit", "profit", "Profit"),
    ("mgmt_fees", "Management fees", "expense", "Fees"),
    ("fixed_charges", "Fixed charges", "expense", "Fees"),
    ("ebitda", "EBITDA", "profit", "Profit"),
    ("cfo", "Operating cash flow", "profit", "Cash"),
]
LINE_LABEL = {k: l for k, l, _n, _g in PNL_LINES}
LINE_NATURE = {k: n for k, _l, n, _g in PNL_LINES}


def classify(nature: str, variance: float, eps: float = 0.5) -> str:
    """'F' favourable, 'U' unfavourable, '–' on budget.

    Revenue and profit: actual above budget is favourable.
    Expenses: actual above budget is unfavourable.
    """
    if abs(variance) < eps:
        return "–"
    if nature in ("revenue", "profit"):
        return "F" if variance > 0 else "U"
    if nature == "expense":
        return "U" if variance > 0 else "F"
    return "–"


def classification_note(key: str, fu: str, act_activity_ratio: float | None) -> str:
    """Context for the F/U label – a higher cost is not always bad news."""
    nature = LINE_NATURE.get(key, "context")
    if nature == "expense" and fu == "U" and act_activity_ratio and act_activity_ratio > 1.01 and key in (
            "commissions", "rooms_variable_costs", "fnb_cogs", "fnb_labour", "utilities_expense"):
        return (f"Unfavourable on the static budget, but activity was {(act_activity_ratio - 1) * 100:.1f}% above "
                "budget; judge it against the flexible budget.")
    if nature == "expense" and fu == "F" and act_activity_ratio and act_activity_ratio < 0.99:
        return ("Favourable on the static budget partly because activity was lower; check the flexible budget "
                "before calling it a saving.")
    if key == "commissions" and fu == "U":
        return "Higher commissions can be acceptable if the extra room nights add net contribution."
    return ""


@dataclass
class Materiality:
    absolute: float = 250_000.0
    percent: float = 0.05

    def is_material(self, var: float, budget: float) -> bool:
        pct = abs(var / budget) if budget else float("inf")
        return (abs(var) >= self.absolute and pct >= self.percent) or abs(var) >= 3 * self.absolute


@dataclass
class FPAData:
    budget: SimulationResult
    actual: SimulationResult
    forecast: SimulationResult
    as_of: int
    materiality: Materiality = field(default_factory=Materiality)

    # ---- period helpers -------------------------------------------------------------
    def month_slice(self, m: int) -> slice:
        return slice(m, m + 1)

    def ytd_slice(self) -> slice:
        return slice(0, self.as_of)

    def fy_slice(self) -> slice:
        return slice(0, 12)

    def le(self, key: str) -> np.ndarray:
        """Latest estimate for FY: actuals to close month, forecast after."""
        a, f = self.actual.s(key), self.forecast.s(key)
        out = f[:12].copy()
        out[:self.as_of] = a[:self.as_of]
        return out

    def series_for(self, version: str, key: str) -> np.ndarray:
        if version == "actual":
            return self.actual.s(key)
        if version == "budget":
            return self.budget.s(key)
        if version == "forecast":
            return self.forecast.s(key)
        if version == "le":
            return self.le(key)
        raise KeyError(version)

    # ---- variance tables -------------------------------------------------------------
    def variance_table(self, period: str = "ytd", month: int | None = None, compare: str = "budget") -> pd.DataFrame:
        if period == "month":
            m = self.as_of - 1 if month is None else month
            sl = slice(m, m + 1)
            act = lambda k: float(self.actual.s(k)[sl].sum())  # noqa: E731
        elif period == "ytd":
            sl = self.ytd_slice()
            act = lambda k: float(self.actual.s(k)[sl].sum())  # noqa: E731
        elif period == "fy":
            sl = self.fy_slice()
            act = lambda k: float(self.le(k).sum())  # noqa: E731
        else:
            raise ValueError(period)
        ref = self.budget if compare == "budget" else self.forecast
        activity = safe_div(float(self.actual.s("occupied_rooms")[sl].sum()) if period != "fy"
                            else float(self.le("occupied_rooms").sum()),
                            float(ref.s("occupied_rooms")[sl].sum()))
        rows = []
        for key, lab, nature, group in PNL_LINES:
            a = act(key)
            b = float(ref.s(key)[sl].sum())
            var = a - b
            fu = classify(nature, var)
            rows.append({"Line": lab, "key": key, "Group": group, "Actual": a,
                         "Budget" if compare == "budget" else "Forecast": b, "Variance": var,
                         "Variance %": safe_div(var, abs(b)) if b else None, "F/U": fu,
                         "Material": "Yes" if self.materiality.is_material(var, b) else "",
                         "Context": classification_note(key, fu, activity)})
        return pd.DataFrame(rows)

    # ---- room revenue rate / mix / volume ----------------------------------------
    def rooms_revenue_bridge(self, sl: slice) -> dict:
        """Decompose room revenue variance (actual − budget) into rate, mix and quantity effects.

        rate     = Σ_s (ADR_a,s − ADR_b,s) × RN_a,s
        mix      = Σ_s (mix_a,s − mix_b,s) × RN_a,total × ADR_b,s
        quantity = (RN_a,total − RN_b,total) × ADR_b (budget average)
        rate + mix + quantity = total variance (exactly).
        """
        A, B = self.actual, self.budget
        rn_a = {s: float(A.segments[s]["room_nights"][sl].sum()) for s in SEGMENTS}
        rn_b = {s: float(B.segments[s]["room_nights"][sl].sum()) for s in SEGMENTS}
        rv_a = {s: float(A.segments[s]["revenue"][sl].sum()) for s in SEGMENTS}
        rv_b = {s: float(B.segments[s]["revenue"][sl].sum()) for s in SEGMENTS}
        ta, tb = sum(rn_a.values()), sum(rn_b.values())
        adr_a = {s: safe_div(rv_a[s], rn_a[s], 0.0) for s in SEGMENTS}
        adr_b = {s: safe_div(rv_b[s], rn_b[s], 0.0) for s in SEGMENTS}
        adr_b_avg = safe_div(sum(rv_b.values()), tb, 0.0)
        rate = sum((adr_a[s] - adr_b[s]) * rn_a[s] for s in SEGMENTS if rn_b[s] > 0)
        # segments with no budget volume: treat their whole revenue as mix
        new_seg = sum(rv_a[s] for s in SEGMENTS if rn_b[s] == 0)
        mix = sum(((rn_a[s] / ta if ta else 0) - (rn_b[s] / tb if tb else 0)) * ta * adr_b[s]
                  for s in SEGMENTS if rn_b[s] > 0) + new_seg
        qty = (ta - tb) * adr_b_avg
        total = sum(rv_a.values()) - sum(rv_b.values())
        by_seg = pd.DataFrame([{"Segment": SEGMENT_LABELS[s], "RN actual": rn_a[s], "RN budget": rn_b[s],
                                "RN variance %": safe_div(rn_a[s] - rn_b[s], rn_b[s]),
                                "ADR actual": adr_a[s] or None, "ADR budget": adr_b[s] or None,
                                "Revenue variance": rv_a[s] - rv_b[s]} for s in SEGMENTS])
        return {"rate": rate, "mix": mix, "quantity": qty, "total": total,
                "residual": total - (rate + mix + qty), "by_segment": by_seg}

    # ---- flexible budget ------------------------------------------------------------
    def flexible_budget(self, sl: slice) -> pd.DataFrame:
        """Static vs flexible budget vs actual for activity-driven costs.

        Flexible budget = budgeted fixed element + budgeted variable rate × ACTUAL activity.
        Activity variance = flexible − static; spending variance = actual − flexible.
        """
        A, B = self.actual, self.budget
        bA = B.assumptions
        t = lambda r, k: float(r.s(k)[sl].sum())  # noqa: E731
        occ_a, occ_b = t(A, "occupied_rooms"), t(B, "occupied_rooms")
        cov_a, cov_b = t(A, "fnb_covers"), t(B, "fnb_covers")
        rows = []

        def add(label, static, fixed_b, var_rate_b, activity_a, actual, driver):
            flex = fixed_b + var_rate_b * activity_a
            rows.append({"Cost line": label, "Activity driver": driver, "Static budget": static,
                         "Flexible budget": flex, "Actual": actual, "Activity variance": flex - static,
                         "Spending variance": actual - flex,
                         "Spending F/U": classify("expense", actual - flex)})

        rvc_b = t(B, "rooms_variable_costs")
        add("Rooms variable costs", rvc_b, 0.0, safe_div(rvc_b, occ_b, 0.0), occ_a, t(A, "rooms_variable_costs"),
            "Occupied rooms")
        cogs_b = t(B, "fnb_cogs")
        add("F&B cost of sales", cogs_b, 0.0, safe_div(cogs_b, t(B, "fnb_revenue"), 0.0), t(A, "fnb_revenue"),
            t(A, "fnb_cogs"), "F&B revenue")
        lab_fixed = t(B, "payroll_fnb")
        lab_var_b = t(B, "fnb_labour") - lab_fixed
        add("F&B payroll", t(B, "fnb_labour"), lab_fixed, safe_div(lab_var_b, cov_b, 0.0), cov_a,
            t(A, "fnb_labour"), "Covers")
        util_b = t(B, "utilities_expense")
        u = bA["undistributed"]
        # fixed part of energy and water does not move with occupancy
        months = sl.stop - sl.start
        var_kwh_rate = u["energy_kwh_per_occupied_room"] * u["energy_price_per_kwh"]
        add("Utilities", util_b, util_b - var_kwh_rate * occ_b, var_kwh_rate, occ_a, t(A, "utilities_expense"),
            "Occupied rooms")
        com_b = t(B, "commissions")
        add("Commissions", com_b, 0.0, safe_div(com_b, t(B, "rooms_revenue"), 0.0), t(A, "rooms_revenue"),
            t(A, "commissions"), "Room revenue")
        _ = months
        return pd.DataFrame(rows)

    # ---- payroll rate / efficiency ----------------------------------------------------
    def payroll_variances(self, sl: slice) -> pd.DataFrame:
        A, B = self.actual, self.budget
        months = (sl.stop or 12) - (sl.start or 0)
        rows = []
        for d in DEPARTMENTS:
            hc_a = A.assumptions["payroll"]["headcount"][d]
            hc_b = B.assumptions["payroll"]["headcount"][d]
            cost_a = float(A.s(f"payroll_{d}")[sl].sum())
            cost_b = float(B.s(f"payroll_{d}")[sl].sum())
            cpf_a = safe_div(cost_a, hc_a * months, 0.0)
            cpf_b = safe_div(cost_b, hc_b * months, 0.0)
            rate = (cpf_a - cpf_b) * hc_a * months
            eff = (hc_a - hc_b) * cpf_b * months
            rows.append({"Department": DEPARTMENT_LABELS[d], "FTE actual": hc_a, "FTE budget": hc_b,
                         "Cost per FTE / month actual": cpf_a, "Cost per FTE / month budget": cpf_b,
                         "Rate variance": rate, "Headcount (efficiency) variance": eff,
                         "Total variance": cost_a - cost_b})
        return pd.DataFrame(rows)

    # ---- utilities price / consumption ----------------------------------------------
    def utilities_variance(self, sl: slice) -> dict:
        A, B = self.actual, self.budget
        kwh_a, kwh_b = float(A.s("energy_kwh")[sl].sum()), float(B.s("energy_kwh")[sl].sum())
        p_a = A.assumptions["undistributed"]["energy_price_per_kwh"]
        p_b = B.assumptions["undistributed"]["energy_price_per_kwh"]
        infl = (1 + B.assumptions["undistributed"]["cost_inflation_pct"]) ** 0
        return {"price": (p_a - p_b) * kwh_a * infl, "consumption": (kwh_a - kwh_b) * p_b * infl,
                "kwh_actual": kwh_a, "kwh_budget": kwh_b, "price_actual": p_a, "price_budget": p_b}

    # ---- explanations ------------------------------------------------------------------
    def explanations(self, period: str = "ytd") -> list[dict]:
        """Evidence-supported explanations for material variances.

        Each explanation separates what the data *quantifies* (driver attribution)
        from what still needs to be *confirmed* (possible causes). Residuals that the
        modelled drivers do not explain are reported as unexplained.
        """
        sl = self.ytd_slice() if period == "ytd" else slice(self.as_of - 1, self.as_of)
        vt = self.variance_table(period)
        out = []
        for _, r in vt[vt["Material"] == "Yes"].iterrows():
            key = r["key"]
            evidence, hypotheses = [], []
            explained = 0.0
            if key == "rooms_revenue":
                br = self.rooms_revenue_bridge(sl)
                evidence.append(f"Rate effect {br['rate']:+,.0f}; mix effect {br['mix']:+,.0f}; volume effect "
                                f"{br['quantity']:+,.0f} (sums to the total variance).")
                seg = br["by_segment"].dropna(subset=["RN variance %"]).copy()
                seg["abs"] = (seg["RN actual"] - seg["RN budget"]).abs()
                for _, sr in seg.sort_values("abs", ascending=False).head(2).iterrows():
                    evidence.append(f"{sr['Segment']} room nights {sr['RN variance %'] * 100:+.1f}% vs budget.")
                explained = br["rate"] + br["mix"] + br["quantity"]
                hypotheses.append("Why segment volumes moved (account losses, competitor pricing, promotions) is "
                                  "not visible in the data – confirm with Sales and Revenue Management.")
            elif key == "commissions":
                ota_a = float(self.actual.segments["leisure_ota"]["room_nights"][sl].sum())
                ota_b = float(self.budget.segments["leisure_ota"]["room_nights"][sl].sum())
                ca = safe_div(float(self.actual.s("commissions")[sl].sum()),
                              float(self.actual.s("rooms_revenue")[sl].sum()), 0)
                cb = safe_div(float(self.budget.s("commissions")[sl].sum()),
                              float(self.budget.s("rooms_revenue")[sl].sum()), 0)
                evidence.append(f"OTA room nights {safe_div(ota_a - ota_b, ota_b, 0) * 100:+.1f}% vs budget; "
                                f"average commission rate {ca * 100:.2f}% vs {cb * 100:.2f}% budget.")
                explained = r["Variance"]
                hypotheses.append("Check whether OTA promotions or campaign commission uplifts were approved.")
            elif key in ("fnb_labour", "payroll_rooms") or key.startswith("payroll"):
                pv = self.payroll_variances(sl)
                tot_rate, tot_eff = pv["Rate variance"].sum(), pv["Headcount (efficiency) variance"].sum()
                evidence.append(f"Across departments: rate (pay/overtime) variance {tot_rate:+,.0f}; headcount "
                                f"variance {tot_eff:+,.0f}.")
                if key == "fnb_labour":
                    fb = self.flexible_budget(sl)
                    row = fb[fb["Cost line"] == "F&B payroll"].iloc[0]
                    evidence.append(f"F&B payroll spending variance vs flexible budget {row['Spending variance']:+,.0f}"
                                    f"; activity variance {row['Activity variance']:+,.0f}.")
                    explained = row["Spending variance"] + row["Activity variance"]
                else:
                    explained = r["Variance"]
            elif key == "utilities_expense":
                uv = self.utilities_variance(sl)
                evidence.append(f"Price effect {uv['price']:+,.0f} (SAR {uv['price_actual']:.2f} vs "
                                f"{uv['price_budget']:.2f}/kWh); consumption effect {uv['consumption']:+,.0f}.")
                explained = uv["price"] + uv["consumption"]
            elif key == "fnb_cogs":
                fb = self.flexible_budget(sl)
                row = fb[fb["Cost line"] == "F&B cost of sales"].iloc[0]
                evidence.append(f"Activity (revenue) effect {row['Activity variance']:+,.0f}; cost-ratio "
                                f"(spending) effect {row['Spending variance']:+,.0f}.")
                explained = row["Activity variance"] + row["Spending variance"]
                hypotheses.append("A higher food cost ratio may reflect supplier prices, waste or menu mix – "
                                  "requires a stock count and menu-engineering review.")
            elif key == "spa_revenue":
                A, B = self.actual, self.budget
                ta, tb = float(A.s("spa_treatments")[sl].sum()), float(B.s("spa_treatments")[sl].sum())
                ca = safe_div(ta, float(A.s("occupied_rooms")[sl].sum()), 0)
                cb = safe_div(tb, float(B.s("occupied_rooms")[sl].sum()), 0)
                pa, pb = safe_div(float(A.s("spa_revenue")[sl].sum()), ta, 0), safe_div(
                    float(B.s("spa_revenue")[sl].sum()), tb, 0)
                evidence.append(f"Treatments {safe_div(ta - tb, tb, 0) * 100:+.1f}% vs budget; treatments per "
                                f"occupied room {ca:.3f} vs {cb:.3f}; average price {pa:,.0f} vs {pb:,.0f}.")
                explained = (ta - tb) * pb + (pa - pb) * ta
                hypotheses.append("Lower capture can stem from guest mix, pricing or booking friction – the data "
                                  "shows the drop, not its cause.")
            elif key == "sm_expense":
                ca = float(self.actual.s("campaign_spend")[sl].sum())
                cb = float(self.budget.s("campaign_spend")[sl].sum())
                pa = float(self.actual.s("payroll_sm")[sl].sum()) - float(self.budget.s("payroll_sm")[sl].sum())
                evidence.append(f"Campaign spend {ca:,.0f} vs {cb:,.0f} budgeted (difference {ca - cb:+,.0f}); "
                                f"S&M payroll {pa:+,.0f} (overtime/pay rate).")
                explained = ca - cb + pa
                hypotheses.append("Confirm who approved the unbudgeted campaign and whether it returned more "
                                  "contribution than it cost.")
            elif key in ("total_dept_expenses", "total_dept_profit", "gop", "ebitda", "total_revenue"):
                comps = {"total_revenue": ["rooms_revenue", "fnb_revenue", "spa_revenue", "events_revenue",
                                           "other_revenue"],
                         "total_dept_expenses": ["commissions", "rooms_variable_costs", "fnb_cogs", "fnb_labour",
                                                 "payroll_rooms"],
                         "total_dept_profit": ["total_revenue", "total_dept_expenses"],
                         "gop": ["total_dept_profit", "ag_expense", "sm_expense", "pom_expense",
                                 "utilities_expense"],
                         "ebitda": ["gop", "mgmt_fees", "fixed_charges"]}[key]
                parts = vt.set_index("key").loc[comps]
                txt = "; ".join(f"{LINE_LABEL[c]} {parts.at[c, 'Variance']:+,.0f} ({parts.at[c, 'F/U']})"
                                for c in comps)
                evidence.append("Built up from: " + txt + ".")
                if key == "total_dept_expenses":
                    explained = float(parts["Variance"].sum())
                elif key == "total_dept_profit":
                    explained = parts.at["total_revenue", "Variance"] - parts.at["total_dept_expenses", "Variance"]
                elif key == "gop":
                    explained = parts.at["total_dept_profit", "Variance"] - float(parts["Variance"].iloc[1:].sum())
                elif key == "ebitda":
                    explained = parts.at["gop", "Variance"] - float(parts["Variance"].iloc[1:].sum())
                else:
                    explained = float(parts["Variance"].sum())
                if key == "total_dept_expenses":
                    evidence.append("Remaining departmental lines (spa, events, other operated) make up the rest.")
                    explained = r["Variance"]
            elif key == "cfo":
                A, B = self.actual, self.budget
                ev = vt.set_index("key").at["ebitda", "Variance"]
                d = lambda res, k: float(res.s(k)[sl.stop - 1]) - (res.opening[k] if sl.start == 0 else  # noqa: E731
                                                                    float(res.s(k)[sl.start - 1]))
                ar = -(d(A, "accounts_receivable") - d(B, "accounts_receivable"))
                evidence.append(f"EBITDA variance {ev:+,.0f}; receivables build vs budget {ar:+,.0f} "
                                f"(DSO assumption {A.assumptions['working_capital']['dso_days']:.0f} vs "
                                f"{B.assumptions['working_capital']['dso_days']:.0f} days).")
                explained = ev + ar
                hypotheses.append("Slower collections may reflect corporate/group payment behaviour – review the "
                                  "aged debtors report.")
            residual = r["Variance"] - explained
            if not evidence:
                evidence.append("No modelled driver isolates this variance.")
                residual = r["Variance"]
            if abs(residual) > max(1.0, abs(r["Variance"]) * 0.02):
                evidence.append(f"Unexplained by modelled drivers: {residual:+,.0f}. Do not attribute a cause "
                                "without further evidence.")
            out.append({"key": key, "line": r["Line"], "variance": r["Variance"], "fu": r["F/U"],
                        "evidence": evidence, "to_confirm": hypotheses})
        return out

    def run_rate(self, key: str = "ebitda") -> dict:
        ytd = float(self.actual.s(key)[:self.as_of].sum())
        return {"ytd_actual": ytd, "run_rate_fy": ytd / self.as_of * 12 if self.as_of else None,
                "latest_estimate": float(self.le(key).sum()), "budget": float(self.budget.s(key)[:12].sum())}

    def rolling_forecast(self, months: int = 12) -> pd.DataFrame:
        """Next ``months`` after the close month from the working scenario (crosses the year end)."""
        f = self.forecast
        start = self.as_of
        end = min(start + months, f.months.size)
        rows = []
        for m in range(start, end):
            occ = safe_div(float(f.s("occupied_rooms")[m]), float(f.s("available_rooms")[m]))
            rows.append({"Month": str(f.months[m]), "Occupancy": occ,
                         "ADR": safe_div(float(f.s("rooms_revenue")[m]), float(f.s("occupied_rooms")[m])),
                         "Total revenue": float(f.s("total_revenue")[m]), "GOP": float(f.s("gop")[m]),
                         "EBITDA": float(f.s("ebitda")[m]), "Closing cash": float(f.s("cash")[m])})
        return pd.DataFrame(rows)


def build_fpa(budget_assumptions: dict, forecast_assumptions: dict, as_of: int = DEFAULT_AS_OF,
              materiality: Materiality | None = None) -> FPAData:
    return FPAData(simulate_cached(budget_assumptions), simulate_cached(actual_world_assumptions()),
                   simulate_cached(forecast_assumptions), max(1, min(12, int(as_of))),
                   materiality or Materiality())


def forecast_snapshot(fpa: FPAData) -> dict:
    """Serializable LE snapshot for forecast versioning."""
    keys = ["total_revenue", "rooms_revenue", "gop", "ebitda", "cfo", "occupied_rooms", "available_rooms"]
    return {"as_of": fpa.as_of, "months": [str(m) for m in fpa.forecast.months[:12]],
            "le": {k: [float(x) for x in fpa.le(k)] for k in keys},
            "budget": {k: [float(x) for x in fpa.budget.s(k)[:12]] for k in keys}}
