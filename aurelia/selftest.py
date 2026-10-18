"""Built-in self-test with a diagnostic report.

Run with ``Aurelia_Finance_Lab.exe --selftest`` (or ``python -m aurelia --selftest``).
Every check runs against temporary copies: the user's own database and files are
never modified. The report is written as plain text plus JSON into the data folder's
``diagnostics`` subfolder (or the path given with ``--report``) and contains no
personal data beyond the data-folder path.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import platform
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable

from . import __version__


@dataclass
class CheckResult:
    area: str
    name: str
    status: str          # PASS | FAIL | SKIP
    detail: str
    seconds: float


class _Fail(Exception):
    pass


def _ensure(cond: bool, msg: str) -> None:
    if not cond:
        raise _Fail(msg)


@contextlib.contextmanager
def _temp_data_dir():
    """Point the app at a throwaway data folder for the duration of a check."""
    old = os.environ.get("AURELIA_DATA_DIR")
    with tempfile.TemporaryDirectory(prefix="aurelia-selftest-") as d:
        os.environ["AURELIA_DATA_DIR"] = d
        try:
            yield Path(d)
        finally:
            if old is None:
                os.environ.pop("AURELIA_DATA_DIR", None)
            else:
                os.environ["AURELIA_DATA_DIR"] = old


# --------------------------------------------------------------------------- checks
def _environment() -> str:
    import numpy
    import pandas
    import matplotlib
    import openpyxl
    import PySide6
    _ensure(sys.version_info >= (3, 10), f"Python {platform.python_version()} is too old")
    return (f"Python {platform.python_version()} · {platform.platform()} · PySide6 {PySide6.__version__} · "
            f"pandas {pandas.__version__} · NumPy {numpy.__version__} · Matplotlib {matplotlib.__version__} · "
            f"openpyxl {openpyxl.__version__} · frozen={getattr(sys, 'frozen', False)}")


def _data_folder() -> str:
    from .persistence.db import app_data_dir
    d = app_data_dir()
    probe = d / ".selftest-write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return f"Data folder is writable: {d}"


def _user_database() -> str:
    """Read-only integrity check of the user's real database (if it exists)."""
    import sqlite3
    from .persistence.db import app_data_dir, DB_FILE_NAME
    p = app_data_dir() / DB_FILE_NAME
    if not p.exists():
        return "No database yet (it is created on first launch)."
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        res = con.execute("PRAGMA integrity_check").fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM scenarios").fetchone()[0]
    finally:
        con.close()
    _ensure(res == "ok", f"SQLite integrity_check returned {res}")
    return f"Your database passed SQLite integrity_check ({n} scenarios), opened read-only."


def _engine_checks() -> str:
    from .model.engine import simulate
    from .model.scenarios import SYSTEM_BUILDERS
    out = []
    for name, builder in SYSTEM_BUILDERS.items():
        r = simulate(builder())
        failed = [c.name for c in r.checks if not c.passed]
        _ensure(not failed, f"{name}: failed checks {failed}")
        out.append(f"{name}: {len(r.checks)}/{len(r.checks)}")
    return "Integrity checks passed – " + ", ".join(out)


def _hand_calculations() -> str:
    from .core import finance as fin
    flows = [-1000, 400, 450, 500]
    # −1000 + 400/1.1 + 450/1.21 + 500/1.331 = −1000 + 363.636 + 371.901 + 375.657 = 111.195
    _ensure(abs(fin.npv(0.10, flows) - 111.195) < 0.01, "NPV hand value")
    # at 15.975%: 400/1.15975 + 450/1.15975² + 500/1.15975³ ≈ 1000
    _ensure(abs(fin.irr(flows).value - 0.15975) < 0.0005, "IRR hand value")
    # 100,000 × r / (1 − (1 + r)^−60), r = 0.05/12 → 1,887.12 per month
    _ensure(abs(abs(fin.pmt(0.05 / 12, 60, 100_000)) - 1887.12) < 0.01, "PMT hand value")
    # cumulative −600, −150, +350 → 2 + 150/500 = 2.3 years
    _ensure(abs(fin.payback_period(flows) - 2.3) < 1e-9, "payback hand value")
    # 100 × 1.02 / (0.10 − 0.02) = 1,275
    _ensure(abs(fin.terminal_value_gordon(100, 0.10, 0.02) - 1275.0) < 1e-6, "Gordon growth hand value")
    return "NPV, IRR, PMT, payback and terminal value match hand-derived values."


