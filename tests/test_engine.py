"""Simulation engine vs a hand-calculated hotel.

WORKED HAND CALCULATION (simple_hotel, January 2027, 31 days)
-------------------------------------------------------------
Rooms: 100 available/day. Corporate requests 50/day at SAR 1,000.
  accepted 50, cancelled 50 × 10% = 5, no-shows 0, shows 45/day
  unmet demand = 0 so no cancelled rooms are resold
  occupied = 45 × 31 = 1,395 room nights; occupancy 45%
  room revenue = 1,395 × 1,000 = 1,395,000; commission 10% = 139,500
Rooms expenses: payroll 10 × 5,000 × 1.2 = 60,000; housekeeping 1,395 × 20 = 27,900
  rooms profit = 1,395,000 − 139,500 − 27,900 − 60,000 = 1,167,600
A&G fixed 100,000 → GOP = EBITDA = 1,067,600
Depreciation 1,200,000 / 120 = 10,000; interest 1,000,000 × 12% / 12 = 10,000
EBT = 1,047,600; tax 20% = 209,520; net income = 838,080
Working capital: AP = all non-payroll costs (DPO 31 = full month) = 139,500 + 27,900 + 100,000 = 267,400
  VAT payable = 1,395,000 × 15% = 209,250 (paid next month); tax payable 209,520
CFO = 838,080 + 10,000 + 267,400 + 209,250 + 209,520 = 1,534,250 → closing cash 2,034,250
Opening RE (plug) = 1,700,000 − 1,000,000 − 1,000,000 = −300,000
"""
import copy

import numpy as np
import pytest

from aurelia.model.engine import simulate, balance_from_days
from aurelia.model.assumptions import baseline, validate, ValidationError, set_path


def test_simple_hotel_rooms(simple):
    r = simulate(simple)
    assert r.s("available_rooms")[0] == pytest.approx(3100)
    assert r.s("occupied_rooms")[0] == pytest.approx(1395)
    assert r.s("rooms_revenue")[0] == pytest.approx(1_395_000)
    assert r.s("commissions")[0] == pytest.approx(139_500)
    assert r.s("cancellations")[0] == pytest.approx(155)
    k = r.kpis()
    assert k["occupancy"] == pytest.approx(0.45)
    assert k["adr"] == pytest.approx(1000)
    assert k["revpar"] == pytest.approx(450)
    assert k["net_adr"] == pytest.approx(900)


def test_simple_hotel_pnl(simple):
    r = simulate(simple)
    assert r.s("rooms_profit")[0] == pytest.approx(1_167_600)
    assert r.s("gop")[0] == pytest.approx(1_067_600)
    assert r.s("ebitda")[0] == pytest.approx(1_067_600)
    assert r.s("depreciation")[0] == pytest.approx(10_000)
    assert r.s("interest_expense")[0] == pytest.approx(10_000)
    assert r.s("tax_expense")[0] == pytest.approx(209_520)
    assert r.s("net_income")[0] == pytest.approx(838_080)


def test_simple_hotel_balance_sheet_and_cash(simple):
    r = simulate(simple)
    assert r.opening["retained_earnings"] == pytest.approx(-300_000)
    assert r.s("accounts_payable")[0] == pytest.approx(267_400)
    assert r.s("vat_payable")[0] == pytest.approx(209_250)
    assert r.s("tax_payable")[0] == pytest.approx(209_520)
    assert r.s("cfo")[0] == pytest.approx(1_534_250)
    assert r.s("cash")[0] == pytest.approx(2_034_250)
    assert r.s("total_assets")[0] == pytest.approx(2_034_250 + 1_190_000)
    assert r.all_checks_passed


def test_price_elasticity_unit_elastic(simple):
    # Elasticity −1: a 10% higher rate reduces demand to 50/1.1; revenue is unchanged.
    a = copy.deepcopy(simple)
    a["segments"]["corporate"]["published_rate"] = 1100.0
    r = simulate(a)
    assert r.s("occupied_rooms")[0] == pytest.approx(31 * 50 / 1.1 * 0.9)
    assert r.s("rooms_revenue")[0] == pytest.approx(1_395_000)
    # ...but costs per occupied room fall, so profit rises: price cut ≠ automatic profit.
    assert r.s("rooms_profit")[0] > 1_167_600


def test_price_cut_does_not_automatically_raise_profit(simple):
    a = copy.deepcopy(simple)
    a["segments"]["corporate"]["published_rate"] = 800.0  # -20%, unit elastic demand
    r = simulate(a)
    assert r.s("rooms_revenue")[0] == pytest.approx(1_395_000)
    assert r.s("rooms_profit")[0] < 1_167_600  # more rooms to clean for the same revenue


def test_capacity_constraint_and_resale(simple):
    # 200 requests for 100 rooms: accept 100, 10 cancel, 60% (=6) resold to unmet demand → 96 occupied
    a = copy.deepcopy(simple)
    a["segments"]["corporate"]["base_demand"] = 200.0
    r = simulate(a)
    assert r.s("occupied_rooms")[0] == pytest.approx(96 * 31)
    assert r.s("occupied_rooms")[0] <= r.s("available_rooms")[0]
    assert r.all_checks_passed


