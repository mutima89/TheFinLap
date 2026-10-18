"""UI smoke and interaction tests (offscreen Qt). Dialogs are patched so nothing blocks."""
import json

import pytest
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from aurelia.persistence.db import Database
from aurelia.ui.state import AppState
from aurelia.ui.main_window import MainWindow, PAGES
from aurelia.analysis import capstone as K
from aurelia.analysis import decisions as D
from aurelia.learning import progress as P


@pytest.fixture
def win(tmp_path, qapp, monkeypatch):
    monkeypatch.setenv("AURELIA_DATA_DIR", str(tmp_path / "appdata"))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    db = Database(tmp_path / "ui.db")
    st = AppState(db)
    w = MainWindow(st)
    yield w
    w.close()
    db.close()


def _patch_module_dialogs(monkeypatch, module, confirm_result=True):
    errors = []
    if hasattr(module, "error"):
        monkeypatch.setattr(module, "error", lambda _p, t, m: errors.append((t, m)))
    if hasattr(module, "confirm"):
        monkeypatch.setattr(module, "confirm", lambda *a, **k: confirm_result)
    if hasattr(module, "info_dialog"):
        monkeypatch.setattr(module, "info_dialog", lambda *a, **k: None)
    return errors


def test_every_page_loads_and_refreshes(win):
    for key, *_ in PAGES:
        win.go(key)
        p = win.pages[key]
        assert not getattr(p, "load_error", None), p.load_error
        assert not getattr(p, "refresh_error", None), p.refresh_error
    win.toggle_theme()
    win.toggle_theme()


def test_decision_room_full_cycle(win, monkeypatch):
    from aurelia.ui.pages import decisions as mod
    errors = _patch_module_dialogs(monkeypatch, mod)
    win.go("decisions", "group_displacement")
    pg = win.pages["decisions"]
    assert pg.case.id == "group_displacement"
    pg._run()
    assert pg.cmp_table.model().rowCount() > 0
    best = max(pg.case.options, key=lambda o: o.quality)
    for b in pg.opt_group.buttons():
        if b.property("opt") == best.id:
            b.setChecked(True)
    for cb in pg.drv_checks[:2]:
        cb.setChecked(True)
    pg.est.setValue(D.evaluate_option(pg.case, best).total)
    pg.just.setPlainText("Recommend the counter-offer because displacement of transient demand at higher rates "
                         "costs more than the group adds; risk is the group walking, so we hold a fallback date "
                         "and the revenue manager confirms by 30 June.")
    pg._submit()
    assert not errors, errors
    rows = win.state.db.query("SELECT * FROM decisions")
    assert len(rows) == 1
    s = json.loads(rows[0]["scores"])
    assert 0 <= s["overall"] <= 100 and set(s["dimensions"]) == set(D.WEIGHTS)
    assert P.best_decision_score(win.state.db, "group_displacement") == pytest.approx(s["overall"])


def test_decision_submit_requires_option_and_text(win, monkeypatch):
    from aurelia.ui.pages import decisions as mod
    errors = _patch_module_dialogs(monkeypatch, mod)
    win.go("decisions", "ota_campaign")
    win.pages["decisions"]._submit()
    assert errors and not win.state.db.query("SELECT * FROM decisions")


def test_learning_guided_exercise_marks_step_and_check_flow(win):
    win.go("learn", "s1_pnl")
    pg = win.pages["learn"]
    assert pg.topic.id == "s1_pnl"
    ex = pg.topic.guided
    from aurelia.ui.pages.learning import ExerciseWidget
    w = ExerciseWidget(ex)
    w.finished.connect(lambda sc, h, tag: pg._done("guided", ex, sc, h, tag))
    if ex.unit == "choice":
        w.group.button(ex.answer).setChecked(True)
    else:
        w.inp.setText(str(ex.answer))
    w.check()
    assert P.step_passed(win.state.db, "s1_pnl", "guided")
    assert not P.step_passed(win.state.db, "s1_pnl", "check")


def test_learning_tree_and_locks(win):
    win.go("learn")
    pg = win.pages["learn"]
    assert pg.tree.topLevelItemCount() == 9
    assert P.stage_unlocked(win.state.db, 1, pg_topics()) and not P.stage_unlocked(win.state.db, 2, pg_topics())


