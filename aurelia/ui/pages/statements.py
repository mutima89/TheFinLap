"""Three-statement model viewer with integrity checks."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QComboBox, QFileDialog

from ...analysis import statements as stm
from ..common import formatters, line_item_html
from ..widgets import Page, label, button, Table, Banner, info_dialog, error


class StatementsPage(Page):
    def __init__(self, state):
        super().__init__("Financial Statements",
                         "Operating statement, income statement, balance sheet and cash flow – linked through "
                         "retained earnings, working capital, depreciation, capex, debt and cash. Double-click a line "
                         "to see its formula and dependencies.")
        self.state = state
        row = QHBoxLayout()
        row.addWidget(label("View:", "Muted"))
        self.freq = QComboBox()
        self.freq.addItem("Annual", "annual")
        self.freq.addItem("Monthly (36 months)", "monthly")
        self.freq.currentIndexChanged.connect(self.refresh)
        row.addWidget(self.freq)
        row.addStretch(1)
        row.addWidget(button("Export statements to Excel…", self._export))
        self.body.addLayout(row)
        self.banner = Banner()
        self.body.addWidget(self.banner)
        self.tabs = QTabWidget()
        self.tables = {}
        for key, title in (("ops", "Operating statement"), ("is", "Income statement"), ("bs", "Balance sheet"),
                           ("cf", "Cash flow"), ("rc", "Revenue, VAT and cash"), ("chk", "Model checks")):
            t = Table(min_height=520)
            t.doubleClicked.connect(lambda idx, k=key: self._inspect(k, idx))
            self.tables[key] = t
            self.tabs.addTab(t, title)
        self.body.addWidget(self.tabs, 1)
        state.results_changed.connect(self.refresh)

    def focus_item(self, key):
        self.tabs.setCurrentIndex(0 if key in ("total_revenue", "gop", "ebitda") else
                                  (2 if key == "closing_cash" else 1))

    def _inspect(self, tab, idx):
        if "key" not in self._frames.get(tab, {}).columns:
            return
        key = self._frames[tab].iloc[idx.row()]["key"]
        from ...model.engine import G
        if key in G.items:
            info_dialog(self, "Line item", line_item_html(key, self.state.result, self.state))

    def refresh(self):
        st = self.state
        res = st.result
        f = self.freq.currentData()
        self._frames = {"ops": stm.operating_statement(res, f), "is": stm.income_statement(res, f),
                        "bs": stm.balance_sheet(res, f), "cf": stm.cash_flow_statement(res, f),
                        "rc": stm.revenue_cash_bridge(res, f)}
        for k, df in self._frames.items():
            cols = [c for c in df.columns if c not in ("Line", "style", "key")]
            bold = [i for i, s in enumerate(df["style"]) if s in ("b", "h")]
            view = df.drop(columns=["style", "key"]).copy()
            view["Line"] = [("    " + l if s == "i" else l) for l, s in zip(df["Line"], df["style"])]
            self.tables[k].set(view, formatters(st, money_cols=cols), bold)
        chk = stm.checks_frame(res)
        self.tables["chk"].set(chk, {"Max abs. difference": lambda v: f"{v:,.6f}"},
                               nature={"Status": lambda r, v: "good" if v == "PASS" else "bad"})
        failed = [c.name for c in res.checks if not c.passed]
        self.banner.set_text((("Integrity checks FAILED: " + ", ".join(failed) + ". ") if failed else "")
                             + " ".join(res.warnings))

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export statements", "Aurelia_statements.xlsx",
                                              "Excel workbook (*.xlsx)")
        if not path:
            return
        try:
            from ...reports.excel_export import export_statements
            export_statements(self.state.result, path, self.state.scenario_name)
            self.state.status.emit(f"Exported statements to {path}")
        except Exception as exc:  # noqa: BLE001
            error(self, "Export failed", str(exc))
