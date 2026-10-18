"""Offline, deterministic, rule-based coach.

The coach never calculates financial results itself: every number it quotes comes
from the exercise definition (computed by the engine) or from the simulation result.
It works entirely offline and needs no API key. An optional local AI integration
could be added later behind the same interface, but it would only be allowed to
rephrase explanations, never to change numbers.

Capabilities
  * diagnose(): classify an answer as correct / known mistake / unknown error
  * hint(): progressive hints (concept → method → numbers)
  * solution(): step-by-step worked solution
  * assess_interpretation(): check a written interpretation for the expected points
  * gaps(): recurring mistakes across all attempts → targeted advice
  * explain_kpi(): step-by-step explanation of a KPI from the user's own scenario
  * explain_workbook_task(): turn grader output into coaching
"""
from __future__ import annotations

from dataclasses import dataclass

from .content import Exercise, is_correct, parse_answer, topics

# Advice for mistake tags (shared across topics). Keyed by tag.
TAG_ADVICE = {
    "gop_missing_undistributed": ("P&L structure", "s1_pnl"),
    "gop_vs_ebitda": ("P&L structure", "s1_pnl"),
    "margin_wrong_level": ("P&L structure", "s1_pnl"),
    "margin_wrong_base": ("P&L structure", "s1_pnl"),
    "physical_rooms": ("Available vs physical rooms", "s1_drivers"),
    "revpar_divided": ("RevPAR definition", "s1_drivers"),
    "revpar_inverse": ("RevPAR definition", "s1_drivers"),
    "commission_ignored": ("Contribution and variable costs", "s1_contribution"),
    "variable_costs_ignored": ("Contribution and variable costs", "s1_contribution"),
    "breakeven_on_price": ("Break-even on contribution", "s1_contribution"),
    "sumifs_missing_date": ("SUMIFS criteria", "s2_sumifs"),
    "sumifs_missing_segment": ("SUMIFS criteria", "s2_sumifs"),
    "countifs_or_logic": ("SUMIFS/COUNTIFS AND logic", "s2_sumifs"),
    "criteria_text_date": ("Date criteria", "s2_sumifs"),
    "match_zero_based": ("Lookups", "s2_lookup"),
    "net_adr_commission_only": ("Net ADR", "s3_segments"),
    "gross_comparison": ("Net vs gross rates", "s3_segments"),
    "elasticity_linear": ("Elasticity model", "s3_elasticity"),
    "displacement_ignored": ("Displacement", "s3_displacement"),
    "mape_on_forecast": ("Forecast accuracy", "s3_forecast"),
    "bias_absolute": ("Forecast bias", "s3_forecast"),
    "favourability_cost": ("Favourability of cost variances", "s4_variance"),
    "materiality_and": ("Materiality tests", "s4_variance"),
    "flex_actual": ("Flexible budgets", "s4_flex"),
    "static_comparison": ("Flexible budgets", "s4_flex"),
    "rate_at_budget_volume": ("Rate/volume bases", "s4_pvm"),
    "volume_at_actual_rate": ("Rate/volume bases", "s4_pvm"),
    "run_rate_as_le": ("Latest estimate vs run-rate", "s5_rolling"),
    "cash_sign": ("Cash-flow signs", "s6_three"),
    "sign_error": ("Signs and direction of flows", "s4_variance"),
    "percent_scale": ("Entering percentages", "s1_drivers"),
    "units_scale": ("Units and thousands", "s1_pnl"),
    "ebitda_drivers": ("What sits above and below EBITDA", "s1_pnl"),
    "wc_sign": ("Working-capital signs", "s6_three"),
    "depreciation_not_added": ("Non-cash items", "s6_three"),
    "tax_shield": ("Depreciation tax shield", "s6_three"),
    "dep_cash": ("Non-cash items", "s6_three"),
    "npv_year0_discounted": ("NPV timing", "s7_npv"),
    "payback_whole_year": ("Payback interpolation", "s7_payback"),
    "pi_npv": ("Profitability index", "s7_payback"),
    "intercompany": ("Consolidation", "s8_group"),
    "fee_ignored": ("Fees on GOP", "s1_pnl"),
    "fee_inverted": ("Fees on GOP", "s1_pnl"),
    "usali_classification": ("USALI classification", "s1_pnl"),
    "depreciation_ebitda": ("What sits below EBITDA", "s1_pnl"),
}


