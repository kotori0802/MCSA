"""Phase 4D-2f: Capture visualization is a single-chart screening workspace."""
from __future__ import annotations

import copy
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.charts import (
    AXIS_CONTEXT,
    AXIS_ELAPSED,
    IntervalChart,
    NAV_CONTEXT_FACTOR,
    ScatterChart,
    WHEEL_ANGLE_NOTCH,
    WHEEL_MAX_STEPS_PER_EVENT,
    ZOOM_IN_FACTOR,
    axis_navigation_envelope,
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
    "legend_configured_reference",
    "legend_on_cadence",
    "legend_extra",
    "legend_chatter",
    "legend_miss",
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


def _wheel_event(widget, local, *, angle=0, pixel=0):
    pos = QPointF(local)
    global_pos = QPointF(widget.mapToGlobal(pos.toPoint()))
    return QWheelEvent(
        pos,
        global_pos,
        QPoint(0, int(pixel)),
        QPoint(0, int(angle)),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def _send_wheel(widget, local, *, angle=0, pixel=0):
    event = _wheel_event(widget, local, angle=angle, pixel=pixel)
    QApplication.sendEvent(widget, event)
    return event


def _plot_anchor_pixel(chart, *, fx=0.25, fy=0.3):
    plot = chart._plot_rect()
    return QPointF(
        plot.left() + plot.width() * fx,
        plot.top() + plot.height() * fy,
    )


def _drag(chart, start, end):
    sp = QPoint(int(QPointF(start).x()), int(QPointF(start).y()))
    ep = QPoint(int(QPointF(end).x()), int(QPointF(end).y()))
    QTest.mousePress(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, sp)
    QTest.mouseMove(chart, ep)
    QTest.mouseRelease(chart, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ep)


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


class NavigationEnvelopeTests(unittest.TestCase):
    def test_context_envelope_contains_content_and_stays_near_zero_floor(self):
        lo, hi = axis_navigation_envelope(150.0, 200.0, min_span=8.0, kind=AXIS_CONTEXT)
        self.assertLessEqual(lo, 150.0)
        self.assertGreaterEqual(hi, 200.0)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi - lo, (50.0 * NAV_CONTEXT_FACTOR) + 1e-6)

    def test_elapsed_envelope_uses_duration_not_context_factor(self):
        lo, hi = axis_navigation_envelope(-4.0, 400.0, min_span=500.0, kind=AXIS_ELAPSED, duration_ms=10000.0)
        self.assertEqual(lo, -4.0)
        self.assertGreaterEqual(hi, 10000.0)
        self.assertLess(hi, 10000.0 * NAV_CONTEXT_FACTOR)

    def test_negative_factual_content_is_not_clipped(self):
        lo, hi = axis_navigation_envelope(-40.0, 10.0, min_span=8.0, kind=AXIS_CONTEXT)
        self.assertLessEqual(lo, -40.0)
        self.assertGreaterEqual(hi, 10.0)


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
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67)
        xmin, xmax, ymin, ymax = self.scatter.visible_bounds()
        self.assertGreater(xmin, 50.0)
        for x, y, *_rest in _CLUSTER:
            self.assertLessEqual(xmin, x)
            self.assertGreaterEqual(xmax, x)
            self.assertLessEqual(ymin, y)
            self.assertGreaterEqual(ymax, y)
        self.assertLessEqual(xmin, 166.67)
        self.assertGreaterEqual(xmax, 166.67)
        self.assertTrue(_finite_tuple((xmin, xmax, ymin, ymax)))

    def test_hold_autofit_fits_displayed_holds(self):
        self.scatter.set_points(_CLUSTER)
        _xmin, _xmax, ymin, ymax = self.scatter.visible_bounds()
        self.assertLessEqual(ymin, 80.0)
        self.assertGreaterEqual(ymax, 90.0)
        self.assertGreater(ymin, -20.0)

    def test_fixture_reference_line_is_the_only_guide(self):
        for chart, load in (
            (self.scatter, lambda ref: self.scatter.set_points(_CLUSTER, target_beat_ms=ref)),
            (self.interval, lambda ref: self.interval.set_series(_CLUSTER_SERIES, target_beat_ms=ref)),
        ):
            with self.subTest(chart=type(chart).__name__):
                load(166.67)
                self.assertEqual(chart.target_beat_ms, 166.67)
                self.assertFalse(hasattr(chart, "association_window"))
                self.assertFalse(hasattr(chart, "association_half_width_ms"))
                labels = [label for _color, label in chart._guide_legend_items()]
                self.assertEqual(labels, ["Reference interval"])

    def test_capture_charts_render_reference_line_without_association_band(self):
        ref = 166.67
        for chart, load, vertical in (
            (self.scatter, lambda r: self.scatter.set_points(_CLUSTER, target_beat_ms=r), True),
            (self.interval, lambda r: self.interval.set_series(_CLUSTER_SERIES, target_beat_ms=r), False),
        ):
            with self.subTest(chart=type(chart).__name__):
                load(None)
                bare = chart.grab().toImage()
                load(ref)
                guided = chart.grab().toImage()
                plot = chart._plot_rect()
                bounds = chart.visible_bounds()
                anchor = chart.pixel_at_data(ref if vertical else bounds[0], (bounds[2] + bounds[3]) / 2 if vertical else ref)
                self.assertIsNotNone(anchor)
                line_pos = anchor.x() if vertical else anchor.y()
                # A band spans the plot perpendicular to its axis; count changed pixels per
                # column (vertical guide) or row (horizontal guide) below the in-plot legend.
                below_legend = int(plot.top() + plot.height() * 0.4)
                xs = range(int(plot.left()) + 2, int(plot.right()) - 1)
                ys = range(below_legend, int(plot.bottom()) - 1)
                counts: dict[int, int] = {}
                for x in xs:
                    for y in ys:
                        if bare.pixel(x, y) != guided.pixel(x, y):
                            key = x if vertical else y
                            counts[key] = counts.get(key, 0) + 1
                span = len(ys) if vertical else len(xs)
                full = [pos for pos, n in counts.items() if n >= span * 0.5]
                self.assertTrue(full, "configured reference line must be drawn")
                for pos in full:
                    self.assertLessEqual(abs(pos - line_pos), 3.0, pos)

    def test_manual_does_not_invent_fixture_guides(self):
        self.scatter.set_points(_CLUSTER, target_beat_ms=None)
        self.assertIsNone(self.scatter.target_beat_ms)
        self.assertEqual(self.scatter._guide_legend_items(), [])
        self.interval.set_series(_CLUSTER_SERIES, target_beat_ms=None)
        self.assertIsNone(self.interval.target_beat_ms)
        self.assertEqual(self.interval._guide_legend_items(), [])

    def test_interval_trend_y_fits_cluster(self):
        self.interval.set_series(_CLUSTER_SERIES, target_beat_ms=166.67)
        xmin, xmax, ymin, ymax = self.interval.visible_bounds()
        self.assertGreater(ymin, 40.0)
        for x, y in _CLUSTER_SERIES:
            self.assertLessEqual(xmin, x)
            self.assertGreaterEqual(xmax, x)
            self.assertLessEqual(ymin, y)
            self.assertGreaterEqual(ymax, y)
        self.assertLessEqual(ymin, 166.67)
        self.assertGreaterEqual(ymax, 166.67)

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
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67)
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
        self.assertTrue(self.scatter.zoom_locked)
        self.assertEqual(self.scatter.visible_bounds(), auto)
        self.assertEqual(self.scatter.points, source)

    def test_wheel_inside_plot_zooms_and_accepts(self):
        self.scatter.show()
        self._qapp.processEvents()
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67)
        before = self.scatter.visible_bounds()
        pos = _plot_anchor_pixel(self.scatter)
        event = _send_wheel(self.scatter, pos, angle=WHEEL_ANGLE_NOTCH)
        self.assertTrue(event.isAccepted())
        after = self.scatter.visible_bounds()
        self.assertTrue(self.scatter.zoom_locked)
        self.assertAlmostEqual((after[1] - after[0]) / (before[1] - before[0]), ZOOM_IN_FACTOR, places=6)
        self.assertEqual(self.scatter.points, list(_CLUSTER))

    def test_wheel_outside_plot_does_not_zoom_and_ignores(self):
        self.scatter.show()
        self._qapp.processEvents()
        self.scatter.set_points(_CLUSTER)
        before = self.scatter.visible_bounds()
        title = QPointF(self.scatter.width() / 2.0, 8.0)
        self.assertFalse(self.scatter._plot_rect().contains(title))
        event = _send_wheel(self.scatter, title, angle=WHEEL_ANGLE_NOTCH)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.scatter.visible_bounds(), before)
        self.assertFalse(self.scatter.zoom_locked)

    def test_wheel_keeps_cursor_data_under_pixel(self):
        for chart, load in (
            (self.scatter, lambda: self.scatter.set_points(_CLUSTER, target_beat_ms=166.67)),
            (self.interval, lambda: self.interval.set_series(_CLUSTER_SERIES, target_beat_ms=166.67)),
        ):
            with self.subTest(chart=type(chart).__name__):
                chart.show()
                self._qapp.processEvents()
                load()
                pos = _plot_anchor_pixel(chart, fx=0.22, fy=0.28)
                data = chart.data_at_pixel(pos)
                self.assertIsNotNone(data)
                _send_wheel(chart, pos, angle=WHEEL_ANGLE_NOTCH)
                mapped = chart.pixel_at_data(*data)
                self.assertIsNotNone(mapped)
                self.assertLess(abs(mapped.x() - pos.x()), 1.5)
                self.assertLess(abs(mapped.y() - pos.y()), 1.5)

    def test_wheel_up_zooms_in_and_down_zooms_out(self):
        self.scatter.set_points(_CLUSTER)
        auto = self.scatter.visible_bounds()
        pos = _plot_anchor_pixel(self.scatter)
        _send_wheel(self.scatter, pos, angle=WHEEL_ANGLE_NOTCH)
        zoomed = self.scatter.visible_bounds()
        self.assertLess(zoomed[1] - zoomed[0], auto[1] - auto[0])
        self.assertLess(zoomed[3] - zoomed[2], auto[3] - auto[2])
        _send_wheel(self.scatter, pos, angle=-WHEEL_ANGLE_NOTCH)
        out = self.scatter.visible_bounds()
        self.assertGreater(out[1] - out[0], zoomed[1] - zoomed[0])
        self.assertGreater(out[3] - out[2], zoomed[3] - zoomed[2])

    def test_button_and_wheel_share_scale_with_different_anchors(self):
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67)
        auto = self.scatter.visible_bounds()
        self.scatter.zoom_in()
        button = self.scatter.visible_bounds()
        self.assertAlmostEqual((button[1] - button[0]) / (auto[1] - auto[0]), ZOOM_IN_FACTOR, places=6)
        mid_x = (auto[0] + auto[1]) / 2.0
        self.assertAlmostEqual((button[0] + button[1]) / 2.0, mid_x, places=6)
        self.scatter.fit_data()
        pos = _plot_anchor_pixel(self.scatter, fx=0.2, fy=0.3)
        _send_wheel(self.scatter, pos, angle=WHEEL_ANGLE_NOTCH)
        wheeled = self.scatter.visible_bounds()
        self.assertAlmostEqual((wheeled[1] - wheeled[0]) / (auto[1] - auto[0]), ZOOM_IN_FACTOR, places=6)
        self.assertGreater(abs(((wheeled[0] + wheeled[1]) / 2.0) - mid_x), 0.2)

    def test_high_resolution_delta_is_one_notch(self):
        self.scatter.set_points(_CLUSTER)
        auto = self.scatter.visible_bounds()
        pos = _plot_anchor_pixel(self.scatter)
        for _ in range(7):
            event = _send_wheel(self.scatter, pos, angle=15)
            self.assertTrue(event.isAccepted())
            self.assertEqual(self.scatter.visible_bounds(), auto)
        _send_wheel(self.scatter, pos, angle=15)
        one = self.scatter.visible_bounds()
        self.assertAlmostEqual((one[1] - one[0]) / (auto[1] - auto[0]), ZOOM_IN_FACTOR, places=6)
        self.scatter.fit_data()
        huge = _send_wheel(self.scatter, pos, pixel=400)
        self.assertTrue(huge.isAccepted())
        burst = self.scatter.visible_bounds()
        expected = auto[1] - auto[0]
        for _ in range(WHEEL_MAX_STEPS_PER_EVENT):
            expected *= ZOOM_IN_FACTOR
        self.assertAlmostEqual(burst[1] - burst[0], expected, places=4)

    def test_wheel_keeps_partial_notch_remainder(self):
        self.scatter.set_points(_CLUSTER)
        auto = self.scatter.visible_bounds()
        pos = _plot_anchor_pixel(self.scatter)
        _send_wheel(self.scatter, pos, angle=50)
        _send_wheel(self.scatter, pos, angle=50)
        self.assertEqual(self.scatter.visible_bounds(), auto)
        self.assertEqual(self.scatter._wheel_accum, 100)
        _send_wheel(self.scatter, pos, angle=20)
        after = self.scatter.visible_bounds()
        self.assertAlmostEqual((after[1] - after[0]) / (auto[1] - auto[0]), ZOOM_IN_FACTOR, places=6)
        self.assertEqual(self.scatter._wheel_accum, 0)

    def test_multi_notch_wheel_event_is_capped(self):
        self.scatter.set_points(_CLUSTER)
        auto = self.scatter.visible_bounds()
        pos = _plot_anchor_pixel(self.scatter)
        _send_wheel(self.scatter, pos, angle=WHEEL_ANGLE_NOTCH * 2)
        two = self.scatter.visible_bounds()
        self.assertAlmostEqual(
            (two[1] - two[0]) / (auto[1] - auto[0]),
            ZOOM_IN_FACTOR ** 2,
            places=6,
        )

    def test_repeated_zoom_stays_finite(self):
        for chart, load in (
            (self.scatter, lambda: self.scatter.set_points(_CLUSTER)),
            (self.interval, lambda: self.interval.set_series(_CLUSTER_SERIES)),
        ):
            with self.subTest(chart=type(chart).__name__):
                load()
                for _ in range(40):
                    chart.zoom_in()
                inn = chart.visible_bounds()
                self.assertTrue(_finite_tuple(inn))
                self.assertGreater(inn[1], inn[0])
                self.assertGreater(inn[3], inn[2])
                self.assertGreaterEqual(inn[1] - inn[0], chart._min_spans()[0] - 1e-9)
                for _ in range(40):
                    chart.zoom_out()
                out = chart.visible_bounds()
                env = chart.navigation_envelope()
                self.assertTrue(_finite_tuple(out))
                self.assertGreater(out[1], out[0])
                self.assertGreater(out[3], out[2])
                self.assertGreaterEqual(out[1] - out[0], inn[1] - inn[0] - 1e-9)
                self.assertGreater(out[3] - out[2], inn[3] - inn[2])
                self.assertGreaterEqual(out[0], env[0] - 1e-6)
                self.assertLessEqual(out[1], env[1] + 1e-6)
                self.assertGreaterEqual(out[2], env[2] - 1e-6)
                self.assertLessEqual(out[3], env[3] + 1e-6)
                self.assertGreater(out[0], -500.0)
                self.assertLess(out[1], 5000.0)

    def test_repeated_zoom_out_does_not_create_huge_negative_space(self):
        self.scatter.set_points(_CLUSTER)
        self.interval.set_series(_CLUSTER_SERIES)
        for _ in range(40):
            self.scatter.zoom_out()
            self.interval.zoom_out()
        sx = self.scatter.visible_bounds()
        iy = self.interval.visible_bounds()
        self.assertGreater(sx[0], -200.0)
        self.assertGreater(sx[2], -200.0)
        self.assertGreater(iy[2], -200.0)
        self.assertLess(sx[1], 2000.0)

    def test_synthetic_negative_observations_remain_visible(self):
        points = [(-25.0, -12.0, "ON_CADENCE", 1), (10.0, 8.0, "ON_CADENCE", 2)]
        self.scatter.set_points(points)
        auto = self.scatter.visible_bounds()
        self.assertLessEqual(auto[0], -25.0)
        self.assertLessEqual(auto[2], -12.0)
        env = self.scatter.navigation_envelope()
        self.assertLessEqual(env[0], -25.0)
        self.assertLessEqual(env[2], -12.0)
        for _ in range(20):
            self.scatter.zoom_out()
        out = self.scatter.visible_bounds()
        self.assertLessEqual(out[0], -25.0)
        self.assertLessEqual(out[2], -12.0)

    def test_fit_data_frames_latest_reset_restores_home(self):
        self.scatter.set_points(_CLUSTER)
        auto = self.scatter.visible_bounds()
        self.scatter.zoom_in()
        zoomed = self.scatter.visible_bounds()
        self.scatter.set_points(_CLUSTER + [(800.0, 400.0, "ON_CADENCE", 9)])
        self.assertEqual(self.scatter.visible_bounds(), zoomed)
        self.scatter.reset_view()
        restored = self.scatter.visible_bounds()
        self.assertAlmostEqual(restored[0], auto[0], places=4)
        self.assertLess(restored[1], 400.0)
        self.scatter.fit_data()
        fitted = self.scatter.visible_bounds()
        self.assertGreaterEqual(fitted[1], 800.0)
        self.assertGreaterEqual(fitted[3], 400.0)
        self.assertFalse(self.scatter.zoom_locked)

    def test_pan_moves_viewport_and_clamps(self):
        self.scatter.show()
        self._qapp.processEvents()
        self.scatter.set_points(_CLUSTER)
        self.scatter.set_pan_enabled(True)
        self.scatter.zoom_in()
        before = self.scatter.visible_bounds()
        source = list(self.scatter.points)
        start = _plot_anchor_pixel(self.scatter, fx=0.5, fy=0.5)
        end = _plot_anchor_pixel(self.scatter, fx=0.2, fy=0.2)
        _drag(self.scatter, start, end)
        after = self.scatter.visible_bounds()
        self.assertNotEqual(after, before)
        self.assertEqual(self.scatter.points, source)
        self.assertTrue(self.scatter.zoom_locked)
        env = self.scatter.navigation_envelope()
        start = _plot_anchor_pixel(self.scatter, fx=0.5, fy=0.5)
        edges = (
            (3000, 0, 0, env[0]),
            (-3000, 0, 1, env[1]),
            (0, -3000, 2, env[2]),
            (0, 3000, 3, env[3]),
        )
        for dx, dy, index, expected in edges:
            self.scatter.fit_data()
            self.scatter.zoom_in()
            _drag(self.scatter, start, QPointF(start.x() + dx, start.y() + dy))
            panned = self.scatter.visible_bounds()
            self.assertGreaterEqual(panned[0], env[0] - 1e-6)
            self.assertLessEqual(panned[1], env[1] + 1e-6)
            self.assertGreaterEqual(panned[2], env[2] - 1e-6)
            self.assertLessEqual(panned[3], env[3] + 1e-6)
            self.assertAlmostEqual(panned[index], expected, places=4)
        for _ in range(30):
            self.scatter.zoom_out()
        at_env = self.scatter.visible_bounds()
        _drag(self.scatter, start, QPointF(start.x() + 400, start.y() + 400))
        panned = self.scatter.visible_bounds()
        self.assertGreaterEqual(panned[0], env[0] - 1e-6)
        self.assertLessEqual(panned[1], env[1] + 1e-6)
        self.assertGreaterEqual(panned[2], env[2] - 1e-6)
        self.assertLessEqual(panned[3], env[3] + 1e-6)
        self.assertGreaterEqual(at_env[0], env[0] - 1e-6)

    def test_pan_disabled_does_not_move_view(self):
        self.scatter.show()
        self._qapp.processEvents()
        self.scatter.set_points(_CLUSTER)
        self.scatter.set_pan_enabled(False)
        self.scatter.zoom_in()
        before = self.scatter.visible_bounds()
        start = _plot_anchor_pixel(self.scatter, fx=0.5, fy=0.5)
        _drag(self.scatter, start, QPointF(start.x() + 80, start.y() + 80))
        self.assertEqual(self.scatter.visible_bounds(), before)

    def test_hover_inspection_is_factual(self):
        self.scatter.show()
        self._qapp.processEvents()
        self.scatter.set_points(_CLUSTER, target_beat_ms=166.67)
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
        self.win.scatter.zoom_in()
        scatter_zoomed = self.win.scatter.visible_bounds()
        self.win.btn_view_interval.click()
        self._settle()
        self.assertEqual(self.win._capture_view, "interval")
        self.assertTrue(self.win.interval_chart.isVisible())
        self.assertFalse(self.win.scatter.isVisible())
        self.assertEqual(self._snapshot(), before)
        self.assertEqual(self.win.scatter.visible_bounds(), scatter_zoomed)
        self.win.interval_chart.zoom_out()
        interval_view = self.win.interval_chart.visible_bounds()
        self.win.btn_view_stability.click()
        self._settle()
        self.assertEqual(self.win._capture_view, "stability")
        self.assertEqual(self.win.scatter.visible_bounds(), scatter_zoomed)
        self.assertNotEqual(scatter_zoomed, scatter_zoom)
        self.win.btn_view_interval.click()
        self._settle()
        self.assertEqual(self.win.interval_chart.visible_bounds(), interval_view)
        self.win.btn_view_stability.click()
        self._settle()
        self.assertEqual(self._snapshot(), before)

    def test_results_charts_remain_legacy_and_multi_view(self):
        self.assertTrue(self.win.results_scatter.data_aware_fit)
        self.assertTrue(self.win.results_interval_chart.data_aware_fit)
        self.assertTrue(self.win.results_distribution_chart.data_aware_fit)
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
        self.assertIsNone(self.win.scatter._nav_home)
        self.assertIsNone(self.win.interval_chart._nav_home)
        self.assertFalse(self.win.scatter.pan_enabled)
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

    def test_fixture_refresh_uses_locked_reference_not_setup_edit(self):
        self._fixture(tol="2")
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        events_before = copy.deepcopy(self.win.events)
        status_before = self.win.val_verdict.text()
        reference = self.win.scatter.target_beat_ms
        self.assertIsNotNone(reference)
        self.win.timing_tol_edit.setText("20")
        self.win.hz_combo.setCurrentText("5")
        self.win._refresh_metrics(final=False)
        self.assertEqual(self.win.events, events_before)
        self.assertEqual(self.win.val_verdict.text(), status_before)
        self.assertEqual(self.win.scatter.target_beat_ms, reference)
        self.assertEqual(self.win.interval_chart.target_beat_ms, reference)
        self.assertNotIn("fixture_timing_tolerance_ms", self.win.locked)
        for chart in (self.win.scatter, self.win.interval_chart):
            labels = [label for _color, label in chart._guide_legend_items()]
            self.assertEqual(labels, [self.win._tr("legend_configured_reference")])

    def test_manual_run_does_not_draw_fixture_guides(self):
        self.win.radio_manual.setChecked(True)
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self.assertIsNone(self.win.scatter.target_beat_ms)
        self.assertEqual(self.win.scatter._guide_legend_items(), [])
        self.assertIsNone(self.win.interval_chart.target_beat_ms)
        self.assertEqual(self.win.interval_chart._guide_legend_items(), [])
        self.assertEqual(self.win.scatter.subtitle, self.win._tr("chart_stability_map_subtitle"))

    def test_fixture_titles_are_factual(self):
        self._fixture(hz="6", tol="2")
        self._start_run()
        self.win._refresh_metrics(final=False)
        self.assertEqual(self.win.scatter.title, "Click interval vs Hold duration")
        self.assertIn("Reference", self.win.scatter.subtitle)
        self.assertNotIn("PASS", self.win.scatter.subtitle)
        self.assertNotIn("specification", self.win.scatter.subtitle.lower())
        self.assertEqual(self.win.interval_chart.title, "Elapsed time vs Click interval")

    def test_measurement_only_capture_does_not_present_legacy_categories(self):
        self._fixture(hz="40", tol="2")
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self.assertTrue(self.win.scatter.measurement_only_presentation)
        self.assertTrue(self.win.issue_title.isHidden())
        self.assertTrue(self.win.capture_issues_grid.isHidden())
        self.assertFalse(self.win.val_time.isHidden())
        self.assertFalse(self.win.val_clicks.isHidden())
        self.assertFalse(self.win.val_interval.isHidden())
        self.assertFalse(self.win.val_hold.isHidden())
        self.assertFalse(self.win.val_verdict.isHidden())
        legend = [text for _, text in self.win.scatter.legend_entries()]
        self.assertIn("Host observation", legend)
        self.assertIn("Reference interval", legend)
        for banned in (
            "Short interval",
            "Very short interval",
            "Short hold",
            "Long interval",
            "Cadence vs reference",
        ):
            self.assertNotIn(banned, legend)
        self.assertNotIn("Short interval", self.win.alert_label.text())
        self.assertNotIn("Very short interval", self.win.alert_label.text())
        self.assertNotIn("Cadence vs reference", self.win.alert_label.text())

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

    def test_wheel_inside_plot_does_not_scroll_capture(self):
        self._start_run()
        self._raw_click()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self._show_capture()
        self.win.resize(1024, 640)
        self.win.setMinimumSize(1, 1)
        self.win.resize(1024, 640)
        self._settle()
        bar = self.win.capture_scroll.verticalScrollBar()
        if bar.maximum() > 0:
            bar.setValue(min(40, bar.maximum()))
            self._settle()
        before = bar.value()
        bounds = self.win.scatter.visible_bounds()
        pos = _plot_anchor_pixel(self.win.scatter)
        event = _send_wheel(self.win.scatter, pos, angle=WHEEL_ANGLE_NOTCH)
        self._settle()
        self.assertTrue(event.isAccepted())
        self.assertNotEqual(self.win.scatter.visible_bounds(), bounds)
        self.assertEqual(bar.value(), before)

    def test_wheel_outside_plot_leaves_page_scroll_available(self):
        self._show_capture()
        self.win.setMinimumSize(1, 1)
        self.win.resize(1024, 640)
        self._settle()
        bar = self.win.capture_scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        title = QPointF(self.win.scatter.width() / 2.0, 8.0)
        self.assertFalse(self.win.scatter._plot_rect().contains(title))
        before_bounds = self.win.scatter.visible_bounds()
        event = _send_wheel(self.win.scatter, title, angle=-WHEEL_ANGLE_NOTCH)
        self.assertFalse(event.isAccepted())
        self.assertEqual(self.win.scatter.visible_bounds(), before_bounds)
        self.assertTrue(bar.isEnabled())
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(min(bar.maximum(), 30))
        self._settle()
        self.assertGreater(bar.value(), 0)

    def test_wheel_and_buttons_at_supported_sizes_do_not_move_page_over_plot(self):
        self._start_run()
        for _ in range(3):
            self._raw_click()
        self.win._refresh_metrics(final=False)
        for width, height in ((1280, 720), (1600, 900)):
            with self.subTest(size=(width, height)):
                self.win.resize(width, height)
                self._show_capture()
                bar = self.win.capture_scroll.verticalScrollBar()
                before = bar.value()
                for chart in (self.win.scatter, self.win.interval_chart):
                    self.win.btn_view_stability.click() if chart is self.win.scatter else self.win.btn_view_interval.click()
                    self._settle()
                    pos = _plot_anchor_pixel(chart)
                    event = _send_wheel(chart, pos, angle=WHEEL_ANGLE_NOTCH)
                    self._settle()
                    self.assertTrue(event.isAccepted())
                    self.assertTrue(chart.zoom_locked)
                    self.assertEqual(bar.value(), before)
                    self.win.btn_chart_zoom_out.click()
                    self.win.btn_chart_fit.click()
                    self.assertFalse(chart.zoom_locked)
                    self.win.btn_chart_reset.click()
                    self.assertEqual(bar.value(), before)

    def test_wheel_does_not_become_a_host_click(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self._show_capture()
        before = self._snapshot()
        pos = _plot_anchor_pixel(self.win.scatter)
        _send_wheel(self.win.scatter, pos, angle=WHEEL_ANGLE_NOTCH)
        self._settle()
        self.assertEqual(self.win.events, before[4])
        self.assertFalse(self.win.running)
        self.assertIsNone(self.win.start_time)
        self.assertEqual(self.win._lifecycle_state(), "armed")

    def test_pan_disabled_until_review(self):
        self.win.radio_manual.setChecked(True)
        self._show_capture()
        self.assertTrue(self.win.lock_profile())
        self.win._update_controls()
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertFalse(self.win.scatter.pan_enabled)
        self.assertFalse(self.win.interval_chart.pan_enabled)
        self.assertTrue(self.win.arm_capture())
        self.win._update_controls()
        self.assertEqual(self.win._lifecycle_state(), "armed")
        self.assertFalse(self.win.scatter.pan_enabled)
        self._start_run()
        self._raw_click()
        self.win._refresh_metrics(final=False)
        self.assertEqual(self.win._lifecycle_state(), "running")
        self.assertFalse(self.win.scatter.pan_enabled)
        events_before = copy.deepcopy(self.win.events)
        start = _plot_anchor_pixel(self.win.scatter)
        _drag(self.win.scatter, start, QPointF(start.x() + 40, start.y() + 40))
        self.assertEqual(self.win.events, events_before)
        self.win.stop_run()
        self._settle()
        self.assertTrue(self.win._post_run_input_guard_active)
        self.assertFalse(self.win.scatter.pan_enabled)
        self.assertFalse(self.win.interval_chart.pan_enabled)
        self.win._release_post_run_input_guard()
        self.win._show_workflow_page("capture")
        self._settle()
        self.assertEqual(self.win._lifecycle_state(), "completed")
        self.assertFalse(self.win._post_run_input_guard_active)
        self.assertTrue(self.win.scatter.pan_enabled)
        self.assertTrue(self.win.interval_chart.pan_enabled)
        self.win.scatter.zoom_in()
        before = self.win.scatter.visible_bounds()
        measured = copy.deepcopy(self.win.events)
        _drag(self.win.scatter, start, QPointF(start.x() + 60, start.y() + 30))
        self.assertNotEqual(self.win.scatter.visible_bounds(), before)
        self.assertEqual(self.win.events, measured)

    def test_review_smoke_clamps_and_does_not_scroll_plot_wheel(self):
        self._start_run()
        for _ in range(4):
            self._raw_click()
        self.win._refresh_metrics(final=False)
        self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()
        for width, height in ((1280, 720), (1600, 900)):
            with self.subTest(size=(width, height)):
                self.win.resize(width, height)
                self._show_capture()
                bar = self.win.capture_scroll.verticalScrollBar()
                before_bar = bar.value()
                for chart in (self.win.scatter, self.win.interval_chart):
                    if chart is self.win.scatter:
                        self.win.btn_view_stability.click()
                    else:
                        self.win.btn_view_interval.click()
                    self._settle()
                    self.assertTrue(chart.pan_enabled)
                    self.win.btn_chart_fit.click()
                    for fx, fy in ((0.15, 0.5), (0.85, 0.5), (0.5, 0.2), (0.5, 0.8)):
                        pos = _plot_anchor_pixel(chart, fx=fx, fy=fy)
                        event = _send_wheel(chart, pos, angle=WHEEL_ANGLE_NOTCH)
                        self.assertTrue(event.isAccepted())
                    self.win.btn_chart_zoom_out.click()
                    for _ in range(20):
                        chart.zoom_out()
                    bounds = chart.visible_bounds()
                    self.assertGreater(bounds[0], -400.0)
                    self.assertGreater(bounds[2], -400.0)
                    start = _plot_anchor_pixel(chart, fx=0.5, fy=0.5)
                    _drag(chart, start, QPointF(start.x() + 50, start.y() + 40))
                    self.win.btn_chart_reset.click()
                    self.assertEqual(bar.value(), before_bar)
                title = QPointF(self.win.scatter.width() / 2.0, 8.0)
                outside = _send_wheel(self.win.scatter, title, angle=-WHEEL_ANGLE_NOTCH)
                self.assertFalse(outside.isAccepted())

    def test_i18n_keys_exist(self):
        for lang in SUPPORTED_LANGS:
            for key in _I18N_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(STRINGS[lang].get(key) or "").strip())
        self.assertEqual(STRINGS["en"]["chart_stability_map"], "Click interval vs Hold duration")
        self.assertEqual(STRINGS["en"]["chart_interval_trend"], "Elapsed time vs Click interval")
        self.assertEqual(STRINGS["en"]["legend_on_cadence"], "Observation")
        for lang in SUPPORTED_LANGS:
            self.assertNotIn("legend_association_window", STRINGS[lang])


if __name__ == "__main__":
    unittest.main()
