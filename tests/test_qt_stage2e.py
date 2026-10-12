"""Stage 2E: Setup association removal, chart naming, distribution, navigation."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from association_support import apply_explicit_association
from mouse_click_stability_analyzer.completed_result import histogram_observation_count
from mouse_click_stability_analyzer.i18n import STRINGS
from mouse_click_stability_analyzer.interval_comparison import (
    BASIS_PERCENT,
    POSITION_ABOVE,
    POSITION_BELOW,
    POSITION_WITHIN,
)
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import (
    AUTO_STOP_ENABLED_KEY,
    FIXTURE_TIMING_TOLERANCE_KEY,
    WheelSafeComboBox,
)
from mouse_click_stability_analyzer.qt_shell.charts import WHEEL_ANGLE_NOTCH


def _make_qapp():
    return QApplication.instance() or QApplication([])


def _wheel_event(widget, local, *, angle=0):
    pos = QPointF(local)
    return QWheelEvent(
        pos,
        QPointF(widget.mapToGlobal(pos.toPoint())),
        QPoint(0, 0),
        QPoint(0, int(angle)),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


class QtStage2ETests(unittest.TestCase):
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
        self.win.resize(1280, 800)

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._tmp.cleanup()

    def _settle(self):
        for _ in range(6):
            self._qapp.processEvents()

    def _configure_normal_fixture(self, *, hz="8", compare=True, value="20", auto_stop=False):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText("10")
        (self.win.auto_stop_on if auto_stop else self.win.auto_stop_off).setChecked(True)
        if auto_stop:
            self.win.auto_stop_sec_combo.setCurrentText("1")
        self.win._interval_cmp_updating = True
        idx = self.win.interval_cmp_unit.findData(BASIS_PERCENT)
        self.win.interval_cmp_unit.setCurrentIndex(idx if idx >= 0 else 0)
        self.win.interval_cmp_value.setText(value)
        self.win._interval_cmp_updating = False
        if compare:
            self.win.interval_cmp_on.setChecked(True)
        else:
            self.win.interval_cmp_off.setChecked(True)

    def _run(self, offsets, *, association_ms=None, **kwargs):
        if self.win._lifecycle_state() == "completed":
            self.win.edit_setup_new_run()
            self._settle()
            self.win.listening = True
        self._configure_normal_fixture(**kwargs)
        self.assertTrue(self.win.lock_profile())
        if association_ms is not None:
            apply_explicit_association(self.win, association_ms)
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

    def test_schedule_association_hidden_from_normal_setup(self):
        self.win.radio_fixture.setChecked(True)
        self._settle()
        for widget in (
            self.win.lbl_schedule_association, self.win.timing_tol_label,
            self.win.timing_tol_edit, self.win.assoc_context_box,
        ):
            self.assertFalse(widget.isVisibleTo(self.win), widget)

    def test_normal_lock_ignores_hidden_field_and_does_not_stamp_w(self):
        self._configure_normal_fixture()
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, snap)
        self.assertNotEqual(snap.get(FIXTURE_TIMING_TOLERANCE_KEY), 10)
        self.assertNotEqual(snap.get(FIXTURE_TIMING_TOLERANCE_KEY), 0)

    def test_settings_fixture_omits_association_key(self):
        self.win.radio_fixture.setChecked(True)
        self.win.timing_tol_edit.setText("10")
        settings = self.win.settings()
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, settings)
        self.win.radio_manual.setChecked(True)
        manual = self.win.settings()
        self.assertIsNone(manual.get(FIXTURE_TIMING_TOLERANCE_KEY))

    def test_normal_run_omits_association_context_and_timing_chart(self):
        self._run([0, 125, 250, 375])
        ctx = self.win.results_context_label.text()
        self.assertNotIn("Schedule Association Window", ctx)
        self.assertNotIn("±0.00", ctx)
        self.assertNotIn("±10", ctx)
        combo = self.win.results_view_combo
        texts = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(texts, [
            "Elapsed time vs Click interval",
            "Click interval distribution",
            "Elapsed time vs Hold duration",
            "Click interval vs Hold duration",
        ])
        self.assertEqual(
            [combo.itemData(i) for i in range(combo.count())],
            ["interval", "distribution", "hold", "scatter"],
        )
        self.assertEqual(combo.findData("timing"), -1)
        self.assertIsNone(self.win.host_evidence_snapshot)

    def test_historical_association_remains_readable(self):
        self._run([0, 25, 50, 75], association_ms=2.0, hz="40", auto_stop=True, compare=False)
        self.assertEqual(self.win.locked[FIXTURE_TIMING_TOLERANCE_KEY], 2.0)
        self.assertIsNotNone(self.win.host_evidence_snapshot)
        ctx = self.win.results_context_label.text()
        self.assertIn("Schedule Association Window ±2.00 ms", ctx)
        combo = self.win.results_view_combo
        self.assertGreaterEqual(combo.findData("timing"), 0)
        self.assertEqual(combo.itemText(combo.findData("timing")), "Elapsed time vs Schedule timing error")

    def test_capture_chart_names_and_axes(self):
        self._run([0, 125, 250])
        self.assertEqual(self.win.scatter.title, "Click interval vs Hold duration")
        self.assertEqual(self.win.interval_chart.title, "Elapsed time vs Click interval")
        self.assertEqual(STRINGS["en"]["axis_interval_ms"], "Click interval (ms)")
        self.assertEqual(STRINGS["en"]["axis_hold_ms"], "Hold duration (ms)")
        self.assertEqual(STRINGS["en"]["axis_elapsed"], "Elapsed time")
        self.assertEqual(STRINGS["en"]["axis_count"], "Observation count")
        self.assertEqual(self.win.btn_view_stability.text(), "Click interval vs Hold duration")
        self.assertEqual(self.win.btn_view_interval.text(), "Elapsed time vs Click interval")

    def test_results_chart_titles_follow_x_then_y(self):
        self._run([0, 125, 250, 375], compare=True, value="20")
        self.assertEqual(self.win.results_interval_chart.title, "Elapsed time vs Click interval")
        self.assertEqual(self.win.results_distribution_chart.title, "Click interval distribution")
        self.assertEqual(self.win.results_hold_chart.title, "Elapsed time vs Hold duration")
        self.assertEqual(self.win.results_scatter.title, "Click interval vs Hold duration")
        for name in ("Click interval vs Elapsed time", "Hold duration vs Elapsed time"):
            self.assertNotIn(name, STRINGS["en"].values())

    def _evidence_tab_visible(self) -> bool:
        tabs = self.win.results_tabs
        return tabs.isTabVisible(tabs.indexOf(self.win.results_evidence_page))

    def _assert_association_unavailable(self):
        self.assertFalse(self._evidence_tab_visible())
        self.assertNotEqual(self.win.results_tabs.currentWidget(), self.win.results_evidence_page)
        text = self.win.results_evidence_na.text()
        self.assertEqual(text, "Schedule Association evidence is not available for this run.")
        for stale in ("Auto Stop", "duration", "±0.00", "Matched", "Unmatched", "Ambiguous"):
            self.assertNotIn(stale, text)
            self.assertNotIn(stale, self.win.results_evidence_text.toPlainText())

    def test_evidence_tab_hidden_for_normal_fixture_run(self):
        self._run([0, 125, 250, 375])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)
        self._assert_association_unavailable()

    def test_evidence_tab_hidden_with_auto_stop_duration_and_no_association(self):
        self._run([0, 125, 250, 375], auto_stop=True)
        self.assertIs(self.win.locked[AUTO_STOP_ENABLED_KEY], True)
        self.assertGreater(float(self.win.locked.get("duration_sec") or 0), 0)
        self.assertIsNone(self.win.host_evidence_snapshot)
        self._assert_association_unavailable()

    def test_evidence_tab_hidden_for_auto_stop_off_run(self):
        self._run([0, 125, 250, 375], auto_stop=False)
        self.assertIs(self.win.locked[AUTO_STOP_ENABLED_KEY], False)
        self._assert_association_unavailable()

    def test_evidence_tab_visible_for_historical_association_run(self):
        self._run([0, 25, 50, 75], association_ms=2.0, hz="40", auto_stop=True, compare=False)
        self.assertIsNotNone(self.win.host_evidence_snapshot)
        self.assertTrue(self._evidence_tab_visible())
        self.win.show()
        self.win._show_workflow_page("results")
        self.win.results_tabs.setCurrentWidget(self.win.results_evidence_page)
        self._settle()
        self.assertTrue(self.win.results_evidence_body.isVisibleTo(self.win))
        self.assertIn("±2.000 ms", self.win.results_evidence_text.toPlainText() + self._evidence_cells_text())
        self.win.new_run()
        self._settle()
        self.assertFalse(self._evidence_tab_visible())

    def _evidence_cells_text(self) -> str:
        return "\n".join(f"{k.text()} {v.text()}" for k, v in self.win._results_evidence_cells)

    def test_results_selector_and_distribution_title(self):
        self._run([0, 125, 250, 375], compare=True, value="20")
        combo = self.win.results_view_combo
        self.assertEqual(combo.currentData(), "distribution")
        chart = self.win.results_distribution_chart
        self.assertEqual(chart.title, "Click interval distribution")
        labels = [label for _c, label in chart.legend_entries()]
        self.assertIn("Below configured interval range", labels)
        self.assertIn("Within configured interval range", labels)
        self.assertIn("Above configured interval range", labels)
        self.assertIn("Configured interval range", labels)

    def test_distribution_bounds_and_count_identity(self):
        # 8 Hz, ±20% -> 100-150 ms. Offsets are press times.
        self._run([0, 90, 215, 365, 520], compare=True, value="20")
        model = self.win._completed_run_facts()["model"]
        comparison = model["interval_comparison"]
        self.assertEqual(comparison["lower_bound_ms"], 100.0)
        self.assertEqual(comparison["upper_bound_ms"], 150.0)
        rows = [row for row in model["click_data"] if row["interval_ms"] is not None]
        by_pos = {POSITION_BELOW: 0, POSITION_WITHIN: 0, POSITION_ABOVE: 0}
        for row in rows:
            by_pos[row["range_position"]] += 1
        self.assertEqual(by_pos[POSITION_BELOW] + by_pos[POSITION_WITHIN] + by_pos[POSITION_ABOVE], len(rows))
        bins = list(self.win.results_distribution_chart.bins)
        self.assertEqual(histogram_observation_count(bins), len(rows))
        for item in bins:
            lo, hi, position = float(item["lo"]), float(item["hi"]), item.get("position")
            if position == POSITION_BELOW:
                self.assertLessEqual(hi, 100.0)
            elif position == POSITION_WITHIN:
                self.assertGreaterEqual(lo, 100.0)
                self.assertLessEqual(hi, 150.0)
            elif position == POSITION_ABOVE:
                self.assertGreaterEqual(lo, 150.0)

    def _prepare_results_chart(self, key: str):
        self.win.show()
        self.win._show_workflow_page("results")
        combo = self.win.results_view_combo
        combo.setCurrentIndex(combo.findData(key))
        self._settle()
        chart = {
            "interval": self.win.results_interval_chart,
            "distribution": self.win.results_distribution_chart,
            "hold": self.win.results_hold_chart,
            "scatter": self.win.results_scatter,
        }[key]
        chart.resize(720, 360)
        self._settle()
        return chart

    def _zoom_until_x_scroll(self, chart, *, steps: int = 12):
        domain = chart._fitted_x_domain()
        self.assertIsNotNone(domain)
        for _ in range(steps):
            chart.zoom_in()
            bounds = chart.visible_bounds()
            if bounds is not None and (bounds[1] - bounds[0]) < (domain[1] - domain[0]) * 0.99:
                break
        self._settle()
        self.assertTrue(chart._x_scroll.isVisibleTo(chart))

    def test_zoom_pan_scrollbar_do_not_rebin(self):
        self._run([0, 125, 250, 375, 2000], compare=True, value="20")
        chart = self._prepare_results_chart("distribution")
        before = [dict(item) for item in chart.bins]
        chart.fit_data()
        self._zoom_until_x_scroll(chart)
        self.assertEqual([dict(item) for item in chart.bins], before)
        chart._x_scroll.setValue(chart._x_scroll.maximum())
        self._settle()
        self.assertEqual([dict(item) for item in chart.bins], before)
        chart.fit_data()
        self.assertEqual([dict(item) for item in chart.bins], before)
        intervals = [
            row["interval_ms"]
            for row in self.win._completed_run_facts()["model"]["click_data"]
            if row["interval_ms"] is not None
        ]
        xmin, xmax, _ymin, _ymax = chart.visible_bounds()
        self.assertGreaterEqual(xmax, max(intervals))

    def test_fit_all_data_and_hidden_reset(self):
        self._run([0, 300, 600, 900, 2000], compare=False)
        self.assertFalse(self.win.btn_chart_reset.isVisibleTo(self.win))
        self.assertFalse(self.win.btn_results_chart_reset.isVisibleTo(self.win))
        self.assertEqual(self.win.btn_chart_fit.toolTip(), "Fit All Data")
        self.assertEqual(self.win.btn_results_chart_fit.toolTip(), "Fit All Data")
        chart = self._prepare_results_chart("interval")
        chart.fit_data()
        _xmin, xmax, _ymin, ymax = chart.visible_bounds()
        self.assertGreaterEqual(ymax, 1100.0)
        self._zoom_until_x_scroll(chart)
        zoomed = chart.visible_bounds()
        chart._x_scroll.setValue(chart._x_scroll.maximum())
        self._settle()
        moved = chart.visible_bounds()
        self.assertNotEqual(moved[0], zoomed[0])
        series = list(chart.series)
        chart.fit_data()
        self.assertEqual(list(chart.series), series)
        _xmin, xmax, _ymin, ymax = chart.visible_bounds()
        self.assertGreaterEqual(ymax, 1100.0)

    def test_wheel_over_plot_zooms_outside_ignored(self):
        self._run([0, 125, 250, 375])
        combo = self.win.results_view_combo
        combo.setCurrentIndex(combo.findData("interval"))
        self._settle()
        chart = self.win.results_interval_chart
        chart.resize(640, 360)
        chart.fit_data()
        self._settle()
        before = chart.visible_bounds()
        plot = chart._plot_rect()
        over = QPointF(plot.center())
        event = _wheel_event(chart, over, angle=WHEEL_ANGLE_NOTCH)
        QApplication.sendEvent(chart, event)
        self.assertTrue(event.isAccepted())
        after = chart.visible_bounds()
        self.assertNotEqual(after, before)
        title = QPointF(chart.width() / 2.0, 8.0)
        outside = _wheel_event(chart, title, angle=-WHEEL_ANGLE_NOTCH)
        QApplication.sendEvent(chart, outside)
        self.assertFalse(outside.isAccepted())

    def test_per_chart_nav_independent_and_new_run_clears(self):
        self._run([0, 125, 250, 2000])
        combo = self.win.results_view_combo
        combo.setCurrentIndex(combo.findData("interval"))
        self._settle()
        interval = self.win.results_interval_chart
        dist = self.win.results_distribution_chart
        interval.zoom_in()
        interval.zoom_in()
        interval_view = interval.visible_bounds()
        combo.setCurrentIndex(combo.findData("distribution"))
        self._settle()
        dist.zoom_in()
        dist_view = dist.visible_bounds()
        combo.setCurrentIndex(combo.findData("interval"))
        self._settle()
        self.assertEqual(interval.visible_bounds(), interval_view)
        combo.setCurrentIndex(combo.findData("distribution"))
        self._settle()
        self.assertEqual(dist.visible_bounds(), dist_view)
        self.win.new_run()
        self._settle()
        self.assertIsNone(interval._user_view)
        self.assertFalse(interval.zoom_locked)
        self.assertIsNone(dist._user_view)

    def test_setup_combos_remain_wheel_safe(self):
        for widget in (
            self.win.button_combo, self.win.hz_combo,
            self.win.interval_cmp_unit, self.win.auto_stop_sec_combo,
        ):
            self.assertIsInstance(widget, WheelSafeComboBox)

    def test_auto_stop_evidence_still_frozen(self):
        self._run([0, 125, 250], auto_stop=True)
        self.assertIs(self.win.locked[AUTO_STOP_ENABLED_KEY], True)
        self.win.auto_stop_off.setChecked(True)
        model = self.win._completed_run_facts()["model"]
        self.assertIs(model["run"][AUTO_STOP_ENABLED_KEY], True)
        self.assertIs(self.win.locked[AUTO_STOP_ENABLED_KEY], True)

    def test_overlay_histogram_stays_neutral(self):
        self._run([0, 145], compare=True, value="20")
        a_model = self.win._completed_run_facts()["model"]
        b_events = [dict(e) for e in self.win.events]
        self.win.overlay_events = b_events
        self.win._refresh_results_charts(a_model)
        overlay = self.win.results_distribution_chart.overlay_bins
        self.assertTrue(overlay)
        self.assertTrue(all(item.get("position") is None for item in overlay))


if __name__ == "__main__":
    unittest.main()
