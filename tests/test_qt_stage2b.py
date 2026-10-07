"""Stage 2B: Capture toolbar, Interval Trend fill, Click Data elapsed sort."""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolButton

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.completed_result import build_completed_result_model
from mouse_click_stability_analyzer.duration import format_elapsed_axis_tick, format_elapsed_hms
from mouse_click_stability_analyzer.i18n import STRINGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.charts import (
    HistogramChart,
    IntervalChart,
    elapsed_viewport,
    nice_ticks,
)
from mouse_click_stability_analyzer.qt_shell.styles import chart_nav_icon


def _make_qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class CaptureToolbarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()
        self.win.ensure_raw_input = lambda: None

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_chart_nav_are_compact_icon_buttons(self):
        for btn in (
            self.win.btn_chart_fit, self.win.btn_chart_zoom_in,
            self.win.btn_chart_zoom_out, self.win.btn_chart_reset,
        ):
            self.assertIsInstance(btn, QToolButton)
            self.assertEqual(btn.objectName(), "ChartNav")
            self.assertTrue(btn.toolTip())
            self.assertTrue(btn.accessibleName())
            self.assertLessEqual(btn.width() or btn.minimumWidth() or 32, 40)
        self.assertEqual(self.win.btn_chart_fit.toolTip(), STRINGS["en"]["viz_fit_data"])
        self.assertEqual(self.win.btn_chart_reset.accessibleName(), STRINGS["en"]["viz_reset_view"])
        self.assertTrue(self.win.btn_chart_fit.text())
        for name in ("fit", "zoom_in", "zoom_out", "reset"):
            self.assertFalse(chart_nav_icon(name).isNull())

    def test_fit_and_reset_remain_distinct(self):
        fit = inspect.getsource(IntervalChart.fit_data)
        reset = inspect.getsource(IntervalChart.reset_view)
        self.assertIn("autofit_bounds", fit)
        self.assertIn("zoom_locked = False", fit)
        self.assertIn("_user_view = home", reset)
        self.assertIn("zoom_locked = True", reset)
        self.assertNotEqual(fit, reset)


class IntervalTrendTests(unittest.TestCase):
    def test_paint_has_no_area_fill(self):
        src = inspect.getsource(IntervalChart.paintEvent)
        self.assertNotIn("fillPath", src)
        self.assertNotIn("interval_fill", src)
        self.assertIn("drawPath", src)
        guides = inspect.getsource(IntervalChart._draw_horizontal_guides)
        self.assertIn("DashLine", guides)
        self.assertNotIn("fillPath", guides)

    def test_manual_has_no_reference_without_target(self):
        chart = IntervalChart()
        chart.factual_guides = True
        chart.measurement_only_presentation = True
        chart.target_beat_ms = None
        self.assertEqual(chart._guide_legend_items(), [])
        chart.target_beat_ms = 25.0
        labels = [label for _color, label in chart._guide_legend_items()]
        self.assertEqual(labels, ["Configured reference"])


class ClickDataElapsedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_elapsed_display_and_numeric_sort(self):
        self.win._populate_click_table({"click_data": [
            {"index": 1, "elapsed_ms": 3_600_000.0, "button": "Left", "interval_ms": 10.0,
             "hold_ms": 8.0, "state": "ON_CADENCE", "tags": [], "reference_delta_ms": None},
            {"index": 2, "elapsed_ms": 18_006.0, "button": "Left", "interval_ms": 10.0,
             "hold_ms": 8.0, "state": "ON_CADENCE", "tags": [], "reference_delta_ms": None},
            {"index": 3, "elapsed_ms": 93_784_567.0, "button": "Left", "interval_ms": 10.0,
             "hold_ms": 8.0, "state": "ON_CADENCE", "tags": [], "reference_delta_ms": None},
        ]})
        table = self.win.results_click_table
        self.assertEqual(table.horizontalHeaderItem(1).text(), STRINGS["en"]["col_elapsed"])
        self.assertEqual(table.item(0, 1).text(), format_elapsed_hms(3_600_000))
        self.assertEqual(table.item(1, 1).text(), format_elapsed_hms(18_006))
        self.assertEqual(table.item(2, 1).text(), "26:03:04.567")
        self.assertEqual(table.item(0, 1).data(Qt.ItemDataRole.UserRole), 3_600_000.0)
        self.win._set_click_sort("elapsed_ms", False)
        texts = [table.item(r, 1).text() for r in range(3)]
        self.assertEqual(texts, [
            format_elapsed_hms(18_006),
            format_elapsed_hms(3_600_000),
            "26:03:04.567",
        ])
        roles = [table.item(r, 1).data(Qt.ItemDataRole.UserRole) for r in range(3)]
        self.assertEqual(roles, [18_006.0, 3_600_000.0, 93_784_567.0])


