# Architecture

## Principles

1. **One calculation layer.** Every number on every page, in every export, case, exercise and grade comes from
   the same engine (`aurelia/model/engine.py`). Pages and analyses never re-implement formulas; they change
   assumptions and re-run the engine, or read its results.
2. **Assumptions are data.** A scenario is a complete JSON assumption tree (with a schema version and random seed),
   validated against driver specifications before every run.
3. **Explainability.** Each engine output carries a plain-language formula and the assumption paths it reads; the
   formula inspector, dependency viewer and generated documentation read that metadata.
4. **Offline and private.** No network code, no accounts, no telemetry. Data lives in a per-user folder.
5. **Testable without a screen.** Business logic has no Qt dependency; the UI is a thin layer over it and is
   tested off-screen.

## Layers

```
            ┌──────────────────────────────────────────────────────────────┐
  UI        │ ui/main_window.py  ui/pages/*  ui/widgets.py  ui/theme.py    │  PySide6, Matplotlib
            │ ui/visuals.py  ui/icons.py  ui/chrome.py (painted, QtSvg)    │
            │ ui/state.py (AppState: working draft, undo/redo, signals)    │
            └───────────────▲──────────────────────────────▲───────────────┘
                            │ reads results                │ change driver / save
            ┌───────────────┴───────────┐   ┌──────────────┴───────────────┐
  Domain    │ analysis/  statements, rm,│   │ learning/ content, progress, │
            │ fpa, sensitivity,         │   │ coach, glossary              │
            │ investment, decisions,    │   │ excel/ formula, workbooks,   │
            │ capstone                  │   │ grader                       │
            │ game/ season, events      │   │                              │
            │ reports/ management_report│   │                              │
            │ excel_export, portfolio   │   │                              │
            └───────────────▲───────────┘   └──────────────▲───────────────┘
                            │ simulate(assumptions)        │
            ┌───────────────┴──────────────────────────────┴───────────────┐
  Engine    │ model/assumptions.py (baseline, DRIVER_SPECS, validate, diff) │
            │ model/graph.py (CalcGraph)  model/engine.py (13 nodes, checks)│
            │ core/finance.py  core/kpis.py  core/expr.py                   │  NumPy, pandas
            └───────────────▲──────────────────────────────────────────────┘
                            │
            ┌───────────────┴──────────────────────────────────────────────┐
  Storage   │ persistence/db.py (SQLite, backup/restore/reset, audit log)   │
            │ model/scenarios.py (ScenarioStore, checkpoints)               │
            └──────────────────────────────────────────────────────────────┘
```

## Engine

* `CalcGraph` holds nodes registered with `@G.node(name, deps, outputs)`. `G.order()` sorts them topologically;
  `G.evaluate` runs them once. There are 13 nodes: rooms, payroll, fnb, spa, events, other_ops, rooms_dept,
  dept_profit, undistributed, gop_ebitda, capex, working_capital, financials.
* `simulate(a)` validates the assumptions, builds the time context (36 months, 1,096 days), evaluates the graph
  and returns a `SimulationResult` with monthly series (`s(key)`), totals, KPIs, the daily rooms frame, segment
  detail, warnings and the 14 integrity checks. `simulate_cached` memoises on the canonical JSON of the
  assumptions.
* Financing and tax run in a single forward loop using opening balances, so there are no circular references.

## Season mode

`aurelia/game/season.py` turns the engine into a twelve-turn game. Each month's assumption tree is the Base case
plus the player's levers, the effects of that month's briefing cards (`game/events.py`), effects carried from
earlier months and any deferred risk that has materialised. The full engine runs on that tree and only month *m* of
model year 1 is read, so every figure in the game passes the same integrity checks as the rest of the app. The
budget is the Base case with standard levers and no noise; the projection uses expected demand; the actual adds the
engine's seeded demand noise. The bridge from budget to actual is built so its steps sum exactly to the variance.
Season state is stored as JSON in the settings table under `season_v1`.

## Design system

`ui/theme.py` defines the dark and light palettes, registers the bundled fonts (Manrope for the interface, Fraunces
for display headings, both SIL OFL) with Qt and Matplotlib, and generates the application style sheet. `ui/icons.py`
renders a stroke SVG icon set with QtSvg; `ui/visuals.py` holds painted widgets (sparkline, ring, progress line,
month track, season bars, EBITDA bridge, range bar, hero panel, avatar) so key visuals do not depend on Matplotlib.

