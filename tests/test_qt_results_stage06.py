"""Stage 0.6: typed Click Data sorting and Measurement-only Results presentation."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.cadence import class_to_tags, classify_click
from mouse_click_stability_analyzer.i18n import STRINGS
from mouse_click_stability_analyzer.presentation import (
    SCREENING_PRESENTATION_EN,
    measurement_only_timing_observation_label,
    screening_presentation_label,
)
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.click_table_sort import sort_permutation
from mouse_click_stability_analyzer.qt_shell.charts import ScatterChart


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


class TypedSortPermutationTests(unittest.TestCase):
    def test_integer_order_is_numeric_not_lexical(self):
        values = [1, 10, 11, 2]
        order = sort_permutation(values, numeric=True)
        self.assertEqual([values[i] for i in order], [1, 2, 10, 11])

    def test_decimals(self):
        values = [10.01, 9.9, 10.0]
        order = sort_permutation(values, numeric=True)
        self.assertEqual([values[i] for i in order], [9.9, 10.0, 10.01])

    def test_negatives(self):
        values = [2, -5, 0]
        order = sort_permutation(values, numeric=True)
        self.assertEqual([values[i] for i in order], [-5, 0, 2])

    def test_blanks_last_both_directions(self):
        values = [10.0, None, 2.0, None, 9.9]
        asc = [values[i] for i in sort_permutation(values, numeric=True)]
        desc = [values[i] for i in sort_permutation(values, numeric=True, descending=True)]
        self.assertEqual(asc[:3], [2.0, 9.9, 10.0])
        self.assertEqual(asc[3:], [None, None])
        self.assertEqual(desc[:3], [10.0, 9.9, 2.0])
        self.assertEqual(desc[3:], [None, None])

    def test_stable_equal_values(self):
        values = [5, 5, 5]
        ties = [2, 0, 1]
        order = sort_permutation(values, numeric=True, tie_breakers=ties)
        self.assertEqual(order, [1, 2, 0])


class ClickDataTableSortTests(unittest.TestCase):
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

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _rows(self, specs):
        rows = []
        for spec in specs:
            rows.append({
                "index": spec.get("index"),
                "elapsed_ms": spec.get("elapsed_ms"),
                "button": spec.get("button", "Left"),
                "interval_ms": spec.get("interval_ms"),
                "hold_ms": spec.get("hold_ms", 8.0),
                "state": spec.get("state", "ON_CADENCE"),
                "tags": spec.get("tags", []),
                "reference_delta_ms": spec.get("reference_delta_ms"),
            })
        return rows

    def _col(self, column: int) -> list[str]:
        table = self.win.results_click_table
        return [table.item(r, column).text() for r in range(table.rowCount())]

    def test_default_order_is_hash_ascending(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "elapsed_ms": 0.0, "interval_ms": None, "reference_delta_ms": None},
            {"index": 2, "elapsed_ms": 10.0, "interval_ms": 10.0, "reference_delta_ms": -15.0},
            {"index": 10, "elapsed_ms": 90.0, "interval_ms": 10.0, "reference_delta_ms": -15.0},
            {"index": 11, "elapsed_ms": 100.0, "interval_ms": 10.0, "reference_delta_ms": -15.0},
        ])})
        header = self.win.results_click_table.horizontalHeader()
        self.assertEqual(header.sortIndicatorSection(), 0)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.AscendingOrder)
        self.assertEqual(self._col(0), ["1", "2", "10", "11"])

    def test_integer_and_header_toggle(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1}, {"index": 10}, {"index": 11}, {"index": 2},
        ])})
        self.assertEqual(self._col(0), ["1", "2", "10", "11"])
        self.win._on_click_header_clicked(0)
        self.assertEqual(self.win.results_click_table.horizontalHeader().sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)
        self.assertEqual(self._col(0), ["11", "10", "2", "1"])
        self.win._on_click_header_clicked(0)
        self.assertEqual(self._col(0), ["1", "2", "10", "11"])

    def test_numeric_decimals_and_negatives(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "elapsed_ms": 100.0, "interval_ms": 10.01, "hold_ms": 10.01, "reference_delta_ms": 2.0},
            {"index": 2, "elapsed_ms": 9.9, "interval_ms": 9.9, "hold_ms": 9.9, "reference_delta_ms": -5.0},
            {"index": 3, "elapsed_ms": 10.0, "interval_ms": 10.0, "hold_ms": 10.0, "reference_delta_ms": 0.0},
        ])})
        self.win._on_click_header_clicked(3)
        self.assertEqual(self._col(3), ["9.90", "10.00", "10.01"])
        self.win._on_click_header_clicked(7)
        self.assertEqual(self._col(7), ["-5.00", "0.00", "2.00"])
        self.win._on_click_header_clicked(1)
        self.assertEqual(self._col(1), ["9.90", "10.00", "100.00"])
        self.win._on_click_header_clicked(4)
        self.assertEqual(self._col(4), ["9.90", "10.00", "10.01"])

    def test_blank_interval_last_both_directions(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "interval_ms": None},
            {"index": 2, "interval_ms": 10.0},
            {"index": 3, "interval_ms": 2.0},
        ])})
        self.win._on_click_header_clicked(3)
        self.assertEqual(self._col(3), ["2.00", "10.00", ""])
        self.assertEqual(self._col(0)[-1], "1")
        self.win._on_click_header_clicked(3)
        self.assertEqual(self._col(3), ["10.00", "2.00", ""])
        self.assertEqual(self._col(0)[-1], "1")

    def test_sorting_does_not_mutate_canonical_events(self):
        events = [
            {"click_index": 1, "accepted": True, "press_interval_ms": None},
            {"click_index": 2, "accepted": True, "press_interval_ms": 10.0},
            {"click_index": 10, "accepted": True, "press_interval_ms": 11.0},
        ]
        self.win.events = events
        click_data = self._rows([
            {"index": 1, "interval_ms": None},
            {"index": 2, "interval_ms": 10.0},
            {"index": 10, "interval_ms": 11.0},
        ])
        model = {"click_data": click_data}
        self.win._populate_click_table(model)
        before_ids = [id(e) for e in self.win.events]
        before_index = [e["click_index"] for e in self.win.events]
        before_model = [row["index"] for row in click_data]
        self.win._on_click_header_clicked(3)
        self.assertEqual([id(e) for e in self.win.events], before_ids)
        self.assertEqual([e["click_index"] for e in self.win.events], before_index)
        self.assertEqual([row["index"] for row in click_data], before_model)
        self.assertEqual(self._col(0)[-1], "1")


class MeasurementOnlyPresentationTests(unittest.TestCase):
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

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def test_neutral_row_shows_dash_not_observation(self):
        self.assertEqual(measurement_only_timing_observation_label(), "—")
        self.win._populate_click_table({"click_data": [{
            "index": 1, "elapsed_ms": 0.0, "button": "Left", "interval_ms": None,
            "hold_ms": 8.0, "state": "ON_CADENCE", "tags": [], "reference_delta_ms": None,
        }]})
        self.assertEqual(self.win.results_click_table.item(0, 5).text(), "—")
        self.assertNotEqual(self.win.results_click_table.item(0, 5).text(), "Observation")
        self.assertEqual(self.win.results_click_table.horizontalHeaderItem(5).text(), "Timing observation")

    def test_legacy_classes_remain_internal(self):
        self.assertEqual(classify_click(5.0, 80.0, {"chatter_threshold_ms": 8}), "CHATTER_BOUNCE")
        self.assertEqual(class_to_tags("CHATTER_BOUNCE", False), ["CHATTER_HARD", "CHATTER_BOUNCE"])
        self.assertEqual(screening_presentation_label("TRUE_EXTRA_CLICK"), "Short interval")
        self.assertEqual(SCREENING_PRESENTATION_EN["ON_CADENCE"], "Observation")
        self.win._populate_click_table({"click_data": [{
            "index": 2, "elapsed_ms": 12.0, "button": "Left", "interval_ms": 12.0,
            "hold_ms": 8.0, "state": "TRUE_EXTRA_CLICK",
            "tags": ["TRUE_EXTRA_CLICK"], "reference_delta_ms": -13.0,
        }]})
        self.assertEqual(self.win.results_click_table.item(0, 5).text(), "—")
        self.assertEqual(self.win.results_click_table.item(0, 6).text(), "—")

    def test_results_legend_uses_host_observation_and_configured_reference(self):
        labels = self.win._chart_labels()
        self.win.results_scatter.set_theme(self.win.results_scatter.palette, labels)
        self.win.results_interval_chart.set_theme(self.win.results_interval_chart.palette, labels)
        self.win.results_distribution_chart.set_theme(self.win.results_distribution_chart.palette, labels)
        self.win.results_scatter.set_points([(25.0, 8.0, "TRUE_EXTRA_CLICK")], target_beat_ms=25.0)
        self.win.results_interval_chart.set_series([(0.0, 25.0), (25.0, 25.0)], target_beat_ms=25.0)
        self.win.results_distribution_chart.set_bins(
            [{"lo": 0.0, "hi": 50.0, "count": 2}],
            target_beat_ms=25.0,
        )
        scatter_text = [text for _, text in self.win.results_scatter.legend_entries()]
        interval_text = [text for _, text in self.win.results_interval_chart.legend_entries()]
        hist_text = [text for _, text in self.win.results_distribution_chart.legend_entries()]
        self.assertIn("Host observation", scatter_text)
        self.assertNotIn("Observation", scatter_text)
        self.assertNotIn("Short interval", scatter_text)
        self.assertNotIn("Very short interval", scatter_text)
        self.assertNotIn("Long interval", scatter_text)
        self.assertNotIn("PASS", scatter_text)
        self.assertNotIn("WARN", scatter_text)
        self.assertNotIn("FAIL", scatter_text)
        self.assertNotIn("Target beat", scatter_text)
        self.assertNotIn("Target beat", interval_text)
        self.assertIn("Configured reference", scatter_text)
        self.assertIn("Configured reference", interval_text)
        self.assertIn("Configured reference", hist_text)
        self.assertNotIn("Target beat", hist_text)
        self.assertFalse(self.win.results_scatter.data_aware_fit)
        self.assertFalse(self.win.results_interval_chart.data_aware_fit)
        self.assertFalse(self.win.results_distribution_chart.data_aware_fit)
        self.assertTrue(self.win.scatter.data_aware_fit)
        self.assertEqual(STRINGS["en"]["legend_on_cadence"], "Observation")
        self.assertEqual(STRINGS["en"]["legend_target"], "Target beat")
        capture = ScatterChart()
        capture.set_data_aware_fit(True)
        capture.set_theme(capture.palette, labels)
        capture.set_points([(25.0, 8.0, "TRUE_EXTRA_CLICK")], target_beat_ms=25.0)
        capture_text = [text for _, text in capture.legend_entries()]
        self.assertIn("Observation", capture_text)
        self.assertIn("Short interval", capture_text)
        self.assertIn("Very short interval", capture_text)
        self.assertIn("Long interval", capture_text)
        self.assertNotIn("Host observation", capture_text)

    def test_point_color_does_not_promote_heuristic_in_results(self):
        extra = self.win.results_scatter._point_color("TRUE_EXTRA_CLICK")
        chatter = self.win.results_scatter._point_color("CHATTER_BOUNCE")
        miss = self.win.results_scatter._point_color("MISS_OR_SLOW")
        host = self.win.results_scatter.palette.on_cadence
        self.assertEqual(extra, host)
        self.assertEqual(chatter, host)
        self.assertEqual(miss, host)
        capture = ScatterChart()
        self.assertNotEqual(capture._point_color("TRUE_EXTRA_CLICK"), capture.palette.on_cadence)
        self.assertIn("Host observation", self.win.results_chart_legend_help.text())
        self.assertIn("not a PASS/FAIL threshold", self.win.results_chart_legend_help.text())
        self.assertNotIn("Target beat", self.win.results_chart_legend_help.text())


if __name__ == "__main__":
    unittest.main()