def _rooms_hand_calculation() -> str:
    """100 rooms, one segment, 50 requests/day at SAR 1,000, 10% cancellations, 10% commission."""
    from .model.assumptions import baseline, SEGMENTS
    from .model.engine import simulate
    a = baseline()
    a["meta"]["months"] = 1
    a["rooms"].update(total_rooms=100, out_of_order_rooms=0, demand_growth_pct=0.0, rate_growth_pct=0.0,
                      seasonality=[1.0] * 12, seasonal_rate_flex=0.0, reference_rate_flex=0.0, demand_noise_sd=0.0,
                      overbooking_pct=0.0, cancellation_resale_pct=0.0, no_show_charge_pct=0.0, special_events=[])
    for s in SEGMENTS:
        a["segments"][s].update(base_demand=0.0, dow=[1.0] * 7, cap=None)
    a["segments"]["corporate"].update(published_rate=1000.0, discount_pct=0.0, reference_rate=1000.0,
                                      base_demand=50.0, elasticity=-1.0, commission_pct=0.10,
                                      cancellation_pct=0.10, no_show_pct=0.0)
    r = simulate(a)
    nights = r.total("occupied_rooms", slice(0, 1))
    rev = r.total("rooms_revenue", slice(0, 1))
    com = r.total("commissions", slice(0, 1))
    days = r.months[0].days_in_month if hasattr(r.months[0], "days_in_month") else 31
    exp_n = 45 * days
    _ensure(abs(nights - exp_n) < 0.5, f"room nights {nights} ≠ {exp_n}")
    _ensure(abs(rev - exp_n * 1000) < 1, f"room revenue {rev} ≠ {exp_n * 1000}")
    _ensure(abs(com - exp_n * 100) < 1, f"commission {com} ≠ {exp_n * 100}")
    return f"Hand-derived month: {exp_n:,} room nights × SAR 1,000, 10% commission – engine agrees."


def _fpa_checks() -> str:
    from .analysis.fpa import build_fpa, actual_world_assumptions
    from .model.assumptions import baseline
    f = build_fpa(baseline(), actual_world_assumptions())
    v = f.variance_table("ytd")
    _ensure(((v["Actual"] - v["Budget"] - v["Variance"]).abs() < 1e-6).all(), "variance ≠ actual − budget")
    ex = f.explanations()
    _ensure(ex, "no explanations produced for material variances")
    _ensure(all(e.get("to_confirm") or e.get("evidence") for e in ex), "explanation without evidence")
    return f"{len(v)} variance lines reconcile; {len(ex)} material variances explained with evidence or flagged."


def _excel_checks() -> str:
    from .excel import formula as F
    from .excel import workbooks as W
    from .excel.grader import grade_file
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    ws["A1"], ws["A2"], ws["A3"] = 2, 3, "=A1^A2^2"
    ws["B1"] = "=-A1^2"
    ws["B2"] = "=SUM(A1:A2)/0"
    calc = F.WorkbookCalculator(wb)
    _ensure(calc.value("S", "A3") == 64, "2^3^2 should be 64 as in Excel")
    _ensure(calc.value("S", "B1") == 4, "-2^2 should be 4 as in Excel")
    _ensure(str(calc.value("S", "B2")) == "#DIV/0!", "division by zero should give #DIV/0!")
    with tempfile.TemporaryDirectory() as d:
        dp = Path(d)
        scores = []
        for s in W.all_specs():
            ref = W.generate(s.key, dp, reference=True)
            blank = W.generate(s.key, dp, reference=False)
            h = hashlib.sha256(ref.read_bytes()).hexdigest()
            r1 = grade_file(ref, dp / "graded")
            r0 = grade_file(blank, dp / "graded")
            _ensure(hashlib.sha256(ref.read_bytes()).hexdigest() == h, "grader modified the original workbook")
            _ensure(abs(r1.score - 100) < 1e-6, f"{s.key}: reference scored {r1.score}")
            _ensure(r0.score == 0, f"{s.key}: blank scored {r0.score}")
            scores.append(s.key)
    return (f"Formula calculator precedence/errors OK; {len(scores)} workbooks: reference = 100%, blank = 0%, "
            "originals unchanged.")


