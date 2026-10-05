"""Phase 4D-2f: Capture visualization is a single-chart screening workspace."""
from __future__ import annotations

import copy
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, Qt

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.charts import (
    IntervalChart,
    ScatterChart,
    fitted_range,
)

_T0 = 1000.0
_CLUSTER = [
    (162.0, 80.0, "ON_CADENCE", 2),
    (175.0, 85.0, "ON_CADENCE", 3),
    (190.0, 90.0, "ON_CADENCE", 4),
]
_CLUSTER_SERIES = [(0.0, 162.0), (200.0, 175.0), (400.0, 190.0)]
_I18N_KEYS = (
    "chart_stability_map",
    "chart_stability_map_subtitle",
    "chart_stability_map_subtitle_fixture",
    "chart_interval_trend",
    "viz_stability_map",
    "viz_interval_trend",
    "viz_fit_data",
    "viz_zoom_in",
    "viz_zoom_out",
    "viz_reset_view",
    "legend_association_window",
    "legend_configured_reference",
    "hover_click",
    "hover_interval",
    "hover_hold",
    "hover_interval_delta",
)


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


def _finite_tuple(values) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in values)


class FittedRangeTests(unittest.TestCase):
    def test_empty_is_finite(self):
        lo, hi = fitted_range([])
        self.assertTrue(_finite_tuple((lo, hi)))
        self.assertGreater(hi, lo)

    def test_single_value_uses_min_span(self):
        lo, hi = fitted_range([180.0], min_span=8.0)
        self.assertLessEqual(lo, 180.0)
        self.assertGreaterEqual(hi, 180.0)
        self.assertGreaterEqual(hi - lo, 8.0)

    def test_identical_values_do_not_collapse(self):
        lo, hi = fitted_range([180.0, 180.0], min_span=8.0)
        self.assertGreater(hi, lo)
        self.assertTrue(_finite_tuple((lo, hi)))

    def test_cluster_does_not_anchor_at_zero(self):
        lo, hi = fitted_range([162.0, 175.0, 190.0], extra=[166.67, 164.67, 168.67], min_span=8.0)
        self.assertGreater(lo, 50.0)
        self.assertLessEqual(lo, 162.0)
        self.assertGreaterEqual(hi, 190.0)


class ChartWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        if cls._qapp is None:
            raise unittest.SkipTest("PySide6 QApplication unavailable")

    def setUp(self):
        self.scatter = ScatterChart()
        self.scatter.set_data_aware_fit(True)
        self.scatter.resize(640, 400)
        self.interval = IntervalChart()
        self.interval.set_data_aware_fit(True)
        self.interval.resize(640, 400)

    def tearDown(self):
        self.scatter.deleteLater()
        self.interval.deleteLater()
        self._qapp.processEvents()

    def test_scatter_autofit_includes_cluster_and_skips_zero(self):
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67, association_half_width_ms=2.0)
        xmin, xmax, ymin, ymax = self.scatter.visible_bounds()
        self.assertGreater(xmin, 50.0)
        for x, y, *_rest in _CLUSTER:
            self.assertLessEqual(xmin, x)
            self.assertGreaterEqual(xmax, x)
            self.assertLessEqual(ymin, y)
            self.assertGreaterEqual(ymax, y)
        self.assertLessEqual(xmin, 164.67)
        self.assertGreaterEqual(xmax, 168.67)
        self.assertTrue(_finite_tuple((xmin, xmax, ymin, ymax)))

    def test_hold_autofit_fits_displayed_holds(self):
        self.scatter.set_points(_CLUSTER)
        _xmin, _xmax, ymin, ymax = self.scatter.visible_bounds()
        self.assertLessEqual(ymin, 80.0)
        self.assertGreaterEqual(ymax, 90.0)
        self.assertGreater(ymin, -20.0)

    def test_fixture_reference_and_band_are_represented(self):
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67, association_half_width_ms=2.0)
        self.assertEqual(self.scatter.target_beat_ms, 166.67)
        self.assertEqual(self.scatter.association_window(), (164.67, 168.67))
        points_before = list(self.scatter.points)
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67, association_half_width_ms=20.0)
        self.assertEqual(self.scatter.points, points_before)
        self.assertEqual(self.scatter.association_window(), (146.67, 186.67))

    def test_manual_does_not_invent_fixture_guides(self):
        self.scatter.set_points(_CLUSTER, target_beat_ms=None, association_half_width_ms=None)
        self.assertIsNone(self.scatter.target_beat_ms)
        self.assertIsNone(self.scatter.association_window())
        self.interval.set_series(_CLUSTER_SERIES, target_beat_ms=None, association_half_width_ms=None)
        self.assertIsNone(self.interval.target_beat_ms)
        self.assertIsNone(self.interval.association_window())

    def test_interval_trend_y_fits_cluster(self):
        self.interval.set_series(_CLUSTER_SERIES, target_beat_ms=166.67, association_half_width_ms=2.0)
        xmin, xmax, ymin, ymax = self.interval.visible_bounds()
        self.assertGreater(ymin, 40.0)
        for x, y in _CLUSTER_SERIES:
            self.assertLessEqual(xmin, x)
            self.assertGreaterEqual(xmax, x)
            self.assertLessEqual(ymin, y)
            self.assertGreaterEqual(ymax, y)
        self.assertLessEqual(ymin, 164.67)
        self.assertGreaterEqual(ymax, 168.67)

    def test_empty_and_single_point_are_safe(self):
        self.scatter.set_points([])
        self.scatter.repaint()
        empty = self.scatter.autofit_bounds()
        self.assertIsNotNone(empty)
        self.assertTrue(_finite_tuple(empty))
        self.assertGreater(empty[1], empty[0])
        self.scatter.set_points([(180.0, 80.0, "ON_CADENCE")])
        self.scatter.repaint()
        bounds = self.scatter.visible_bounds()
        self.assertTrue(_finite_tuple(bounds))
        self.assertLessEqual(bounds[0], 180.0)
        self.assertGreaterEqual(bounds[1], 180.0)
        self.interval.set_series([])
        self.interval.repaint()
        self.interval.set_series([(100.0, 180.0)])
        self.interval.repaint()
        ib = self.interval.visible_bounds()
        self.assertTrue(_finite_tuple(ib))
        self.assertGreater(ib[1], ib[0])
        self.assertGreater(ib[3], ib[2])

    def test_identical_axes_keep_finite_span(self):
        self.scatter.set_points([(180.0, 80.0, "ON_CADENCE"), (180.0, 80.0, "ON_CADENCE")])
        xmin, xmax, ymin, ymax = self.scatter.visible_bounds()
        self.assertGreater(xmax, xmin)
        self.assertGreater(ymax, ymin)
        self.assertTrue(_finite_tuple((xmin, xmax, ymin, ymax)))

    def test_zoom_changes_only_visible_range(self):
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67, association_half_width_ms=2.0)
        source = list(self.scatter.points)
        auto = self.scatter.visible_bounds()
        self.scatter.zoom_in()
        zoomed = self.scatter.visible_bounds()
        self.assertTrue(self.scatter.zoom_locked)
        self.assertLess(zoomed[1] - zoomed[0], auto[1] - auto[0])
        self.assertEqual(self.scatter.points, source)
        self.scatter.zoom_out()
        out = self.scatter.visible_bounds()
        self.assertGreater(out[1] - out[0], zoomed[1] - zoomed[0])
        self.assertEqual(self.scatter.points, source)
        self.scatter.fit_data()
        self.assertFalse(self.scatter.zoom_locked)
        self.assertEqual(self.scatter.visible_bounds(), auto)
        self.scatter.zoom_in()
        self.scatter.reset_view()
        self.assertFalse(self.scatter.zoom_locked)
        self.assertEqual(self.scatter.visible_bounds(), auto)
        self.assertEqual(self.scatter.points, source)

    def test_hover_inspection_is_factual(self):
        self.scatter.show()
        self._qapp.processEvents()
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67, association_half_width_ms=2.0)
        mapped = self.scatter._maps()
        self.assertIsNotNone(mapped)
        _plot, _bounds, map_x, map_y = mapped
        pos = QPoint(int(map_x(175.0)), int(map_y(85.0)))
        info = self.scatter.nearest_observation(pos)
        self.assertIsNotNone(info)
        self.assertEqual(info["index"], 3)
        self.assertAlmostEqual(info["interval_ms"], 175.0)
        self.assertAlmostEqual(info["hold_ms"], 85.0)

    def test_results_legacy_charts_still_anchor_at_zero(self):
        legacy = ScatterChart()
        legacy.resize(400, 300)
        legacy.set_points(_CLUSTER)
        xmin, xmax, ymin, ymax = legacy.visible_bounds()
        self.assertEqual(xmin, 0.0)
        self.assertEqual(ymin, 0.0)
        self.assertGreater(xmax, 190.0)
        legacy.deleteLater()


