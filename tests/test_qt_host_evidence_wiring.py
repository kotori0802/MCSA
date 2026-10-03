"""Focused tests for Phase 2B-3d2a Qt Host Evidence runtime wiring."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer import app as legacy_app
from mouse_click_stability_analyzer.host_evidence import HostEvidenceError, build_fixture_host_evidence
from mouse_click_stability_analyzer.qt_shell import app as qt_app

_T0 = 1000.0


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover - environment without Qt
        return None
    return QApplication.instance() or QApplication([])


class QtHostEvidenceWiringTests(unittest.TestCase):
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
        self.win = self._new_window()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _new_window(self):
        win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        win._listen_start_timer.stop()
        win.ui_timer.stop()
        win.ensure_raw_input = lambda: None
        win._cursor_in_test_area = lambda: True
        win.listening = True
        return win

    # -- run drivers -------------------------------------------------
    def _setup_fixture(self, win=None, *, hz="40", tol="2", auto_sec: str | None = "1"):
        win = win or self.win
        win.radio_fixture.setChecked(True)
        win.hz_combo.setCurrentText(hz)
        win.timing_tol_edit.setText(tol)
        if auto_sec is None:
            win.auto_stop_off.setChecked(True)
        else:
            win.auto_stop_on.setChecked(True)
            win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _setup_manual(self, win=None):
        win = win or self.win
        win.radio_manual.setChecked(True)

    def _lock_and_arm(self, win=None):
        win = win or self.win
        self.assertTrue(win.lock_profile())
        self.assertTrue(win.arm_capture())
        win._cursor_over_capture_exclusion_ui = lambda: False

    def _run(self, press_offsets_ms, win=None, *, stop=True):
        win = win or self.win
        self._lock_and_arm(win)
        win.completed = False
        t0 = float(win._arm_boundary_perf) + 0.001
        first = press_offsets_ms[0]
        win._begin_session_from_first_click("Left", t0 + first / 1000.0, t0 + first / 1000.0 + 0.01, {})
        self.assertTrue(win.running, "session did not start")
        for off in press_offsets_ms[1:]:
            press = t0 + off / 1000.0
            win.record_click("Left", press, press + 0.01, {})
        if stop:
            win.stop_run()
        if win._post_run_input_guard_active:
            win._release_post_run_input_guard()

    def _visible_outputs(self, win):
        legacy_review = win.results_observations_text.text()
        return (
            win.status_label.text(),
            win.alert_label.text(),
            legacy_review,
            win.val_verdict.text(),
            win.val_clicks.text(),
        )

    # -- tests -------------------------------------------------------
    def test_initial_state_is_none(self):
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_fixture_auto_stop_on_builds_snapshot(self):
        self._setup_fixture(hz="40", tol="2", auto_sec="1")
        self._run([0, 25, 50, 75])
        snap = self.win.host_evidence_snapshot
        self.assertIsNotNone(snap)
        self.assertEqual(snap["configuration"]["capture_duration_s"], 1.0)
        self.assertEqual(snap["configuration"]["fixture_frequency_hz"], 40.0)
        self.assertEqual(snap["configuration"]["timing_tolerance_ms"], 2.0)
        self.assertEqual(snap["counts"]["expected_slot_count"], 40)
        self.assertEqual(snap["counts"]["raw_host_press_count"], 4)
        self.assertEqual(snap["matching"]["matched_host_observation_count"], 4)

    def test_first_event_is_t0_anchor(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)
        self.assertIsNotNone(self.win.host_evidence_snapshot)

    def test_manual_does_not_build(self):
        self._setup_manual()
        with mock.patch.object(qt_app, "build_fixture_host_evidence") as builder:
            self._run([0, 25, 50, 75])
        builder.assert_not_called()
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertIn("press_elapsed_ms", self.win.events[0])

    def test_fixture_auto_stop_off_does_not_build(self):
        self._setup_fixture(hz="40", tol="2", auto_sec=None)
        offsets = [k * 25.0 for k in range(400)]
        with mock.patch.object(qt_app, "build_fixture_host_evidence") as builder:
            self._run(offsets)
        builder.assert_not_called()
        self.assertEqual(self.win.locked["duration_sec"], 0)
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_snapshot_uses_locked_settings_not_widgets(self):
        self._setup_fixture(hz="40", tol="2", auto_sec="1")
        self._run([0, 25, 50, 75], stop=False)
        self.win.radio_manual.setChecked(True)
        self.win.hz_combo.setCurrentText("5")
        self.win.timing_tol_edit.setText("13")
        self.win.auto_stop_off.setChecked(True)
        self.win.auto_stop_sec_combo.setCurrentText("99")
        self.win.stop_run()
        snap = self.win.host_evidence_snapshot
        self.assertIsNotNone(snap)
        self.assertEqual(snap["configuration"]["fixture_frequency_hz"], 40.0)
        self.assertEqual(snap["configuration"]["timing_tolerance_ms"], 2.0)
        self.assertEqual(snap["configuration"]["capture_duration_s"], 1.0)

    def test_press_elapsed_ms_is_the_observation_source(self):
        self._setup_fixture(hz="40", tol="2", auto_sec="0.1")
        self._run([0, 25, 50, 75], stop=False)
        for i, event in enumerate(self.win.events):
            event["elapsed_ms"] = 12.5 + i
            event["release_elapsed_ms"] = 12.5 + i
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self.win.stop_run()
        passed = list(builder.call_args.args[3])
        self.assertEqual(passed, [e["press_elapsed_ms"] for e in self.win.events])
        snap = self.win.host_evidence_snapshot
        self.assertEqual(snap["matching"]["single_occupancy_slot_count"], 4)
        self.assertEqual(snap["matching"]["unmatched_host_observation_count"], 0)

    def test_post_deadline_events_passed_and_isolated(self):
        self._setup_fixture(hz="40", tol="2", auto_sec="0.1")
        self._run([0, 25, 50, 75, 100, 110])
        snap = self.win.host_evidence_snapshot
        self.assertEqual(len(self.win.events), 6)
        self.assertEqual(snap["counts"]["raw_host_press_count"], 6)
        self.assertEqual(snap["counts"]["in_window_host_press_count"], 4)
        self.assertEqual(snap["matching"]["outside_capture_window_observation_count"], 2)
        self.assertEqual(snap["counts"]["expected_slot_count"], 4)
        self.assertEqual(snap["counts"]["host_count_delta_vs_expected_slots"], 0)
        self.assertEqual(snap["timing"]["matched_delta_stats"]["count"], 4)

    def test_snapshot_built_exactly_once(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            first = self.win.host_evidence_snapshot
            self.win._refresh_metrics(final=True)
            self.win._tick()
            self.win._on_lang_changed()
            self.win._retranslate_ui()
            self.win.stop_run()
            self.win.repaint()
        self.assertEqual(builder.call_count, 1)
        self.assertIs(self.win.host_evidence_snapshot, first)

    def test_not_built_during_running(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence") as builder:
            self._run([0, 25, 50], stop=False)
            self.win.end_time = time.perf_counter() + 3600.0
            self.win._refresh_metrics(final=False)
            self.win._tick()
            self.assertTrue(self.win.running)
        builder.assert_not_called()
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_auto_stop_tick_builds_once_with_post_deadline_press(self):
        self._setup_fixture(hz="40", tol="2", auto_sec="0.1")
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75, 104], stop=False)
            # t0 is a real post-Arm QPC stamp; expire Auto Stop without sleeping.
            self.win.end_time = time.perf_counter() - 1e-6
            self.win._tick()
            self.win._tick()
        self.assertFalse(self.win.running)
        self.assertEqual(builder.call_count, 1)
        snap = self.win.host_evidence_snapshot
        self.assertEqual(snap["counts"]["raw_host_press_count"], 5)
        self.assertEqual(snap["matching"]["outside_capture_window_observation_count"], 1)
        self.assertEqual(snap["counts"]["host_count_delta_vs_expected_slots"], 0)

    def test_new_run_clears_snapshot(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertIsNotNone(self.win.host_evidence_snapshot)
        self.win.new_run()
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_new_session_clears_snapshot_before_capture(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.new_run()
        self.win.host_evidence_snapshot = {"stale": True}
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_next_manual_run_does_not_inherit(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertIsNotNone(self.win.host_evidence_snapshot)
        self.win.new_run()
        self._setup_manual()
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_next_fixture_auto_stop_off_does_not_inherit(self):
        self._setup_fixture(auto_sec="1")
        self._run([0, 25, 50, 75])
        self.assertIsNotNone(self.win.host_evidence_snapshot)
        self.win.new_run()
        self._setup_fixture(auto_sec=None)
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_zero_tolerance_is_wired(self):
        self._setup_fixture(hz="40", tol="0", auto_sec="0.1")
        self._run([0, 25, 50, 75])
        snap = self.win.host_evidence_snapshot
        self.assertIsNotNone(snap)
        self.assertEqual(snap["configuration"]["timing_tolerance_ms"], 0.0)

    def test_overlapping_windows_allowed(self):
        self._setup_fixture(hz="40", tol="13", auto_sec="0.1")
        self._run([0, 12.5, 50, 75])
        snap = self.win.host_evidence_snapshot
        self.assertIsNotNone(snap)
        self.assertTrue(snap["configuration"]["matching_windows_can_overlap"])
        self.assertGreater(snap["matching"]["ambiguous_host_observation_count"], 0)

    def test_malformed_event_leaves_snapshot_none(self):
        self._setup_fixture()
        self._run([0, 25, 50], stop=False)
        del self.win.events[1]["press_elapsed_ms"]
        with self.assertLogs(qt_app._log, level="WARNING"):
            self.win.stop_run()
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_build_error_is_non_diagnostic(self):
        reference = self._new_window()
        try:
            self._setup_fixture(reference)
            self._run([0, 25, 50, 75], reference)
            expected_outputs = self._visible_outputs(reference)
        finally:
            reference.close()
            reference.deleteLater()
        for exc in (HostEvidenceError("boom"), ValueError("boom")):
            with self.subTest(exc=type(exc).__name__):
                win = self._new_window()
                try:
                    self._setup_fixture(win)
                    with mock.patch.object(qt_app, "build_fixture_host_evidence", side_effect=exc):
                        with self.assertLogs(qt_app._log, level="WARNING"):
                            self._run([0, 25, 50, 75], win)
                    self.assertIsNone(win.host_evidence_snapshot)
                    self.assertTrue(win.completed)
                    self.assertEqual(self._visible_outputs(win), expected_outputs)
                finally:
                    win.close()
                    win.deleteLater()

    def test_legacy_verdict_unchanged_by_wiring(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 90])
        with_snapshot = self._visible_outputs(self.win)
        settings = self.win.locked
        annotated = legacy_app.annotate_events(list(self.win.events), settings)
        m = legacy_app.build_payload("", "", settings, annotated, run_id="x").get("metrics") or {}
        tags = legacy_app._metrics_issue_tags(m, settings, annotated)
        verdict_before = qt_app.qt_visible_verdict(tags, m, settings)
        self.win.host_evidence_snapshot = None
        self.win._refresh_metrics(final=True)
        self.assertEqual(self._visible_outputs(self.win), with_snapshot)
        self.assertEqual(qt_app.qt_visible_verdict(tags, m, settings), verdict_before)

    def test_no_host_evidence_labels_or_cards(self):
        from PySide6.QtWidgets import QLabel

        self._setup_fixture()
        self._run([0, 25, 50, 75])
        capture_texts = " ".join(lab.text().lower() for lab in self.win.page_capture.findChildren(QLabel))
        for token in ("host evidence", "expected slot", "count delta", "occupancy", "ambiguous", "outside window"):
            self.assertNotIn(token, capture_texts)
        self.assertEqual(
            self.win.lbl_results_evidence.text(),
            self.win._tr("results_host_evidence_section").upper(),
        )

    def test_no_report_or_session_wiring(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.new_run()
        run = self.win.session_runs[-1]
        self.assertNotIn("host_evidence", run)
        self.assertNotIn("host_evidence_snapshot", run["settings"])
        report_source = Path(legacy_app.__file__).read_text(encoding="utf-8")
        self.assertNotIn("host_evidence", report_source)


if __name__ == "__main__":
    unittest.main()
