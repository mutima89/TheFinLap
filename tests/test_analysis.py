"""Revenue Management, FP&A, sensitivity and investment analytics – hand-calculated cases."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from aurelia.analysis import rm, fpa, sensitivity as se, investment as inv
from aurelia.model.assumptions import baseline
from aurelia.model.engine import simulate


# ---------------------------------------------------------------- FP&A
def _fake(rn_a, adr_a):
    segs = {}
    from aurelia.model.assumptions import SEGMENTS
    for i, s in enumerate(SEGMENTS):
        rn = rn_a[i] if i < len(rn_a) else 0.0
        adr = adr_a[i] if i < len(adr_a) else 0.0
        segs[s] = {"room_nights": np.array([rn]), "revenue": np.array([rn * adr])}
    return SimpleNamespace(segments=segs)


def test_rate_mix_volume_hand_calculated():
    # Budget: A 100 RN @100, B 100 RN @50. Actual: A 80 @110, B 140 @50.
    # rate = (110−100)×80 = 800; mix = (80/220−0.5)×220×100 + (140/220−0.5)×220×50 = −3000 + 1500 = −1500
    # quantity = (220−200) × 75 = 1500; total = 15,800 − 15,000 = 800
    data = fpa.FPAData(budget=_fake([100, 100], [100, 50]), actual=_fake([80, 140], [110, 50]), forecast=None,
                       as_of=1)
    br = data.rooms_revenue_bridge(slice(0, 1))
    assert br["rate"] == pytest.approx(800)
    assert br["mix"] == pytest.approx(-1500)
    assert br["quantity"] == pytest.approx(1500)
    assert br["total"] == pytest.approx(800)
    assert br["residual"] == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("nature,var,expected", [
    ("revenue", 100, "F"), ("revenue", -100, "U"), ("expense", 100, "U"), ("expense", -100, "F"),
    ("profit", -5, "U"), ("expense", 0.0, "–")])
def test_variance_classification(nature, var, expected):
    assert fpa.classify(nature, var) == expected


def test_context_note_for_activity_driven_cost():
    note = fpa.classification_note("fnb_cogs", "U", 1.08)
    assert "flexible budget" in note


def test_materiality():
    m = fpa.Materiality(absolute=100_000, percent=0.05)
    assert m.is_material(150_000, 1_000_000)
    assert not m.is_material(150_000, 10_000_000)  # 1.5% – below percent threshold
    assert m.is_material(400_000, 100_000_000)  # very large absolute
    assert not m.is_material(50_000, 100_000)


@pytest.fixture(scope="module")
def fdata():
    return fpa.build_fpa(baseline(), baseline())


def test_le_combines_actuals_and_forecast(fdata):
    le = fdata.le("ebitda")
    assert le[:9] == pytest.approx(fdata.actual.s("ebitda")[:9])
    assert le[9:] == pytest.approx(fdata.forecast.s("ebitda")[9:12])


def test_occupancy_above_budget_but_ebitda_below(fdata):
    sl = fdata.ytd_slice()
    assert fdata.actual.kpis(sl)["occupancy"] > fdata.budget.kpis(sl)["occupancy"]
    assert fdata.actual.total("ebitda", sl) < fdata.budget.total("ebitda", sl)


def test_flexible_budget_identity(fdata):
    fb = fdata.flexible_budget(fdata.ytd_slice())
    for _, r in fb.iterrows():
        assert r["Activity variance"] + r["Spending variance"] == pytest.approx(r["Actual"] - r["Static budget"])


def test_payroll_rate_efficiency_sum(fdata):
    pv = fdata.payroll_variances(fdata.ytd_slice())
    for _, r in pv.iterrows():
        assert r["Rate variance"] + r["Headcount (efficiency) variance"] == pytest.approx(r["Total variance"])


def test_explanations_flag_unexplained_and_never_invent(fdata):
    ex = fdata.explanations()
    assert ex, "expected material variances in the fictional actuals"
    for e in ex:
        assert e["evidence"]
    rr = [e for e in fdata.explanations() if e["key"] == "commissions"]
    assert rr and "OTA" in rr[0]["evidence"][0]


def test_variance_table_signs(fdata):
    vt = fdata.variance_table("ytd")
    for _, r in vt.iterrows():
        assert r["Variance"] == pytest.approx(r["Actual"] - r["Budget"])


# ---------------------------------------------------------------- RM
def test_forecast_accuracy_hand():
    m = rm.forecast_accuracy(np.array([100, 200]), np.array([110, 180]))
    assert m["MAPE"] == pytest.approx(0.10)
    assert m["MAE"] == pytest.approx(15)
    assert m["Bias (mean error)"] == pytest.approx(-5)
    assert m["Tracking signal"] == pytest.approx(-10 / 15)


def test_mlos_hand_and_capacity():
    df = rm.mlos_exercise(capacity=1000, peak_night=3, mlos=1, arrivals=(10, 0, 0, 0, 0, 0, 0),
                          los_mix=(1, 0, 0, 0), rate=(100,) * 7)
    assert df.attrs["revenue"] == pytest.approx(1000)
    df2 = rm.mlos_exercise(mlos=2)
    assert (df2["Occupied"] <= 150 + 1e-9).all()


def test_overbooking_zero_has_no_walks():
    t = rm.overbooking_table(100, 0.9, 1000, 1500, levels=range(0, 5))
    assert t.loc[0, "Expected walks"] == 0
    assert (t["Expected walks"].diff().dropna() >= -1e-9).all()


def test_displacement_no_displacement_hand(simple):
    # 45 transient rooms/night, block of 30 fits: Δ room revenue = 30 × 2 × 500 = 30,000
    d = rm.displacement_analysis(simple, "2027-01-10", 2, 30, 500)
    assert d.displaced_room_nights == pytest.approx(0, abs=1e-9)
    assert d.delta_room_revenue == pytest.approx(30_000)


def test_displacement_with_displacement_hand(simple):
    # Block 70 → 30 rooms left: accept 30, 3 cancel, 60% of 3 resold → 28.8 transient vs 45 → 16.2 displaced/night
    d = rm.displacement_analysis(simple, "2027-01-10", 2, 70, 500)
    assert d.displaced_room_nights == pytest.approx(32.4)
    assert d.delta_room_revenue == pytest.approx(70 * 2 * 500 - 32.4 * 1000)


def test_segment_economics_net_adr(base_result):
    df = rm.segment_economics(base_result, base_result.year_slice(1))
    ota = df[df["key"] == "leisure_ota"].iloc[0]
    assert ota["Net ADR"] == pytest.approx(ota["Gross ADR"] * (1 - ota["Commission %"]))


def test_pace_curve_monotonic(base_result):
    pc = rm.pace_curve(base_result, 10)
    assert (pc["Total on the books"].diff().dropna() >= 0).all()
    assert pc["Total on the books"].iloc[-1] == pytest.approx(base_result.s("occupied_rooms")[10])


# ---------------------------------------------------------------- sensitivity
def test_one_way_energy_matches_hand_derivation():
    a = baseline()
    r = simulate(a)
    sl = r.year_slice(1)
    kwh = r.total("energy_kwh", sl)
    df = se.one_way(a, "undistributed.energy_price_per_kwh", [0.30, 0.40], "ebitda", sl)
    assert df["Result"][1] - df["Result"][0] == pytest.approx(-kwh * 0.10 * 0.92, rel=1e-9)


def test_operating_leverage_identity(base_result):
    ol = se.operating_leverage(base_result, base_result.year_slice(1))
    assert ol["contribution"] - ol["fixed_costs"] == pytest.approx(ol["ebitda"])
    assert ol["dol"] == pytest.approx(ol["contribution"] / ol["ebitda"])


def test_monte_carlo_reproducible():
    a = baseline()
    m1 = se.monte_carlo(a, se.DEFAULT_MC, iterations=20, seed=5)
    m2 = se.monte_carlo(a, se.DEFAULT_MC, iterations=20, seed=5)
    assert np.array_equal(m1["values"], m2["values"])
    assert m1["p5"] <= m1["p50"] <= m1["p95"]


def test_break_even_demand():
    a = baseline()
    be = se.break_even_demand(a, slice(0, 12))
    b = copy.deepcopy(a)
    for s in b["segments"].values():
        s["base_demand"] *= be["multiplier"]
    assert simulate(b).total("ebitda", slice(0, 12)) == pytest.approx(0, abs=5e4)


# ---------------------------------------------------------------- investment
def test_tax_shield_only_case_hand():
    # No operating benefit: FCF_t = 20% × 1,000,000/10 = 20,000 for 10 years.
    # NPV = −1,000,000 + 20,000 × 6.144567 = −877,108.66
    a = baseline()
    ev = inv.run_case("renovation", a, {"capex": 1_000_000, "ooo_rooms": 0, "ooo_months": 0, "rate_uplift": 0.0,
                                        "demand_uplift": 0.0, "life": 10, "discount": 0.10})
    assert ev.cash_flows[1] == pytest.approx(20_000)
    assert ev.npv == pytest.approx(-877_108.66, abs=0.05)
    assert "Do not proceed" in ev.recommendation


def test_all_cases_run_and_reconcile():
    a = baseline()
    for c in inv.CASES:
        ev = inv.run_case(c.key, a)
        assert ev.table["Free cash flow"].sum() == pytest.approx(sum(ev.cash_flows))
        assert ev.assumptions


def test_invalid_discount_rate_rejected():
    with pytest.raises(Exception):
        inv.run_case("spa", baseline(), {"discount": -1.5})


def test_custom_cash_flows_multiple_irr():
    ev = inv.custom_cash_flows([-100, 230, -132], 0.15)
    assert ev.irr.status == "multiple"
    assert any("multiple" in r.lower() for r in ev.reasons)