RUN_DURATION_CASES = (
    (20.1, "00:00:20.100"),
    (3600.0, "01:00:00.000"),
    (93_784.567, "26:03:04.567"),
)


class RunDurationDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        cls._tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()
        self.win.ensure_raw_input = lambda: None

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_live_capture_time_uses_human_duration(self):
        start = 1000.0
        for seconds, expected in RUN_DURATION_CASES:
            with self.subTest(seconds=seconds):
                now = start + seconds
                self.win.running = True
                self.win.start_time = start
                self.win.end_time = None
                self.win._last_metric_ts = now
                with mock.patch.object(qt_app.time, "perf_counter", return_value=now):
                    self.win._tick()
                text = self.win.val_time.text()
                self.assertEqual(text, expected)
                self.assertNotIn(f"{seconds:.1f}s", text)
        self.win.running = False

    def test_completed_capture_time_uses_human_duration(self):
        src = inspect.getsource(qt_app.MainWindow.stop_run)
        self.assertIn("format_elapsed_seconds_hms", src)
        self.assertNotIn(':.1f}s"', src)

    def test_results_run_context_uses_human_duration(self):
        for seconds, expected in RUN_DURATION_CASES:
            with self.subTest(seconds=seconds):
                model = build_completed_result_model(
                    locked={"manual_mode": True, "focus_button": "Left", "profile_name": "Manual"},
                    events=[], run_id="ctx", target="T", start_time=0.0, stop_time=seconds,
                )
                self.assertEqual(model["run"]["elapsed_s"], seconds)
                text = self.win._format_run_context(model)
                self.assertIn(expected, text)
                self.assertNotIn(f"{seconds:.1f} s", text)


class ElapsedViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()

    def _chart(self, series, *, data_aware=True):
        chart = IntervalChart()
        chart.set_data_aware_fit(data_aware)
        chart.resize(600, 300)
        chart.set_series(series)
        return chart

    def test_short_elapsed_near_zero_never_negative(self):
        series = [(0.0, 100.0), (120.0, 120.0), (260.0, 140.0)]
        before = list(series)
        chart = self._chart(series)
        xmin, xmax, _ymin, _ymax = chart.autofit_bounds()
        self.assertGreaterEqual(xmin, 0.0)
        self.assertGreater(xmax, 260.0)
        ticks = nice_ticks(xmin, xmax)
        self.assertTrue(all(t >= 0.0 for t in ticks), ticks)
        chart.fit_data()
        self.assertGreaterEqual(chart.visible_bounds()[0], 0.0)
        chart.zoom_out()
        chart.zoom_out()
        self.assertGreaterEqual(chart.visible_bounds()[0], 0.0)
        chart.reset_view()
        self.assertGreaterEqual(chart.visible_bounds()[0], 0.0)
        self.assertGreaterEqual(chart.navigation_envelope()[0], 0.0)
        self.assertEqual(chart.series, before)
        self.assertEqual(series, before)

    def test_later_elapsed_keeps_padding(self):
        series = [(60_000.0, 100.0), (60_100.0, 101.0), (60_200.0, 99.0)]
        chart = self._chart(series)
        xmin, xmax, _ymin, _ymax = chart.autofit_bounds()
        self.assertLess(xmin, 60_000.0)
        self.assertGreater(xmax, 60_200.0)
        self.assertGreater(xmin, 0.0)

    def test_results_fit_never_negative(self):
        chart = self._chart([(0.0, 25.0), (25.0, 25.0)], data_aware=False)
        self.assertGreaterEqual(chart.autofit_bounds()[0], 0.0)

    def test_viewport_helper(self):
        self.assertEqual(elapsed_viewport(-510.0, 4_000.0), (0.0, 4_510.0))
        self.assertEqual(elapsed_viewport(100.0, 200.0), (100.0, 200.0))


class HistogramAxisLabelTests(unittest.TestCase):
    def test_qt_histogram_y_axis_is_count(self):
        src = inspect.getsource(HistogramChart.paintEvent)
        self.assertIn('"axis_count"', src)
        self.assertNotIn('"clicks"', src)
        self.assertEqual(STRINGS["en"]["axis_count"], "Count")
        self.assertIn('"axis_count"', inspect.getsource(qt_app.MainWindow._chart_labels))


class AxisTickTests(unittest.TestCase):
    def test_representative_spans(self):
        self.assertEqual(format_elapsed_axis_tick(10_000, span_ms=20_000), "10.0")
        self.assertEqual(format_elapsed_axis_tick(125_000, span_ms=180_000), "2:05")
        self.assertEqual(format_elapsed_axis_tick(3_661_000, span_ms=7_200_000), "1:01:01")


if __name__ == "__main__":
    unittest.main()
