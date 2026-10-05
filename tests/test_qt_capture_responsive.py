"""Step 3d: Capture responsive reflow is presentation-only."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, QRect

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import WINDOW_MODES

_T0 = 1000.0


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


def _no_pairwise_overlap(widgets) -> None:
    geos = [w.geometry() for w in widgets]
    for i, a in enumerate(geos):
        for b in geos[i + 1 :]:
            if a.intersects(b) and a.intersected(b).width() > 1 and a.intersected(b).height() > 1:
                raise AssertionError(f"overlap {a} {b}")


class CaptureResponsiveTests(unittest.TestCase):
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
        self.win.show()
        self._qapp.processEvents()
        self.win.ui_timer.stop()
        self.win._listen_start_timer.stop()
        self.win.listening = True
        self._in_test_area = True
        self._cursor = QPoint(0, 0)
        self.win._cursor_global_pos = lambda: self._cursor
        self._t = _T0 + 1.0

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()

    def _settle(self):
        for _ in range(5):
            self._qapp.processEvents()

    def _show_capture_at(self, width: int, height: int) -> None:
        if width < self.win.minimumWidth() or height < self.win.minimumHeight():
            self.win.setMinimumSize(1, 1)
        self.win._show_workflow_page("capture")
        self.win.resize(width, height)
        self._settle()
        if self.win.width() != width or self.win.height() != height:
            self.skipTest(f"window could not reach {width}x{height}")

    def _stat_cells(self):
        return [
            self.win.val_phase.parentWidget(),
            self.win.val_time.parentWidget(),
            self.win.val_clicks.parentWidget(),
            self.win.val_interval.parentWidget(),
            self.win.val_hold.parentWidget(),
            self.win.val_verdict.parentWidget(),
        ]

    def _issue_cells(self):
        return [
            self.win.val_extra.parentWidget(),
            self.win.val_rebound.parentWidget(),
            self.win.val_delay.parentWidget(),
            self.win.val_dut.parentWidget(),
            self.win.val_setup.parentWidget(),
        ]

    def _action_buttons(self):
        return [
            self.win.btn_stop, self.win.btn_arm, self.win.btn_edit_profile,
        ]

    def _assert_label_value_separated(self, values) -> None:
        for val in values:
            cell = val.parentWidget()
            lab = None
            for child in cell.findChildren(type(val)):
                if child.objectName() == "StatLabel":
                    lab = child
                    break
            self.assertIsNotNone(lab, val)
            self.assertFalse(lab.geometry().intersects(val.geometry()), (lab.geometry(), val.geometry()))
            self.assertGreaterEqual(lab.height(), 12, lab)
            self.assertGreaterEqual(val.height(), 16, val)
            self.assertLessEqual(lab.geometry().bottom(), val.geometry().top() + 2)

    def _assert_capture_usable(self, *, stats_cols: int, issues_cols: int) -> None:
        self.assertEqual(self.win.capture_stats_grid.columns(), stats_cols)
        self.assertEqual(self.win.capture_issues_grid.columns(), issues_cols)
        _no_pairwise_overlap(self._stat_cells())
        _no_pairwise_overlap(self._issue_cells())
        _no_pairwise_overlap(self._action_buttons())
        self._assert_label_value_separated([
            self.win.val_phase, self.win.val_time, self.win.val_clicks,
            self.win.val_interval, self.win.val_hold, self.win.val_verdict,
            self.win.val_extra, self.win.val_rebound, self.win.val_delay,
            self.win.val_dut, self.win.val_setup,
        ])
        self.assertGreaterEqual(self.win.test_area.height(), 280)
        self.assertTrue(self.win.scatter.isVisible())
        self.assertFalse(self.win.interval_chart.isVisible())
        self.assertGreaterEqual(self.win.scatter.height(), 140)
        self.assertGreaterEqual(self.win.capture_chart_stack.height(), 140)
        self.assertFalse(self.win.test_area.isAncestorOf(self.win.capture_viz_toolbar))
        self.assertEqual(
            self.win.capture_scroll.horizontalScrollBarPolicy(),
            qt_app.Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertFalse(self.win.capture_scroll.horizontalScrollBar().isVisible())

    def _lifecycle_tuple(self):
        return (
            self.win._lifecycle_state(),
            self.win.capture_armed,
            self.win.running,
            self.win.completed,
            self.win.locked,
            self.win.profile_locked_settings,
            self.win.start_time,
            self.win.first_press_time,
            self.win.end_time,
            len(self.win.events),
            list(self.win.events),
            list(self.win.raw_events),
            self.win.host_evidence_snapshot,
        )

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
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self.win._cursor_in_test_area = lambda: True
        self._lock_and_arm()
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        self._settle()

    def _raw_click(self, button="Left"):
        base = {"capture_source": "windows_raw_input", "button": button, "device_source": "dut"}
        self.win._on_raw_event_ui({**base, "event_type": "down", "time_perf": self._t})
        self.win._on_raw_event_ui({**base, "event_type": "up", "time_perf": self._t + 0.01})
        self._t += 0.025

    # 1
    def test_wide_1600_is_single_row_metrics(self):
        self._show_capture_at(1600, 900)
        self._assert_capture_usable(stats_cols=6, issues_cols=5)
        ys = {c.y() for c in self._stat_cells()}
        self.assertEqual(len(ys), 1)
        self.assertEqual(len({c.y() for c in self._issue_cells()}), 1)

    # 2
    def test_standard_1440_has_no_metric_overlap(self):
        self._show_capture_at(1440, 810)
        self.assertIn(self.win.capture_stats_grid.columns(), (3, 6))
        self.assertIn(self.win.capture_issues_grid.columns(), (3, 5))
        _no_pairwise_overlap(self._stat_cells())
        _no_pairwise_overlap(self._issue_cells())
        _no_pairwise_overlap(self._action_buttons())
        self._assert_label_value_separated([self.win.val_phase, self.win.val_verdict, self.win.val_extra])
        self.assertGreaterEqual(self.win.test_area.height(), 280)

    # 3
    def test_compact_1280_reflows_without_clipping(self):
        self._show_capture_at(1280, 720)
        self.assertLess(self.win.capture_stats_grid.columns(), 6)
        self.assertLess(self.win.capture_issues_grid.columns(), 5)
        self._assert_capture_usable(
            stats_cols=self.win.capture_stats_grid.columns(),
            issues_cols=self.win.capture_issues_grid.columns(),
        )
        self.assertGreaterEqual(self.win.capture_live.height(), self.win.capture_live.minimumSizeHint().height() - 8)
        self.assertGreaterEqual(self.win.val_phase.height(), 16)

    # 4
    def test_live_resize_compact_to_wide_reflows_up(self):
        self._show_capture_at(1280, 720)
        self.assertEqual(self.win.capture_stats_grid.columns(), 3)
        self._show_capture_at(1600, 900)
        self._assert_capture_usable(stats_cols=6, issues_cols=5)

    # 5
    def test_live_resize_wide_to_compact_reflows_down(self):
        self._show_capture_at(1600, 900)
        self.assertEqual(self.win.capture_stats_grid.columns(), 6)
        self._show_capture_at(1280, 720)
        self.assertEqual(self.win.capture_stats_grid.columns(), 3)
        self._assert_capture_usable(stats_cols=3, issues_cols=3)

    def _resize_preserves(self, before):
        self._show_capture_at(1280, 720)
        self._show_capture_at(1600, 900)
        self.assertEqual(self._lifecycle_tuple(), before)

    # 6
    def test_ready_resize_preserves_state(self):
        self._setup_fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        before = self._lifecycle_tuple()
        self._resize_preserves(before)

    # 7
    def test_armed_resize_preserves_state(self):
        self._setup_fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        before = self._lifecycle_tuple()
        self._resize_preserves(before)

    # 8
    def test_running_resize_preserves_run_data(self):
        self._setup_fixture()
        self._start_run()
        before = (
            self.win.running,
            self.win.start_time,
            list(self.win.events),
            self.win.end_time,
            len(self.win.events),
        )
        self._show_capture_at(1280, 720)
        self._show_capture_at(1600, 900)
        self.assertEqual(
            (self.win.running, self.win.start_time, list(self.win.events), self.win.end_time, len(self.win.events)),
            before,
        )

    # 9, 10
    def test_review_resize_preserves_host_evidence_and_stays_readable(self):
        self._setup_fixture()
        self._start_run()
        self.win.stop_run()
        self.assertTrue(self.win.completed)
        snap = self.win.host_evidence_snapshot
        self.assertFalse(self.win.review_text.isVisibleTo(self.win))
        self.assertTrue(self.win.results_workspace.isVisibleTo(self.win))
        obs = self.win.results_observations_text.text()
        self.assertGreater(len(obs), 0)
        self._show_capture_at(1280, 720)
        self.assertIs(self.win.host_evidence_snapshot, snap)
        self.assertFalse(self.win.review_text.isVisibleTo(self.win))
        self.assertTrue(self.win.completed)
        self.assertGreaterEqual(self.win.test_area.height(), 280)
        self._show_capture_at(1600, 900)
        self.assertIs(self.win.host_evidence_snapshot, snap)
        self.win._show_workflow_page("results")
        self._settle()
        self.assertEqual(self.win.results_observations_text.text(), obs)
        self.assertTrue(self.win.results_workspace.isVisibleTo(self.win))

    # 11
    def test_startup_window_preset_reflows_capture_without_lifecycle_change(self):
        self.win._available_geometry = lambda: QRect(0, 0, 1920, 1040)
        self._setup_fixture()
        self.assertTrue(self.win.lock_profile())
        self.win._show_workflow_page("capture")
        before = self._lifecycle_tuple()
        self.win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("compact"))
        self._settle()
        self.assertEqual(self.win.size().width(), 1280)
        self.assertLess(self.win.capture_stats_grid.columns(), 6)
        self.win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index("large"))
        self._settle()
        self.assertEqual(self.win.size().width(), 1600)
        self.assertEqual(self.win.capture_stats_grid.columns(), 6)
        self.assertEqual(self._lifecycle_tuple(), before)

    # --- Step 3e: new preset sizes reflow naturally from window geometry ---

    def _select_preset(self, mode: str) -> None:
        self.win.startup_window_combo.setCurrentIndex(WINDOW_MODES.index(mode))
        self._settle()

    def _assert_setup_usable(self) -> None:
        self.win._show_workflow_page("setup")
        self._settle()
        grid = self.win.setup_card_grid
        self.assertEqual(
            grid.columns(),
            qt_app.ResponsiveCardGrid.columns_for_width(self.win.setup_scroll.viewport().width() - 4),
        )
        _no_pairwise_overlap(grid._cards)
        self.assertFalse(self.win.setup_scroll.horizontalScrollBar().isVisible())
        for card in grid._cards:
            self.assertGreaterEqual(card.width(), card.minimumSizeHint().width() - 2, card)

    def _assert_capture_usable_here(self) -> None:
        self.win._show_workflow_page("capture")
        self._settle()
        self._assert_capture_usable(
            stats_cols=self.win.capture_stats_grid.columns(),
            issues_cols=self.win.capture_issues_grid.columns(),
        )

    def test_laptop_1366_preset_reflows_setup_and_capture(self):
        self.win._available_geometry = lambda: QRect(0, 0, 1920, 1040)
        self.win._show_workflow_page("capture")
        self._select_preset("laptop")
        self.assertEqual((self.win.width(), self.win.height()), (1366, 768))
        self._assert_capture_usable_here()
        self.assertLess(self.win.capture_stats_grid.columns(), 6)
        self._assert_setup_usable()

    def test_large_plus_1728_preset_returns_to_wide_layout(self):
        self.win._available_geometry = lambda: QRect(0, 0, 1920, 1040)
        self.win._show_workflow_page("capture")
        self._select_preset("compact")
        self.assertEqual(self.win.capture_stats_grid.columns(), 3)
        self._select_preset("large_plus")
        self.assertEqual((self.win.width(), self.win.height()), (1728, 972))
        self._assert_capture_usable_here()
        self.assertEqual(self.win.capture_stats_grid.columns(), 6)
        self.assertEqual(self.win.capture_issues_grid.columns(), 5)
        self._assert_setup_usable()
        self.assertEqual(self.win.setup_card_grid.columns(), 3)

    def test_preset_sequence_reflows_without_restart_or_lifecycle_change(self):
        self.win._available_geometry = lambda: QRect(0, 0, 1920, 1040)
        self._setup_fixture()
        self.assertTrue(self.win.lock_profile())
        self.win._show_workflow_page("capture")
        before = self._lifecycle_tuple()
        widgets = (self.win.page_capture, self.win.test_area, self.win.capture_stats_grid)
        for mode, size in (("compact", (1280, 720)), ("large_plus", (1728, 972)), ("laptop", (1366, 768))):
            with self.subTest(mode=mode):
                self._select_preset(mode)
                self.assertEqual((self.win.width(), self.win.height()), size)
                self._assert_capture_usable_here()
                self.assertTrue(self.win.test_area.isVisibleTo(self.win))
        self.assertEqual(self._lifecycle_tuple(), before)
        self.assertEqual((self.win.page_capture, self.win.test_area, self.win.capture_stats_grid), widgets)

    def test_custom_size_reflows_capture_like_presets(self):
        self.win._available_geometry = lambda: QRect(0, 0, 1920, 1040)
        self.win._show_workflow_page("capture")
        self.assertTrue(self.win.apply_custom_window_size(1500, 820))
        self._settle()
        self.assertEqual((self.win.width(), self.win.height()), (1500, 820))
        self._assert_capture_usable_here()

    def test_full_hd_request_fits_work_area_and_capture_stays_usable(self):
        work = QRect(0, 0, 1920, 1040)
        self.win._available_geometry = lambda: QRect(work)
        self.win._show_workflow_page("capture")
        self._select_preset("full_hd")
        self.assertTrue(work.contains(self.win.frameGeometry()), self.win.frameGeometry())
        self._assert_capture_usable_here()

    # 12
    def test_manual_test_area_hit_test_after_reflow(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._show_capture_at(1280, 720)
        self.win.capture_scroll.ensureWidgetVisible(self.win.test_area, 0, 0)
        self._settle()
        visible = self.win.test_area.visibleRegion().boundingRect()
        self.assertFalse(visible.isEmpty())
        self._cursor = self.win.test_area.mapToGlobal(QPoint(visible.center().x(), visible.top() + 10))
        self.assertTrue(self.win._cursor_in_test_area())
        self._show_capture_at(1600, 900)
        self._cursor = self.win.test_area.mapToGlobal(self.win.test_area.rect().center())
        self.assertTrue(self.win._cursor_in_test_area())
        self._cursor = self.win.btn_stop.mapToGlobal(self.win.btn_stop.rect().center())
        self.assertFalse(self.win._cursor_in_test_area())

    # 13, 14
    def test_fixture_clicks_after_resize_still_honor_exclusion(self):
        self._setup_fixture()
        self._start_run()
        self.win._cursor_in_test_area = lambda: False
        self.win._cursor_over_capture_exclusion_ui = lambda: qt_app.MainWindow._cursor_over_capture_exclusion_ui(self.win)
        self._show_capture_at(1280, 720)
        self._cursor = self.win.status_label.mapToGlobal(self.win.status_label.rect().center())
        before = len(self.win.events)
        self._raw_click()
        self.assertEqual(len(self.win.events), before + 1)
        self._cursor = self.win.btn_stop.mapToGlobal(self.win.btn_stop.rect().center())
        self.assertTrue(self.win._cursor_over_capture_exclusion_ui())
        self._raw_click()
        self.assertEqual(len(self.win.events), before + 1)

    # 15
    def test_scrolled_test_area_hit_test_and_scrollbar_exclusion(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._show_capture_at(1280, 720)
        bar = self.win.capture_scroll.verticalScrollBar()
        self.assertIn(bar, self.win._capture_exclusion_widgets())
        if bar.maximum() > 0:
            bar.setValue(min(80, bar.maximum()))
            self._settle()
            self._cursor = bar.mapToGlobal(bar.rect().center())
            self.assertTrue(self.win._cursor_over_capture_exclusion_ui())
        visible = self.win.test_area.visibleRegion().boundingRect()
        self.assertFalse(visible.isEmpty())
        local = visible.center()
        self._cursor = self.win.test_area.mapToGlobal(local)
        self.assertTrue(self.win._cursor_in_test_area())


    # ── Step 3d1: scroll-aware Test Area hit-test ─────────────────────
    def _scrolled_test_area_points(self, value: int = 0) -> tuple[QPoint, QPoint]:
        """Return (clipped, visible) global points inside test_area.rect() at 1280x720."""
        self._show_capture_at(1280, 720)
        bar = self.win.capture_scroll.verticalScrollBar()
        if bar.maximum() <= 0:
            self.skipTest("Capture did not overflow vertically at 1280x720")
        bar.setValue(min(value, bar.maximum()))
        self._settle()
        area = self.win.test_area
        viewport = self.win.capture_scroll.viewport()
        top_in_vp = area.mapTo(viewport, QPoint(0, 0)).y()
        visible_top = max(0, -top_in_vp)
        visible_bottom = min(area.height(), viewport.height() - top_in_vp)
        self.assertGreater(visible_bottom - visible_top, 20, "Test Area not partially visible")
        x = area.width() // 2
        if visible_bottom < area.height() - 4:
            clipped_local = QPoint(x, area.height() - 3)
        elif visible_top > 4:
            clipped_local = QPoint(x, 2)
        else:
            self.skipTest("no clipped Test Area portion at this scroll value")
        visible_local = QPoint(x, (visible_top + visible_bottom) // 2)
        clipped = area.mapToGlobal(clipped_local)
        visible = area.mapToGlobal(visible_local)
        self.assertTrue(area.rect().contains(area.mapFromGlobal(clipped)))
        self.assertFalse(viewport.rect().contains(viewport.mapFromGlobal(clipped)))
        return clipped, visible

    # A-E
    def test_clipped_test_area_point_is_not_in_test_area(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        clipped, visible = self._scrolled_test_area_points(0)
        self.assertTrue(self.win._test_area_is_active())
        self._cursor = clipped
        self.assertFalse(self.win._cursor_in_test_area())
        self._cursor = visible
        self.assertTrue(self.win._cursor_in_test_area())

    def test_clipped_point_after_partial_scroll_is_not_in_test_area(self):
        self.assertTrue(self.win.lock_profile())
        self._show_capture_at(1280, 720)
        bar = self.win.capture_scroll.verticalScrollBar()
        if bar.maximum() < 40:
            self.skipTest("not enough vertical overflow for a partial scroll")
        clipped, visible = self._scrolled_test_area_points(bar.maximum() // 2)
        self.assertGreater(bar.value(), 0)
        self._cursor = clipped
        self.assertFalse(self.win._cursor_in_test_area())
        self._cursor = visible
        self.assertTrue(self.win._cursor_in_test_area())

    def test_hit_test_failure_still_fails_closed_with_scroll(self):
        self.assertTrue(self.win.lock_profile())
        _clipped, visible = self._scrolled_test_area_points(0)
        self._cursor = visible
        viewport = self.win.capture_scroll.viewport()

        def _boom(*_a, **_k):
            raise RuntimeError("map failure")

        viewport.mapFromGlobal = _boom
        try:
            self.assertFalse(self.win._cursor_in_test_area())
        finally:
            del viewport.mapFromGlobal

    # F
    def test_manual_armed_click_at_clipped_point_does_not_start(self):
        self.win.radio_manual.setChecked(True)
        self._lock_and_arm()
        clipped, visible = self._scrolled_test_area_points(0)
        self._cursor = clipped
        self._raw_click()
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.start_time)
        self.assertEqual(self.win.events, [])
        self.assertTrue(self.win.capture_armed)
        self._cursor = visible
        self._raw_click()
        self.assertTrue(self.win.running)
        self.assertEqual(len(self.win.events), 1)

    # G
    def test_manual_running_click_at_clipped_point_is_not_recorded(self):
        self.win.radio_manual.setChecked(True)
        self._lock_and_arm()
        clipped, visible = self._scrolled_test_area_points(0)
        self._cursor = visible
        self._raw_click()
        self.assertTrue(self.win.running)
        self.assertEqual(len(self.win.events), 1)
        self._cursor = clipped
        self._raw_click()
        self.assertEqual(len(self.win.events), 1)
        self._cursor = visible
        self._raw_click()
        self.assertEqual(len(self.win.events), 2)

    # H, I
    def test_fixture_after_scroll_clipped_point_goes_through_ui_exclusion(self):
        self._setup_fixture()
        self._start_run()
        self.win._cursor_in_test_area = lambda: qt_app.MainWindow._cursor_in_test_area(self.win)
        self.win._cursor_over_capture_exclusion_ui = (
            lambda: qt_app.MainWindow._cursor_over_capture_exclusion_ui(self.win)
        )
        clipped, _visible = self._scrolled_test_area_points(0)

        self._cursor = clipped
        self.assertFalse(self.win._cursor_in_test_area())
        excluded = self.win._cursor_over_capture_exclusion_ui()
        before = len(self.win.events)
        self._raw_click()
        self.assertEqual(len(self.win.events), before if excluded else before + 1)

        btn = self.win.btn_stop
        viewport = self.win.capture_scroll.viewport()
        self.assertTrue(btn.isVisibleTo(self.win))
        center = btn.mapToGlobal(btn.rect().center())
        self.assertTrue(viewport.rect().contains(viewport.mapFromGlobal(center)))
        self._cursor = center
        self.assertFalse(self.win._cursor_in_test_area())
        self.assertTrue(self.win._cursor_over_capture_exclusion_ui())
        before = len(self.win.events)
        self._raw_click()
        self.assertEqual(len(self.win.events), before)

        bar = self.win.capture_scroll.verticalScrollBar()
        self._cursor = bar.mapToGlobal(bar.rect().center())
        self.assertTrue(self.win._cursor_over_capture_exclusion_ui())
        self._raw_click()
        self.assertEqual(len(self.win.events), before)
        self.assertTrue(self.win.running)


if __name__ == "__main__":
    unittest.main()
