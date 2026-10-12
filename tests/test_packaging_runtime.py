"""Packaging helpers: frozen-aware paths, helper command, bundled resources."""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer import cli
from mouse_click_stability_analyzer.adapters.raw_input_subprocess import WindowsRawInputSubprocess
from mouse_click_stability_analyzer.runtime import (
    HELPER_ENV,
    HELPER_FLAG,
    REQUIRED_QT_ASSETS,
    REQUIRED_STRING_FILES,
    application_dir,
    default_report_root,
    helper_command,
    is_frozen,
    is_helper_mode,
    missing_runtime_resources,
    qt_asset_dir,
    windows_file_version,
)
from mouse_click_stability_analyzer.schema import TOOL_VERSION


class PackagingRuntimeTests(unittest.TestCase):
    def test_source_mode_is_not_frozen(self):
        self.assertFalse(is_frozen())

    def test_source_application_dir_is_repo_root(self):
        repo = Path(__file__).resolve().parents[1]
        self.assertEqual(application_dir(), repo)
        self.assertEqual(default_report_root(), repo / "reports")
        self.assertEqual(cli.default_report_root(), repo / "reports")

    def test_windows_file_version_matches_tool_version(self):
        self.assertEqual(TOOL_VERSION, "1.0.0")
        self.assertEqual(windows_file_version(), "1.0.0.0")

    def test_required_resources_are_present_in_source(self):
        self.assertEqual(missing_runtime_resources(), [])
        assets = qt_asset_dir()
        for name in REQUIRED_QT_ASSETS:
            self.assertTrue((assets / name).is_file(), name)
        from mouse_click_stability_analyzer.strings.loader import ALL_RESOURCE_FILES

        self.assertEqual(set(REQUIRED_STRING_FILES), set(ALL_RESOURCE_FILES))

    def test_source_helper_command_uses_bridge_script(self):
        command = helper_command()
        self.assertEqual(command[0], sys.executable)
        self.assertTrue(command[1].endswith("raw_input_bridge.py"))
        self.assertTrue(Path(command[1]).is_file())
        self.assertNotIn(HELPER_FLAG, command)

    def test_frozen_helper_command_uses_same_exe_flag(self):
        fake_exe = r"C:\MCSA Test\MCSA-1.0.0-win64\MCSA.exe"
        with mock.patch("mouse_click_stability_analyzer.runtime.is_frozen", return_value=True):
            with mock.patch("mouse_click_stability_analyzer.runtime.sys") as frozen_sys:
                frozen_sys.executable = fake_exe
                command = helper_command()
        self.assertEqual(command, [fake_exe, HELPER_FLAG])

    def test_helper_mode_does_not_spawn_another_helper(self):
        adapter = WindowsRawInputSubprocess(lambda _event: None)
        with mock.patch.dict(os.environ, {HELPER_ENV: "1"}, clear=False):
            adapter.start()
        self.assertFalse(adapter.running)
        self.assertIsNone(adapter.process)
        self.assertIn("must not start another helper", adapter.last_error)

    def test_helper_flag_is_detected_before_gui(self):
        self.assertTrue(is_helper_mode([HELPER_FLAG]))
        self.assertFalse(is_helper_mode([]))

    def test_cli_helper_flag_does_not_parse_gui_args(self):
        with mock.patch("mouse_click_stability_analyzer.cli._run_raw_input_helper", return_value=17) as helper:
            code = cli.main([HELPER_FLAG, "--ui", "qt"])
        self.assertEqual(code, 17)
        helper.assert_called_once_with()

    def test_version_info_file_contains_1_0_0(self):
        text = (Path(__file__).resolve().parents[1] / "packaging" / "file_version_info.txt").read_text(encoding="utf-8")
        self.assertIn("u'ProductVersion', u'1.0.0'", text)
        self.assertIn("filevers=(1, 0, 0, 0)", text)
        self.assertIn("u'FileDescription', u'Mouse Click Stability Analyzer'", text)


class _Cp1252Stream:
    """Stdout stand-in whose text write rejects Chinese, like a Windows cp1252 console."""

    encoding = "cp1252"
    errors = "strict"

    def __init__(self):
        self.buffer = io.BytesIO()
        self.writes: list[str] = []

    def write(self, text: str) -> int:
        encoded = text.encode(self.encoding, errors="strict")
        self.writes.append(text)
        self.buffer.write(encoded)
        return len(text)

    def flush(self) -> None:
        return None


