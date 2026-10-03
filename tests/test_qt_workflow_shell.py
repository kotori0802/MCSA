"""Focused tests for Phase 2C-1 workflow shell and layout migration."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QLineEdit, QScrollArea, QSplitter, QStackedWidget

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer import app as legacy_app
from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app

_T0 = 1000.0
_NAV_KEYS = (
    "nav_setup",
    "nav_capture",
    "nav_results",
    "nav_preferences",
    "page_setup_subtitle",
    "page_capture_subtitle",
    "page_results_subtitle",
    "page_results_placeholder",
    "page_preferences_subtitle",
    "preferences_more_note",
    "setup_device_section",
    "setup_config_section",
)


def _under(widget, ancestor) -> bool:
    current = widget
    while current is not None:
        if current is ancestor:
            return True
        current = current.parentWidget()
    return False


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


class WorkflowShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        if cls._qapp is None:
            raise unittest.SkipTest("PySide6 QApplication unavailable")
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()
        self.win.ensure_raw_input = lambda: None
        self.win._cursor_in_test_area = lambda: True
        self.win.listening = True

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _setup_fixture(self, *, auto_sec: str | None = "0.1", tol: str = "2", hz: str = "40"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tol)
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _lock_and_arm(self):
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self.win._cursor_over_capture_exclusion_ui = lambda: False

    def _run(self, offsets, *, stop=True):
        self._lock_and_arm()
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        for off in offsets[1:]:
            press = t0 + off / 1000.0
            self.win.record_click("Left", press, press + 0.01, {})
        if stop:
            self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()

    def test_shell_exists(self):
        self.assertTrue(isinstance(self.win.page_stack, QStackedWidget))
        self.assertEqual(self.win.page_stack.count(), 4)
        self.assertEqual(self.win.nav_rail.objectName(), "NavRail")
        self.assertIs(self.win.page_stack.widget(0), self.win.page_setup)
        self.assertIs(self.win.page_stack.widget(1), self.win.page_capture)
        self.assertIs(self.win.page_stack.widget(2), self.win.page_results)
        self.assertIs(self.win.page_stack.widget(3), self.win.page_preferences)
        self.assertEqual(self.win.findChildren(QFrame, "SideCard"), [])

    def test_initial_page_is_setup(self):
        self.assertEqual(self.win._current_page, "setup")
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_setup)
        self.assertTrue(self.win.nav_setup.isChecked())
        self.assertFalse(self.win.nav_capture.isChecked())

    def test_navigation_changes_page_and_checked_state(self):
        mapping = (
            ("capture", self.win.nav_capture, self.win.page_capture),
            ("results", self.win.nav_results, self.win.page_results),
            ("preferences", self.win.nav_preferences, self.win.page_preferences),
            ("setup", self.win.nav_setup, self.win.page_setup),
        )
        for name, btn, page in mapping:
            btn.click()
            self.assertEqual(self.win._current_page, name)
            self.assertIs(self.win.page_stack.currentWidget(), page)
            self.assertTrue(btn.isChecked())
            for other in self.win._nav_buttons.values():
                if other is not btn:
                    self.assertFalse(other.isChecked())

    def test_no_duplicate_settings_widgets(self):
        hz_likes = [
            w for w in self.win.findChildren(QComboBox)
            if [w.itemText(i) for i in range(w.count())] == ["5", "10", "20", "40"]
        ]
        self.assertEqual(hz_likes, [self.win.hz_combo])
        self.assertEqual(self.win.findChildren(QLineEdit).count(self.win.timing_tol_edit), 1)
        self.assertEqual(self.win.findChildren(QLineEdit).count(self.win.device_edit), 1)
        for key, edit in self.win._limit_edits.items():
            with self.subTest(key=key):
                self.assertEqual(self.win.findChildren(QLineEdit).count(edit), 1)

    def test_setup_page_owns_settings_controls(self):
        owned = [
            self.win.device_edit,
            self.win.button_combo,
            self.win.hz_combo,
            self.win.timing_tol_edit,
            self.win.auto_stop_off,
            self.win.auto_stop_on,
            self.win.auto_stop_sec_combo,
            *self.win._limit_edits.values(),
        ]
        for widget in owned:
            self.assertTrue(_under(widget, self.win.page_setup), widget)
            self.assertTrue(_under(widget, self.win.setup_scroll), widget)

    def test_setup_page_scroll_area(self):
        self.assertIsInstance(self.win.setup_scroll, QScrollArea)
        self.assertTrue(self.win.setup_scroll.widgetResizable())
        self.assertEqual(
            self.win.setup_scroll.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertIsNotNone(self.win.setup_scroll.widget())

    def test_capture_page_owns_live_workspace(self):
        for widget in (
            self.win.test_area,
            self.win.scatter,
            self.win.interval_chart,
            self.win.review_text,
            self.win.btn_stop,
            self.win.btn_arm,
            self.win.val_verdict,
            self.win.status_label,
            self.win.btn_capture_new_run,
            self.win.btn_capture_goto_results,
            self.win.btn_capture_edit_setup,
        ):
            self.assertTrue(_under(widget, self.win.page_capture), widget)
        self.assertTrue(_under(self.win.btn_lock_profile, self.win.page_setup))
        self.assertTrue(_under(self.win.btn_new, self.win.page_results))
        self.assertTrue(_under(self.win.btn_generate_excel, self.win.page_results))
        self.assertTrue(_under(self.win.btn_generate_html, self.win.page_results))
        self.assertTrue(_under(self.win.btn_export, self.win.page_results))

    def test_help_is_on_nav_footer(self):
        self.assertTrue(_under(self.win.btn_help, self.win.nav_rail))
        self.assertFalse(_under(self.win.btn_help, self.win.page_capture))

    def test_theme_language_live_in_preferences(self):
        for combo in (self.win.theme_combo, self.win.lang_combo):
            self.assertTrue(_under(combo, self.win.page_preferences), combo)
            self.assertFalse(_under(combo, self.win.page_setup), combo)

    def test_action_buttons_single_connection(self):
        for btn in (self.win.btn_stop, self.win.btn_arm, self.win.btn_edit_profile):
            self.assertTrue(_under(btn, self.win.page_capture), btn)
        for btn in (
            self.win.btn_new, self.win.btn_generate_excel, self.win.btn_generate_html,
            self.win.btn_export, self.win.btn_overlay, self.win.btn_clear_overlay,
        ):
            self.assertTrue(_under(btn, self.win.page_results), btn)
        self.assertTrue(_under(self.win.btn_help, self.win.nav_rail))
        self.win.btn_stop.click()
        self.assertFalse(self.win.running)

    def test_setup_locking_survives_navigation(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._run([0, 25], stop=False)
        self.win.nav_setup.click()
        self.assertFalse(qt_app.setup_controls_editable(running=True, completed=False, profile_locked=True))
        for widget in (
            self.win.device_edit,
            self.win.hz_combo,
            self.win.timing_tol_edit,
            self.win.radio_manual,
            *self.win._limit_edits.values(),
        ):
            self.assertFalse(widget.isEnabled(), widget)
        self.win.stop_run()
        self.win.nav_setup.click()
        self.assertFalse(self.win.timing_tol_edit.isEnabled())

    def test_values_survive_page_switching(self):
        self._setup_fixture(hz="40", tol="2", auto_sec="10")
        self.win._limit_edits["chatter_threshold_ms"].setText("7")
        self.win.nav_capture.click()
        self.win.nav_results.click()
        self.win.nav_setup.click()
        self.assertTrue(self.win.radio_fixture.isChecked())
        self.assertEqual(self.win.hz_combo.currentText(), "40")
        self.assertEqual(self.win.timing_tol_edit.text(), "2")
        self.assertTrue(self.win.auto_stop_on.isChecked())
        self.assertEqual(self.win.auto_stop_sec_combo.currentText(), "10")
        self.assertEqual(self.win._limit_edits["chatter_threshold_ms"].text(), "7")

    def test_navigation_does_not_rebuild_host_evidence(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            snap = self.win.host_evidence_snapshot
            for _ in range(2):
                self.win.nav_setup.click()
                self.win.nav_capture.click()
                self.win.nav_results.click()
                self.win.nav_preferences.click()
            self.win.nav_capture.click()
        self.assertEqual(builder.call_count, 1)
        self.assertIs(self.win.host_evidence_snapshot, snap)

    def test_language_switch_retranslates_shell(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        snap = self.win.host_evidence_snapshot
        self.win.nav_setup.click()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
            self.assertEqual(self.win.nav_setup.text(), "設定")
            self.assertIn("擷取前", self.win.page_subtitle.text())
            self.assertEqual(self.win.hz_combo.currentText(), "40")
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("en"))
            self.assertEqual(self.win.nav_setup.text(), "Setup")
        self.assertEqual(builder.call_count, 0)
        self.assertIs(self.win.host_evidence_snapshot, snap)

    def test_theme_switch_keeps_widgets_and_values(self):
        self._setup_fixture(hz="40", tol="2")
        device = self.win.device_edit
        self.win.theme_combo.setCurrentIndex(1)
        self.assertIs(self.win.device_edit, device)
        self.assertEqual(self.win.hz_combo.currentText(), "40")
        self.assertEqual(self.win.timing_tol_edit.text(), "2")
        self.assertEqual(self.win.theme, "dark")

    def test_review_splitter(self):
        self.assertIsInstance(self.win.capture_splitter, QSplitter)
        self.assertEqual(self.win.capture_splitter.orientation(), Qt.Orientation.Vertical)
        self.assertFalse(self.win.review_text.isVisibleTo(self.win))
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.nav_capture.click()
        self.assertFalse(self.win.review_text.isVisibleTo(self.win))
        self.assertTrue(self.win.capture_completed_note.isVisibleTo(self.win))
        self.win.new_run()
        self.assertFalse(self.win.review_text.isVisibleTo(self.win))
        self.assertFalse(self.win.capture_completed_note.isVisibleTo(self.win))

    def test_host_evidence_remains_in_review(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        text = self.win.results_evidence_text.toPlainText()
        self.assertIn("HOST EVIDENCE", text)
        self.assertIn("Expected Slots", text)
        self.assertIn("Outside Capture Window", text)
        self.win.nav_capture.click()
        self.assertNotIn("HOST EVIDENCE", self.win.review_text.toPlainText())

    def test_new_run_clears_review_and_keeps_shell(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.new_run()
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertEqual(self.win.review_text.toPlainText(), "")
        self.assertEqual(self.win.results_observations_text.text(), "")
        self.assertEqual(self.win.page_stack.count(), 4)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_capture)
        self.win.nav_results.click()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self.assertTrue(self.win.results_empty_card.isVisibleTo(self.win))

    def test_manual_run_usable_without_host_evidence(self):
        self.win.radio_manual.setChecked(True)
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertNotIn("HOST EVIDENCE", self.win.results_evidence_text.toPlainText())
        self.assertTrue(self.win.completed)

    def test_fixture_auto_stop_off_usable_without_host_evidence(self):
        self._setup_fixture(auto_sec=None)
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertNotIn("Expected Slots", self.win.results_evidence_text.toPlainText())

    def test_no_shell_fields_in_session_or_reports(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.new_run()
        run = self.win.session_runs[-1]
        self.assertNotIn("workflow_page", run)
        self.assertNotIn("current_page", run.get("settings") or {})
        report_source = Path(legacy_app.__file__).read_text(encoding="utf-8")
        self.assertNotIn("WorkflowStack", report_source)
        self.assertNotIn("page_setup_subtitle", report_source)

    def test_i18n_keys_exist(self):
        for lang in SUPPORTED_LANGS:
            for key in _NAV_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(STRINGS[lang].get(key) or "").strip())

    def test_results_is_placeholder(self):
        self.win.nav_results.click()
        self.assertEqual(self.win.results_placeholder.text(), self.win._tr("results_empty"))
        self.assertTrue(self.win.results_empty_card.isVisibleTo(self.win))
        self.assertFalse(self.win.results_workspace.isVisibleTo(self.win))

    def test_minimum_size(self):
        self.assertEqual(self.win.minimumWidth(), 1024)
        self.assertEqual(self.win.minimumHeight(), 640)


if __name__ == "__main__":
    unittest.main()
