"""Executive Decision Room."""
from __future__ import annotations

import json

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QListWidget, QListWidgetItem, QTabWidget,
                               QCheckBox, QRadioButton, QButtonGroup, QTextEdit, QDoubleSpinBox, QGridLayout)

from ...analysis import decisions as D
from ...learning import progress as P
from ...persistence.db import now
from ..common import formatters
from ..widgets import Page, card, label, button, Table, error, confirm


class DecisionPage(Page):
    def __init__(self, state):
        super().__init__("Executive Decision Room",
                         "Realistic management situations. Inspect the evidence, identify the drivers, compare the "
                         "alternatives the engine has quantified, decide and justify. Several answers can be "
                         "defensible: the rubric rewards reasoning, evidence and risk awareness, not only the choice.")
        self.state = state
        self.case: D.Case | None = None
        self._viewed = False
        self._ran = False
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(300)
        self.list.setMaximumWidth(330)
        self.list.setSpacing(4)
        self.list.setWordWrap(True)
        self.list.currentRowChanged.connect(self._select)
        row.addWidget(self.list)
        right = QVBoxLayout()
        self.title = label("", "H2")
        self.meta = label("", "Muted")
        self.situation = label("", wrap=True)
        right.addWidget(self.title)
        right.addWidget(self.meta)
        right.addWidget(self.situation)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._tab_changed)
        right.addWidget(self.tabs, 1)
        row.addLayout(right, 1)
        self.body.addLayout(row, 1)

        # 1 evidence
        w = QWidget()
        self.ev_lay = QVBoxLayout(w)
        self.tabs.addTab(w, "1 · Evidence")
        # 2 drivers
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Which drivers explain this situation? Select all that apply.", "H3"))
        self.drv_box = QVBoxLayout()
        lay.addLayout(self.drv_box)
        lay.addStretch(1)
        self.tabs.addTab(w, "2 · Drivers")
        # 3–5 analysis
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Steps 3–5: build the comparison, compare the alternatives and quantify them. The engine "
                            "runs each option against the same starting position. The component lines add up to the "
                            "decision metric; the total itself is hidden until you submit your estimate.", "Muted",
                            wrap=True))
        r = QHBoxLayout()
        r.addWidget(button("Run comparison", self._run, primary=True))
        r.addWidget(button("Load the starting position into the Scenario Lab", self._load_lab,
                           tip="Replaces your working draft (undo with Ctrl+Z) so you can modify the analysis "
                               "yourself."))
        r.addStretch(1)
        lay.addLayout(r)
        self.cmp_table = Table(min_height=260)
        lay.addWidget(self.cmp_table)
        self.cmp_note = label("", "Muted", wrap=True)
        lay.addWidget(self.cmp_note)
        lay.addStretch(1)
        self.tabs.addTab(w, "3–5 · Analyse")
        # 6–7 decide
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("6 · Select a recommendation", "H3"))
        self.opt_box = QVBoxLayout()
        lay.addLayout(self.opt_box)
        self.opt_group = QButtonGroup(self)
        g = QGridLayout()
        self.est_lbl = label("Your estimate of the decision metric for the chosen option:")
        self.est = QDoubleSpinBox()
        self.est.setRange(-1e10, 1e10)
        self.est.setDecimals(0)
        self.est.setGroupSeparatorShown(True)
        self.est.setPrefix("SAR ")
        g.addWidget(self.est_lbl, 0, 0)
        g.addWidget(self.est, 0, 1)
        lay.addLayout(g)
        lay.addWidget(label("7 · Executive justification (40–180 words): lead with the recommendation, cite numbers, "
                            "name the key risk or assumption, close with a next step.", "H3", wrap=True))
        self.just = QTextEdit()
        self.just.setMinimumHeight(140)
        self.just.textChanged.connect(self._count)
        lay.addWidget(self.just)
        self.count_lbl = label("0 words", "Muted")
        lay.addWidget(self.count_lbl)
        r = QHBoxLayout()
        r.addWidget(button("Submit decision", self._submit, primary=True))
        r.addStretch(1)
        lay.addLayout(r)
        self.tabs.addTab(w, "6–7 · Decide")
        # outcome
        w = QWidget()
        lay = QVBoxLayout(w)
        self.out_lbl = label("Submit a decision to see the assessment and what happened.", wrap=True)
        lay.addWidget(self.out_lbl)
        self.score_table = Table(min_height=190)
        lay.addWidget(self.score_table)
        self.out_detail = label("", wrap=True)
        lay.addWidget(self.out_detail)
        lay.addWidget(label("Previous attempts", "H3"))
        self.hist = Table(min_height=140)
        lay.addWidget(self.hist)
        lay.addStretch(1)
        self.tabs.addTab(w, "Outcome")
        self._fill_list()
        self.list.setCurrentRow(0)

    # ------------------------------------------------------------------ list
    def _fill_list(self):
        cur = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for c in D.CASES:
            best = P.best_decision_score(self.state.db, c.id)
            mark = "✓ " if best is not None else "○ "
            it = QListWidgetItem(f"{mark}{c.title}\n   {c.category}" + (f" · best {best:.0f}" if best is not None
                                                                           else ""))
            it.setData(Qt.UserRole, c.id)
            self.list.addItem(it)
        self.list.blockSignals(False)
        if cur >= 0:
            self.list.setCurrentRow(cur)

    def _select(self, row):
        if row < 0:
            return
        c = D.CASES[row]
        self.case = c
        self._viewed = self._ran = False
        self.title.setText(c.title)
        self.meta.setText(f"{c.category} · analysis window {c.window_label()} · decision metric: "
                          f"{D.metric_label(c)}")
        self.situation.setText(f"{c.situation}<br><b>{c.question}</b>")
        # evidence
        while self.ev_lay.count():
            it = self.ev_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for title, obj in D.evidence(c):
            f, fl = card()
            fl.addWidget(label(title, "H3"))
            if isinstance(obj, pd.DataFrame):
                t = Table(min_height=120)
                t.set(*self._fmt_frame(obj))
                t.fit_height(26)
                fl.addWidget(t)
            else:
                fl.addWidget(label(str(obj), wrap=True))
            self.ev_lay.addWidget(f)
        self.ev_lay.addStretch(1)
        # drivers
        while self.drv_box.count():
            it = self.drv_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.drv_checks = []
        for d, _rel in sorted(c.drivers, key=lambda x: x[0]):
            cb = QCheckBox(d)
            self.drv_box.addWidget(cb)
            self.drv_checks.append(cb)
        # options
        for b in self.opt_group.buttons():
            self.opt_group.removeButton(b)
        while self.opt_box.count():
            it = self.opt_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for i, o in enumerate(c.options):
            # radio buttons cannot wrap, so the long description goes in a wrapping label beneath
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 4)
            hl.setSpacing(0)
            rb = QRadioButton(o.label)
            rb.setProperty("opt", o.id)
            rb.setToolTip(o.description)
            self.opt_group.addButton(rb, i)
            hl.addWidget(rb)
            desc = label(o.description, "Muted", wrap=True)
            desc.setContentsMargins(24, 0, 0, 0)
            hl.addWidget(desc)
            self.opt_box.addWidget(holder)
        self.est_lbl.setText(f"Your estimate of {D.metric_label(c)} for the chosen option (SAR"
                             f"{', NPV at the case discount rate' if c.metric == 'npv' else ''}):")
        self.est.setPrefix("SAR ")
        self.est.setValue(0)
        self.just.clear()
        self.cmp_table.set(pd.DataFrame())
        self.cmp_note.setText("")
        self._history()
        self.tabs.setCurrentIndex(0)
        self._viewed = True

    def _fmt_frame(self, df: pd.DataFrame):
        st = self.state
        if "unit" in df.columns:
            view = df.drop(columns=["unit"]).copy()
            units = list(df["unit"])
            for col in view.columns[1:]:
                view[col] = [("n/a" if v is None else (f"{v * 100:.1f}%" if u == "pct" else st.money(v)))
                             for v, u in zip(df[col], units)]
            return view, {}
        money_cols = [c for c in df.columns if df[c].dtype.kind == "f" and df[c].abs().max() > 50]
        small = [c for c in df.columns if df[c].dtype.kind == "f" and c not in money_cols]
        f = formatters(st, money_cols=money_cols)
        for c in small:
            f[c] = (lambda v: f"{v * 100:.1f}%") if df[c].abs().max() <= 1.0 else (lambda v: f"{v:,.2f}")
        return df, f

    def _tab_changed(self, i):
        if i == 0:
            self._viewed = True

    # ------------------------------------------------------------------ analysis
    def _run(self):
        c = self.case
        if not c:
            return
        rows = []
        results = [D.evaluate_option(c, o) for o in c.options]
        names = [n for n, _v in results[0].components]
        for r in results:
            for n, _v in r.components:
                if n not in names:
                    names.append(n)
        for n in names:
            row = {"Line": n}
            for r in results:
                row[r.option.label] = dict(r.components).get(n, 0.0)
            rows.append(row)
        info_keys = list(results[0].info.keys())
        for k in info_keys:
            if k in ("Δ EBITDA", "Δ Closing cash", "Δ Revolver") and c.metric != "cash":
                continue
            row = {"Line": f"(info) {k}"}
            for r in results:
                row[r.option.label] = r.info.get(k)
            rows.append(row)
        df = pd.DataFrame(rows)
        st = self.state
        pct_rows = {i for i, ln in enumerate(df["Line"]) if "IRR" in ln or "%" in ln or "margin" in ln.lower()}

        def fmt(v, row=None):
            if v is None or v != v:
                return "n/a"
            if row in pct_rows:
                return f"{v * 100:.1f}%"
            return f"{v:,.2f}" if abs(v) < 100 else st.money(v)
        shown = pd.DataFrame({"Line": df["Line"]})
        for col in df.columns[1:]:
            shown[col] = [fmt(v, i) for i, v in enumerate(df[col])]
        self.cmp_table.set(shown)
        self.cmp_table.fit_height(20)
        self._ran = True
        self.cmp_note.setText(
            f"Add the component lines (with their signs) to get {D.metric_label(c)} for an option. "
            "Info rows are context, not part of the total. Each option is compared with the starting position "
            "over the analysis window" + (" (NPV over the asset life for the investment case)." if c.metric == "npv"
                                          else "."))

    def _load_lab(self):
        if not self.case:
            return
        if not confirm(self, "Load case into Scenario Lab", "Replace your working draft with this case's starting "
                       "position? You can undo with Ctrl+Z."):
            return
        probs = self.state.replace_draft(self.case.base(), f"Decision Room: {self.case.title}")
        if probs:
            error(self, "Cannot load", "\n".join(probs))
            return
        self._ran = True
        self.state.navigate.emit("lab", None)

    # ------------------------------------------------------------------ decide
    def _count(self):
        n = len(D._words(self.just.toPlainText()))
        self.count_lbl.setText(f"{n} words")

    def _submit(self):
        c = self.case
        btn = self.opt_group.checkedButton()
        if not c or not btn:
            error(self, "Select an option", "Choose a recommendation first (step 6).")
            return
        if len(D._words(self.just.toPlainText())) < 5:
            error(self, "Justification needed", "Write a short executive justification (step 7).")
            return
        sub = D.Submission(c.id, btn.property("opt"), [cb.text() for cb in self.drv_checks if cb.isChecked()],
                           self.est.value(), self.just.toPlainText(), self._viewed, self._ran)
        g = D.grade(c, sub)
        db = self.state.db
        db.execute("INSERT INTO decisions (ts, case_id, option_id, justification, scores) VALUES (?,?,?,?,?)",
                   (now(), c.id, sub.option_id, sub.justification,
                    json.dumps({"overall": g.overall, "dimensions": g.scores, "estimate": sub.estimate,
                                "truth": g.truth, "drivers": sub.drivers, "realised": g.outcome["realised"]})))
        db.audit("decision", None, c.id, None, sub.option_id, f"Decision Room score {g.overall:.0f}")
        P.record_decision(db, c, g)
        self.state.progress_changed.emit()
        self._show_grade(c, sub, g)
        self._fill_list()
        self.tabs.setCurrentIndex(4)

    def _show_grade(self, c, sub, g):
        st = self.state
        rows = [{"Dimension": D.DIMENSION_LABELS[k], "Weight": f"{D.WEIGHTS[k] * 100:.0f}%",
                 "Score": f"{v * 100:.0f}%", "Feedback": " ".join(g.feedback[k])} for k, v in g.scores.items()]
        self.score_table.set(pd.DataFrame(rows))
        self.score_table.fit_height(6)
        opt = next(o for o in c.options if o.id == sub.option_id)
        oc = g.outcome
        self.out_lbl.setText(f"<h3>Overall {g.overall:.0f} / 100</h3><span style='color:gray'>Rule-based rubric: it "
                             "checks structure, numbers, drivers and risk language. It cannot judge prose like a "
                             "person, and the score is practice feedback, not a qualification.</span>")
        nxt = "".join(f"<li>{x}</li>" for x in oc["investigate_next"])
        self.out_detail.setText(
            f"<h3>What happened</h3><p>You chose <b>{opt.label}</b>. Your analysis implied {D.metric_label(c)} of "
            f"<b>{st.money(oc['expected'])}</b>; the realised result was <b>{st.money(oc['realised'])}</b>.</p>"
            f"<p>{oc['reality_note']}</p><p><b>Why:</b> {opt.outcome_note}</p>"
            f"<h3>What an experienced analyst would investigate next</h3><ul>{nxt}</ul>")

    def _history(self):
        if not self.case:
            return
        rows = []
        for r in self.state.db.query("SELECT * FROM decisions WHERE case_id = ? ORDER BY id DESC",
                                     (self.case.id,)):
            s = json.loads(r["scores"])
            o = next((x.label for x in self.case.options if x.id == r["option_id"]), r["option_id"])
            rows.append({"When": r["ts"].replace("T", " "), "Option": o, "Score": f"{s.get('overall', 0):.0f}"})
        self.hist.set(pd.DataFrame(rows) if rows else pd.DataFrame({"When": [], "Option": [], "Score": []}))

    def refresh(self):
        pass

    def focus_item(self, payload):
        for i, c in enumerate(D.CASES):
            if c.id == payload:
                self.list.setCurrentRow(i)
