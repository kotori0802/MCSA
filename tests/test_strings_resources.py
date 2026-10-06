"""Stage 1: engineer-editable copy resources."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
_REPO = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.i18n import LANG_LABELS, STRINGS, SUPPORTED_LANGS, normalize_lang, t
from mouse_click_stability_analyzer.report_v2 import click_data_columns, xlsx_kv_cell_value
from mouse_click_stability_analyzer.strings.check import main as strings_check_main
from mouse_click_stability_analyzer.strings.check import validate_resources
from mouse_click_stability_analyzer.strings.loader import (
    ALL_RESOURCE_FILES,
    DuplicateJsonKeyError,
    REPORT_STRINGS,
    parse_resource_json,
    reload_string_tables,
    report_text,
    resolve_strings_root,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _prod_root() -> Path:
    return Path(str(resolve_strings_root()))


def _copy_prod(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    src = _prod_root()
    for name in ALL_RESOURCE_FILES:
        shutil.copy2(src / name, dest / name)


class LoaderTests(unittest.TestCase):
    def test_loads_en_and_zh_tables(self):
        self.assertEqual(set(STRINGS), {"en", "zh"})
        self.assertGreaterEqual(len(STRINGS["en"]), 326)
        self.assertEqual(set(STRINGS["en"]), set(STRINGS["zh"]))
        self.assertEqual(STRINGS["en"]["nav_setup"], "Setup")
        self.assertEqual(STRINGS["zh"]["nav_setup"], "設定")
        self.assertEqual(STRINGS["en"]["col_state"], "Timing observation")
        self.assertEqual(STRINGS["en"]["legend_host_observation"], "Host observation")
        self.assertEqual(STRINGS["en"]["legend_configured_reference"], "Configured reference")

    def test_utf8_sig_bom(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "setup.json").read_text(encoding="utf-8"))
            payload["page_setup_subtitle"]["en"] = "BOM Setup subtitle"
            bom = b"\xef\xbb\xbf" + json.dumps(payload, ensure_ascii=False).encode("utf-8")
            (dest / "setup.json").write_bytes(bom)
            reload_string_tables(dest)
            try:
                self.assertEqual(t("en", "page_setup_subtitle"), "BOM Setup subtitle")
            finally:
                reload_string_tables()

    def test_independent_of_cwd(self):
        with tempfile.TemporaryDirectory() as raw:
            prev = Path.cwd()
            os.chdir(raw)
            try:
                reload_string_tables()
                self.assertEqual(t("en", "nav_capture"), "Capture")
            finally:
                os.chdir(prev)

    def test_spaces_and_non_ascii_path(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "MCSA Tools" / "測試工具" / "strings"
            _copy_prod(dest)
            reload_string_tables(dest)
            try:
                self.assertEqual(t("en", "app_title"), "Mouse Click Stability Analyzer")
                self.assertEqual(report_text("report_title"), "MCSA — Test Report")
            finally:
                reload_string_tables()


class ValidationTests(unittest.TestCase):
    def _issues(self, dest: Path) -> str:
        return "\n".join(str(i) for i in validate_resources(dest))

    def test_duplicate_json_key(self):
        with self.assertRaises(DuplicateJsonKeyError) as ctx:
            parse_resource_json('{"a": 1, "a": 2}', path="dup.json")
        self.assertEqual(ctx.exception.key, "a")
        self.assertEqual(ctx.exception.path, "dup.json")

    def test_duplicate_cross_file_key(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            extra = json.loads((dest / "common.json").read_text(encoding="utf-8"))
            extra["page_setup_subtitle"] = {"en": "x", "zh-TW": "y"}
            (dest / "common.json").write_text(json.dumps(extra, ensure_ascii=False), encoding="utf-8")
            text = self._issues(dest)
            self.assertIn("Duplicate key 'page_setup_subtitle'", text)

    def test_missing_language_and_blank(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "setup.json").read_text(encoding="utf-8"))
            payload["manual"] = {"en": "Manual"}
            payload["fixture"] = {"en": "  ", "zh-TW": "治具"}
            (dest / "setup.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            text = self._issues(dest)
            self.assertIn("missing required zh-TW", text)
            self.assertIn("missing required English", text)

    def test_bad_placeholder_and_mismatch(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "setup.json").read_text(encoding="utf-8"))
            payload["reference_interval_derived"] = {
                "en": "{0} ms",
                "zh-TW": "{ms} ms",
                "placeholders": ["ms"],
            }
            (dest / "setup.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            text = self._issues(dest)
            self.assertIn("malformed placeholder", text)

    def test_unknown_language_typo_and_malformed_json(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "common.json").read_text(encoding="utf-8"))
            payload["cancel"] = {"en": "Cancel", "zh_TW": "取消"}
            (dest / "common.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            text = self._issues(dest)
            self.assertIn("zh-TW", text)
            (dest / "results.json").write_text("{not json", encoding="utf-8")
            text = self._issues(dest)
            self.assertIn("Malformed JSON", text)

    def test_ampersand_and_unreferenced_warning(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "common.json").read_text(encoding="utf-8"))
            payload["edit_setup_new_run"]["en"] = "Edit Setup && New Run"
            payload["totally_unused_copy_key"] = {"en": "Unused", "zh-TW": "未用"}
            (dest / "common.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            issues = validate_resources(dest)
            levels = {(i.level, i.message) for i in issues}
            self.assertTrue(any(i.level == "error" and "&&" in i.message for i in issues))
            self.assertTrue(any(i.level == "warning" and "totally_unused_copy_key" in i.message for i in issues))

    def test_production_resources_have_no_errors(self):
        issues = validate_resources()
        errors = [i.message for i in issues if i.level == "error"]
        self.assertEqual(errors, [])


class EngineerEditableProofTests(unittest.TestCase):
    def test_setup_label_follows_resource_not_python(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "setup.json").read_text(encoding="utf-8"))
            payload["page_setup_subtitle"]["en"] = "Edited setup subtitle from JSON"
            (dest / "setup.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            reload_string_tables(dest)
            try:
                self.assertEqual(t("en", "page_setup_subtitle"), "Edited setup subtitle from JSON")
            finally:
                reload_string_tables()
        self.assertEqual(t("en", "page_setup_subtitle"), "Configure the test before capture.")

    def test_report_label_change_does_not_change_xlsx_typing(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "report.json").read_text(encoding="utf-8"))
            payload["report_label_run_id"]["en"] = "Run Identifier"
            (dest / "report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            reload_string_tables(dest)
            try:
                self.assertEqual(report_text("report_label_run_id"), "Run Identifier")
                self.assertEqual(xlsx_kv_cell_value("run_id", "123"), "123")
                self.assertEqual(click_data_columns(False)[0], "#")
            finally:
                reload_string_tables()
        self.assertEqual(report_text("report_label_run_id"), "Run ID")


class CloseoutCopyTests(unittest.TestCase):
    def test_wrong_button_alerts_come_from_capture_json(self):
        self.assertEqual(t("en", "wrong_button_alert", button="Right"), "Wrong button: Right")
        self.assertEqual(
            t("en", "wrong_button_expected_alert", button="Right", target="Left"),
            "Wrong button: got Right, expected Left",
        )
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "capture.json").read_text(encoding="utf-8"))
            payload["wrong_button_expected_alert"]["en"] = "Pressed {button}; locked to {target}"
            (dest / "capture.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            reload_string_tables(dest)
            try:
                self.assertEqual(
                    t("en", "wrong_button_expected_alert", button="Right", target="Left"),
                    "Pressed Right; locked to Left",
                )
            finally:
                reload_string_tables()

    def test_report_no_data_comes_from_report_json(self):
        from mouse_click_stability_analyzer import report_v2

        self.assertIn(">No data<", report_v2._empty_chart("x"))
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            _copy_prod(dest)
            payload = json.loads((dest / "report.json").read_text(encoding="utf-8"))
            payload["report_chart_no_data"]["en"] = "Nothing recorded"
            (dest / "report.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            reload_string_tables(dest)
            try:
                self.assertIn(">Nothing recorded<", report_v2._empty_chart("x"))
            finally:
                reload_string_tables()


class RuntimeLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except Exception:
            raise unittest.SkipTest("PySide6 unavailable")
        cls._qapp = QApplication.instance() or QApplication([])
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_en_zh_en_retranslates_without_restart(self):
        from mouse_click_stability_analyzer.qt_shell import app as qt_app

        win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        win._listen_start_timer.stop()
        win.ui_timer.stop()
        win.ensure_raw_input = lambda: None
        try:
            self.assertEqual(win.nav_setup.text(), "Setup")
            zh = win.lang_combo.findData("zh")
            win.lang_combo.setCurrentIndex(zh)
            self.assertEqual(win.lang, "zh")
            self.assertEqual(win.nav_setup.text(), "設定")
            self.assertEqual(win.auto_stop_off.text(), "OFF")
            en = win.lang_combo.findData("en")
            win.lang_combo.setCurrentIndex(en)
            self.assertEqual(win.nav_setup.text(), "Setup")
            self.assertEqual(win.results_click_table.horizontalHeaderItem(5).text(), "Timing observation")
        finally:
            win.close()
            win.deleteLater()


class PackageAndWrapperTests(unittest.TestCase):
    def test_package_resources_include_json_and_readme(self):
        from importlib.resources import files

        root = files("mouse_click_stability_analyzer.resources").joinpath("strings")
        names = {item.name for item in root.iterdir()}
        expected = set(ALL_RESOURCE_FILES) | {"README.md"}
        self.assertTrue(expected.issubset(names), names)

    def test_wheel_contains_string_resources(self):
        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw)
            proc = __import__("subprocess").run(
                [sys.executable, "-m", "pip", "wheel", str(_REPO), "-w", str(dest), "--no-deps"],
                capture_output=True,
                text=True,
                cwd=str(_REPO),
            )
            if proc.returncode != 0:
                self.skipTest("pip wheel unavailable: " + (proc.stderr or proc.stdout)[:300])
            wheels = list(dest.glob("*.whl"))
            self.assertTrue(wheels)
            with zipfile.ZipFile(wheels[0]) as zf:
                names = zf.namelist()
            prefix = "mouse_click_stability_analyzer/resources/strings/"
            for name in ALL_RESOURCE_FILES:
                self.assertIn(prefix + name, names)
            self.assertIn(prefix + "README.md", names)

    def test_wrapper_paths(self):
        open_bat = _REPO / "open_strings.bat"
        check_bat = _REPO / "check_strings.bat"
        self.assertTrue(open_bat.is_file())
        text = open_bat.read_text(encoding="utf-8")
        self.assertIn("%~dp0", text)
        self.assertIn("resources\\strings", text)
        self.assertEqual(strings_check_main([]), 0)


if __name__ == "__main__":
    unittest.main()
