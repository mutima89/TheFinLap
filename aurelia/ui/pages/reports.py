"""Reports: monthly management report, statement and comparison exports, learning portfolio."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtWidgets import QHBoxLayout, QFileDialog, QTextBrowser, QLineEdit

from ...model.engine import simulate_cached
from ...reports import management_report as MR
from ...reports import portfolio as PF
from ...reports.excel_export import export_statements, export_frames
from ..common import fpa_data
from ..widgets import Page, card, label, button, error


class ReportsPage(Page):
    def __init__(self, state):
        super().__init__("Reports and Exports",
                         "Management-ready outputs from the live engine. Every export records the scenario, settings "
                         "and app version so it can be reproduced. Exports never overwrite existing files without "
                         "your confirmation in the save dialog.")
        self.state = state
        f, fl = card()
        fl.addWidget(label("Monthly management performance report", "H3"))
        fl.addWidget(label("Seven sections: executive summary; actual, budget and forecast; material variances; "
                           "evidence-supported explanations; forward-looking risks; recommended corrective actions; "
                           "action owners and due dates. Uses the FP&A Lab settings (budget scenario, close month, "
                           "materiality) and the action plans you recorded there.", "Muted", wrap=True))
        r = QHBoxLayout()
        r.addWidget(label("Prepared by:"))
        self.prepared = QLineEdit(state.db.get_setting("prepared_by", ""))
        self.prepared.setMaximumWidth(220)
        self.prepared.editingFinished.connect(lambda: state.db.set_setting("prepared_by", self.prepared.text()))
        r.addWidget(self.prepared)
        r.addWidget(button("Preview", self._preview, primary=True))
        r.addWidget(button("Save as HTML…", lambda: self._save_report("html")))
        r.addWidget(button("Save as PDF…", lambda: self._save_report("pdf")))
        r.addWidget(button("Variance tables to Excel…", self._variance_xlsx))
        r.addStretch(1)
        fl.addLayout(r)
        self.preview = QTextBrowser()
        self.preview.setMinimumHeight(420)
        fl.addWidget(self.preview)
        self.body.addWidget(f)

        f, fl = card()
        fl.addWidget(label("Financial statements and scenario comparison", "H3"))
        r = QHBoxLayout()
        r.addWidget(button("Statements (annual) to Excel…", lambda: self._statements("annual")))
        r.addWidget(button("Statements (monthly) to Excel…", lambda: self._statements("monthly")))
        r.addWidget(button("Scenario comparison to Excel…", self._comparison))
        r.addStretch(1)
        fl.addLayout(r)
        self.body.addWidget(f)

        f, fl = card()
        fl.addWidget(label("Learning portfolio", "H3"))
        fl.addWidget(label(PF.DISCLAIMER, "Muted", wrap=True))
        r = QHBoxLayout()
        r.addWidget(label("Name on portfolio (optional):"))
        self.learner = QLineEdit(state.db.get_setting("learner_name", ""))
        self.learner.setMaximumWidth(220)
        self.learner.editingFinished.connect(lambda: state.db.set_setting("learner_name", self.learner.text()))
        r.addWidget(self.learner)
        r.addWidget(button("Export portfolio (HTML, PDF, JSON)…", self._portfolio, primary=True))
        r.addStretch(1)
        fl.addLayout(r)
        self.body.addWidget(f)
        self.body.addStretch(1)

    # ------------------------------------------------------------------ report
    def _html(self) -> str:
        st = self.state
        fpa, budget_name = fpa_data(st)
        return MR.build_report(fpa, MR.actions_from_db(st.db), st.money, budget_name, st.scenario_name,
                               self.prepared.text(), currency=st.currency, fx=st.fx())

    def _preview(self):
        try:
            self.preview.setHtml(self._html())
        except Exception as exc:  # noqa: BLE001
            error(self, "Report failed", str(exc))

    def _save_report(self, kind):
        path, _ = QFileDialog.getSaveFileName(self, "Save management report", f"Aurelia_management_report.{kind}",
                                              "PDF (*.pdf)" if kind == "pdf" else "HTML (*.html)")
        if not path:
            return
        try:
            h = self._html()
            (MR.save_pdf if kind == "pdf" else MR.save_html)(h, path)
            self.state.status.emit(f"Saved {path}")
        except Exception as exc:  # noqa: BLE001
            error(self, "Save failed", str(exc))

    def _variance_xlsx(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save variance tables", "Aurelia_variances.xlsx",
                                              "Excel workbook (*.xlsx)")
        if not path:
            return
        st = self.state
        fpa, _n = fpa_data(st)
        frames = {"YTD vs budget": fpa.variance_table("ytd").drop(columns=["key"]),
                  "Month vs budget": fpa.variance_table("month").drop(columns=["key"]),
                  "FY LE vs budget": fpa.variance_table("fy").drop(columns=["key"]),
                  "Rolling forecast": fpa.rolling_forecast(12)}
        export_frames(frames, path, "Aurelia Grand variance analysis", st.scenario_name, st.currency,
                      pct_cols=("Variance %", "Occupancy"))
        st.status.emit(f"Saved {path}")

    # ------------------------------------------------------------------ statements
    def _statements(self, freq):
        path, _ = QFileDialog.getSaveFileName(self, "Export statements", f"Aurelia_statements_{freq}.xlsx",
                                              "Excel workbook (*.xlsx)")
        if not path:
            return
        st = self.state
        export_statements(st.result, path, st.scenario_name, st.currency, st.fx(), freq)
        st.status.emit(f"Saved {path}")

    def _comparison(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export scenario comparison", "Aurelia_scenarios.xlsx",
                                              "Excel workbook (*.xlsx)")
        if not path:
            return
        st = self.state
        rows = []
        names = st.store.names()
        keys = [("Occupancy", "occupancy", "pct"), ("ADR", "adr", "cur"), ("RevPAR", "revpar", "cur"),
                ("Total revenue", "total_revenue", "cur"), ("GOP", "gop", "cur"), ("GOP margin", "gop_margin", "pct"),
                ("EBITDA", "ebitda", "cur"), ("EBITDA margin", "ebitda_margin", "pct"),
                ("Net income", "net_income", "cur"), ("Closing cash", "closing_cash", "cur")]
        results = {n: simulate_cached(st.store.get(n).assumptions) for n in names}
        results["(working draft)"] = st.result
        for year in (1, 2, 3):
            for lab, k, unit in keys:
                row = {"Year": year, "KPI": lab + (" (%)" if unit == "pct" else f" ({st.currency})")}
                for n, r in results.items():
                    v = r.kpis(r.year_slice(year))[k]
                    row[n] = None if v is None else (round(v * 100, 2) if unit == "pct" else v * st.fx())
                rows.append(row)
        export_frames({"Scenario comparison": pd.DataFrame(rows)}, path, "Scenario comparison", st.scenario_name,
                      st.currency)
        st.status.emit(f"Saved {path}")

    # ------------------------------------------------------------------ portfolio
    def _portfolio(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder for the portfolio")
        if not d:
            return
        try:
            paths = PF.export(self.state.db, d, self.state, self.learner.text())
        except Exception as exc:  # noqa: BLE001
            error(self, "Export failed", str(exc))
            return
        self.state.status.emit("Portfolio saved: " + ", ".join(Path(p).name for p in paths))
