"""Histogram presentation: category bar styles and unambiguous boundary notation.

Classification and bin placement are owned by interval_comparison / completed_result
and are only read here.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.completed_result import (
    classified_interval_histogram,
    histogram_observation_count,
    interval_histogram_bins,
)
from mouse_click_stability_analyzer.interval_comparison import (
    POSITION_ABOVE,
    POSITION_BELOW,
    POSITION_WITHIN,
    classify_interval,
    format_histogram_bin_range,
    histogram_bin_closure,
    resolve_configured_range,
)

LOWER = 300.0
UPPER = 1000.0 / 3.0 * 1.1
CONTRACT = resolve_configured_range(reference_hz=3, basis="percent", value=10)
VALUES = [
    244.01, 270.0, 299.99,           # below lower
    LOWER,                           # exactly lower
    301.0, 320.0, 333.33, 358.0,     # inside
    UPPER,                           # exactly upper
    366.7, 380.0, 415.0,             # above upper
]


def _contains(value: float, item: dict, closure: tuple[bool, bool]) -> bool:
    lo, hi = float(item["lo"]), float(item["hi"])
    lo_ok = value >= lo if closure[0] else value > lo
    hi_ok = value <= hi if closure[1] else value < hi
    return lo_ok and hi_ok


class ReferenceRangeTests(unittest.TestCase):
    def test_reference_bounds(self):
        self.assertAlmostEqual(CONTRACT["lower_bound_ms"], LOWER, places=9)
        self.assertAlmostEqual(CONTRACT["upper_bound_ms"], UPPER, places=9)


class ClassificationUnchangedTests(unittest.TestCase):
    def test_boundary_classification(self):
        contract = {"enabled": True, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER}
        self.assertEqual(classify_interval(299.99, contract), POSITION_BELOW)
        self.assertEqual(classify_interval(LOWER, contract), POSITION_WITHIN)
        self.assertEqual(classify_interval(333.33, contract), POSITION_WITHIN)
        self.assertEqual(classify_interval(UPPER, contract), POSITION_WITHIN)
        self.assertEqual(classify_interval(366.7, contract), POSITION_ABOVE)

    def test_counts_unchanged(self):
        contract = {"enabled": True, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER}
        bins = classified_interval_histogram(VALUES, contract)
        totals = {POSITION_BELOW: 0, POSITION_WITHIN: 0, POSITION_ABOVE: 0}
        for item in bins:
            totals[item["position"]] += int(item["count"])
        self.assertEqual(totals, {POSITION_BELOW: 3, POSITION_WITHIN: 6, POSITION_ABOVE: 3})
        self.assertEqual(histogram_observation_count(bins), len(VALUES))


class BoundaryNotationTests(unittest.TestCase):
    def setUp(self):
        self.contract = {"enabled": True, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER}
        self.bins = classified_interval_histogram(VALUES, self.contract)
        self.closure = histogram_bin_closure(self.bins, self.contract)
        self.labels = [
            format_histogram_bin_range(float(b["lo"]), float(b["hi"]), *c)
            for b, c in zip(self.bins, self.closure)
        ]

    def test_notation_matches_placement_for_every_observation(self):
        for value in VALUES:
            holders = [i for i, (b, c) in enumerate(zip(self.bins, self.closure)) if _contains(value, b, c)]
            self.assertEqual(len(holders), 1, f"{value} claimed by bins {holders}")
            self.assertEqual(self.bins[holders[0]]["position"], classify_interval(value, self.contract))
        for item, closure in zip(self.bins, self.closure):
            self.assertEqual(int(item["count"]), sum(_contains(v, item, closure) for v in VALUES))

    def test_lower_bound_not_claimed_by_below(self):
        below = [i for i, b in enumerate(self.bins) if b["position"] == POSITION_BELOW]
        last_below = below[-1]
        self.assertEqual(float(self.bins[last_below]["hi"]), LOWER)
        self.assertFalse(self.closure[last_below][1])
        self.assertTrue(self.labels[last_below].endswith("x < 300.00 ms"))
        first_within = last_below + 1
        self.assertEqual(self.bins[first_within]["position"], POSITION_WITHIN)
        self.assertTrue(self.labels[first_within].startswith("300.00 ≤ x"))

    def test_upper_bound_not_claimed_by_above(self):
        above = [i for i, b in enumerate(self.bins) if b["position"] == POSITION_ABOVE]
        first_above = above[0]
        self.assertEqual(float(self.bins[first_above]["lo"]), UPPER)
        self.assertFalse(self.closure[first_above][0])
        self.assertTrue(self.labels[first_above].startswith("366.67 < x ≤"))
        last_within = first_above - 1
        self.assertEqual(self.bins[last_within]["position"], POSITION_WITHIN)
        self.assertTrue(self.labels[last_within].endswith("≤ 366.67 ms"))

    def test_no_boundary_closed_on_both_neighbours(self):
        for i in range(len(self.bins) - 1):
            shared_edge = float(self.bins[i]["hi"])
            self.assertEqual(shared_edge, float(self.bins[i + 1]["lo"]))
            self.assertFalse(self.closure[i][1] and self.closure[i + 1][0], self.labels[i : i + 2])

    def test_unclassified_bins_use_half_open_with_closed_last(self):
        bins = interval_histogram_bins(VALUES)
        closure = histogram_bin_closure(bins, {"enabled": False})
        self.assertEqual(closure[:-1], [(True, False)] * (len(bins) - 1))
        self.assertEqual(closure[-1], (True, True))
        for value in VALUES:
            self.assertEqual(sum(_contains(value, b, c) for b, c in zip(bins, closure)), 1)


class HtmlHistogramNotationTests(unittest.TestCase):
    def test_svg_titles_use_boundary_notation(self):
        from mouse_click_stability_analyzer.report_v2 import _svg_histogram

        contract = {"enabled": True, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER}
        bins = classified_interval_histogram(VALUES, contract)
        reference = {"interval_ms": 1000.0 / 3.0, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER}
        svg = _svg_histogram(bins, reference)
        self.assertIn("x &lt; 300.00 ms:", svg)
        self.assertIn("<title>300.00 ≤ x &lt;", svg)
        self.assertIn("≤ 366.67 ms:", svg)
        self.assertIn("<title>366.67 &lt; x ≤", svg)
        self.assertNotIn("–300.00 ms", svg)
        self.assertNotIn("–366.67 ms", svg)
        self.assertEqual(svg.count("class='bar-"), len(bins))


class QtHistogramCategoryStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PySide6.QtWidgets import QApplication
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"PySide6 unavailable: {exc}")
        cls.app = QApplication.instance() or QApplication([])

    def _chart(self, contract):
        from mouse_click_stability_analyzer.qt_shell.charts import HistogramChart

        chart = HistogramChart()
        chart.set_bins(classified_interval_histogram(VALUES, contract), target_beat_ms=1000.0 / 3.0,
                       configured_range=(LOWER, UPPER) if contract.get("enabled") else None)
        return chart

    def test_each_bar_uses_its_category_style(self):
        from mouse_click_stability_analyzer.qt_shell.charts import HIST_CATEGORY_PALETTE_KEYS

        chart = self._chart({"enabled": True, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER})
        for item in chart.bins:
            category = chart.bar_category(item)
            self.assertEqual(category, item["position"])
            self.assertEqual(chart.bar_palette_key(item), HIST_CATEGORY_PALETTE_KEYS[category])
            self.assertEqual(chart._bar_color(item), getattr(chart.palette, HIST_CATEGORY_PALETTE_KEYS[category]))

    def test_legend_swatches_equal_bar_fills(self):
        from mouse_click_stability_analyzer.qt_shell.charts import HIST_CATEGORY_PALETTE_KEYS

        chart = self._chart({"enabled": True, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER})
        legend = chart.legend_entries()[:3]
        expected = [getattr(chart.palette, HIST_CATEGORY_PALETTE_KEYS[p])
                    for p in (POSITION_BELOW, POSITION_WITHIN, POSITION_ABOVE)]
        self.assertEqual([color for color, _label in legend], expected)
        fills = {chart.bar_category(b): chart._bar_color(b) for b in chart.bins}
        self.assertEqual([fills[p] for p in (POSITION_BELOW, POSITION_WITHIN, POSITION_ABOVE)], expected)

    def test_rendered_bar_bodies_show_category_fill(self):
        """Painter state: the edge pass must not overpaint bodies with a leftover legend brush."""
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QColor

        chart = self._chart({"enabled": True, "lower_bound_ms": LOWER, "upper_bound_ms": UPPER})
        chart.resize(960, 420)
        image = chart.grab().toImage()
        plot = chart._plot_rect()
        xmin, xmax, ymin, ymax = chart.visible_bounds()
        for item in chart.bins:
            if not item["count"]:
                continue
            lo, hi = float(item["lo"]), float(item["hi"])
            x = plot.left() + ((lo + hi) / 2 - xmin) / (xmax - xmin) * plot.width()
            y = plot.bottom() - 2
            if not (plot.left() < x < plot.right()) or (hi - lo) / (xmax - xmin) * plot.width() < 6:
                continue
            ratio = image.devicePixelRatio()
            pixel = QColor(image.pixel(QPoint(int(x * ratio), int(y * ratio))))
            with self.subTest(position=item["position"], lo=lo):
                self.assertEqual(pixel.name(), QColor(chart._bar_color(item)).name())

    def test_category_fills_are_distinct_from_range_and_reference(self):
        from PySide6.QtGui import QColor

        from mouse_click_stability_analyzer.qt_shell.styles import DARK_PALETTE, LIGHT_PALETTE

        for pal in (LIGHT_PALETTE, DARK_PALETTE):
            with self.subTest(palette=pal.bg):
                fills = {pal.chatter, pal.interval_line, pal.extra}
                self.assertEqual(len(fills), 3)
                self.assertTrue(fills.isdisjoint({pal.range_band, pal.range_edge, pal.target_line}))
                for name in fills:
                    self.assertEqual(QColor(name).alpha(), 255, name)

    def test_unclassified_fill_is_translucent_interval_hue(self):
        from PySide6.QtGui import QColor

        from mouse_click_stability_analyzer.qt_shell.styles import DARK_PALETTE, LIGHT_PALETTE

        for pal in (LIGHT_PALETTE, DARK_PALETTE):
            with self.subTest(palette=pal.bg):
                fill = QColor(pal.interval_fill)
                line = QColor(pal.interval_line)
                self.assertTrue(0 < fill.alpha() < 255)
                self.assertEqual(fill.rgb(), line.rgb())
        chart = self._chart({"enabled": False})
        self.assertTrue(all(chart.bar_category(b) is None for b in chart.bins))
        self.assertTrue(all(chart.bar_palette_key(b) == "interval_fill" for b in chart.bins))


if __name__ == "__main__":
    unittest.main()
