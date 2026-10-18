"""Settings, data storage disclosure, backup/restore, reset and scenario import/export."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QComboBox, QFileDialog, QInputDialog, QFormLayout, QSpinBox, \
    QDoubleSpinBox

from ...model.engine import simulate
from ...persistence.db import app_data_dir, RestoreError
from ..widgets import Page, card, label, button, Table, confirm, error, info_dialog


class SettingsPage(Page):
    def __init__(self, state):
        super().__init__("Settings and Data", "Appearance, currency, analysis settings and your local data.")
        self.state = state
        f, fl = card()
        fl.addWidget(label("Appearance and currency", "H3"))
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light"])
        self.theme.setCurrentText(state.theme)
        self.theme.activated.connect(lambda _i: self._theme())
        form.addRow("Theme", self.theme)
        self.cur = QComboBox()
        self.cur.addItems(["SAR", "USD"])
        self.cur.setCurrentText(state.currency)
        self.cur.activated.connect(lambda _i: state.set_currency(self.cur.currentText()))
        form.addRow("Display currency", self.cur)
        fl.addLayout(form)
        fl.addWidget(label("The model calculates in SAR. USD display converts at the scenario's fixed, fictional "
                           "exchange-rate assumption (Scenario Lab → Meta). Revenue is shown net of VAT (15% "
                           "assumption, configurable).", "Muted", wrap=True))
        self.body.addWidget(f)

        f, fl = card()
        fl.addWidget(label("FP&A analysis settings", "H3"))
        form = QFormLayout()
        self.as_of = QSpinBox()
        self.as_of.setRange(1, 12)
        self.as_of.setValue(int(state.db.get_setting("fpa_as_of", 9)))
        form.addRow("Close month (actuals available to)", self.as_of)
        self.mat_abs = QDoubleSpinBox()
        self.mat_abs.setRange(0, 1e9)
        self.mat_abs.setGroupSeparatorShown(True)
        self.mat_abs.setDecimals(0)
        self.mat_abs.setValue(float(state.db.get_setting("materiality_abs", 250_000.0)))
        form.addRow("Materiality — absolute (SAR)", self.mat_abs)
        self.mat_pct = QDoubleSpinBox()
        self.mat_pct.setRange(0, 100)
        self.mat_pct.setSuffix(" %")
        self.mat_pct.setValue(float(state.db.get_setting("materiality_pct", 0.05)) * 100)
        form.addRow("Materiality — percentage", self.mat_pct)
        fl.addLayout(form)
        fl.addWidget(button("Apply analysis settings", self._apply_fpa))
        self.body.addWidget(f)

        f, fl = card()
        fl.addWidget(label("Your data", "H3"))
        fl.addWidget(label(
            f"All data is stored only on this computer in:<br><b>{app_data_dir()}</b><br>"
            "It contains your scenarios, checkpoints, audit trail, progress, attempts, decisions, workbook grades, "
            "action plans, forecast versions and capstone answers (SQLite database <i>aurelia.db</i>), plus graded "
            "workbook copies and logs. The application sends nothing over the network, collects no analytics, "
            "needs no account and stores no credentials or API keys.", wrap=True))
        r = QHBoxLayout()
        r.addWidget(button("Open data folder", lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(app_data_dir())))))
        r.addWidget(button("Back up…", self._backup, primary=True))
        r.addWidget(button("Restore from backup…", self._restore))
        r.addWidget(button("Export scenarios (JSON)…", self._export))
        r.addWidget(button("Import scenarios (JSON)…", self._import))
        r.addStretch(1)
        fl.addLayout(r)
        r = QHBoxLayout()
        r.addWidget(button("Run integrity check", self._integrity))
        r.addWidget(button("Show welcome tour again", self._tour))
        r.addStretch(1)
        r.addWidget(button("Reset all data…", self._reset, danger=True))
        fl.addLayout(r)
        self.int_table = Table(min_height=120)
        fl.addWidget(self.int_table)
        self.body.addWidget(f)
        self.body.addStretch(1)

    def _theme(self):
        win = self.window()
        if self.theme.currentText() != self.state.theme and hasattr(win, "toggle_theme"):
            win.toggle_theme()
        else:
            self.state.set_theme(self.theme.currentText())

    def _apply_fpa(self):
        db = self.state.db
        db.set_setting("fpa_as_of", self.as_of.value())
        db.set_setting("materiality_abs", self.mat_abs.value())
        db.set_setting("materiality_pct", self.mat_pct.value() / 100)
        self.state.results_changed.emit()
        self.state.status.emit("Analysis settings applied.")

    def _backup(self):
        from datetime import datetime
        path, _ = QFileDialog.getSaveFileName(self, "Back up data", f"aurelia-backup-{datetime.now():%Y%m%d-%H%M}.db",
                                              "Aurelia backup (*.db)")
        if path:
            self.state.db.backup(path)
            self.state.status.emit(f"Backup written to {path}")

    def _restore(self):
        path, _ = QFileDialog.getOpenFileName(self, "Restore from backup", "", "Aurelia backup (*.db)")
        if not path:
            return
        problems = self.state.db.validate_backup(path)
        if problems:
            error(self, "Backup rejected", "\n".join(problems))
            return
        if not confirm(self, "Restore backup", "Replace ALL current data with this backup? A safety copy of the "
                       "current data is made first."):
            return
        try:
            safety = self.state.db.restore(path)
        except RestoreError as exc:
            error(self, "Restore failed", str(exc))
            return
        self.state.reload()
        info_dialog(self, "Restored", f"<p>Backup restored. Your previous data was saved to:</p><p>{safety}</p>")

    def _reset(self):
        if not confirm(self, "Reset all data", "This erases every scenario, progress record, decision, grade and "
                       "setting. A safety backup is written first. Continue?"):
            return
        text, ok = QInputDialog.getText(self, "Confirm reset", "Type RESET to confirm:")
        if not ok or text.strip() != "RESET":
            self.state.status.emit("Reset cancelled.")
            return
        safety = self.state.db.reset_all()
        self.state.reload()
        info_dialog(self, "Reset complete", f"<p>All data was reset. Safety backup:</p><p>{safety}</p>")

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export scenarios", "aurelia-scenarios.json", "JSON (*.json)")
        if path:
            self.state.db.export_scenarios_json(path)
            self.state.status.emit(f"Scenarios exported to {path}")

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import scenarios", "", "JSON (*.json)")
        if not path:
            return
        try:
            created = self.state.store.import_json(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            error(self, "Import failed", str(exc))
            return
        self.state.scenarios_changed.emit()
        self.state.status.emit(f"Imported {len(created)} scenario(s): {', '.join(created)}")

    def _integrity(self):
        rows = [{"Check": "Database", "Result": "PASS" if not (p := self.state.db.integrity_check()) else "FAIL",
                 "Detail": "; ".join(p) or "SQLite integrity, required tables, scenario JSON"}]
        for name in self.state.store.names():
            try:
                res = simulate(self.state.store.get(name).assumptions)
                failed = [c.name for c in res.checks if not c.passed]
                rows.append({"Check": f"Scenario '{name}'", "Result": "PASS" if not failed else "FAIL",
                             "Detail": "All 14 model checks passed" if not failed else ", ".join(failed)})
            except Exception as exc:  # noqa: BLE001
                rows.append({"Check": f"Scenario '{name}'", "Result": "FAIL", "Detail": str(exc)})
        self.int_table.set(pd.DataFrame(rows), nature={"Result": lambda r, v: "good" if v == "PASS" else "bad"})
        self.int_table.fit_height(15)

    def _tour(self):
        from ..onboarding import Onboarding
        Onboarding(self, self.state).exec()