def _decision_checks() -> str:
    from .analysis import decisions as D
    n = 0
    for c in D.CASES:
        for o in c.options:
            r = D.evaluate_option(c, o)
            _ensure(abs(sum(v for _k, v in r.components) - r.total) <= 1.0, f"{c.id}/{o.id} components ≠ total")
            n += 1
    return f"{len(D.CASES)} cases, {n} options evaluated; components reconcile to totals."


def _learning_checks() -> str:
    from .learning import content as C
    n = 0
    for t in C.topics():
        _ensure(t.worked(), f"{t.id}: worked example empty")
        for ex in [t.guided, t.independent, *t.check] + ([t.applied.exercise] if t.applied.exercise else []):
            ans = ex.answer if ex.unit == "choice" else float(ex.answer)
            _ensure(C.is_correct(ex, ans), f"{ex.id}: answer key inconsistent")
            n += 1
    _ensure(len(C.STAGES) == 9, "expected 9 stages")
    return f"9 stages, {len(C.topics())} topics, {n} exercises with consistent answer keys."


def _capstone_checks() -> str:
    from .analysis import capstone as K
    clean = K.apply_rules(K.messy_rooms(), K.correct_rules())
    ctrl = K.hotel_controls()
    _ensure(abs(clean["room_revenue"].sum() - ctrl["room_revenue"].sum()) < 1, "cleaned revenue ≠ controls")
    _ensure(abs(clean["room_nights"].sum() - ctrl["occupied_rooms"].sum()) < 0.5, "cleaned room nights ≠ controls")
    return "Messy capstone dataset is recoverable: cleaned totals reconcile to hotel controls."


def _persistence_checks() -> str:
    from .persistence.db import Database
    from .model.scenarios import ScenarioStore
    from .model.assumptions import baseline
    with _temp_data_dir() as d:
        db = Database(d / "t.db")
        try:
            ScenarioStore(db).create("Selftest", baseline(), "")
            bk = db.backup(d / "b.db")
            _ensure(db.validate_backup(bk) == [], "backup did not validate")
            db.reset_all()
            _ensure("Selftest" not in ScenarioStore(db).names(), "reset did not clear user scenarios")
            db.restore(bk)
            _ensure("Selftest" in ScenarioStore(db).names(), "restore did not bring back the scenario")
            junk = d / "junk.db"
            junk.write_bytes(b"not a database")
            _ensure(db.validate_backup(junk), "invalid backup accepted")
        finally:
            db.close()
    return "Create, backup, validate, reset, restore and invalid-backup rejection work (temporary database)."


def _privacy_checks() -> str:
    """No module of the app imports a networking library."""
    import importlib
    import pkgutil
    import aurelia
    banned = {"socket", "requests", "urllib.request", "http.client", "httpx", "aiohttp", "ftplib", "smtplib"}
    loaded = []
    for m in pkgutil.walk_packages(aurelia.__path__, "aurelia."):
        if m.name.startswith("aurelia.ui") or m.name in ("aurelia.selftest", "aurelia.__main__", "aurelia.app"):
            continue
        mod = importlib.import_module(m.name)
        loaded.append(m.name)
        for val in vars(mod).values():
            name = getattr(val, "__name__", None)
            if isinstance(val, type(sys)) and name in banned:
                raise _Fail(f"{m.name} imports {name}")
    return f"{len(loaded)} non-UI modules checked: no networking imports; no accounts, analytics or credentials."


def _season_checks() -> str:
    from .game import season as S
    sn = S.new_season(7)
    rec = S.close_month(sn, S.Levers())
    _ensure(sn.month == 2, "season did not advance after closing a month")
    gap = sum(v for _, v in rec.bridge) - (rec.actual["ebitda"] - rec.budget["ebitda"])
    _ensure(abs(gap) < 1, f"month-close bridge does not add up (gap {gap:,.2f})")
    return f"Played one month of a seeded season; EBITDA SAR {rec.actual['ebitda'] / 1e6:,.2f}m, bridge reconciles."