def pg_topics():
    from aurelia.learning.content import topics_by_stage
    return topics_by_stage()


def test_capstone_step_submission(win):
    win.go("capstone")
    pg = win.pages["capstone"]
    for c in pg.fields[1]["rules"]:
        c.setChecked(c.property("key") in K.correct_rules())
    pg.fields[1]["duplicates"].setText(str(K.DUPLICATES))
    pg._submit(1)
    assert K.step_scores(win.state.db)[1] == pytest.approx(1.0)
    e = K.expected()
    pg.fields[2]["occupancy"].setText(f"{e['kpis']['occupancy'] * 100:.2f}%")
    for k in ("adr", "revpar", "net_adr"):
        pg.fields[2][k].setText(f"{e['kpis'][k]:.2f}")
    pg._submit(2)
    assert K.step_scores(win.state.db)[2] == pytest.approx(1.0)
    assert K.overall_score(win.state.db) is None


def test_reports_exports(win, monkeypatch, tmp_path):
    from aurelia.ui.pages import reports as mod
    errors = _patch_module_dialogs(monkeypatch, mod)
    win.go("reports")
    pg = win.pages["reports"]
    pg._preview()
    assert "Executive summary" in pg.preview.toHtml()
    out = tmp_path / "out"
    out.mkdir()
    for kind in ("html", "pdf"):
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, k=kind, **kw: (str(out / f"r.{k}"), "")))
        pg._save_report(kind)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "v.xlsx"), "")))
    pg._variance_xlsx()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "s.xlsx"), "")))
    pg._statements("annual")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out / "c.xlsx"), "")))
    pg._comparison()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(out)))
    pg._portfolio()
    assert not errors, errors
    names = {p.name for p in out.iterdir()}
    assert {"r.html", "r.pdf", "v.xlsx", "s.xlsx", "c.xlsx"} <= names
    assert any(n.endswith(".pdf") and n.startswith("Aurelia_portfolio") for n in names)
    assert (out / "r.pdf").read_bytes()[:4] == b"%PDF"


def test_excel_lab_generate_and_grade(win, monkeypatch, tmp_path):
    from aurelia.ui.pages import excel_lab as mod
    errors = _patch_module_dialogs(monkeypatch, mod)
    win.go("excel")
    pg = win.pages["excel"]
    pg.with_ref.setChecked(True)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path)))
    pg._generate()
    ref = next(p for p in tmp_path.iterdir() if "REFERENCE" in p.name and "01_" in p.name)
    before = ref.read_bytes()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(ref), "")))
    pg._grade()
    assert not errors, errors
    assert pg._report.score == pytest.approx(100.0)
    assert ref.read_bytes() == before
    assert P.best_workbook_score(win.state.db, "revenue") == pytest.approx(100.0)


def test_settings_integrity_backup_restore_reset(win, monkeypatch, tmp_path):
    from aurelia.ui.pages import settings as mod
    _patch_module_dialogs(monkeypatch, mod)
    win.go("settings")
    pg = win.pages["settings"]
    pg._integrity()
    m = pg.int_table.model()
    assert all(m.index(r, 1).data() == "PASS" for r in range(m.rowCount()))
    st = win.state
    st.save_as("Mine", "test")
    bk = tmp_path / "b.db"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(bk), "")))
    pg._backup()
    assert bk.exists()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("RESET", True)))
    pg._reset()
    assert "Mine" not in st.store.names()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bk), "")))
    pg._restore()
    assert "Mine" in st.store.names()


def test_reset_needs_typed_confirmation(win, monkeypatch):
    from aurelia.ui.pages import settings as mod
    _patch_module_dialogs(monkeypatch, mod)
    st = win.state
    st.save_as("Keep")
    win.go("settings")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("reset please", True)))
    win.pages["settings"]._reset()
    assert "Keep" in st.store.names()


def test_glossary_search_and_navigate(win):
    win.go("glossary", "RevPAR")
    pg = win.pages["glossary"]
    assert pg._hits and any(h.kind == "Glossary" for h in pg._hits)
    win.go("glossary", "help")
    assert pg.tabs.currentIndex() == 3


def test_dashboard_extras_text(win):
    win.go("dashboard")
    pg = win.pages["dashboard"]
    for fn in pg.extras.values():
        assert isinstance(fn(), str) and fn()