def test_occupancy_never_exceeds_capacity_extreme_demand():
    a = baseline()
    for s in a["segments"].values():
        s["base_demand"] = 400.0
        s["cap"] = None
    r = simulate(a)
    assert (r.s("occupied_rooms") <= r.s("available_rooms") + 1e-6).all()
    assert (r.daily["occupied"] <= r.daily["available"] + 1e-9).all()


def test_overbooking_produces_walks_and_costs(simple):
    a = copy.deepcopy(simple)
    a["segments"]["corporate"]["base_demand"] = 200.0
    a["rooms"]["overbooking_pct"] = 0.10
    a["rooms"]["cancellation_resale_pct"] = 0.0
    r = simulate(a)
    # accepted 110/day, cancellations 11, shows 99 → never certain to exceed 100 → small expected walks
    assert r.s("walked_guests")[0] >= 0
    assert r.s("occupied_rooms")[0] <= r.s("available_rooms")[0] + 1e-6
    assert r.s("walk_costs")[0] == pytest.approx(r.s("walked_guests")[0] * a["rooms"]["walk_cost"])
    assert r.all_checks_passed


def test_out_of_order_rooms_reduce_inventory(simple):
    a = copy.deepcopy(simple)
    a["rooms"]["out_of_order_rooms"] = 60  # 40 available; demand 50 → constrained
    r = simulate(a)
    assert r.s("available_rooms")[0] == pytest.approx(40 * 31)
    assert r.s("occupied_rooms")[0] <= 40 * 31 + 1e-6


def test_invalid_inputs_rejected():
    a = baseline()
    a["rooms"]["out_of_order_rooms"] = 500
    assert any("negative inventory" in p for p in validate(a))
    a = baseline()
    set_path(a, "segments.corporate.cancellation_pct", 1.5)
    with pytest.raises(ValidationError):
        simulate(a)


def test_reproducible_with_seed():
    a = baseline()
    r1, r2 = simulate(a), simulate(copy.deepcopy(a))
    assert np.array_equal(r1.s("occupied_rooms"), r2.s("occupied_rooms"))
    b = copy.deepcopy(a)
    b["rooms"]["random_seed"] = 99
    assert not np.array_equal(r1.s("occupied_rooms"), simulate(b).s("occupied_rooms"))


def test_unrelated_change_does_not_reshuffle_noise():
    a = baseline()
    b = copy.deepcopy(a)
    b["undistributed"]["energy_price_per_kwh"] = 0.5
    assert np.array_equal(simulate(a).s("occupied_rooms"), simulate(b).s("occupied_rooms"))


def test_baseline_integrity(base_result):
    failed = [c.name for c in base_result.checks if not c.passed]
    assert not failed, failed
    assert base_result.months.size == 36


def test_three_statement_links_over_36_months(base_result):
    r = base_result
    # Independent identity: ΔCash = Σ CFO + Σ CFI + Σ CFF
    assert r.s("cash")[-1] - r.opening["cash"] == pytest.approx(r.total("cfo") + r.total("cfi") + r.total("cff"))
    # Retained earnings change = cumulative NI − dividends
    assert r.s("retained_earnings")[-1] - r.opening["retained_earnings"] == pytest.approx(
        r.total("net_income") - r.total("dividends"))


def test_vat_is_not_revenue(base_result):
    r = base_result
    assert r.total("gross_billings") == pytest.approx(r.total("total_revenue") * 1.15)


def test_balance_from_days():
    flows = np.array([310.0, 280.0, 310.0])
    dim = np.array([31.0, 28.0, 31.0])
    # 45 days at end of month 2 = all of Feb (280) + 17/31 of Jan (170)
    assert balance_from_days(flows, dim, 45)[1] == pytest.approx(450)
    # month 1 with 45 days uses steady-state pre-model month equal to month 1
    assert balance_from_days(flows, dim, 45)[0] == pytest.approx(310 + 140)


def test_renovation_project_takes_rooms_out_and_depreciates():
    a = baseline()
    a["capex"]["projects"] = [{"name": "Renovation", "month": "2027-06", "amount": 12_000_000.0, "life_years": 10,
                               "ooo_rooms": 30, "ooo_months": 2, "rate_uplift_pct": 0.05}]
    base = simulate(baseline())
    r = simulate(a)
    assert r.s("available_rooms")[5] == pytest.approx(base.s("available_rooms")[5] - 30 * 30)
    assert r.s("capex")[5] - base.s("capex")[5] == pytest.approx(12_000_000, rel=0.01)
    assert r.s("depreciation")[6] - base.s("depreciation")[6] == pytest.approx(100_000, rel=0.02)
    assert r.all_checks_passed


def test_campaign_costs_and_uplift():
    a = baseline()
    a["campaigns"] = [{"name": "OTA promo", "segment": "leisure_ota", "start_month": "2027-03", "months": 2,
                       "spend_per_month": 50000.0, "demand_uplift_pct": 0.2, "extra_commission_pct": 0.03}]
    base, r = simulate(baseline()), simulate(a)
    assert r.s("campaign_spend")[2] == pytest.approx(50000)
    assert r.segments["leisure_ota"]["demand"][2] > base.segments["leisure_ota"]["demand"][2] * 1.15
    assert r.s("commissions")[2] > base.s("commissions")[2]
