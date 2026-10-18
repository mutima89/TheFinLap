# Build and verification report

Aurelia Finance Lab 1.0.0 · report date 2026-10-18

## Summary

| Item | Status |
|---|---|
| Complete source code | Delivered (`aurelia/`, about 15,600 lines of Python) |
| Automated tests | **166 passed, 0 failed** on Python 3.12.3 with the pinned dependencies, and on Python 3.13.16 (Linux, Qt off-screen) |
| Built-in self-test (`--selftest`) | **14 of 14 checks passed** from source on Python 3.12 and 3.13 |
| PyInstaller spec | Trial-built on **Linux** with PyInstaller 6.22.3; the frozen Linux application passed its full self-test (14/14, including every page and PDF export) and the UI smoke test |
| Pinned dependencies | All 32 packages in `requirements-lock.txt` resolved to binary wheels for **Windows x64 / CPython 3.12** (`pip download --platform win_amd64 --python-version 3.12 --only-binary=:all:`) |
| Windows build scripts | `build_windows.bat` and `build_windows.ps1` written; the PowerShell script parses without errors in PowerShell 7.4.6 |
| **Windows `.exe`** | **Built and self-tested on Windows by GitHub Actions.** `build_windows.ps1` ran end to end on a GitHub-hosted Windows Server 2022 runner: 166 tests passed on Windows, PyInstaller built the exe, and the built exe's `--selftest` passed (14/14 checks, including every page and PDF export). Each GitHub Release is produced by the same workflow and carries its own `BUILD_RESULT.txt`, self-test report and SHA-256 checksums. Not yet tried by a person on a desktop Windows 10/11 PC (see *Not verified*). |

## How the Windows .exe is produced

PyInstaller only builds for the operating system it runs on, and the release was prepared in a Linux container.
The Windows build therefore runs in GitHub Actions ([`.github/workflows/release.yml`](../.github/workflows/release.yml))
on a GitHub-hosted Windows runner, using exactly the same `build_windows.ps1` a user would run. The workflow only
publishes a release if the tests, the build and the built executable's self-test all pass.

### First Windows verification run (2026-10-18)

