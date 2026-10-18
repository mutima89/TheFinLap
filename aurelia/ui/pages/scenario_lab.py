"""Scenario Lab: change drivers, see interconnected consequences, save and restore scenarios."""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QVBoxLayout, QComboBox, QFormLayout, QWidget, QInputDialog, QLineEdit,
                               QListWidget, QListWidgetItem, QSplitter, QTabWidget)

from ...model.assumptions import DRIVER_SPECS, HEADLINE_DRIVERS, SPEC_BY_PATH, get_path
from ...model.engine import simulate_cached
from ..common import period_combo, period_slice, impact_frame, spin_for, spin_value
from ..widgets import Page, card, label, button, Table, Chart, money_formatter, confirm, error, Banner
from .. import theme


class ScenarioLabPage(Page):
    def __init__(self, state):
        super().__init__("Scenario Lab",
                         "Change commercial and operating drivers. Every dependent figure – revenue, contribution, "
                         "EBITDA, the balance sheet and cash – recalculates through the same engine. Changes are "
                         "auto-saved as a draft; use Save to keep them in a named scenario.")
        self.state = state
        self._editors: dict[str, QWidget] = {}

        # ---- scenario bar --------------------------------------------------------------
        bar, bv = card(QVBoxLayout, 8)
        bl = QHBoxLayout()
        bv.addLayout(bl)
        bl.addWidget(label("Scenario:", "H3"))
        self.scenario_cb = QComboBox()
        self.scenario_cb.setMinimumWidth(220)
        self.scenario_cb.activated.connect(self._load)
        bl.addWidget(self.scenario_cb)
        bl.addWidget(label("Compare with:", "Muted"))
        self.compare_cb = QComboBox()
        self.compare_cb.setMinimumWidth(180)
        self.compare_cb.activated.connect(lambda _i: state.set_compare(self.compare_cb.currentText()))
        bl.addWidget(self.compare_cb)
        bl.addStretch(1)
        bl = QHBoxLayout()  # actions on a second row so the bar fits narrow windows
        bv.addLayout(bl)
        self.btn_save = button("Save", self._save, primary=True, tip="Save changes into this scenario (Ctrl+S)")
        bl.addWidget(self.btn_save)
        bl.addWidget(button("Save as…", self._save_as, tip="Save the working draft as a new scenario"))
        bl.addWidget(button("Clone", self._clone, tip="Clone the saved scenario"))
        bl.addWidget(button("Undo", lambda: state.undo(), tip="Undo the last change (Ctrl+Z)"))
        bl.addWidget(button("Redo", lambda: state.redo(), tip="Redo (Ctrl+Y)"))
        bl.addWidget(button("Revert", self._revert, tip="Discard unsaved changes and restore the saved scenario"))
        bl.addWidget(button("Reset to baseline", self._reset, tip="Replace the draft with the baseline assumptions"))
        bl.addStretch(1)
        self.body.addWidget(bar)
        self.state_lbl = label("", "Muted", wrap=True)
        self.body.addWidget(self.state_lbl)
        self.banner = Banner()
        self.body.addWidget(self.banner)

        split = QSplitter(Qt.Horizontal)
        # ---- left: drivers ---------------------------------------------------------------
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        hc, hl = card()
        hl.addWidget(label("Headline drivers", "H2"))
        hl.addWidget(label("Room rates, demand and operating costs. Press Enter or leave the field to recalculate.",
                           "Muted", wrap=True))
        form = QFormLayout()
        for path in HEADLINE_DRIVERS:
            spec = SPEC_BY_PATH[path]
            w = self._make_editor(spec)
            form.addRow(spec.label, w)
        hl.addLayout(form)
        ll.addWidget(hc)

        ac, al = card()
        al.addWidget(label("All drivers by area", "H2"))
        self.cat_cb = QComboBox()
        cats = []
        for s in DRIVER_SPECS:
            if s.category not in cats:
                cats.append(s.category)
        self.cat_cb.addItems(cats)
        self.cat_cb.currentTextChanged.connect(self._build_category)
        al.addWidget(self.cat_cb)
        self.cat_form_host = QWidget()
        self.cat_form = QFormLayout(self.cat_form_host)
        al.addWidget(self.cat_form_host)
        ll.addWidget(ac)
        ll.addStretch(1)
        split.addWidget(left)

        # ---- right: impact ----------------------------------------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        ic, il = card()
        top = QHBoxLayout()
        top.addWidget(label("Impact vs comparison scenario", "H2"))
        top.addStretch(1)
        self.period = period_combo()
        self.period.currentIndexChanged.connect(self.refresh)
        top.addWidget(self.period)
        il.addLayout(top)
        self.impact = Table(min_height=360)
        il.addWidget(self.impact)
        rl.addWidget(ic)

        bc, bl2 = card()
        bl2.addWidget(label("EBITDA bridge: comparison → working scenario", "H3"))
        self.bridge = Chart(2.8)
        bl2.addWidget(self.bridge)
        rl.addWidget(bc)

        tabs = QTabWidget()
        self.changes = Table(min_height=140)
        tabs.addTab(self.changes, "Unsaved changes")
        cp = QWidget()
        cpl = QVBoxLayout(cp)
        row = QHBoxLayout()
        row.addWidget(button("Create checkpoint", self._checkpoint))
        row.addWidget(button("Restore selected checkpoint", self._restore_checkpoint))
        row.addStretch(1)
        cpl.addLayout(row)
        self.cp_list = QListWidget()
        cpl.addWidget(self.cp_list)
        tabs.addTab(cp, "Checkpoints")
        self.audit = Table(min_height=140)
        tabs.addTab(self.audit, "Audit trail")
        self.compare_all = Table(min_height=160)
        tabs.addTab(self.compare_all, "All scenarios")
        mg = QWidget()
        mgl = QVBoxLayout(mg)
        mrow = QHBoxLayout()
        mrow.addWidget(button("Rename scenario…", self._rename))
        mrow.addWidget(button("Delete scenario", self._delete, danger=True))
        mrow.addStretch(1)
        mgl.addLayout(mrow)
        mgl.addWidget(label("Reference cases (Base, Upside, Downside) are protected: save changes as a new "
                            "scenario instead.", "Muted", wrap=True))
        mgl.addStretch(1)
        tabs.addTab(mg, "Manage")
        rl.addWidget(tabs)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        self.body.addWidget(split, 1)

        self._build_category(self.cat_cb.currentText())
        state.results_changed.connect(self.refresh)
        state.scenarios_changed.connect(self.refresh)
        state.theme_changed.connect(lambda _n: self.refresh())

    # ---- editors ---------------------------------------------------------------------------
    def _make_editor(self, spec):
        val = get_path(self.state.draft, spec.path)
        if val is None:
            val = 0
        w = spin_for(spec, val)
        w.editingFinished.connect(lambda s=spec, ww=w: self._apply(s, ww))
        self._editors.setdefault(spec.path, [])
        self._editors[spec.path].append(w)
        return w

    def _build_category(self, cat: str) -> None:
        while self.cat_form.rowCount():
            self.cat_form.removeRow(0)
        for path in list(self._editors):
            self._editors[path] = [w for w in self._editors[path] if _alive(w)
                                   and w.parent() is not self.cat_form_host]
        for spec in DRIVER_SPECS:
            if spec.category == cat:
                self.cat_form.addRow(spec.label, self._make_editor(spec))

    def _apply(self, spec, w) -> None:
        value = spin_value(spec, w)
        current = get_path(self.state.draft, spec.path)
        if current is not None and abs(float(current) - value) < 1e-12:
            return
        problems = self.state.set_driver(spec.path, value)
        if problems:
            error(self, "Invalid assumption", "\n".join(problems))
            self._sync_editors()

    def _sync_editors(self) -> None:
        for path, ws in self._editors.items():
            spec = SPEC_BY_PATH[path]
            v = get_path(self.state.draft, path)
            for w in ws:
                if not _alive(w):
                    continue
                w.blockSignals(True)
                w.setValue((v or 0) * 100 if spec.unit == "pct" else (v or 0))
                w.blockSignals(False)

    # ---- actions -------------------------------------------------------------------------------
    def _load(self, _i=None) -> None:
        name = self.scenario_cb.currentText()
        if name == self.state.scenario_name:
            return
        if self.state.dirty and not confirm(self, "Unsaved changes",
                                            f"Discard unsaved changes to '{self.state.scenario_name}' and load "
                                            f"'{name}'? (Cancel keeps your draft.)"):
            self.refresh()
            return
        self.state.load(name)

    def _save(self) -> None:
        sc = self.state.store.get(self.state.scenario_name)
        if sc.is_system:
            self._save_as()
            return
        try:
            self.state.save()
            self.state.status.emit(f"Saved '{sc.name}'.")
        except Exception as exc:  # noqa: BLE001
            error(self, "Could not save", str(exc))

    def _save_as(self) -> None:
        name, ok = QInputDialog.getText(self, "Save scenario as", "New scenario name:", QLineEdit.Normal,
                                        f"{self.state.scenario_name} – what-if")
        if not ok or not name.strip():
            return
        try:
            self.state.save_as(name.strip())
            self.state.status.emit(f"Saved as '{name.strip()}'.")
        except Exception as exc:  # noqa: BLE001
            error(self, "Could not save", str(exc))

    def _clone(self) -> None:
        name, ok = QInputDialog.getText(self, "Clone scenario", "Name of the clone:", QLineEdit.Normal,
                                        f"{self.state.scenario_name} (copy)")
        if not ok or not name.strip():
            return
        try:
            self.state.store.clone(self.state.scenario_name, name.strip())
            self.state.scenarios_changed.emit()
        except Exception as exc:  # noqa: BLE001
            error(self, "Could not clone", str(exc))

    def _revert(self) -> None:
        if self.state.dirty and confirm(self, "Revert", "Discard all unsaved what-if changes?"):
            self.state.revert()

    def _reset(self) -> None:
        if confirm(self, "Reset to baseline", "Replace the working draft with the baseline assumptions? "
                                              "You can undo this, and saved scenarios are not affected."):
            self.state.reset_draft_to_baseline()

    def _checkpoint(self) -> None:
        if self.state.dirty:
            error(self, "Save first", "Checkpoints capture the saved scenario. Save your changes first.")
            return
        label_, ok = QInputDialog.getText(self, "Checkpoint", "Checkpoint label:")
        if ok and label_.strip():
            self.state.store.checkpoint(self.state.scenario_name, label_.strip())
            self.refresh()

    def _restore_checkpoint(self) -> None:
        item = self.cp_list.currentItem()
        if item is None:
            error(self, "Select a checkpoint", "Select a checkpoint to restore.")
            return
        sc = self.state.store.get(self.state.scenario_name)
        if sc.is_system:
            error(self, "Protected", "Reference cases cannot be overwritten.")
            return
        if confirm(self, "Restore checkpoint", f"Restore '{item.text()}' into '{sc.name}'? The current version "
                                               "stays in the audit trail."):
            self.state.store.restore_checkpoint(sc.name, item.data(Qt.UserRole))
            self.state.load(sc.name)

    def _rename(self) -> None:
        name, ok = QInputDialog.getText(self, "Rename", "New name:", QLineEdit.Normal, self.state.scenario_name)
        if ok and name.strip():
            try:
                old = self.state.scenario_name
                self.state.store.rename(old, name.strip())
                self.state.scenario_name = name.strip()
                self.state.db.set_setting("current_scenario", name.strip())
                self.state._autosave()
                self.state.scenarios_changed.emit()
            except Exception as exc:  # noqa: BLE001
                error(self, "Could not rename", str(exc))

    def _delete(self) -> None:
        name = self.state.scenario_name
        sc = self.state.store.get(name)
        if sc.is_system:
            error(self, "Protected", "Reference cases cannot be deleted.")
            return
        if confirm(self, "Delete scenario", f"Permanently delete '{name}' and its checkpoints?"):
            self.state.store.delete(name)
            self.state.load("Base case")

    # ---- refresh --------------------------------------------------------------------------------
    def refresh(self) -> None:
        st = self.state
        names = st.store.names()
        for cb, cur in ((self.scenario_cb, st.scenario_name), (self.compare_cb, st.compare_name)):
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(names)
            cb.setCurrentText(cur)
            cb.blockSignals(False)
        sc = st.store.get(st.scenario_name)
        changes = st.pending_changes()
        self.state_lbl.setText(
            f"{'Protected reference case' if sc.is_system else 'User scenario'} · {sc.description} · "
            f"{len(changes)} unsaved change(s) · last saved {sc.updated_at}")
        self.banner.set_text(" ".join(st.result.warnings))
        self._sync_editors()

        res, base = st.result, st.compare_result
        sl = period_slice(res, self.period.currentData())
        df = impact_frame(st, base, res, sl)
        nat = {"Change": lambda r, v, d=df: _verdict(d, r)}
        self.impact.set(df.drop(columns=["_d", "_key"]), nature=nat)
        self.impact.fit_height(15)

        rows = []
        for p, o, n in changes:
            spec = SPEC_BY_PATH.get(p)
            rows.append({"Driver": spec.label if spec else p, "Saved": _fmtv(spec, o), "Draft": _fmtv(spec, n)})
        self.changes.set(pd.DataFrame(rows or [{"Driver": "No unsaved changes", "Saved": "", "Draft": ""}]))

        self.cp_list.clear()
        for cp in st.store.checkpoints(st.scenario_name):
            it = QListWidgetItem(f"{cp['label']}  ·  {cp['created_at']}")
            it.setData(Qt.UserRole, cp["id"])
            self.cp_list.addItem(it)

        aud = st.db.audit_entries(sc.id, 200)
        self.audit.set(pd.DataFrame([{"When": r["ts"], "Action": r["action"],
                                      "Driver": (SPEC_BY_PATH[r["path"]].label if r["path"] in SPEC_BY_PATH else
                                                 (r["path"] or "")),
                                      "Old": r["old_value"] or "", "New": r["new_value"] or "", "Note": r["note"] or ""}
                                     for r in aud] or [{"When": "", "Action": "No entries yet", "Driver": "", "Old": "",
                                                        "New": "", "Note": ""}]))
        allrows = []
        for s in st.store.list():
            r = simulate_cached(s.assumptions)
            k = r.kpis(sl)
            allrows.append({"Scenario": s.name, "Occupancy": st.fmt(k["occupancy"], "pct"),
                            "ADR": st.fmt(k["adr"], "currency", 0), "Revenue": st.money(k["total_revenue"]),
                            "EBITDA": st.money(k["ebitda"]), "Net income": st.money(k["net_income"]),
                            "Closing cash": st.money(k["closing_cash"])})
        self.compare_all.set(pd.DataFrame(allrows))
        self._bridge(base, res, sl)

    def _bridge(self, base, res, sl) -> None:
        p = theme.current()
        fx = self.state.fx()
        t = lambda r, k: r.total(k, sl) * fx  # noqa: E731
        steps = [
            ("Room revenue", t(res, "rooms_revenue") - t(base, "rooms_revenue")),
            ("Other revenue", (t(res, "total_revenue") - t(res, "rooms_revenue"))
             - (t(base, "total_revenue") - t(base, "rooms_revenue"))),
            ("Dept. expenses", -(t(res, "total_dept_expenses") - t(base, "total_dept_expenses"))),
            ("Undistributed", -(t(res, "total_undistributed") - t(base, "total_undistributed"))),
            ("Fees & fixed", -((t(res, "mgmt_fees") + t(res, "fixed_charges"))
                               - (t(base, "mgmt_fees") + t(base, "fixed_charges")))),
        ]
        ax = self.bridge.new_axes()
        start = t(base, "ebitda")
        labels = [f"{self.state.compare_name}\nEBITDA"] + [s[0] for s in steps] + ["Working\nEBITDA"]
        ax.bar(0, start, color=p.muted)
        cum = start
        for i, (_n, d) in enumerate(steps, start=1):
            ax.bar(i, d, bottom=cum if d >= 0 else cum + d, color=p.good if d >= 0 else p.bad)
            ax.text(i, max(cum, cum + d), _short(d), ha="center", va="bottom", fontsize=7, color=p.text2)
            cum += d
        ax.bar(len(steps) + 1, cum, color=p.teal)
        ax.set_xticks(range(len(labels)), labels, fontsize=7)
        ax.yaxis.set_major_formatter(money_formatter())
        lo = min(start, cum) * 0.9 if min(start, cum) > 0 else min(start, cum) * 1.1
        ax.set_ylim(bottom=min(lo, 0) if lo < 0 else lo)
        self.bridge.draw()


def _alive(w) -> bool:
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def _short(v: float) -> str:
    return f"{v / 1e6:+.2f}m" if abs(v) >= 1e5 else f"{v / 1e3:+.0f}k"


def _fmtv(spec, v) -> str:
    if spec is None or v is None or not isinstance(v, (int, float)):
        return str(v)
    if spec.unit == "pct":
        return f"{v * 100:.2f}%"
    return f"{v:,.2f}"


_HIGHER_BAD = {"_none"}


def _verdict(df: pd.DataFrame, row: int):
    d = df.iloc[row]["_d"]
    key = df.iloc[row]["_key"]
    if abs(d) < 1e-9 or key in ("occupancy", "adr"):
        return None
    return "good" if d > 0 else "bad"