class CaptureVisualizationTests(unittest.TestCase):
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

    def _show_capture(self):
        self.win._show_workflow_page("capture")
        self._settle()

    def _viz_controls(self):
        return [
            self.win.btn_view_stability,
            self.win.btn_view_interval,
            self.win.btn_chart_fit,
            self.win.btn_chart_zoom_in,
            self.win.btn_chart_zoom_out,
            self.win.btn_chart_reset,
        ]

    def _fixture(self, *, hz="6", tol="2"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tol)
        self.win.auto_stop_off.setChecked(True)

    def _lock_and_arm(self):
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._t = float(self.win._arm_boundary_perf) + 0.001

    def _start_run(self, *, in_test_area=True):
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self.win._cursor_in_test_area = lambda: in_test_area
        self._lock_and_arm()
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        self._settle()

    def _raw_click(self, button="Left"):
        base = {"capture_source": "windows_raw_input", "button": button, "device_source": "dut"}
        self.win._on_raw_event_ui({**base, "event_type": "down", "time_perf": self._t})
        self.win._on_raw_event_ui({**base, "event_type": "up", "time_perf": self._t + 0.01})
        self._t += 0.180

    def _point_at(self, widget):
        self._settle()
        self.assertTrue(widget.isVisibleTo(self.win), widget)
        self._cursor = widget.mapToGlobal(widget.rect().center())

    def _snapshot(self):
        return (
            self.win._lifecycle_state(),
            self.win.capture_armed,
            self.win.running,
            self.win.completed,
            copy.deepcopy(self.win.events),
            copy.deepcopy(self.win.locked),
            copy.deepcopy(self.win.profile_locked_settings),
            self.win.host_evidence_snapshot,
            self.win.val_verdict.text(),
        )

    def test_default_view_is_stability_map_only(self):
        self._show_capture()
        self.assertEqual(self.win._capture_view, "stability")
        self.assertEqual(self.win.capture_chart_stack.currentIndex(), 0)
        self.assertTrue(self.win.btn_view_stability.isChecked())
        self.assertFalse(self.win.btn_view_interval.isChecked())
        self.assertTrue(self.win.scatter.isVisible())
        self.assertFalse(self.win.interval_chart.isVisible())
        self.assertTrue(self.win.scatter.data_aware_fit)
        self.assertTrue(self.win.interval_chart.data_aware_fit)

    def test_view_selector_does_not_mutate_run_state(self):
        self._start_run()
        self._raw_click()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        before = self._snapshot()
        scatter_zoom = self.win.scatter.visible_bounds()
        self.win.btn_view_interval.click()
        self._settle()
        self.assertEqual(self.win._capture_view, "interval")
        self.assertTrue(self.win.interval_chart.isVisible())
        self.assertFalse(self.win.scatter.isVisible())
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.win.scatter.visible_bounds(), scatter_zoom)
        self.win.btn_view_stability.click()
        self._settle()
        self.assertEqual(self.win._capture_view, "stability")
        self.assertTrue(self.win.scatter.isVisible())
        self.assertFalse(self.win.interval_chart.isVisible())
        self.assertEqual(self._snapshot(), before)

    def test_results_charts_remain_legacy_and_multi_view(self):
        self.assertFalse(self.win.results_scatter.data_aware_fit)
        self.assertFalse(self.win.results_interval_chart.data_aware_fit)
        self.assertGreaterEqual(self.win.results_chart_stack.count(), 3)

    def test_live_refresh_preserves_manual_zoom(self):
        self._start_run()
        self._raw_click()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self.assertGreaterEqual(len(self.win.scatter.points), 1)
        self.win.scatter.zoom_in()
        bounds = self.win.scatter.visible_bounds()
        source = list(self.win.scatter.points)
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self.assertTrue(self.win.scatter.zoom_locked)
        self.assertEqual(self.win.scatter.visible_bounds(), bounds)
        self.assertGreaterEqual(len(self.win.scatter.points), len(source))

    def test_new_run_clears_charts_and_resets_view(self):
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self.win.btn_view_interval.click()
        self.win.interval_chart.zoom_in()
        self.assertTrue(self.win.interval_chart.zoom_locked)
        self.win.running = False
        self.win.completed = True
        self.win.new_run()
        self._settle()
        self.assertEqual(self.win._capture_view, "stability")
        self.assertEqual(self.win.scatter.points, [])
        self.assertEqual(self.win.interval_chart.series, [])
        self.assertFalse(self.win.scatter.zoom_locked)
        self.assertFalse(self.win.interval_chart.zoom_locked)
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertIsNotNone(self.win.profile_locked_settings)

    def test_start_capture_cancel_start_unchanged(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertTrue(self.win.arm_capture())
        self.assertEqual(self.win._lifecycle_state(), "armed")
        self.assertIn("Cancel", self.win.btn_arm.text())
        self.win.btn_arm.click()
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertFalse(self.win.capture_armed)
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])
        self.assertIsNotNone(self.win.profile_locked_settings)

    def test_fixture_refresh_uses_locked_association_not_setup_edit(self):
        self._fixture(tol="2")
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        events_before = copy.deepcopy(self.win.events)
        status_before = self.win.val_verdict.text()
        self.assertEqual(self.win.scatter.association_window(), (
            self.win.scatter.target_beat_ms - 2.0,
            self.win.scatter.target_beat_ms + 2.0,
        ))
        self.win.timing_tol_edit.setText("20")
        self.win._refresh_metrics(final=False)
        self.assertEqual(self.win.events, events_before)
        self.assertEqual(self.win.val_verdict.text(), status_before)
        self.assertEqual(self.win.scatter.association_half_width_ms, 2.0)

    def test_manual_run_does_not_draw_fixture_guides(self):
        self.win.radio_manual.setChecked(True)
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self.assertIsNone(self.win.scatter.target_beat_ms)
        self.assertIsNone(self.win.scatter.association_window())
        self.assertIsNone(self.win.interval_chart.target_beat_ms)
        self.assertIsNone(self.win.interval_chart.association_window())
        self.assertEqual(self.win.scatter.subtitle, self.win._tr("chart_stability_map_subtitle"))

    def test_fixture_titles_are_factual(self):
        self._fixture(hz="6", tol="2")
        self._start_run()
        self.win._refresh_metrics(final=False)
        self.assertEqual(self.win.scatter.title, "Click Stability Map")
        self.assertIn("Reference", self.win.scatter.subtitle)
        self.assertNotIn("PASS", self.win.scatter.subtitle)
        self.assertNotIn("specification", self.win.scatter.subtitle.lower())
        self.assertEqual(self.win.interval_chart.title, "Interval Trend")

    def test_toolbar_is_outside_test_area(self):
        self._show_capture()
        self.assertFalse(self.win.test_area.isAncestorOf(self.win.capture_viz_toolbar))
        for widget in self._viz_controls():
            self.assertFalse(self.win.test_area.isAncestorOf(widget), widget)
            self.assertTrue(self.win.capture_viz_toolbar.isAncestorOf(widget) or widget is self.win.capture_viz_toolbar)
        self.assertTrue(self.win.test_area.isAncestorOf(self.win.scatter))
        self.assertTrue(self.win.test_area.isAncestorOf(self.win.interval_chart))

    def test_manual_viz_controls_cannot_become_t0(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._t = float(self.win._arm_boundary_perf) + 0.001
        self._show_capture()
        for widget in self._viz_controls():
            with self.subTest(widget=widget.text()):
                self._point_at(widget)
                self.assertFalse(qt_app.MainWindow._cursor_in_test_area(self.win), widget)
                self._raw_click()
                self.assertFalse(self.win.running, widget)
                self.assertIsNone(self.win.start_time)
                self.assertEqual(self.win.events, [])

    def test_fixture_viz_controls_cannot_become_measurement(self):
        self._fixture()
        self._start_run()
        self.win._cursor_over_capture_exclusion_ui = lambda: qt_app.MainWindow._cursor_over_capture_exclusion_ui(self.win)
        self.win._cursor_in_test_area = lambda: False
        before = len(self.win.events)
        running = self.win.running
        for widget in self._viz_controls() + [self.win.capture_viz_toolbar]:
            with self.subTest(widget=getattr(widget, "text", lambda: widget.objectName())()):
                self._point_at(widget)
                self.assertTrue(self.win._cursor_over_capture_exclusion_ui(), widget)
                self._raw_click()
                self.assertEqual(len(self.win.events), before, widget)
                self.assertEqual(self.win.running, running)

    def test_zoom_buttons_do_not_mutate_measurements(self):
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        before = self._snapshot()
        self.win.btn_chart_zoom_in.click()
        self.win.btn_chart_zoom_out.click()
        self.win.btn_chart_fit.click()
        self.win.btn_chart_reset.click()
        self.assertEqual(self._snapshot(), before)

    def test_i18n_keys_exist(self):
        for lang in SUPPORTED_LANGS:
            for key in _I18N_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(STRINGS[lang].get(key) or "").strip())
        self.assertEqual(STRINGS["en"]["chart_stability_map"], "Click Stability Map")
        self.assertEqual(STRINGS["en"]["chart_interval_trend"], "Interval Trend")
        self.assertNotIn("PASS zone", STRINGS["en"]["legend_association_window"])


if __name__ == "__main__":
    unittest.main()
