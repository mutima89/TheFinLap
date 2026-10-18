# Release notes

## 1.0.0 (2026-10-17)

First complete release.

**Simulation**
* Single calculation-graph engine (13 nodes, 97 line items) for The Aurelia Grand: daily rooms demand by five
  segments with seasonality, events, elasticity, cancellations, no-shows, overbooking and group blocks; F&B, spa,
  events and other departments; payroll; undistributed costs; management fees; capex; working capital with VAT and
  deposits; debt, revolver, tax and dividends; integrated income statement, balance sheet and cash flow over 36
  months; 14 integrity checks on every run.
* 91 validated drivers, Base/Upside/Downside reference scenarios, user scenarios, cloning, checkpoints, undo/redo,
  auto-saved draft, audit trail, comparison.

**Analysis**
* Revenue Management: segment/channel economics, pace, displacement, rate search, MLOS, overbooking, forecast
  accuracy.
* FP&A: budget vs actual vs latest estimate, F/U classification with context, materiality, price/volume/mix,
  flexible budget, evidence-backed explanations that separate measured drivers from causes to confirm, action
  plans, forecast versions with approval.
* Statements, Modelling Workbench (models A–H, dependency viewer, safe custom formulas), sensitivity (one-way,
  two-way, tornado, break-even), Monte Carlo with visible seed and distributions, six investment cases.

**Practice**
* Executive Decision Room: nine cases, seven steps, five-dimension rubric, outcome reveal and next investigations.
* Learning Path: nine stages, 26 topics with engine-backed worked examples, guided/independent exercises,
  applied tasks and competency checks; competency-based unlocking; offline rule-based coach.
* Excel Lab: four generated workbooks with reference versions, own formula calculator (34 functions), grading of a
  copy with value/method scoring, known-mistake feedback and reconciliation checks.
* Capstone: messy dataset with ten scored steps ending in a meeting defence.

**Output and data**
* Seven-section monthly management report (HTML/PDF), Excel exports, scenario comparison, portfolio
  (HTML/PDF/JSON).
* Local SQLite storage in the per-user application-data folder, backup/restore with validation and safety copies,
  reset with typed confirmation, scenario import/export, integrity check, storage disclosure.
* Onboarding tour, global search, keyboard shortcuts, light and dark themes, SAR/USD display.

**Quality and packaging**
* pytest suite (engine, finance, analysis, Excel, learning, decisions, capstone, reports, persistence, UI
  off-screen, self-test).
* `--selftest` diagnostic report built into the application.
* Pinned dependencies with a Windows/Python 3.12 lock file; PyInstaller spec; `build_windows.bat` /
  `build_windows.ps1` that test, build, self-test the executable and package it.

**Not included in this release:** a Windows executable built by the release author (see KNOWN_LIMITATIONS.md).
