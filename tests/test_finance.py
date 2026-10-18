"""Finance formulas vs independently hand-calculated (or published) reference values.

Reference values were worked by hand / taken from textbook and Excel
documentation examples; they are NOT produced by calling the implementation.
"""
import math

import pytest

from aurelia.core import finance as f


def test_npv_hand_calculated():
    # -1000 + 500/1.1 + 500/1.21 + 500/1.331 = -1000 + 454.5455 + 413.2231 + 375.6574
    assert f.npv(0.10, [-1000, 500, 500, 500]) == pytest.approx(243.4260, abs=1e-3)


def test_npv_zero_rate_is_sum():
    assert f.npv(0.0, [-100, 30, 30, 30]) == pytest.approx(-10.0)


@pytest.mark.parametrize("rate", [-1.0, -1.5, float("nan"), float("inf")])
def test_npv_invalid_rate(rate):
    with pytest.raises(f.FinanceError):
        f.npv(rate, [-1, 2])


def test_npv_empty():
    with pytest.raises(f.FinanceError):
        f.npv(0.1, [])


def test_irr_single_period():
    r = f.irr([-100, 110])
    assert r.status == "ok" and r.value == pytest.approx(0.10, abs=1e-9)


def test_irr_annuity_known_value():
    # Solving -1000 + 500·a(3, r) = 0 gives r ≈ 23.3752% (published annuity tables)
    r = f.irr([-1000, 500, 500, 500])
    assert r.value == pytest.approx(0.233752, abs=1e-5)


def test_irr_multiple_roots_detected():
    # -100 + 230/(1+r) - 132/(1+r)^2 = 0 has roots at exactly 10% and 20%
    r = f.irr([-100, 230, -132])
    assert r.status == "multiple"
    assert r.value is None
    assert r.all_roots == pytest.approx([0.10, 0.20], abs=1e-6)


def test_irr_none_when_no_sign_change():
    assert f.irr([100, 50, 20]).status == "none"
    assert f.irr([-100, -50]).status == "none"


def test_irr_none_when_never_recovered():
    # Losses never recovered: NPV < 0 for all rates > -99%.
    r = f.irr([-100, 10, 10])
    assert r.status == "ok" and r.value < 0  # negative IRR is a valid finding


def test_mirr_excel_documentation_example():
    # Microsoft's MIRR documentation: -120000, 39000, 30000, 21000, 37000, 46000;
    # finance 10%, reinvest 12% => 12.61%
    assert f.mirr([-120000, 39000, 30000, 21000, 37000, 46000], 0.10, 0.12) == pytest.approx(0.126094, abs=1e-5)


def test_payback_interpolated():
    # cumulative: -1000, -700, -300, +200 -> 2 + 300/500 = 2.6
    assert f.payback_period([-1000, 300, 400, 500]) == pytest.approx(2.6)


def test_payback_never():
    assert f.payback_period([-1000, 100, 100]) is None


def test_discounted_payback():
    # discounted: 454.545, 413.223, 375.657; after 2 periods -132.231 -> 2 + 132.231/375.657
    assert f.discounted_payback(0.10, [-1000, 500, 500, 500]) == pytest.approx(2.35200, abs=1e-4)


def test_profitability_index():
    assert f.profitability_index(0.10, [-1000, 500, 500, 500]) == pytest.approx(1.243426, abs=1e-5)
    assert f.profitability_index(0.10, [100, 500]) is None


def test_pmt_known_value():
    # 10,000 over 12 months at 1%/month -> 888.49 (standard loan table)
    assert f.pmt(0.01, 12, 10000) == pytest.approx(888.4879, abs=1e-3)
    assert f.pmt(0.0, 10, 1000) == pytest.approx(100)


def test_gordon_terminal_value():
    assert f.terminal_value_gordon(100, 0.10, 0.02) == pytest.approx(1275.0)
    with pytest.raises(f.FinanceError):
        f.terminal_value_gordon(100, 0.02, 0.03)


def test_break_even_and_leverage():
    assert f.break_even_units(1000, 50, 30) == pytest.approx(50)
    assert f.break_even_units(1000, 30, 30) is None
    assert f.contribution_margin_ratio(50, 30) == pytest.approx(0.4)
    assert f.degree_of_operating_leverage(400, 100) == pytest.approx(4.0)
    assert f.degree_of_operating_leverage(400, 0) is None


def test_safe_div():
    assert f.safe_div(1, 0) is None
    assert f.safe_div(1, 0, 0.0) == 0.0
    assert f.safe_div(6, 3) == 2


def test_roi_and_eac():
    assert f.roi(1500, 1000) == pytest.approx(0.5)
    # EAC of a 1000 asset with no other flows over 2 years at 10%: 1000 / 1.735537 = 576.19
    assert f.equivalent_annual_cost(0.10, [-1000, 0, 0]) == pytest.approx(576.19, abs=0.01)


def test_monthly_rate():
    assert f.monthly_rate(0.1268250301) == pytest.approx(0.01, abs=1e-9)


def test_sign_changes():
    assert f.sign_changes([-1, 2, -3, 0, 4]) == 3
    assert math.isfinite(f.npv(0.05, [-1, 0, 0, 2]))
