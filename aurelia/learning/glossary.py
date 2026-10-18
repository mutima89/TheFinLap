"""Glossary and in-app search index."""
from __future__ import annotations

from dataclasses import dataclass

GLOSSARY: dict[str, str] = {
    "ADR (Average Daily Rate)": "Room revenue ÷ rooms sold. Price achieved per occupied room.",
    "Available rooms": "Physical rooms minus rooms out of order; the denominator for occupancy and RevPAR.",
    "Bias (forecast)": "Average of forecast − actual. Positive = systematic over-forecasting.",
    "Break-even": "Volume (or price, or assumption) at which profit or NPV equals zero.",
    "Business case": "A structured argument for spending money: problem, options, incremental cash flows, NPV, "
                     "risks and how success will be measured.",
    "Cannibalisation": "New bookings in one channel that would otherwise have come through a cheaper one.",
    "Capex": "Capital expenditure: spending on long-lived assets, shown in investing cash flow and depreciated.",
    "Cash conversion": "Operating cash flow ÷ EBITDA: how much operating profit becomes cash.",
    "Cash flow statement": "Explains the change in cash: operating (CFO), investing (CFI) and financing (CFF).",
    "Contribution": "Revenue − variable costs. What each extra unit adds towards fixed costs and profit.",
    "Contribution margin": "Contribution ÷ revenue.",
    "Deferred revenue (advance deposits)": "Cash received before the stay; a liability until the service is "
                                          "delivered.",
    "Departmental profit": "Revenue of an operated department minus its direct costs (USALI).",
    "Depreciation": "Allocation of an asset's cost over its useful life. Non-cash, but tax-deductible.",
    "Discounted payback": "Time until cumulative discounted cash flows turn positive.",
    "Displacement": "Higher-value business turned away because capacity was given to lower-value business.",
    "DPO (Days Payable Outstanding)": "Payables ÷ purchases × days. Supplier credit used.",
    "DSO (Days Sales Outstanding)": "Receivables ÷ credit sales × days. Speed of collection.",
    "EBITDA": "Earnings before interest, tax, depreciation and amortisation. Here: GOP − management fees − fixed "
              "charges.",
    "Elasticity (price)": "% change in demand ÷ % change in price. Constant-elasticity model: demand ∝ price^e.",
    "Favourable / unfavourable (F/U)": "Whether a variance helps or hurts profit, judged by the nature of the line "
                                       "and its context — not by its sign.",
    "Fixed charges": "Insurance, property taxes and lease costs below GOP.",
    "Flexible budget": "Budget restated at actual activity: fixed costs unchanged, variable costs at budget rates.",
    "Forecast version": "A saved, dated forecast with an approval status, so decisions can cite the numbers that "
                        "were current at the time.",
    "GOP (Gross Operating Profit)": "Departmental profit − undistributed operating expenses.",
    "GOPPAR": "GOP ÷ available rooms.",
    "Group block": "Rooms contracted to a group for given dates at a negotiated rate.",
    "Incentive fee": "Management fee paid to the operator as a share of GOP (here 8%).",
    "Incremental cash flow": "Cash flows with the project minus cash flows without it.",
    "IRR (Internal Rate of Return)": "Discount rate at which NPV = 0. Can be multiple or absent for unusual cash "
                                     "flows.",
    "Latest estimate (LE)": "Actuals to date plus forecast for the rest of the year.",
    "MAPE": "Mean absolute percentage error of a forecast, on actuals.",
    "Materiality": "Threshold above which a variance must be explained (here SAR 250k and 5%, configurable).",
    "Minimum length of stay (MLOS)": "Restriction that a booking must cover at least N nights.",
    "MIRR": "Modified IRR: reinvests positive flows at a stated rate and finances negative flows at another; "
            "always unique.",
    "Mix variance": "Effect on revenue of selling a different proportion of high- and low-rated segments.",
    "Monte Carlo": "Repeated simulation with inputs drawn from assumed distributions; shows a range under those "
                   "assumptions, not a prediction.",
    "Net ADR": "(Room revenue − commissions and distribution costs) ÷ rooms sold.",
    "Net RevPAR": "(Room revenue − distribution costs) ÷ available rooms.",
    "No-show": "Guest with a reservation who neither arrives nor cancels.",
    "NPV (Net Present Value)": "Sum of cash flows discounted at the required return, including the initial "
                               "investment. Positive NPV creates value.",
    "Occupancy": "Rooms sold ÷ rooms available.",
    "Operating leverage": "Contribution ÷ profit. A high value means profit is very sensitive to volume.",
    "OTA": "Online travel agency; a distribution channel that charges commission.",
    "Overbooking": "Selling more rooms than available to offset expected cancellations and no-shows; risks "
                   "walking guests.",
    "Pace / pickup": "How bookings for a future date accumulate over time.",
    "Payback": "Time to recover the initial investment from undiscounted cash flows.",
    "Profitability index": "PV of future cash flows ÷ initial investment.",
    "Rate fence": "A condition that separates customer groups so a lower rate is not available to everyone "
                  "(advance purchase, non-refundable, minimum stay).",
    "Rate variance": "(Actual rate − budget rate) × actual volume.",
    "Retained earnings": "Accumulated net income not paid out as dividends; links the P&L to the balance sheet.",
    "RevPAR": "Room revenue ÷ available rooms = occupancy × ADR.",
    "Revolver": "Revolving credit facility drawn automatically when cash falls below the minimum.",
    "Rolling forecast": "Forecast that always covers the next N months, crossing the year end.",
    "Run-rate": "YTD result scaled to a full year. Ignores seasonality.",
    "Segment": "Group of guests with similar booking behaviour (corporate, leisure, group, wholesale).",
    "Sensitivity analysis": "Changing one (or two) inputs to see the effect on an output.",
    "Spending (efficiency) variance": "Actual cost − flexed budget cost.",
    "Terminal value": "Value of cash flows beyond the explicit forecast period (Gordon growth: CF × (1+g) ÷ (r − g)).",
    "TRevPAR": "Total revenue ÷ available rooms.",
    "Undistributed expenses": "Costs not owned by one department: A&G, S&M, maintenance, utilities, IT.",
    "USALI": "Uniform System of Accounts for the Lodging Industry — the standard hotel P&L layout.",
    "VAT (here 15%)": "Value-added tax collected on behalf of the government. Revenue in Aurelia is net of VAT; "
                      "VAT collected is a liability, paid with a one-month lag.",
    "Volume variance": "(Actual volume − budget volume) × budget rate.",
    "Walk": "Relocating a guest with a confirmed booking to another hotel because of overbooking.",
    "Working capital": "Receivables + inventory − payables and other operating liabilities.",
}

