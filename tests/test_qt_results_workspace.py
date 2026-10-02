"""Step 4A: Results owns completed-run review, evidence, and post-run actions."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QAbstractItemView, QToolButton

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer import app as legacy_app
from mouse_click_stability_analyzer.completed_result import (
    TIMING_ERROR_UNAVAILABLE_REASON,
    build_completed_result_model,
    interval_histogram_bins,
    paired_interval_histograms,
    qt_present_issue_tags,
    qt_visible_verdict,
)
from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.overlay_io import extract_overlay_events, load_overlay_payload
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import format_host_evidence_review_lines

_T0 = 1000.0
_RESULT_KEYS = (
    "results_empty",
    "results_run_summary",
    "results_run_context",
    "results_observations",
    "results_host_evidence_section",
    "results_actions",
    "results_elapsed",
    "results_host_clicks",
    "results_avg_interval",
    "results_avg_hold",
    "results_existing_result",
    "generate_report",
    "generate_excel",
    "generate_html",
    "export_save_as",
    "export_analysis_txt",
    "export_click_log_csv",
    "export_summary_json",
    "export_detail_json",
    "save_report_as",
    "report",
    "capture_run_completed",
    "analysis",
    "evidence",
    "click_data",
    "analysis_view",
    "interval_over_time",
    "interval_distribution",
    "hold_vs_interval",
    "timing_error",
    "observations_none",
    "configured_reference",
    "observed_average",
    "difference",
    "expected_windows",
    "host_observations",
    "occupancy",
    "association",
    "unoccupied",
    "single_occupancy",
    "multi_occupancy",
    "matched",
    "unmatched",
    "ambiguous",
    "outside_capture",
    "neutral_host_evidence_note",
    "run_again",
    "edit_setup_new_run",
    "editing_next_run_note",
    "not_applicable_manual",
    "next_run",
    "compare",
)


def _under(widget, ancestor) -> bool:
    current = widget
    while current is not None:
        if current is ancestor:
            return True
        current = current.parentWidget()
    return False


def _no_pairwise_overlap(widgets) -> None:
    geos = [w.geometry() for w in widgets if w.isVisible()]
    for i, a in enumerate(geos):
        for b in geos[i + 1 :]:
            if a.intersects(b) and a.intersected(b).width() > 1 and a.intersected(b).height() > 1:
                raise AssertionError(f"overlap {a} {b}")


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


class ResultsWorkspaceTests(unittest.TestCase):
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
        self.win._cursor_in_test_area = lambda: True
        self.win._cursor_over_capture_exclusion_ui = lambda: False
        self.win.listening = True

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()
        self._qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def _settle(self):
        for _ in range(5):
            self._qapp.processEvents()

    def _setup_fixture(self, *, auto_sec: str | None = "1", tol: str = "2", hz: str = "40"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tol)
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _lock_and_arm(self):
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())

    def _run(self, offsets, *, stop=True, auto_stop=False):
        self._lock_and_arm()
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        for off in offsets[1:]:
            press = t0 + off / 1000.0
            self.win.record_click("Left", press, press + 0.01, {})
        if auto_stop:
            self.win.end_time = time.perf_counter() - 1e-6
            self.win._tick()
        elif stop:
            self.win.stop_run()

    def _facts(self):
        return self.win._completed_run_facts()

    def _result_cards(self):
        return [
            self.win.results_summary_card,
            self.win.results_observations_card,
            self.win.results_evidence_card,
            self.win.results_actions_card,
        ]

    def _show_results_at(self, width: int, height: int) -> None:
        self.win._show_workflow_page("results")
        self.win.resize(width, height)
        self._settle()

    def _show_results_tab(self, index: int) -> None:
        self.win.results_tabs.setCurrentIndex(index)
        self._settle()

    def _assert_empty_results(self):
        self.win._show_workflow_page("results")
        self._settle()
        self.assertTrue(self.win.results_empty_card.isVisibleTo(self.win))
        self.assertFalse(self.win.results_workspace.isVisibleTo(self.win))
        self.assertEqual(self.win.results_placeholder.text(), self.win._tr("results_empty"))
        self.assertFalse(self.win.completed)

    def test_launch_results_is_empty_state(self):
        self._assert_empty_results()

    def test_ready_results_still_empty(self):
        self._setup_fixture()
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self._assert_empty_results()

    def test_armed_results_still_empty(self):
        self._setup_fixture()
        self._lock_and_arm()
        self.assertEqual(self.win._lifecycle_state(), "armed")
        self._assert_empty_results()

    def test_running_results_does_not_pretend_completed(self):
        self._setup_fixture()
        self._run([0, 25, 50], stop=False)
        before = (
            self.win.running,
            self.win.completed,
            list(self.win.events),
            self.win.host_evidence_snapshot,
            self.win.start_time,
        )
        self.win._show_workflow_page("results")
        self._settle()
        self.assertTrue(self.win.running)
        self.assertFalse(self.win.completed)
        self.assertTrue(self.win.results_empty_card.isVisibleTo(self.win))
        self.assertFalse(self.win.results_workspace.isVisibleTo(self.win))
        self.assertEqual(
            (
                self.win.running,
                self.win.completed,
                list(self.win.events),
                self.win.host_evidence_snapshot,
                self.win.start_time,
            ),
            before,
        )

    def test_manual_stop_opens_results(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertTrue(self.win.completed)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)
        self.assertTrue(self.win.results_workspace.isVisibleTo(self.win))

    def test_auto_stop_opens_results(self):
        self._setup_fixture(auto_sec="1")
        self._run([0, 25, 50, 75], stop=False, auto_stop=True)
        self.assertTrue(self.win.completed)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)

    def test_f5_stop_opens_results(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75], stop=False)
        self.win.stop_run()
        self.assertTrue(self.win.completed)
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_results)

    def test_second_stop_does_not_rebuild_or_renavigate(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            snap = self.win.host_evidence_snapshot
            page = self.win.page_stack.currentWidget()
            obs = self.win.results_observations_text.text()
            self.win.stop_run()
        self.assertEqual(builder.call_count, 1)
        self.assertIs(self.win.host_evidence_snapshot, snap)
        self.assertIs(self.win.page_stack.currentWidget(), page)
        self.assertEqual(self.win.results_observations_text.text(), obs)

    def test_summary_uses_frozen_locked_values(self):
        self.win.device_edit.setText("DUT-LOCK")
        self._setup_fixture(hz="40", tol="2", auto_sec="1")
        self._run([0, 25, 50, 75])
        self.win.device_edit.setText("MUTATED")
        self.win.hz_combo.setCurrentText("5")
        self.win.timing_tol_edit.setText("13")
        self.win.button_combo.setCurrentText("Right")
        self.win._refresh_results_workspace()
        ctx = self.win.results_context_label.text()
        self.assertIn("DUT-LOCK", ctx)
        self.assertIn("40 Hz", ctx)
        self.assertIn("±2 ms", ctx)
        self.assertIn("Left", ctx)
        self.assertNotIn("MUTATED", ctx)
        self.assertNotIn("5 Hz", ctx)
        self.assertEqual(self.win.results_verdict_label.text(), self.win.val_verdict.text())

    def test_summary_metrics_match_existing_payload(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        facts = self._facts()
        self.assertIsNotNone(facts)
        settings = self.win.locked
        annotated = legacy_app.annotate_events(list(self.win.events), settings)
        metrics = legacy_app.build_payload(
            self.win.target, self.win.operator, settings, annotated, run_id=self.win.run_id
        ).get("metrics") or {}
        tags = legacy_app._metrics_issue_tags(metrics, settings, annotated)
        verdict = qt_app.qt_visible_verdict(tags, metrics, settings)
        self.assertEqual(facts["verdict"], verdict)
        self.assertEqual(facts["metrics"].get("click_count"), metrics.get("click_count"))
        self.assertEqual(facts["metrics"].get("interval_avg_ms"), metrics.get("interval_avg_ms"))
        self.assertEqual(facts["metrics"].get("hold_avg_ms"), metrics.get("hold_avg_ms"))
        self.assertEqual(self.win.results_verdict_label.text(), str(verdict))
        obs = self.win.results_observations_text.text()
        self.assertTrue(obs)
        self.assertNotIn("DUT", obs)
        self.assertNotIn("Host click count", obs)

    def test_navigation_and_resize_preserve_values(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        snap = self.win.host_evidence_snapshot
        obs = self.win.results_observations_text.text()
        evidence = self.win.results_evidence_text.toPlainText()
        summary = self.win.results_context_label.text()
        self.win._show_workflow_page("capture")
        self.win.resize(1280, 720)
        self._settle()
        self.win._show_workflow_page("results")
        self.win.resize(1600, 900)
        self._settle()
        self.assertIs(self.win.host_evidence_snapshot, snap)
        self.assertEqual(self.win.results_observations_text.text(), obs)
        self.assertEqual(self.win.results_evidence_text.toPlainText(), evidence)
        self.assertEqual(self.win.results_context_label.text(), summary)

    def test_fixture_auto_stop_on_shows_host_evidence(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        self._show_results_tab(1)
        self.assertTrue(self.win.results_evidence_card.isVisibleTo(self.win))
        text = self.win.results_evidence_text.toPlainText()
        for line in format_host_evidence_review_lines(self.win.host_evidence_snapshot, self.win._tr):
            self.assertIn(line, text)
        self.assertIn("HOST EVIDENCE", text)

    def test_manual_has_no_host_evidence(self):
        self.win.radio_manual.setChecked(True)
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self._show_results_tab(1)
        self.assertTrue(self.win.results_evidence_card.isVisibleTo(self.win))
        self.assertEqual(self.win.results_evidence_na.text(), self.win._tr("not_applicable_manual"))
        self.assertNotIn("HOST EVIDENCE", self.win.results_evidence_text.toPlainText())
        self.assertNotIn("Expected Slots", self.win.results_evidence_text.toPlainText())
        self.assertTrue(self.win.results_workspace.isVisibleTo(self.win))

    def test_fixture_auto_stop_off_has_no_host_evidence(self):
        self._setup_fixture(auto_sec=None)
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self._show_results_tab(1)
        self.assertEqual(self.win.results_evidence_na.text(), self.win._tr("not_applicable_no_duration"))
        self.assertNotIn("Expected Slots", self.win.results_evidence_text.toPlainText())

    def test_language_switch_retranslates_without_rebuild(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            snap = self.win.host_evidence_snapshot
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
            self.assertEqual(self.win.lbl_results_summary.text(), STRINGS["zh"]["results_run_context"].upper())
            self.assertEqual(self.win.btn_generate_excel.text(), STRINGS["zh"]["generate_excel"])
            self.assertEqual(self.win.btn_generate_html.text(), STRINGS["zh"]["generate_html"])
            self.assertEqual(self.win.btn_export.text(), STRINGS["zh"]["export_save_as"])
            self.assertIn("主機觀測證據", self.win.results_evidence_text.toPlainText())
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("en"))
            self.assertIn("HOST EVIDENCE", self.win.results_evidence_text.toPlainText())
        self.assertEqual(builder.call_count, 1)
        self.assertIs(self.win.host_evidence_snapshot, snap)

    def test_capture_results_roundtrip_does_not_rebuild_evidence(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            snap = self.win.host_evidence_snapshot
            self.win._show_workflow_page("capture")
            self.win._show_workflow_page("results")
        self.assertEqual(builder.call_count, 1)
        self.assertIs(self.win.host_evidence_snapshot, snap)

    def test_capture_is_not_canonical_review(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        self.win._show_workflow_page("capture")
        self._settle()
        self.assertFalse(self.win.review_text.isVisibleTo(self.win))
        self.assertEqual(self.win.review_text.toPlainText(), "")
        self.assertTrue(self.win.capture_completed_note.isVisibleTo(self.win))
        self.assertIn("Results", self.win.capture_completed_note.text())
        self.assertNotIn("HOST EVIDENCE", self.win.capture_completed_note.text())

    def test_results_owns_post_run_actions(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        for widget in (
            self.win.btn_new, self.win.btn_generate_excel, self.win.btn_generate_html,
            self.win.btn_export, self.win.btn_overlay, self.win.btn_clear_overlay,
        ):
            with self.subTest(widget=widget.text()):
                self.assertTrue(_under(widget, self.win.page_results), widget)
                self.assertFalse(_under(widget, self.win.page_capture), widget)
                self.assertTrue(widget.isVisibleTo(self.win), widget)
        self.assertEqual(self.win.btn_generate_excel.text(), self.win._tr("generate_excel"))
        self.assertEqual(self.win.btn_generate_html.text(), self.win._tr("generate_html"))
        self.assertEqual(self.win.btn_export.text(), self.win._tr("export_save_as"))
        self.assertEqual(self.win.btn_new.text(), self.win._tr("run_again"))
        self.assertEqual(self.win.btn_edit_setup_new_run.text(), self.win._tr("edit_setup_new_run"))
        self.assertTrue(_under(self.win.btn_overlay, self.win.results_analysis_page))
        self.assertTrue(_under(self.win.btn_clear_overlay, self.win.results_analysis_page))
        self.assertFalse(_under(self.win.btn_overlay, self.win.results_actions_card))
        self.assertTrue(_under(self.win.btn_generate_excel, self.win.results_actions_card))
        self.assertFalse(_under(self.win.btn_generate_excel, self.win.results_tabs))
        self.assertEqual(self.win.results_tabs.currentIndex(), 0)
        self.assertTrue(self.win.btn_generate_excel.isEnabled())
        self.assertTrue(self.win.btn_generate_html.isEnabled())
        self.assertTrue(self.win.btn_export.isEnabled())
        self.assertTrue(_under(self.win.btn_stop, self.win.page_capture))
        self.assertTrue(_under(self.win.btn_arm, self.win.page_capture))
        self.assertTrue(_under(self.win.btn_edit_profile, self.win.page_capture))

    def test_buttons_call_existing_handlers(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.report_written = True
        self.win._update_controls()
        mapping = (
            (self.win.btn_generate_excel, "generate_excel_report"),
            (self.win.btn_generate_html, "generate_html_report"),
            (self.win.btn_overlay, "load_overlay_run"),
            (self.win.btn_clear_overlay, "clear_overlay"),
            (self.win.btn_new, "new_run"),
            (self.win.btn_edit_setup_new_run, "edit_setup_new_run"),
        )
        for button, method in mapping:
            with self.subTest(method=method):
                self.assertTrue(button.isEnabled(), method)
                with mock.patch.object(self.win, method) as handler:
                    button.click()
                handler.assert_called_once()

    def test_new_run_returns_capture_ready_disarmed(self):
        self._setup_fixture()
        self.win.device_edit.setText("KEEP-ME")
        self._run([0, 25, 50, 75])
        locked = self.win.profile_locked_settings
        target = self.win.profile_locked_target
        hz = self.win.hz_combo.currentText()
        events_before = list(self.win.events)
        self.win.btn_new.click()
        self._settle()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_capture)
        self.assertFalse(self.win.completed)
        self.assertFalse(self.win.running)
        self.assertFalse(self.win.capture_armed)
        self.assertEqual(self.win.events, [])
        self.assertIsNone(self.win.locked)
        self.assertIs(self.win.profile_locked_settings, locked)
        self.assertEqual(self.win.profile_locked_target, target)
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertEqual(self.win.device_edit.text(), "KEEP-ME")
        self.assertEqual(self.win.hz_combo.currentText(), hz)
        self.assertTrue(self.win.session_runs)
        self.assertEqual(self.win.session_runs[-1]["events"], events_before)
        self.win._show_workflow_page("results")
        self.assertTrue(self.win.results_empty_card.isVisibleTo(self.win))
        self.assertFalse(self.win.results_workspace.isVisibleTo(self.win))

    def test_edit_profile_still_forbidden_when_completed(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertFalse(self.win.edit_profile())
        self.assertIsNotNone(self.win.profile_locked_settings)
        self.assertTrue(self.win.completed)
        self.assertFalse(self.win.btn_edit_profile.isEnabled())

    def test_results_layout_usable_at_presets(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        for width, height in ((1280, 720), (1440, 810), (1600, 900)):
            with self.subTest(size=f"{width}x{height}"):
                self._show_results_at(width, height)
                self.assertEqual(
                    self.win.results_scroll.horizontalScrollBarPolicy(),
                    Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
                )
                self.assertFalse(self.win.results_scroll.horizontalScrollBar().isVisible())
                visible = [
                    self.win.results_summary_card,
                    self.win.results_assessment_card,
                    self.win.results_actions_card,
                ]
                _no_pairwise_overlap(visible)
                self.assertGreaterEqual(self.win.results_interval_chart.height(), 80)
                self.assertLessEqual(self.win.results_workspace.height(), max(self.win.height() * 4, 4000))
                self.assertTrue(self.win.results_tabs.isVisibleTo(self.win))
                self.assertTrue(self.win.btn_generate_excel.isVisibleTo(self.win))

    def test_hidden_results_actions_do_not_exclude_capture(self):
        self._setup_fixture()
        self._run([0, 25, 50], stop=False)
        self.win._show_workflow_page("capture")
        self._settle()
        self.win._cursor_over_capture_exclusion_ui = lambda: qt_app.MainWindow._cursor_over_capture_exclusion_ui(self.win)
        for widget in (
            self.win.btn_new, self.win.btn_generate_excel, self.win.btn_generate_html,
            self.win.btn_export, self.win.results_evidence_text,
        ):
            self.assertFalse(widget.isVisibleTo(self.win), widget)
        self.win._cursor_global_pos = lambda: self.win.test_area.mapToGlobal(self.win.test_area.rect().center())
        self.assertFalse(self.win._cursor_over_capture_exclusion_ui())

    def test_report_primary_and_secondary_actions(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertEqual(self.win.btn_generate_excel.objectName(), "Primary")
        self.assertEqual(self.win.btn_generate_html.objectName(), "Primary")
        self.assertIsInstance(self.win.btn_export, QToolButton)
        self.assertEqual(self.win.btn_export.objectName(), "Secondary")
        self.assertEqual(self.win.lbl_results_report.text(), self.win._tr("report").upper())
        menu = self.win.btn_export.menu()
        self.assertIs(menu, self.win.export_menu)
        labels = [action.text() for action in menu.actions() if action.text()]
        self.assertEqual(
            labels,
            [
                self.win._tr("export_analysis_txt"),
                self.win._tr("export_click_log_csv"),
                self.win._tr("export_summary_json"),
                self.win._tr("export_detail_json"),
                self.win._tr("save_report_as"),
            ],
        )

    def _fake_bundle(self, name: str, *, skip: tuple[str, ...] = ()) -> dict[str, str]:
        root = Path(self._tmp.name) / name
        root.mkdir(exist_ok=True)
        paths = {}
        for key, fname in legacy_app.artifact_names(self.win.run_id).items():
            path = root / fname
            if key in skip:
                paths[key] = ""
                continue
            path.write_text(key, encoding="utf-8")
            paths[key] = str(path)
        return paths

    def test_generate_excel_and_html_pass_distinct_preferred_artifacts(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        expected = (
            (self.win.btn_generate_excel, "engineering_xlsx"),
            (self.win.btn_generate_html, "engineering_html"),
        )
        for button, key in expected:
            with self.subTest(key=key):
                with mock.patch.object(self.win, "finish_report") as handler:
                    button.click()
                handler.assert_called_once_with(preferred_artifact=key)

    def test_primary_success_target_is_preferred_artifact(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        paths = self._fake_bundle("primary_target")
        for method, key in (
            (self.win.generate_excel_report, "engineering_xlsx"),
            (self.win.generate_html_report, "engineering_html"),
        ):
            with self.subTest(key=key):
                self.win.report_written = False
                with mock.patch.object(qt_app, "write_reports", return_value=dict(paths)) as writer, \
                     mock.patch.object(qt_app.QMessageBox, "information") as info, \
                     mock.patch.object(qt_app.QMessageBox, "critical") as critical:
                    method()
                writer.assert_called_once()
                critical.assert_not_called()
                info.assert_called_once()
                message = info.call_args[0][2]
                self.assertEqual(message, self.win._tr("saved_to", path=paths[key]))
                self.assertTrue(self.win.report_written)

    def test_generate_excel_missing_xlsx_is_not_success(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        paths = self._fake_bundle("missing_xlsx", skip=("engineering_xlsx",))
        locked = self.win.locked
        events_before = list(self.win.events)
        with mock.patch.object(qt_app, "write_reports", return_value=paths) as writer, \
             mock.patch.object(qt_app.QMessageBox, "information") as info, \
             mock.patch.object(qt_app.QMessageBox, "critical") as critical:
            self.win.generate_excel_report()
        writer.assert_called_once()
        info.assert_not_called()
        critical.assert_called_once()
        self.assertEqual(critical.call_args[0][1], self.win._tr("report_failed"))
        self.assertIn("engineering_xlsx", critical.call_args[0][2])
        self.assertFalse(self.win.report_written)
        self.assertIs(self.win.locked, locked)
        self.assertEqual(self.win.events, events_before)

    def test_direct_secondary_export_prepares_bundle_silently(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertFalse(self.win.report_written)
        self.assertTrue(self.win.btn_export.isEnabled())
        paths = self._fake_bundle("silent_export")
        dest = Path(self._tmp.name) / "silent_export_out.csv"
        locked = self.win.locked
        events_before = list(self.win.events)
        host = self.win.host_evidence_snapshot
        with mock.patch.object(qt_app, "write_reports", return_value=paths) as writer, \
             mock.patch.object(qt_app.QMessageBox, "information") as info, \
             mock.patch.object(qt_app.QMessageBox, "critical") as critical, \
             mock.patch.object(qt_app.QFileDialog, "getSaveFileName", return_value=(str(dest), "")) as dialog:
            self.win.act_export_csv.trigger()
        writer.assert_called_once()
        self.assertIs(writer.call_args[0][3], locked)
        info.assert_not_called()
        critical.assert_not_called()
        dialog.assert_called_once()
        self.assertEqual(dest.read_text(encoding="utf-8"), "all_click_log_csv")
        self.assertTrue(self.win.report_written)
        self.assertIs(self.win.locked, locked)
        self.assertEqual(self.win.events, events_before)
        self.assertIs(self.win.host_evidence_snapshot, host)

    def test_direct_save_report_as_prepares_bundle_silently(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        paths = self._fake_bundle("silent_bundle")
        out_root = Path(self._tmp.name) / "silent_bundle_out"
        out_root.mkdir()
        with mock.patch.object(qt_app, "write_reports", return_value=paths) as writer, \
             mock.patch.object(qt_app.QMessageBox, "information") as info, \
             mock.patch.object(qt_app.QFileDialog, "getExistingDirectory", return_value=str(out_root)):
            self.win.act_save_report_as.trigger()
        writer.assert_called_once()
        info.assert_not_called()
        copied = list((out_root / f"mcsa_{self.win.run_id}").iterdir())
        self.assertEqual(len(copied), len(paths))

    def test_menu_indicator_style_is_scoped_to_secondary_tool_button(self):
        from mouse_click_stability_analyzer.qt_shell.styles import get_style

        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                sheet = get_style(theme)
                self.assertIn("QToolButton#Secondary::menu-indicator", sheet)
                self.assertNotIn("\nQToolButton::menu-indicator", sheet)
                self.assertNotIn("QPushButton, QToolButton {", sheet)

    def test_export_menu_routes_to_existing_exporters(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.report_written = True
        self.win._update_controls()
        artifact_actions = (
            (self.win.act_export_txt, "txt"),
            (self.win.act_export_csv, "all_click_log_csv"),
            (self.win.act_export_summary_json, "summary_json"),
            (self.win.act_export_detail_json, "detail_json"),
        )
        for action, key in artifact_actions:
            with self.subTest(key=key):
                with mock.patch.object(self.win, "export_report_artifact") as exporter:
                    action.trigger()
                exporter.assert_called_once_with(key)
        with mock.patch.object(self.win, "save_report_as") as saver:
            self.win.act_save_report_as.trigger()
        saver.assert_called_once()

    def test_export_artifact_copies_existing_bundle_file(self):
        src = Path(self._tmp.name) / "mcsa_copy_analysis.txt"
        src.write_text("bundle-txt", encoding="utf-8")
        dest = Path(self._tmp.name) / "saved_analysis.txt"
        self.win.report_written = True
        self.win.report_paths = {"txt": str(src)}
        with mock.patch.object(qt_app.QFileDialog, "getSaveFileName", return_value=(str(dest), "")):
            self.win.export_report_artifact("txt")
        self.assertEqual(dest.read_text(encoding="utf-8"), "bundle-txt")

    def test_generate_excel_writes_detail_json_for_overlay(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        root = Path(self._tmp.name) / "sidecar_excel"
        root.mkdir()
        self.win.report_root = root
        locked = self.win.locked
        events_before = list(self.win.events)
        with mock.patch.object(qt_app.QMessageBox, "information") as info, \
             mock.patch.object(qt_app.QMessageBox, "critical") as critical:
            self.win.generate_excel_report()
        critical.assert_not_called()
        info.assert_called_once()
        self.assertTrue(list(root.glob("mcsa_*_report.xlsx")))
        details = list(root.glob("mcsa_*_detail.json"))
        self.assertEqual(len(details), 1, details)
        payload = load_overlay_payload(details[0])
        overlay_events = extract_overlay_events(payload)
        self.assertGreaterEqual(len(overlay_events), 1)
        self.assertTrue(list(root.glob("mcsa_*_summary.json")))
        self.assertTrue(list(root.glob("mcsa_*_report.html")))
        self.assertTrue(list(root.glob("mcsa_*_events.csv")))
        self.assertTrue(list(root.glob("mcsa_*_analysis.txt")))
        candidates = self.win._list_overlay_candidates()
        self.assertTrue(any(Path(item.get("detail_path") or "") == details[0] for item in candidates))
        self.assertIs(self.win.locked, locked)
        self.assertEqual(self.win.events, events_before)

    def test_report_generation_uses_completed_snapshot_without_mutating_it(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        locked = self.win.locked
        events_before = list(self.win.events)
        host = self.win.host_evidence_snapshot
        run_id = self.win.run_id
        paths = self._fake_bundle("snapshot")
        with mock.patch.object(qt_app, "write_reports", return_value=paths) as writer, \
             mock.patch.object(qt_app.QMessageBox, "information"), \
             mock.patch.object(qt_app.QMessageBox, "critical") as critical:
            self.win.generate_html_report()
        critical.assert_not_called()
        writer.assert_called_once()
        args = writer.call_args[0]
        self.assertIs(args[3], locked)
        self.assertEqual(args[4], events_before)
        self.assertEqual(args[5], run_id)
        self.assertIs(self.win.locked, locked)
        self.assertEqual(self.win.events, events_before)
        self.assertIs(self.win.host_evidence_snapshot, host)
        self.assertTrue(self.win.completed)

    def test_report_actions_follow_completed_lifecycle(self):
        self._setup_fixture()
        self.assertFalse(self.win.btn_generate_excel.isEnabled())
        self.assertFalse(self.win.btn_generate_html.isEnabled())
        self.assertFalse(self.win.btn_export.isEnabled())
        self._run([0, 25, 50, 75])
        self.assertTrue(self.win.completed)
        self.assertTrue(self.win.btn_generate_excel.isEnabled())
        self.assertTrue(self.win.btn_generate_html.isEnabled())
        self.assertFalse(self.win.report_written)
        self.assertTrue(self.win.btn_export.isEnabled())
        self.win.btn_new.click()
        self._settle()
        self.assertFalse(self.win.completed)
        self.assertFalse(self.win.report_written)
        self.assertFalse(self.win.btn_generate_excel.isEnabled())
        self.assertFalse(self.win.btn_generate_html.isEnabled())
        self.assertFalse(self.win.btn_export.isEnabled())

    def test_export_failure_does_not_mutate_completed_result(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        locked = self.win.locked
        events_before = list(self.win.events)
        host = self.win.host_evidence_snapshot
        with mock.patch.object(qt_app, "write_reports", side_effect=RuntimeError("disk full")), \
             mock.patch.object(qt_app.QMessageBox, "critical") as critical:
            self.win.generate_excel_report()
        critical.assert_called_once()
        self.assertTrue(self.win.completed)
        self.assertFalse(self.win.report_written)
        self.assertIs(self.win.locked, locked)
        self.assertEqual(self.win.events, events_before)
        self.assertIs(self.win.host_evidence_snapshot, host)

    def test_frozen_model_ignores_setup_widget_mutations(self):
        self.win.device_edit.setText("DUT-FROZEN")
        self._setup_fixture(hz="40", tol="2", auto_sec="1")
        self._run([0, 25, 50, 75])
        events_id = id(self.win.events)
        events_before = list(self.win.events)
        host = self.win.host_evidence_snapshot
        locked = self.win.locked
        model = build_completed_result_model(
            locked=locked,
            events=list(self.win.events),
            run_id=self.win.run_id,
            target=self.win.target,
            operator=self.win.operator,
            start_time=self.win.start_time,
            stop_time=self.win.stop_time,
            host_evidence_snapshot=host,
        )
        self.assertIsNotNone(model)
        self.win.device_edit.setText("MUTATED")
        self.win.hz_combo.setCurrentText("5")
        self.win.timing_tol_edit.setText("13")
        self.win.button_combo.setCurrentText("Right")
        again = self.win._completed_run_facts()["model"]
        self.assertEqual(again["run"]["target"], "DUT-FROZEN")
        self.assertEqual(again["run"]["reference_hz"], model["run"]["reference_hz"])
        self.assertEqual(again["run"]["button"], "Left")
        self.assertIs(again["host_evidence"]["snapshot"], host)
        self.assertEqual(again["assessment"]["verdict"], model["assessment"]["verdict"])
        self.assertEqual(id(self.win.events), events_id)
        self.assertEqual(self.win.events, events_before)
        settings = locked
        annotated = legacy_app.annotate_events(list(self.win.events), settings)
        metrics = legacy_app.build_payload(
            self.win.target, self.win.operator, settings, annotated, run_id=self.win.run_id
        ).get("metrics") or {}
        tags = legacy_app._metrics_issue_tags(metrics, settings, annotated)
        self.assertEqual(again["assessment"]["verdict"], qt_app.qt_visible_verdict(tags, metrics, settings))
        self.assertEqual(again["assessment"]["tags"], qt_app.qt_present_issue_tags(tags))

    def test_results_tabs_default_analysis_and_hide_old_stack(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertEqual(self.win.results_tabs.count(), 3)
        self.assertEqual(self.win.results_tabs.tabText(0), self.win._tr("analysis"))
        self.assertEqual(self.win.results_tabs.tabText(1), self.win._tr("evidence"))
        self.assertEqual(self.win.results_tabs.tabText(2), self.win._tr("click_data"))
        self.assertEqual(self.win.results_tabs.currentIndex(), 0)
        self.assertTrue(self.win.results_context_label.isVisibleTo(self.win))
        self.assertTrue(self.win.results_interval_chart.isVisibleTo(self.win))
        self.assertFalse(self.win.results_evidence_text.isVisibleTo(self.win))
        self.assertEqual(self.win._results_summary_cells, [])

    def test_analysis_chart_switch_does_not_mutate_completed_state(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            snap = self.win.host_evidence_snapshot
            events_before = list(self.win.events)
            completed = self.win.completed
            for data in ("interval", "distribution", "scatter", "timing"):
                idx = self.win.results_view_combo.findData(data)
                self.assertGreaterEqual(idx, 0, data)
                self.win.results_view_combo.setCurrentIndex(idx)
                self._settle()
            self.assertEqual(self.win.results_view_combo.findData("timing"), 3)
            self.assertEqual(
                self.win._completed_run_facts()["model"]["analysis"]["timing_error_reason"],
                TIMING_ERROR_UNAVAILABLE_REASON,
            )
            self.assertIn(self.win._tr("timing_error_unavailable"), self.win.results_timing_text.text())
        self.assertEqual(builder.call_count, 1)
        self.assertIs(self.win.host_evidence_snapshot, snap)
        self.assertEqual(self.win.events, events_before)
        self.assertEqual(self.win.completed, completed)

    def test_manual_analysis_has_no_fixture_timing_view(self):
        self.win.radio_manual.setChecked(True)
        self._run([0, 25, 50, 75])
        self.assertEqual(self.win.results_view_combo.findData("timing"), -1)
        self.assertIsNone(self.win._completed_run_facts()["model"]["analysis"]["reference_interval_ms"])

    def test_fixture_mismatch_observation_is_a_finding(self):
        self._setup_fixture(hz="5", auto_sec="1")
        self._run([0, 25, 50, 75])
        text = self.win.results_observations_text.text()
        self.assertIn(self.win._tr("obs_fixture_hz_mismatch"), text)
        self.assertIn(self.win._tr("observed_average"), text)
        self.assertIn(self.win._tr("configured_reference"), text)
        self.assertIn(self.win._tr("difference"), text)
        self.assertIn("FIXTURE_HZ_MISMATCH", text)
        self.assertNotIn("DUT", text)
        body = "\n".join(text.splitlines()[1:])
        self.assertNotIn(self.win.results_context_label.text().split(" · ")[0], body)

    def test_no_observation_uses_neutral_message(self):
        self.win.radio_manual.setChecked(True)
        self._run([0, 120, 240, 360])
        facts = self._facts()
        if facts["model"]["observations"]:
            self.skipTest("this cadence still produced rule-based findings")
        self.assertEqual(
            self.win.results_observations_text.text(),
            self.win._tr("observations_none"),
        )
        self.assertNotIn("Host click count", self.win.results_observations_text.text())

    def test_evidence_tab_matches_frozen_snapshot(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        snap = self.win.host_evidence_snapshot
        self._show_results_tab(1)
        values = " ".join(
            f"{key.text()} {val.text()}" for key, val in self.win._results_evidence_cells
        )
        self.assertIn(str(snap["counts"]["expected_slot_count"]), values)
        self.assertIn(self.win._tr("neutral_host_evidence_note"), self.win.results_evidence_note.text())
        self.assertTrue(self.win.results_occupancy_bar.isVisibleTo(self.win))
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
            self._show_results_tab(1)
            self.assertIn(STRINGS["zh"]["neutral_host_evidence_note"], self.win.results_evidence_note.text())
        self.assertEqual(builder.call_count, 0)
        self.assertIs(self.win.host_evidence_snapshot, snap)

    def test_click_data_table_is_read_only_frozen_events(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        events_before = list(self.win.events)
        self._show_results_tab(2)
        table = self.win.results_click_table
        accepted = [e for e in self.win.events if e.get("accepted")]
        self.assertEqual(table.rowCount(), len(accepted))
        self.assertEqual(table.editTriggers(), QAbstractItemView.EditTrigger.NoEditTriggers)
        interval_item = None
        for row in range(table.rowCount()):
            if table.item(row, 3) and table.item(row, 3).text():
                interval_item = table.item(row, 3)
                break
        self.assertIsNotNone(interval_item)
        self.assertFalse(bool(interval_item.flags() & Qt.ItemFlag.ItemIsEditable))
        self.assertNotIn("drift", " ".join(
            table.horizontalHeaderItem(c).text().lower() for c in range(table.columnCount())
        ))
        table.selectRow(1)
        self._settle()
        self.assertEqual(self.win.events, events_before)
        model_rows = self.win._completed_run_facts()["model"]["click_data"]
        self.assertEqual(model_rows[1]["interval_ms"], accepted[1].get("press_interval_ms"))

    def test_compare_overlay_stays_on_analysis_and_preserves_run(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        first_id = self.win.run_id
        self.win.new_run()
        self._run([0, 25, 50, 75])
        current_events = list(self.win.events)
        current_host = self.win.host_evidence_snapshot
        locked = self.win.locked
        candidates = self.win._list_overlay_candidates()
        self.assertTrue(any(item.get("run_id") == first_id for item in candidates))
        archived = next(item for item in candidates if item.get("run_id") == first_id)
        self.assertTrue(archived.get("events"))
        self.win._set_overlay(list(archived["events"]), archived.get("metrics") or {}, f"session:{first_id}")
        self.assertTrue(self.win.completed)
        self.assertEqual(self.win.events, current_events)
        self.assertIs(self.win.host_evidence_snapshot, current_host)
        self.assertTrue(self.win.overlay_path.startswith("session:"))
        self.assertTrue(_under(self.win.btn_overlay, self.win.results_analysis_page))
        self.win.clear_overlay()
        self.assertEqual(self.win.overlay_path, "")
        self.assertTrue(self.win.completed)
        self.assertIs(self.win.locked, locked)
        self.assertEqual(self.win.events, current_events)
        self.assertIs(self.win.host_evidence_snapshot, current_host)

    def test_edit_setup_new_run_returns_setup_draft(self):
        self.win.device_edit.setText("KEEP-SETUP")
        self._setup_fixture(hz="40", tol="2", auto_sec="1")
        self._run([0, 25, 50, 75])
        events_before = list(self.win.events)
        self.win.btn_edit_setup_new_run.click()
        self._settle()
        self.assertIs(self.win.page_stack.currentWidget(), self.win.page_setup)
        self.assertEqual(self.win._lifecycle_state(), "draft")
        self.assertIsNone(self.win.profile_locked_settings)
        self.assertIsNone(self.win.locked)
        self.assertFalse(self.win.completed)
        self.assertFalse(self.win.running)
        self.assertEqual(self.win.events, [])
        self.assertTrue(self.win.device_edit.isEnabled())
        self.assertEqual(self.win.device_edit.text(), "KEEP-SETUP")
        self.assertEqual(self.win.hz_combo.currentText(), "40")
        self.assertEqual(self.win.timing_tol_edit.text(), "2")
        self.assertIn(self.win._tr("editing_next_run_note"), self.win.lbl_profile_status.text())
        self.assertTrue(self.win.session_runs)
        self.assertEqual(self.win.session_runs[-1]["events"], events_before)

    def test_histogram_bins_are_deterministic(self):
        bins = interval_histogram_bins([10.0, 10.0, 20.0, 30.0], max_bins=16)
        again = interval_histogram_bins([10.0, 10.0, 20.0, 30.0], max_bins=16)
        self.assertEqual(bins, again)
        self.assertEqual(sum(int(b["count"]) for b in bins), 4)
        self.assertEqual(interval_histogram_bins([]), [])

    def test_retired_count_tags_are_not_canonical_results(self):
        injected = [
            "MISS_CLICK_WARN", "MISS_CLICK_FAIL",
            "EXCESS_CLICK_COUNT_WARN", "EXCESS_CLICK_COUNT_FAIL",
            "FIXTURE_HZ_MISMATCH",
        ]
        self.assertEqual(qt_present_issue_tags(injected), ["FIXTURE_HZ_MISMATCH"])
        self.assertEqual(injected[-1], "FIXTURE_HZ_MISMATCH")
        settings = {"manual_mode": False, "fixture_hz": 5.0, "expected_clicks": 400, "target_clicks": 400}
        metrics = {"click_count": 20, "health": "FAIL"}
        count_only = [
            "MISS_CLICK_FAIL", "EXCESS_CLICK_COUNT_FAIL",
            "MISS_CLICK_WARN", "EXCESS_CLICK_COUNT_WARN",
        ]
        self.assertEqual(qt_visible_verdict(count_only, metrics, settings), "PASS")
        self.assertEqual(
            qt_visible_verdict(["CHATTER_HARD", "MISS_CLICK_FAIL"], metrics, settings),
            "FAIL",
        )
        self.assertEqual(
            qt_visible_verdict([], {"click_count": 20, "health": "FAIL"}, settings),
            "FAIL",
        )
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        with mock.patch(
            "mouse_click_stability_analyzer.completed_result._metrics_issue_tags",
            return_value=list(count_only),
        ):
            model = build_completed_result_model(
                locked=self.win.locked,
                events=list(self.win.events),
                run_id=self.win.run_id,
                target=self.win.target,
                operator=self.win.operator,
                start_time=self.win.start_time,
                stop_time=self.win.stop_time,
                host_evidence_snapshot=self.win.host_evidence_snapshot,
            )
        self.assertIsNotNone(model)
        for tag in count_only:
            self.assertNotIn(tag, model["assessment"]["tags"])
            self.assertNotIn(tag, self.win.results_observations_text.text())
        self.assertFalse(any(f["rule"] in count_only for f in model["observations"]))
        self.assertNotEqual(model["assessment"]["verdict"], "FAIL")

    def test_presentation_facts_tags_exclude_retired_count_tags(self):
        retired = [
            "MISS_CLICK_WARN", "MISS_CLICK_FAIL",
            "EXCESS_CLICK_COUNT_WARN", "EXCESS_CLICK_COUNT_FAIL",
        ]
        injected = retired + ["FIXTURE_HZ_MISMATCH"]
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        with mock.patch(
            "mouse_click_stability_analyzer.completed_result._metrics_issue_tags",
            return_value=list(injected),
        ):
            model = build_completed_result_model(
                locked=self.win.locked,
                events=list(self.win.events),
                run_id=self.win.run_id,
                target=self.win.target,
                operator=self.win.operator,
                start_time=self.win.start_time,
                stop_time=self.win.stop_time,
                host_evidence_snapshot=self.win.host_evidence_snapshot,
            )
            facts = self.win._completed_run_facts()
        self.assertEqual(model["assessment"]["tags"], ["FIXTURE_HZ_MISMATCH"])
        self.assertEqual(facts["tags"], ["FIXTURE_HZ_MISMATCH"])
        for tag in retired:
            self.assertNotIn(tag, facts["tags"])
        settings = {"manual_mode": False, "fixture_hz": 5.0}
        metrics = {"click_count": 20}
        self.assertEqual(qt_visible_verdict(["CHATTER_HARD", "MISS_CLICK_WARN"], metrics, settings), "FAIL")

    def test_excel_html_run_again_archives_run_id_once(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        rid = self.win.run_id
        paths = self._fake_bundle("idempotent")
        with mock.patch.object(qt_app, "write_reports", return_value=paths), \
             mock.patch.object(qt_app.QMessageBox, "information"), \
             mock.patch.object(qt_app.QMessageBox, "critical"):
            self.win.generate_excel_report()
            self.win.generate_html_report()
        self.win.new_run()
        self._settle()
        ids = [str(run.get("run_id") or "") for run in self.win.session_runs]
        self.assertEqual(ids.count(rid), 1)

    def test_archived_compare_candidate_keeps_dut_after_setup_edit(self):
        self.win.device_edit.setText("DUT-A")
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        rid = self.win.run_id
        verdict = self.win._completed_run_facts()["verdict"]
        self.win.edit_setup_new_run()
        self._settle()
        self.win.device_edit.setText("DUT-B")
        archived = next(run for run in self.win.session_runs if run.get("run_id") == rid)
        self.assertEqual(archived.get("target"), "DUT-A")
        self.assertEqual(archived.get("result"), verdict)
        candidates = self.win._list_overlay_candidates()
        meta = next(item for item in candidates if item.get("run_id") == rid)
        self.assertEqual(meta.get("target"), "DUT-A")
        self.assertIn("DUT-A", meta.get("label") or "")
        self.assertNotIn("DUT-B", meta.get("label") or "")
        self.assertEqual(meta.get("result"), verdict)

    def test_overlay_candidate_order_uses_stored_mtime(self):
        self._setup_fixture()
        self.win.run_id = "order-first"
        self._run([0, 25, 50, 75])
        first_id = self.win.run_id
        self.win.new_run()
        self.win.run_id = "order-second"
        self._run([0, 25, 50, 75])
        second_id = self.win.run_id
        self.win.new_run()
        by_id = {str(run.get("run_id") or ""): run for run in self.win.session_runs}
        by_id[first_id]["mtime"] = 100.0
        by_id[second_id]["mtime"] = 200.0
        with mock.patch("mouse_click_stability_analyzer.qt_shell.app.time.time", return_value=9999.0):
            order_a = [item.get("run_id") for item in self.win._list_overlay_candidates()]
            order_b = [item.get("run_id") for item in self.win._list_overlay_candidates()]
        self.assertEqual(order_a, order_b)
        self.assertNotEqual(first_id, second_id)
        self.assertLess(order_a.index(second_id), order_a.index(first_id))

    def test_compare_status_has_no_ab_winner(self):
        self._setup_fixture()
        self.win.run_id = "compare-first"
        self._run([0, 25, 50, 75])
        first_id = self.win.run_id
        self.win.new_run()
        self.win.run_id = "compare-second"
        self._run([0, 25, 50, 75])
        archived = next(run for run in self.win.session_runs if run.get("run_id") == first_id)
        self.win._set_overlay(list(archived["events"]), archived.get("metrics") or {}, f"session:{first_id}")
        status = "\n".join((
            self.win.overlay_delta_label.text(),
            self.win.results_overlay_status.text(),
        ))
        self.assertTrue(status.strip())
        self.assertNotRegex(status, r"(DUT score|Miss rate|Extra clicks|Delay / miss|SETUP score):\s*[AB]\b")
        self.assertNotRegex(status.lower(), r"\bwinner\b")

    def test_paired_histogram_uses_common_edges(self):
        current = [10.0, 12.0, 11.0, 13.0]
        overlay = [80.0, 90.0, 100.0, 110.0, 120.0]
        cur_bins, ov_bins = paired_interval_histograms(current, overlay)
        self.assertEqual([(b["lo"], b["hi"]) for b in cur_bins], [(b["lo"], b["hi"]) for b in ov_bins])
        self.assertEqual(sum(int(b["count"]) for b in cur_bins), 4)
        self.assertEqual(sum(int(b["count"]) for b in ov_bins), 5)
        self.assertEqual(float(cur_bins[0]["lo"]), 10.0)
        self.assertEqual(float(cur_bins[-1]["hi"]), 120.0)
        solo, empty = paired_interval_histograms(current, [])
        self.assertEqual(empty, [])
        self.assertEqual(solo, interval_histogram_bins(current))

    def test_results_styles_are_scoped(self):
        from mouse_click_stability_analyzer.qt_shell.styles import get_style

        for theme in ("light", "dark"):
            with self.subTest(theme=theme):
                sheet = get_style(theme)
                self.assertIn("QTabWidget#ResultsTabs QTabBar::tab", sheet)
                self.assertIn("QTableWidget#ResultsClickTable QHeaderView::section", sheet)
                self.assertNotRegex(sheet, r"(?m)^QTabBar::tab \{")
                self.assertNotRegex(sheet, r"(?m)^QHeaderView::section \{")
                self.assertEqual(sheet.count("QTabWidget#ResultsTabs QTabBar::tab {"), 1)

    def _completed_results_at(self, width: int, height: int) -> None:
        self.win.show()
        self.win.resize(width, height)
        self.win._show_workflow_page("results")
        self._settle()

    def test_results_content_width_grows_with_viewport(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        widths = []
        for width, height in ((1280, 720), (1440, 810), (1600, 900)):
            with self.subTest(size=(width, height)):
                self._completed_results_at(width, height)
                viewport = self.win.results_scroll.viewport().width()
                content = self.win.results_content
                expected = min(viewport, self.win.MAX_SETUP_CONTENT_WIDTH)
                self.assertLessEqual(abs(content.width() - expected), 2, (content.width(), viewport))
                self.assertGreaterEqual(content.geometry().right(), viewport - 3)
                self.assertEqual(self.win.results_scroll.horizontalScrollBar().maximum(), 0)
                widths.append(content.width())
        self.assertEqual(widths, sorted(widths))
        self.assertGreater(widths[-1], widths[0] + 200)

    def test_results_content_centers_only_beyond_maximum_width(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self._completed_results_at(1920, 1080)
        viewport = self.win.results_scroll.viewport().width()
        content = self.win.results_content
        self.assertGreater(viewport, self.win.MAX_SETUP_CONTENT_WIDTH)
        self.assertEqual(content.width(), self.win.MAX_SETUP_CONTENT_WIDTH)
        left = content.x()
        right = viewport - content.geometry().right() - 1
        self.assertGreater(left, 0)
        self.assertLessEqual(abs(left - right), 2)

    def test_desktop_analysis_is_horizontal_with_dominant_chart(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        for width, height in ((1280, 720), (1440, 810), (1600, 900)):
            with self.subTest(size=(width, height)):
                self._completed_results_at(width, height)
                split = self.win.results_analysis_split
                self.assertEqual(split.orientation(), Qt.Orientation.Horizontal)
                chart, observations = split.sizes()
                total = chart + observations
                self.assertGreaterEqual(chart / total, 0.62)
                self.assertLessEqual(chart / total, 0.72)
                self.assertGreaterEqual(chart, 600)
                self.assertGreaterEqual(observations, 240)
                self.assertEqual(self.win.results_header_grid.columns(), 2)
                self.assertEqual(self.win.results_actions_grid.columns(), 2)
                self.assertEqual(self.win.results_scroll.horizontalScrollBar().maximum(), 0)

    def test_narrow_results_reflow_to_one_column(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.setMinimumSize(1, 1)
        self._completed_results_at(820, 700)
        self.assertEqual(self.win.results_analysis_split.orientation(), Qt.Orientation.Vertical)
        self.assertEqual(self.win.results_header_grid.columns(), 1)
        self.assertEqual(self.win.results_actions_grid.columns(), 1)
        self.assertEqual(self.win.results_scroll.horizontalScrollBar().maximum(), 0)
        viewport = self.win.results_scroll.viewport().width()
        self.assertLessEqual(self.win.results_content.width(), viewport)

    def test_evidence_groups_reflow_by_width(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.setMinimumSize(1, 1)
        seen = {}
        for width, height in ((1600, 900), (1024, 640), (760, 640)):
            self._completed_results_at(width, height)
            self._show_results_tab(1)
            grid = self.win.results_evidence_grid
            seen[width] = grid.columns()
            self.assertEqual(grid.columns(), grid.columns_for_width(grid.width()))
            self.assertEqual(self.win.results_scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(seen[1600], 3)
        self.assertEqual(seen[1024], 2)
        self.assertEqual(seen[760], 1)
        self.assertEqual(len(self.win.results_evidence_groups), 5)
        self.assertEqual(len(self.win._results_evidence_cells), 24)

    def test_click_data_uses_available_results_width(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        for width, height in ((1280, 720), (1600, 900)):
            with self.subTest(size=(width, height)):
                self._completed_results_at(width, height)
                self._show_results_tab(2)
                table = self.win.results_click_table
                content = self.win.results_content
                self.assertGreaterEqual(table.width(), content.width() - 12)
                self.assertEqual(self.win.results_scroll.horizontalScrollBar().maximum(), 0)

    def test_capture_to_results_defers_reflow_without_window_resize(self):
        self.win.show()
        self.win.resize(1600, 900)
        self._settle()
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win._show_workflow_page("capture")
        self._settle()
        split = self.win.results_analysis_split
        split.setOrientation(Qt.Orientation.Vertical)
        self.win._results_split_synced_extent = -1
        size_before = self.win.size()
        facts_before = self.win._completed_run_facts()
        with mock.patch.object(qt_app, "build_completed_result_model") as rebuild, \
                mock.patch.object(qt_app, "build_fixture_host_evidence") as rebuild_evidence:
            self.win._show_workflow_page("results")
            self.assertTrue(self.win._results_layout_sync_pending)
            self._settle()
        rebuild.assert_not_called()
        rebuild_evidence.assert_not_called()
        self.assertEqual(self.win.size(), size_before)
        self.assertFalse(self.win._results_layout_sync_pending)
        self.assertEqual(split.orientation(), Qt.Orientation.Horizontal)
        chart, observations = split.sizes()
        self.assertGreaterEqual(chart / (chart + observations), 0.62)
        facts_after = self.win._completed_run_facts()
        self.assertEqual(facts_after["verdict"], facts_before["verdict"])
        self.assertEqual(facts_after["tags"], facts_before["tags"])

    def test_results_tab_change_and_window_state_schedule_layout_sync(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self._completed_results_at(1440, 810)
        with mock.patch.object(self.win, "_schedule_results_layout_sync") as schedule:
            self.win.results_tabs.setCurrentIndex(1)
            self.assertTrue(schedule.called)
        with mock.patch.object(self.win, "_schedule_results_layout_sync") as schedule:
            self.win.showMaximized()
            self._settle()
            self.win.showNormal()
            self._settle()
            self.assertTrue(schedule.called)

    def test_i18n_keys_exist(self):
        for lang in SUPPORTED_LANGS:
            for key in _RESULT_KEYS:
                with self.subTest(lang=lang, key=key):
                    value = str(STRINGS[lang].get(key) or "").strip()
                    self.assertTrue(value)
                    self.assertNotEqual(value, key)


if __name__ == "__main__":
    unittest.main()