@dataclass
class Diagnosis:
    correct: bool
    tag: str | None
    message: str
    expected_display: str | None = None


def _fmt(ex: Exercise, v) -> str:
    if ex.unit == "choice" or isinstance(v, str):
        return str(v)
    if ex.unit == "pct":
        return f"{float(v) * 100:.2f}%"
    if ex.unit == "currency":
        return f"SAR {float(v):,.2f}"
    return f"{float(v):,.4g}" if abs(float(v)) < 100 else f"{float(v):,.2f}"


def _close(ex: Exercise, a: float, b: float) -> bool:
    if ex.unit == "pct":
        return abs(a - b) <= max(ex.tolerance, 1e-9)
    return abs(a - b) <= max(abs(b) * max(ex.tolerance, 0.002), 0.5 if ex.unit == "currency" else 1e-6)


def diagnose(ex: Exercise, raw) -> Diagnosis:
    given = raw if ex.unit == "choice" else (raw if isinstance(raw, (int, float)) else parse_answer(str(raw), ex.unit))
    if ex.unit != "choice" and given is None:
        return Diagnosis(False, "unparseable", "Enter a number (you can type 12.5% for a percentage).")
    if is_correct(ex, given):
        return Diagnosis(True, None, "Correct.", _fmt(ex, ex.answer))
    for val, tag, msg in ex.mistakes:
        if ex.unit == "choice" or isinstance(val, str):
            if str(given) == str(val):
                return Diagnosis(False, tag, msg)
        elif _close(ex, float(given), float(val)):
            return Diagnosis(False, tag, msg)
    if ex.unit != "choice":
        a = float(ex.answer)
        g = float(given)
        if a != 0 and _close(ex, g, -a):
            return Diagnosis(False, "sign_error", "Right size, wrong sign. Check which way the flow or variance goes.")
        if a != 0 and (abs(g / a - 100) < 0.01 or abs(g / a - 0.01) < 0.0001):
            return Diagnosis(False, "percent_scale", "Off by a factor of 100: check how you entered the percentage.")
        if a != 0 and any(abs(g / a - f) < 0.001 for f in (1000, 0.001)):
            return Diagnosis(False, "units_scale", "Off by a factor of 1,000: check thousands vs units.")
    return Diagnosis(False, "unknown", "Not quite. Use a hint, or re-read the worked example.")


def hint(ex: Exercise, level: int) -> str:
    """Progressive hints; level starts at 1. Beyond the authored hints the coach shows the method."""
    hs = list(ex.hints)
    if level <= len(hs):
        return hs[level - 1]
    if ex.solution:
        return "Method: " + ex.solution[0]
    return "Re-read the explanation and the worked example; the method is the same with new numbers."


def solution(ex: Exercise) -> str:
    steps = ex.solution or [f"Expected answer: {_fmt(ex, ex.answer)}"]
    return "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + f"</ol><p>Answer: <b>{_fmt(ex, ex.answer)}</b></p>"


def assess_interpretation(ex: Exercise, text: str) -> tuple[float, list[str]]:
    if not ex.interpretation_points:
        return 1.0, []
    low = text.lower()
    notes, hit = [], 0
    for label, keys in ex.interpretation_points:
        if any(k in low for k in keys):
            hit += 1
            notes.append(f"✓ {label}")
        else:
            notes.append(f"○ Consider: {label.lower()}")
    if len(text.split()) < 12:
        notes.append("Write at least two sentences: what the number means and what you would do.")
    return hit / len(ex.interpretation_points), notes


def gaps(db, limit: int = 300) -> list[dict]:
    """Recurring mistakes → targeted advice. Adapts to demonstrated knowledge gaps."""
    from .progress import recent_mistakes
    counts = recent_mistakes(db, limit)
    by_area: dict[str, dict] = {}
    for tag, n in counts.items():
        area, tid = TAG_ADVICE.get(tag, (None, None))
        if not area:
            continue
        a = by_area.setdefault(area, {"area": area, "topic": tid, "count": 0, "tags": []})
        a["count"] += n
        a["tags"].append(tag)
    out = sorted(by_area.values(), key=lambda d: -d["count"])
    titles = {t.id: t.title for t in topics()}
    for d in out:
        d["advice"] = (f"You have made {d['count']} mistake(s) on {d['area'].lower()}. Revisit "
                       f"'{titles.get(d['topic'], d['topic'])}', work through the worked example, then retry the "
                       "guided exercise without hints.")
        d["level"] = "recurring" if d["count"] >= 2 else "single"
    return out


