"""Local SQLite persistence.

Location (per-user, never the install folder):
  Windows: %APPDATA%\\AureliaFinanceLab\\aurelia.db
  macOS:   ~/Library/Application Support/AureliaFinanceLab/aurelia.db
  Linux:   $XDG_DATA_HOME/AureliaFinanceLab/aurelia.db (default ~/.local/share)
Override with the AURELIA_DATA_DIR environment variable (used by tests).

Nothing is transmitted anywhere. No credentials are stored.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

DB_SCHEMA_VERSION = 1
APP_DIR_NAME = "AureliaFinanceLab"
DB_FILE_NAME = "aurelia.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'user',
    description TEXT DEFAULT '',
    assumptions TEXT NOT NULL,
    parent_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    assumptions TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    scenario_id INTEGER,
    action TEXT NOT NULL,
    path TEXT,
    old_value TEXT,
    new_value TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS progress (
    topic_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    best_score REAL DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    updated_at TEXT,
    data TEXT
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    activity_id TEXT NOT NULL,
    item_id TEXT,
    correct INTEGER,
    score REAL,
    answer TEXT,
    mistake_tag TEXT,
    hints_used INTEGER DEFAULT 0,
    competency TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    case_id TEXT NOT NULL,
    option_id TEXT,
    justification TEXT,
    scores TEXT
);
CREATE TABLE IF NOT EXISTS workbook_grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    workbook TEXT NOT NULL,
    file_name TEXT,
    score REAL,
    results TEXT
);
CREATE TABLE IF NOT EXISTS action_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    owner TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Open',
    variance_ref TEXT,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS forecast_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    name TEXT NOT NULL,
    scenario_name TEXT,
    status TEXT NOT NULL DEFAULT 'Draft',
    approved_by TEXT,
    notes TEXT,
    snapshot TEXT
);
CREATE TABLE IF NOT EXISTS custom_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    expression TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capstone (
    step TEXT PRIMARY KEY,
    data TEXT,
    score REAL,
    updated_at TEXT
);
"""

REQUIRED_TABLES = {"meta", "settings", "scenarios", "checkpoints", "audit_log", "progress", "attempts",
                   "decisions", "workbook_grades", "action_plans", "forecast_versions", "custom_metrics",
                   "capstone"}


def app_data_dir() -> Path:
    env = os.environ.get("AURELIA_DATA_DIR")
    if env:
        p = Path(env)
    elif sys.platform.startswith("win"):
        p = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_DIR_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RestoreError(RuntimeError):
    pass


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else app_data_dir() / DB_FILE_NAME
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._init()

    # ---- lifecycle ------------------------------------------------------------
    def _init(self) -> None:
        with self._lock, self.conn:
            self.conn.executescript(SCHEMA)
            self.conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
                              (str(DB_SCHEMA_VERSION),))
            self.conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('created_at', ?)", (now(),))

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ---- generic helpers -----------------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock, self.conn:
            return self.conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, tuple(params)))

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    # ---- settings --------------------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = "
                     "excluded.value", (key, json.dumps(value)))

    # ---- audit -----------------------------------------------------------------------
    def audit(self, action: str, scenario_id: int | None = None, path: str | None = None, old: Any = None,
              new: Any = None, note: str = "") -> None:
        self.execute("INSERT INTO audit_log(ts, scenario_id, action, path, old_value, new_value, note) "
                     "VALUES (?,?,?,?,?,?,?)", (now(), scenario_id, action, path,
                                                None if old is None else json.dumps(old),
                                                None if new is None else json.dumps(new), note))

    def audit_entries(self, scenario_id: int | None = None, limit: int = 500) -> list[sqlite3.Row]:
        if scenario_id is None:
            return self.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return self.query("SELECT * FROM audit_log WHERE scenario_id = ? ORDER BY id DESC LIMIT ?",
                          (scenario_id, limit))

    # ---- integrity, backup and restore ----------------------------------------------
    def integrity_check(self) -> list[str]:
        problems = []
        res = self.one("PRAGMA integrity_check")
        if res is None or res[0] != "ok":
            problems.append(f"SQLite integrity check failed: {res[0] if res else 'no result'}")
        tables = {r["name"] for r in self.query("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            problems.append("Missing tables: " + ", ".join(sorted(missing)))
        for row in self.query("SELECT id, name, assumptions FROM scenarios"):
            try:
                json.loads(row["assumptions"])
            except (TypeError, ValueError):
                problems.append(f"Scenario '{row['name']}' has corrupt assumptions JSON.")
        return problems

    def backup(self, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = sqlite3.connect(str(dest))
            try:
                self.conn.backup(target)
            finally:
                target.close()
        return dest

    @staticmethod
    def validate_backup(path: str | Path) -> list[str]:
        path = Path(path)
        if not path.exists():
            return [f"Backup file not found: {path}"]
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                ok = con.execute("PRAGMA integrity_check").fetchone()[0]
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                ver = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() \
                    if "meta" in tables else None
            finally:
                con.close()
        except sqlite3.DatabaseError as exc:
            return [f"Not a valid Aurelia backup: {exc}"]
        problems = []
        if ok != "ok":
            problems.append(f"Backup failed integrity check: {ok}")
        missing = REQUIRED_TABLES - tables
        if missing:
            problems.append("Backup is missing tables: " + ", ".join(sorted(missing)))
        if ver is None:
            problems.append("Backup has no schema version.")
        elif int(ver[0]) > DB_SCHEMA_VERSION:
            problems.append("Backup was created by a newer version of Aurelia Finance Lab.")
        return problems

    def restore(self, src: str | Path) -> Path:
        """Replace current data with a validated backup. Returns the safety copy path."""
        problems = self.validate_backup(src)
        if problems:
            raise RestoreError("; ".join(problems))
        safety = self.path.with_name(f"aurelia.pre-restore-{datetime.now():%Y%m%d-%H%M%S}.db")
        self.backup(safety)
        with self._lock:
            source = sqlite3.connect(str(src))
            try:
                source.backup(self.conn)
            finally:
                source.close()
        self._init()
        return safety

    def reset_all(self) -> Path:
        """Erase all user data (after a safety backup). Returns the safety backup path."""
        safety = self.path.with_name(f"aurelia.pre-reset-{datetime.now():%Y%m%d-%H%M%S}.db")
        self.backup(safety)
        with self._lock, self.conn:
            for t in REQUIRED_TABLES - {"meta"}:
                self.conn.execute(f"DELETE FROM {t}")
        return safety

    def export_scenarios_json(self, dest: str | Path, names: list[str] | None = None) -> Path:
        rows = self.query("SELECT name, kind, description, assumptions, created_at, updated_at FROM scenarios")
        data = [dict(r) | {"assumptions": json.loads(r["assumptions"])} for r in rows
                if names is None or r["name"] in names]
        Path(dest).write_text(json.dumps({"format": "aurelia-scenarios", "version": 1, "scenarios": data},
                                         indent=2), encoding="utf-8")
        return Path(dest)


def copy_file(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)
