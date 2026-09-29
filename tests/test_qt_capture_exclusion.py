"""Phase 2C-1a: Raw Input clicks over application chrome must not become Fixture test events."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QPoint, QRect

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence
from mouse_click_stability_analyzer.qt_shell import app as qt_app

_T0 = 1000.0


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


class CaptureExclusionTests(unittest.TestCase):
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
        self.win.resize(1280, 840)
        self.win.show()
        self._qapp.processEvents()
        self.win.ui_timer.stop()
        self.win._listen_start_timer.stop()
        self.win.listening = True
        self._in_test_area = True
        self._cursor = QPoint(0, 0)
        self.win._cursor_in_test_area = lambda: self._in_test_area
        self.win._cursor_global_pos = lambda: self._cursor
        self._t = _T0 + 1.0

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()

    def _setup_fixture(self):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("2")
        self.win.auto_stop_off.setChecked(True)

    def _start_run(self):
        self._in_test_area = True
        self.win.listening = True
        self.win.completed = False
        self.win._begin_session_from_first_click("Left", _T0, _T0 + 0.01, {})
        self.assertTrue(self.win.running)
        self._qapp.processEvents()

    def _point_at(self, widget):
        self._qapp.processEvents()
        self.assertTrue(widget.isVisibleTo(self.win), widget)
        self._cursor = widget.mapToGlobal(widget.rect().center())

    def _raw_click(self, button="Left"):
        base = {"capture_source": "windows_raw_input", "button": button, "device_source": "dut"}
        self.win._on_raw_event_ui({**base, "event_type": "down", "time_perf": self._t})
        self.win._on_raw_event_ui({**base, "event_type": "up", "time_perf": self._t + 0.01})
        self._t += 0.025

    def _assert_click_excluded(self, widget):
        self._point_at(widget)
        self._in_test_area = False
        self.assertTrue(self.win._cursor_over_capture_exclusion_ui(), widget)
        before = len(self.win.events)
        self._raw_click()
        self.assertEqual(len(self.win.events), before, widget)

    def test_fixture_click_over_capture_actions_is_excluded(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._start_run()
        for widget in (
            self.win.btn_new, self.win.btn_finish, self.win.btn_save,
            self.win.btn_overlay, self.win.btn_clear_overlay,
        ):
            with self.subTest(widget=widget.text()):
                self._assert_click_excluded(widget)

    def test_fixture_click_over_stop_is_excluded(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._start_run()
        self.assertTrue(self.win.btn_stop.isEnabled())
        self._assert_click_excluded(self.win.btn_stop)
        self.assertEqual(len(self.win.events), 1)
        self.assertTrue(self.win.running)

    def test_fixture_click_outside_test_area_not_over_ui_still_records(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._start_run()
        self._point_at(self.win.status_label)
        self._in_test_area = False
        self.assertFalse(self.win._cursor_over_capture_exclusion_ui())
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    def test_fixture_click_on_setup_page_background_still_records(self):
        self._setup_fixture()
        self._start_run()
        self.win.nav_setup.click()
        self._point_at(self.win.lbl_setup)
        self._in_test_area = False
        self.assertFalse(self.win._cursor_over_capture_exclusion_ui())
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    def test_nav_rail_is_excluded(self):
        self._setup_fixture()
        self._start_run()
        for widget in (self.win.nav_setup, self.win.nav_results, self.win.btn_help, self.win.title_label):
            with self.subTest(widget=widget.text()):
                self._assert_click_excluded(widget)

    def test_global_theme_language_are_excluded(self):
        self._setup_fixture()
        self._start_run()
        self.assertTrue(self.win.theme_combo.isEnabled())
        self.assertTrue(self.win.lang_combo.isEnabled())
        self._assert_click_excluded(self.win.theme_combo)
        self._assert_click_excluded(self.win.lang_combo)

    def test_visible_setup_controls_are_excluded_during_run(self):
        self._setup_fixture()
        self.win.auto_stop_on.setChecked(True)
        self.win.auto_stop_sec_combo.setCurrentText("60")
        self._start_run()
        self.win.nav_setup.click()
        for widget in (
            self.win.device_edit, self.win.button_combo, self.win.radio_manual,
            self.win.radio_fixture, self.win.hz_combo, self.win.timing_tol_edit,
            self.win.auto_stop_off, self.win.auto_stop_on, self.win.auto_stop_sec_combo,
        ):
            with self.subTest(widget=type(widget).__name__):
                self.win.setup_scroll.ensureWidgetVisible(widget)
                self._assert_click_excluded(widget)
        for key, edit in self.win._limit_edits.items():
            with self.subTest(limit=key):
                self.win.setup_scroll.ensureWidgetVisible(edit)
                self._assert_click_excluded(edit)

    def test_hidden_page_controls_do_not_exclude(self):
        self._setup_fixture()
        self.win.nav_setup.click()
        self._start_run()
        self.assertFalse(self.win.btn_stop.isVisibleTo(self.win))
        self._cursor = self.win.btn_stop.mapToGlobal(self.win.btn_stop.rect().center())
        self._in_test_area = False
        self.assertFalse(self.win.capture_actions.isVisibleTo(self.win))

    def test_manual_requires_test_area_unchanged(self):
        self.win.radio_manual.setChecked(True)
        self.win.nav_capture.click()
        self._start_run()
        self._point_at(self.win.status_label)
        self._in_test_area = False
        self._raw_click()
        self.assertEqual(len(self.win.events), 1)
        self._in_test_area = True
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    def test_non_target_button_still_ignored(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._start_run()
        self._point_at(self.win.status_label)
        self._in_test_area = False
        self._raw_click(button="Right")
        self.assertEqual(len(self.win.events), 1)

    def test_host_evidence_uses_only_accepted_events(self):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("2")
        self.win.auto_stop_on.setChecked(True)
        self.win.auto_stop_sec_combo.setCurrentText("10")
        self.win.nav_capture.click()
        self._start_run()
        self._point_at(self.win.btn_stop)
        self._in_test_area = False
        self._raw_click()
        self._point_at(self.win.status_label)
        self._raw_click()
        accepted = [dict(e) for e in self.win.events]
        self.assertEqual(len(accepted), 2)
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self.win.stop_run()
        self.assertEqual(builder.call_count, 1)
        observed = list(builder.call_args.args[3])
        self.assertEqual(observed, [e["press_elapsed_ms"] for e in accepted])
        self.assertIsNotNone(self.win.host_evidence_snapshot)


class HiddenTestAreaGeometryTests(unittest.TestCase):
    """Step 1a: the real Test Area hit-test must ignore stale geometry on hidden stacked pages."""

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
        self.win.resize(1280, 840)
        self.win.show()
        self._qapp.processEvents()
        self.win.ui_timer.stop()
        self.win._listen_start_timer.stop()
        self.win.listening = True
        self.win.completed = False
        self.win._ignore_arm_until = 0.0
        self._cursor = QPoint(0, 0)
        self.win._cursor_global_pos = lambda: self._cursor
        self._t = _T0

        self._show("capture")
        area = self.win.test_area
        self.area_rect = QRect(area.mapToGlobal(QPoint(0, 0)), area.size())
        self.area_center = area.mapToGlobal(area.rect().center())

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()

    def _show(self, page):
        self.win._show_workflow_page(page)
        self._qapp.processEvents()

    def _raw_click(self, button="Left"):
        base = {"capture_source": "windows_raw_input", "button": button, "device_source": "dut"}
        self.win._on_raw_event_ui({**base, "event_type": "down", "time_perf": self._t})
        self.win._on_raw_event_ui({**base, "event_type": "up", "time_perf": self._t + 0.01})
        self._t += 0.025

    def _setup_fixture(self, *, auto_sec=None):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("2")
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _start_run_via_real_test_area(self):
        self._show("capture")
        self._cursor = self.area_center
        self.assertTrue(self.win._cursor_in_test_area())
        self._raw_click()
        self.assertTrue(self.win.running)
        self.assertEqual(len(self.win.events), 1)

    def _setup_control_overlapping_hidden_area(self):
        self._show("setup")
        self.assertFalse(self.win.test_area.isVisibleTo(self.win))
        candidates = [
            self.win.device_edit, self.win.button_combo, self.win.radio_manual,
            self.win.radio_fixture, self.win.hz_combo, self.win.timing_tol_edit,
            self.win.auto_stop_off, self.win.auto_stop_on, *self.win._limit_edits.values(),
        ]
        for widget in candidates:
            if not widget.isVisibleTo(self.win):
                continue
            rect = QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())
            overlap = rect.intersected(self.area_rect)
            if overlap.width() > 2 and overlap.height() > 2:
                return widget, overlap.center()
        self.fail("no visible Setup control overlaps the hidden Test Area geometry")

    def test_setup_page_stale_geometry_is_not_test_area(self):
        self._show("setup")
        self._cursor = self.area_center
        self.assertTrue(self.area_rect.contains(self._cursor))
        self.assertFalse(self.win._cursor_in_test_area())

    def test_results_and_preferences_stale_geometry_is_not_test_area(self):
        for page in ("results", "preferences"):
            with self.subTest(page=page):
                self._show(page)
                self._cursor = self.area_center
                self.assertFalse(self.win._cursor_in_test_area())

    def test_listen_click_on_setup_at_stale_geometry_does_not_start_run(self):
        self._setup_fixture()
        self._show("setup")
        self._cursor = self.area_center
        self._raw_click()
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.start_time)
        self.assertIsNone(self.win.first_press_time)
        self.assertEqual(self.win.events, [])
        self.assertFalse(self.win._arming_scheduled)

    def test_listen_click_on_results_at_stale_geometry_does_not_start_run(self):
        self.win.radio_manual.setChecked(True)
        self._show("results")
        self._cursor = self.area_center
        self._raw_click()
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])

    def test_listen_click_in_visible_test_area_still_starts_run(self):
        self._setup_fixture()
        self._start_run_via_real_test_area()
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)

    def test_manual_click_on_other_page_at_stale_geometry_is_rejected(self):
        self.win.radio_manual.setChecked(True)
        self._start_run_via_real_test_area()
        for page in ("setup", "results", "preferences"):
            with self.subTest(page=page):
                self._show(page)
                self._cursor = self.area_center
                self._raw_click()
                self.assertEqual(len(self.win.events), 1)
        self._show("capture")
        self._cursor = self.area_center
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    def test_fixture_setup_control_over_stale_geometry_is_excluded(self):
        self._setup_fixture()
        self._start_run_via_real_test_area()
        widget, point = self._setup_control_overlapping_hidden_area()
        self._cursor = point
        self.assertFalse(self.win._cursor_in_test_area(), widget)
        self.assertTrue(self.win._cursor_over_capture_exclusion_ui(), widget)
        self._raw_click()
        self.assertEqual(len(self.win.events), 1)

    def test_fixture_non_control_location_on_other_page_still_records(self):
        self._setup_fixture()
        self._start_run_via_real_test_area()
        self._show("results")
        self._cursor = self.area_center
        self.assertFalse(self.win._cursor_over_capture_exclusion_ui())
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    def test_non_target_button_ignored_in_visible_test_area(self):
        self._setup_fixture()
        self._start_run_via_real_test_area()
        self._raw_click(button="Right")
        self.assertEqual(len(self.win.events), 1)

    def _break_hit_test(self):
        def _raise(*_args, **_kwargs):
            raise RuntimeError("forced hit-test failure")
        self.win.test_area.mapFromGlobal = _raise

    def test_hit_test_failure_fails_closed(self):
        self._show("capture")
        self._cursor = self.area_center
        self.assertTrue(self.win._test_area_is_active())
        self.assertTrue(self.win._cursor_in_test_area())
        self._break_hit_test()
        with self.assertLogs(qt_app._log, level="WARNING"):
            self.assertFalse(self.win._cursor_in_test_area())

    def test_cursor_position_failure_fails_closed(self):
        self._show("capture")
        def _raise():
            raise RuntimeError("forced cursor failure")
        self.win._cursor_global_pos = _raise
        with self.assertLogs(qt_app._log, level="WARNING"):
            self.assertFalse(self.win._cursor_in_test_area())

    def test_listen_click_under_hit_test_failure_does_not_start_run(self):
        self._setup_fixture()
        self._show("capture")
        self._cursor = self.area_center
        self._break_hit_test()
        with self.assertLogs(qt_app._log, level="WARNING"):
            self._raw_click()
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.start_time)
        self.assertIsNone(self.win.first_press_time)
        self.assertEqual(self.win.events, [])
        self.assertFalse(self.win._arming_scheduled)

    def test_host_evidence_receives_only_accepted_events(self):
        self._setup_fixture(auto_sec="10")
        self._start_run_via_real_test_area()
        _widget, point = self._setup_control_overlapping_hidden_area()
        self._cursor = point
        self._raw_click()
        self._show("results")
        self._cursor = self.area_center
        self._raw_click()
        accepted = [e["press_elapsed_ms"] for e in self.win.events]
        self.assertEqual(len(accepted), 2)
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self.win.stop_run()
        self.assertEqual(builder.call_count, 1)
        self.assertEqual(list(builder.call_args.args[3]), accepted)


if __name__ == "__main__":
    unittest.main()