def explain_kpi(result, key: str, sl=None, money=None) -> str:
    """Step-by-step explanation of a KPI using the user's own scenario numbers."""
    from ..core.kpis import KPI_DEFINITIONS
    money = money or (lambda v: f"SAR {v:,.0f}")
    sl = sl or slice(None)
    k = result.kpis(sl)
    t = lambda x: result.total(x, sl)  # noqa: E731
    d = KPI_DEFINITIONS.get(key)
    steps = {
        "occupancy": [f"Rooms sold = {t('occupied_rooms'):,.0f}", f"Rooms available = {t('available_rooms'):,.0f}",
                      f"Occupancy = {t('occupied_rooms'):,.0f} ÷ {t('available_rooms'):,.0f} = "
                      f"{(k['occupancy'] or 0) * 100:.1f}%"],
        "adr": [f"Room revenue = {money(t('rooms_revenue'))}", f"Rooms sold = {t('occupied_rooms'):,.0f}",
                f"ADR = {money(t('rooms_revenue'))} ÷ {t('occupied_rooms'):,.0f} = {money(k['adr'] or 0)}"],
        "revpar": [f"Room revenue = {money(t('rooms_revenue'))}", f"Rooms available = {t('available_rooms'):,.0f}",
                   f"RevPAR = {money(k['revpar'] or 0)} (= occupancy {(k['occupancy'] or 0) * 100:.1f}% × ADR "
                   f"{money(k['adr'] or 0)})"],
        "net_adr": [f"Room revenue {money(t('rooms_revenue'))} − commissions {money(t('commissions'))}",
                    f"÷ rooms sold {t('occupied_rooms'):,.0f} = {money(k['net_adr'] or 0)}"],
        "ebitda": [f"GOP = {money(t('gop'))}", f"− management fees {money(t('mgmt_fees'))}",
                   f"− fixed charges {money(t('fixed_charges'))}", f"= EBITDA {money(t('ebitda'))}"],
        "gop_margin": [f"GOP {money(t('gop'))} ÷ total revenue {money(t('total_revenue'))} = "
                       f"{(k['gop_margin'] or 0) * 100:.1f}%"],
        "cash_conversion": [f"CFO {money(t('cfo'))} ÷ EBITDA {money(t('ebitda'))} = "
                            f"{(k['cash_conversion'] or 0) * 100:.1f}%",
                            "Below 100% means working capital, tax or interest absorbed part of EBITDA."],
    }.get(key)
    if not steps:
        return f"<p>{d.name if d else key}: {d.formula if d else ''}</p>"
    why = {
        "occupancy": "Occupancy shows volume only; pair it with ADR before judging performance.",
        "adr": "ADR shows price achieved; a rising ADR with falling occupancy can still lower RevPAR.",
        "revpar": "RevPAR combines price and volume but ignores distribution and operating costs.",
        "net_adr": "Net ADR is what the hotel keeps after paying channels: use it for channel decisions.",
        "ebitda": "EBITDA is the owner's operating cash profit before financing and depreciation.",
        "gop_margin": "GOP margin measures how efficiently the hotel is operated.",
        "cash_conversion": "A profitable hotel can still run short of cash; this ratio shows the gap.",
    }[key]
    return ("<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>" +
            f"<p><b>Why it matters:</b> {why}</p><p><b>Your turn:</b> what would you check next if this figure "
            "moved 5% against budget?</p>")


def explain_workbook_task(task_result) -> str:
    """Coach view of one graded workbook cell."""
    lines = [f"<b>{task_result.id} {task_result.title}</b> ({task_result.status})"]
    if task_result.formula:
        lines.append(f"Your formula: <code>{task_result.formula}</code>")
    for f in task_result.feedback:
        lines.append("• " + f)
    if task_result.status != "correct" and not any("Hint" in f for f in task_result.feedback):
        lines.append("• Rebuild the calculation step by step in a spare cell and compare with each component.")
    return "<br>".join(lines)


def compare_approaches(topic_id: str) -> str:
    from .content import topic
    t = topic(topic_id)
    return t.alternatives or "<p>No alternative approach is documented for this topic.</p>"
