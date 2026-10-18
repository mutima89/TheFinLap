"""First vertical slice: load baseline, change a room rate, a demand assumption and an operating cost,
recalculate revenue / contribution / EBITDA / cash, compare with baseline, save and restore."""
import copy

import pytest

from aurelia.persistence.db import Database
from aurelia.ui.state import AppState
from aurelia.model.engine import simulate


@pytest.fixture
def state(tmp_path, qapp):
    db = Database(tmp_path / "t.db")
    st = AppState(db)
    yield st
    db.close()


def test_baseline_loaded(state):
    assert state.scenario_name == "Base case"
    k = state.result.kpis(state.result.year_slice(1))
    assert 0.5 < k["occupancy"] < 0.95
    assert k["ebitda"] > 0


def test_energy_cost_change_hand_derived(state):
    """ΔEBITDA = −ΔkWh cost × (1 − incentive fee %) because the incentive fee is 8% of (positive) GOP."""
    base = state.result
    sl = base.year_slice(1)
    kwh = base.total("energy_kwh", sl)
    assert state.set_driver("undistributed.energy_price_per_kwh", 0.35) == []
    new = state.result
    expected = -kwh * 0.05 * (1 - 0.08)
    assert new.total("ebitda", sl) - base.total("ebitda", sl) == pytest.approx(expected, rel=1e-9)
    assert new.total("total_revenue", sl) == pytest.approx(base.total("total_revenue", sl))
    assert new.s("cash")[11] < base.s("cash")[11]  # cash impact flows through


def test_rate_demand_cost_changes_and_save_restore(state):
    base = copy.deepcopy(state.result)
    assert state.set_driver("segments.corporate.published_rate", 1350) == []
    assert state.set_driver("segments.leisure_ota.base_demand", 36) == []
    assert state.set_driver("payroll.overtime_pct", 0.08) == []
    assert state.dirty
    new = state.result
    sl = new.year_slice(1)
    assert new.total("rooms_revenue", sl) != base.total("rooms_revenue", sl)
    assert new.total("ebitda", sl) != base.total("ebitda", sl)
    # Protected case: must save as new
    with pytest.raises(Exception):
        state.save()
    state.save_as("My pricing test")
    assert not state.dirty
    saved_ebitda = state.result.total("ebitda", sl)
    # Restore: load another scenario, then load ours back and get identical results
    state.load("Base case")
    assert state.result.total("ebitda", sl) == pytest.approx(base.total("ebitda", sl))
    state.load("My pricing test")
    assert state.result.total("ebitda", sl) == pytest.approx(saved_ebitda)
    assert state.draft["segments"]["corporate"]["published_rate"] == 1350
    # Independent re-run of the stored assumptions reproduces exactly
    assert simulate(state.store.get("My pricing test").assumptions).total("ebitda", sl) == saved_ebitda


def test_invalid_input_rejected_without_changing_draft(state):
    before = copy.deepcopy(state.draft)
    problems = state.set_driver("rooms.out_of_order_rooms", 999)
    assert problems
    assert state.draft == before


def test_undo_redo_and_revert(state):
    state.set_driver("payroll.overtime_pct", 0.10)
    assert state.undo()
    assert state.draft["payroll"]["overtime_pct"] == 0.05
    assert state.redo()
    assert state.draft["payroll"]["overtime_pct"] == 0.10
    state.revert()
    assert not state.dirty


def test_draft_autosaved_across_restart(tmp_path, qapp):
    db = Database(tmp_path / "x.db")
    st = AppState(db)
    st.set_driver("segments.group.cap", 30)
    db.close()
    db2 = Database(tmp_path / "x.db")
    st2 = AppState(db2)
    assert st2.draft["segments"]["group"]["cap"] == 30
    db2.close()


def test_audit_trail_records_changes(state):
    state.set_driver("segments.corporate.published_rate", 1300)
    entries = state.db.audit_entries()
    assert any(e["path"] == "segments.corporate.published_rate" for e in entries)