class DiagnosticEncodingTests(unittest.TestCase):
    def test_ascii_diagnostic_text(self):
        buf = io.StringIO()
        cli.emit_diagnostic("MCSA_SOURCE=C:\\MCSA\\cli.py", stream=buf)
        self.assertEqual(buf.getvalue(), "MCSA_SOURCE=C:\\MCSA\\cli.py\n")

    def test_chinese_unicode_text_on_utf8_stream(self):
        buf = io.StringIO()
        cli.emit_diagnostic("MCSA_PROJECT_ROOT=C:\\測試工具", stream=buf)
        self.assertIn("測試工具", buf.getvalue())

    def test_non_ascii_path_survives_cp1252_stdout(self):
        stream = _Cp1252Stream()
        path = r"C:\測試工具\MCSA-1.0.0-win64"
        cli.emit_diagnostic(f"MCSA_PROJECT_ROOT={path}", stream=stream)
        raw = stream.buffer.getvalue()
        self.assertTrue(raw)
        self.assertNotIn("測試".encode("utf-8"), raw)
        self.assertIn(b"MCSA_PROJECT_ROOT=C:\\", raw)
        decoded = raw.decode("cp1252", errors="replace")
        self.assertIn("MCSA-1.0.0-win64", decoded)
        self.assertNotIn("測試", decoded)
        self.assertIn("?", decoded)

    def test_cp1252_stream_without_buffer_degrades(self):
        stream = _Cp1252Stream()
        del stream.buffer
        stream.buffer = None
        cli.emit_diagnostic(r"MCSA_PROJECT_ROOT=C:\測試工具\MCSA-1.0.0-win64", stream=stream)
        self.assertEqual(stream.writes, ["MCSA_PROJECT_ROOT=C:\\????\\MCSA-1.0.0-win64\n"])

    def test_closed_stream_does_not_raise(self):
        buf = io.StringIO()
        buf.close()
        cli.emit_diagnostic(r"MCSA_PROJECT_ROOT=C:\測試工具", stream=buf)

    def test_missing_stdout_does_not_raise(self):
        chinese = Path(r"C:\測試工具\MCSA-1.0.0-win64") / "reports"
        with mock.patch.object(cli.sys, "stdout", None):
            cli.emit_diagnostic(f"MCSA_REPORT_ROOT={chinese}")
            cli.print_source_diagnostic()

    def test_missing_stderr_does_not_raise(self):
        chinese = Path(r"C:\測試工具\MCSA-1.0.0-win64") / "reports"
        with mock.patch.object(cli.sys, "stderr", None):
            self.assertEqual(cli._fail("Report folder is not writable", str(chinese)), 1)

    def test_fail_on_cp1252_stderr_does_not_raise(self):
        stream = _Cp1252Stream()
        with mock.patch.object(cli.sys, "stderr", stream):
            self.assertEqual(cli._fail("Report folder is not writable", r"C:\測試工具\reports"), 1)
        text = stream.buffer.getvalue().decode("cp1252")
        self.assertIn("[ERROR] Report folder is not writable", text)
        self.assertIn(r"C:\????\reports", text)

    def test_main_print_source_on_cp1252_stdout_returns_zero(self):
        stream = _Cp1252Stream()
        root = Path(r"C:\測試工具\MCSA-1.0.0-win64")
        with mock.patch.object(cli, "application_dir", return_value=root):
            with mock.patch.object(cli, "default_report_root", return_value=root / "reports"):
                with mock.patch.object(cli.sys, "stdout", stream):
                    with mock.patch.object(cli, "_configure_stdio"):
                        rc = cli.main(["--print-source"])
        self.assertEqual(rc, 0)
        text = stream.buffer.getvalue().decode("cp1252")
        self.assertIn(r"MCSA_PROJECT_ROOT=C:\????\MCSA-1.0.0-win64", text)

    def test_configure_stdio_only_for_console_modes(self):
        with mock.patch.object(cli, "_configure_stdio") as configure:
            with mock.patch.object(cli, "print_source_diagnostic"):
                cli.main(["--print-source"])
        configure.assert_called_once_with()
        with mock.patch.object(cli, "_configure_stdio") as configure:
            with mock.patch.object(cli, "_run_raw_input_helper", return_value=0):
                cli.main([HELPER_FLAG])
        configure.assert_not_called()
        with mock.patch.object(cli, "_configure_stdio") as configure:
            with mock.patch("mouse_click_stability_analyzer.qt_shell.run_qt_ui", return_value=0):
                with mock.patch.object(cli, "ensure_writable_report_root"):
                    cli.main(["--ui", "qt"])
        configure.assert_not_called()

    def test_print_source_diagnostic_with_chinese_path_on_cp1252(self):
        stream = _Cp1252Stream()
        root = Path(r"C:\測試工具\MCSA-1.0.0-win64")
        with mock.patch.object(cli, "package_file", return_value=root / "_internal" / "mouse_click_stability_analyzer" / "cli.py"):
            with mock.patch.object(cli, "application_dir", return_value=root):
                with mock.patch.object(cli, "default_report_root", return_value=root / "reports"):
                    with mock.patch.object(cli, "is_frozen", return_value=True):
                        with mock.patch.object(cli.sys, "executable", str(root / "MCSA.exe")):
                            with mock.patch.object(cli.sys, "stdout", stream):
                                cli.print_source_diagnostic()
        text = stream.buffer.getvalue().decode("cp1252", errors="replace")
        self.assertIn("MCSA_SOURCE=", text)
        self.assertIn("MCSA_FROZEN=1", text)
        self.assertIn("MCSA.exe", text)
        self.assertIn("reports", text)

    def test_configure_stdio_skips_none_streams(self):
        with mock.patch.object(cli.sys, "stdout", None), mock.patch.object(cli.sys, "stderr", None):
            cli._configure_stdio()


