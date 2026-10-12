"""Phase Step 2: Profile Lock + Capture Arm state machine."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QPoint

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from association_support import apply_explicit_association
from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app

_T0 = 1000.0
_I18N_KEYS = (
    "lock_profile_continue", "edit_profile", "arm_capture", "disarm_capture",
    "new_run",
    "profile_status_draft", "profile_status_locked",
    "status_draft", "status_ready", "status_armed",
    "status_ready_manual", "status_ready_fixture",
    "status_armed_manual", "status_armed_fixture",
    "phase_draft", "phase_ready", "phase_armed",
    "test_area_hint_draft", "test_area_hint_ready", "test_area_hint_armed",
    "test_area_hint_ready_manual", "test_area_hint_ready_fixture",
    "test_area_hint_armed_manual", "test_area_hint_armed_fixture",
)


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


class ProfileLockArmTests(unittest.TestCase):
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
        self._in_test_area = True
        self._cursor = QPoint(0, 0)
        self.win._cursor_in_test_area = lambda: self._in_test_area
        self.win._cursor_global_pos = lambda: self._cursor
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self._t = _T0 + 1.0

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _raw(self, etype, button="Left", t=None):
        if t is None:
            t = self._t
            self._t += 0.01
        self.win._on_raw_event_ui({
            "capture_source": "windows_raw_input",
            "button": button,
            "event_type": etype,
            "device_source": "dut",
            "time_perf": t,
        })

    def _click(self, button="Left"):
        self._raw("down", button)
        self._raw("up", button)

    def _fixture(self, *, hz="5", tol="2", auto_sec="10"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tol)
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _arm_now(self):
        self.assertTrue(self.win.arm_capture())
        self._t = float(self.win._arm_boundary_perf) + 0.001

    def test_initial_state_is_draft(self):
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertFalse(self.win.capture_armed)
        self.assertFalse(self.win.running)
        self.assertFalse(self.win.completed)
        self.assertEqual(self.win._lifecycle_state(), "draft")
        self.assertTrue(self.win.device_edit.isEnabled())

    def test_navigation_does_not_lock_or_start(self):
        self.win.nav_capture.click()
        self.assertEqual(self.win._lifecycle_state(), "draft")
        self._in_test_area = True
        self._click()
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.start_time)
        self.assertEqual(self.win.events, [])

    def test_draft_raw_click_does_not_establish_t0(self):
        self._fixture()
        self._click()
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.first_press_time)
        self.assertEqual(list(self.win.device_press_queues.values()), [])

    def test_valid_manual_profile_locks(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertTrue(self.win.profile_locked_settings["manual_mode"])
        self.assertFalse(self.win.capture_armed)
        self.assertFalse(self.win.running)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_capture)

    def test_valid_fixture_profile_locks(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        self.assertEqual(snap["fixture_reference_hz"], 5.0)
        self.assertNotIn("fixture_timing_tolerance_ms", snap)
        self.assertEqual(snap["duration_sec"], 10.0)
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.locked)
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_missing_reference_rate_blocks_lock(self):
        self._fixture()
        self.win.hz_combo.setCurrentText("")
        self.assertFalse(self.win.lock_profile())
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertEqual(self.win._lifecycle_state(), "draft")

    def test_missing_timing_tolerance_does_not_block_lock(self):
        self._fixture(tol="")
        self.assertTrue(self.win.lock_profile())
        self.assertNotIn("fixture_timing_tolerance_ms", self.win.profile_locked_settings)

    def _assert_setup_error_visible(self, key):
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_setup)
        self.assertTrue(self.win.page_setup.isAncestorOf(self.win.lbl_profile_status))
        self.assertTrue(self.win.lbl_profile_status.isVisibleTo(self.win))
        self.assertEqual(self.win.lbl_profile_status.text(), self.win._tr(key))

    def test_validation_error_visible_on_setup_without_navigation(self):
        self._fixture()
        self.win.hz_combo.setCurrentText("")
        self.assertEqual(self.win._current_page, "setup")
        self.assertFalse(self.win.lock_profile())
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertEqual(self.win._current_page, "setup")
        self._assert_setup_error_visible("reference_rate_invalid")

    def test_validation_error_retranslates_on_language_switch(self):
        self._fixture()
        self.win.hz_combo.setCurrentText("")
        self.assertFalse(self.win.lock_profile())
        self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
        self.assertEqual(
            self.win.lbl_profile_status.text(),
            STRINGS["zh"]["reference_rate_invalid"],
        )

    def test_successful_lock_clears_setup_validation_error(self):
        self._fixture()
        self.win.hz_combo.setCurrentText("")
        self.assertFalse(self.win.lock_profile())
        self._fixture(tol="2")
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win.lbl_profile_status.text(), self.win._tr("profile_status_locked"))
        self.assertIsNone(self.win._profile_validation_error_key)

    def test_edit_profile_returns_clean_draft_status(self):
        self._fixture()
        self.win.hz_combo.setCurrentText("")
        self.assertFalse(self.win.lock_profile())
        self._fixture(tol="2")
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.edit_profile())
        self.assertEqual(self.win._current_page, "setup")
        self.assertEqual(self.win.lbl_profile_status.text(), self.win._tr("profile_status_draft"))

    def test_hidden_timing_tolerance_zero_is_not_stamped(self):
        self._fixture(tol="0")
        self.assertTrue(self.win.lock_profile())
        self.assertNotIn("fixture_timing_tolerance_ms", self.win.profile_locked_settings)

    def test_invalid_auto_stop_blocks_only_when_on(self):
        self._fixture(auto_sec=None)
        self.win.auto_stop_sec_combo.setCurrentText("abc")
        self.assertTrue(self.win.lock_profile())
        self.win.edit_profile()
        self._fixture(auto_sec="abc")
        self.assertFalse(self.win.lock_profile())

    def test_lock_stamps_legacy_defaults_without_custom_limit_widgets(self):
        self.win.radio_manual.setChecked(True)
        self.assertEqual(self.win._limit_edits, {})
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        self.assertIsNotNone(snap)
        defaults = qt_app.qt_custom_limit_defaults()
        for key, value in defaults.items():
            self.assertEqual(snap[key], value)

    def test_lock_snapshot_is_immutable(self):
        self._fixture(hz="40", tol="2")
        self.win.device_edit.setText("DUT-A")
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        self.win.hz_combo.setCurrentText("10")
        self.win.timing_tol_edit.setText("9")
        self.win.device_edit.setText("DUT-B")
        self.assertEqual(snap["fixture_reference_hz"], 40.0)
        self.assertNotIn("fixture_timing_tolerance_ms", snap)
        self.assertEqual(self.win.profile_locked_target, "DUT-A")
        self.assertIs(self.win.profile_locked_settings, snap)

    def test_setup_disabled_after_lock(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.win.nav_setup.click()
        for widget in (self.win.device_edit, self.win.hz_combo, self.win.timing_tol_edit):
            self.assertFalse(widget.isEnabled(), widget)

    def test_disarmed_test_area_click_does_not_start(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._in_test_area = True
        self._click()
        self.assertFalse(self.win.running)
        self.assertEqual(self.win._lifecycle_state(), "ready")

    def test_disarmed_does_not_queue_downs(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._raw("down")
        self.assertEqual(sum(len(q) for q in self.win.device_press_queues.values()), 0)

    def test_arm_does_not_open_a_dead_window(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        before = time.perf_counter()
        self.assertTrue(self.win.arm_capture())
        self.assertIsNotNone(self.win._arm_boundary_perf)
        self.assertGreaterEqual(self.win._arm_boundary_perf, before - 0.05)
        self.assertLessEqual(self.win._ignore_arm_until, time.perf_counter())

    def test_first_valid_event_immediately_after_arm_starts(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 1e-6
        self._raw("down", t=t0)
        self._raw("up", t=t0 + 0.01)
        self.assertTrue(self.win.running)
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)
        self.assertAlmostEqual(self.win.end_time, self.win.start_time + 10.0)

    def _armed_event(self, etype, **stamp):
        event = {
            "capture_source": "windows_raw_input",
            "button": "Left",
            "event_type": etype,
            "device_source": "dut",
        }
        event.update(stamp)
        return event

    def test_armed_invalid_time_perf_cannot_start(self):
        cases = {
            "missing": {},
            "none": {"time_perf": None},
            "nan": {"time_perf": float("nan")},
            "pos_inf": {"time_perf": float("inf")},
            "neg_inf": {"time_perf": float("-inf")},
            "text": {"time_perf": "abc"},
            "nan_text": {"time_perf": "nan"},
            "bool": {"time_perf": True},
        }
        for name, stamp in cases.items():
            with self.subTest(case=name):
                self.win.edit_profile()
                self._fixture()
                self.assertTrue(self.win.lock_profile())
                self.assertTrue(self.win.arm_capture())
                self.win._on_raw_event_ui(self._armed_event("down", **stamp))
                self.assertEqual(sum(len(q) for q in self.win.device_press_queues.values()), 0)
                self.win._on_raw_event_ui(self._armed_event("up", **stamp))
                self.assertFalse(self.win.running)
                self.assertIsNone(self.win.start_time)
                self.assertIsNone(self.win.locked)
                self.assertEqual(self.win.events, [])
                self.assertTrue(self.win.capture_armed)
                self.assertFalse(self.win._arming_scheduled)
                self.assertEqual(sum(len(q) for q in self.win.device_press_queues.values()), 0)

    def _lock_arm_boundary(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        return float(self.win._arm_boundary_perf)

    def _target_queue_len(self):
        return len(self.win.device_press_queues.get(("dut", "Left"), ()))

    def test_armed_invalid_up_after_valid_down_cannot_start(self):
        boundary = self._lock_arm_boundary()
        self.win._on_raw_event_ui(self._armed_event("down", time_perf=boundary + 0.001))
        self.assertEqual(self._target_queue_len(), 1)
        self.win._on_raw_event_ui(self._armed_event("up", time_perf=float("nan")))
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])
        self.assertEqual(self._target_queue_len(), 0)

    def test_invalid_up_invalidates_pending_down_for_later_up(self):
        for name, stamp in (
            ("missing", {}),
            ("none", {"time_perf": None}),
            ("nan", {"time_perf": float("nan")}),
            ("pos_inf", {"time_perf": float("inf")}),
            ("neg_inf", {"time_perf": float("-inf")}),
            ("text", {"time_perf": "abc"}),
        ):
            with self.subTest(case=name):
                self.win.edit_profile()
                boundary = self._lock_arm_boundary()
                self.win._on_raw_event_ui(self._armed_event("down", time_perf=boundary + 0.001))
                self.win._on_raw_event_ui(self._armed_event("up", **stamp))
                self.win._on_raw_event_ui(self._armed_event("up", time_perf=boundary + 0.02))
                self.assertFalse(self.win.running)
                self.assertIsNone(self.win.start_time)
                self.assertEqual(self.win.events, [])
                self.assertEqual(self._target_queue_len(), 0)

    def test_invalid_up_then_new_valid_pair_starts_from_new_down(self):
        boundary = self._lock_arm_boundary()
        stale_down = boundary + 0.001
        new_down = boundary + 0.05
        self.win._on_raw_event_ui(self._armed_event("down", time_perf=stale_down))
        self.win._on_raw_event_ui(self._armed_event("up", time_perf=float("inf")))
        self.win._on_raw_event_ui(self._armed_event("down", time_perf=new_down))
        self.win._on_raw_event_ui(self._armed_event("up", time_perf=new_down + 0.01))
        self.assertTrue(self.win.running)
        self.assertEqual(self.win.start_time, new_down)
        self.assertEqual(self.win.first_press_time, new_down)
        self.assertEqual(len(self.win.events), 1)
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)

    def test_boundary_or_stale_up_invalidates_pending_down(self):
        for name, offset in (("at_boundary", 0.0), ("before_boundary", -0.5)):
            with self.subTest(case=name):
                self.win.edit_profile()
                boundary = self._lock_arm_boundary()
                self.win._on_raw_event_ui(self._armed_event("down", time_perf=boundary + 0.001))
                self.win._on_raw_event_ui(self._armed_event("up", time_perf=boundary + offset))
                self.assertEqual(self._target_queue_len(), 0)
                self.win._on_raw_event_ui(self._armed_event("up", time_perf=boundary + 0.02))
                self.assertFalse(self.win.running)
                self.assertEqual(self.win.events, [])

    def test_invalid_target_event_leaves_other_keys_untouched(self):
        boundary = self._lock_arm_boundary()
        self.win.device_press_queues[("other_dut", "Left")].append(boundary + 0.001)
        self.win._on_raw_event_ui(self._armed_event("down", time_perf=boundary + 0.001))
        self.win._on_raw_event_ui(self._armed_event("up", time_perf=float("nan")))
        self.assertEqual(self._target_queue_len(), 0)
        self.assertEqual(len(self.win.device_press_queues[("other_dut", "Left")]), 1)

    def test_boundary_helper_rejects_non_finite(self):
        boundary = self._lock_arm_boundary()
        for value in (float("inf"), float("nan"), float("-inf")):
            with self.subTest(value=value):
                self.assertFalse(self.win._is_timestamp_after_arm_boundary(value))
        self.assertFalse(self.win._is_timestamp_after_arm_boundary(boundary))
        self.assertTrue(self.win._is_timestamp_after_arm_boundary(boundary + 1e-6))

    def test_boundary_helper_rejects_non_finite_boundary(self):
        self._lock_arm_boundary()
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(boundary=bad):
                self.win._arm_boundary_perf = bad
                self.assertFalse(self.win._is_timestamp_after_arm_boundary(1.0))

    def test_armed_valid_finite_stamp_after_boundary_starts_immediately(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 1e-6
        self.win._on_raw_event_ui(self._armed_event("down", time_perf=t0))
        self.win._on_raw_event_ui(self._armed_event("up", time_perf=t0 + 0.01))
        self.assertTrue(self.win.running)
        self.assertEqual(self.win.start_time, t0)
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)

    def test_event_at_arm_boundary_cannot_become_t0(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        boundary = float(self.win._arm_boundary_perf)
        self._raw("down", t=boundary)
        self._raw("up", t=boundary)
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])

    def test_delayed_pre_arm_timestamp_cannot_start(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        pre = time.perf_counter()
        self.assertTrue(self.win.arm_capture())
        self.assertGreater(self.win._arm_boundary_perf, pre)
        self._raw("down", t=pre)
        self._raw("up", t=pre + 0.01)
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])

    def test_pre_arm_down_post_arm_up_cannot_start(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        pre = time.perf_counter()
        self._raw("down", t=pre)
        self.assertTrue(self.win.arm_capture())
        self._raw("up", t=float(self.win._arm_boundary_perf) + 0.01)
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])

    def test_arm_transitions_without_t0(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self.assertEqual(self.win._lifecycle_state(), "armed")
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.locked)
        self.assertEqual(self.win.events, [])

    def test_pre_arm_down_cannot_pair_after_arm(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._raw("down", t=_T0)
        self._arm_now()
        self._raw("up", t=_T0 + 0.01)
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])

    def test_arm_clears_stale_queues(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.win.device_press_queues[("dut", "Left")].append(_T0)
        self._arm_now()
        self.assertEqual(sum(len(q) for q in self.win.device_press_queues.values()), 0)

    def test_disarm_preserves_profile_and_clears_queues(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        self._arm_now()
        self.win.device_press_queues[("dut", "Left")].append(_T0)
        self.assertTrue(self.win.disarm_capture())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertIs(self.win.profile_locked_settings, snap)
        self.assertEqual(sum(len(q) for q in self.win.device_press_queues.values()), 0)

    def test_rearm_works(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self.win.disarm_capture()
        self._arm_now()
        self._click()
        self.assertTrue(self.win.running)

    def test_manual_armed_in_test_area_starts_once(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._in_test_area = True
        self._click()
        self.assertTrue(self.win.running)
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)
        self.assertFalse(self.win.capture_armed)
        self._click()
        self.assertEqual(len(self.win.events), 2)

    def test_manual_armed_outside_test_area_does_not_start(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._in_test_area = False
        self._click()
        self.assertFalse(self.win.running)

    def test_fixture_armed_outside_test_area_not_over_ui_starts(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._in_test_area = False
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self._click()
        self.assertTrue(self.win.running)
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)

    def test_fixture_armed_over_ui_does_not_start(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.win.resize(1280, 840)
        self.win.show()
        self.win.nav_capture.click()
        self._qapp.processEvents()
        self._arm_now()
        self._in_test_area = False
        self.win._cursor_over_capture_exclusion_ui = lambda: qt_app.MainWindow._cursor_over_capture_exclusion_ui(self.win)
        self._cursor = self.win.btn_arm.mapToGlobal(self.win.btn_arm.rect().center())
        self.assertTrue(self.win._cursor_over_capture_exclusion_ui())
        self._click()
        self.assertFalse(self.win.running)

    def test_non_target_button_does_not_start(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click(button="Right")
        self.assertFalse(self.win.running)

    def test_run_locked_is_copy_of_profile_and_ignores_widget_mutation(self):
        self._fixture(hz="40", tol="2")
        self.assertTrue(self.win.lock_profile())
        profile = self.win.profile_locked_settings
        self._arm_now()
        self._click()
        self.assertIsNot(self.win.locked, profile)
        self.assertEqual(self.win.locked["fixture_reference_hz"], 40.0)
        self.win.hz_combo.setCurrentText("5")
        self.assertEqual(self.win.locked["fixture_reference_hz"], 40.0)
        self.assertEqual(self.win.profile_locked_settings["fixture_reference_hz"], 40.0)

    def test_auto_stop_starts_from_t0_not_lock_or_arm(self):
        self._fixture(auto_sec="10")
        self.assertTrue(self.win.lock_profile())
        self.assertIsNone(self.win.end_time)
        self._arm_now()
        self.assertIsNone(self.win.end_time)
        self._click()
        self.assertAlmostEqual(self.win.end_time, self.win.start_time + 10.0)

    def test_stop_leaves_profile_locked(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.win.stop_run()
        self.assertTrue(self.win.completed)
        self.assertIsNotNone(self.win.profile_locked_settings)
        self.assertFalse(self.win.capture_armed)
        self.assertFalse(self.win.btn_edit_profile.isEnabled())

    def test_host_evidence_fixture_auto_stop_on_once(self):
        self._fixture(hz="40", auto_sec="10")
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self.assertTrue(self.win.lock_profile())
            apply_explicit_association(self.win, 2.0)
            self._arm_now()
            self._click()
            t1 = self.win.start_time + 0.025
            self.win.record_click("Left", t1, t1 + 0.01, {})
            self.win.stop_run()
            self.win.nav_results.click()
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
        self.assertEqual(builder.call_count, 1)
        self.assertIsNotNone(self.win.host_evidence_snapshot)

    def test_host_evidence_not_for_manual_or_auto_stop_off(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.win.stop_run()
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.win.new_run()
        self.win.edit_profile()
        self._fixture(auto_sec=None)
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.win.stop_run()
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_new_run_preserves_profile_and_returns_disarmed(self):
        self._fixture(hz="40", tol="2")
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.win.stop_run()
        snap = self.win.profile_locked_settings
        self.win.new_run()
        self.assertIsNone(self.win.locked)
        self.assertEqual(self.win.events, [])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertFalse(self.win.completed)
        self.assertIs(self.win.profile_locked_settings, snap)
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertFalse(self.win.capture_armed)
        self.assertEqual(self.win.hz_combo.currentText(), "40")
        self._arm_now()
        self._click()
        self.assertTrue(self.win.running)
        self.assertEqual(self.win.locked["fixture_reference_hz"], 40.0)

    def test_edit_profile_from_ready_and_armed(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.edit_profile())
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertTrue(self.win.device_edit.isEnabled())
        self.assertEqual(self.win._current_page, "setup")
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self.win.device_press_queues[("dut", "Left")].append(_T0)
        self.assertTrue(self.win.edit_profile())
        self.assertFalse(self.win.capture_armed)
        self.assertEqual(sum(len(q) for q in self.win.device_press_queues.values()), 0)
        self.assertTrue(self.win.hz_combo.isEnabled())

    def test_edit_profile_unavailable_running_and_completed(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.assertFalse(self.win.btn_edit_profile.isEnabled())
        self.assertFalse(self.win.edit_profile())
        self.assertTrue(self.win.running)
        self.win.stop_run()
        snap = self.win.host_evidence_snapshot
        self.assertFalse(self.win.btn_edit_profile.isEnabled())
        self.assertFalse(self.win.edit_profile())
        self.assertTrue(self.win.completed)
        self.assertIs(self.win.host_evidence_snapshot, snap)

    def test_navigation_never_locks_arms_or_starts(self):
        self._fixture()
        armed = self.win.capture_armed
        self.win.nav_capture.click()
        self.win.nav_results.click()
        self.win.nav_setup.click()
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertEqual(self.win.capture_armed, armed)
        self.assertFalse(self.win.running)

    def test_i18n_keys_exist(self):
        for lang in SUPPORTED_LANGS:
            for key in _I18N_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(STRINGS[lang].get(key) or "").strip())

    def test_no_report_schema_fields(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.win.stop_run()
        self.win.new_run()
        run = self.win.session_runs[-1]
        self.assertNotIn("profile_locked_settings", run)
        self.assertNotIn("capture_armed", run.get("settings") or {})

    def test_ready_shows_start_capture_while_internally_unarmed(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertFalse(self.win.capture_armed)
        self.assertEqual(self.win.btn_arm.text(), self.win._tr("arm_capture"))
        self.assertIn("Start Capture", self.win.btn_arm.text())
        self.assertTrue(self.win.btn_arm.isEnabled())
        self.assertFalse(self.win.btn_stop.isEnabled())
        self.assertTrue(self.win.btn_edit_profile.isEnabled())
        self.assertTrue(self.win.capture_action_bar.isVisibleTo(self.win))
        self.assertFalse(self.win.capture_completed_bar.isVisibleTo(self.win))
        self.win.btn_arm.click()
        self.assertEqual(self.win._lifecycle_state(), "armed")
        self.assertTrue(self.win.capture_armed)
        self.assertEqual(self.win.btn_arm.text(), self.win._tr("disarm_capture"))
        self.assertIn("Cancel Start", self.win.btn_arm.text())

    def test_start_capture_button_click_cannot_become_t0(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.win.btn_arm.click()
        boundary = float(self.win._arm_boundary_perf)
        self._raw("down", t=boundary)
        self._raw("up", t=boundary)
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])

    def test_cancel_start_returns_ready_without_a_run(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self.win.btn_arm.click()
        self.win.device_press_queues[("dut", "Left")].append(_T0)
        self.win.btn_arm.click()
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertFalse(self.win.capture_armed)
        self.assertFalse(self.win.running)
        self.assertFalse(self.win.completed)
        self.assertEqual(self.win.events, [])
        self.assertIsNone(self.win.locked)
        self.assertEqual(sum(len(q) for q in self.win.device_press_queues.values()), 0)

    def test_manual_ready_guidance_requires_test_area(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertIn("Test Area", self.win.status_label.text())
        self.assertIn("Start Capture", self.win.status_label.text())
        self.assertNotIn("fixture", self.win.status_label.text().lower())
        self.win.btn_arm.click()
        self.assertIn("Test Area", self.win.status_label.text())
        self.assertIn("this area", self.win.hint.text().lower())

    def test_fixture_ready_guidance_does_not_require_test_area(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        text = f"{self.win.status_label.text()}\n{self.win.hint.text()}"
        self.assertIn("Start Capture", self.win.status_label.text())
        self.assertIn("fixture", text.lower())
        self.assertNotIn("click inside the Test Area", self.win.status_label.text())
        self.assertIn("do not need to hit this area", self.win.hint.text())
        self.win.btn_arm.click()
        self.assertIn("fixture", self.win.status_label.text().lower())
        self.assertNotIn("Click inside the Test Area", self.win.status_label.text())

    def test_running_controls_enable_stop_only(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.assertEqual(self.win._lifecycle_state(), "running")
        self.assertTrue(self.win.btn_stop.isEnabled())
        self.assertFalse(self.win.btn_arm.isEnabled())
        self.assertFalse(self.win.btn_edit_profile.isEnabled())
        self.assertTrue(self.win.capture_action_bar.isVisibleTo(self.win))
        self.assertFalse(self.win.capture_completed_bar.isVisibleTo(self.win))

    def test_completed_capture_offers_new_run_results_edit_setup(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.win.stop_run()
        self.win._release_post_run_input_guard()
        self.win._show_workflow_page("capture")
        self.assertEqual(self.win._lifecycle_state(), "completed")
        self.assertFalse(self.win.capture_action_bar.isVisibleTo(self.win))
        self.assertTrue(self.win.capture_completed_bar.isVisibleTo(self.win))
        self.assertFalse(self.win.btn_stop.isVisibleTo(self.win))
        self.assertFalse(self.win.btn_arm.isVisibleTo(self.win))
        self.assertTrue(self.win.btn_capture_new_run.isEnabled())
        self.assertTrue(self.win.btn_capture_goto_results.isEnabled())
        self.assertTrue(self.win.btn_capture_edit_setup.isEnabled())
        self.assertEqual(self.win.btn_capture_new_run.text(), self.win._tr("new_run"))
        self.assertEqual(self.win.btn_capture_goto_results.text(), self.win._tr("nav_results"))
        snap = self.win.profile_locked_settings
        with mock.patch.object(self.win, "_show_workflow_page", wraps=self.win._show_workflow_page) as shown:
            self.win.btn_capture_goto_results.click()
        shown.assert_called_with("results")
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self.win._show_workflow_page("capture")
        self.win.btn_capture_new_run.click()
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertFalse(self.win.completed)
        self.assertEqual(self.win.events, [])
        self.assertIs(self.win.profile_locked_settings, snap)

    def test_completed_capture_edit_setup_uses_existing_path(self):
        self._fixture()
        self.assertTrue(self.win.lock_profile())
        self._arm_now()
        self._click()
        self.win.stop_run()
        self.win._release_post_run_input_guard()
        self.win._show_workflow_page("capture")
        self.win.btn_capture_edit_setup.click()
        self.assertEqual(self.win._lifecycle_state(), "draft")
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertEqual(self.win._current_page, "setup")
        self.assertFalse(self.win.completed)
        self.assertEqual(self.win.events, [])
        self.assertTrue(self.win.device_edit.isEnabled())


if __name__ == "__main__":
    unittest.main()
