"""Structured learning path with competency-based unlocking and the offline coach."""
from __future__ import annotations

import json

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QWidget, QTreeWidget, QTreeWidgetItem, QTabWidget,
                               QLineEdit, QRadioButton, QButtonGroup, QTextEdit, QTextBrowser, QComboBox, QFrame)

from ...learning import content as C
from ...learning import coach
from ...learning import progress as P
from ..widgets import Page, card, label, button, Table


class ExerciseWidget(QFrame):
    """One exercise with progressive hints, diagnosis and optional interpretation question."""
    finished = Signal(float, int, str)   # score, hints used, mistake tag
    wrong = Signal(str, int)             # diagnosed mistake tag, hints used

    def __init__(self, ex: C.Exercise, allow_hints: bool = True):
        super().__init__()
        self.ex = ex
        self.hints = 0
        self.revealed = False
        self.done = False
        self.tag = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 8)
        lay.addWidget(label(ex.prompt, wrap=True))
        self.group = None
        if ex.unit == "choice":
            self.group = QButtonGroup(self)
            for i, ch in enumerate(ex.choices or []):
                rb = QRadioButton(ch)
                self.group.addButton(rb, i)
                lay.addWidget(rb)
        else:
            row = QHBoxLayout()
            self.inp = QLineEdit()
            self.inp.setPlaceholderText({"pct": "e.g. 24.9%", "currency": "e.g. 1,234,567"}.get(ex.unit, "number"))
            self.inp.setMaximumWidth(260)
            self.inp.returnPressed.connect(self.check)
            row.addWidget(self.inp)
            row.addStretch(1)
            lay.addLayout(row)
        row = QHBoxLayout()
        self.check_btn = button("Check", self.check, primary=True)
        row.addWidget(self.check_btn)
        if allow_hints:
            row.addWidget(button("Hint", self.hint, tip="Progressive hints. Each hint lowers the score a little."))
            row.addWidget(button("Show solution", self.reveal, tip="Shows the worked solution; the step will need "
                                                                   "another attempt later to count as passed."))
        row.addStretch(1)
        lay.addLayout(row)
        self.fb = label("", wrap=True)
        lay.addWidget(self.fb)
        self.interp_box = QWidget()
        il = QVBoxLayout(self.interp_box)
        il.setContentsMargins(0, 0, 0, 0)
        if ex.interpretation_q:
            il.addWidget(label("<b>Interpret:</b> " + ex.interpretation_q, wrap=True))
            self.interp = QTextEdit()
            self.interp.setMaximumHeight(80)
            il.addWidget(self.interp)
            il.addWidget(button("Get coach feedback", self._interp))
            self.interp_fb = label("", wrap=True)
            il.addWidget(self.interp_fb)
        self.interp_box.setVisible(False)
        lay.addWidget(self.interp_box)

    def _given(self):
        if self.ex.unit == "choice":
            b = self.group.checkedButton()
            return b.text() if b else None
        return self.inp.text()

    def check(self):
        given = self._given()
        if given in (None, ""):
            self.fb.setText("Enter an answer first.")
            return
        d = coach.diagnose(self.ex, given)
        if d.correct:
            score = 0.3 if self.revealed else max(0.5, 1.0 - 0.15 * self.hints)
            self.fb.setText("<span style='color:#2BB673'><b>Correct.</b></span> "
                            + ("" if self.hints == 0 else f"({self.hints} hint(s) used) ")
                            + coach.solution(self.ex))
            self.interp_box.setVisible(bool(self.ex.interpretation_q))
            if not self.done:
                self.done = True
                self.finished.emit(score, self.hints + (3 if self.revealed else 0), self.tag or "")
        else:
            self.fb.setText(f"<span style='color:#F0616D'><b>Not yet.</b></span> {d.message}")
            if d.tag not in ("unknown", "unparseable"):
                self.tag = d.tag
            if d.tag != "unparseable" and not self.done:
                self.wrong.emit(d.tag if d.tag != "unknown" else "", self.hints)

    def hint(self):
        self.hints += 1
        self.fb.setText(f"<b>Hint {self.hints}:</b> {coach.hint(self.ex, self.hints)}")

    def reveal(self):
        self.revealed = True
        self.fb.setText(coach.solution(self.ex))

    def _interp(self):
        sc, notes = coach.assess_interpretation(self.ex, self.interp.toPlainText())
        self.interp_fb.setText("<br>".join(notes) + f"<br><i>Coverage {sc * 100:.0f}%. There is no single right "
                                                    "wording; compare with the business interpretation on the Learn "
                                                    "tab.</i>")