@unittest.skipUnless(sys.platform == "win32", "Raw Input bridge is Windows-only")
class HelperWireProtocolTests(unittest.TestCase):
    DEVICE = "\\\\?\\HID#VID_046D&PID_C08B#滑鼠裝置#{378de44c-56ef-11d1-bc8c-00a0c91405dd}"
    ERROR = "WM_INPUT handle error: [WinError 5] 存取被拒。"

    def setUp(self):
        from mouse_click_stability_analyzer.adapters import raw_input_bridge

        self.bridge = raw_input_bridge

    def _helper_lines(self, *objects) -> list[str]:
        stream = _Cp1252Stream()
        with mock.patch.object(self.bridge.sys, "stdout", stream):
            for obj in objects:
                if isinstance(obj, str):
                    self.bridge.emit_error(obj)
                else:
                    self.bridge.emit(obj)
        return stream.writes

    def _mouse_event(self) -> dict:
        return {
            "type": "mouse_button",
            "button": "Left",
            "event_type": "down",
            "x": 0,
            "y": 0,
            "time_perf": 12.5,
            "capture_source": "windows_raw_input",
            "device_source": self.DEVICE,
            "raw_hdevice": "65599",
            "raw_dx": 0,
            "raw_dy": 0,
        }

    def test_unicode_on_cp1252_stdout_failed_with_previous_encoding(self):
        with self.assertRaises(UnicodeEncodeError):
            _Cp1252Stream().write(json.dumps({"device_source": self.DEVICE}, ensure_ascii=False))

    def test_helper_lines_are_ascii_newline_delimited_json(self):
        lines = self._helper_lines(self._mouse_event(), self.ERROR)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertTrue(line.isascii(), line)
            self.assertTrue(line.endswith("\n"))
            self.assertEqual(line.count("\n"), 1)

    def test_chinese_device_source_round_trips_to_parent_callback(self):
        lines = self._helper_lines(self._mouse_event())
        received: list[dict] = []
        adapter = WindowsRawInputSubprocess(received.append)
        adapter.running = True
        adapter.process = SimpleNamespace(stdout=iter(lines))
        adapter._read_stdout()
        self.assertEqual(received, [self._mouse_event()])
        self.assertEqual(received[0]["device_source"], self.DEVICE)

    def test_chinese_helper_error_round_trips_to_parent(self):
        lines = self._helper_lines(self.ERROR)
        adapter = WindowsRawInputSubprocess(lambda _event: self.fail("error must not reach callback"))
        adapter.running = True
        adapter.process = SimpleNamespace(stdout=iter(lines))
        adapter._read_stdout()
        self.assertEqual(adapter.last_error, self.ERROR)

    def test_ready_handshake_unchanged(self):
        lines = self._helper_lines({"type": "ready", "capture_source": "windows_raw_input_bridge"})
        self.assertEqual(lines, ['{"type": "ready", "capture_source": "windows_raw_input_bridge"}\n'])


