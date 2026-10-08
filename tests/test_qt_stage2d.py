"""Stage 2D Qt: Configured Interval Range Setup, Capture, Results, Click Data."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.interval_comparison import (
    BASIS_MILLISECONDS,
    BASIS_PERCENT,
    POSITION_ABOVE,
    POSITION_BELOW,
    POSITION_NOT_COMPARABLE,
    POSITION_WITHIN,
)
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.click_table_sort import CLICK_TABLE_ID_TO_INDEX
from mouse_click_stability_analyzer.qt_shell.styles import get_palette


def _make_qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class QtStage2DIntervalComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
        if cls._qapp is None:
            raise unittest.SkipTest("PySide6 QApplication unavailable")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()
        self.win.ensure_raw_input = lambda: None
        self.win._cursor_in_test_area = lambda: True
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self.win.listening = True

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._tmp.cleanup()

    def _settle(self):
        for _ in range(4):
            self._qapp.processEvents()

    def _configure_fixture(self, *, hz="8", window="20", compare=False, basis=BASIS_PERCENT, value="20"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(window)
        self.win.auto_stop_off.setChecked(True)
        self.win._interval_cmp_updating = True
        idx = self.win.interval_cmp_unit.findData(basis)
        self.win.interval_cmp_unit.setCurrentIndex(idx if idx >= 0 else 0)
        self.win.interval_cmp_value.setText(value)
        self.win._interval_cmp_updating = False
        if compare:
            self.win.interval_cmp_on.setChecked(True)
        else:
            self.win.interval_cmp_off.setChecked(True)
        self.win._refresh_interval_comparison_context()
        self._settle()

    def _run(self, offsets, **kwargs):
        if self.win._lifecycle_state() == "completed":
            self.win.edit_setup_new_run()
            self._settle()
            self.win.listening = True
        self._configure_fixture(**kwargs)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.04, {})
        for off in offsets[1:]:
            press = t0 + off / 1000.0
            self.win.record_click("Left", press, press + 0.04, {})
        self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()
        self._settle()

    def test_comparison_disabled_by_default(self):
        self.win.radio_fixture.setChecked(True)
        self._settle()
        self.assertTrue(self.win.interval_cmp_off.isChecked())
        self.assertFalse(self.win.settings().get("interval_comparison_enabled"))
        self.assertFalse(self.win.interval_cmp_detail.isVisibleTo(self.win))

    def test_manual_hides_comparison_but_can_keep_stored_state(self):
        self._configure_fixture(compare=True, value="20")
        self.assertTrue(self.win.interval_cmp_box.isVisibleTo(self.win))
        self.win.radio_manual.setChecked(True)
        self._settle()
        self.assertFalse(self.win.interval_cmp_box.isVisibleTo(self.win))
        stored = self.win.settings()
        self.assertTrue(stored.get("interval_comparison_enabled"))
        self.assertEqual(stored.get("interval_comparison_value"), 20.0)
        self.win.radio_fixture.setChecked(True)
        self._settle()
        self.assertTrue(self.win.interval_cmp_box.isVisibleTo(self.win))
        self.assertTrue(self.win.interval_cmp_on.isChecked())
        self.assertEqual(self.win.interval_cmp_value.text().strip(), "20")

    def test_setup_8hz_20_percent_bounds(self):
        self._configure_fixture(compare=True, value="20")
        self.assertIn("25.00", self.win.interval_cmp_derived.text())
        self.assertIn("100.00", self.win.interval_cmp_bounds.text())
        self.assertIn("150.00", self.win.interval_cmp_bounds.text())
        self.assertTrue(self.win.interval_cmp_derived.objectName() == "DerivedValue")

    def test_unit_switch_preserves_bounds(self):
        self._configure_fixture(compare=True, value="20")
        self.win.interval_cmp_unit.setCurrentIndex(self.win.interval_cmp_unit.findData(BASIS_MILLISECONDS))
        self._settle()
        self.assertEqual(self.win.interval_cmp_unit.currentData(), BASIS_MILLISECONDS)
        self.assertEqual(float(self.win.interval_cmp_value.text()), 25.0)
        self.assertIn("20.00", self.win.interval_cmp_derived.text())
        self.assertIn("100.00", self.win.interval_cmp_bounds.text())
        self.assertIn("150.00", self.win.interval_cmp_bounds.text())

    def test_5hz_20ms_example(self):
        self._configure_fixture(hz="5", compare=True, basis=BASIS_MILLISECONDS, value="20")
        self.assertIn("10.00", self.win.interval_cmp_derived.text())
        self.assertIn("180.00", self.win.interval_cmp_bounds.text())
        self.assertIn("220.00", self.win.interval_cmp_bounds.text())

    def test_rate_change_keeps_percent_authoritative(self):
        self._configure_fixture(compare=True, value="20")
        self.win.hz_combo.setCurrentText("10")
        self._settle()
        self.assertEqual(self.win.interval_cmp_unit.currentData(), BASIS_PERCENT)
        self.assertEqual(float(self.win.interval_cmp_value.text()), 20.0)
        self.assertIn("20.00", self.win.interval_cmp_derived.text())
        self.assertIn("80.00", self.win.interval_cmp_bounds.text())
        self.assertIn("120.00", self.win.interval_cmp_bounds.text())

    def test_invalid_percent_blocks_lock(self):
        self._configure_fixture(compare=True, value="101")
        self.assertFalse(self.win.lock_profile())
        self.assertEqual(self.win._profile_validation_error_key, "interval_comparison_percent_range")

    def test_negative_tolerance_blocks_lock(self):
        self._configure_fixture(compare=True, value="-1")
        self.assertFalse(self.win.lock_profile())
        self.assertEqual(self.win._profile_validation_error_key, "interval_comparison_invalid")

    def test_capture_and_results_mark_within_outside_without_verdict(self):
        self._run([0, 125, 215, 385], compare=True, value="20")
        self.assertEqual(self.win.scatter.configured_range, (100.0, 150.0))
        self.assertEqual(self.win.interval_chart.configured_range, (100.0, 150.0))
        legend = " ".join(label for _color, label in self.win.scatter.legend_entries())
        self.assertIn("Within configured range", legend)
        self.assertIn("Outside configured range", legend)
        self.assertNotIn("PASS", legend)
        self.assertNotIn("FAIL", legend)
        self.assertNotIn("WARN", legend)
        facts = self.win._completed_run_facts()
        model = facts["model"]
        self.assertEqual(model["run"]["run_status"], "COMPLETE")
        positions = [row["range_position"] for row in model["click_data"]]
        self.assertEqual(positions[0], POSITION_NOT_COMPARABLE)
        self.assertEqual(positions[1], POSITION_WITHIN)
        self.assertEqual(positions[2], POSITION_BELOW)
        self.assertEqual(positions[3], POSITION_ABOVE)
        self.assertEqual(self.win.results_interval_chart.configured_range, (100.0, 150.0))
        self.assertEqual(self.win.results_scatter.configured_range, (100.0, 150.0))
        self.assertEqual(self.win.results_distribution_chart.configured_range, (100.0, 150.0))
        summary = self.win.results_comparison_summary.text()
        self.assertIn("3", summary)
        self.assertTrue(self.win.results_comparison_summary.isVisibleTo(self.win))
        self.assertNotIn("PASS", summary)
        self.assertNotIn("yield", summary.lower())

        table = self.win.results_click_table
        col = CLICK_TABLE_ID_TO_INDEX["range_position"]
        self.assertFalse(table.horizontalHeader().isSectionHidden(col))
        self.assertEqual(table.item(0, col).text(), "—")
        self.assertEqual(table.item(1, col).text(), self.win._tr("range_position_within"))
        self.assertEqual(table.item(2, col).text(), self.win._tr("range_position_below"))
        self.assertEqual(table.item(3, col).text(), self.win._tr("range_position_above"))
        extra = QColor(get_palette(self.win.theme).extra)
        self.assertEqual(table.item(2, col).foreground().color().name(), extra.name())
        self.assertEqual(table.item(3, col).foreground().color().name(), extra.name())

        chart = self.win.results_interval_chart
        chart.fit_data()
        bounds = chart.visible_bounds()
        self.assertIsNotNone(bounds)
        self.assertGreaterEqual(max(pt[1] for pt in model["analysis"]["interval_series"]), 160)

    def test_range_column_hidden_when_disabled_or_manual(self):
        self._run([0, 125, 250], compare=False)
        col = CLICK_TABLE_ID_TO_INDEX["range_position"]
        self.assertTrue(self.win.results_click_table.horizontalHeader().isSectionHidden(col))
        self.assertFalse(self.win.results_comparison_summary.isVisibleTo(self.win))
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()
        self.win = qt_app.MainWindow(report_root=Path(self._tmp.name))
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()
        self.win.ensure_raw_input = lambda: None
        self.win._cursor_in_test_area = lambda: True
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self.win.listening = True
        self.win.radio_manual.setChecked(True)
        self.win.auto_stop_off.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.04, {})
        self.win.record_click("Left", t0 + 0.125, t0 + 0.165, {})
        self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()
        self._settle()
        self.assertTrue(self.win.results_click_table.horizontalHeader().isSectionHidden(col))
        self.assertIsNone(self.win.scatter.configured_range)

    def test_changing_setup_after_complete_does_not_recolor_old_run(self):
        self._run([0, 125, 250], compare=True, value="20")
        self.assertEqual(self.win.results_interval_chart.configured_range, (100.0, 150.0))
        self.win.interval_cmp_value.setText("5")
        self.win._refresh_interval_comparison_context()
        facts = self.win._completed_run_facts()
        self.win._refresh_results_charts(facts["model"])
        self.assertEqual(self.win.results_interval_chart.configured_range, (100.0, 150.0))
        self.assertEqual(facts["model"]["interval_comparison"]["configured_value"], 20.0)

    def _layer_kinds(self, chart):
        return [kind for kind, _value in chart.range_layers()]

    def test_configured_range_band_layers_on_results_charts(self):
        self._run([0, 125, 215, 385], compare=True, value="20")
        expected = ["band_lower", "band_upper", "lower_bound", "upper_bound", "reference"]
        for chart in (
            self.win.results_scatter, self.win.results_interval_chart, self.win.results_distribution_chart,
            self.win.scatter, self.win.interval_chart,
        ):
            with self.subTest(chart=type(chart).__name__):
                self.assertEqual(self._layer_kinds(chart), expected)
                values = dict((k, v) for k, v in chart.range_layers())
                self.assertEqual(values["lower_bound"], 100.0)
                self.assertEqual(values["upper_bound"], 150.0)
                self.assertEqual(values["reference"], 125.0)
                labels = [label for _c, label in chart.legend_entries()]
                self.assertEqual(labels.count("Configured range"), 1)
                self.assertIn("Configured reference", labels)
                self.assertFalse(chart.grab().isNull())
        for chart in (self.win.results_scatter, self.win.results_interval_chart):
            labels = [label for _c, label in chart.legend_entries()]
            self.assertLess(labels.index("Configured range"), labels.index("Within configured range"))
            self.assertLess(labels.index("Outside configured range"), labels.index("Configured reference"))
        hist_labels = [label for _c, label in self.win.results_distribution_chart.legend_entries()]
        self.assertNotIn("Within configured range", hist_labels)
        self.assertNotIn("Outside configured range", hist_labels)
        pal = get_palette(self.win.theme)
        self.assertNotIn(pal.range_band, (pal.interval_fill, pal.on_cadence, pal.extra, pal.overlay, pal.target_line))
        self.assertNotIn(pal.range_edge, (pal.on_cadence, pal.extra, pal.overlay, pal.target_line))

    def test_histogram_bins_unchanged_by_range(self):
        offsets = [0, 125, 215, 385, 500]
        self._run(offsets, compare=False)
        bins_off = [dict(b) for b in self.win.results_distribution_chart.bins]
        self._run(offsets, compare=True, value="20")
        self.assertEqual([dict(b) for b in self.win.results_distribution_chart.bins], bins_off)
        model = self.win._completed_run_facts()["model"]
        self.assertEqual(self.win.results_distribution_chart.bins, list(model["analysis"]["histogram"]))

    def test_no_band_when_disabled_or_manual(self):
        self._run([0, 125, 250], compare=False)
        for chart in (self.win.results_scatter, self.win.results_interval_chart, self.win.results_distribution_chart):
            self.assertEqual(self._layer_kinds(chart), ["reference"])
            labels = [label for _c, label in chart.legend_entries()]
            self.assertNotIn("Configured range", labels)
            self.assertEqual(chart.point_range_positions() if hasattr(chart, "point_range_positions") else [], [])

    def test_hold_over_time_view(self):
        self._run([0, 125, 215, 385], compare=True, value="20")
        combo = self.win.results_view_combo
        keys = [combo.itemData(i) for i in range(combo.count())]
        self.assertEqual(keys[:4], ["interval", "distribution", "hold", "scatter"])
        self.assertEqual(combo.currentData(), "distribution")
        self.assertIn(self.win._tr("hold_over_time"), [combo.itemText(i) for i in range(combo.count())])
        combo.setCurrentIndex(combo.findData("hold"))
        self._settle()
        chart = self.win.results_hold_chart
        self.assertIs(self.win.results_chart_stack.currentWidget(), chart)
        self.assertIs(self.win._active_results_chart(), chart)
        self.assertTrue(self.win.btn_results_chart_fit.isEnabled())
        model = self.win._completed_run_facts()["model"]
        hold_series = model["analysis"]["hold_series"]
        self.assertEqual(len(hold_series), 4)
        self.assertEqual(chart.series, hold_series)
        self.assertTrue(all(h >= 0 and x >= 0 for x, h in hold_series))
        self.assertAlmostEqual(hold_series[0][1], 40.0, places=3)
        self.assertIsNone(chart.configured_range)
        self.assertIsNone(chart.target_beat_ms)
        self.assertEqual(chart.range_layers(), [])
        self.assertEqual(chart.point_range_positions(), [])
        labels = [label for _c, label in chart.legend_entries()]
        for banned in ("Configured range", "Within configured range", "Outside configured range", "Configured reference"):
            self.assertNotIn(banned, labels)
        chart.fit_data()
        xmin, _xmax, ymin, _ymax = chart.visible_bounds()
        self.assertGreaterEqual(ymin, 0.0)
        self.assertGreaterEqual(xmin, 0.0)
        chart.zoom_in()
        chart.reset_view()
        self.assertFalse(chart.grab().isNull())

    def test_overlay_is_never_reclassified_by_base_range(self):
        # Run B: 110-140 ms range, 145 ms interval -> Above in its own frozen model.
        self._run([0, 145], compare=True, basis=BASIS_MILLISECONDS, value="15")
        b_model = self.win._completed_run_facts()["model"]
        self.assertEqual(b_model["interval_comparison"]["lower_bound_ms"], 110.0)
        self.assertEqual(b_model["click_data"][1]["range_position"], POSITION_ABOVE)
        b_events = [dict(e) for e in self.win.events]
        # Run A: 100-150 ms range, 145 ms interval -> Within.
        self._run([0, 145], compare=True, basis=BASIS_PERCENT, value="20")
        a_model = self.win._completed_run_facts()["model"]
        self.assertEqual(a_model["click_data"][1]["range_position"], POSITION_WITHIN)
        self.win.overlay_events = b_events
        self.win._refresh_results_charts(a_model)
        for chart in (self.win.results_interval_chart, self.win.results_scatter):
            with self.subTest(chart=type(chart).__name__):
                self.assertEqual(chart.configured_range, (100.0, 150.0))
                self.assertEqual(chart.point_range_positions(), [POSITION_WITHIN])
        overlay_ivs = [y for _x, y in self.win.results_interval_chart.overlay_series]
        self.assertTrue(any(abs(v - 145.0) < 1e-6 for v in overlay_ivs))
        self.assertEqual(len(self.win.results_scatter.overlay_points), 1)
        self.assertEqual(self.win.results_distribution_chart.configured_range, (100.0, 150.0))
        self.assertEqual(b_model["click_data"][1]["range_position"], POSITION_ABOVE)
        self.assertEqual(self.win.results_hold_chart.range_layers(), [])

    def test_summary_lives_in_analysis_not_run_context(self):
        self._run([0, 125, 215, 385], compare=True, value="20")
        summary = self.win.results_comparison_summary
        self.assertFalse(self.win.results_summary_card.isAncestorOf(summary))
        self.assertNotIn("Comparable", self.win.results_context_label.text())
        text = summary.text()
        for fact in ("Comparable intervals: 3", "Within configured range: 1", "Outside configured range: 2",
                     "Below configured range: 1", "Above configured range: 1", "33.33%"):
            self.assertIn(fact, text)

    def test_rate_change_invalidates_ms_value_without_clamping(self):
        self._configure_fixture(hz="5", compare=True, basis=BASIS_MILLISECONDS, value="120")
        self.assertFalse(self.win.interval_cmp_error.isVisibleTo(self.win))
        self.assertIn("80.00", self.win.interval_cmp_bounds.text())
        self.win.hz_combo.setCurrentText("10")
        self._settle()
        self.assertEqual(self.win.interval_cmp_value.text(), "120")
        self.assertEqual(self.win.interval_cmp_unit.currentData(), BASIS_MILLISECONDS)
        self.assertTrue(self.win.interval_cmp_error.isVisibleTo(self.win))
        self.assertEqual(self.win.interval_cmp_error.text(), self.win._tr("interval_comparison_ms_range"))
        self.assertTrue(self.win.interval_cmp_bounds.text().endswith("—"))
        self.assertFalse(self.win.lock_profile())
        self.assertEqual(self.win._profile_validation_error_key, "interval_comparison_ms_range")
        self.assertEqual(self.win.interval_cmp_value.text(), "120")
        self.win.interval_cmp_value.setText("50")
        self._settle()
        self.assertFalse(self.win.interval_cmp_error.isVisibleTo(self.win))
        self.assertIn("50.00", self.win.interval_cmp_bounds.text())
        self.assertIn("150.00", self.win.interval_cmp_bounds.text())
        self.assertTrue(self.win.lock_profile())

    def test_sections_are_separately_headed(self):
        self.win.radio_fixture.setChecked(True)
        self._settle()
        self.assertIn("INTERVAL COMPARISON", self.win.lbl_interval_comparison.text().upper())
        self.assertIn("SCHEDULE ASSOCIATION", self.win.lbl_schedule_association.text().upper())
        self.assertNotEqual(self.win.lbl_interval_comparison.text(), self.win.lbl_schedule_association.text())


if __name__ == "__main__":
    unittest.main()
