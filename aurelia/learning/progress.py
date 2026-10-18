"""Progress, competency evidence and unlocking rules.

Competency is established by *practical* evidence, not quiz scores:

* Each attempt is stored with its activity type, competency, score, hints used and
  any diagnosed mistake tag.
* Activity weights: competency-check questions count least; independent exercises,
  applied tasks, graded Excel workbooks, decision cases and capstone steps count most.
* A competency is **Demonstrated** only when at least two distinct practical activities
  scored ≥ 70%, at least one of them without hints. Quiz-style evidence alone is capped
  at **Developing**, whatever the score.

Unlocking: within a topic, each step unlocks when the previous one is passed; a stage
unlocks when every topic of the previous stage has a passed competency check *and* a
passed applied task. Lesson completion alone unlocks nothing.

None of this is an accredited qualification; the app says so wherever a level appears.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from dataclasses import dataclass

COMPETENCIES = {
    "rm": "Revenue Management",
    "excel": "Excel & financial modelling",
    "fpa": "FP&A",
    "budget": "Budgeting & forecasting",
    "statements": "Financial statement integration",
    "invest": "Investment appraisal",
    "judgement": "Commercial judgement",
    "comms": "Executive communication",
}
PRACTICAL = {"independent", "applied", "workbook", "decision", "capstone"}
WEIGHT = {"check": 0.5, "guided": 0.5, "independent": 1.0, "applied": 1.5, "workbook": 1.5, "decision": 1.5,
          "capstone": 2.0}
PASS = 0.7
STEPS = ["guided", "independent", "applied", "check"]
DISCLAIMER = ("Competency levels are practice feedback from this application only. They are not an accredited "
              "qualification and do not guarantee employment.")


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def record_attempt(db, activity_type: str, activity_id: str, item_id: str | None, score: float,
                   competency: str | None, answer=None, mistake_tag: str | None = None, hints_used: int = 0) -> None:
    db.execute("INSERT INTO attempts (ts, activity_type, activity_id, item_id, correct, score, answer, mistake_tag, "
               "hints_used, competency) VALUES (?,?,?,?,?,?,?,?,?,?)",
               (_now(), activity_type, activity_id, item_id, int(score >= PASS), float(score),
                json.dumps(answer, default=str) if answer is not None else None, mistake_tag, int(hints_used),
                competency))


def set_topic_status(db, topic_id: str, status: str, score: float | None = None, data: dict | None = None) -> None:
    row = db.one("SELECT * FROM progress WHERE topic_id = ?", (topic_id,))
    best = max(float(row["best_score"] or 0) if row else 0.0, score or 0.0)
    attempts = (int(row["attempts"]) if row else 0) + (1 if score is not None else 0)
    old = json.loads(row["data"]) if row and row["data"] else {}
    old.update(data or {})
    db.execute("INSERT INTO progress (topic_id, status, best_score, attempts, updated_at, data) VALUES (?,?,?,?,?,?) "
               "ON CONFLICT(topic_id) DO UPDATE SET status=excluded.status, best_score=excluded.best_score, "
               "attempts=excluded.attempts, updated_at=excluded.updated_at, data=excluded.data",
               (topic_id, status, best, attempts, _now(), json.dumps(old)))


def topic_data(db, topic_id: str) -> dict:
    row = db.one("SELECT data FROM progress WHERE topic_id = ?", (topic_id,))
    return json.loads(row["data"]) if row and row["data"] else {}


def step_passed(db, topic_id: str, step: str) -> bool:
    return bool(topic_data(db, topic_id).get(f"{step}_passed"))


def mark_step(db, topic_id: str, step: str, score: float, hints: int = 0) -> None:
    d = topic_data(db, topic_id)
    passed = score >= PASS
    d[f"{step}_passed"] = d.get(f"{step}_passed", False) or passed
    d[f"{step}_best"] = max(float(d.get(f"{step}_best", 0)), score)
    if passed and hints == 0:
        d[f"{step}_independent"] = True
    status = "completed" if all(d.get(f"{s}_passed") for s in STEPS) else "in_progress"
    set_topic_status(db, topic_id, status, score, d)


def step_unlocked(db, topic_id: str, step: str) -> bool:
    i = STEPS.index(step)
    return i == 0 or step_passed(db, topic_id, STEPS[i - 1])


def topic_complete(db, topic_id: str) -> bool:
    return all(step_passed(db, topic_id, s) for s in STEPS)


def stage_unlocked(db, stage: int, topics_by_stage: dict[int, list[str]]) -> bool:
    if stage <= 1:
        return True
    prev = topics_by_stage.get(stage - 1, [])
    return all(step_passed(db, t, "check") and step_passed(db, t, "applied") for t in prev)


@dataclass
class CompetencyStatus:
    key: str
    label: str
    level: str          # Not started | Developing | Demonstrated
    score: float        # weighted 0..1
    practical_passes: int
    independent: bool
    attempts: int
    recurring_mistakes: list[tuple[str, int]]
    trend: float | None  # latest minus first score on repeated items


def competency_profile(db) -> list[CompetencyStatus]:
    rows = db.query("SELECT * FROM attempts ORDER BY id")
    out = []
    for key, lab in COMPETENCIES.items():
        rs = [r for r in rows if r["competency"] == key]
        if not rs:
            out.append(CompetencyStatus(key, lab, "Not started", 0.0, 0, False, 0, [], None))
            continue
        best: dict[tuple, tuple[float, str, int]] = {}
        first_last: dict[tuple, list[float]] = {}
        for r in rs:
            k = (r["activity_type"], r["activity_id"], r["item_id"])
            sc = float(r["score"] or 0)
            if k not in best or sc > best[k][0]:
                best[k] = (sc, r["activity_type"], int(r["hints_used"] or 0))
            first_last.setdefault(k, []).append(sc)
        wsum = sum(WEIGHT.get(t, 1.0) for _s, t, _h in best.values())
        score = sum(s * WEIGHT.get(t, 1.0) for s, t, _h in best.values()) / wsum if wsum else 0.0
        practical = [(s, h) for s, t, h in best.values() if t in PRACTICAL and s >= PASS]
        independent = any(h == 0 for _s, h in practical)
        level = "Demonstrated" if len(practical) >= 2 and independent and score >= PASS else "Developing"
        mistakes = Counter(r["mistake_tag"] for r in rs if r["mistake_tag"])
        rep = [(m, n) for m, n in mistakes.most_common() if n >= 2]
        deltas = [v[-1] - v[0] for v in first_last.values() if len(v) > 1]
        trend = sum(deltas) / len(deltas) if deltas else None
        out.append(CompetencyStatus(key, lab, level, score, len(practical), independent, len(rs), rep, trend))
    return out


def recent_mistakes(db, limit: int = 200) -> Counter:
    rows = db.query("SELECT mistake_tag FROM attempts WHERE mistake_tag IS NOT NULL ORDER BY id DESC LIMIT ?",
                    (limit,))
    return Counter(r["mistake_tag"] for r in rows)


def record_workbook(db, report) -> None:
    """Map a workbook grade to competencies (Excel plus the subject of the workbook)."""
    subject = {"revenue": "rm", "variance": "fpa", "three_statement": "statements", "investment": "invest"}
    s = report.score / 100
    record_attempt(db, "workbook", report.workbook, None, s, "excel", {"score": report.score})
    record_attempt(db, "workbook", report.workbook, "subject", s, subject.get(report.workbook))


def record_decision(db, case, grade) -> None:
    sc = grade.scores
    record_attempt(db, "decision", case.id, "judgement", (sc["judgement"] + sc["numerical"] + sc["evidence"]) / 3,
                   "judgement", {"overall": grade.overall})
    record_attempt(db, "decision", case.id, "comms", (sc["communication"] + sc["risk"]) / 2, "comms")
    cat = {"FP&A": "fpa", "Revenue Management": "rm", "Investment": "invest", "Forecasting": "budget",
           "Treasury & working capital": "statements"}.get(case.category)
    if cat:
        record_attempt(db, "decision", case.id, "subject", sc["numerical"] * 0.5 + sc["evidence"] * 0.5, cat)


def best_decision_score(db, case_id: str) -> float | None:
    rows = db.query("SELECT scores FROM decisions WHERE case_id = ?", (case_id,))
    return max(json.loads(r["scores"]).get("overall", 0) for r in rows) if rows else None


def best_workbook_score(db, key: str) -> float | None:
    row = db.one("SELECT MAX(score) AS s FROM workbook_grades WHERE workbook = ?", (key,))
    return float(row["s"]) if row and row["s"] is not None else None
