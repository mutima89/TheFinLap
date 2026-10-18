"""Authoritative corporate-finance functions.

Every function here is pure, documented and validated against hand-calculated
reference cases in ``tests/test_finance.py``. Edge cases (no IRR, multiple IRRs,
invalid discount rates, empty cash flows) are reported explicitly instead of
returning misleading numbers.

Conventions
-----------
* Cash flows are a sequence ``cf[0], cf[1], ...`` where ``cf[0]`` occurs at
  t = 0 (today, undiscounted) and ``cf[t]`` at the end of period ``t``.
* Rates are decimals per period (0.10 = 10 %).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


class FinanceError(ValueError):
    """Raised when a calculation is undefined for the supplied inputs."""


def safe_div(numerator: float, denominator: float, default: float | None = None) -> float | None:
    """Divide, returning ``default`` (``None`` unless given) when the denominator is zero.

    ``None`` propagates "undefined" to the caller rather than silently
    substituting zero, which would distort KPIs such as ADR on a zero-occupancy day.
    """
    if denominator == 0 or denominator is None or numerator is None:
        return default
    if isinstance(denominator, float) and math.isnan(denominator):
        return default
    return numerator / denominator


def _validate_rate(rate: float) -> None:
    if rate is None or not math.isfinite(rate):
        raise FinanceError("Discount rate must be a finite number.")
    if rate <= -1.0:
        raise FinanceError("Discount rate must be greater than -100%.")


def _validate_flows(cash_flows: Sequence[float]) -> list[float]:
    flows = [float(x) for x in cash_flows]
    if not flows:
        raise FinanceError("At least one cash flow is required.")
    if any(not math.isfinite(x) for x in flows):
        raise FinanceError("Cash flows must be finite numbers.")
    return flows


def npv(rate: float, cash_flows: Sequence[float]) -> float:
    """Net present value with ``cash_flows[0]`` at t = 0.

    NPV = sum_t CF_t / (1 + r)^t

    Note: Excel's ``NPV()`` discounts the *first* value by one period; the
    Excel equivalent of this function is ``=CF0 + NPV(r, CF1:CFn)``.
    """
    _validate_rate(rate)
    flows = _validate_flows(cash_flows)
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(flows))


def sign_changes(cash_flows: Sequence[float]) -> int:
    """Number of sign changes in the cash-flow series (zeros ignored).

    By Descartes' rule of signs this bounds the number of positive real IRRs.
    """
    signs = [1 if x > 0 else -1 for x in cash_flows if x != 0]
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


@dataclass
class IRRResult:
    """Outcome of an IRR search. ``value`` is ``None`` when no IRR exists."""

    value: float | None
    all_roots: list[float] = field(default_factory=list)
    status: str = "ok"  # ok | none | multiple
    message: str = ""

    @property
    def is_unique(self) -> bool:
        return self.status == "ok"


def _npv_unchecked(rate: float, flows: Sequence[float]) -> float:
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(flows))


def irr(cash_flows: Sequence[float], lo: float = -0.99, hi: float = 10.0) -> IRRResult:
    """Internal rate of return, robust to unusual cash-flow patterns.

    The NPV curve is scanned on a fine grid between ``lo`` and ``hi`` and every
    sign change is refined by bisection, so *all* roots in the interval are
    found. Status:

    * ``ok`` – exactly one IRR.
    * ``multiple`` – several IRRs (non-conventional cash flows); IRR is not a
      reliable decision rule and NPV/MIRR should be used instead.
    * ``none`` – no IRR exists (e.g. all flows positive, or NPV never crosses 0).
    """
    flows = _validate_flows(cash_flows)
    if all(x >= 0 for x in flows) or all(x <= 0 for x in flows):
        return IRRResult(None, [], "none", "No IRR: cash flows never change sign.")

    roots: list[float] = []
    # Logarithmically denser grid near zero where most business IRRs lie.
    grid: list[float] = []
    r = lo
    while r < hi:
        grid.append(r)
        step = 0.0025 if -0.5 < r < 1.0 else 0.02
        r += step
    grid.append(hi)

    prev_r = grid[0]
    prev_v = _npv_unchecked(prev_r, flows)
    for r in grid[1:]:
        v = _npv_unchecked(r, flows)
        if prev_v == 0:
            roots.append(prev_r)
        elif prev_v * v < 0:
            a, b, fa = prev_r, r, prev_v
            for _ in range(200):
                m = (a + b) / 2
                fm = _npv_unchecked(m, flows)
                if fa * fm <= 0:
                    b = m
                else:
                    a, fa = m, fm
                if b - a < 1e-12:
                    break
            roots.append((a + b) / 2)
        prev_r, prev_v = r, v
    if prev_v == 0:
        roots.append(prev_r)

    roots = sorted({round(x, 10) for x in roots})
    if not roots:
        return IRRResult(None, [], "none", "No IRR found between -99% and 1000%.")
    if len(roots) > 1:
        return IRRResult(
            None,
            roots,
            "multiple",
            "Multiple IRRs ("
            + ", ".join(f"{x:.2%}" for x in roots)
            + "). Cash flows change sign more than once; use NPV or MIRR.",
        )
    return IRRResult(roots[0], roots, "ok", "")


def mirr(cash_flows: Sequence[float], finance_rate: float, reinvest_rate: float) -> float:
    """Modified IRR (Excel ``MIRR`` convention).

    MIRR = (FV of positive flows at reinvest rate / -PV of negative flows at
    finance rate) ^ (1/n) - 1, where n = number of periods (len - 1).
    """
    _validate_rate(finance_rate)
    _validate_rate(reinvest_rate)
    flows = _validate_flows(cash_flows)
    n = len(flows) - 1
    if n < 1:
        raise FinanceError("MIRR needs at least two cash flows.")
    pv_neg = sum(cf / (1 + finance_rate) ** t for t, cf in enumerate(flows) if cf < 0)
    fv_pos = sum(cf * (1 + reinvest_rate) ** (n - t) for t, cf in enumerate(flows) if cf > 0)
    if pv_neg == 0 or fv_pos == 0:
        raise FinanceError("MIRR requires at least one negative and one positive cash flow.")
    return (fv_pos / -pv_neg) ** (1.0 / n) - 1.0


def payback_period(cash_flows: Sequence[float]) -> float | None:
    """Undiscounted payback in periods, interpolated within the recovery period.

    Returns ``None`` when the investment is never recovered.
    """
    flows = _validate_flows(cash_flows)
    cumulative = 0.0
    for t, cf in enumerate(flows):
        prev = cumulative
        cumulative += cf
        if t > 0 and prev < 0 <= cumulative:
            return (t - 1) + (-prev / cf if cf else 0.0)
    if flows[0] >= 0:
        return 0.0
    return None


def discounted_payback(rate: float, cash_flows: Sequence[float]) -> float | None:
    """Payback period of discounted cash flows; ``None`` if never recovered."""
    _validate_rate(rate)
    flows = _validate_flows(cash_flows)
    return payback_period([cf / (1 + rate) ** t for t, cf in enumerate(flows)])


def profitability_index(rate: float, cash_flows: Sequence[float]) -> float | None:
    """PV of future flows divided by the initial investment (-CF0).

    PI = sum_{t>=1} PV(CF_t) / -CF_0. ``None`` when CF0 is not an outflow.
    """
    _validate_rate(rate)
    flows = _validate_flows(cash_flows)
    if flows[0] >= 0:
        return None
    pv_future = sum(cf / (1 + rate) ** t for t, cf in enumerate(flows) if t > 0)
    return pv_future / -flows[0]


def roi(total_gain: float, investment: float) -> float | None:
    """Simple (undiscounted) return on investment = (gain - investment) / investment."""
    return safe_div(total_gain - investment, investment)


def pmt(rate: float, nper: int, pv: float) -> float:
    """Level payment that amortises ``pv`` over ``nper`` periods (positive number)."""
    if nper <= 0:
        raise FinanceError("Number of periods must be positive.")
    if rate == 0:
        return pv / nper
    _validate_rate(rate)
    return pv * rate / (1 - (1 + rate) ** -nper)


def terminal_value_gordon(final_cash_flow: float, discount_rate: float, growth: float) -> float:
    """Gordon growth terminal value at the end of the final period.

    TV = CF_n × (1 + g) / (r − g). Requires r > g.
    """
    _validate_rate(discount_rate)
    if discount_rate <= growth:
        raise FinanceError("Terminal value requires the discount rate to exceed the growth rate.")
    return final_cash_flow * (1 + growth) / (discount_rate - growth)


def break_even_units(fixed_costs: float, price: float, variable_cost: float) -> float | None:
    """Units needed to cover fixed costs. ``None`` if contribution per unit ≤ 0."""
    contribution = price - variable_cost
    if contribution <= 0:
        return None
    return fixed_costs / contribution


def contribution_margin_ratio(price: float, variable_cost: float) -> float | None:
    return safe_div(price - variable_cost, price)


def degree_of_operating_leverage(contribution: float, operating_profit: float) -> float | None:
    """DOL = total contribution / operating profit (undefined at zero profit)."""
    return safe_div(contribution, operating_profit)


def annuity_factor(rate: float, n: int) -> float:
    if rate == 0:
        return float(n)
    _validate_rate(rate)
    return (1 - (1 + rate) ** -n) / rate


def equivalent_annual_cost(rate: float, cash_flows: Sequence[float]) -> float:
    """EAC = −NPV / annuity factor; used for repair-vs-replace comparisons."""
    flows = _validate_flows(cash_flows)
    n = len(flows) - 1
    if n < 1:
        raise FinanceError("EAC needs at least one period.")
    return -npv(rate, flows) / annuity_factor(rate, n)


def monthly_rate(annual_rate: float) -> float:
    """Convert an effective annual rate to the equivalent monthly rate."""
    _validate_rate(annual_rate)
    return (1 + annual_rate) ** (1 / 12) - 1
