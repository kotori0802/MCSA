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
from PySide6.QtWidgets import QToolButton

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer import app as legacy_app
from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.overlay_io import extract_overlay_events, load_overlay_payload
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import format_host_evidence_review_lines

_T0 = 1000.0
_RESULT_KEYS = (
    "results_empty",
    "results_run_summary",
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
        values = " ".join(lab.text() for _, _, lab in self.win._results_summary_cells)
        self.assertIn("DUT-LOCK", values)
        self.assertIn("40 Hz", values)
        self.assertIn("±2 ms", values)
        self.assertIn("Left", values)
        self.assertNotIn("MUTATED", values)
        self.assertNotIn("5 Hz", values)
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
        self.assertEqual(len(self.win.results_observations_text.text().splitlines()), 4)

    def test_navigation_and_resize_preserve_values(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        snap = self.win.host_evidence_snapshot
        obs = self.win.results_observations_text.text()
        evidence = self.win.results_evidence_text.toPlainText()
        summary = [lab.text() for _, _, lab in self.win._results_summary_cells]
        self.win._show_workflow_page("capture")
        self.win.resize(1280, 720)
        self._settle()
        self.win._show_workflow_page("results")
        self.win.resize(1600, 900)
        self._settle()
        self.assertIs(self.win.host_evidence_snapshot, snap)
        self.assertEqual(self.win.results_observations_text.text(), obs)
        self.assertEqual(self.win.results_evidence_text.toPlainText(), evidence)
        self.assertEqual([lab.text() for _, _, lab in self.win._results_summary_cells], summary)

    def test_fixture_auto_stop_on_shows_host_evidence(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        self.assertTrue(self.win.results_evidence_card.isVisibleTo(self.win))
        text = self.win.results_evidence_text.toPlainText()
        for line in format_host_evidence_review_lines(self.win.host_evidence_snapshot, self.win._tr):
            self.assertIn(line, text)
        self.assertIn("HOST EVIDENCE", text)

    def test_manual_has_no_host_evidence(self):
        self.win.radio_manual.setChecked(True)
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertFalse(self.win.results_evidence_card.isVisibleTo(self.win))
        self.assertNotIn("HOST EVIDENCE", self.win.results_evidence_text.toPlainText())
        self.assertTrue(self.win.results_workspace.isVisibleTo(self.win))

    def test_fixture_auto_stop_off_has_no_host_evidence(self):
        self._setup_fixture(auto_sec=None)
        self._run([0, 25, 50, 75])
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertFalse(self.win.results_evidence_card.isVisibleTo(self.win))
        self.assertNotIn("Expected Slots", self.win.results_evidence_text.toPlainText())

    def test_language_switch_retranslates_without_rebuild(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            snap = self.win.host_evidence_snapshot
            self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
            self.assertEqual(self.win.lbl_results_summary.text(), STRINGS["zh"]["results_run_summary"].upper())
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
                visible = [c for c in self._result_cards() if c.isVisibleTo(self.win)]
                _no_pairwise_overlap(visible)
                self.assertGreaterEqual(self.win.results_evidence_text.height(), 120)
                self.assertLessEqual(self.win.results_workspace.height(), max(self.win.height() * 4, 4000))

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

    def test_i18n_keys_exist(self):
        for lang in SUPPORTED_LANGS:
            for key in _RESULT_KEYS:
                with self.subTest(lang=lang, key=key):
                    value = str(STRINGS[lang].get(key) or "").strip()
                    self.assertTrue(value)
                    self.assertNotEqual(value, key)


if __name__ == "__main__":
    unittest.main()
