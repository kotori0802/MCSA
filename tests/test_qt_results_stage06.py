"""Stage 0.6: typed Click Data sorting and Measurement-only Results presentation."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHeaderView

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
from mouse_click_stability_analyzer.qt_shell.click_table_sort import (
    CLICK_TABLE_MEASUREMENT_VISIBLE_IDS,
    sort_permutation,
)
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

    def test_numeric_equal_values_ascending_keep_canonical_order(self):
        values = [10.0, 5.0, 10.0, 5.0, 10.0]
        ties = [4, 3, 0, 1, 2]
        order = sort_permutation(values, numeric=True, tie_breakers=ties)
        self.assertEqual([values[i] for i in order], [5.0, 5.0, 10.0, 10.0, 10.0])
        self.assertEqual([ties[i] for i in order], [1, 3, 0, 2, 4])

    def test_numeric_equal_values_descending_keep_canonical_order(self):
        values = [10.0, 5.0, 10.0, 5.0, 10.0]
        ties = [4, 3, 0, 1, 2]
        order = sort_permutation(values, numeric=True, descending=True, tie_breakers=ties)
        self.assertEqual([values[i] for i in order], [10.0, 10.0, 10.0, 5.0, 5.0])
        self.assertEqual([ties[i] for i in order], [0, 2, 4, 1, 3])

    def test_text_equal_values_ascending_keep_canonical_order(self):
        values = ["Right", "left", "Left", "right", "Left"]
        ties = [3, 4, 0, 1, 2]
        order = sort_permutation(values, tie_breakers=ties)
        self.assertEqual([values[i].casefold() for i in order], ["left", "left", "left", "right", "right"])
        self.assertEqual([ties[i] for i in order], [0, 2, 4, 1, 3])

    def test_text_equal_values_descending_keep_canonical_order(self):
        values = ["Right", "left", "Left", "right", "Left"]
        ties = [3, 4, 0, 1, 2]
        order = sort_permutation(values, descending=True, tie_breakers=ties)
        self.assertEqual([values[i].casefold() for i in order], ["right", "right", "left", "left", "left"])
        self.assertEqual([ties[i] for i in order], [1, 3, 0, 2, 4])

    def test_equal_values_with_blanks_descending(self):
        values = [None, 7.0, "", 7.0, 3.0]
        ties = [4, 2, 0, 1, 3]
        order = sort_permutation(values, numeric=True, descending=True, tie_breakers=ties)
        self.assertEqual([ties[i] for i in order], [1, 2, 3, 0, 4])

    def test_inputs_are_not_mutated(self):
        values = [3.0, 1.0, 3.0]
        ties = [2, 1, 0]
        sort_permutation(values, numeric=True, descending=True, tie_breakers=ties)
        self.assertEqual(values, [3.0, 1.0, 3.0])
        self.assertEqual(ties, [2, 1, 0])


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

    def _show_click_data(self) -> None:
        self.win.show()
        self.win.resize(1280, 800)
        self.win.results_empty_card.setVisible(False)
        self.win.results_workspace.setVisible(True)
        self.win._show_workflow_page("results")
        self.win.results_tabs.setCurrentIndex(2)
        table = self.win.results_click_table
        table.show()
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        width = 40
        for index in range(header.count()):
            if header.isSectionHidden(index):
                header.resizeSection(index, 0)
            else:
                header.resizeSection(index, 96)
                width += 96
        table.setMinimumWidth(width)
        table.resize(width, 280)
        self._qapp.processEvents()

    def _click_header(self, logical: int) -> None:
        header = self.win.results_click_table.horizontalHeader()
        x = header.sectionViewportPosition(logical) + max(header.sectionSize(logical) // 2, 4)
        y = max(header.height() // 2, 2)
        QTest.mouseClick(
            header.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(x, y),
        )
        self._qapp.processEvents()

    def test_default_order_is_hash_ascending(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "elapsed_ms": 0.0, "interval_ms": None, "reference_delta_ms": None},
            {"index": 2, "elapsed_ms": 10.0, "interval_ms": 10.0, "reference_delta_ms": -15.0},
            {"index": 10, "elapsed_ms": 90.0, "interval_ms": 10.0, "reference_delta_ms": -15.0},
            {"index": 11, "elapsed_ms": 100.0, "interval_ms": 10.0, "reference_delta_ms": -15.0},
        ])})
        self._show_click_data()
        header = self.win.results_click_table.horizontalHeader()
        self.assertEqual(header.sortIndicatorSection(), 0)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.win.click_sort_column_combo.currentData(), "index")
        self.assertEqual(self.win.click_sort_order_combo.currentData(), "asc")
        self.assertEqual(self._col(0), ["1", "2", "10", "11"])
        ids = [
            self.win.click_sort_column_combo.itemData(i)
            for i in range(self.win.click_sort_column_combo.count())
        ]
        self.assertEqual(tuple(ids), CLICK_TABLE_MEASUREMENT_VISIBLE_IDS)
        self.assertNotIn("state", ids)
        self.assertNotIn("tags", ids)
        self.assertNotEqual(self.win.click_sort_column_combo.currentData(), self.win.click_sort_column_combo.currentText())

    def test_header_click_toggles_and_syncs_sort_controls(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "interval_ms": 11.0},
            {"index": 10, "interval_ms": 10.0},
            {"index": 11, "interval_ms": 9.0},
            {"index": 2, "interval_ms": 12.0},
        ])})
        self._show_click_data()
        self.assertEqual(self._col(0), ["1", "2", "10", "11"])
        self._click_header(0)
        header = self.win.results_click_table.horizontalHeader()
        self.assertEqual(header.sortIndicatorSection(), 0)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)
        self.assertEqual(self.win.click_sort_column_combo.currentData(), "index")
        self.assertEqual(self.win.click_sort_order_combo.currentData(), "desc")
        self.assertEqual(self._col(0), ["11", "10", "2", "1"])
        self._click_header(0)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.win.click_sort_order_combo.currentData(), "asc")
        self.assertEqual(self._col(0), ["1", "2", "10", "11"])
        self._click_header(3)
        self.assertEqual(header.sortIndicatorSection(), 3)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.win.click_sort_column_combo.currentData(), "interval_ms")
        self.assertEqual(self.win.click_sort_order_combo.currentData(), "asc")
        self.assertEqual(self._col(3), ["9.00", "10.00", "11.00", "12.00"])
        self.assertEqual(self._col(0), ["11", "10", "1", "2"])

    def test_sort_controls_update_header_and_table(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "interval_ms": 11.0, "hold_ms": 8.0},
            {"index": 2, "interval_ms": 9.0, "hold_ms": 10.0},
            {"index": 3, "interval_ms": 10.0, "hold_ms": 9.0},
        ])})
        self._show_click_data()
        combo = self.win.click_sort_column_combo
        combo.setCurrentIndex(combo.findData("interval_ms"))
        self._qapp.processEvents()
        header = self.win.results_click_table.horizontalHeader()
        self.assertEqual(header.sortIndicatorSection(), 3)
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.AscendingOrder)
        self.assertEqual(self.win._click_sort_id, "interval_ms")
        self.assertEqual(self._col(3), ["9.00", "10.00", "11.00"])
        self.win.click_sort_order_combo.setCurrentIndex(self.win.click_sort_order_combo.findData("desc"))
        self._qapp.processEvents()
        self.assertEqual(header.sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)
        self.assertEqual(self.win._click_sort_descending, True)
        self.assertEqual(self._col(3), ["11.00", "10.00", "9.00"])

    def test_numeric_decimals_and_negatives(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "elapsed_ms": 100.0, "interval_ms": 10.01, "hold_ms": 10.01, "reference_delta_ms": 2.0},
            {"index": 2, "elapsed_ms": 9.9, "interval_ms": 9.9, "hold_ms": 9.9, "reference_delta_ms": -5.0},
            {"index": 3, "elapsed_ms": 10.0, "interval_ms": 10.0, "hold_ms": 10.0, "reference_delta_ms": 0.0},
        ])})
        self._show_click_data()
        self._click_header(3)
        self.assertEqual(self._col(3), ["9.90", "10.00", "10.01"])
        self._click_header(7)
        self.assertEqual(self._col(7), ["-5.00", "0.00", "2.00"])
        self._click_header(1)
        from mouse_click_stability_analyzer.duration import format_elapsed_hms
        self.assertEqual(self._col(1), [format_elapsed_hms(9.9), format_elapsed_hms(10.0), format_elapsed_hms(100.0)])
        elapsed_roles = [
            self.win.results_click_table.item(r, 1).data(Qt.ItemDataRole.UserRole) for r in range(3)
        ]
        self.assertEqual(elapsed_roles, [9.9, 10.0, 100.0])
        self._click_header(4)
        self.assertEqual(self._col(4), ["9.90", "10.00", "10.01"])

    def test_header_descending_keeps_canonical_order_for_equal_values(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "interval_ms": 10.0, "button": "Left"},
            {"index": 2, "interval_ms": 20.0, "button": "Right"},
            {"index": 3, "interval_ms": 10.0, "button": "Left"},
            {"index": 4, "interval_ms": 20.0, "button": "Right"},
            {"index": 5, "interval_ms": 10.0, "button": "Left"},
        ])})
        self._show_click_data()
        self._click_header(3)
        self.assertEqual(self._col(0), ["1", "3", "5", "2", "4"])
        self._click_header(3)
        self.assertEqual(self.win.click_sort_order_combo.currentData(), "desc")
        self.assertEqual(self._col(3), ["20.00", "20.00", "10.00", "10.00", "10.00"])
        self.assertEqual(self._col(0), ["2", "4", "1", "3", "5"])
        self._click_header(2)
        self.assertEqual(self._col(0), ["1", "3", "5", "2", "4"])
        self._click_header(2)
        self.assertEqual(self.win.click_sort_column_combo.currentData(), "button")
        self.assertEqual(self.win.click_sort_order_combo.currentData(), "desc")
        self.assertEqual(self._col(0), ["2", "4", "1", "3", "5"])

    def test_blank_interval_last_both_directions(self):
        self.win._populate_click_table({"click_data": self._rows([
            {"index": 1, "interval_ms": None},
            {"index": 2, "interval_ms": 10.0},
            {"index": 3, "interval_ms": 2.0},
        ])})
        self._show_click_data()
        self._click_header(3)
        self.assertEqual(self._col(3), ["2.00", "10.00", ""])
        self.assertEqual(self._col(0)[-1], "1")
        self._click_header(3)
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
        self._show_click_data()
        before_ids = [id(e) for e in self.win.events]
        before_index = [e["click_index"] for e in self.win.events]
        before_model = [row["index"] for row in click_data]
        self._click_header(3)
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
        header = self.win.results_click_table.horizontalHeader()
        self.assertTrue(header.isSectionHidden(5))
        self.assertTrue(header.isSectionHidden(6))
        self.assertFalse(header.isSectionHidden(0))
        self.assertFalse(header.isSectionHidden(3))
        self.assertFalse(header.isSectionHidden(7))
        self.assertTrue(header.isSectionHidden(8))
        self.assertEqual(self.win.results_click_table.columnCount(), 9)

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
        self.assertIn("Reference interval", scatter_text)
        self.assertIn("Reference interval", interval_text)
        self.assertIn("Reference interval", hist_text)
        self.assertNotIn("Target beat", hist_text)
        self.assertTrue(self.win.results_scatter.data_aware_fit)
        self.assertTrue(self.win.results_interval_chart.data_aware_fit)
        self.assertTrue(self.win.results_distribution_chart.data_aware_fit)
        self.assertTrue(self.win.scatter.data_aware_fit)
        self.assertTrue(self.win.scatter.measurement_only_presentation)
        self.assertTrue(self.win.interval_chart.measurement_only_presentation)
        self.assertEqual(STRINGS["en"]["legend_on_cadence"], "Observation")
        self.assertEqual(STRINGS["en"]["legend_target"], "Target beat")
        self.win.scatter.set_theme(self.win.scatter.palette, labels)
        self.win.scatter.set_points([(25.0, 8.0, "TRUE_EXTRA_CLICK")], target_beat_ms=25.0)
        capture_text = [text for _, text in self.win.scatter.legend_entries()]
        self.assertIn("Host observation", capture_text)
        self.assertIn("Reference interval", capture_text)
        for banned in (
            "Short interval",
            "Very short interval",
            "Short hold",
            "Long interval",
            "Cadence vs reference",
            "Observation",
            "Target beat",
        ):
            self.assertNotIn(banned, capture_text)
        screening = ScatterChart()
        screening.set_data_aware_fit(True)
        screening.set_theme(screening.palette, labels)
        screening.set_points([(25.0, 8.0, "TRUE_EXTRA_CLICK")], target_beat_ms=25.0)
        screening_text = [text for _, text in screening.legend_entries()]
        self.assertIn("Short interval", screening_text)
        self.assertNotIn("Host observation", screening_text)

    def test_point_color_does_not_promote_heuristic_in_results(self):
        extra = self.win.results_scatter._point_color("TRUE_EXTRA_CLICK")
        chatter = self.win.results_scatter._point_color("CHATTER_BOUNCE")
        miss = self.win.results_scatter._point_color("MISS_OR_SLOW")
        host = self.win.results_scatter.palette.on_cadence
        self.assertEqual(extra, host)
        self.assertEqual(chatter, host)
        self.assertEqual(miss, host)
        self.assertEqual(self.win.scatter._point_color("TRUE_EXTRA_CLICK"), self.win.scatter.palette.on_cadence)
        screening = ScatterChart()
        self.assertNotEqual(screening._point_color("TRUE_EXTRA_CLICK"), screening.palette.on_cadence)
        self.assertIn("Host observation", self.win.results_chart_legend_help.text())
        self.assertIn("not a PASS/FAIL threshold", self.win.results_chart_legend_help.text())
        self.assertNotIn("Target beat", self.win.results_chart_legend_help.text())


if __name__ == "__main__":
    unittest.main()