class LearningPage(Page):
    def __init__(self, state):
        super().__init__("Learning Path",
                         "Nine stages from financial literacy to an integrated capstone. Every topic has an "
                         "explanation, worked example, guided and independent exercises, an applied task in the "
                         "simulator and a competency check. Stages unlock on demonstrated competency, not on "
                         "reading a lesson. " + P.DISCLAIMER)
        self.state = state
        self.topic: C.Topic | None = None
        row = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(330)
        self.tree.setMaximumWidth(360)
        self.tree.currentItemChanged.connect(self._pick)
        row.addWidget(self.tree)
        right = QVBoxLayout()
        self.t_title = label("", "H2")
        self.t_meta = label("", "Muted", wrap=True)
        right.addWidget(self.t_title)
        right.addWidget(self.t_meta)
        self.tabs = QTabWidget()
        right.addWidget(self.tabs, 1)
        row.addLayout(right, 1)
        self.body.addLayout(row, 1)
        self.learn = QTextBrowser()
        self.learn.setOpenExternalLinks(False)
        self.tabs.addTab(self.learn, "Learn")
        self.tab_widgets = {}
        for step, name in (("guided", "Guided exercise"), ("independent", "Independent exercise"),
                           ("applied", "Applied task"), ("check", "Competency check")):
            w = QWidget()
            lay = QVBoxLayout(w)
            self.tab_widgets[step] = lay
            self.tabs.addTab(w, name)
        self._coach_tab()
        self._build_tree()

    # ------------------------------------------------------------------ tree
    def _build_tree(self):
        db = self.state.db
        cur = self.topic.id if self.topic else None
        self.tree.blockSignals(True)
        self.tree.clear()
        tbs = C.topics_by_stage()
        first_open = None
        select = None
        for stage, title in C.STAGES.items():
            unlocked = P.stage_unlocked(db, stage, tbs)
            st = QTreeWidgetItem([f"{'' if unlocked else '🔒 '}Stage {stage} — {title}"])
            st.setFlags(st.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(st)
            for tid in tbs.get(stage, []):
                t = C.topic(tid)
                done = P.topic_complete(db, tid)
                n = sum(P.step_passed(db, tid, s) for s in P.STEPS)
                mark = "✓" if done else (f"{n}/4" if n else "○")
                it = QTreeWidgetItem([f"{mark}  {t.title}"])
                it.setData(0, Qt.UserRole, tid)
                st.addChild(it)
                if unlocked and not done and first_open is None:
                    first_open = it
                if tid == cur:
                    select = it
            st.setExpanded(unlocked)
        self.tree.blockSignals(False)
        self.tree.setCurrentItem(select or first_open or self.tree.topLevelItem(0).child(0))

    def _pick(self, item, _prev=None):
        if not item or not item.data(0, Qt.UserRole):
            return
        self.topic = C.topic(item.data(0, Qt.UserRole))
        self._show()

    # ------------------------------------------------------------------ topic
    def _show(self):
        t = self.topic
        db = self.state.db
        unlocked = P.stage_unlocked(db, t.stage, C.topics_by_stage())
        self.t_title.setText(t.title)
        comp = P.COMPETENCIES.get(t.competency, t.competency)
        status = " · ".join(f"{s}: {'passed' if P.step_passed(db, t.id, s) else '—'}" for s in P.STEPS)
        self.t_meta.setText(f"Stage {t.stage} — {C.STAGES[t.stage]} · competency: {comp} · {status}")
        self.learn.setHtml(
            f"<h3>Concept</h3>{t.explanation}<h3>Business context</h3><p>{t.context}</p>"
            f"<h3>Worked example (live from the engine, fictional data)</h3>{t.worked()}"
            f"<h3>Common mistake</h3>{t.mistake}<h3>Business interpretation</h3>{t.interpretation}" +
            (f"<h3>Alternative approaches</h3>{t.alternatives}" if t.alternatives else "") +
            (f"<p><i>Related page: open it from the sidebar ({t.page}).</i></p>" if t.page else ""))
        for step, lay in self.tab_widgets.items():
            self._clear(lay)
            idx = 1 + list(self.tab_widgets).index(step)
            if not unlocked:
                lay.addWidget(label("🔒 This stage unlocks when every topic of the previous stage has a passed "
                                    "applied task and competency check.", wrap=True))
                lay.addStretch(1)
                continue
            if not P.step_unlocked(db, t.id, step):
                prev = P.STEPS[P.STEPS.index(step) - 1]
                lay.addWidget(label(f"🔒 Pass the {prev} step first (score ≥ {P.PASS * 100:.0f}%).", wrap=True))
                lay.addStretch(1)
                continue
            if P.step_passed(db, t.id, step):
                lay.addWidget(label(f"✓ Passed (best {P.topic_data(db, t.id).get(step + '_best', 0) * 100:.0f}%). "
                                    "You can practise again; your best score is kept.", "Good", wrap=True))
            getattr(self, f"_step_{step}")(lay)
            lay.addStretch(1)
            self.tabs.setTabText(idx, self.tabs.tabText(idx).lstrip("✓ "))
            if P.step_passed(db, t.id, step):
                self.tabs.setTabText(idx, "✓ " + self.tabs.tabText(idx))

    @staticmethod
    def _clear(lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                LearningPage._clear(it.layout())

    def _exercise(self, lay, ex: C.Exercise, step: str, allow_hints: bool = True):
        w = ExerciseWidget(ex, allow_hints)
        w.finished.connect(lambda sc, h, tag, s=step, e=ex: self._done(s, e, sc, h, tag))
        w.wrong.connect(lambda tag, h, s=step, e=ex, ww=w: P.record_attempt(
            self.state.db, s, self.topic.id, e.id, 0.0, self.topic.competency, ww._given(), tag or None, h))
        lay.addWidget(w)
        return w

    def _done(self, step, ex, score, hints, tag):
        db = self.state.db
        P.record_attempt(db, step, self.topic.id, ex.id, score, self.topic.competency, None, tag or None, hints)
        P.mark_step(db, self.topic.id, step, score, hints)
        self.state.progress_changed.emit()
        self._refresh_meta()

    def _refresh_meta(self):
        t = self.topic
        db = self.state.db
        status = " · ".join(f"{s}: {'passed' if P.step_passed(db, t.id, s) else '—'}" for s in P.STEPS)
        self.t_meta.setText(f"Stage {t.stage} — {C.STAGES[t.stage]} · competency: "
                            f"{P.COMPETENCIES.get(t.competency)} · {status} — reopen the topic to see unlocked "
                            "steps.")

    def _step_guided(self, lay):
        lay.addWidget(label("Follow the method from the worked example. Hints are available.", "Muted", wrap=True))
        self._exercise(lay, self.topic.guided, "guided")

    def _step_independent(self, lay):
        lay.addWidget(label("Work this one on your own. Hints exist but lower the score; competency needs at least "
                            "one hint-free pass.", "Muted", wrap=True))
        self._exercise(lay, self.topic.independent, "independent")

    def _step_applied(self, lay):
        a = self.topic.applied
        lay.addWidget(label("<b>Applied task:</b> " + a.prompt, wrap=True))
        if a.kind == "exercise" and a.exercise:
            self._exercise(lay, a.exercise, "applied")
            return
        self.app_fb = label("", wrap=True)
        row = QHBoxLayout()
        row.addWidget(button("Check my work", self._check_applied, primary=True))
        target_page = {"workbook": "excel", "decision": "decisions", "capstone": "capstone",
                       "scenario": self.topic.page or "lab"}[a.kind]
        row.addWidget(button("Go to the page", lambda: self.state.navigate.emit(target_page, None)))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.app_fb)

    def _check_applied(self):
        a = self.topic.applied
        db = self.state.db
        ok, msg, score = False, "", 0.0
        if a.kind == "scenario":
            ok, msg = a.check(self.state)
            score = 1.0 if ok else 0.0
        elif a.kind == "workbook":
            best = P.best_workbook_score(db, a.target)
            score = (best or 0) / 100
            ok = best is not None and best >= a.threshold
            msg = ("No graded attempt yet." if best is None else f"Best grade {best:.0f}%.") + \
                  (" Passed." if ok else f" Need {a.threshold:.0f}%.")
        elif a.kind == "decision":
            if a.target == "*comms":
                best = 0.0
                for r in db.query("SELECT scores FROM decisions"):
                    best = max(best, json.loads(r["scores"]).get("dimensions", {}).get("communication", 0) * 100)
                ok = best >= a.threshold
                score = best / 100
                msg = f"Best communication score {best:.0f}%." + (" Passed." if ok else "")
            else:
                best = P.best_decision_score(db, a.target)
                score = (best or 0) / 100
                ok = best is not None and best >= a.threshold
                msg = ("Not attempted yet." if best is None else f"Best score {best:.0f}.") + \
                      (" Passed." if ok else f" Need {a.threshold:.0f}.")
        elif a.kind == "capstone":
            from ...analysis.capstone import overall_score
            best = overall_score(db)
            score = (best or 0) / 100
            ok = best is not None and best >= a.threshold
            msg = ("Capstone not completed yet." if best is None else f"Capstone score {best:.0f}.") + \
                  (" Passed." if ok else "")
        self.app_fb.setText(("✓ " if ok else "○ ") + msg)
        if ok:
            P.record_attempt(db, "applied", self.topic.id, a.kind, max(score, P.PASS), self.topic.competency)
            P.mark_step(db, self.topic.id, "applied", max(score, P.PASS), 0)
            self.state.progress_changed.emit()
            self._refresh_meta()

    def _step_check(self, lay):
        lay.addWidget(label("Competency check: no hints. Answer every question, then submit. Pass mark 70%.",
                            "Muted", wrap=True))
        self.check_ws = []
        for ex in self.topic.check:
            w = ExerciseWidget(ex, allow_hints=False)
            w.check_btn.setVisible(False)
            if ex.unit != "choice":
                w.inp.returnPressed.disconnect()
            lay.addWidget(w)
            self.check_ws.append(w)
        lay.addWidget(button("Submit competency check", self._submit_check, primary=True))
        self.check_fb = label("", wrap=True)
        lay.addWidget(self.check_fb)

    def _submit_check(self):
        db = self.state.db
        right, notes = 0, []
        for w in self.check_ws:
            d = coach.diagnose(w.ex, w._given() or "")
            right += d.correct
            if not d.correct:
                notes.append(f"• {w.ex.prompt[:70]}… — {d.message}")
                P.record_attempt(db, "check", self.topic.id, w.ex.id, 0.0, self.topic.competency, w._given(),
                                 d.tag if d.tag not in ("unknown", "unparseable") else None)
        score = right / max(1, len(self.check_ws))
        P.record_attempt(db, "check", self.topic.id, "total", score, self.topic.competency)
        P.mark_step(db, self.topic.id, "check", score, 0)
        self.check_fb.setText(f"<b>{right}/{len(self.check_ws)} correct ({score * 100:.0f}%).</b> " +
                              ("Passed." if score >= P.PASS else "Review the topic and try again.") + "<br>" +
                              "<br>".join(notes))
        self.state.progress_changed.emit()
        self._build_tree()

    # ------------------------------------------------------------------ coach
    def _coach_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(label("Offline coach — deterministic and rule-based. It explains your own numbers and your "
                            "mistakes; every figure comes from the calculation engine.", "Muted", wrap=True))
        f, fl = card()
        fl.addWidget(label("Your recurring mistakes", "H3"))
        self.gap_lbl = label("", wrap=True)
        fl.addWidget(self.gap_lbl)
        lay.addWidget(f)
        f, fl = card()
        fl.addWidget(label("Explain a KPI from my current scenario (year 1)", "H3"))
        row = QHBoxLayout()
        self.kpi_cb = QComboBox()
        for k, n in (("occupancy", "Occupancy"), ("adr", "ADR"), ("revpar", "RevPAR"), ("net_adr", "Net ADR"),
                     ("gop_margin", "GOP margin"), ("ebitda", "EBITDA"), ("cash_conversion", "Cash conversion")):
            self.kpi_cb.addItem(n, k)
        row.addWidget(self.kpi_cb)
        row.addWidget(button("Explain step by step", self._explain))
        row.addStretch(1)
        fl.addLayout(row)
        self.kpi_out = label("", wrap=True)
        fl.addWidget(self.kpi_out)
        lay.addWidget(f)
        f, fl = card()
        fl.addWidget(label("Competency profile", "H3"))
        self.comp_table = Table(min_height=240)
        fl.addWidget(self.comp_table)
        fl.addWidget(label(P.DISCLAIMER, "Muted", wrap=True))
        lay.addWidget(f)
        lay.addStretch(1)
        self.tabs.addTab(w, "Coach && progress")
        self.tabs.currentChanged.connect(lambda i: self._coach_refresh() if i == self.tabs.count() - 1 else None)

    def _coach_refresh(self):
        g = coach.gaps(self.state.db)
        self.gap_lbl.setText("<br>".join(f"• {d['advice']}" for d in g[:5]) if g else
                             "No recurring mistakes recorded yet.")
        rows = [{"Competency": c.label, "Level": c.level, "Weighted score": f"{c.score * 100:.0f}%",
                 "Practical passes": c.practical_passes, "Hint-free pass": "yes" if c.independent else "no",
                 "Attempts": c.attempts,
                 "Trend": "n/a" if c.trend is None else f"{c.trend * 100:+.0f} pts",
                 "Recurring mistakes": ", ".join(f"{m} ×{n}" for m, n in c.recurring_mistakes) or "—"}
                for c in P.competency_profile(self.state.db)]
        self.comp_table.set(pd.DataFrame(rows))

    def _explain(self):
        r = self.state.result
        self.kpi_out.setText(coach.explain_kpi(r, self.kpi_cb.currentData(), r.year_slice(1), self.state.money))

    def refresh(self):
        self._build_tree()

    def focus_item(self, payload):
        it = self.tree.findItems("", Qt.MatchContains | Qt.MatchRecursive)
        for i in it:
            if i.data(0, Qt.UserRole) == payload:
                self.tree.setCurrentItem(i)
                return
