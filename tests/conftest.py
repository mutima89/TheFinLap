import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aurelia.model.assumptions import baseline, SEGMENTS  # noqa: E402


def simple_hotel(months: int = 1) -> dict:
    """A deliberately tiny hotel whose results can be calculated by hand.

    100 rooms, one segment (corporate) with 50 requests/day at SAR 1,000,
    10% cancellations, 10% commission, nothing else. See tests/test_engine.py
    for the worked hand calculation.
    """
    a = baseline()
    a["meta"]["months"] = months
    r = a["rooms"]
    r.update(total_rooms=100, out_of_order_rooms=0, demand_growth_pct=0.0, rate_growth_pct=0.0,
             seasonality=[1.0] * 12, seasonal_rate_flex=0.0, reference_rate_flex=0.0, demand_noise_sd=0.0,
             overbooking_pct=0.0, cancellation_resale_pct=0.6, no_show_charge_pct=0.0, special_events=[])
    for s in SEGMENTS:
        seg = a["segments"][s]
        seg.update(base_demand=0.0, dow=[1.0] * 7, cap=None, credit_pct=0.0, deposit_pct=0.0)
    a["segments"]["corporate"].update(published_rate=1000.0, discount_pct=0.0, reference_rate=1000.0,
                                      base_demand=50.0, elasticity=-1.0, commission_pct=0.10,
                                      cancellation_pct=0.10, no_show_pct=0.0)
    f = a["fnb"]
    f.update(breakfast_capture=0, lunch_capture=0, dinner_capture=0, outside_covers_per_day=0,
             variable_labour_per_cover=0)
    a["spa"].update(therapists=0, external_treatments_per_day=0, treatments_per_occupied_room=0)
    a["events"].update(events_per_month=0)
    a["other_revenue"].update(per_occupied_room=0)
    a["rooms_costs"].update(housekeeping_per_occupied_room=20.0, guest_supplies_per_occupied_room=0,
                            laundry_per_occupied_room=0, other_expense_pct=0)
    p = a["payroll"]
    p.update(on_cost_pct=0.2, overtime_pct=0.0, annual_increase_pct=0.0)
    p["headcount"] = {k: 0 for k in p["headcount"]}
    p["headcount"]["rooms"] = 10
    p["monthly_salary"] = {k: 5000.0 for k in p["monthly_salary"]}
    u = a["undistributed"]
    u.update(ag_fixed_monthly=100000.0, ag_pct_revenue=0, it_fixed_monthly=0, marketing_monthly=0,
             pom_fixed_monthly=0, pom_pct_revenue=0, energy_fixed_kwh=0, energy_kwh_per_occupied_room=0,
             water_other_utilities_monthly=0, card_fee_pct=0, cost_inflation_pct=0)
    a["fees_fixed"].update(base_mgmt_fee_pct=0, incentive_fee_pct_gop=0, insurance_monthly=0,
                           property_tax_lease_monthly=0)
    a["tax"].update(vat_rate=0.15, vat_payment_lag_months=1, income_tax_rate=0.20, tax_payment_month=4)
    a["working_capital"].update(dso_days=45, dpo_days=31, other_credit_pct=0)
    a["capex"].update(ffe_reserve_pct=0.0, projects=[])
    ob = a["opening_balance"]
    ob.update(cash=500000.0, accounts_receivable=0, inventory=0, accounts_payable=0, vat_payable=0,
              deferred_revenue=0, tax_payable=0, share_capital=1_000_000.0,
              fixed_assets=[{"name": "Asset", "cost": 1_200_000.0, "accumulated": 0.0, "life_years": 10}])
    a["financing"].update(term_loan_opening=1_000_000.0, term_loan_rate=0.12, term_loan_monthly_repayment=0.0,
                          revolver_limit=0, minimum_cash=0, cash_interest_rate=0, dividend_payout_pct=0)
    return a


@pytest.fixture
def simple():
    return simple_hotel()


@pytest.fixture(scope="session")
def base_result():
    from aurelia.model.engine import simulate
    return simulate(baseline())
