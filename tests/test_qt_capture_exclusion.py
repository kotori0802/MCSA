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

    def _lock_and_arm(self):
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._t = float(self.win._arm_boundary_perf) + 0.001

    def _start_run(self):
        self._in_test_area = True
        self._lock_and_arm()
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        self._qapp.processEvents()
        self.win._cursor_over_capture_exclusion_ui = lambda: qt_app.MainWindow._cursor_over_capture_exclusion_ui(self.win)

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
            self.win.btn_arm, self.win.btn_edit_profile,
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

    def test_fixture_click_over_visualization_controls_is_excluded(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._start_run()
        for widget in (
            self.win.btn_view_stability, self.win.btn_view_interval,
            self.win.btn_chart_fit, self.win.btn_chart_zoom_in,
            self.win.btn_chart_zoom_out, self.win.btn_chart_reset,
            self.win.capture_viz_toolbar,
        ):
            with self.subTest(widget=widget.objectName() or widget.text()):
                self._assert_click_excluded(widget)
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

    def test_visible_preferences_theme_language_are_excluded(self):
        self._setup_fixture()
        self._start_run()
        self.win.nav_preferences.click()
        self._qapp.processEvents()
        for combo in (self.win.theme_combo, self.win.lang_combo):
            with self.subTest(combo=combo):
                self.assertTrue(combo.isVisibleTo(self.win))
                self.assertTrue(combo.isEnabled())
                self._assert_click_excluded(combo)
        for widget in (
            self.win.startup_window_combo,
            self.win.remember_window_size_checkbox,
            self.win.reset_window_geometry_button,
        ):
            with self.subTest(widget=widget.objectName() or widget.__class__.__name__):
                self.assertTrue(widget.isVisibleTo(self.win))
                self.assertTrue(widget.isEnabled())
                self._assert_click_excluded(widget)
        self.assertEqual(len(self.win.events), 1)
        self.assertTrue(self.win.running)

    def _stale_background_point(self, widgets):
        """A point inside hidden widgets' stale geometry not covered by any visible exclusion widget."""
        visible = [w for w in self.win._capture_exclusion_widgets() if w.isVisibleTo(self.win)]
        for widget in widgets:
            rect = widget.rect()
            for fx in (0.2, 0.5, 0.8):
                for fy in (0.25, 0.5, 0.75):
                    local = QPoint(int(rect.width() * fx), int(rect.height() * fy))
                    point = widget.mapToGlobal(local)
                    if not any(w.rect().contains(w.mapFromGlobal(point)) for w in visible):
                        return widget, point
        return None, None

    def test_hidden_preferences_theme_language_do_not_exclude_on_capture(self):
        self._setup_fixture()
        self.win.nav_preferences.click()
        self._qapp.processEvents()
        self.win.nav_capture.click()
        self._start_run()
        self._qapp.processEvents()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_capture)
        combos = (
            self.win.theme_combo,
            self.win.lang_combo,
            self.win.startup_window_combo,
            self.win.remember_window_size_checkbox,
            self.win.reset_window_geometry_button,
        )
        for combo in combos:
            self.assertFalse(combo.isVisibleTo(self.win))
        widget, point = self._stale_background_point(combos)
        self.assertIsNotNone(point, "no stale Theme/Language point lies on Capture background")
        self._cursor = point
        self._in_test_area = False
        self.assertFalse(self.win._cursor_over_capture_exclusion_ui(), widget)
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    def _reveal_custom_controls(self):
        self.win.nav_preferences.click()
        self._qapp.processEvents()
        self.win.startup_window_combo.setCurrentIndex(qt_app.WINDOW_MODES.index("custom"))
        self._qapp.processEvents()

    def _custom_controls(self):
        return (self.win.custom_width_spin, self.win.custom_height_spin, self.win.apply_custom_size_button)

    def test_visible_custom_size_controls_are_excluded(self):
        self._setup_fixture()
        self._start_run()
        self._reveal_custom_controls()
        for widget in self._custom_controls():
            with self.subTest(widget=widget.__class__.__name__):
                self.assertTrue(widget.isVisibleTo(self.win))
                self.assertTrue(widget.isEnabled())
                self._assert_click_excluded(widget)
        self.assertEqual(len(self.win.events), 1)
        self.assertTrue(self.win.running)

    def test_hidden_custom_controls_on_preferences_do_not_exclude(self):
        self._setup_fixture()
        self._start_run()
        self._reveal_custom_controls()
        self._qapp.processEvents()
        combo = self.win.startup_window_combo
        combo.blockSignals(True)
        try:
            combo.setCurrentIndex(qt_app.WINDOW_MODES.index("auto"))
        finally:
            combo.blockSignals(False)
        self.win._sync_custom_window_panel()
        self._qapp.processEvents()
        for widget in self._custom_controls():
            self.assertFalse(widget.isVisibleTo(self.win))
        widget, point = self._stale_background_point(self._custom_controls())
        self.assertIsNotNone(point, "no stale Custom-control point lies on uncovered Preferences background")
        self._cursor = point
        self._in_test_area = False
        self.assertFalse(self.win._cursor_over_capture_exclusion_ui(), widget)
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    def test_custom_controls_on_hidden_preferences_do_not_exclude_on_capture(self):
        self._setup_fixture()
        self._reveal_custom_controls()
        self.win.nav_capture.click()
        self._start_run()
        self._qapp.processEvents()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_capture)
        for widget in self._custom_controls():
            self.assertFalse(widget.isVisibleTo(self.win))
        widget, point = self._stale_background_point(self._custom_controls())
        self.assertIsNotNone(point, "no stale Custom-control point lies on Capture background")
        self._cursor = point
        self._in_test_area = False
        self.assertFalse(self.win._cursor_over_capture_exclusion_ui(), widget)
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

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
        self.win.setup_scroll.ensureWidgetVisible(self.win.setup_screening_card)
        self._assert_click_excluded(self.win.setup_screening_card)

    def test_hidden_page_controls_do_not_exclude(self):
        self._setup_fixture()
        self._start_run()
        self.win.nav_setup.click()
        self._qapp.processEvents()
        self.assertFalse(self.win.btn_stop.isVisibleTo(self.win))
        self.assertFalse(self.win.capture_actions.isVisibleTo(self.win))
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

    def _break_cursor_position(self):
        def _raise():
            raise RuntimeError("forced cursor failure")
        self.win._cursor_global_pos = _raise

    def _break_exclusion_map(self):
        def _raise(*_args, **_kwargs):
            raise RuntimeError("forced mapFromGlobal failure")
        self.win.nav_rail.mapFromGlobal = _raise

    def test_exclusion_cursor_position_failure_fails_closed(self):
        self._setup_fixture()
        self._break_cursor_position()
        with self.assertLogs(qt_app._log, level="WARNING"):
            self.assertTrue(self.win._cursor_over_capture_exclusion_ui())

    def test_exclusion_map_from_global_failure_fails_closed(self):
        self._setup_fixture()
        self.assertTrue(self.win.nav_rail.isVisibleTo(self.win))
        self._break_exclusion_map()
        with self.assertLogs(qt_app._log, level="WARNING"):
            self.assertTrue(self.win._cursor_over_capture_exclusion_ui())

    def test_fixture_running_event_under_exclusion_failure_not_recorded(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._start_run()
        self._in_test_area = False
        self._break_exclusion_map()
        with self.assertLogs(qt_app._log, level="WARNING"):
            self._raw_click()
        self.assertEqual(len(self.win.events), 1)
        self.assertTrue(self.win.running)

    def test_fixture_armed_first_event_under_exclusion_failure_does_not_start(self):
        self._setup_fixture()
        self.win.nav_capture.click()
        self._lock_and_arm()
        self._in_test_area = False
        self._break_cursor_position()
        with self.assertLogs(qt_app._log, level="WARNING"):
            self._raw_click()
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.start_time)
        self.assertEqual(self.win.events, [])
        self.assertTrue(self.win.capture_armed)
        self.assertFalse(self.win._arming_scheduled)

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

    def test_capture_scrollbar_is_excluded_when_overflowing(self):
        self._setup_fixture()
        # 1280x720 now fits without scrolling; the 1024x640 minimum still overflows.
        self.win.resize(1024, 640)
        self.win._show_workflow_page("capture")
        self._start_run()
        self._qapp.processEvents()
        bar = self.win.capture_scroll.verticalScrollBar()
        self.assertIn(bar, self.win._capture_exclusion_widgets())
        if bar.maximum() <= 0:
            self.skipTest("Capture page did not overflow vertically at 1024x640")
        self._assert_click_excluded(bar)
        self.assertTrue(self.win.running)


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

    def _lock_and_arm(self):
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._t = float(self.win._arm_boundary_perf) + 0.001

    def _start_run_via_real_test_area(self):
        self._lock_and_arm()
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
            self.win.auto_stop_off, self.win.auto_stop_on, self.win.setup_screening_card,
            self.win.btn_lock_profile, self.win.setup_profile_card,
            self.win.setup_device_card, self.win.setup_config_card, self.win.setup_limits_card,
        ]
        for widget in candidates:
            if not widget.isVisibleTo(self.win):
                continue
            self.win.setup_scroll.ensureWidgetVisible(widget)
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
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._t = float(self.win._arm_boundary_perf) + 0.001
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