class FrozenLegacyTkTests(unittest.TestCase):
    def test_frozen_tk_is_rejected_without_importing_tkinter(self):
        with mock.patch.object(cli, "is_frozen", return_value=True):
            with mock.patch.object(cli, "_show_gui_startup_error", side_effect=cli._fail) as startup_error:
                with mock.patch.dict(sys.modules, {"tkinter": None}):
                    with mock.patch("mouse_click_stability_analyzer.app.run_visible_ui") as run_tk:
                        with mock.patch.object(cli, "ensure_writable_report_root") as ensure_root:
                            rc = cli.main(["--ui", "tk"])
        self.assertEqual(rc, 1)
        run_tk.assert_not_called()
        ensure_root.assert_not_called()
        message = startup_error.call_args.args[0]
        self.assertEqual(message, "Legacy Tk UI is not included in the packaged Windows release.")
        self.assertIn("Qt UI", startup_error.call_args.args[1])

    def test_frozen_startup_error_uses_native_dialog_not_qt(self):
        with mock.patch.object(cli, "is_frozen", return_value=True):
            with mock.patch.object(cli, "write_startup_log", return_value=None):
                with mock.patch.object(cli, "_native_error_dialog") as dialog:
                    with mock.patch.dict(sys.modules, {"PySide6.QtWidgets": None}):
                        rc = cli.main(["--ui", "tk"])
        self.assertEqual(rc, 1)
        title, text = dialog.call_args.args
        self.assertEqual(title, "Mouse Click Stability Analyzer")
        self.assertIn("Legacy Tk UI is not included in the packaged Windows release.", text)

    def test_source_startup_error_shows_no_dialog(self):
        with mock.patch.object(cli, "_native_error_dialog") as dialog:
            self.assertEqual(cli._show_gui_startup_error("Report folder is not writable"), 1)
        dialog.assert_not_called()

    def test_source_tk_keeps_legacy_entry_point(self):
        with mock.patch("mouse_click_stability_analyzer.app.run_visible_ui", return_value=0) as run_tk:
            with mock.patch.object(cli, "ensure_writable_report_root"):
                rc = cli.main(["--ui", "tk"])
        self.assertEqual(rc, 0)
        run_tk.assert_called_once()

    def test_spec_still_excludes_tkinter(self):
        spec = (Path(__file__).resolve().parents[1] / "packaging" / "mcsa.spec").read_text(encoding="utf-8")
        self.assertIn('excludes=["tkinter"', spec)


