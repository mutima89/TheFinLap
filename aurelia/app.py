"""Application entry point.

Usage:
  Aurelia_Finance_Lab.exe                 launch the desktop app
  Aurelia_Finance_Lab.exe --selftest      run calculation & integrity self-test, write a diagnostic report
                                          (--report FILE to choose the path, --quiet for no dialog)
  Aurelia_Finance_Lab.exe --generate-workbooks DIR   write the Excel practice workbooks to DIR
  Aurelia_Finance_Lab.exe --data-dir DIR  use a specific data folder (portable mode)
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from pathlib import Path

from . import __version__ as APP_VERSION


def _parse(argv):
    p = argparse.ArgumentParser(prog="Aurelia_Finance_Lab", description="Aurelia Finance Lab")
    p.add_argument("--selftest", action="store_true", help="run the self-test and exit")
    p.add_argument("--report", default=None, help="path for the self-test report (default: data folder)")
    p.add_argument("--generate-workbooks", metavar="DIR", default=None)
    p.add_argument("--data-dir", default=None)
    p.add_argument("--smoke-ui", action="store_true", help="open every page offscreen and exit (UI self-test)")
    p.add_argument("--quiet", action="store_true", help="no dialog after --selftest (for build scripts)")
    p.add_argument("--version", action="store_true")
    return p.parse_args(argv)


def _ensure_streams() -> None:
    """A windowed (no-console) executable has no stdout/stderr; give print() somewhere to go."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _headless() -> bool:
    return not sys.platform.startswith(("win", "darwin")) and not os.environ.get("DISPLAY") \
        and not os.environ.get("WAYLAND_DISPLAY")


def main(argv=None) -> int:
    has_console = sys.stdout is not None
    _ensure_streams()
    args = _parse(argv if argv is not None else sys.argv[1:])
    if (args.selftest or args.smoke_ui) and _headless():
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.data_dir:
        os.environ["AURELIA_DATA_DIR"] = args.data_dir
    if args.version:
        print(f"Aurelia Finance Lab {APP_VERSION}")
        return 0
    if args.selftest:
        from .selftest import run_selftest
        ok, path = run_selftest(args.report, include_ui=True)
        msg = f"Self-test {'PASSED' if ok else 'FAILED'} – report: {path}"
        print(msg)
        if not has_console and not args.quiet:
            from PySide6.QtWidgets import QApplication, QMessageBox
            QApplication.instance() or QApplication(sys.argv[:1])
            (QMessageBox.information if ok else QMessageBox.warning)(None, "Aurelia Finance Lab self-test", msg)
        return 0 if ok else 1
    if args.generate_workbooks:
        from .excel.workbooks import generate_all
        out = generate_all(Path(args.generate_workbooks))
        for f in out:
            print(f)
        return 0
    return run_gui(smoke=args.smoke_ui)


def run_gui(smoke: bool = False) -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QIcon, QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    from PySide6.QtCore import QLocale
    QLocale.setDefault(QLocale(QLocale.English, QLocale.UnitedStates))
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Aurelia Finance Lab")
    app.setOrganizationName("Aurelia Finance Lab")
    icon = Path(__file__).with_name("assets") / "aurelia.ico"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    from .persistence.db import Database
    from .ui.state import AppState
    from .ui.main_window import MainWindow, apply_theme, PAGES

    try:
        db = Database()
        problems = db.integrity_check()
    except Exception as exc:  # noqa: BLE001
        QMessageBox.critical(None, "Aurelia Finance Lab", f"Could not open the local database:\n{exc}")
        return 2
    state = AppState(db)
    apply_theme(app, state.theme)
    win = MainWindow(state)
    win.show()
    if problems:
        QMessageBox.warning(win, "Data integrity", "Data checks reported problems:\n" + "\n".join(problems) +
                            "\n\nUse Settings → Restore backup if needed.")
    if not db.get_setting("onboarded", False) and not smoke:
        from .ui.onboarding import show_onboarding
        QTimer.singleShot(300, lambda: show_onboarding(win, state))
    if smoke:
        failures = []
        for key, *_ in PAGES:
            try:
                win.go(key)
                app.processEvents()
                w = win.pages[key]
                err = getattr(w, "load_error", None) or getattr(w, "refresh_error", None)
                if err:
                    failures.append(key + ": " + err)
            except Exception:  # noqa: BLE001
                failures.append(key + ": " + traceback.format_exc())
        win.toggle_theme()
        app.processEvents()
        win.toggle_theme()
        print("UI smoke test:", "PASSED" if not failures else f"FAILED {failures}")
        win.close()
        return 0 if not failures else 1
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
