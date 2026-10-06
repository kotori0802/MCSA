"""Stage 0.5A: folder-local Qt launch, no silent Tk, Python 3.12 selection."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer import cli


def _stage_copy(dest: Path) -> None:
    shutil.copytree(
        _REPO / "src",
        dest / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
    )
    shutil.copy2(_REPO / "run.bat", dest / "run.bat")


def _run_bat(bat: Path, *args: str, extra_env: dict[str, str] | None = None, timeout: int = 90):
    env = os.environ.copy()
    env["MCSA_NOPAUSE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)
    if extra_env:
        env.update(extra_env)
    env["MCSA_BAT"] = str(bat)
    command = "& $env:MCSA_BAT --% " + subprocess.list2cmdline(list(args))
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd="C:\\",
        env=env,
        timeout=timeout,
    )


def _python312() -> str:
    env = os.environ.copy()
    env["MCSA_NOPAUSE"] = "1"
    probe = subprocess.run(
        ["cmd.exe", "/d", "/c", "py -3.12 -c \"import sys; print(sys.executable)\""],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=30,
    )
    path = (probe.stdout or "").strip().splitlines()
    if probe.returncode == 0 and path:
        return path[-1].strip()
    if sys.version_info[:2] == (3, 12):
        return sys.executable
    raise unittest.SkipTest("Python 3.12 is not available on this machine")


class FolderLocalLaunchTests(unittest.TestCase):
    def test_copy_b_imports_b_not_a(self):
        with tempfile.TemporaryDirectory(prefix="mcsa_a_") as a_raw, tempfile.TemporaryDirectory(prefix="mcsa_b_") as b_raw:
            a = Path(a_raw)
            b = Path(b_raw)
            _stage_copy(a)
            _stage_copy(b)
            marker = a / "src" / "mouse_click_stability_analyzer" / "_copy_marker.txt"
            marker.write_text("A", encoding="utf-8")
            env = {
                "PYTHONPATH": str(a / "src"),
                "MCSA_NOPAUSE": "1",
            }
            result = _run_bat(b / "run.bat", "--print-source", extra_env=env)
            out = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, out)
            source_line = next(line for line in result.stdout.splitlines() if line.startswith("MCSA_SOURCE="))
            source = Path(source_line.split("=", 1)[1])
            self.assertTrue(str(source).lower().startswith(str(b.resolve()).lower()), source)
            self.assertFalse(str(source).lower().startswith(str(a.resolve()).lower()), source)
            self.assertIn("Source:", out)

    def test_missing_source_folder_fails(self):
        with tempfile.TemporaryDirectory(prefix="mcsa_empty_") as raw:
            dest = Path(raw)
            shutil.copy2(_REPO / "run.bat", dest / "run.bat")
            result = _run_bat(dest / "run.bat", "--print-source")
            text = result.stdout + result.stderr
            self.assertNotEqual(result.returncode, 0, text)
            self.assertIn("source folder is missing", text.lower())


class MissingPySide6Tests(unittest.TestCase):
    def test_normal_launch_does_not_open_tk(self):
        py = _python312()
        with tempfile.TemporaryDirectory(prefix="mcsa_nopyside_") as raw:
            dest = Path(raw)
            _stage_copy(dest)
            reports = dest / "reports"
            reports.mkdir()
            script = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])

class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"PySide6", "shiboken6"}:
            raise ModuleNotFoundError("No module named 'PySide6' (blocked)")
        return None

sys.meta_path.insert(0, Block())
from mouse_click_stability_analyzer import cli
import mouse_click_stability_analyzer.app as legacy

def _tk(**kwargs):
    raise AssertionError("legacy Tk launched")

legacy.run_visible_ui = _tk
rc = cli.main(["--ui", "auto", "--report-root", sys.argv[2]])
print("RC", rc)
raise SystemExit(rc)
"""
            proc = subprocess.run(
                [py, "-B", "-c", script, str(dest / "src"), str(reports)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            combined = proc.stdout + proc.stderr
            self.assertNotIn("legacy Tk launched", combined)
            self.assertIn("RC 1", proc.stdout)
            self.assertIn("Qt UI could not start", proc.stderr)
            self.assertIn("PySide6", proc.stderr)
            self.assertNotEqual(proc.returncode, 0)


class QtStartupExceptionTests(unittest.TestCase):
    def test_auto_ui_preserves_exception_and_skips_tk(self):
        with tempfile.TemporaryDirectory(prefix="mcsa_qtexc_") as raw:
            reports = Path(raw)
            tk = mock.Mock(return_value=0)
            with mock.patch("mouse_click_stability_analyzer.app.run_visible_ui", tk):
                with mock.patch("mouse_click_stability_analyzer.qt_shell.run_qt_ui", side_effect=RuntimeError("synthetic qt failure")):
                    err = io.StringIO()
                    with redirect_stderr(err):
                        rc = cli.main(["--ui", "auto", "--report-root", str(reports)])
            self.assertEqual(rc, 1)
            tk.assert_not_called()
            text = err.getvalue()
            self.assertIn("Qt UI could not start", text)
            self.assertIn("synthetic qt failure", text)
            self.assertNotIn("falling back to Tk", text)

    def test_explicit_qt_flag_same_failure_contract(self):
        with tempfile.TemporaryDirectory(prefix="mcsa_qtexc2_") as raw:
            with mock.patch("mouse_click_stability_analyzer.app.run_visible_ui") as tk:
                with mock.patch("mouse_click_stability_analyzer.qt_shell.run_qt_ui", side_effect=RuntimeError("boom")):
                    err = io.StringIO()
                    with redirect_stderr(err):
                        rc = cli.main(["--ui", "qt", "--report-root", str(raw)])
            self.assertEqual(rc, 1)
            tk.assert_not_called()
            self.assertIn("boom", err.getvalue())


class ExplicitLegacyTkTests(unittest.TestCase):
    def test_ui_tk_is_the_only_legacy_entry(self):
        with tempfile.TemporaryDirectory(prefix="mcsa_tk_") as raw:
            tk = mock.Mock(return_value=0)
            with mock.patch("mouse_click_stability_analyzer.app.run_visible_ui", tk):
                rc = cli.main(["--ui", "tk", "--report-root", str(raw)])
            self.assertEqual(rc, 0)
            tk.assert_called_once()

    def test_default_auto_does_not_call_tk(self):
        with tempfile.TemporaryDirectory(prefix="mcsa_auto_") as raw:
            tk = mock.Mock(return_value=0)
            with mock.patch("mouse_click_stability_analyzer.app.run_visible_ui", tk):
                with mock.patch("mouse_click_stability_analyzer.qt_shell.run_qt_ui", return_value=0):
                    rc = cli.main(["--ui", "auto", "--report-root", str(raw)])
            self.assertEqual(rc, 0)
            tk.assert_not_called()


class PythonSelectionTests(unittest.TestCase):
    def test_run_bat_does_not_select_py_dash_3(self):
        text = (_REPO / "run.bat").read_text(encoding="utf-8")
        self.assertIn("py -3.12", text)
        self.assertIn(".venv\\Scripts\\python.exe", text)
        self.assertNotIn("py -3 -B", text)
        self.assertNotIn("py -3 -c", text)
        self.assertIn("PYTHONPATH=%MCSA_SRC%", text)

    def test_install_bat_targets_local_venv_only(self):
        text = (_REPO / "install.bat").read_text(encoding="utf-8")
        self.assertIn("-m venv .venv", text)
        self.assertIn(".venv\\Scripts\\python.exe", text)
        self.assertNotIn("py -3 -m pip", text)
        self.assertIn('pip install -e ".[gui]"', text)

    def test_supported_launch_uses_python_312(self):
        result = _run_bat(_REPO / "run.bat", "--print-source")
        out = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, out)
        py_line = next(line for line in result.stdout.splitlines() if line.startswith("MCSA_PYTHON="))
        self.assertTrue(py_line.split("=", 1)[1].startswith("3.12."), py_line)
        self.assertNotIn("3.14.", py_line)
        source_line = next(line for line in result.stdout.splitlines() if line.startswith("MCSA_SOURCE="))
        self.assertIn("mouse_click_stability_analyzer", source_line)
        repo = str(_REPO.resolve()).lower()
        self.assertTrue(source_line.split("=", 1)[1].lower().startswith(repo), source_line)


class ReportRootTests(unittest.TestCase):
    def test_unwritable_report_root_fails_without_tk(self):
        with tempfile.TemporaryDirectory(prefix="mcsa_ro_") as raw:
            blocked = Path(raw) / "reports"
            blocked.write_text("not a directory", encoding="utf-8")
            tk = mock.Mock(return_value=0)
            with mock.patch("mouse_click_stability_analyzer.app.run_visible_ui", tk):
                err = io.StringIO()
                with redirect_stderr(err):
                    rc = cli.main(["--report-root", str(blocked)])
            self.assertEqual(rc, 1)
            tk.assert_not_called()
            self.assertIn("not writable", err.getvalue().lower())

    def test_mcsa_root_mismatch_fails(self):
        env = {"MCSA_ROOT": r"C:\definitely-not-this-checkout"}
        with mock.patch.dict(os.environ, env, clear=False):
            err = io.StringIO()
            with redirect_stderr(err):
                rc = cli.main(["--print-source"])
        self.assertEqual(rc, 1)
        self.assertIn("Wrong or missing MCSA source folder", err.getvalue())


class SpacesAndNonAsciiLaunchTests(unittest.TestCase):
    def test_spaces_and_cjk_print_source(self):
        py = _python312()
        with tempfile.TemporaryDirectory(prefix="mcsa_paths_") as raw:
            base = Path(raw)
            space = base / "MCSA Test" / "copy"
            cjk = base / "測試工具" / "MCSA"
            for dest in (space, cjk):
                dest.mkdir(parents=True)
                _stage_copy(dest)
                env = os.environ.copy()
                env["PYTHONPATH"] = str(dest / "src")
                env["MCSA_ROOT"] = str(dest)
                env["PYTHONIOENCODING"] = "utf-8"
                proc = subprocess.run(
                    [py, "-B", "-m", "mouse_click_stability_analyzer", "--print-source"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd="C:\\",
                    env=env,
                    timeout=45,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                source_line = next(line for line in proc.stdout.splitlines() if line.startswith("MCSA_SOURCE="))
                self.assertTrue(
                    source_line.split("=", 1)[1].lower().startswith(str(dest.resolve()).lower()),
                    source_line,
                )
                bat = _run_bat(dest / "run.bat", "--print-source")
                bat_out = bat.stdout + bat.stderr
                self.assertEqual(bat.returncode, 0, bat_out)
                bat_source = next(line for line in bat.stdout.splitlines() if line.startswith("MCSA_SOURCE="))
                self.assertTrue(
                    bat_source.split("=", 1)[1].lower().startswith(str(dest.resolve()).lower()),
                    bat_source,
                )


if __name__ == "__main__":
    unittest.main()
