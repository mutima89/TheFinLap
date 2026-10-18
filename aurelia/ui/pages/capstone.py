"""Integrated capstone: messy data → KPIs → reconciliation → forecast → analysis → decisions → risk →
dashboard → recommendation → simulated meeting."""
from __future__ import annotations


from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QListWidget, QListWidgetItem, QStackedWidget,
                               QCheckBox, QFormLayout, QLineEdit, QComboBox, QTextEdit, QRadioButton, QButtonGroup,
                               QFileDialog, QTabWidget)

from ...analysis import capstone as K
from ...learning import progress as P
from ...learning.content import parse_answer
from ..widgets import Page, label, button, Table, error


class CapstonePage(Page):
    def __init__(self, state):
        super().__init__("Capstone",
                         "A messy but recoverable dataset for model year 2 (2028), and ten steps that take you from "
                         "data validation to defending a recommendation. Every expected answer comes from the "
                         "simulation engine. Scores are practice feedback, not a qualification.")
        self.state = state
        top = QHBoxLayout()
        top.addWidget(button("Export the dataset (CSV)…", self._export,
                             tip="Writes new files; never overwrites existing ones."))
        self.overall = label("", "H3")
        top.addWidget(self.overall)
        top.addStretch(1)
        self.body.addLayout(top)
        data_tabs = QTabWidget()
        for name, df in (("Rooms by month & segment (RAW)", K.messy_rooms()),
                         ("Hotel control totals", K.hotel_controls()), ("Budget", K.budget_file())):
            t = Table(min_height=220)
            t.set(df.astype(str) if name.startswith("Rooms") else df)
            data_tabs.addTab(t, name.replace("&", "&&"))
        data_tabs.setMaximumHeight(280)
        self.body.addWidget(data_tabs)
        row = QHBoxLayout()
        self.steps = QListWidget()
        self.steps.setMaximumWidth(300)
        self.steps.currentRowChanged.connect(lambda i: self.stack.setCurrentIndex(i))
        row.addWidget(self.steps)
        self.stack = QStackedWidget()
        row.addWidget(self.stack, 1)
        self.body.addLayout(row, 1)
        self.fields: dict[int, dict] = {}
        self.feedback: dict[int, object] = {}
        for i, title in enumerate(K.STEP_TITLES, 1):
            w = QWidget()
            lay = QVBoxLayout(w)
            lay.addWidget(label(title, "H2"))
            getattr(self, f"_build{i}")(lay, i)
            r = QHBoxLayout()
            r.addWidget(button("Submit step", lambda _=False, s=i: self._submit(s), primary=True))
            r.addStretch(1)
            lay.addLayout(r)
            fb = label("", wrap=True)
            lay.addWidget(fb)
            lay.addStretch(1)
            self.feedback[i] = fb
            self.stack.addWidget(w)
        self._refresh_list()
        self.steps.setCurrentRow(0)

    # ------------------------------------------------------------------ helpers
    def _num(self, form, step, key, text, unit="currency"):
        e = QLineEdit()
        e.setMaximumWidth(240)
        e.setProperty("unit", unit)
        form.addRow(text, e)
        self.fields.setdefault(step, {})[key] = e
        return e

    def _choice(self, form, step, key, text, items):
        cb = QComboBox()
        cb.addItem("— choose —", None)
        for it in items:
            cb.addItem(it, it)
        form.addRow(text, cb)
        self.fields.setdefault(step, {})[key] = cb
        return cb

    def _text(self, lay, step, key, prompt, h=130):
        lay.addWidget(label(prompt, wrap=True))
        t = QTextEdit()
        t.setMinimumHeight(h)
        lay.addWidget(t)
        self.fields.setdefault(step, {})[key] = t
        return t

    def _collect(self, step) -> dict:
        out = {}
        for k, w in self.fields.get(step, {}).items():
            if isinstance(w, QLineEdit):
                out[k] = parse_answer(w.text(), w.property("unit") or "number")
            elif isinstance(w, QComboBox):
                out[k] = w.currentData()
            elif isinstance(w, QTextEdit):
                out[k] = w.toPlainText()
            elif isinstance(w, list):
                out[k] = [c.property("key") for c in w if c.isChecked()]
        return out

    # ------------------------------------------------------------------ steps
    def _build1(self, lay, s):
        lay.addWidget(label("Inspect the RAW rooms file above against the hotel control totals. Choose the cleaning "
                            "rules you would apply (Aurelia applies them in a fixed, documented order) and count the "
                            "exact duplicate rows.", wrap=True))
        checks = []
        for k, (txt, _ok) in K.RULES.items():
            c = QCheckBox(txt)
            c.setProperty("key", k)
            lay.addWidget(c)
            checks.append(c)
        self.fields.setdefault(s, {})["rules"] = checks
        f = QFormLayout()
        self._num(f, s, "duplicates", "Number of exact duplicate rows:", "number")
        lay.addLayout(f)

    def _build2(self, lay, s):
        lay.addWidget(label("From the cleaned data (use the control totals for available rooms), calculate the "
                            "full-year 2028 KPIs.", wrap=True))
        f = QFormLayout()
        self._num(f, s, "occupancy", "Occupancy (e.g. 75.0%):", "pct")
        self._num(f, s, "adr", "ADR (SAR):")
        self._num(f, s, "revpar", "RevPAR (SAR):")
        self._num(f, s, "net_adr", "Net ADR after commissions (SAR):")
        lay.addLayout(f)

    def _build3(self, lay, s):
        lay.addWidget(label("Reconcile 2028 room revenue against the budget file (actual − budget) and split it into "
                            "rate (at actual rooms) and volume (at budget ADR).", wrap=True))
        f = QFormLayout()
        self._num(f, s, "rev_var", "Total room revenue variance:")
        self._num(f, s, "rate_var", "Rate variance:")
        self._num(f, s, "vol_var", "Volume variance:")
        self._choice(f, s, "fu", "Overall verdict:", ["F", "U"])
        lay.addLayout(f)

    def _build4(self, lay, s):
        lay.addWidget(label("Forecast room revenue for January–March 2029. Choose a method and enter your number. "
                            "After you submit, you will see what actually happened in the simulation.", wrap=True))
        f = QFormLayout()
        self._choice(f, s, "method", "Method:", ["Seasonal (same quarter last year × growth)",
                                                 "Driver-based (rooms × occupancy × ADR)",
                                                 "Run-rate (last 3 months × 1)", "Annual average ÷ 4"])
        self._num(f, s, "forecast", "Forecast room revenue Q1 2029 (SAR):")
        lay.addLayout(f)

    def _build5(self, lay, s):
        lay.addWidget(label("Load the capstone world into the Scenario Lab, open Statements and answer for 2028 "
                            "(FY2028 column).", wrap=True))
        lay.addWidget(button("Load the capstone world into the Scenario Lab", self._load_world,
                             tip="Replaces your working draft; undo with Ctrl+Z."))
        f = QFormLayout()
        self._num(f, s, "ebitda", "EBITDA 2028:")
        self._num(f, s, "cfo", "Cash flow from operations 2028:")
        self._choice(f, s, "gap_item", "Largest item between EBITDA and CFO:",
                     ["Interest paid", "Tax paid", "Working-capital increase", "Capital expenditure"])
        lay.addLayout(f)

    def _build6(self, lay, s):
        lay.addWidget(label("With the capstone world loaded, use the Investment page to evaluate:<br>A — Room "
                            "refurbishment, phased: capex 18m, 15 rooms out for 6 months, +6% rate, +3% demand, "
                            "10 years, 10%.<br>B — Direct-booking marketing campaign at its default assumptions.",
                            wrap=True))
        f = QFormLayout()
        self._num(f, s, "npv_a", "NPV of A:")
        self._num(f, s, "npv_b", "NPV of B:")
        self._choice(f, s, "choice", "Which would you fund?", ["A", "B"])
        lay.addLayout(f)
        self._text(lay, s, "why", "One or two sentences: why?", 70)

    def _build7(self, lay, s):
        lay.addWidget(label("Sensitivity & Risk page (capstone world, period 2028): what happens to EBITDA if demand "
                            "is 10% lower in every segment (demand multiplier 0.9)?", wrap=True))
        f = QFormLayout()
        self._num(f, s, "down_delta", "Change in 2028 EBITDA (SAR, negative if lower):")
        self._num(f, s, "down_pct", "Change in EBITDA (%):", "pct")
        lay.addLayout(f)
        self._text(lay, s, "insight", "Why does EBITDA fall by much more than 10%?", 70)

    def _build8(self, lay, s):
        lay.addWidget(label("Choose exactly six KPIs for the owner's monthly dashboard.", wrap=True))
        checks = []
        for k in K.DASHBOARD_KPIS:
            c = QCheckBox(k)
            c.setProperty("key", k)
            lay.addWidget(c)
            checks.append(c)
        self.fields.setdefault(s, {})["kpis"] = checks

    def _build9(self, lay, s):
        self._text(lay, s, "text", "Write the executive recommendation for the owner (60–220 words): which project, "
                                   "why, what the 2028 results and cash position mean, the key risk, and the next "
                                   "step with an owner and date.", 170)

    def _build10(self, lay, s):
        self.meet_groups = []
        for i, (who, q, opts, _r) in enumerate(K.MEETING):
            lay.addWidget(label(f"<b>{who}:</b> {q}", wrap=True))
            g = QButtonGroup(self)
            for j, o in enumerate(opts):
                rb = QRadioButton(o)
                g.addButton(rb, j)
                lay.addWidget(rb)
            self.meet_groups.append(g)
        self._text(lay, s, "text", "Owner (follow-up): 'Why should I believe your forecast?' — answer in a few "
                                   "sentences.", 90)

    # ------------------------------------------------------------------ actions
    def _submit(self, step):
        ans = self._collect(step)
        if step == 10:
            ans["answers"] = [g.checkedId() for g in self.meet_groups]
        res = K.grade_step(step, ans)
        K.save_step(self.state.db, step, ans, res)
        comp = {1: "excel", 2: "rm", 3: "fpa", 4: "budget", 5: "statements", 6: "invest", 7: "invest", 8: "comms",
                9: "comms", 10: "judgement"}[step]
        P.record_attempt(self.state.db, "capstone", "capstone", f"step{step}", res.score, comp)
        self.feedback[step].setText(f"<b>Step score {res.score * 100:.0f}%</b><br>" + "<br>".join(res.notes))
        self.state.progress_changed.emit()
        self._refresh_list()

    def _refresh_list(self):
        sc = K.step_scores(self.state.db)
        cur = self.steps.currentRow()
        self.steps.blockSignals(True)
        self.steps.clear()
        for i, t in enumerate(K.STEP_TITLES, 1):
            it = QListWidgetItem((f"✓ {t} — {sc[i] * 100:.0f}%" if i in sc else f"○ {t}"))
            self.steps.addItem(it)
        self.steps.blockSignals(False)
        self.steps.setCurrentRow(max(cur, 0))
        o = K.overall_score(self.state.db)
        self.overall.setText(f"Capstone score: {o:.0f} / 100" if o is not None else
                             f"{len(sc)}/10 steps submitted")

    def _load_world(self):
        from ...analysis.fpa import actual_world_assumptions
        probs = self.state.replace_draft(actual_world_assumptions(), "Capstone world loaded")
        if probs:
            error(self, "Cannot load", "\n".join(probs))
        else:
            self.state.status.emit("Capstone world loaded into the working draft (Ctrl+Z to undo).")

    def _export(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for the capstone dataset")
        if not d:
            return
        paths = K.export_dataset(d)
        self.state.status.emit(f"Wrote {len(paths)} files to {d}")

    def refresh(self):
        self._refresh_list()
