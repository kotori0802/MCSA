"""Stage 2C workflow: Auto Stop, Setup guard, Results default/nav, Generate Report."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QPushButton

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.qt_shell import app as qt_app


def _make_qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class QtStage2CWorkflowTests(unittest.TestCase):
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

    def _run(self, offsets, *, manual=False, auto_sec=None):
        if manual:
            self.win.radio_manual.setChecked(True)
        else:
            self.win.radio_fixture.setChecked(True)
            self.win.hz_combo.setCurrentText("10")
            self.win.timing_tol_edit.setText("2")
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)
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

    def test_manual_auto_stop_off_on_and_persistence(self):
        self.win.radio_manual.setChecked(True)
        self.win._show_workflow_page("setup")
        self.win._apply_mode_fields()
        self.win.auto_stop_off.setChecked(True)
        self.assertTrue(self.win.auto_stop_on.isVisibleTo(self.win))
        self.assertTrue(self.win.auto_stop_off.isVisibleTo(self.win))
        self.assertIsNone(self.win._auto_stop_seconds())
        s_off = self.win.settings()
        self.assertEqual(s_off["duration_sec"], 0)
        self.win.auto_stop_on.setChecked(True)
        self.win.auto_stop_sec_combo.setCurrentText("00:00:20")
        self.assertEqual(self.win._auto_stop_seconds(), 20.0)
        self.assertEqual(self.win.settings()["duration_sec"], 20.0)
        self.win.auto_stop_sec_combo.setCurrentText("01:00:00")
        self.assertEqual(self.win._auto_stop_seconds(), 3600.0)
        self.assertEqual(self.win.settings()["duration_sec"], 3600.0)
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win.profile_locked_settings["duration_sec"], 3600.0)

    def test_setup_has_compact_measurement_only_guard(self):
        self.win._show_workflow_page("setup")
        self.assertEqual(self.win.setup_card_grid._cards, [self.win.setup_device_card, self.win.setup_config_card])
        self.assertIs(self.win.setup_screening_card.parentWidget(), self.win.setup_config_card)
        self.assertEqual(self.win.lbl_screening.text(), self.win._tr("analysis_scope"))
        self.assertEqual(self.win.lbl_screening_status.text(), self.win._tr("screening_measurement_only"))
        self.assertIn("approved", self.win.lbl_screening_note.text().lower())
        self.assertNotEqual(self.win.lbl_screening.text().upper(), "SCREENING")

    def test_results_default_is_interval_distribution(self):
        self._run([0, 25, 50, 75], manual=True)
        self.assertEqual(self.win.results_view_combo.currentData(), "distribution")
        self.assertEqual(self.win.results_chart_stack.currentIndex(), 1)
        self.win.results_view_combo.setCurrentIndex(self.win.results_view_combo.findData("interval"))
        self.assertEqual(self.win.results_view_combo.currentData(), "interval")
        facts = self.win._completed_run_facts()
        self.win._fill_analysis_views(facts["model"])
        self.assertEqual(self.win.results_view_combo.currentData(), "interval")

    def test_results_navigation_keeps_outliers_and_elapsed_floor(self):
        self._run([0, 25, 50, 400], manual=True)
        chart = self.win.results_interval_chart
        self.win.results_view_combo.setCurrentIndex(self.win.results_view_combo.findData("interval"))
        self._settle()
        facts = self.win._completed_run_facts()
        series = facts["model"]["analysis"]["interval_series"]
        self.assertGreaterEqual(max(pt[1] for pt in series), 300)
        chart.fit_data()
        bounds = chart.visible_bounds()
        self.assertIsNotNone(bounds)
        self.assertGreaterEqual(bounds[0], 0.0)
        chart.zoom_in()
        zoomed = chart.visible_bounds()
        self.assertIsNotNone(zoomed)
        self.assertGreaterEqual(zoomed[0], 0.0)
        chart.reset_view()
        hist = self.win.results_distribution_chart
        self.win.results_view_combo.setCurrentIndex(self.win.results_view_combo.findData("distribution"))
        hist.zoom_in()
        self.assertEqual(hist.bins, self.win.results_distribution_chart.bins)
        self.assertGreaterEqual(len(hist.bins), 1)

    def test_generate_report_writes_standard_bundle_once(self):
        self._run([0, 25, 50, 75])
        with mock.patch.object(qt_app, "write_reports", wraps=qt_app.write_reports) as writer, \
             mock.patch.object(qt_app.QMessageBox, "information"), \
             mock.patch.object(qt_app.QMessageBox, "critical") as critical:
            self.win.generate_report()
        writer.assert_called_once()
        critical.assert_not_called()
        self.assertTrue(self.win.report_written)
        root = Path(self.win.report_root)
        rid = self.win.run_id
        package = root / f"mcsa_{rid}"
        self.assertEqual([p.name for p in root.iterdir()], [package.name])
        self.assertEqual(
            sorted(p.name for p in package.iterdir()),
            sorted([
                f"mcsa_{rid}_events.csv", f"mcsa_{rid}_evidence.json",
                f"mcsa_{rid}_report.html", f"mcsa_{rid}_report.xlsx",
            ]),
        )
        self.assertFalse(list(root.rglob("mcsa_*_analysis.txt")))
        self.assertFalse(list(root.rglob("mcsa_*_summary.json")))
        self.assertFalse(list(root.rglob("mcsa_*_detail.json")))
        excel_buttons = [
            w for w in self.win.findChildren(QPushButton)
            if w.text() in ("Generate Excel", "Generate HTML")
        ]
        self.assertEqual(excel_buttons, [])

    def test_open_reports_folder_does_not_generate(self):
        self._run([0, 25, 50, 75])
        with mock.patch.object(qt_app, "write_reports") as writer, \
             mock.patch.object(qt_app.QDesktopServices, "openUrl", return_value=True) as opener:
            self.win.open_reports_folder()
        writer.assert_not_called()
        opener.assert_called_once()

    def _opened_path(self, opener) -> Path:
        url = opener.call_args[0][0]
        return Path(url.toLocalFile()).resolve()

    def test_open_reports_folder_root_before_generation(self):
        self._run([0, 25, 50, 75])
        with mock.patch.object(qt_app.QDesktopServices, "openUrl", return_value=True) as opener:
            self.win.open_reports_folder()
        self.assertEqual(self._opened_path(opener), Path(self.win.report_root).resolve())

    def test_open_reports_folder_current_package_after_generation(self):
        self._run([0, 25, 50, 75])
        with mock.patch.object(qt_app.QMessageBox, "information"):
            self.win.generate_report()
        self.assertTrue(self.win.report_written)
        expected = (Path(self.win.report_root) / f"mcsa_{self.win.run_id}").resolve()
        with mock.patch.object(qt_app, "write_reports") as writer, \
             mock.patch.object(qt_app.QDesktopServices, "openUrl", return_value=True) as opener:
            self.win.open_reports_folder()
        writer.assert_not_called()
        self.assertEqual(self._opened_path(opener), expected)

    def test_open_reports_folder_never_points_to_stale_run(self):
        self._run([0, 25, 50, 75])
        with mock.patch.object(qt_app.QMessageBox, "information"):
            self.win.generate_report()
        old_package = Path(self.win.report_paths["evidence_json"]).parent.resolve()
        self.win.run_id = "different_run"
        with mock.patch.object(qt_app.QDesktopServices, "openUrl", return_value=True) as opener:
            self.win.open_reports_folder()
        self.assertNotEqual(self._opened_path(opener), old_package)
        self.assertEqual(self._opened_path(opener), Path(self.win.report_root).resolve())
        self.win.enter_listen()
        self.assertFalse(self.win.report_written)
        with mock.patch.object(qt_app.QDesktopServices, "openUrl", return_value=True) as opener:
            self.win.open_reports_folder()
        self.assertEqual(self._opened_path(opener), Path(self.win.report_root).resolve())

    def test_open_reports_folder_failure_shows_clear_error(self):
        with mock.patch.object(qt_app.QDesktopServices, "openUrl", return_value=False), \
             mock.patch.object(qt_app.QMessageBox, "warning") as warning, \
             mock.patch.object(qt_app, "write_reports") as writer:
            self.win.open_reports_folder()
        warning.assert_called_once()
        writer.assert_not_called()

    def test_results_report_area_has_no_open_excel_or_html(self):
        self._run([0, 25, 50, 75])
        self.win._show_workflow_page("results")
        self._settle()
        self.assertFalse(hasattr(self.win, "btn_open_excel"))
        self.assertFalse(hasattr(self.win, "btn_open_html"))
        texts = {self.win._tr("open_excel"), self.win._tr("open_html"), "Open Excel", "Open HTML"}
        for button in self.win.findChildren(QPushButton):
            if button.text() in texts:
                self.assertFalse(button.isVisible())
                self.assertEqual(button.focusPolicy(), Qt.FocusPolicy.NoFocus)
        bar_buttons = list(self.win.results_report_bar._buttons) if hasattr(self.win.results_report_bar, "_buttons") else []
        if bar_buttons:
            self.assertEqual(
                bar_buttons,
                [self.win.btn_generate_report, self.win.btn_open_reports_folder, self.win.btn_export],
            )
        self.assertTrue(callable(self.win.open_excel_report))
        self.assertTrue(callable(self.win.open_html_report))

    def test_run_context_uses_analysis_scope(self):
        self._run([0, 25, 50, 75])
        facts = self.win._completed_run_facts()
        ctx = self.win._format_run_context(facts["model"]) if facts else ""
        self.assertIn(f"{self.win._tr('analysis_scope')}: {self.win._tr('screening_measurement_only')}", ctx)
        self.assertNotIn("Screening:", ctx)

    def test_compare_remains_enabled_on_distribution(self):
        self._run([0, 25, 50, 75])
        self.assertEqual(self.win.results_view_combo.currentData(), "distribution")
        self.assertTrue(self.win.btn_overlay.isEnabled())
        idx = self.win.results_view_combo.findData("timing")
        if idx >= 0:
            self.win.results_view_combo.setCurrentIndex(idx)
            self._settle()
            self.assertFalse(self.win.btn_overlay.isEnabled())


class QtStage2COverlayDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.win = qt_app.MainWindow(report_root=self.root)
        self.win._listen_start_timer.stop()
        self.win.ui_timer.stop()

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self._tmp.cleanup()

    @staticmethod
    def _events(n=5):
        return [
            {"index": i + 1, "button": "Left", "accepted": True,
             "press_elapsed_ms": i * 100.0, "press_interval_ms": None if i == 0 else 100.0, "hold_ms": 40.0}
            for i in range(n)
        ]

    def _write_json(self, path: Path, payload: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _nested(self, rid: str) -> Path:
        return self._write_json(
            self.root / f"mcsa_{rid}" / f"mcsa_{rid}_evidence.json",
            {"schema": "MCSA_EVIDENCE_V1", "run_id": rid, "run_status": "COMPLETE",
             "target_product": "NEW", "events": self._events(), "measurements": {"host_press_count": 5}},
        )

    def test_nested_package_evidence_discovered(self):
        path = self._nested("n1")
        items = {c["run_id"]: c for c in self.win._list_overlay_candidates()}
        self.assertIn("n1", items)
        self.assertEqual(Path(items["n1"]["detail_path"]), path)
        self.assertEqual(Path(items["n1"]["summary_path"]), path)

    def test_flat_legacy_detail_and_evidence_still_discovered(self):
        self._write_json(self.root / "mcsa_old1_detail.json", {"run_id": "old1", "events": self._events()})
        self._write_json(self.root / "mcsa_old1_summary.json", {"run_id": "old1", "result": "PASS"})
        self._write_json(self.root / "mcsa_old2_evidence.json", {"run_id": "old2", "events": self._events()})
        items = {c["run_id"]: c for c in self.win._list_overlay_candidates()}
        self.assertEqual(Path(items["old1"]["detail_path"]).name, "mcsa_old1_detail.json")
        self.assertEqual(Path(items["old2"]["detail_path"]).name, "mcsa_old2_evidence.json")

    def test_nested_sibling_lookup_uses_discovered_parent(self):
        rid = "sib1"
        detail = self._write_json(
            self.root / f"mcsa_{rid}" / f"mcsa_{rid}_detail.json", {"run_id": rid, "events": self._events()},
        )
        evidence = self._nested(rid)
        meta = self.win._load_run_meta_from_disk(detail)
        self.assertEqual(Path(meta["detail_path"]), evidence)
        self.assertEqual(Path(meta["detail_path"]).parent, detail.parent)

    def test_no_duplicate_entries_and_new_evidence_preferred(self):
        rid = "dup1"
        nested = self._nested(rid)
        self._write_json(self.root / f"mcsa_{rid}_detail.json", {"run_id": rid, "events": self._events(3)})
        self._write_json(self.root / f"mcsa_{rid}_evidence.json", {"run_id": rid, "events": self._events(2)})
        candidates = self.win._list_overlay_candidates()
        ids = [c["run_id"] for c in candidates]
        self.assertEqual(ids.count(rid), 1)
        chosen = next(c for c in candidates if c["run_id"] == rid)
        self.assertEqual(Path(chosen["detail_path"]), nested)

    def test_overlay_loads_new_nested_evidence(self):
        path = self._nested("ov1")
        payload = qt_app.load_overlay_payload(str(path))
        events = qt_app.extract_overlay_events(payload)
        self.assertEqual(len(events), 5)
        self.win._set_overlay(events, payload.get("metrics") or {}, str(path))
        self.assertEqual(len(self.win.overlay_events), 5)


class QtStage2CChartDomainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()

    def _fit(self, chart):
        chart.set_data_aware_fit(True)
        chart.resize(600, 300)
        chart.fit_data()
        return chart.autofit_bounds(), chart.visible_bounds()

    def test_interval_chart_y_and_elapsed_x_non_negative(self):
        chart = qt_app.IntervalChart()
        series = [(i * 10.0, 0.3 + (i % 3) * 0.2) for i in range(30)]
        before = list(series)
        chart.set_series(series)
        auto, visible = self._fit(chart)
        self.assertGreaterEqual(auto[0], 0.0)
        self.assertGreaterEqual(auto[2], 0.0)
        self.assertGreaterEqual(visible[0], 0.0)
        self.assertGreaterEqual(visible[2], 0.0)
        self.assertEqual(chart.series, before)

    def test_histogram_count_axis_zero_and_counts_unchanged(self):
        chart = qt_app.HistogramChart()
        bins = [{"lo": 0.0, "hi": 0.5, "count": 3}, {"lo": 0.5, "hi": 1.0, "count": 7}]
        chart.set_bins([dict(b) for b in bins])
        auto, visible = self._fit(chart)
        self.assertEqual(auto[2], 0.0)
        self.assertGreaterEqual(auto[0], 0.0)
        self.assertGreaterEqual(visible[2], 0.0)
        self.assertEqual([b["count"] for b in chart.bins], [3, 7])
        self.assertEqual([(b["lo"], b["hi"]) for b in chart.bins], [(0.0, 0.5), (0.5, 1.0)])

    def test_scatter_x_and_y_non_negative(self):
        chart = qt_app.ScatterChart()
        points = [(0.4 + i * 0.01, 0.2 + i * 0.01, "") for i in range(20)]
        chart.set_points(points)
        auto, visible = self._fit(chart)
        self.assertGreaterEqual(auto[0], 0.0)
        self.assertGreaterEqual(auto[2], 0.0)
        self.assertGreaterEqual(visible[0], 0.0)
        self.assertGreaterEqual(visible[2], 0.0)

    def test_negative_observations_remain_visible(self):
        chart = qt_app.ScatterChart()
        chart.set_points([(-5.0, 10.0, ""), (20.0, 12.0, "")])
        auto, _ = self._fit(chart)
        self.assertLessEqual(auto[0], -5.0)


if __name__ == "__main__":
    unittest.main()
