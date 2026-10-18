"""Grade a learner's copy of a training workbook.

Safety: the learner's file is copied into the application's data folder first and
only the copy is opened (read-only). The original is never modified.

Each task is scored on two parts:
  * value (70%) – the result matches the independently calculated answer;
  * method (30%) – the cell contains a formula (not a typed number) and uses one of
    the expected function families where the task names them.

The value is taken from Aurelia's own recalculation of the formula (openpyxl does not
calculate). If a function is outside the supported list, Excel's saved (cached) value
is used instead and the result says so. Where both exist and disagree, the result
notes that the file may not have been recalculated before saving.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path

import openpyxl

from .formula import WorkbookCalculator, UnsupportedFormula, XLError, functions_used, _to_serial
from .workbooks import Task, WorkbookSpec, spec, identify, _close

VALUE_WEIGHT, METHOD_WEIGHT = 0.7, 0.3


@dataclass
class TaskResult:
    id: str
    title: str
    cell: str
    sheet: str
    status: str            # correct | partial | wrong | missing
    score: float           # 0..1 of the task's points
    points: float
    got: object
    expected: object
    formula: str | None
    feedback: list[str] = field(default_factory=list)
    concept: str = ""


@dataclass
class GradeReport:
    workbook: str
    title: str
    file_name: str
    graded_copy: str
    score: float           # 0..100
    tasks: list[TaskResult]
    reconciliations: list[tuple[str, bool, str]]
    notes: list[str]

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, default=str)

    def summary_by_concept(self) -> dict[str, float]:
        agg: dict[str, list[float]] = {}
        for t in self.tasks:
            agg.setdefault(t.concept or "Other", [0.0, 0.0])
            agg[t.concept or "Other"][0] += t.score * t.points
            agg[t.concept or "Other"][1] += t.points
        return {k: (v[0] / v[1] if v[1] else 0.0) for k, v in agg.items()}


class GradingError(Exception):
    pass


def _norm(v):
    if isinstance(v, (dt.datetime, dt.date)):
        return float(_to_serial(v))
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return float(v)
    return v


def _value_matches(got, t: Task) -> bool:
    got = _norm(got)
    if isinstance(t.expected, str):
        return isinstance(got, str) and got.strip().lower() == t.expected.strip().lower()
    if isinstance(got, bool) or not isinstance(got, (int, float)):
        return False
    return _close(float(got), float(t.expected), t.tolerance_abs, t.tolerance_rel)


def _mistake(got, t: Task) -> str | None:
    got = _norm(got)
    for val, msg in t.mistakes:
        if isinstance(val, str):
            if isinstance(got, str) and got.strip().lower() == val.lower():
                return msg
        elif isinstance(got, (int, float)) and not isinstance(got, bool) and \
                _close(float(got), float(val), max(t.tolerance_abs, 0.01), 1e-6):
            return msg
    return None


def safe_copy(src: str | Path, dest_dir: str | Path) -> Path:
    src = Path(src)
    if not src.exists():
        raise GradingError(f"File not found: {src}")
    if src.suffix.lower() not in (".xlsx", ".xlsm"):
        raise GradingError("Only .xlsx / .xlsm workbooks can be graded.")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = dest_dir / f"{src.stem}.graded-copy-{stamp}{src.suffix}"
    shutil.copy2(src, dest)
    return dest


def grade_file(path: str | Path, work_dir: str | Path, key: str | None = None) -> GradeReport:
    copy = safe_copy(path, work_dir)
    try:
        wb_f = openpyxl.load_workbook(copy, data_only=False, read_only=False)
        wb_v = openpyxl.load_workbook(copy, data_only=True, read_only=False)
    except Exception as exc:  # corrupted or not a workbook
        raise GradingError(f"Could not open the workbook: {exc}") from exc
    key = key or identify(wb_f)
    if key is None:
        raise GradingError("This does not look like an Aurelia training workbook (sheet names do not match).")
    rep = grade_workbook(wb_f, wb_v, spec(key))
    rep.file_name = Path(path).name
    rep.graded_copy = str(copy)
    return rep


def grade_workbook(wb_f, wb_v, s: WorkbookSpec) -> GradeReport:
    calc = WorkbookCalculator(wb_f)
    notes: list[str] = []
    missing_sheets = {t.sheet for t in s.tasks} - set(wb_f.sheetnames)
    if missing_sheets:
        notes.append("Missing sheets: " + ", ".join(sorted(missing_sheets)) + ". Were tabs renamed or deleted?")
    results: list[TaskResult] = []
    cached_mismatch = 0
    used_cached = 0

    def value_of(sheet: str, cell: str):
        if sheet not in wb_f.sheetnames:
            return None
        try:
            v = calc.value(sheet, cell)
        except UnsupportedFormula:
            v = wb_v[sheet][cell].value
        return None if isinstance(v, XLError) else v

    for t in s.tasks:
        if t.sheet not in wb_f.sheetnames:
            results.append(TaskResult(t.id, t.title, t.cell, t.sheet, "missing", 0.0, t.points, None, t.expected,
                                      None, ["Sheet missing."], t.concept))
            continue
        raw = wb_f[t.sheet][t.cell].value
        cached = wb_v[t.sheet][t.cell].value
        fb: list[str] = []
        is_formula = isinstance(raw, str) and raw.startswith("=")
        if raw is None or raw == "":
            results.append(TaskResult(t.id, t.title, t.cell, t.sheet, "missing", 0.0, t.points, None, t.expected,
                                      None, ["No answer yet." + (f" Hint: {t.hint}" if t.hint else "")], t.concept))
            continue
        if is_formula:
            try:
                got = calc.value(t.sheet, t.cell)
                if cached is not None and not isinstance(got, XLError):
                    same = (_norm(cached) == _norm(got)) if isinstance(cached, str) or isinstance(got, str) else \
                        (isinstance(_norm(cached), (int, float)) and isinstance(_norm(got), (int, float)) and
                         _close(float(_norm(cached)), float(_norm(got)), 0.01, 1e-6))
                    if not same:
                        cached_mismatch += 1
                        fb.append(f"Excel's saved value ({cached}) differs from the recalculated value; save the file "
                                  "in Excel after editing so values are recalculated.")
            except UnsupportedFormula as u:
                got = cached
                used_cached += 1
                fb.append(f"{u} is not in Aurelia's supported function list; graded on Excel's saved value.")
        else:
            got = raw
        if isinstance(got, XLError):
            fb.append(f"The formula returns {got}.")
            got_v = None
        else:
            got_v = got
        value_ok = got_v is not None and _value_matches(got_v, t)
        method = 0.0
        if is_formula:
            used = functions_used(raw)
            if t.functions_any:
                if any(fs <= used for fs in t.functions_any):
                    method = 1.0
                else:
                    method = 0.5
                    opts = " or ".join("+".join(sorted(fs)) for fs in t.functions_any)
                    fb.append(f"Expected method: {opts}.")
            else:
                method = 1.0
        else:
            fb.append("This is a typed value, not a formula. Build it with a formula so it updates when inputs change.")
        score = (VALUE_WEIGHT if value_ok else 0.0) + METHOD_WEIGHT * method
        if not value_ok:
            m = _mistake(got_v, t) if got_v is not None else None
            if m:
                fb.insert(0, m)
            elif got_v is not None:
                fb.insert(0, "Value does not match the expected result." + (f" Hint: {t.hint}" if t.hint else ""))
            score = METHOD_WEIGHT * method * 0.5   # some credit for a reasonable approach
        status = "correct" if score >= 0.999 else ("partial" if value_ok else "wrong")
        results.append(TaskResult(t.id, t.title, t.cell, t.sheet, status, round(score, 4), t.points, _norm(got_v),
                                  t.expected, raw if is_formula else None, fb, t.concept))

    recs = []
    for r in s.reconciliations:
        try:
            ok, msg = r.check(value_of)
        except Exception as exc:  # defensive: a learner's workbook can be in any state
            ok, msg = False, f"Could not evaluate: {exc}"
        recs.append((r.name, bool(ok), msg))
    total_pts = sum(t.points for t in s.tasks)
    got_pts = sum(r.score * r.points for r in results)
    score = 100.0 * got_pts / total_pts if total_pts else 0.0
    if cached_mismatch:
        notes.append(f"{cached_mismatch} cell(s) had saved values that differ from recalculation.")
    if used_cached:
        notes.append(f"{used_cached} cell(s) graded on Excel's saved value (unsupported function).")
    notes.append("Scores are practice feedback only, not a qualification.")
    return GradeReport(s.key, s.title, "", "", round(score, 1), results, recs, notes)


def record(db, rep: GradeReport) -> None:
    db.execute("INSERT INTO workbook_grades (ts, workbook, file_name, score, results) VALUES (?,?,?,?,?)",
               (dt.datetime.now().isoformat(timespec="seconds"), rep.workbook, rep.file_name, rep.score,
                rep.to_json()))
