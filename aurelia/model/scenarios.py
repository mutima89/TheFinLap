"""Scenario management: base/upside/downside cases, user scenarios, cloning,
checkpoints, audit trail, comparison and reset-to-baseline.

A scenario is a complete assumption tree (not a list of deltas) stored as JSON,
so it reproduces exactly – including its random seed – regardless of later
changes to the baseline.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from .assumptions import baseline, diff, from_json, to_json, validate, get_path, set_path, coerce_value, \
    ValidationError, SEGMENTS
from ..persistence.db import Database, now

SYSTEM_SCENARIOS = ["Base case", "Upside case", "Downside case"]


def upside_case() -> dict:
    a = baseline()
    for s in SEGMENTS:
        a["segments"][s]["base_demand"] *= 1.06
    a["rooms"]["rate_growth_pct"] = 0.045
    a["fnb"]["dinner_capture"] = 0.33
    a["undistributed"]["energy_price_per_kwh"] = 0.28
    return a


def downside_case() -> dict:
    a = baseline()
    for s in SEGMENTS:
        a["segments"][s]["base_demand"] *= 0.88
    a["rooms"]["rate_growth_pct"] = 0.0
    a["payroll"]["overtime_pct"] = 0.08
    a["undistributed"]["energy_price_per_kwh"] = 0.34
    a["working_capital"]["dso_days"] = 60.0
    return a


SYSTEM_BUILDERS = {"Base case": baseline, "Upside case": upside_case, "Downside case": downside_case}
SYSTEM_DESCRIPTIONS = {
    "Base case": "Baseline training assumptions for The Aurelia Grand (fictional).",
    "Upside case": "+6% demand, 4.5% rate growth, stronger dinner capture, cheaper energy.",
    "Downside case": "−12% demand, flat rates, higher overtime and energy price, slower collections.",
}


@dataclass
class Scenario:
    id: int
    name: str
    kind: str
    description: str
    assumptions: dict
    parent_id: int | None
    created_at: str
    updated_at: str

    @property
    def is_system(self) -> bool:
        return self.kind == "system"


class ScenarioError(RuntimeError):
    pass


class ScenarioStore:
    def __init__(self, db: Database):
        self.db = db
        self.ensure_system()

    def ensure_system(self) -> None:
        for name, builder in SYSTEM_BUILDERS.items():
            if self.db.one("SELECT id FROM scenarios WHERE name = ?", (name,)) is None:
                self.db.execute("INSERT INTO scenarios(name, kind, description, assumptions, created_at, updated_at)"
                                " VALUES (?, 'system', ?, ?, ?, ?)",
                                (name, SYSTEM_DESCRIPTIONS[name], to_json(builder()), now(), now()))

    # ---- read -----------------------------------------------------------------------
    def _row(self, row) -> Scenario:
        return Scenario(row["id"], row["name"], row["kind"], row["description"] or "", from_json(row["assumptions"]),
                        row["parent_id"], row["created_at"], row["updated_at"])

    def list(self) -> list[Scenario]:
        rows = self.db.query("SELECT * FROM scenarios ORDER BY kind DESC, id")
        return [self._row(r) for r in rows]

    def names(self) -> list[str]:
        return [s.name for s in self.list()]

    def get(self, name: str) -> Scenario:
        row = self.db.one("SELECT * FROM scenarios WHERE name = ?", (name,))
        if row is None:
            raise ScenarioError(f"No scenario named '{name}'.")
        return self._row(row)

    def get_by_id(self, sid: int) -> Scenario:
        row = self.db.one("SELECT * FROM scenarios WHERE id = ?", (sid,))
        if row is None:
            raise ScenarioError(f"No scenario with id {sid}.")
        return self._row(row)

    # ---- write ----------------------------------------------------------------------
    def create(self, name: str, assumptions: dict, description: str = "", parent: str | None = None) -> Scenario:
        name = name.strip()
        if not name:
            raise ScenarioError("Scenario name cannot be empty.")
        if self.db.one("SELECT id FROM scenarios WHERE name = ?", (name,)):
            raise ScenarioError(f"A scenario named '{name}' already exists.")
        problems = validate(assumptions)
        if problems:
            raise ValidationError(problems)
        parent_id = self.get(parent).id if parent else None
        cur = self.db.execute("INSERT INTO scenarios(name, kind, description, assumptions, parent_id, created_at, "
                              "updated_at) VALUES (?, 'user', ?, ?, ?, ?, ?)",
                              (name, description, to_json(assumptions), parent_id, now(), now()))
        sid = cur.lastrowid
        self.db.audit("create_scenario", sid, note=f"Created '{name}'" + (f" from '{parent}'" if parent else ""))
        return self.get_by_id(sid)

    def clone(self, source: str, new_name: str) -> Scenario:
        src = self.get(source)
        return self.create(new_name, copy.deepcopy(src.assumptions), f"Clone of {source}", parent=source)

    def save(self, name: str, assumptions: dict, note: str = "") -> Scenario:
        """Persist changes to a user scenario, logging every changed driver."""
        sc = self.get(name)
        if sc.is_system:
            raise ScenarioError(f"'{name}' is a protected reference case. Save your changes as a new scenario.")
        problems = validate(assumptions)
        if problems:
            raise ValidationError(problems)
        changes = diff(sc.assumptions, assumptions)
        if not changes:
            return sc
        self.db.execute("UPDATE scenarios SET assumptions = ?, updated_at = ? WHERE id = ?",
                        (to_json(assumptions), now(), sc.id))
        for path, old, new in changes:
            self.db.audit("change", sc.id, path, old, new, note)
        return self.get_by_id(sc.id)

    def set_driver(self, name: str, path: str, value: Any, note: str = "") -> Scenario:
        sc = self.get(name)
        a = copy.deepcopy(sc.assumptions)
        set_path(a, path, coerce_value(path, value))
        return self.save(name, a, note)

    def rename(self, old: str, new: str) -> None:
        sc = self.get(old)
        if sc.is_system:
            raise ScenarioError("Reference cases cannot be renamed.")
        if self.db.one("SELECT id FROM scenarios WHERE name = ?", (new,)):
            raise ScenarioError(f"A scenario named '{new}' already exists.")
        self.db.execute("UPDATE scenarios SET name = ?, updated_at = ? WHERE id = ?", (new, now(), sc.id))
        self.db.audit("rename", sc.id, note=f"{old} → {new}")

    def delete(self, name: str) -> None:
        sc = self.get(name)
        if sc.is_system:
            raise ScenarioError("Reference cases cannot be deleted.")
        self.db.execute("DELETE FROM checkpoints WHERE scenario_id = ?", (sc.id,))
        self.db.execute("DELETE FROM scenarios WHERE id = ?", (sc.id,))
        self.db.audit("delete_scenario", sc.id, note=f"Deleted '{name}'")

    def reset_to_baseline(self, name: str) -> Scenario:
        sc = self.get(name)
        if sc.is_system:
            return sc
        return self.save(name, baseline(), note="Reset to baseline")

    # ---- checkpoints ---------------------------------------------------------------
    def checkpoint(self, name: str, label: str) -> int:
        sc = self.get(name)
        cur = self.db.execute("INSERT INTO checkpoints(scenario_id, label, assumptions, created_at) VALUES (?,?,?,?)",
                              (sc.id, label, to_json(sc.assumptions), now()))
        self.db.audit("checkpoint", sc.id, note=f"Checkpoint '{label}'")
        return cur.lastrowid

    def checkpoints(self, name: str) -> list[dict]:
        sc = self.get(name)
        return [dict(r) for r in self.db.query("SELECT id, label, created_at FROM checkpoints WHERE scenario_id = ? "
                                               "ORDER BY id DESC", (sc.id,))]

    def restore_checkpoint(self, name: str, checkpoint_id: int) -> Scenario:
        sc = self.get(name)
        row = self.db.one("SELECT * FROM checkpoints WHERE id = ? AND scenario_id = ?", (checkpoint_id, sc.id))
        if row is None:
            raise ScenarioError("Checkpoint not found for this scenario.")
        return self.save(name, from_json(row["assumptions"]), note=f"Restored checkpoint '{row['label']}'")

    # ---- import / export ----------------------------------------------------------
    def import_json(self, text: str) -> list[str]:
        data = json.loads(text)
        if data.get("format") != "aurelia-scenarios":
            raise ScenarioError("Not an Aurelia scenario export file.")
        created = []
        for sc in data.get("scenarios", []):
            name = sc["name"]
            base_name, i = name, 2
            while self.db.one("SELECT id FROM scenarios WHERE name = ?", (name,)):
                name = f"{base_name} (imported {i})"
                i += 1
            from .assumptions import upgrade
            self.create(name, upgrade(sc["assumptions"]), sc.get("description", "Imported"))
            created.append(name)
        return created


def driver_value(a: dict, path: str) -> Any:
    return get_path(a, path)
