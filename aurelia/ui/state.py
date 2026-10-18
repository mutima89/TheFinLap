"""Application state shared by all pages.

The *working draft* is the scenario the user is experimenting with. Every
change is validated, recalculated through the single engine, logged to the
audit trail and auto-saved (as a draft) so that nothing is lost if the app
closes. Explicit "Save" writes the draft into a named scenario.
"""
from __future__ import annotations

import copy
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..core.kpis import fmt_value
from ..model.assumptions import baseline, validate, set_path, get_path, coerce_value, diff, SPEC_BY_PATH, upgrade
from ..model.engine import simulate_cached, SimulationResult
from ..model.scenarios import ScenarioStore, ScenarioError
from ..persistence.db import Database


class AppState(QObject):
    results_changed = Signal()
    scenarios_changed = Signal()
    theme_changed = Signal(str)
    progress_changed = Signal()
    navigate = Signal(str, object)  # page key, optional payload
    status = Signal(str)

    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.store = ScenarioStore(db)
        self.scenario_name: str = db.get_setting("current_scenario", "Base case")
        if self.scenario_name not in self.store.names():
            self.scenario_name = "Base case"
        self.compare_name: str = db.get_setting("compare_scenario", "Base case")
        if self.compare_name not in self.store.names():
            self.compare_name = "Base case"
        draft = db.get_setting("draft")
        if draft and draft.get("scenario") == self.scenario_name:
            self.draft = upgrade(draft["assumptions"])
            if validate(self.draft):
                self.draft = copy.deepcopy(self.store.get(self.scenario_name).assumptions)
        else:
            self.draft = copy.deepcopy(self.store.get(self.scenario_name).assumptions)
        self.currency = db.get_setting("currency", "SAR")
        self.theme = db.get_setting("theme", "dark")
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []

    # ---- results ----------------------------------------------------------------------
    @property
    def result(self) -> SimulationResult:
        return simulate_cached(self.draft)

    @property
    def saved(self) -> dict:
        return self.store.get(self.scenario_name).assumptions

    @property
    def compare_result(self) -> SimulationResult:
        return simulate_cached(self.store.get(self.compare_name).assumptions)

    @property
    def baseline_result(self) -> SimulationResult:
        return simulate_cached(baseline())

    @property
    def dirty(self) -> bool:
        return bool(diff(self.saved, self.draft))

    def pending_changes(self) -> list[tuple[str, Any, Any]]:
        return diff(self.saved, self.draft)

    # ---- formatting ---------------------------------------------------------------------
    def fx(self) -> float:
        return 1.0 if self.currency == "SAR" else float(self.draft["meta"].get("fx_usd_per_sar", 0.2667))

    def money(self, v: float | None, decimals: int | None = None) -> str:
        if v is None:
            return "n/a"
        return fmt_value(v * self.fx(), "currency", self.currency, decimals)

    def fmt(self, v: float | None, unit: str, decimals: int | None = None) -> str:
        if unit == "currency":
            return self.money(v, decimals)
        return fmt_value(v, unit, self.currency, decimals)

    # ---- editing ---------------------------------------------------------------------------
    def _autosave(self) -> None:
        self.db.set_setting("draft", {"scenario": self.scenario_name, "assumptions": self.draft})

    def set_driver(self, path: str, value: Any, note: str = "what-if") -> list[str]:
        """Change one driver in the working draft. Returns validation problems (empty = applied)."""
        new = copy.deepcopy(self.draft)
        old = get_path(new, path)
        try:
            set_path(new, path, coerce_value(path, value))
        except (TypeError, ValueError) as exc:
            return [f"Invalid value for {path}: {exc}"]
        problems = validate(new)
        if problems:
            return problems
        if get_path(new, path) == old:
            return []
        self.undo_stack.append(self.draft)
        self.redo_stack.clear()
        self.draft = new
        sid = self.store.get(self.scenario_name).id
        self.db.audit("what_if", sid, path, old, get_path(new, path), note)
        self._autosave()
        self.results_changed.emit()
        spec = SPEC_BY_PATH.get(path)
        self.status.emit(f"Recalculated after changing {spec.label if spec else path}.")
        return []

    def replace_draft(self, assumptions: dict, note: str) -> list[str]:
        problems = validate(assumptions)
        if problems:
            return problems
        self.undo_stack.append(self.draft)
        self.redo_stack.clear()
        sid = self.store.get(self.scenario_name).id
        for p, o, n in diff(self.draft, assumptions):
            self.db.audit("what_if", sid, p, o, n, note)
        self.draft = copy.deepcopy(assumptions)
        self._autosave()
        self.results_changed.emit()
        return []

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        self.redo_stack.append(self.draft)
        self.draft = self.undo_stack.pop()
        self._autosave()
        self.results_changed.emit()
        self.status.emit("Undid last change.")
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        self.undo_stack.append(self.draft)
        self.draft = self.redo_stack.pop()
        self._autosave()
        self.results_changed.emit()
        return True

    def revert(self) -> None:
        """Discard unsaved what-if changes (restore the saved scenario)."""
        self.undo_stack.append(self.draft)
        self.draft = copy.deepcopy(self.saved)
        self.db.audit("revert", self.store.get(self.scenario_name).id, note="Discarded unsaved changes")
        self._autosave()
        self.results_changed.emit()

    def reset_draft_to_baseline(self) -> None:
        self.replace_draft(baseline(), "Reset to baseline")

    def load(self, name: str) -> None:
        sc = self.store.get(name)
        self.scenario_name = name
        self.draft = copy.deepcopy(sc.assumptions)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.db.set_setting("current_scenario", name)
        self._autosave()
        self.results_changed.emit()
        self.scenarios_changed.emit()
        self.status.emit(f"Loaded scenario '{name}'.")

    def save(self) -> str:
        """Save the draft into the current scenario (or raise if it is a protected case)."""
        self.store.save(self.scenario_name, self.draft, note="Saved from working draft")
        self._autosave()
        self.scenarios_changed.emit()
        self.results_changed.emit()
        return self.scenario_name

    def save_as(self, name: str, description: str = "") -> str:
        parent = self.scenario_name
        self.store.create(name, self.draft, description or f"Derived from {parent}", parent=parent)
        self.scenario_name = name
        self.db.set_setting("current_scenario", name)
        self._autosave()
        self.scenarios_changed.emit()
        self.results_changed.emit()
        return name

    def reload(self) -> None:
        """Re-read everything from the database (after restore or reset)."""
        self.store.ensure_system()
        names = self.store.names()
        self.scenario_name = self.db.get_setting("current_scenario", "Base case")
        if self.scenario_name not in names:
            self.scenario_name = "Base case"
        self.compare_name = self.db.get_setting("compare_scenario", "Base case")
        if self.compare_name not in names:
            self.compare_name = "Base case"
        draft = self.db.get_setting("draft")
        self.draft = copy.deepcopy(self.store.get(self.scenario_name).assumptions)
        if draft and draft.get("scenario") == self.scenario_name:
            d = upgrade(draft["assumptions"])
            if not validate(d):
                self.draft = d
        self.currency = self.db.get_setting("currency", "SAR")
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.scenarios_changed.emit()
        self.results_changed.emit()
        self.progress_changed.emit()

    def set_compare(self, name: str) -> None:
        self.compare_name = name
        self.db.set_setting("compare_scenario", name)
        self.results_changed.emit()

    def set_currency(self, cur: str) -> None:
        self.currency = cur
        self.db.set_setting("currency", cur)
        self.results_changed.emit()

    def set_theme(self, name: str) -> None:
        self.theme = name
        self.db.set_setting("theme", name)
        self.theme_changed.emit(name)


__all__ = ["AppState", "ScenarioError"]
