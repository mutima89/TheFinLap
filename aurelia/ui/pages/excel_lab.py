"""Excel Lab: generate practice workbooks, grade completed copies, coach on each cell."""
from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QHBoxLayout, QFileDialog, QCheckBox

from ...excel import workbooks as W
from ...excel.formula import SUPPORTED_FUNCTIONS
from ...excel.grader import grade_file, record, GradingError
from ...learning import coach
from ...learning import progress as P
from ...persistence.db import app_data_dir
from ..widgets import Page, card, label, button, Table, error


class ExcelLabPage(Page):
    def __init__(self, state):
        super().__init__("Excel Lab",
                         "Practise financial modelling in Microsoft Excel (or a compatible program). Generate "
                         "training workbooks with raw data, assumptions and instructions; complete them; then grade "
                         "your copy here. Aurelia never modifies your file: it grades a copy stored in its data "
                         "folder.")
        self.state = state
        f, fl = card()
        fl.addWidget(label("1 · Generate workbooks", "H3"))
        rows = [{"Workbook": s.title, "What you practise": s.objective, "Tasks": len(s.tasks)}
                for s in W.all_specs()]
        t = Table(min_height=150)
        t.set(pd.DataFrame(rows))
        t.fit_height(6)
        fl.addWidget(t)
        r = QHBoxLayout()
        self.with_ref = QCheckBox("Also generate the completed REFERENCE workbooks (model answers)")
        r.addWidget(self.with_ref)
        r.addStretch(1)
        r.addWidget(button("Generate into a folder…", self._generate, primary=True))
        fl.addLayout(r)
        self.gen_lbl = label("", "Muted", wrap=True)
        fl.addWidget(self.gen_lbl)
        self.body.addWidget(f)

        f, fl = card()
        fl.addWidget(label("2 · Grade a completed workbook", "H3"))
        fl.addWidget(label(
            "Important: the openpyxl library reads formulas but does not calculate them, and files saved by some "
            "programs contain no stored results. Aurelia therefore recalculates supported formulas with its own "
            "documented calculator and compares with Excel's saved values. Supported functions: "
            + ", ".join(sorted(SUPPORTED_FUNCTIONS)) + ". Cells using other functions are graded on Excel's saved "
            "value and flagged.", "Muted", wrap=True))
        r = QHBoxLayout()
        r.addWidget(button("Choose workbook and grade…", self._grade, primary=True))
        r.addStretch(1)
        fl.addLayout(r)
        self.grade_lbl = label("", wrap=True)
        fl.addWidget(self.grade_lbl)
        self.tasks = Table(min_height=300)
        self.tasks.clicked.connect(self._coach_cell)
        fl.addWidget(self.tasks)
        self.coach_lbl = label("Click a row for the coach's explanation.", "Muted", wrap=True)
        fl.addWidget(self.coach_lbl)
        self.recs = Table(min_height=90)
        fl.addWidget(self.recs)
        self.body.addWidget(f)

        f, fl = card()
        fl.addWidget(label("Grading history", "H3"))
        self.hist = Table(min_height=140)
        fl.addWidget(self.hist)
        self.body.addWidget(f)
        self._report = None
        self._history()

    def _generate(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for the workbooks")
        if not d:
            return
        try:
            paths = W.generate_all(d, self.with_ref.isChecked())
        except OSError as exc:
            error(self, "Could not write files", str(exc))
            return
        self.gen_lbl.setText("Created (existing files are never overwritten):<br>" +
                             "<br>".join(p.name for p in paths))
        self.state.status.emit(f"Generated {len(paths)} workbooks in {d}")

    def _grade(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose a completed workbook", "", "Excel workbook (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            rep = grade_file(path, app_data_dir() / "graded")
        except GradingError as exc:
            error(self, "Cannot grade", str(exc))
            return
        self._show(rep)
        record(self.state.db, rep)
        P.record_workbook(self.state.db, rep)
        self.state.progress_changed.emit()
        self._history()

    def _show(self, rep):
        self._report = rep
        self.grade_lbl.setText(f"<h3>{rep.title}: {rep.score:.1f}%</h3>File: {rep.file_name}<br>Graded copy: "
                               f"{rep.graded_copy}<br>" + "<br>".join(rep.notes))
        rows = [{"Task": t.id, "Cell": f"{t.sheet}!{t.cell}", "Title": t.title, "Status": t.status,
                 "Your value": "" if t.got is None else (f"{t.got:,.4f}" if isinstance(t.got, float) and abs(t.got) < 10
                                                        else (f"{t.got:,.2f}" if isinstance(t.got, float) else str(t.got))),
                 "Expected": (f"{t.expected:,.4f}" if isinstance(t.expected, float) and abs(t.expected) < 10
                              else (f"{t.expected:,.2f}" if isinstance(t.expected, float) else str(t.expected))),
                 "Feedback": " ".join(t.feedback)} for t in rep.tasks]
        self.tasks.set(pd.DataFrame(rows), nature={"Status": lambda r, v: "good" if v == "correct" else
                                                   ("bad" if v in ("wrong", "missing") else None)})
        self.recs.set(pd.DataFrame([{"Reconciliation check": n, "Result": "PASS" if ok else "FAIL", "Detail": m}
                                    for n, ok, m in rep.reconciliations]),
                      nature={"Result": lambda r, v: "good" if v == "PASS" else "bad"})
        self.recs.fit_height(4)

    def _coach_cell(self, idx):
        if not self._report:
            return
        t = self._report.tasks[idx.row()]
        self.coach_lbl.setText(coach.explain_workbook_task(t))

    def _history(self):
        rows = [{"When": r["ts"].replace("T", " "), "Workbook": r["workbook"], "File": r["file_name"],
                 "Score": f"{r['score']:.1f}%"}
                for r in self.state.db.query("SELECT * FROM workbook_grades ORDER BY id DESC LIMIT 50")]
        self.hist.set(pd.DataFrame(rows) if rows else pd.DataFrame({"When": [], "Workbook": [], "File": [],
                                                                    "Score": []}))