Workflow run [39094902852](https://github.com/mutima89/TheFinLap/actions/runs/39094902852), commit `84f2b06`:

```
Aurelia Finance Lab 1.0.0 - Windows build result
Machine:      Microsoft Windows NT 10.0.20348.0, AMD64
Python:       Python 3.12.10
PyInstaller:  6.22.3
Tests:        166 passed in 46.49s
Exe:          dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe
Exe self-test: PASSED (report: build\exe-selftest-report.txt)
Package:      dist\Aurelia_Finance_Lab-1.0.0-win64.zip (about 90 MB)
```

The published v1.0.0 release was rebuilt by the same workflow from the tagged commit; its own `BUILD_RESULT.txt`
and checksums are attached to the release.

## Exact steps to produce and verify the .exe on Windows

Full detail is in [BUILD_WINDOWS.md](BUILD_WINDOWS.md).

1. Install 64-bit Python 3.12 from python.org.
2. Copy the project folder to the PC and run `build_windows.bat`.
3. The script installs `requirements-lock.txt` into `.venv-build`, runs the 166 tests, builds with
   `packaging\aurelia.spec`, runs `dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe --selftest --quiet` against a
   temporary data folder, and stops unless the report says `Overall: PASSED`.
4. Results: `dist\Aurelia_Finance_Lab\Aurelia_Finance_Lab.exe`, `dist\Aurelia_Finance_Lab-1.0.0-win64.zip`,
   `dist\SHA256SUMS.txt`, `build\BUILD_RESULT.txt`, `build\test-output.txt`, `build\exe-selftest-report.txt`.
5. Append `build\BUILD_RESULT.txt` and the self-test report to this document to record the Windows verification.

## What was verified, and how

### Test suite (pytest, Qt off-screen)

| File | Tests | Scope |
|---|---|---|
| test_engine.py | 18 | Hand-calculated 100-room hotel (room nights, revenue, commission, costs, cash), 14 integrity checks across scenarios, validation, determinism |
| test_finance.py | 24 | NPV, IRR incl. multiple and missing roots, MIRR, payback, discounted payback, PI, PMT, terminal value, invalid inputs |
| test_analysis.py | 30 | Price/volume/mix by hand, F/U classification, materiality, flexible budget identity, explanations never inventing causes, RM (displacement by hand, MLOS, overbooking, pace), sensitivity by hand, Monte Carlo reproducibility, investment cases |
| test_excel.py | 24 | Formula calculator (precedence, associativity, errors, lookups, finance and date functions, circularity, unsupported functions), reference workbooks equal Python answers, generation never overwrites, grader: reference 100%, blank 0%, typed values 70%, mistake feedback, original file hash unchanged |
| test_learning_decisions.py | 48 | All 9 Decision Room cases (components reconcile, strong answers score ≥80, weak <40, wrong-sign estimates, condition terms, outcomes), all 26 topics complete with engine-backed worked examples, every answer key self-consistent and every known mistake diagnosed, coach diagnoses, competency rules (quiz capped at Developing, Demonstrated needs two practical passes with one hint-free), step and stage unlocking, capstone recoverability and full-mark answers, management report's seven sections, portfolio export and disclaimer, statement export, backup/validate/reset/restore, invalid backups rejected, search |
| test_vertical_slice.py | 7 | Change rate, demand and cost → recalculation → compare → save → restore; validation; undo/redo; draft survives restart; audit trail |
| test_ui_pages.py | 12 | All 15 pages load and refresh, theme toggle, Decision Room full cycle, Learning exercise and locks, Capstone steps, Reports exports (HTML, PDF, Excel, portfolio), Excel Lab generate and grade with original unchanged, Settings integrity/backup/reset/restore, typed reset confirmation, Glossary search, Dashboard panels |
| test_selftest_cli.py | 3 | Self-test checks and report files, `--version`, `--generate-workbooks` |

### Self-test checks (the same checks run inside the executable)

Runtime and libraries · data folder writable · user database integrity (read-only) · backup/restore/reset on a
temporary database · finance functions against hand values · rooms engine against a hand calculation · 14
integrity checks for all reference scenarios · FP&A variance reconciliation and evidence · all Decision Room options
reconcile · learning content answer keys · capstone recoverability · Excel calculator, all four workbooks
(reference 100%, blank 0%, originals unchanged) · no networking imports · every page, theme toggle and PDF export.

### Static checks

pyflakes reports no issues in `aurelia/`, `tests/` and `tools/`.

### Manual review

Off-screen screenshots of the Dashboard, Decision Room, Learning Path, Capstone, Excel Lab, Reports, Glossary and
Settings pages were inspected for layout problems; issues found (cramped case list, raw IRR decimals, stray
keyboard-mnemonic underscores in labels) were fixed.

## Environments used

| | Version |
|---|---|
| OS | Linux 6.18 x86_64 (container); Windows Server 2022 (GitHub Actions runner) for the Windows build |
| Python | 3.12.3 (pinned dependency set) and 3.13.16 on Linux; 3.12.10 on Windows |
| PySide6 / pandas / NumPy / Matplotlib / openpyxl | 6.8.1 / 3.0.5 / 2.5.3 / 3.11.2 / 3.1.5 |
| pytest / pytest-qt / PyInstaller | 9.1.1 / 4.5.0 / 6.22.3 |

## Not verified

* Hands-on use of the Windows executable by a person on a desktop Windows 10/11 PC: appearance with Windows fonts
  and DPI scaling, SmartScreen behaviour and native file dialogs. The CI self-test opens every page and exports a
  PDF inside the built exe, but nobody has looked at the screen.
* Opening the generated workbooks in Microsoft Excel itself (they were checked with openpyxl and the app's own
  calculator, and reference formulas were confirmed to produce the expected values).
