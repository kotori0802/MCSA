"""Phase 4D-2a: post-run GUI mouse-input quarantine after a completed Capture run."""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.qt_shell import app as qt_app

_QUIET_MS = 50


def _make_qapp():
    return QApplication.instance() or QApplication([])


class PostRunQuietMsTests(unittest.TestCase):
    def test_6hz_uses_900ms_floor(self):
        self.assertEqual(
            qt_app.post_run_quiet_ms({"manual_mode": False, "fixture_reference_hz": 6.0}),
            900,
        )
        self.assertEqual(
            qt_app.post_run_quiet_ms({"manual_mode": False, "fixture_reference_hz": 10.0}),
            900,
        )

    def test_1hz_uses_two_intervals(self):
        self.assertEqual(
            qt_app.post_run_quiet_ms({"manual_mode": False, "fixture_reference_hz": 1.0}),
            2000,
        )

    def test_half_hz_uses_two_intervals(self):
        self.assertEqual(
            qt_app.post_run_quiet_ms({"manual_mode": False, "fixture_reference_hz": 0.5}),
            4000,
        )
        self.assertEqual(
            qt_app.post_run_quiet_ms({"manual_mode": False, "fixture_hz": 2.0}),
            1000,
        )

    def test_manual_does_not_fabricate_fixture_cadence(self):
        self.assertEqual(qt_app.post_run_quiet_ms({"manual_mode": True}), 900)
        self.assertEqual(
            qt_app.post_run_quiet_ms({
                "manual_mode": True,
                "fixture_reference_hz": 0.5,
                "fixture_hz": 0.5,
            }),
            900,
        )


class PostRunInputGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self._quiet = mock.patch.object(qt_app, "POST_RUN_INPUT_QUIET_MS", _QUIET_MS)
        self._quiet.start()
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name) / self.id().rsplit(".", 1)[-1])
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()
        self.win.ensure_raw_input = lambda: None
        self.win._cursor_in_test_area = lambda: True
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self.win.listening = True
        self.win.resize(1280, 840)
        self.win.show()
        self._qapp.processEvents()
        self.win.ui_timer.stop()
        self.win._listen_start_timer.stop()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._quiet.stop()

    def _setup_fixture(self, *, auto_sec: str | None = "1", hz: str = "6"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText("2")
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _complete(self, *, auto_stop=False):
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        for off in (0, 166, 332, 498, 664):
            if off == 0:
                continue
            press = t0 + off / 1000.0
            self.win.record_click("Left", press, press + 0.01, {})
        if auto_stop:
            self.win.end_time = time.perf_counter() - 1e-6
            self.win._tick()
        else:
            self.win.stop_run()
        self._qapp.processEvents()

    def _snapshot(self):
        return {
            "completed": self.win.completed,
            "run_id": self.win.run_id,
            "events": copy.deepcopy(list(self.win.events)),
            "raw_events": copy.deepcopy(list(self.win.raw_events)),
            "locked": copy.deepcopy(self.win.locked),
            "host_evidence": copy.deepcopy(self.win.host_evidence_snapshot),
            "session_runs": copy.deepcopy(list(self.win.session_runs)),
        }

    def _assert_preserved(self, before):
        self.assertTrue(self.win.completed)
        self.assertEqual(self.win.run_id, before["run_id"])
        self.assertEqual(self.win.events, before["events"])
        self.assertEqual(self.win.raw_events, before["raw_events"])
        self.assertEqual(self.win.locked, before["locked"])
        self.assertEqual(self.win.host_evidence_snapshot, before["host_evidence"])
        self.assertEqual(self.win.session_runs, before["session_runs"])
        facts = self.win._completed_run_facts()
        self.assertIsNotNone(facts)
        self.assertEqual(facts["model"]["run"]["run_id"], before["run_id"])

    def _assert_guarded(self):
        self.assertTrue(self.win._post_run_input_guard_active)
        self.assertFalse(self.win.btn_edit_setup_new_run.isEnabled())
        self.assertFalse(self.win.btn_new.isEnabled())
        self.assertFalse(self.win.btn_generate_excel.isEnabled())
        self.assertFalse(self.win.btn_generate_html.isEnabled())
        self.assertFalse(self.win.btn_export.isEnabled())
        self.assertFalse(self.win.btn_overlay.isEnabled())
        self.assertFalse(self.win.btn_clear_overlay.isEnabled())
        self.assertFalse(self.win.nav_setup.isEnabled())
        self.assertFalse(self.win.nav_capture.isEnabled())
        self.assertFalse(self.win.nav_preferences.isEnabled())
        self.assertFalse(self.win.btn_help.isEnabled())
        self.assertTrue(self.win.nav_results.isEnabled())
        self.assertTrue(self.win.results_tabs.isEnabled())
        self.assertTrue(self.win.results_view_combo.isEnabled())
        self.assertTrue(self.win.results_scroll.isEnabled())
        self.assertTrue(self.win.results_input_guard_status.isVisibleTo(self.win))

    def _send_global_mouse_move(self, global_pos: QPoint):
        local = self.win.mapFromGlobal(global_pos)
        event = QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(local),
            QPointF(local),
            QPointF(global_pos),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(self.win, event)
        self._qapp.processEvents()

    def _signal_human_intent(self, *, distance: int | None = None):
        origin = QPoint(self.win._post_run_guard_origin)
        delta = int(qt_app.POST_RUN_HUMAN_INTENT_MOVE_PX) + 8 if distance is None else int(distance)
        self._send_global_mouse_move(origin + QPoint(delta, 0))

    def _wait_quiet(self, extra_ms: int = 40):
        QTest.qWait(int(self.win._post_run_quiet_ms()) + extra_ms)
        self._qapp.processEvents()

    def _unlock_guard(self):
        self._signal_human_intent()
        self._wait_quiet()

    def test_auto_stop_activates_guard_on_results(self):
        self._setup_fixture(auto_sec="1")
        self._complete(auto_stop=True)
        self.assertTrue(self.win.completed)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self._assert_guarded()
        before = self._snapshot()
        self._assert_preserved(before)

    def test_guarded_edit_setup_mouse_click_does_not_clear_results(self):
        self._setup_fixture()
        self._complete()
        before = self._snapshot()
        self._assert_guarded()
        QTest.mouseClick(self.win.btn_edit_setup_new_run, Qt.MouseButton.LeftButton)
        self._qapp.processEvents()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self._assert_preserved(before)
        self.assertTrue(self.win._post_run_input_guard_active)

    def test_guarded_run_again_mouse_click_does_not_clear_results(self):
        self._setup_fixture()
        self._complete()
        before = self._snapshot()
        QTest.mouseClick(self.win.btn_new, Qt.MouseButton.LeftButton)
        self._qapp.processEvents()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self._assert_preserved(before)

    def test_repeated_clicks_restart_quiet_timer(self):
        self._setup_fixture()
        self._complete()
        self.assertTrue(self.win._post_run_input_guard_active)
        remaining_before = self.win._post_run_quiet_timer.remainingTime()
        for _ in range(4):
            QTest.mousePress(self.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
            QTest.mouseRelease(self.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20))
            QTest.qWait(int(_QUIET_MS * 0.4))
        # 4 × 0.4 quiet > one quiet period; the guard stays up only if the timer restarted.
        self.assertTrue(self.win._post_run_input_guard_active)
        self.assertTrue(self.win._post_run_quiet_timer.isActive())
        self.assertGreater(self.win._post_run_quiet_timer.remainingTime(), 0)

    def test_quiet_release_restores_lifecycle_enablement(self):
        self._setup_fixture()
        self._complete()
        self._assert_guarded()
        self._unlock_guard()
        self.assertFalse(self.win._post_run_input_guard_active)
        self.assertTrue(self.win.completed)
        self.assertTrue(self.win.btn_edit_setup_new_run.isEnabled())
        self.assertTrue(self.win.btn_new.isEnabled())
        self.assertTrue(self.win.btn_generate_excel.isEnabled())
        self.assertTrue(self.win.btn_overlay.isEnabled())
        self.assertFalse(self.win.btn_clear_overlay.isEnabled())
        self.assertTrue(self.win.nav_setup.isEnabled())
        self.assertTrue(self.win.btn_help.isEnabled())

    def test_after_release_edit_setup_mouse_click_works(self):
        self._setup_fixture()
        self._complete()
        events = copy.deepcopy(list(self.win.events))
        self._unlock_guard()
        self.assertFalse(self.win._post_run_input_guard_active)
        self.assertTrue(self.win.btn_edit_setup_new_run.isEnabled())
        QTest.mouseClick(self.win.btn_edit_setup_new_run, Qt.MouseButton.LeftButton)
        self._qapp.processEvents()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_setup)
        self.assertFalse(self.win.completed)
        self.assertIsNone(self.win.locked)
        self.assertFalse(self.win.events)
        self.assertTrue(self.win.session_runs)
        self.assertEqual(self.win.session_runs[-1]["events"], events)

    def test_user_stop_activates_the_same_guard(self):
        self._setup_fixture(auto_sec=None)
        self._complete(auto_stop=False)
        self.assertTrue(self.win.completed)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self._assert_guarded()

    def test_tabs_view_and_scroll_remain_usable_while_guarded(self):
        self._setup_fixture()
        self._complete()
        self._assert_guarded()
        self.assertEqual(self.win.results_tabs.currentIndex(), 0)
        bar = self.win.results_tabs.tabBar()
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, bar.tabRect(1).center())
        self._qapp.processEvents()
        self.assertEqual(self.win.results_tabs.currentIndex(), 1)
        self.win.results_view_combo.setCurrentIndex(min(1, self.win.results_view_combo.count() - 1))
        self.assertTrue(self.win.results_scroll.isEnabled())
        self.assertTrue(self.win._post_run_input_guard_active)
        self.assertTrue(self.win.completed)

    def test_navigation_blocked_while_guarded_and_works_after_release(self):
        self._setup_fixture()
        self._complete()
        before = self._snapshot()
        QTest.mouseClick(self.win.nav_setup, Qt.MouseButton.LeftButton)
        self._qapp.processEvents()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self._assert_preserved(before)
        self._unlock_guard()
        self.assertTrue(self.win.nav_setup.isEnabled())
        QTest.mouseClick(self.win.nav_setup, Qt.MouseButton.LeftButton)
        self._qapp.processEvents()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_setup)
        self.assertTrue(self.win.completed)

    def test_manual_results_navigation_without_completed_run_does_not_arm_guard(self):
        self._setup_fixture()
        self.win._show_workflow_page("results")
        self._qapp.processEvents()
        self.assertFalse(self.win.completed)
        self.assertFalse(self.win._post_run_input_guard_active)
        self.assertTrue(self.win.nav_setup.isEnabled())

    def test_guard_status_visible_without_scrolling(self):
        self._setup_fixture()
        self._complete()
        text = self.win._tr("waiting_for_mouse_input")
        for width, height in ((1280, 720), (1600, 900)):
            with self.subTest(size=f"{width}x{height}"):
                self.win.resize(width, height)
                self._qapp.processEvents()
                status = self.win.results_input_guard_status
                self.assertTrue(status.isVisibleTo(self.win))
                self.assertEqual(status.text(), text)
                self.assertFalse(self.win.results_next_run_note.isVisibleTo(self.win))
                viewport = self.win.results_scroll.viewport()
                top = status.mapTo(viewport, QPoint(0, 0))
                self.assertGreaterEqual(top.y(), 0)
                self.assertLess(top.y(), viewport.height())
                self.assertNotIn(text, self.win.results_verdict_label.text())
                self.assertNotIn(text, self.win.results_tags_label.text())
                self.assertNotIn(text, self.win.results_observations_text.text())

    def test_guard_status_disappears_after_release(self):
        self._setup_fixture()
        self._complete()
        self.assertTrue(self.win.results_input_guard_status.isVisibleTo(self.win))
        self._unlock_guard()
        self.assertFalse(self.win._post_run_input_guard_active)
        self.assertFalse(self.win.results_input_guard_status.isVisibleTo(self.win))
        self.assertEqual(self.win.results_input_guard_status.text(), "")

    def test_clear_overlay_enablement_follows_loaded_overlay(self):
        self._setup_fixture()
        self._complete()
        self._unlock_guard()
        self.assertFalse(self.win._post_run_input_guard_active)
        self.assertTrue(self.win.btn_overlay.isEnabled())
        self.assertFalse(self.win.btn_clear_overlay.isEnabled())
        self.win._set_overlay(list(self.win.events), {}, "session:overlay")
        self.assertTrue(self.win.btn_clear_overlay.isEnabled())
        self.win.clear_overlay()
        self.assertFalse(self.win.btn_clear_overlay.isEnabled())
        self.assertTrue(self.win.btn_overlay.isEnabled())

    def test_half_hz_repeated_fixture_clicks_never_release(self):
        self._setup_fixture(hz="0.5")
        with mock.patch.object(qt_app, "post_run_quiet_ms", return_value=80):
            self._complete()
            self._assert_guarded()
            self._signal_human_intent()
            for _ in range(6):
                QTest.mousePress(
                    self.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20),
                )
                QTest.mouseRelease(
                    self.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(20, 20),
                )
                QTest.qWait(40)
            self.assertTrue(self.win._post_run_input_guard_active)
            self.assertTrue(self.win._post_run_quiet_timer.isActive())
            self.assertTrue(self.win.completed)

    def test_quiet_without_cursor_move_stays_locked(self):
        self._setup_fixture()
        self._complete()
        self._wait_quiet()
        self.assertTrue(self.win._post_run_input_guard_active)
        self.assertTrue(self.win._post_run_quiet_ready)
        self.assertFalse(self.win._post_run_human_intent)

    def test_cursor_move_before_quiet_stays_locked(self):
        self._setup_fixture()
        self._complete()
        self._signal_human_intent()
        self.assertTrue(self.win._post_run_human_intent)
        QTest.qWait(max(1, int(self.win._post_run_quiet_ms() * 0.3)))
        self._qapp.processEvents()
        self.assertTrue(self.win._post_run_input_guard_active)
        self.assertFalse(self.win._post_run_quiet_ready)

    def test_cursor_move_and_quiet_releases(self):
        self._setup_fixture()
        self._complete()
        self._signal_human_intent()
        self._wait_quiet()
        self.assertFalse(self.win._post_run_input_guard_active)
        self.assertTrue(self.win.btn_edit_setup_new_run.isEnabled())

    def test_press_release_does_not_set_human_intent(self):
        self._setup_fixture()
        self._complete()
        origin = QPoint(self.win._post_run_guard_origin)
        local = QPointF(self.win.mapFromGlobal(origin))
        global_pos = QPointF(origin)
        for etype, buttons in (
            (QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
            (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton),
        ):
            event = QMouseEvent(
                etype,
                local,
                local,
                global_pos,
                Qt.MouseButton.LeftButton,
                buttons,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(self.win, event)
        self._qapp.processEvents()
        self.assertFalse(self.win._post_run_human_intent)
        self._wait_quiet()
        self.assertTrue(self.win._post_run_input_guard_active)

    def test_subthreshold_cursor_jitter_does_not_unlock(self):
        self._setup_fixture()
        self._complete()
        self._signal_human_intent(distance=8)
        self.assertFalse(self.win._post_run_human_intent)
        self._wait_quiet()
        self.assertTrue(self.win._post_run_input_guard_active)

    def test_manual_uses_quiet_floor_and_requires_intent(self):
        self.win.radio_manual.setChecked(True)
        self._complete()
        self.assertTrue(bool(self.win.locked.get("manual_mode")))
        self.assertEqual(self.win._post_run_quiet_ms(), int(qt_app.POST_RUN_INPUT_QUIET_MS))
        self.assertEqual(
            qt_app.post_run_quiet_ms({
                **dict(self.win.locked),
                "fixture_reference_hz": 0.5,
                "fixture_hz": 0.5,
            }),
            int(qt_app.POST_RUN_INPUT_QUIET_MS),
        )
        self._wait_quiet()
        self.assertTrue(self.win._post_run_input_guard_active)
        self._unlock_guard()
        self.assertFalse(self.win._post_run_input_guard_active)


if __name__ == "__main__":
    unittest.main()