def _load_check_build_env():
    path = Path(__file__).resolve().parents[1] / "packaging" / "check_build_env.py"
    spec = importlib.util.spec_from_file_location("mcsa_check_build_env", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildEnvironmentGuardTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def setUp(self):
        self.guard = _load_check_build_env()
        self.versions = {
            "pyinstaller": "6.13.0",
            "PySide6": "6.11.0",
            "openpyxl": "3.1.5",
            "mouse-click-stability-analyzer": "1.0.0",
        }
        self.origin = (self.ROOT / "src" / "mouse_click_stability_analyzer" / "__init__.py").resolve()

    def _check(self, *, version_info=(3, 12, 10), is_64bit=True, origin="repo"):
        resolved = self.origin if origin == "repo" else origin
        return self.guard.check_environment(
            self.ROOT,
            version_info=version_info,
            is_64bit=is_64bit,
            get_version=self.versions.get,
            get_origin=lambda _name: resolved,
        )

    def test_pinned_environment_passes(self):
        self.assertEqual(self._check(), [])

    def test_wrong_python_fails(self):
        self.assertTrue(any("Python 3.12 64-bit" in e for e in self._check(version_info=(3, 13, 1))))
        self.assertTrue(any("32-bit" in e for e in self._check(is_64bit=False)))

    def test_wrong_tool_versions_fail(self):
        for name, wrong in (("pyinstaller", "6.19.0"), ("PySide6", "6.10.2"), ("openpyxl", "3.1.4")):
            with self.subTest(name=name):
                self.setUp()
                self.versions[name] = wrong
                errors = self._check()
                self.assertEqual(len(errors), 1)
                self.assertIn(f"found {wrong}", errors[0])

    def test_missing_tool_fails(self):
        del self.versions["PySide6"]
        self.assertIn("PySide6==6.11.0 required; found not installed", self._check())

    def test_stale_installed_package_fails(self):
        stale = Path(r"C:\Python312\Lib\site-packages\mouse_click_stability_analyzer\__init__.py")
        errors = self._check(origin=stale)
        self.assertTrue(any("expected this repository" in e for e in errors))

    def test_unimportable_package_fails(self):
        self.assertTrue(any("not importable" in e for e in self._check(origin=None)))

    def test_wrong_mcsa_version_fails(self):
        self.versions["mouse-click-stability-analyzer"] = "0.9.0"
        self.assertTrue(any("mouse-click-stability-analyzer==1.0.0" in e for e in self._check()))

    def test_pins_match_requirements_and_pyproject(self):
        build = (self.ROOT / "requirements-build.txt").read_text(encoding="utf-8")
        gui = (self.ROOT / "requirements-gui.txt").read_text(encoding="utf-8")
        pyproject = (self.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("PyInstaller==6.13.0", build)
        self.assertIn("PySide6==6.11.0", gui)
        self.assertIn("openpyxl==3.1.5", gui)
        self.assertIn('version = "1.0.0"', pyproject)

    def _fake_root(self, tmp: str, *report_names: str) -> Path:
        root = Path(tmp)
        reports = root / "dist" / "MCSA-1.0.0-win64" / "reports"
        reports.mkdir(parents=True)
        (reports / ".gitkeep").write_text("", encoding="utf-8")
        for name in report_names:
            (reports / name).mkdir()
            (reports / name / f"{name}_evidence.json").write_text("{}", encoding="utf-8")
        return root

    def test_empty_reports_folder_allows_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_root(tmp)
            self.assertEqual(self.guard.existing_report_packages(root), [])
            with mock.patch.object(self.guard, "check_environment", return_value=[]):
                with mock.patch("sys.stdout", new_callable=io.StringIO):
                    self.assertEqual(self.guard.main([str(root)]), 0)

    def test_missing_dist_allows_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.guard.existing_report_packages(Path(tmp)), [])

    def test_existing_report_packages_abort_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._fake_root(tmp, "mcsa_20261012_141455", "mcsa_20261012_144925")
            before = sorted(p.relative_to(root) for p in root.rglob("*"))
            out = io.StringIO()
            with mock.patch.object(self.guard, "check_environment", return_value=[]):
                with mock.patch("sys.stdout", out):
                    rc = self.guard.main([str(root)])
            self.assertEqual(rc, 1)
            text = out.getvalue()
            self.assertIn("2 report package(s)", text)
            self.assertIn("mcsa_20261012_141455", text)
            self.assertIn("Back up or move them", text)
            self.assertIn("Nothing was deleted.", text)
            self.assertNotIn("BUILD ENVIRONMENT OK", text)
            self.assertEqual(sorted(p.relative_to(root) for p in root.rglob("*")), before)

    def test_report_guard_runs_before_dist_cleanup(self):
        bat = (self.ROOT / "build_exe.bat").read_text(encoding="utf-8")
        guard = bat.index("check_build_env.py")
        cleanup = bat.index('rd /s /q "%DISTDIR%"')
        self.assertLess(guard, cleanup)
        self.assertIn("exit /b 1", bat[guard:cleanup])

    def test_build_script_runs_guard_and_never_installs(self):
        bat = (self.ROOT / "build_exe.bat").read_text(encoding="utf-8")
        self.assertIn("check_build_env.py", bat)
        self.assertNotIn("pip install -r", bat.split("Verifying pinned build toolchain", 1)[1])

    def test_build_script_copies_license_directory(self):
        bat = (self.ROOT / "build_exe.bat").read_text(encoding="utf-8")
        self.assertIn(r'packaging\licenses', bat)
        self.assertIn(r'%DISTDIR%\licenses', bat)

    def test_release_zip_script_excludes_reports(self):
        bat = (self.ROOT / "packaging" / "make_release_zip.bat").read_text(encoding="utf-8")
        self.assertIn("Remove-Item (Join-Path $rel 'reports')", bat)
        self.assertIn("mcsa_startup.log", bat)


def _load_verify_bundle():
    path = Path(__file__).resolve().parents[1] / "packaging" / "verify_bundle.py"
    spec = importlib.util.spec_from_file_location("mcsa_verify_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BundleLicenseContractTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def setUp(self):
        self.verify = _load_verify_bundle()

    def test_repo_license_sources_exist(self):
        for name in self.verify.REQUIRED_LICENSE_FILES:
            path = self.ROOT / "packaging" / name
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 400, name)

    def test_notices_point_at_every_included_license_file(self):
        text = (self.ROOT / "packaging" / "THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        for name in self.verify.REQUIRED_LICENSE_FILES:
            self.assertIn(name.replace("/", "\\"), text)
        self.assertNotIn("OPEN:", text)
        self.assertIn("LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only", text)
        self.assertIn("https://code.qt.io/cgit/pyside/pyside-setup.git", text)
        self.assertIn("v6.11.0", text)
        python_text = (self.ROOT / "packaging" / "licenses" / "python_LICENSE.txt").read_text(encoding="utf-8")
        self.assertIn("Python Software Foundation", python_text)
        pi = (self.ROOT / "packaging" / "licenses" / "pyinstaller_COPYING.txt").read_text(encoding="utf-8")
        self.assertIn("Bootloader Exception", pi)
        self.assertIn("GNU GENERAL PUBLIC LICENSE", pi)

    def test_qt_gnu_license_texts_match_declared_alternatives(self):
        licenses = self.ROOT / "packaging" / "licenses"
        expected = {
            "qt_LGPL-3.0-only.txt": ("GNU LESSER GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007"),
            "qt_GPL-3.0-only.txt": ("GNU GENERAL PUBLIC LICENSE", "Version 3, 29 June 2007"),
            "qt_GPL-2.0-only.txt": ("GNU GENERAL PUBLIC LICENSE", "Version 2, June 1991"),
        }
        for name, markers in expected.items():
            text = (licenses / name).read_text(encoding="utf-8")
            for marker in markers:
                self.assertIn(marker, text, name)

    def _minimal_bundle(self, root: Path, *, licenses: bool) -> None:
        (root / "MCSA.exe").write_bytes(b"x")
        (root / "platforms").mkdir()
        (root / "platforms" / "qwindows.dll").write_bytes(b"x")
        for name in ("LICENSE", "QUICK_START.txt", "THIRD_PARTY_NOTICES.txt"):
            (root / name).write_text("ok", encoding="utf-8")
        for name in self.verify.REQUIRED_STRINGS:
            (root / name).write_text("{}", encoding="utf-8")
        for name in ("chart_fit.svg", "check_white.svg"):
            (root / name).write_text("<svg/>", encoding="utf-8")
        (root / "licenses").mkdir()
        if licenses:
            for name in self.verify.REQUIRED_LICENSE_FILES:
                (root / name).write_text("text", encoding="utf-8")

    def _run_verify(self, root: Path) -> tuple[int, str]:
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            rc = self.verify.main([str(root)])
        return rc, out.getvalue() + err.getvalue()

    def test_verify_bundle_fails_when_license_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._minimal_bundle(root, licenses=False)
            rc, output = self._run_verify(root)
            self.assertEqual(rc, 1)
            self.assertIn("missing licenses/python_LICENSE.txt", output)

    def test_verify_bundle_passes_with_full_license_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._minimal_bundle(root, licenses=True)
            rc, output = self._run_verify(root)
            self.assertEqual(rc, 0, output)
            self.assertIn("BUNDLE CHECK OK", output)

    def test_verify_bundle_fails_when_any_qt_gnu_text_missing(self):
        for name in ("licenses/qt_LGPL-3.0-only.txt", "licenses/qt_GPL-3.0-only.txt", "licenses/qt_GPL-2.0-only.txt"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self._minimal_bundle(root, licenses=True)
                (root / name).unlink()
                rc, output = self._run_verify(root)
                self.assertEqual(rc, 1)
                self.assertIn(f"missing {name}", output)


if __name__ == "__main__":
    unittest.main()
