"""Learning-path content: nine stages of topics, each with explanation, context, worked
example, guided and independent exercises, common mistake, interpretation, applied task
and competency check.

Numbers in worked examples and exercises are computed from the simulation engine's
baseline (fictional) so they always agree with what the learner sees in the app.
Exercises state rounded inputs and the expected answer is computed from those exact
rounded inputs, so a learner who follows the method gets the expected answer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from ..core import finance as fin
from ..model.assumptions import baseline
from ..model.engine import simulate_cached


@dataclass
class Exercise:
    id: str
    prompt: str
    answer: float | str
    unit: str = "number"             # number | currency | pct | choice
    tolerance: float = 0.005         # relative (or absolute for pct points when unit == 'pct')
    hints: list[str] = field(default_factory=list)
    mistakes: list[tuple[float | str, str, str]] = field(default_factory=list)   # (value, tag, explanation)
    choices: list[str] | None = None
    solution: list[str] = field(default_factory=list)                           # step-by-step
    interpretation_q: str = ""
    interpretation_points: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)


@dataclass
class AppliedTask:
    prompt: str
    kind: str                         # scenario | workbook | decision | capstone | exercise
    target: str = ""                  # workbook key / case id / path
    threshold: float = 70.0
    check: Callable | None = None     # for scenario tasks: (state) -> (bool, message)
    exercise: Exercise | None = None  # for exercise-type applied tasks


@dataclass
class Topic:
    id: str
    stage: int
    title: str
    competency: str
    explanation: str
    context: str
    worked: Callable[[], str]
    guided: Exercise
    independent: Exercise
    mistake: str
    interpretation: str
    applied: AppliedTask
    check: list[Exercise]
    alternatives: str = ""
    page: str = ""


STAGES = {
    1: "Financial literacy and operating drivers",
    2: "Excel-based analysis and model construction",
    3: "Hotel Revenue Management",
    4: "Management accounting and variance analysis",
    5: "Budgeting and rolling forecasts",
    6: "Financial statement modelling and cash flow",
    7: "Investment appraisal and scenario analysis",
    8: "Commercial finance and business partnering",
    9: "Executive communication and integrated capstone",
}


@lru_cache(maxsize=1)
def _y1() -> dict:
    r = simulate_cached(baseline())
    sl = r.year_slice(1)
    t = {k: r.total(k, sl) for k in ("total_revenue", "rooms_revenue", "total_dept_expenses", "total_dept_profit",
                                      "total_undistributed", "gop", "mgmt_fees", "fixed_charges", "ebitda",
                                      "depreciation", "interest_expense", "tax_expense", "net_income",
                                      "occupied_rooms", "available_rooms", "commissions", "rooms_variable_costs",
                                      "cfo", "cfi", "cff", "fnb_revenue", "fnb_cogs")}
    t["seg"] = {s: (float(r.segments[s]["room_nights"][sl].sum()), float(r.segments[s]["revenue"][sl].sum()),
                    float(r.segments[s]["commission"][sl].sum())) for s in r.segments}
    t["cash_open"] = float(r.opening["cash"])
    t["cash_close"] = float(r.s("cash")[sl][-1])
    return t


def R(x: float, step: float = 1000) -> float:
    """Round to a presentation step (default SAR thousands)."""
    return round(x / step) * step


def m(x: float) -> str:
    return f"SAR {x:,.0f}"


# Interpretation keyword groups reused across topics
VOL = ("volume", "occupancy", "rooms sold", "demand")
RATE = ("rate", "price", "adr")
COST = ("cost", "expense", "payroll", "labour")
CASH = ("cash", "liquidity", "working capital")
ACTION = ("should", "recommend", "action", "next", "investigate", "review")


def _topics() -> list[Topic]:
    y = _y1()
    T: list[Topic] = []

    # ================================================================ STAGE 1
    rev, dex, und = R(y["total_revenue"]), R(y["total_dept_expenses"]), R(y["total_undistributed"])
    fees, fixed = R(y["mgmt_fees"]), R(y["fixed_charges"])
    gop = rev - dex - und
    ebitda = gop - fees - fixed
    T.append(Topic(
        "s1_pnl", 1, "How a hotel makes (and loses) money", "fpa",
        "<p>A hotel P&amp;L follows the Uniform System of Accounts for the Lodging Industry (USALI) layout. "
        "<b>Operated departments</b> (Rooms, F&amp;B, Spa, Events) each earn revenue and carry their own direct costs. "
        "Their <b>departmental profit</b> pays for <b>undistributed</b> costs that no single department owns "
        "(A&amp;G, Sales &amp; Marketing, Maintenance, Utilities, IT). What is left is <b>Gross Operating Profit "
        "(GOP)</b>, the measure of how well the hotel is run. Management fees and fixed charges (insurance, "
        "property tax/lease) then give <b>EBITDA</b>, the owner's operating cash profit before financing and "
        "depreciation.</p>",
        "The owner of The Aurelia Grand judges the operator on GOP and judges the investment on EBITDA and cash.",
        lambda: (f"<p>Year 1 (fictional baseline):</p><pre>Total revenue           {m(rev)}\n"
                 f"− Departmental expenses {m(dex)}\n= Departmental profit   {m(rev - dex)}\n"
                 f"− Undistributed         {m(und)}\n= GOP                   {m(gop)}   "
                 f"(GOP margin {gop / rev * 100:.1f}%)\n− Management fees       {m(fees)}\n− Fixed charges         "
                 f"{m(fixed)}\n= EBITDA                {m(ebitda)}   (EBITDA margin {ebitda / rev * 100:.1f}%)</pre>"),
        Exercise("s1_pnl_g", f"Total revenue is {m(rev)}, departmental expenses {m(dex)} and undistributed expenses "
                 f"{m(und)}. What is GOP?", gop, "currency",
                 hints=["GOP = departmental profit − undistributed expenses.",
                        "Departmental profit = revenue − departmental expenses.",
                        f"{m(rev)} − {m(dex)} − {m(und)}"],
                 mistakes=[(rev - dex, "gop_missing_undistributed", "That is departmental profit: undistributed "
                            "expenses still have to be deducted to reach GOP."),
                           (ebitda, "gop_vs_ebitda", "You also deducted fees and fixed charges; that gives EBITDA, "
                            "which sits below GOP.")],
                 solution=[f"Departmental profit = {m(rev)} − {m(dex)} = {m(rev - dex)}",
                           f"GOP = {m(rev - dex)} − {m(und)} = {m(gop)}"],
                 interpretation_q="Who in the hotel is accountable for GOP, and why does the owner care?",
                 interpretation_points=[("Names the operator / general manager", ("manager", "operator", "gm")),
                                        ("Links GOP to operating efficiency", ("efficien", "control", "run"))]),
        Exercise("s1_pnl_i", f"Using GOP of {m(gop)}, management fees of {m(fees)} and fixed charges of {m(fixed)}, "
                 f"what is the EBITDA margin on revenue of {m(rev)}?", ebitda / rev, "pct", 0.001,
                 hints=["EBITDA = GOP − fees − fixed charges.", "Margin = EBITDA ÷ total revenue."],
                 mistakes=[(gop / rev, "margin_wrong_level", "That is the GOP margin. Deduct fees and fixed charges "
                            "first."), (ebitda / R(y["rooms_revenue"]), "margin_wrong_base", "Margins use TOTAL "
                            "revenue, not rooms revenue.")],
                 solution=[f"EBITDA = {m(gop)} − {m(fees)} − {m(fixed)} = {m(ebitda)}",
                           f"Margin = {m(ebitda)} ÷ {m(rev)} = {ebitda / rev * 100:.2f}%"]),
        "<p><b>Common mistake:</b> treating GOP and EBITDA as the same thing. GOP is before management fees and "
        "fixed charges; comparing one hotel's GOP with another's EBITDA flatters the first.</p>",
        "<p>A falling GOP margin with stable revenue points to operating cost control. A falling EBITDA with a "
        "stable GOP points to fees or fixed charges — a contract or ownership issue, not an operating one.</p>",
        AppliedTask("Open the Statements page and find the year 2 EBITDA margin. Enter it here.", "exercise",
                    exercise=None),
        [Exercise("s1_pnl_c1", "Which line is NOT an undistributed expense in USALI?", "Rooms payroll", "choice",
                  choices=["Sales & marketing", "Utilities", "Rooms payroll", "Administrative & general"],
                  mistakes=[("Utilities", "usali_classification", "Utilities serve the whole hotel: undistributed."),
                            ("Sales & marketing", "usali_classification", "S&M serves the whole hotel.")]),
         Exercise("s1_pnl_c2", "If GOP rises by SAR 1m and the incentive fee is 8% of GOP, by how much does EBITDA "
                  "rise (ignore all other effects)?", 920_000.0, "currency",
                  mistakes=[(1_000_000.0, "fee_ignored", "The incentive fee takes 8% of the GOP increase."),
                            (80_000.0, "fee_inverted", "SAR 80,000 is the fee; EBITDA keeps the remaining 92%.")])],
        page="statements"))
    # applied task for s1: EBITDA margin year 2 from the engine
    r = simulate_cached(baseline())
    y2 = r.kpis(r.year_slice(2))["ebitda_margin"]
    T[-1].applied.exercise = Exercise("s1_pnl_a", "Year 2 EBITDA margin of the Base case (Statements → Operating "
                                      "statement, or Dashboard with period 'Year 2').", y2, "pct", 0.002,
                                      hints=["Set the Dashboard period to Year 2.", "EBITDA ÷ total revenue."])

    occ, adr = 0.77, R(y["rooms_revenue"] / y["occupied_rooms"], 1)
    revpar = occ * adr
    T.append(Topic(
        "s1_drivers", 1, "Occupancy, ADR and RevPAR", "rm",
        "<p><b>Occupancy</b> = rooms sold ÷ rooms <i>available</i> (rooms out of order are excluded). "
        "<b>ADR</b> (average daily rate) = room revenue ÷ rooms sold. <b>RevPAR</b> = room revenue ÷ rooms "
        "available = occupancy × ADR. RevPAR combines volume and price, which is why revenue managers track it; "
        "but it ignores distribution costs and other spend, so it is not a profit measure.</p>",
        "The Aurelia Grand has 150 rooms; 2 are out of order, so 148 are available each night.",
        lambda: (f"<pre>Rooms sold (year 1)      {y['occupied_rooms']:,.0f}\nRooms available          "
                 f"{y['available_rooms']:,.0f}\nOccupancy                {y['occupied_rooms'] / y['available_rooms'] * 100:.1f}%\n"
                 f"Room revenue             {m(y['rooms_revenue'])}\nADR                      "
                 f"{m(y['rooms_revenue'] / y['occupied_rooms'])}\nRevPAR = Occ × ADR        "
                 f"{m(y['rooms_revenue'] / y['available_rooms'])}</pre>"),
        Exercise("s1_drv_g", f"Occupancy is 77.0% and ADR is {m(adr)}. What is RevPAR?", revpar, "currency",
                 hints=["RevPAR = occupancy × ADR.", f"0.77 × {adr:,.0f}"],
                 mistakes=[(adr / occ, "revpar_divided", "Divide? No: RevPAR is occupancy TIMES ADR.")],
                 solution=[f"RevPAR = 0.77 × {m(adr)} = {m(revpar)}"]),
        Exercise("s1_drv_i", "The owner wants RevPAR of SAR 950 next year. If occupancy stays at 77.0%, what ADR "
                 "is required?", 950 / 0.77, "currency",
                 hints=["ADR = RevPAR ÷ occupancy."],
                 mistakes=[(950 * 0.77, "revpar_inverse", "Multiply gives a smaller number than RevPAR, which is "
                            "impossible: ADR is always ≥ RevPAR.")],
                 solution=["ADR = 950 ÷ 0.77 = SAR 1,233.77"],
                 interpretation_q="Is raising ADR to that level realistic? What else could change?",
                 interpretation_points=[("Mentions demand response / elasticity", ("elastic", "demand", "volume")),
                                        ("Mentions an alternative lever", ("occupancy", "mix", "segment"))]),
        "<p><b>Common mistake:</b> dividing by physical rooms (150) instead of available rooms (148), or "
        "confusing ADR (per room sold) with RevPAR (per room available).</p>",
        "<p>The same RevPAR can come from high occupancy at a low rate or low occupancy at a high rate. The "
        "second usually earns more profit because each occupied room carries variable costs (housekeeping, "
        "amenities, laundry, commission).</p>",
        AppliedTask("In the Scenario Lab, change one driver so that year-1 RevPAR rises by at least 3% while "
                    "EBITDA also rises. (Check: compares your working draft to the saved Base case.)", "scenario",
                    check=_check_revpar_and_ebitda),
        [Exercise("s1_drv_c1", "A hotel sells 120 of 148 available rooms at an ADR of SAR 1,000. RevPAR?",
                  120 / 148 * 1000, "currency",
                  mistakes=[(120 / 150 * 1000, "physical_rooms", "Use available rooms (148), not physical rooms.")]),
         Exercise("s1_drv_c2", "Which statement is true?", "RevPAR can rise while profit falls", "choice",
                  choices=["Higher RevPAR always means higher profit", "RevPAR can rise while profit falls",
                           "ADR includes rooms out of order", "Occupancy uses physical rooms"])],
        alternatives="<p>RevPAR vs <b>net RevPAR</b> (after commissions) vs <b>GOPPAR</b> (GOP per available room): "
                     "each step moves closer to profit. Use RevPAR for pricing, net RevPAR for channel decisions, "
                     "GOPPAR for owner returns.</p>", page="rm"))

    hk = 35 + 55 + 30
    contrib = R(adr, 1) * (1 - 0.03) - hk
    fixed_m = 2_400_000.0
    T.append(Topic(
        "s1_contribution", 1, "Fixed costs, variable costs and contribution", "fpa",
        "<p>A <b>variable cost</b> moves with activity (guest supplies, laundry, commission per room sold). A "
        "<b>fixed cost</b> does not move within the planning range (most salaries, insurance, base marketing). "
        "<b>Contribution</b> = price − variable cost per unit; it is what each extra room sold adds towards fixed "
        "costs and profit. <b>Break-even volume</b> = fixed costs ÷ contribution per unit.</p>",
        "Pricing, discounting and group decisions all hinge on contribution, not on revenue.",
        lambda: (f"<pre>ADR                                {m(adr)}\n− Commission (3%)                   "
                 f"{m(adr * 0.03)}\n− Housekeeping + supplies + laundry {m(hk)}\n= Contribution per room sold        "
                 f"{m(contrib)}</pre><p>Fixed costs are covered once enough rooms are sold; each room beyond "
                 "break-even adds its full contribution to profit (operating leverage).</p>"),
        Exercise("s1_con_g", f"ADR is {m(adr)}; commission averages 3% of rate; housekeeping, supplies and laundry "
                 f"cost SAR {hk} per room sold. What is the contribution per room sold?", contrib, "currency",
                 hints=["Contribution = rate − all variable costs per room.", "Commission = 3% × ADR.",
                        f"{adr:,.0f} − {adr * 0.03:,.2f} − {hk}"],
                 mistakes=[(adr - hk, "commission_ignored", "Commission is a variable cost too."),
                           (adr * 0.97, "variable_costs_ignored", "Deduct housekeeping, supplies and laundry.")],
                 solution=[f"Commission = 3% × {adr:,.0f} = {adr * 0.03:,.2f}",
                           f"Contribution = {adr:,.0f} − {adr * 0.03:,.2f} − {hk} = {contrib:,.2f}"]),
        Exercise("s1_con_i", f"Rooms-related fixed costs are {m(fixed_m)} a month. Using a contribution of "
                 f"{m(contrib)} per room sold, how many rooms must be sold per month to break even?",
                 fixed_m / contrib, "number", 0.002,
                 hints=["Break-even units = fixed costs ÷ contribution per unit."],
                 mistakes=[(fixed_m / adr, "breakeven_on_price", "Divide by contribution, not by price: the "
                            "variable cost of each room is not available to cover fixed costs.")],
                 solution=[f"{m(fixed_m)} ÷ {contrib:,.2f} = {fixed_m / contrib:,.0f} rooms"]),
        "<p><b>Common mistake:</b> calculating break-even on price instead of contribution, which understates "
        "the volume needed.</p>",
        "<p>Because most hotel costs are fixed in the short term, small changes in occupancy move profit a lot "
        "(high operating leverage) — in both directions.</p>",
        AppliedTask("In Modelling Workbench → H. Unit economics, find the break-even occupancy for the Base case "
                    "(year 1) and enter it.", "exercise"),
        [Exercise("s1_con_c1", "Price SAR 500, variable cost SAR 200, fixed costs SAR 90,000. Break-even units?",
                  300.0, "number", mistakes=[(180.0, "breakeven_on_price", "Divide by contribution (500 − 200).")]),
         Exercise("s1_con_c2", "Which cost is most likely variable in a hotel?", "OTA commission", "choice",
                  choices=["General Manager salary", "Property insurance", "OTA commission", "Building depreciation"])],
        page="workbench"))
    T[-1].applied.exercise = _unit_breakeven_exercise()

    # ================================================================ STAGE 2
    T.append(Topic(
        "s2_sumifs", 2, "Conditional aggregation: SUMIFS and COUNTIFS", "excel",
        "<p><code>SUMIFS(sum_range, criteria_range1, criteria1, …)</code> adds the values that meet <i>all</i> "
        "criteria. Criteria can be text (\"Corporate\"), comparisons (\">=135\") or dates built with "
        "<code>\"&gt;=\"&amp;DATE(2027,2,1)</code>. <code>COUNTIFS</code> counts instead of adding.</p>",
        "Booking ledgers have one row per booking or per day and segment; SUMIFS turns them into segment and "
        "period totals.",
        lambda: ("<pre>=SUMIFS(Bookings!F:F, Bookings!B:B, \"Corporate (negotiated)\",\n        Bookings!A:A, "
                 "\"&gt;=\"&amp;DATE(2027,2,1), Bookings!A:A, \"&lt;\"&amp;DATE(2027,3,1))</pre>"
                 "<p>Three criteria: the segment, on or after 1 Feb, and before 1 Mar. Using '&lt;' the first of the "
                 "next month avoids end-of-month and time-of-day errors.</p>"),
        Exercise("s2_sum_g", "Rows: (Corporate, 10 Jan, 1,000), (OTA, 12 Jan, 600), (Corporate, 3 Feb, 900), "
                 "(Corporate, 28 Feb, 400). What does SUMIFS return for Corporate revenue in February?", 1300.0,
                 hints=["Keep rows that are Corporate AND dated in February.", "900 + 400"],
                 mistakes=[(2300.0, "sumifs_missing_date", "You summed all Corporate rows; add the date criteria."),
                           (1900.0, "sumifs_missing_segment", "You summed all February rows; add the segment "
                            "criterion.")]),
        Exercise("s2_sum_i", "Same rows. How many rows does COUNTIFS(segment, \"Corporate\", revenue, \">=900\") "
                 "count?", 2.0, hints=["Both conditions must hold on the same row."],
                 mistakes=[(3.0, "countifs_or_logic", "COUNTIFS uses AND logic: the 400 row fails the second "
                            "criterion.")]),
        "<p><b>Common mistakes:</b> ranges of different sizes (#VALUE!), typing the criterion as "
        "<code>\"&gt;=DATE(2027,2,1)\"</code> (text, never matches), and summing whole columns that include the "
        "header or a total row.</p>",
        "<p>Conditional aggregation is how a finance team answers \"which segment drove the change?\" in seconds.</p>",
        AppliedTask("Generate the workbooks (Excel Lab), complete '01 Revenue KPIs' in Excel and grade it. "
                    "Pass mark: 70%.", "workbook", "revenue"),
        [Exercise("s2_sum_c1", "Which criterion correctly selects dates on or after 1 March 2027?",
                  "\">=\"&DATE(2027,3,1)", "choice",
                  choices=["\">=DATE(2027,3,1)\"", "\">=\"&DATE(2027,3,1)", ">=DATE(2027,3,1)", "\"=>2027-03-01\""],
                  mistakes=[("\">=DATE(2027,3,1)\"", "criteria_text_date", "Inside quotes DATE() is just text.")]),
         Exercise("s2_sum_c2", "SUMIFS(C2:C10, A2:A11, \"x\") returns…", "#VALUE!", "choice",
                  choices=["The sum of matching rows", "0", "#VALUE!", "#N/A"])],
        page="excel"))

    T.append(Topic(
        "s2_lookup", 2, "Lookups and error handling: XLOOKUP, INDEX/MATCH, IFERROR", "excel",
        "<p><code>XLOOKUP(value, lookup_range, return_range, [if_not_found])</code> finds an exact match by "
        "default. <code>INDEX(return_range, MATCH(value, lookup_range, 0))</code> is the pre-365 equivalent; the "
        "0 forces an exact match. <code>IFERROR(x, alt)</code> replaces any error with an alternative — useful for "
        "division by zero, dangerous when it hides a broken lookup.</p>",
        "Mapping account codes to P&L lines, rates to segments, budgets to departments.",
        _worked_lookup,
        Exercise("s2_lk_g", "MATCH(\"OTA\", {\"Direct\",\"OTA\",\"Group\"}, 0) returns…", 2.0,
                 hints=["MATCH returns the position, not the value.", "Positions start at 1."],
                 mistakes=[(1.0, "match_zero_based", "Positions in Excel start at 1, not 0.")]),
        Exercise("s2_lk_i", "Why is =IFERROR(XLOOKUP(code, codes, amounts), 0) risky in a P&L mapping?",
                 "A missing code silently becomes 0 and the P&L no longer reconciles", "choice",
                 choices=["It is slower than VLOOKUP", "A missing code silently becomes 0 and the P&L no longer "
                          "reconciles", "XLOOKUP cannot return numbers", "IFERROR only catches #DIV/0!"]),
        "<p><b>Common mistake:</b> VLOOKUP with the default approximate match on unsorted data returns a wrong "
        "value without an error. Always use exact match for codes and names.</p>",
        "<p>Every lookup should be paired with a reconciliation check (totals before = totals after mapping).</p>",
        AppliedTask("Complete the lookup and IF tasks in '01 Revenue KPIs' (graded with the workbook).", "workbook",
                    "revenue"),
        [Exercise("s2_lk_c1", "VLOOKUP(x, table, 2) with the 4th argument omitted performs…",
                  "An approximate match", "choice", choices=["An exact match", "An approximate match",
                                                             "A wildcard match", "An error"])],
        page="excel"))

    T.append(Topic(
        "s2_model", 2, "Building a sound model: inputs, calculations, checks", "excel",
        "<p>Separate <b>inputs</b> (blue, one place, documented), <b>calculations</b> (black, no typed numbers) "
        "and <b>outputs</b>. Link, don't retype. Build <b>checks</b> that must equal zero (balance sheet balances, "
        "sub-totals add up, mapped totals reconcile) and show them prominently.</p>",
        "Aurelia's own engine follows this: drivers in one assumption set, a dependency graph for calculations, "
        "and 14 integrity checks on every run (Statements → Integrity checks).",
        _worked_model,
        Exercise("s2_mod_g", "A balance-sheet check shows 0 for months 1–5 and −250,000 from month 6. What is the "
                 "most likely cause?", "A flow posted to one statement only from month 6", "choice",
                 choices=["Rounding", "A flow posted to one statement only from month 6",
                          "The opening balance sheet is wrong", "Excel needs recalculating"]),
        Exercise("s2_mod_i", "A cell contains =B4*1.15 where 1.15 represents VAT. What is the best fix?",
                 "Put the VAT rate in an input cell and reference it", "choice",
                 choices=["Leave it: it is correct today", "Put the VAT rate in an input cell and reference it",
                          "Replace it with the calculated value", "Add a comment"]),
        "<p><b>Common mistake:</b> hard-coding a number inside a formula. When the input changes, the model is "
        "silently wrong.</p>",
        "<p>Model checks are what make a number safe to put in front of an owner.</p>",
        AppliedTask("Complete '03 Three-Statement Mini Model' so every balance check is zero; grade it (≥ 70%).",
                    "workbook", "three_statement"),
        [Exercise("s2_mod_c1", "Which is an output, not an input?", "EBITDA", "choice",
                  choices=["DSO days", "Tax rate", "EBITDA", "Opening cash"])],
        page="workbench"))

    # ================================================================ STAGE 3
    ota_rn, ota_rev, ota_com = y["seg"]["leisure_ota"]
    ota_adr = R(ota_rev / ota_rn, 1)
    ota_cp = round(ota_com / ota_rev, 3)
    T.append(Topic(
        "s3_segments", 3, "Segments, channels and net ADR", "rm",
        "<p>Guests arrive through <b>segments</b> (corporate, leisure, group, wholesale) and <b>channels</b> "
        "(direct web, OTA, group desk, wholesaler). Each has a different rate, cancellation pattern, lead time and "
        "<b>distribution cost</b>. <b>Net ADR</b> = (room revenue − commissions and distribution costs) ÷ rooms "
        "sold. Channel decisions should be made on net ADR and contribution, not gross ADR.</p>",
        "OTAs bring global reach but charge commission (here ~15–18%); direct bookings cost far less.",
        lambda: (f"<pre>Leisure – OTA (year 1)\nRoom nights   {ota_rn:,.0f}\nRevenue       {m(ota_rev)}\n"
                 f"Commission    {m(ota_com)}  ({ota_com / ota_rev * 100:.1f}%)\nGross ADR     {m(ota_rev / ota_rn)}\n"
                 f"Net ADR       {m((ota_rev - ota_com) / ota_rn)}</pre>"),
        Exercise("s3_seg_g", f"The OTA segment's ADR is {m(ota_adr)} and commission is {ota_cp * 100:.1f}% of "
                 "revenue. What is its net ADR?", ota_adr * (1 - ota_cp), "currency",
                 hints=["Net ADR = ADR × (1 − commission %)."],
                 mistakes=[(ota_adr * ota_cp, "net_adr_commission_only", "That is the commission per room, not "
                            "the net rate.")],
                 solution=[f"{ota_adr:,.0f} × (1 − {ota_cp:.3f}) = {ota_adr * (1 - ota_cp):,.2f}"]),
        Exercise("s3_seg_i", f"A direct booking at SAR 1,150 costs 3% in distribution; an OTA booking at "
                 f"{m(ota_adr)} costs {ota_cp * 100:.1f}%. How much more net revenue per room does the direct "
                 "booking bring?", 1150 * 0.97 - ota_adr * (1 - ota_cp), "currency",
                 hints=["Compute both net ADRs, then subtract."],
                 mistakes=[(1150 - ota_adr, "gross_comparison", "Compare NET rates; you compared gross rates.")]),
        "<p><b>Common mistake:</b> celebrating OTA volume growth without checking whether it displaced cheaper "
        "direct bookings (cannibalisation).</p>",
        "<p>Shifting 5% of room nights from OTA to direct can be worth more than a rate increase, with no "
        "demand risk.</p>",
        AppliedTask("Decision Room: complete 'OTA campaign: more bookings, less contribution' with a score of "
                    "60 or more.", "decision", "ota_campaign", 60),
        [Exercise("s3_seg_c1", "Gross ADR 1,000, commission 15%, other distribution cost 2%. Net ADR?", 830.0,
                  "currency", mistakes=[(850.0, "partial_distribution", "Deduct ALL distribution costs.")])],
        page="rm"))

    T.append(Topic(
        "s3_elasticity", 3, "Price elasticity: why a price cut is not automatically profitable", "rm",
        "<p><b>Price elasticity</b> e = % change in demand ÷ % change in price. With e = −0.6, a 10% price cut "
        "raises demand ~6%. Revenue then <i>falls</i> (0.9 × 1.06 = 0.954). Even when revenue rises, profit can "
        "fall because each extra room carries variable costs and capacity may be limited. Aurelia's engine uses "
        "constant-elasticity demand per segment (documented in Model Reference).</p>",
        "Leisure guests are more price-sensitive than corporate travellers; elasticity differs by segment.",
        lambda: ("<pre>Price −10%, elasticity −0.6 → demand × (0.9)^−0.6 = × 1.0653\n"
                 "Revenue factor = 0.9 × 1.0653 = 0.9588 (−4.1%)\n"
                 "Price −10%, elasticity −1.8 → demand × 1.2088; revenue × 1.0879 (+8.8%)</pre>"),
        Exercise("s3_el_g", "Elasticity is −0.6 (constant-elasticity model). Price is cut 10%. By what factor does "
                 "demand change? (e.g. 1.0653)", 0.9 ** -0.6, "number", 0.0005,
                 hints=["Demand factor = (new price ÷ old price) ^ elasticity.", "0.9 ^ −0.6"],
                 mistakes=[(1.06, "elasticity_linear", "1.06 is the linear approximation; the model uses "
                            "(0.9)^−0.6.")]),
        Exercise("s3_el_i", "With elasticity −1.8 and a 10% price cut, by what % does revenue change?",
                 0.9 * 0.9 ** -1.8 - 1, "pct", 0.001,
                 hints=["Revenue factor = price factor × demand factor.", "0.9 × 0.9^−1.8 − 1"],
                 interpretation_q="Revenue rises. Does that mean the price cut is a good idea?",
                 interpretation_points=[("Mentions variable costs / contribution", ("contribution", "variable",
                                                                                     "cost")),
                                        ("Mentions capacity or displacement", ("capacity", "displace", "full"))]),
        "<p><b>Common mistake:</b> assuming higher occupancy means higher profit. Check contribution, "
        "capacity and which segments fill the rooms.</p>",
        "<p>Discounting into high-demand dates gives away rate for nothing; discounting into need periods can "
        "add contribution.</p>",
        AppliedTask("In the Scenario Lab, cut the Leisure – OTA published rate by 10%. Is year-1 EBITDA higher or "
                    "lower than the Base case? The check reads your working draft.", "scenario",
                    check=_check_ota_rate_cut),
        [Exercise("s3_el_c1", "Elasticity −0.5, price +10%. Revenue change (constant elasticity)?",
                  1.1 * 1.1 ** -0.5 - 1, "pct", 0.001)],
        page="rm"))

    T.append(Topic(
        "s3_displacement", 3, "Group displacement analysis", "rm",
        "<p>A group block fills rooms, but on high-demand nights it <b>displaces</b> transient guests who would "
        "have paid more. Value of the group = group room contribution + group F&amp;B contribution − contribution "
        "of displaced transient business. The <b>minimum acceptable rate</b> is the group rate at which the "
        "group adds zero.</p>",
        "Sales teams are paid on revenue; revenue management must defend contribution.",
        lambda: ("<pre>Group: 50 rooms × 3 nights at SAR 800; transient forecast leaves 20 rooms empty per night\n"
                 "Displaced transient: 30 rooms × 3 nights = 90 room nights at SAR 1,200\n"
                 "Group revenue  = 150 × 800  = 120,000\nDisplaced      =  90 × 1,200 = 108,000\n"
                 "Net gain (before F&amp;B and variable costs) = 12,000</pre>"),
        Exercise("s3_dis_g", "60 rooms × 4 nights at SAR 850. Without the group, only 25 rooms per night would stay "
                 "empty; displaced guests would pay SAR 1,300. Net room revenue gain (ignore costs)?",
                 60 * 4 * 850 - 35 * 4 * 1300, "currency",
                 hints=["Displaced rooms per night = 60 − 25.", "Gain = group revenue − displaced revenue."],
                 mistakes=[(60 * 4 * 850, "displacement_ignored", "Deduct the displaced transient revenue.")]),
        Exercise("s3_dis_i", "Same case: what group rate makes the net room revenue gain zero?",
                 35 * 4 * 1300 / (60 * 4), "currency",
                 hints=["Set group revenue = displaced revenue and solve for the rate."]),
        "<p><b>Common mistake:</b> comparing group revenue with zero instead of with the business it displaces.</p>",
        "<p>Offer alternative dates or a higher rate on compressed nights before declining outright.</p>",
        AppliedTask("Decision Room: complete 'Group request during peak week' with a score of 60 or more.",
                    "decision", "group_displacement", 60),
        [Exercise("s3_dis_c1", "Which data matters most for a displacement decision?",
                  "Transient demand forecast on the requested nights", "choice",
                  choices=["Annual occupancy", "Transient demand forecast on the requested nights",
                           "Last year's group revenue", "Depreciation"])],
        page="rm"))

    T.append(Topic(
        "s3_forecast", 3, "Forecast accuracy and bias", "budget",
        "<p><b>MAPE</b> (mean absolute percentage error) measures size of error; <b>bias</b> (mean of forecast − "
        "actual) shows a systematic tendency to over- or under-forecast. A forecast can have a low MAPE and a "
        "persistent bias; bias is the more dangerous because decisions lean in one direction.</p>",
        "Staffing, purchasing and pricing all use the rooms forecast.",
        lambda: "<pre>Forecast 100, 110, 90 vs actual 95, 100, 100\nErrors +5, +10, −10\nAPE 5.3%, 10.0%, 10.0% → "
                "MAPE 8.4%\nBias = (5 + 10 − 10) ÷ 3 = +1.7 rooms</pre>",
        Exercise("s3_fc_g", "Forecast 120, 130, 140; actual 100, 130, 150. MAPE (on actuals)?",
                 (20 / 100 + 0 + 10 / 150) / 3, "pct", 0.001,
                 hints=["APE = |forecast − actual| ÷ actual.", "Average the three APEs."],
                 mistakes=[((20 / 120 + 0 + 10 / 140) / 3, "mape_on_forecast", "Divide by ACTUAL, not by "
                            "forecast.")]),
        Exercise("s3_fc_i", "Same data: bias (mean of forecast − actual)?", (20 + 0 - 10) / 3, "number", 0.01,
                 mistakes=[((20 + 0 + 10) / 3, "bias_absolute", "Bias keeps the sign; absolute values hide it.")]),
        "<p><b>Common mistake:</b> averaging signed errors and calling it accuracy: +10 and −10 average to 0.</p>",
        "<p>A positive bias in the rooms forecast means overstaffing and over-ordering every month.</p>",
        AppliedTask("Revenue page → Forecast accuracy: read the MAPE for the selected comparison and enter it.",
                    "exercise"),
        [Exercise("s3_fc_c1", "Which measure reveals systematic over-forecasting?", "Bias", "choice",
                  choices=["MAPE", "Bias", "MAE", "RevPAR"])],
        page="rm"))
    T[-1].applied.exercise = _mape_exercise()

    # ================================================================ STAGE 4
    T.append(Topic(
        "s4_variance", 4, "Variance analysis and favourability", "fpa",
        "<p>Variance = actual − budget. Whether it is <b>favourable</b> depends on the line: more revenue is "
        "usually favourable, more cost usually unfavourable. Context matters: higher variable costs because the "
        "hotel was busier can be a good sign, so always compare against a <b>flexed</b> budget too. "
        "<b>Materiality</b> thresholds (here SAR 250k and 5%) focus attention on what matters.</p>",
        "The monthly management report explains every material variance with evidence.",
        _worked_variance,
        Exercise("s4_var_g", "Utilities budget SAR 1,900,000; actual SAR 2,040,000. Variance and verdict?",
                 "+140,000 unfavourable", "choice",
                 choices=["+140,000 favourable", "+140,000 unfavourable", "−140,000 favourable",
                          "−140,000 unfavourable"],
                 mistakes=[("+140,000 favourable", "favourability_cost", "For a cost, spending more than budget "
                            "is unfavourable.")]),
        Exercise("s4_var_i", "Is a variance of SAR 300,000 on a budget of SAR 8,000,000 material under a rule of "
                 "'≥ SAR 250k AND ≥ 5%'?", "No", "choice", choices=["Yes", "No"],
                 mistakes=[("Yes", "materiality_and", "300k ÷ 8m = 3.75% < 5%: both tests must be met.")]),
        "<p><b>Common mistake:</b> treating the sign of the variance as the verdict.</p>",
        "<p>A material unfavourable variance needs an owner, an explanation backed by data and an action.</p>",
        AppliedTask("Complete '02 Variance Analysis' (Variance tab) and grade it (≥ 70%).", "workbook", "variance"),
        [Exercise("s4_var_c1", "Revenue 5% above budget and commission costs 12% above budget. Which is TRUE?",
                  "Commission variance may be partly explained by higher volume", "choice",
                  choices=["Both variances are favourable", "Commission variance may be partly explained by "
                           "higher volume", "Commission variance must be fraud", "Revenue variance is unfavourable"])],
        page="fpa"))

    T.append(Topic(
        "s4_flex", 4, "Flexible budgets", "fpa",
        "<p>A <b>flexible budget</b> restates the budget at the actual level of activity: fixed costs stay, "
        "variable costs = budget rate × actual activity. The difference between actual and flexed budget is the "
        "<b>spending (efficiency) variance</b>; the difference between flexed and static budget is the "
        "<b>activity variance</b>.</p>",
        "Department heads should be judged on spending variances, not on volume they do not control.",
        lambda: "<pre>Budget: 30% food cost on SAR 20.0m F&amp;B revenue = 6.0m\nActual revenue 20.3m → flexed "
                "cost 6.09m\nActual cost 6.24m → spending variance 0.15m U; activity variance 0.09m U</pre>",
        Exercise("s4_flex_g", "Budget food cost is 30% of F&B revenue. Actual F&B revenue SAR 20,300,000; actual "
                 "food cost SAR 6,240,000. What is the flexed budget cost?", 0.30 * 20_300_000, "currency",
                 hints=["Flexed budget = budget rate × actual activity."],
                 mistakes=[(6_240_000.0, "flex_actual", "That is the actual cost.")]),
        Exercise("s4_flex_i", "Same data: spending variance (actual − flexed)?", 6_240_000 - 0.30 * 20_300_000,
                 "currency", mistakes=[(6_240_000 - 6_000_000, "static_comparison", "Compare with the FLEXED "
                                        "budget (6.09m), not the static one.")]),
        "<p><b>Common mistake:</b> blaming a department for a cost overrun that is entirely volume-driven.</p>",
        "<p>Spending variances point to price, waste or productivity — things a manager can act on.</p>",
        AppliedTask("Complete the flexible-budget section of '02 Variance Analysis' (Bridge tab) and grade it.",
                    "workbook", "variance"),
        [Exercise("s4_flex_c1", "Which cost stays the same in a flexed budget?", "Insurance", "choice",
                  choices=["Food cost", "Commission", "Insurance", "Guest supplies"])],
        page="fpa"))

    T.append(Topic(
        "s4_pvm", 4, "Price, volume and mix variances", "fpa",
        "<p>Rooms revenue variance splits into a <b>rate (price) variance</b> = (actual ADR − budget ADR) × actual "
        "rooms, and a <b>volume variance</b> = (actual rooms − budget rooms) × budget ADR. With segments, a "
        "<b>mix</b> variance isolates the effect of selling a different proportion of high- and low-rated "
        "segments. The parts always add up to the total.</p>",
        "This is how 'occupancy above budget but revenue below expectations' gets explained.",
        lambda: "<pre>Budget 1,000 rooms × 900; actual 1,100 × 870\nRate   = (870 − 900) × 1,100 = −33,000\n"
                "Volume = (1,100 − 1,000) × 900 = +90,000\nTotal  = 957,000 − 900,000 = +57,000 ✓</pre>",
        Exercise("s4_pvm_g", "Budget 2,000 rooms at SAR 1,000; actual 2,100 rooms at SAR 960. Rate variance?",
                 (960 - 1000) * 2100, "currency",
                 hints=["Rate variance uses ACTUAL rooms."],
                 mistakes=[((960 - 1000) * 2000, "rate_at_budget_volume", "Use actual rooms (2,100).")]),
        Exercise("s4_pvm_i", "Same data: volume variance?", (2100 - 2000) * 1000, "currency",
                 mistakes=[((2100 - 2000) * 960, "volume_at_actual_rate", "Volume variance uses the BUDGET rate.")]),
        "<p><b>Common mistake:</b> using the same basis twice so the parts do not add up to the total.</p>",
        "<p>A negative rate variance with a positive volume variance often means discounting bought volume — "
        "check whether contribution rose.</p>",
        AppliedTask("Complete the rate/volume bridge in '02 Variance Analysis' (tasks 2.11–2.15) and grade it.",
                    "workbook", "variance"),
        [Exercise("s4_pvm_c1", "Rate + volume variance must equal…", "The total revenue variance", "choice",
                  choices=["Zero", "The total revenue variance", "The mix variance", "Budget revenue"])],
        page="fpa"))

    # ================================================================ STAGE 5
    bud_rev = 148 * 365 * 0.75 * 1100
    T.append(Topic(
        "s5_budget", 5, "Driver-based budgeting", "budget",
        "<p>A <b>driver-based budget</b> builds revenue and cost from operating drivers (rooms, occupancy, ADR, "
        "covers, average check, headcount, wage rates) instead of 'last year + 5%'. Each driver has an owner and "
        "an evidence base, and the budget can be re-run when a driver changes.</p>",
        "Aurelia's Base case is a driver-based budget: every line traces to drivers in the Scenario Lab.",
        lambda: f"<pre>Rooms revenue = 148 rooms × 365 nights × 75% × SAR 1,100 = {m(bud_rev)}</pre>" + _worked_budget(),
        Exercise("s5_bud_g", "148 available rooms, 365 nights, 75% occupancy, ADR SAR 1,100. Annual rooms revenue?",
                 bud_rev, "currency", mistakes=[(150 * 365 * 0.75 * 1100, "physical_rooms", "Use available rooms.")]),
        Exercise("s5_bud_i", "Breakfast capture 75% of guests, 1.6 guests per occupied room, average check SAR 140. "
                 "Breakfast revenue per occupied room night?", 0.75 * 1.6 * 140, "currency",
                 hints=["Covers per occupied room = guests per room × capture."]),
        "<p><b>Common mistake:</b> incremental budgeting that carries last year's inefficiencies forward.</p>",
        "<p>Driver-based budgets make the conversation about assumptions, which is where it belongs.</p>",
        AppliedTask("In the Scenario Lab, save a scenario named 'My budget' with at least one changed driver.",
                    "scenario", check=_check_my_budget),
        [Exercise("s5_bud_c1", "Which is a driver, not an output?", "F&B average check", "choice",
                  choices=["GOP", "F&B average check", "EBITDA", "Net income"])],
        page="lab"))

    T.append(Topic(
        "s5_rolling", 5, "Rolling forecasts and the latest estimate", "budget",
        "<p>The <b>latest estimate (LE)</b> for the year = actuals to date + forecast for the remaining months. "
        "A <b>rolling forecast</b> always looks 12 months ahead, crossing the year end. The <b>run-rate</b> "
        "(YTD ÷ months × 12) ignores seasonality and is only a rough cross-check.</p>",
        "Owners want to know where the year will land, not only how the year started.",
        lambda: "<pre>YTD actual (9 months) 13.1m; forecast Oct–Dec 6.2m → LE 19.3m\n"
                "Run-rate = 13.1 ÷ 9 × 12 = 17.5m (misleading: Q4 is high season)</pre>",
        Exercise("s5_rf_g", "YTD EBITDA after 9 months is SAR 13,100,000; the forecast for the last 3 months is SAR "
                 "6,200,000. Latest estimate?", 19_300_000.0, "currency",
                 mistakes=[(13_100_000 / 9 * 12, "run_rate_as_le", "That is the run-rate, which ignores "
                            "seasonality.")]),
        Exercise("s5_rf_i", "Same data: run-rate estimate?", 13_100_000 / 9 * 12, "currency"),
        "<p><b>Common mistake:</b> presenting a run-rate as a forecast in a seasonal business.</p>",
        "<p>Version and approve forecasts: decisions need to know which numbers were current when.</p>",
        AppliedTask("FP&A Lab → Forecast versions: save a forecast version and approve it.", "scenario",
                    check=_check_forecast_approved),
        [Exercise("s5_rf_c1", "A rolling 12-month forecast made in October covers…", "Nov this year to Oct next year",
                  "choice", choices=["Jan–Dec this year", "Nov this year to Oct next year", "Only Q4",
                                     "Next calendar year"])],
        page="fpa"))

    # ================================================================ STAGE 6
    T.append(Topic(
        "s6_three", 6, "How the three statements link", "statements",
        "<p>Net income flows into <b>retained earnings</b>. Depreciation reduces profit but not cash, so it is "
        "added back in operating cash flow. Changes in working capital (receivables, payables, inventory) move "
        "cash without touching profit. Capex is investing cash flow and increases fixed assets; debt drawdowns "
        "and repayments are financing cash flow. Closing cash = opening cash + CFO + CFI + CFF, and the balance "
        "sheet must balance every month.</p>",
        "Aurelia runs this loop monthly for 36 months; Statements → Integrity checks proves it balances.",
        lambda: (f"<pre>Opening cash   {m(y['cash_open'])}\n+ CFO          {m(y['cfo'])}\n+ CFI          "
                 f"{m(y['cfi'])}\n+ CFF          {m(y['cff'])}\n= Closing cash {m(y['cash_close'])}</pre>"),
        Exercise("s6_3s_g", f"Opening cash {m(R(y['cash_open']))}, CFO {m(R(y['cfo']))}, CFI {m(R(y['cfi']))}, CFF "
                 f"{m(R(y['cff']))}. Closing cash?", R(y["cash_open"]) + R(y["cfo"]) + R(y["cfi"]) + R(y["cff"]),
                 "currency", mistakes=[(R(y["cash_open"]) + R(y["cfo"]) - R(y["cfi"]) - R(y["cff"]),
                                         "cash_sign", "CFI and CFF are already negative numbers: add them.")]),
        Exercise("s6_3s_i", "Net income SAR 2,000,000, depreciation SAR 1,500,000, receivables up SAR 400,000, "
                 "payables up SAR 100,000. CFO?", 2_000_000 + 1_500_000 - 400_000 + 100_000, "currency",
                 mistakes=[(2_000_000 + 1_500_000 + 400_000 + 100_000, "wc_sign", "An increase in receivables "
                            "uses cash: subtract it."),
                           (2_000_000 - 400_000 + 100_000, "depreciation_not_added", "Add back depreciation: it is "
                            "a non-cash expense.")]),
        "<p><b>Common mistake:</b> treating profit as cash.</p>",
        "<p>A profitable hotel can run out of cash through slow collections, capex and debt repayments.</p>",
        AppliedTask("Grade '03 Three-Statement Mini Model' at 70% or more.", "workbook", "three_statement"),
        [Exercise("s6_3s_c1", "Depreciation increases by SAR 100k (tax 20%). Effect on cash?", 20_000.0,
                  "currency", mistakes=[(0.0, "tax_shield", "Depreciation is non-cash but reduces tax paid: "
                                         "+20k."), (-100_000.0, "dep_cash", "Depreciation is not a cash outflow.")])],
        page="statements"))

    T.append(Topic(
        "s6_wc", 6, "Working capital and cash conversion", "statements",
        "<p>Receivables ≈ credit sales × DSO ÷ days; payables ≈ purchases × DPO ÷ days. Higher DSO ties up cash; "
        "higher DPO funds the business with supplier credit (within agreed terms). <b>Cash conversion</b> = CFO ÷ "
        "EBITDA shows how much profit turns into cash.</p>",
        "Corporate and group accounts are invoiced on credit; leisure guests pay on departure.",
        lambda: "<pre>Credit sales SAR 4.5m per month, DSO 45 days → receivables ≈ 4.5m × 45 ÷ 30 = 6.75m\n"
                "DSO 55 → 8.25m: 1.5m more cash tied up</pre>",
        Exercise("s6_wc_g", "Monthly credit sales SAR 4,500,000. How much cash is released if DSO falls from 55 to 45 "
                 "days (30-day months)?", 4_500_000 * 10 / 30, "currency",
                 hints=["Receivables = credit sales × DSO ÷ 30.", "Compare the two balances."]),
        Exercise("s6_wc_i", "EBITDA SAR 23.2m, CFO SAR 12.1m. Cash conversion?", 12.1 / 23.2, "pct", 0.001),
        "<p><b>Common mistake:</b> stretching supplier payments beyond terms to make cash look better — it "
        "damages supply and pricing.</p>",
        "<p>A 10-day DSO improvement is often worth more cash than a year of cost cutting.</p>",
        AppliedTask("Decision Room: complete 'Cash falling despite operating profit' with a score of 60 or more.",
                    "decision", "cash_squeeze", 60),
        [Exercise("s6_wc_c1", "Which change releases cash?", "Lower DSO", "choice",
                  choices=["Higher DSO", "Lower DSO", "Lower DPO", "Higher inventory days"])],
        page="workbench"))

    # ================================================================ STAGE 7
    flows = [-1_000_000, 400_000, 450_000, 500_000]
    npv10 = fin.npv(0.10, flows)
    T.append(Topic(
        "s7_npv", 7, "NPV and IRR", "invest",
        "<p><b>NPV</b> discounts each future cash flow at the required return and subtracts the investment: "
        "positive NPV creates value. <b>IRR</b> is the rate that makes NPV zero; it can be misleading with "
        "unusual cash-flow patterns (several sign changes → several IRRs, or none) and when comparing projects of "
        "different size. NPV is the primary rule; IRR, MIRR and payback support it.</p>",
        "Every capital request at the Aurelia Grand needs an NPV on incremental, after-tax cash flows.",
        lambda: (f"<pre>Cash flows −1,000,000 / 400,000 / 450,000 / 500,000 at 10%\nNPV = −1,000,000 + 400,000/1.1 + "
                 f"450,000/1.21 + 500,000/1.331 = {npv10:,.0f}\nIRR = {fin.irr(flows).value * 100:.2f}%</pre>"),
        Exercise("s7_npv_g", "Cash flows: −1,000,000 now, then 400,000, 450,000 and 500,000. NPV at 10%?", npv10,
                 "currency", hints=["Discount year t by 1.1^t.", "Year 0 is not discounted."],
                 mistakes=[(npv10 / 1.1, "npv_year0_discounted", "Year 0 is not discounted (Excel's NPV() "
                            "discounts its first value).")]),
        Exercise("s7_npv_i", "Same cash flows. IRR (to 0.1%)?", fin.irr(flows).value, "pct", 0.001,
                 hints=["Find the rate where NPV = 0: try 15%, then 20%."]),
        "<p><b>Common mistake:</b> putting year 0 inside Excel's NPV() function.</p>",
        "<p>A higher IRR does not make a project better if it creates less value (NPV) — scale matters.</p>",
        AppliedTask("Grade '04 Investment Appraisal' at 70% or more.", "workbook", "investment"),
        [Exercise("s7_npv_c1", "Cash flows −100, +230, −132. How many IRRs can there be?", "Up to two", "choice",
                  choices=["Exactly one", "Up to two", "None ever", "Infinite"])],
        page="invest"))

    T.append(Topic(
        "s7_payback", 7, "Payback, discounted payback and profitability index", "invest",
        "<p><b>Payback</b> = time to recover the investment from undiscounted cash flows; <b>discounted "
        "payback</b> uses discounted flows. Both ignore cash after the cut-off, so they measure risk/liquidity, "
        "not value. <b>Profitability index</b> = PV of future flows ÷ investment; useful when capital is "
        "rationed.</p>",
        "Owners often ask 'when do we get our money back?' — answer it, then show NPV.",
        lambda: "<pre>−1,000,000 / 400,000 / 450,000 / 500,000\nCumulative: −600,000 → −150,000 → +350,000\n"
                "Payback = 2 + 150,000 ÷ 500,000 = 2.3 years</pre>",
        Exercise("s7_pb_g", "Same cash flows. Payback in years?", 2.3, "number", 0.001,
                 mistakes=[(3.0, "payback_whole_year", "Interpolate within year 3.")]),
        Exercise("s7_pb_i", "Same cash flows at 10%. Profitability index?", (npv10 + 1_000_000) / 1_000_000,
                 "number", 0.001, mistakes=[(npv10 / 1_000_000, "pi_npv", "PI uses the PV of inflows, not NPV.")]),
        "<p><b>Common mistake:</b> rejecting a positive-NPV project only because payback is long.</p>",
        "<p>Use payback as a risk screen and NPV as the decision rule.</p>",
        AppliedTask("Decision Room: complete 'Room refurbishment approval' with a score of 60 or more.", "decision",
                    "renovation", 60),
        [Exercise("s7_pb_c1", "Which ignores the time value of money?", "Simple payback", "choice",
                  choices=["NPV", "IRR", "Simple payback", "Discounted payback"])],
        page="invest"))

    T.append(Topic(
        "s7_sensitivity", 7, "Sensitivity, scenarios and Monte Carlo", "invest",
        "<p><b>Sensitivity</b> changes one input at a time to see which drives the result most (tornado). "
        "<b>Scenarios</b> change several inputs together into a coherent story (base, upside, downside). "
        "<b>Monte Carlo</b> samples many inputs from distributions to show a range — but the range is only as good "
        "as the distributions you assume. None of these predicts the future.</p>",
        "Investment committees want the break-even assumption: 'how wrong can we be before NPV turns negative?'",
        _worked_sensitivity,
        Exercise("s7_sens_g", "A tornado shows: OTA commission ±10% moves EBITDA ±0.3m; ADR ±10% moves it ±4.1m; "
                 "energy price ±10% moves it ±0.2m. Which driver deserves most analysis effort?", "ADR", "choice",
                 choices=["OTA commission", "ADR", "Energy price", "All equally"]),
        Exercise("s7_sens_i", "NPV is +2.0m at a 6% rate uplift and falls by 0.5m for every 1-point reduction in the "
                 "uplift. What uplift gives NPV = 0?", 2.0, "number", 0.001,
                 hints=["2.0m ÷ 0.5m per point = 4 points.", "6% − 4 points."]),
        "<p><b>Common mistake:</b> presenting the Monte Carlo P50 as 'the forecast'.</p>",
        "<p>Report ranges and the assumptions that drive them; decide what you would monitor.</p>",
        AppliedTask("Decision Room: complete 'Forecast revision after a demand shock' with a score of 60 or more.",
                    "decision", "demand_shock", 60),
        [Exercise("s7_sens_c1", "Which statement is correct?", "Monte Carlo results depend on the assumed "
                  "distributions", "choice", choices=["Monte Carlo predicts the future", "Monte Carlo results "
                                                      "depend on the assumed distributions",
                                                      "Scenarios are statistical forecasts",
                                                      "Sensitivity changes all inputs at once"])],
        page="risk"))

    # ================================================================ STAGE 8
    T.append(Topic(
        "s8_partner", 8, "Business partnering: challenging a budget request", "judgement",
        "<p>Finance partners help managers make good decisions. A request for money needs: the problem, the "
        "expected return with its key assumption, the break-even, how success will be measured and when, and a "
        "way to stop if it is not working. A <b>pilot with a stop/go gate</b> buys evidence cheaply.</p>",
        "The Spa Manager wants SAR 600k of marketing with no evidence of return.",
        lambda: "<pre>Contribution per extra treatment ≈ 650 × (1 − 8% − 10%) = 533\nBreak-even extra treatments = "
                "600,000 ÷ 533 ≈ 1,126 a year ≈ 3.1 a day</pre>",
        Exercise("s8_bp_g", "Marketing spend SAR 600,000; contribution per extra treatment SAR 533. Break-even "
                 "extra treatments per year?", 600_000 / 533, "number", 0.002),
        Exercise("s8_bp_i", "External treatments are 6 a day today. What % increase is needed to break even "
                 "(365 days)?", (600_000 / 533 / 365) / 6, "pct", 0.002),
        "<p><b>Common mistake:</b> approving or declining on gut feel instead of the break-even.</p>",
        "<p>Saying 'yes, if…' with a measurable condition builds trust better than 'no'.</p>",
        AppliedTask("Decision Room: complete 'Spa asks for budget without evidence' with a score of 60 or more.",
                    "decision", "budget_request", 60),
        [Exercise("s8_bp_c1", "Best first response to an unevidenced budget request?", "Ask for the expected "
                  "return, break-even and how it will be measured", "choice",
                  choices=["Approve to keep the relationship", "Decline", "Ask for the expected return, break-even "
                           "and how it will be measured", "Escalate to the owner"])],
        page="decisions"))

    T.append(Topic(
        "s8_channel", 8, "Commercial judgement: occupancy up, EBITDA down", "judgement",
        "<p>When volume rises and profit falls, look for: lower net rate (discounts, mix shift to low-rated "
        "segments or costly channels), cost overruns not explained by volume (flexed budget), and one-off items. "
        "Quantify each driver, separate evidence from hypotheses, then act on the drivers.</p>",
        "This is the Aurelia Grand's actual situation in the FP&A Lab (close month September).",
        _worked_channel,
        Exercise("s8_ch_g", "Occupancy is above budget and EBITDA below. Which is NOT a plausible driver?",
                 "Depreciation increased", "choice",
                 choices=["OTA mix and commission increased", "Food cost ratio rose", "Overtime increased",
                          "Depreciation increased"],
                 mistakes=[(c, "ebitda_drivers", "That one can lower EBITDA while occupancy rises, so it is "
                            "plausible. Look for the item that sits below EBITDA.")
                           for c in ("OTA mix and commission increased", "Food cost ratio rose",
                                     "Overtime increased")]),
        Exercise("s8_ch_i", "OTA room nights rose 4,000 at net ADR SAR 900 vs direct net ADR SAR 1,100. If 1,500 of "
                 "them would have booked direct anyway, what is the net revenue gain?",
                 2500 * 900 - 1500 * (1100 - 900), "currency",
                 hints=["Incremental nights: 2,500 × 900.", "Cannibalised: 1,500 × (1,100 − 900) lost."]),
        "<p><b>Common mistake:</b> stating a cause ('the campaign failed') when the data shows only a "
        "correlation.</p>",
        "<p>Evidence first, hypotheses labelled, actions owned.</p>",
        AppliedTask("Decision Room: complete 'Occupancy above budget, EBITDA below' with a score of 60 or more.",
                    "decision", "fpa_gap", 60),
        [Exercise("s8_ch_c1", "Data shows spa revenue fell while occupancy rose. The correct statement is…",
                  "Spa capture fell; the cause needs confirming", "choice",
                  choices=["Guests dislike the spa", "Spa capture fell; the cause needs confirming",
                           "The spa manager underperformed", "Prices are too high"])],
        page="fpa"))

    T.append(Topic(
        "s8_group", 8, "Multi-property expansion and consolidation", "invest",
        "<p>Buying a second hotel is an investment decision (NPV of the acquisition) and a reporting change "
        "(group consolidation: sum the hotels' results, eliminate intercompany items, add group overheads). The "
        "Investment page evaluates the fictional Aurelia Oasis Resort acquisition and shows a consolidated view.</p>",
        "Aurelia Hospitality Group is considering an 80-room resort.",
        _worked_group,
        Exercise("s8_grp_g", "Grand EBITDA SAR 23.2m, Oasis EBITDA SAR 6.1m, group overheads SAR 1.2m, intercompany "
                 "management charge SAR 0.4m (income at Grand, cost at Oasis). Group EBITDA?", 23.2e6 + 6.1e6 - 1.2e6,
                 "currency", mistakes=[(23.2e6 + 6.1e6 - 1.2e6 + 0.4e6, "intercompany", "Intercompany charges net "
                                        "to zero in the group; do not add them.")]),
        Exercise("s8_grp_i", "Purchase price SAR 105m; PV of future cash flows SAR 107m. NPV?", 2e6, "currency"),
        "<p><b>Common mistake:</b> adding intercompany revenue to group revenue.</p>",
        "<p>A small positive NPV on a large deal is fragile: test the key assumption before committing.</p>",
        AppliedTask("Investment page → 'Acquire Aurelia Oasis Resort': enter the NPV shown for the default "
                    "assumptions.", "exercise"),
        [Exercise("s8_grp_c1", "In consolidation, intercompany sales are…", "Eliminated", "choice",
                  choices=["Added twice", "Eliminated", "Shown as other income", "Ignored only if small"])],
        page="invest"))
    T[-1].applied.exercise = _oasis_exercise()

    # ================================================================ STAGE 9
    T.append(Topic(
        "s9_comm", 9, "Writing an executive recommendation", "comms",
        "<p>Lead with the recommendation. Then the two or three numbers that justify it, the key assumption and "
        "risk, and the next step with an owner and date. 40–180 words. Avoid jargon; never hide uncertainty.</p>",
        "The owner reads the first two lines; the GM reads the rest.",
        lambda: "<pre>Recommend: renegotiate the OTA promotion, restore food cost to 30% and cap overtime.\n"
                "Why: these three drivers explain SAR 1.6m of the EBITDA gap over 12 months.\n"
                "Risk: OTA may refuse; fallback is to end the promotion (≈ SAR 1.1m).\n"
                "Next: Revenue Director to report OTA response by 15 Nov.</pre>",
        Exercise("s9_cm_g", "Which opening sentence is best?", "I recommend we renegotiate the OTA promotion; it "
                 "recovers SAR 1.6m of EBITDA over 12 months.", "choice",
                 choices=["Following a detailed review of the variance tables, several observations emerged.",
                          "I recommend we renegotiate the OTA promotion; it recovers SAR 1.6m of EBITDA over 12 "
                          "months.", "Results were mixed this month.", "Please see the attached analysis."]),
        Exercise("s9_cm_i", "Which element is missing: 'I recommend phasing the refurbishment. NPV improves to "
                 "SAR 0.36m and displacement halves.'", "Risk and next step", "choice",
                 choices=["The recommendation", "Numbers", "Risk and next step", "Nothing"]),
        "<p><b>Common mistake:</b> narrating the analysis chronologically instead of leading with the answer.</p>",
        "<p>Clear writing is a commercial skill: decisions are made on what executives understand.</p>",
        AppliedTask("Decision Room: complete any case with a Communication score of at least 0.7.", "decision",
                    "*comms", 70),
        [Exercise("s9_cm_c1", "An executive justification should be about…", "40–180 words", "choice",
                  choices=["10 words", "40–180 words", "500 words", "As long as needed"])],
        page="decisions"))

    T.append(Topic(
        "s9_defend", 9, "Defending a recommendation under challenge", "comms",
        "<p>When challenged: acknowledge the goal behind the challenge, restate the evidence, quantify the "
        "alternative, and offer a fenced test that meets the goal without the main risk. Escalation without new "
        "evidence rarely helps.</p>",
        "The GM wants occupancy; you want profit. A fenced test can serve both.",
        _worked_defend,
        Exercise("s9_df_g", "Best first move when the GM rejects your analysis in a meeting?",
                 "Acknowledge the goal and show the numbers behind your view", "choice",
                 choices=["Concede to avoid conflict", "Acknowledge the goal and show the numbers behind your view",
                          "Escalate to the owner", "Repeat your conclusion more firmly"]),
        Exercise("s9_df_i", "Which counter-proposal best limits downside?", "A capped test with a review date",
                 "choice", choices=["Do it everywhere immediately", "A capped test with a review date",
                                    "Do nothing", "Let the GM decide alone"]),
        "<p><b>Common mistake:</b> treating the challenge as personal rather than as a request for evidence.</p>",
        "<p>Your credibility comes from being right about the numbers and flexible about the route.</p>",
        AppliedTask("Decision Room: complete 'The GM challenges your recommendation' with a score of 60 or more.",
                    "decision", "manager_challenge", 60),
        [Exercise("s9_df_c1", "A 'fenced' test means…", "Limited in scope with conditions and a review",
                  "choice", choices=["Unlimited", "Limited in scope with conditions and a review",
                                     "Secret", "Approved by the owner only"])],
        page="decisions"))

    T.append(Topic(
        "s9_capstone", 9, "Integrated capstone", "judgement",
        "<p>The capstone brings everything together on a messy but recoverable dataset: validate the data, build "
        "KPIs, reconcile actuals to budget, forecast, build an integrated analysis, evaluate two competing "
        "decisions, quantify risk, prepare a dashboard, write the recommendation and defend it in a simulated "
        "meeting.</p>",
        "This is the closest the simulator gets to a real month-end and board pack.",
        _worked_capstone,
        Exercise("s9_cap_g", "In a messy dataset, a row has occupied rooms 162 for a 148-room night. Best action?",
                 "Flag it, exclude or cap it, and document the adjustment", "choice",
                 choices=["Keep it", "Delete the whole file", "Flag it, exclude or cap it, and document the "
                          "adjustment", "Replace it with the average silently"]),
        Exercise("s9_cap_i", "Two duplicate rows of SAR 50,000 revenue each were found in a month total of SAR "
                 "4,050,000 (one duplicate is genuine). Corrected total?", 4_000_000.0, "currency"),
        "<p><b>Common mistake:</b> 'cleaning' data without documenting what was changed and why.</p>",
        "<p>Data validation is part of the analysis, not a chore before it.</p>",
        AppliedTask("Complete the Capstone with an overall score of 60 or more.", "capstone", "capstone", 60),
        [Exercise("s9_cap_c1", "Which is NOT a data-validation check?", "Calculating NPV", "choice",
                  choices=["Duplicates", "Missing values", "Impossible values", "Calculating NPV"])],
        page="capstone"))
    return T


# --------------------------------------------------------------------------- applied checks & exercises
def _check_revpar_and_ebitda(state):
    base = simulate_cached(state.store.get("Base case").assumptions)
    cur = state.result
    sl = base.year_slice(1)
    kb, kc = base.kpis(sl), cur.kpis(sl)
    up = (kc["revpar"] or 0) / (kb["revpar"] or 1) - 1
    de = (kc["ebitda"] or 0) - (kb["ebitda"] or 0)
    ok = up >= 0.03 and de > 0
    return ok, (f"RevPAR {up * 100:+.1f}% and EBITDA {de:+,.0f} vs Base case (year 1). " +
                ("Passed." if ok else "Need RevPAR ≥ +3% AND EBITDA higher."))


def _check_ota_rate_cut(state):
    base_a = state.store.get("Base case").assumptions
    cur_a = state.draft
    rb, rc = base_a["segments"]["leisure_ota"]["published_rate"], cur_a["segments"]["leisure_ota"]["published_rate"]
    if abs(rc / rb - 0.9) > 0.01:
        return False, f"The Leisure – OTA published rate is {rc:,.0f} vs {rb:,.0f} in the Base case: cut it by 10%."
    base, cur = simulate_cached(base_a), state.result
    sl = base.year_slice(1)
    d = cur.total("ebitda", sl) - base.total("ebitda", sl)
    return True, (f"Done. Year-1 EBITDA changed by {d:+,.0f}. Occupancy changed by "
                  f"{(cur.kpis(sl)['occupancy'] - base.kpis(sl)['occupancy']) * 100:+.1f} points. "
                  "Explain why in the interpretation box.")


def _check_my_budget(state):
    names = state.store.names()
    if "My budget" not in names:
        return False, "No scenario named 'My budget' yet (Scenario Lab → Save as…)."
    from ..model.assumptions import diff as _diff
    changed = _diff(baseline(), state.store.get("My budget").assumptions)
    return (bool(changed), f"'My budget' differs from the baseline in {len(changed)} driver(s)."
            if changed else "'My budget' is identical to the baseline: change at least one driver.")


def _check_forecast_approved(state):
    row = state.db.one("SELECT COUNT(*) AS n FROM forecast_versions WHERE status = 'Approved'")
    n = int(row["n"]) if row else 0
    return n > 0, (f"{n} approved forecast version(s) found." if n else "No approved forecast version yet.")


def _unit_breakeven_exercise() -> Exercise:
    from ..analysis.sensitivity import operating_leverage
    from ..core.kpis import safe_div
    r = simulate_cached(baseline())
    sl = r.year_slice(1)
    ol = operating_leverage(r, sl)
    cpr = safe_div(ol["contribution"], r.total("occupied_rooms", sl))
    be = safe_div(safe_div(ol["fixed_costs"], cpr), r.total("available_rooms", sl))
    return Exercise("s1_con_a", "Break-even occupancy (EBITDA = 0) for the Base case, year 1, from Modelling "
                    "Workbench → H. Unit economics (period: Year 1).", float(be or 0), "pct", 0.003)


def _mape_exercise() -> Exercise:
    from ..analysis.rm import forecast_accuracy
    from ..analysis.fpa import actual_world_assumptions
    b, a = simulate_cached(baseline()), simulate_cached(actual_world_assumptions())
    fa = forecast_accuracy(a.s("occupied_rooms")[:9], b.s("occupied_rooms")[:9])
    return Exercise("s3_fc_a", "Revenue page → Forecast accuracy (close month September, budget = Base case): MAPE "
                    "of the budget room-night forecast against actuals.", float(fa["MAPE"]), "pct", 0.002)


def _oasis_exercise() -> Exercise:
    from ..analysis import investment as inv
    ev = inv.run_case("expansion", baseline())
    return Exercise("s8_grp_a", "NPV of the Aurelia Oasis acquisition at default assumptions (Base case).",
                    float(ev.npv), "currency", 0.01)


# --------------------------------------------------------------------------- engine-backed worked examples
def _worked_lookup() -> str:
    import pandas as pd
    d = simulate_cached(baseline()).daily
    row = d[d["date"] == pd.Timestamp(2027, 2, 14)].iloc[0]
    rev = sum(float(row[c]) for c in d.columns if c.endswith("_revenue"))
    return ("<pre>=XLOOKUP(DATE(2027,2,14), Daily!A:A, Daily!D:D, 0)\n"
            "=INDEX(Daily!D:D, MATCH(DATE(2027,2,14), Daily!A:A, 0))\n=IFERROR(D5/D6, 0)</pre>"
            f"<p>In the baseline, 14 February 2027 has {row['occupied']:,.0f} occupied rooms and room revenue of "
            f"{m(rev)}; both lookups return that revenue from the Daily tab. The trailing 0 in XLOOKUP and MATCH "
            "asks for an exact match: without it a sorted-range approximate match can silently return the wrong "
            "day. IFERROR belongs around a known, harmless case such as a zero denominator, never around a lookup "
            "you have not checked.</p>")


def _worked_model() -> str:
    y = _y1()
    rn = y["occupied_rooms"]
    a = baseline()["rooms_costs"]
    per = a["housekeeping_per_occupied_room"] + a["guest_supplies_per_occupied_room"] + a["laundry_per_occupied_room"]
    r = simulate_cached(baseline())
    failed = [c.name for c in r.checks if not c.passed]
    return (f"<p>One driver flowing through the model (year 1, fictional baseline):</p><pre>"
            f"INPUT   housekeeping + supplies + laundry per occupied room   SAR {per:,.2f}\n"
            f"CALC    occupied rooms (from demand, rate and capacity)        {rn:,.0f}\n"
            f"CALC    variable rooms cost ≈ {per:,.2f} × {rn:,.0f}           = {m(per * rn)}\n"
            f"OUTPUT  flows into Rooms departmental profit → GOP → EBITDA → cash</pre>"
            f"<p>Checks on this run: {len(r.checks) - len(failed)} of {len(r.checks)} passed "
            f"(balance sheet balances, cash reconciles, segments sum to totals…). Modelling Workbench → Dependency "
            f"viewer shows the same chain for every line.</p>")


def _worked_variance() -> str:
    from ..analysis.fpa import build_fpa, actual_world_assumptions
    f = build_fpa(baseline(), actual_world_assumptions())
    v = f.variance_table("ytd")
    rows = v[v["key"].isin(["rooms_revenue", "spa_revenue", "commissions", "fnb_labour"])]
    lines = [f"{r.Line:<28} actual {r.Actual / 1e6:6.2f}m  budget {r.Budget / 1e6:6.2f}m  "
             f"variance {r.Variance / 1e6:+6.2f}m  {r._8}" for r in rows.itertuples()]
    return ("<p>YTD September, fictional 'actual' world against the Base-case budget:</p><pre>" + "\n".join(lines) +
            "</pre><p>Room revenue is <b>above</b> budget (favourable: more revenue). Commissions are also above "
            "budget, but for a cost line that is <b>unfavourable</b>. The sign alone never decides the verdict: "
            "read it with the nature of the line, then ask whether the extra commissions bought profitable volume. "
            "FP&amp;A Lab → Variance analysis shows the full table and the basis for every verdict.</p>")


def _worked_budget() -> str:
    y = _y1()
    occ = y["occupied_rooms"] / y["available_rooms"]
    adr = y["rooms_revenue"] / y["occupied_rooms"]
    return (f"<p>The Base case builds the same line from its drivers: {y['available_rooms']:,.0f} available rooms × "
            f"{occ * 100:.1f}% occupancy × ADR SAR {adr:,.0f} = {m(y['rooms_revenue'])} room revenue in year 1. "
            "Change any driver in the Scenario Lab and the whole budget recalculates.</p>")


def _worked_sensitivity() -> str:
    from ..analysis.sensitivity import _apply
    a = baseline()
    out = []
    for mult in (0.9, 1.0, 1.1):
        r = simulate_cached(_apply(a, "segments.*.base_demand_mult", mult))
        out.append((mult, r.total("ebitda", r.year_slice(1))))
    base = out[1][1]
    lines = [f"demand × {mm:.1f}   EBITDA {m(e)}   change {(e - base) / base * 100:+.1f}%" for mm, e in out]
    return ("<p>One-way sensitivity on the baseline (year 1), demand in every segment:</p><pre>" + "\n".join(lines) +
            "</pre><p>A 10% demand change moves EBITDA by far more than 10% because fixed costs do not move: that is "
            "operating leverage. The response is also not symmetric, because capacity caps the upside. These are "
            "outcomes under the model's assumptions, not predictions.</p>")


def _worked_channel() -> str:
    y = _y1()
    out = []
    for s, lab in (("leisure_direct", "Leisure direct"), ("leisure_ota", "Leisure OTA"), ("corporate", "Corporate")):
        if s not in y["seg"]:
            continue
        rn, rev, com = y["seg"][s]
        if rn:
            out.append(f"{lab:<15} ADR SAR {rev / rn:7,.0f}   commission SAR {com / rn:5,.0f}   "
                       f"net ADR SAR {(rev - com) / rn:7,.0f}")
    return ("<p>Year 1 baseline by channel:</p><pre>" + "\n".join(out) + "</pre><p>A room sold through an OTA can "
            "show a healthy ADR yet earn less per night after commission. When occupancy beats budget but EBITDA "
            "misses, check mix and net ADR first, then cost per occupied room. The data quantifies these drivers; "
            "it does not by itself prove why guests switched channel, so mark the cause as 'to confirm'.</p>")


def _worked_group() -> str:
    from ..analysis import investment as inv
    y = _y1()
    ev = inv.run_case("expansion", baseline())
    return (f"<pre>Group EBITDA = Grand EBITDA + Oasis EBITDA − group overheads − intercompany eliminations</pre>"
            f"<p>Grand year-1 EBITDA in the baseline is {m(y['ebitda'])}. The fictional Oasis acquisition at default "
            f"assumptions has an NPV of {m(ev.npv)}. A management charge from the Grand to the Oasis is income for "
            "one and cost for the other: it nets to zero at group level and must be eliminated, otherwise group "
            "EBITDA is overstated by double counting.</p>")


def _worked_defend() -> str:
    y = _y1()
    return ("<p><b>GM:</b> 'Cutting the OTA promotion will empty the hotel.'</p>"
            "<p><b>Analyst (model answer):</b> 'I share the occupancy goal. The numbers show the promotion adds room "
            "nights but each OTA night earns less after commission, so EBITDA falls. I propose a fenced test: keep "
            "the promotion on low-demand dates only for six weeks, and we both review net RevPAR and EBITDA, not "
            f"occupancy alone. The hotel's year-1 EBITDA is {m(y['ebitda'])}; the test limits the downside while we "
            "find out.'</p><p>Pattern: acknowledge the goal → show the evidence → separate fact from assumption → "
            "offer a measurable test with an owner and date. Practise it in the Decision Room case 'The GM challenges "
            "your recommendation'.</p>")


def _worked_capstone() -> str:
    from ..analysis import capstone as K
    raw = K.messy_rooms()
    ctrl = K.hotel_controls()
    dups = int(raw.duplicated().sum())
    return (f"<p>Step 1 in miniature: the raw rooms file has {len(raw)} rows; the hotel control totals cover "
            f"{len(ctrl)} months. {dups} rows are exact duplicates, so summing the raw file overstates revenue. "
            "Remove duplicates, standardise segment labels, convert text numbers, then reconcile room nights and "
            "revenue to the control totals before computing any KPI. Every adjustment is written down.</p>"
            "<p>The other nine steps follow the same discipline: KPIs, reconciliation to budget, forecast, "
            "statements, investment choice, sensitivity, dashboard design, a written recommendation and a meeting "
            "defence.</p>")


@lru_cache(maxsize=1)
def topics() -> tuple[Topic, ...]:
    return tuple(_topics())


def topic(tid: str) -> Topic:
    return next(t for t in topics() if t.id == tid)


def topics_by_stage() -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for t in topics():
        out.setdefault(t.stage, []).append(t.id)
    return out


# --------------------------------------------------------------------------- answer checking
def parse_answer(text: str, unit: str) -> float | None:
    s = (text or "").strip().replace(",", "").replace("SAR", "").replace("USD", "").strip()
    if not s:
        return None
    pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    if unit == "pct" and (pct or abs(v) > 1.5):
        v /= 100
    return v


def is_correct(ex: Exercise, given) -> bool:
    if ex.unit == "choice":
        return str(given) == str(ex.answer)
    if given is None:
        return False
    if ex.unit == "pct":
        return abs(given - float(ex.answer)) <= max(ex.tolerance, 1e-9)
    tol = max(abs(float(ex.answer)) * ex.tolerance, 0.5 if ex.unit == "currency" else 1e-6)
    return abs(given - float(ex.answer)) <= tol


def _mapply(x: float) -> float:
    return x if math.isfinite(x) else 0.0