## Application state

`AppState` (ui/state.py) owns the working draft, the current and comparison scenarios, currency and theme, the
undo/redo stack and Qt signals (`results_changed`, `scenarios_changed`, `progress_changed`, `navigate`, `status`).
Every driver change is validated, applied, re-simulated, written to the audit log and auto-saved as the draft.
Pages are created lazily on first visit (`MainWindow.page`), and a page that fails to load is replaced by an error
page rather than crashing the app.

## Storage

SQLite database `aurelia.db` in `app_data_dir()`:

| Table | Holds |
|---|---|
| meta, settings | schema version, preferences, the auto-saved draft |
| scenarios, checkpoints | assumption trees (system scenarios are protected), named snapshots |
| audit_log | every driver change, save, decision and restore |
| progress, attempts | learning progress per topic and every attempt with score, hints, mistake tag and competency |
| decisions | Decision Room submissions with rubric scores |
| workbook_grades | Excel grading results |
| action_plans, forecast_versions | FP&A actions and versioned forecasts |
| custom_metrics | Workbench formulas |
| capstone | capstone step answers and scores |

Backups are SQLite online-backup copies. Restore validates the file (SQLite integrity, required tables, scenario
JSON) and writes a safety copy before replacing data. Reset also writes a safety copy. The location can be
overridden with `--data-dir` or `AURELIA_DATA_DIR`.

## Excel integration

* `excel/workbooks.py` defines four workbook specifications (tasks, target cells, expected values computed in
  Python from the engine, expected functions, known mistakes, reconciliations) and generates training and
  reference files. `unique_path` guarantees an existing file is never overwritten.
* `excel/formula.py` is a documented Excel formula calculator (tokenizer, Pratt parser with Excel precedence and
  left-associative operators, error values, ranges, 34 functions). Unsupported functions raise
  `UnsupportedFormula` so the grader can fall back to Excel's saved value and say so.
* `excel/grader.py` copies the user's file into the data folder, identifies the workbook by a marker cell, loads it
  twice (formulas and saved values), recalculates, scores and records the result.

## Learning and assessment

`learning/content.py` holds the 9 stages and 26 topics as data (worked examples are functions that read the
engine). `learning/progress.py` implements the unlocking and competency rules from stored attempts.
`learning/coach.py` is a deterministic, rule-based coach (no language model, no network). `analysis/decisions.py`
and `analysis/capstone.py` define cases and rubrics; their expected answers come from the engine.

## Reports

`reports/management_report.py` builds the seven-section report as HTML and renders PDF with Qt's
`QTextDocument` + `QPdfWriter`. `reports/excel_export.py` writes formatted value snapshots with openpyxl.
`reports/portfolio.py` collects progress from the database into HTML/PDF/JSON.

## Testing

| Suite | Covers |
|---|---|
| tests/test_engine.py | hand-calculated hotel, integrity checks, validation, determinism |
| tests/test_finance.py | NPV, IRR (multiple/no roots), MIRR, payback, PMT, edge cases |
| tests/test_analysis.py | variances, materiality, flexible budget, explanations, RM, sensitivity, Monte Carlo, investment |
| tests/test_excel.py | formula calculator, workbook generation, grading, original-file protection |
| tests/test_learning_decisions.py | decision cases and rubric, content consistency, coach, competency rules, capstone, reports, portfolio, backup/restore, search |
| tests/test_vertical_slice.py | change → recalculate → compare → save → restore through AppState |
| tests/test_ui_pages.py | every page loads off-screen; Decision Room, Learning, Capstone, Excel Lab, Reports, Settings, Glossary interactions |
| tests/test_selftest_cli.py | self-test checks, report files, CLI options |

`aurelia/selftest.py` repeats the essential checks inside the shipped executable (`--selftest`).

## Packaging

`packaging/aurelia.spec` builds a one-folder, windowed PyInstaller application with the icon, a Windows version
resource and all `aurelia` submodules as hidden imports (pages are imported lazily). Unused Qt modules are
excluded. `build_windows.ps1` performs the full reproducible build and verification (see BUILD_WINDOWS.md).
