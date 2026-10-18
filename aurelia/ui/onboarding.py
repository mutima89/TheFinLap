"""First-run setup and guided onboarding."""
from __future__ import annotations

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QStackedWidget, QWidget, QComboBox, QFormLayout,
                               QPushButton, QApplication)

from ..persistence.db import app_data_dir
from .widgets import label

STEPS = [
    ("Welcome to Aurelia Finance Lab",
     "<p>You are joining the finance team of <b>The Aurelia Grand</b>, a 150-room luxury hotel owned by the "
     "fictional <b>Aurelia Hospitality Group</b>.</p>"
     "<p>This is not a course with a dashboard attached. It is a working business: you will change prices, "
     "staffing and plans, and every decision flows through a single, tested financial engine into the P&amp;L, "
     "balance sheet and cash flow.</p>"),
    ("What is real and what is not",
     "<p>All company names, figures, tax settings and benchmarks are <b>fictional training assumptions</b>. "
     "They are internally consistent but are not real industry data and must not be quoted as such.</p>"
     "<p>Defaults use <b>SAR</b> and a 15% VAT assumption. Every rate, fee and business rule is editable.</p>"
     "<p>Scores in this app show practice performance only; they are not an accredited qualification.</p>"),
    ("Your data stays on this computer",
     "<p>Progress, scenarios and model versions are stored locally in:</p><p><code>{data}</code></p>"
     "<p>Nothing is transmitted, there are no accounts and no analytics. Use <i>Settings and Data</i> to back up, "
     "restore or reset.</p>"),
    ("Set up your workspace", ""),
    ("Where to start",
     "<ol><li><b>Dashboard</b> – read the current business position.</li>"
     "<li><b>Scenario Lab</b> – change a room rate, a demand assumption and a cost, and watch EBITDA and cash "
     "move.</li><li><b>Learning Path</b> – Stage 1 explains the drivers you just changed and checks your "
     "understanding with live numbers.</li></ol>"
     "<p>Shortcuts: <b>Ctrl+K</b> search · <b>Ctrl+S</b> save scenario · <b>Ctrl+Z / Ctrl+Y</b> undo/redo · "
     "<b>Ctrl+T</b> theme · <b>Ctrl+1…9</b> pages · <b>F1</b> help.</p>"),
]


class Onboarding(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Getting started")
        self.resize(620, 420)
        lay = QVBoxLayout(self)
        self.stack = QStackedWidget()
        for i, (title, html) in enumerate(STEPS):
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.addWidget(label(title, "H1"))
            if i == 3:
                form = QFormLayout()
                self.theme_cb = QComboBox()
                self.theme_cb.addItems(["dark", "light"])
                self.theme_cb.setCurrentText(state.theme)
                self.cur_cb = QComboBox()
                self.cur_cb.addItems(["SAR", "USD"])
                self.cur_cb.setCurrentText(state.currency)
                form.addRow("Theme", self.theme_cb)
                form.addRow("Display currency", self.cur_cb)
                wl.addLayout(form)
                wl.addWidget(label("You can change these at any time in Settings.", "Muted"))
            else:
                lab = label(html.replace("{data}", str(app_data_dir())), wrap=True)
                lab.setTextFormat(lab.textFormat())
                wl.addWidget(lab)
            wl.addStretch(1)
            self.stack.addWidget(w)
        lay.addWidget(self.stack, 1)
        row = QHBoxLayout()
        self.step_lbl = label("", "Muted")
        row.addWidget(self.step_lbl)
        row.addStretch(1)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self._go(-1))
        self.next = QPushButton("Next")
        self.next.setObjectName("Primary")
        self.next.clicked.connect(lambda: self._go(1))
        skip = QPushButton("Skip")
        skip.clicked.connect(self._finish)
        row.addWidget(skip)
        row.addWidget(self.back)
        row.addWidget(self.next)
        lay.addLayout(row)
        self._go(0)

    def _go(self, d: int) -> None:
        i = self.stack.currentIndex() + d
        if i >= self.stack.count():
            self._finish()
            return
        self.stack.setCurrentIndex(max(0, i))
        self.back.setEnabled(i > 0)
        self.next.setText("Finish" if i == self.stack.count() - 1 else "Next")
        self.step_lbl.setText(f"Step {i + 1} of {self.stack.count()}")

    def _finish(self) -> None:
        from .main_window import apply_theme
        if self.theme_cb.currentText() != self.state.theme:
            apply_theme(QApplication.instance(), self.theme_cb.currentText())
            self.state.set_theme(self.theme_cb.currentText())
        self.state.set_currency(self.cur_cb.currentText())
        self.state.db.set_setting("onboarded", True)
        self.accept()


def show_onboarding(parent, state) -> None:
    Onboarding(parent, state).exec()
    if hasattr(parent, "theme_btn"):
        parent.theme_btn.setText("Light theme" if state.theme == "dark" else "Dark theme")