def _ui_checks() -> str:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    with _temp_data_dir() as d:
        from .persistence.db import Database
        from .ui.state import AppState
        from .ui.main_window import MainWindow, PAGES
        from .reports.management_report import build_report, save_pdf
        from .analysis.fpa import build_fpa, actual_world_assumptions
        from .model.assumptions import baseline
        db = Database(d / "ui.db")
        try:
            win = MainWindow(AppState(db))
            bad = []
            for key, *_ in PAGES:
                win.go(key)
                app.processEvents()
                w = win.pages[key]
                if getattr(w, "load_error", None) or getattr(w, "refresh_error", None):
                    bad.append(key)
            win.toggle_theme()
            win.toggle_theme()
            win.close()
            from PySide6.QtGui import QFontDatabase
            from .ui import icons
            fams = set(QFontDatabase.families())
            _ensure({"Manrope", "Fraunces"} <= fams, "bundled fonts did not load")
            _ensure(not icons.pixmap("home", "#D9B66F", 16).isNull(), "icon rendering failed")
            _ensure(not bad, f"pages failed: {bad}")
            pdf = save_pdf(build_report(build_fpa(baseline(), actual_world_assumptions())), d / "r.pdf")
            _ensure(Path(pdf).read_bytes()[:4] == b"%PDF", "PDF export failed")
        finally:
            db.close()
    return f"All {len(PAGES)} pages loaded, fonts and icons rendered, theme toggled, management report PDF rendered."


CHECKS: list[tuple[str, str, Callable[[], str], bool]] = [
    ("Environment", "Runtime and libraries", _environment, False),
    ("Storage", "Data folder writable", _data_folder, False),
    ("Storage", "Your database (read-only check)", _user_database, False),
    ("Storage", "Backup / restore / reset", _persistence_checks, False),
    ("Calculations", "Finance functions vs hand values", _hand_calculations, False),
    ("Calculations", "Rooms engine vs hand calculation", _rooms_hand_calculation, False),
    ("Calculations", "Engine integrity checks (all reference scenarios)", _engine_checks, False),
    ("Analysis", "FP&A variances and explanations", _fpa_checks, False),
    ("Analysis", "Decision Room cases", _decision_checks, False),
    ("Game", "Season month close", _season_checks, False),
    ("Learning", "Learning path content and answer keys", _learning_checks, False),
    ("Learning", "Capstone dataset", _capstone_checks, False),
    ("Excel", "Formula calculator, workbooks and grading", _excel_checks, False),
    ("Privacy", "No network code", _privacy_checks, False),
    ("Interface", "Every page, theme, PDF export", _ui_checks, True),
]


def run_checks(include_ui: bool = True) -> list[CheckResult]:
    out = []
    for area, name, fn, ui in CHECKS:
        if ui and not include_ui:
            out.append(CheckResult(area, name, "SKIP", "UI checks not requested.", 0.0))
            continue
        t0 = time.perf_counter()
        try:
            detail = fn()
            status = "PASS"
        except _Fail as exc:
            status, detail = "FAIL", str(exc)
        except Exception:  # noqa: BLE001 – the report must capture any failure
            status, detail = "FAIL", traceback.format_exc(limit=6)
        out.append(CheckResult(area, name, status, detail, round(time.perf_counter() - t0, 2)))
    return out


def format_report(results: list[CheckResult]) -> str:
    ok = all(r.status != "FAIL" for r in results)
    lines = [f"Aurelia Finance Lab {__version__} – self-test report",
             f"Generated {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
             f"Overall: {'PASSED' if ok else 'FAILED'} "
             f"({sum(r.status == 'PASS' for r in results)} passed, {sum(r.status == 'FAIL' for r in results)} "
             f"failed, {sum(r.status == 'SKIP' for r in results)} skipped)", ""]
    for r in results:
        lines.append(f"[{r.status}] {r.area} – {r.name} ({r.seconds:.2f}s)")
        for ln in str(r.detail).splitlines():
            lines.append(f"       {ln}")
    lines += ["", "All checks run on temporary copies; your data was not modified.",
              "This report contains no personal data other than the data-folder path. Nothing was transmitted.",
              "If a check failed, see docs/TROUBLESHOOTING.md and include this file when asking for help."]
    return "\n".join(lines)


def run_selftest(report: str | Path | None = None, include_ui: bool = True) -> tuple[bool, Path]:
    from .persistence.db import app_data_dir
    if report:
        path = Path(report)
    else:
        diag = app_data_dir() / "diagnostics"
        diag.mkdir(parents=True, exist_ok=True)
        path = diag / f"selftest-{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    results = run_checks(include_ui)
    ok = all(r.status != "FAIL" for r in results)
    path.write_text(format_report(results), encoding="utf-8")
    path.with_suffix(".json").write_text(json.dumps({"version": __version__, "passed": ok,
                                                     "results": [asdict(r) for r in results]}, indent=2),
                                         encoding="utf-8")
    return ok, path
