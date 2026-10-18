"""Financial statement layouts built from engine results (shared by UI, Excel and PDF/HTML exports)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..model.engine import SimulationResult

# (key or None for header, label, sign, style) – style: h (header), b (bold total), n (normal), i (indent)
OPERATING_STATEMENT = [
    (None, "Operating revenue", 1, "h"),
    ("rooms_revenue", "Rooms", 1, "i"), ("fnb_revenue", "Food & beverage", 1, "i"),
    ("spa_revenue", "Spa & wellness", 1, "i"), ("events_revenue", "Events & banqueting", 1, "i"),
    ("other_revenue", "Other operated departments", 1, "i"),
    ("total_revenue", "Total operating revenue", 1, "b"),
    (None, "Departmental profit", 1, "h"),
    ("rooms_profit", "Rooms", 1, "i"), ("fnb_profit", "Food & beverage", 1, "i"), ("spa_profit", "Spa & wellness", 1, "i"),
    ("events_profit", "Events & banqueting", 1, "i"), ("other_profit", "Other operated departments", 1, "i"),
    ("total_dept_profit", "Total departmental profit", 1, "b"),
    (None, "Undistributed operating expenses", 1, "h"),
    ("ag_expense", "Administrative & general", -1, "i"), ("it_expense", "Information & telecom systems", -1, "i"),
    ("sm_expense", "Sales & marketing", -1, "i"), ("pom_expense", "Property operation & maintenance", -1, "i"),
    ("utilities_expense", "Utilities", -1, "i"),
    ("total_undistributed", "Total undistributed expenses", -1, "b"),
    ("gop", "Gross operating profit (GOP)", 1, "b"),
    ("mgmt_fees", "Management fees", -1, "i"), ("fixed_charges", "Fixed charges", -1, "i"),
    ("ebitda", "EBITDA", 1, "b"),
]

INCOME_STATEMENT = [
    ("total_revenue", "Revenue", 1, "b"),
    ("total_dept_expenses", "Departmental expenses", -1, "i"),
    ("total_undistributed", "Undistributed expenses", -1, "i"),
    ("mgmt_fees", "Management fees", -1, "i"),
    ("fixed_charges", "Fixed charges", -1, "i"),
    ("ebitda", "EBITDA", 1, "b"),
    ("depreciation", "Depreciation", -1, "i"),
    ("ebit", "EBIT", 1, "b"),
    ("interest_expense", "Interest expense", -1, "i"),
    ("interest_income", "Interest income", 1, "i"),
    ("ebt", "Profit before tax", 1, "b"),
    ("tax_expense", "Income tax", -1, "i"),
    ("net_income", "Net income", 1, "b"),
]

BALANCE_SHEET = [
    (None, "Assets", 1, "h"),
    ("cash", "Cash", 1, "i"), ("accounts_receivable", "Accounts receivable", 1, "i"),
    ("inventory", "Inventory", 1, "i"), ("fa_nbv", "Property, plant & equipment (net)", 1, "i"),
    ("total_assets", "Total assets", 1, "b"),
    (None, "Liabilities", 1, "h"),
    ("accounts_payable", "Accounts payable", 1, "i"), ("vat_payable", "VAT payable", 1, "i"),
    ("deferred_revenue", "Advance deposits (deferred revenue)", 1, "i"), ("tax_payable", "Income tax payable", 1, "i"),
    ("term_loan", "Term loan", 1, "i"), ("revolver", "Revolving credit facility", 1, "i"),
    ("total_liabilities", "Total liabilities", 1, "b"),
    (None, "Equity", 1, "h"),
    ("share_capital", "Share capital", 1, "i"), ("retained_earnings", "Retained earnings", 1, "i"),
    ("total_equity", "Total equity", 1, "b"),
    ("balance_check", "Check: assets − liabilities − equity", 1, "n"),
]

CASH_FLOW = [
    ("net_income", "Net income", 1, "i"),
    ("depreciation", "Add back depreciation", 1, "i"),
    ("_d_ar", "(Increase)/decrease in receivables", 1, "i"),
    ("_d_inv", "(Increase)/decrease in inventory", 1, "i"),
    ("_d_ap", "Increase/(decrease) in payables", 1, "i"),
    ("_d_vat", "Increase/(decrease) in VAT payable", 1, "i"),
    ("_d_dep", "Increase/(decrease) in advance deposits", 1, "i"),
    ("_d_tax", "Increase/(decrease) in tax payable", 1, "i"),
    ("cfo", "Cash flow from operations", 1, "b"),
    ("capex", "Capital expenditure", -1, "i"),
    ("cfi", "Cash flow from investing", 1, "b"),
    ("revolver_draw", "Revolver draw/(repayment)", 1, "i"),
    ("term_repayment", "Term loan repayment", -1, "i"),
    ("dividends", "Dividends", -1, "i"),
    ("cff", "Cash flow from financing", 1, "b"),
    ("net_cash_flow", "Net cash flow", 1, "b"),
    ("cash_opening", "Opening cash", 1, "i"),
    ("cash", "Closing cash", 1, "b"),
]

REVENUE_CASH_BRIDGE = [
    ("total_revenue", "Operating revenue recognised (excl. VAT)", 1, "b"),
    ("vat_output", "VAT collected for the authority (not revenue)", 1, "i"),
    ("gross_billings", "Gross billings incl. VAT", 1, "b"),
    ("_d_ar", "Less increase in receivables", 1, "i"),
    ("_d_dep", "Add increase in advance deposits", 1, "i"),
    ("cash_receipts", "Cash receipts from customers", 1, "b"),
]


def _derived(res: SimulationResult) -> dict[str, np.ndarray]:
    def delta(k, sign):
        s = res.s(k)
        prev = np.concatenate([[res.opening[k]], s[:-1]])
        return sign * (s - prev)
    return {"_d_ar": delta("accounts_receivable", -1), "_d_inv": delta("inventory", -1),
            "_d_ap": delta("accounts_payable", 1), "_d_vat": delta("vat_payable", 1),
            "_d_dep": delta("deferred_revenue", 1), "_d_tax": delta("tax_payable", 1)}


def statement(res: SimulationResult, layout, freq: str = "annual", balance: bool = False,
              signed: bool = False) -> pd.DataFrame:
    """Return a DataFrame with columns Line, style and one column per period.

    Flow items are summed per period; balance items take the period-end value.
    Expenses are shown as positive numbers in the 'sign = -1' rows (labelled as costs),
    matching conventional management-report presentation.
    """
    der = _derived(res)
    months = res.months
    if freq == "monthly":
        groups = [(m.strftime("%b %Y"), slice(i, i + 1)) for i, m in enumerate(months)]
    else:
        years = sorted({m.year for m in months})
        groups = []
        for y in years:
            idx = [i for i, m in enumerate(months) if m.year == y]
            groups.append((f"FY{y}", slice(idx[0], idx[-1] + 1)))
    rows = []
    for key, lab, _sign, style in layout:
        row = {"Line": lab, "style": style, "key": key or ""}
        for name, sl in groups:
            if key is None:
                row[name] = None
                continue
            series = der[key] if key in der else res.s(key)
            if signed:
                series = series * _sign
            if balance or (key in ("cash", "cash_opening") and freq == "annual"):
                if key == "cash_opening":
                    row[name] = float(series[sl][0])
                else:
                    row[name] = float(series[sl][-1])
            else:
                row[name] = float(series[sl].sum())
        rows.append(row)
    return pd.DataFrame(rows)


def operating_statement(res, freq="annual"):
    return statement(res, OPERATING_STATEMENT, freq)


def income_statement(res, freq="annual"):
    return statement(res, INCOME_STATEMENT, freq)


def balance_sheet(res, freq="annual"):
    return statement(res, BALANCE_SHEET, freq, balance=True)


def cash_flow_statement(res, freq="annual"):
    return statement(res, CASH_FLOW, freq, signed=True)


def revenue_cash_bridge(res, freq="annual"):
    return statement(res, REVENUE_CASH_BRIDGE, freq)


def checks_frame(res: SimulationResult) -> pd.DataFrame:
    return pd.DataFrame([{"Check": c.name, "Status": "PASS" if c.passed else "FAIL",
                          "Max abs. difference": c.max_abs_error, "Rule": c.detail} for c in res.checks])
