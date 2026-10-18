"""CLI self-test and command-line options."""
import json

from aurelia import __version__
from aurelia.app import main
from aurelia.selftest import run_checks, run_selftest


def test_selftest_checks_pass_without_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("AURELIA_DATA_DIR", str(tmp_path))
    res = run_checks(include_ui=False)
    failed = [(r.name, r.detail) for r in res if r.status == "FAIL"]
    assert not failed, failed
    assert any(r.status == "SKIP" for r in res)


def test_selftest_writes_text_and_json_report(tmp_path, monkeypatch):
    monkeypatch.setenv("AURELIA_DATA_DIR", str(tmp_path))
    ok, path = run_selftest(tmp_path / "r.txt", include_ui=False)
    assert ok and path.exists()
    assert "Overall: PASSED" in path.read_text(encoding="utf-8")
    data = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert data["passed"] and data["version"] == __version__


def test_cli_version_and_generate_workbooks(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("AURELIA_DATA_DIR", str(tmp_path / "d"))
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out
    assert main(["--generate-workbooks", str(tmp_path / "wb")]) == 0
    assert len(list((tmp_path / "wb").glob("*.xlsx"))) == 8