SHORTCUTS = [("Ctrl+K", "Search"), ("Ctrl+Z / Ctrl+Y", "Undo / redo a driver change"),
             ("Ctrl+S", "Save the working draft into the current scenario"), ("Ctrl+T", "Toggle light/dark theme"),
             ("Ctrl+1 … Ctrl+9", "Jump to the first nine pages"), ("F1", "Help & glossary")]


@dataclass
class Hit:
    kind: str
    title: str
    snippet: str
    page: str
    payload: object = None


def search(q: str, limit: int = 60) -> list[Hit]:
    """Plain-text search across glossary, KPIs, lessons, models, decision cases and drivers."""
    q = (q or "").strip().lower()
    if not q:
        return []
    hits: list[Hit] = []
    for term, d in GLOSSARY.items():
        if q in term.lower() or q in d.lower():
            hits.append(Hit("Glossary", term, d, "glossary", term))
    from ..core.kpis import KPI_DEFINITIONS
    for k, kd in KPI_DEFINITIONS.items():
        if q in kd.name.lower() or q in kd.formula.lower() or q in k:
            hits.append(Hit("KPI", kd.name, kd.formula, "dashboard", k))
    from .content import topics
    import re
    for t in topics():
        text = re.sub(r"<[^>]+>", " ", t.explanation)
        if q in t.title.lower() or q in text.lower():
            i = text.lower().find(q)
            snip = text[max(0, i - 60): i + 100].strip() if i >= 0 else text[:140]
            hits.append(Hit("Lesson", f"Stage {t.stage}: {t.title}", snip, "learn", t.id))
    from ..analysis.decisions import CASES
    for c in CASES:
        if q in c.title.lower() or q in c.situation.lower():
            hits.append(Hit("Decision case", c.title, c.situation[:140], "decisions", c.id))
    from ..model.assumptions import DRIVER_SPECS
    for s in DRIVER_SPECS:
        if q in s.label.lower() or q in s.path.lower() or q in (s.help or "").lower():
            hits.append(Hit("Driver", s.label, f"{s.category} · {s.path}", "lab", s.path))
    models = {"A. Revenue driver model": "bookings × price × mix", "B. Departmental profit": "contribution",
              "C. Hotel operating statement": "USALI", "D. Three-statement model": "income balance cash flow",
              "E. Integrated forecast": "36 months", "F. Working capital": "receivables payables DSO DPO",
              "G. Capital expenditure": "depreciation capex", "H. Unit economics": "break-even contribution leverage"}
    for name, kw in models.items():
        if q in name.lower() or q in kw:
            hits.append(Hit("Model", name, kw, "workbench", name[0]))
    return hits[:limit]
