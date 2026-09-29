"""Focused tests for Phase 2B-3d2b Host Evidence REVIEW presentation."""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer import app as legacy_app
from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS, t
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import format_host_evidence_review_lines

_T0 = 1000.0
_HE_KEYS = ("he_title", "he_config", "he_counts", "he_windows", "he_observations", "he_timing", "he_overlap")
_FORBIDDEN_EN = (
    "missing click", "double click", "double-click", "extra click", "bounce", "chatter",
    "debounce", "hardware failure", "pass", "fail", "warning", "warn", "verdict", "root cause",
    "health", "score", "review required",
)
_FORBIDDEN_ZH = ("漏點", "漏鍵", "雙擊", "連點", "彈跳", "通過", "失敗", "警告")


def _en(key, **kwargs):
    return t("en", key, **kwargs)


def _zh(key, **kwargs):
    return t("zh", key, **kwargs)


def _snapshot(**overrides):
    snap = {
        "configuration": {
            "capture_duration_s": 10.0,
            "fixture_frequency_hz": 40.0,
            "reference_interval_ms": 25.0,
            "timing_tolerance_ms": 2.0,
            "matching_windows_can_overlap": False,
        },
        "counts": {
            "expected_slot_count": 400,
            "raw_host_press_count": 401,
            "in_window_host_press_count": 399,
            "host_count_delta_vs_expected_slots": -1,
            "host_count_deficit_vs_expected_slots": 1,
            "host_count_excess_vs_expected_slots": 0,
        },
        "matching": {
            "empty_expected_slot_count": 3,
            "single_occupancy_slot_count": 395,
            "multi_occupancy_slot_count": 2,
            "matched_host_observation_count": 397,
            "unmatched_host_observation_count": 1,
            "ambiguous_host_observation_count": 1,
            "outside_capture_window_observation_count": 2,
        },
        "timing": {
            "matched_delta_stats": {"count": 397, "average": 0.125, "minimum": -1.2, "maximum": 1.85, "stdev": 0.62},
            "matched_absolute_delta_stats": {"count": 397, "average": 0.5, "minimum": 0.0, "maximum": 1.85, "stdev": 0.4},
        },
    }
    for section, values in overrides.items():
        snap[section].update(values)
    return snap


class FormatterTests(unittest.TestCase):
    def test_none_snapshot_yields_no_lines(self):
        self.assertEqual(format_host_evidence_review_lines(None, _en), [])
        self.assertEqual(format_host_evidence_review_lines({}, _en), [])

    def test_values_come_from_snapshot(self):
        text = "\n".join(format_host_evidence_review_lines(_snapshot(), _en))
        for fragment in (
            "Fixture Frequency 40 Hz",
            "Capture Duration 10.000 s",
            "Timing Tolerance ±2.000 ms",
            "Reference Interval 25.000 ms",
            "Expected Slots 400",
            "In-window Host Presses 399",
            "Host Count Delta -1",
            "Raw Host Presses 401",
            "Unoccupied Expected Windows 3",
            "Single-observation Windows 395",
            "Multi-observation Expected Windows 2",
            "Matched Host Observations 397",
            "Unmatched Host Observations 1",
            "Ambiguous Host Observations 1",
            "Outside Capture Window 2",
            "Average +0.125",
            "Minimum -1.200",
            "Maximum +1.850",
            "Std Dev 0.620",
            "Average Absolute Timing Error 0.500",
        ):
            self.assertIn(fragment, text)

    def test_compact_line_count(self):
        lines = format_host_evidence_review_lines(_snapshot(), _en)
        self.assertGreaterEqual(len(lines), 6)
        self.assertLessEqual(len(lines), 16)
        overlap = format_host_evidence_review_lines(
            _snapshot(configuration={"matching_windows_can_overlap": True}), _en
        )
        self.assertEqual(len(overlap), len(lines) + 1)
        self.assertIn("Matching windows overlap: Yes", overlap)

    def test_negative_delta_stays_negative(self):
        text = "\n".join(format_host_evidence_review_lines(_snapshot(), _en))
        self.assertIn("Host Count Delta -1", text)
        self.assertNotIn("missing", text.lower())

    def test_positive_delta_stays_positive(self):
        snap = _snapshot(counts={"host_count_delta_vs_expected_slots": 1})
        text = "\n".join(format_host_evidence_review_lines(snap, _en))
        self.assertIn("Host Count Delta +1", text)
        self.assertNotIn("extra click", text.lower())
        self.assertNotIn("double click", text.lower())

    def test_zero_delta_unsigned(self):
        snap = _snapshot(counts={"host_count_delta_vs_expected_slots": 0})
        text = "\n".join(format_host_evidence_review_lines(snap, _en))
        self.assertIn("Host Count Delta 0 ", text)

    def test_compensating_case_shows_all_facts(self):
        snap = _snapshot(
            counts={"host_count_delta_vs_expected_slots": 0},
            matching={"empty_expected_slot_count": 1, "multi_occupancy_slot_count": 1},
        )
        text = "\n".join(format_host_evidence_review_lines(snap, _en))
        self.assertIn("Host Count Delta 0", text)
        self.assertIn("Unoccupied Expected Windows 1", text)
        self.assertIn("Multi-observation Expected Windows 1", text)
        for word in ("clean", "ok", "pass"):
            self.assertNotIn(f" {word} ", f" {text.lower()} ")

    def test_none_timing_stats_show_dash(self):
        none_stats = {"count": 0, "average": None, "minimum": None, "maximum": None, "stdev": None}
        snap = _snapshot()
        snap["timing"] = {"matched_delta_stats": dict(none_stats), "matched_absolute_delta_stats": dict(none_stats)}
        timing_line = format_host_evidence_review_lines(snap, _en)[5]
        self.assertIn("Average — ", timing_line)
        self.assertIn("Std Dev —", timing_line)
        self.assertNotIn("0.000", timing_line)

    def test_zero_stat_is_not_dash(self):
        zero = {"count": 4, "average": 0.0, "minimum": 0.0, "maximum": 0.0, "stdev": 0.0}
        snap = _snapshot()
        snap["timing"] = {"matched_delta_stats": dict(zero), "matched_absolute_delta_stats": dict(zero)}
        timing_line = format_host_evidence_review_lines(snap, _en)[5]
        self.assertIn("Average 0.000", timing_line)
        self.assertNotIn("—", timing_line)

    def test_ambiguity_and_outside_visible_without_verdict(self):
        snap = _snapshot(matching={"ambiguous_host_observation_count": 7, "outside_capture_window_observation_count": 5})
        text = "\n".join(format_host_evidence_review_lines(snap, _en))
        self.assertIn("Ambiguous Host Observations 7", text)
        self.assertIn("Outside Capture Window 5", text)

    def test_snapshot_not_mutated(self):
        snap = _snapshot()
        before = copy.deepcopy(snap)
        format_host_evidence_review_lines(snap, _en)
        self.assertEqual(snap, before)

    def test_decimal_frequency_compact(self):
        snap = _snapshot(configuration={"fixture_frequency_hz": 7.5, "reference_interval_ms": 1000.0 / 7.5})
        text = "\n".join(format_host_evidence_review_lines(snap, _en))
        self.assertIn("Fixture Frequency 7.5 Hz", text)
        self.assertIn("Reference Interval 133.333 ms", text)

    def test_no_forbidden_terms_english(self):
        for snap in (
            _snapshot(),
            _snapshot(configuration={"matching_windows_can_overlap": True}),
            _snapshot(counts={"host_count_delta_vs_expected_slots": 3}),
        ):
            text = "\n".join(format_host_evidence_review_lines(snap, _en)).lower()
            for word in _FORBIDDEN_EN:
                self.assertNotIn(word, text)

    def test_no_forbidden_terms_chinese(self):
        snap = _snapshot(configuration={"matching_windows_can_overlap": True})
        text = "\n".join(format_host_evidence_review_lines(snap, _zh))
        for word in _FORBIDDEN_ZH:
            self.assertNotIn(word, text)
        self.assertIn("主機觀測證據", text)
        self.assertIn("未佔用預期時間窗 3", text)

    def test_all_languages_have_keys_and_render(self):
        for lang in SUPPORTED_LANGS:
            for key in _HE_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(STRINGS[lang].get(key) or "").strip())
            lines = format_host_evidence_review_lines(
                _snapshot(configuration={"matching_windows_can_overlap": True}),
                lambda k, _lang=lang, **kw: t(_lang, k, **kw),
            )
            joined = "\n".join(lines)
            with self.subTest(lang=lang):
                self.assertNotIn("{", joined)
                self.assertIn("400", joined)
                self.assertIn("-1", joined)


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover - environment without Qt
        return None
    return QApplication.instance() or QApplication([])


class ReviewPresentationTests(unittest.TestCase):
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
        self.win.listening = True

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def _setup_fixture(self, *, auto_sec: str | None = "0.1", tol: str = "2", hz: str = "40"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tol)
        if auto_sec is None:
            self.win.auto_stop_off.setChecked(True)
        else:
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText(auto_sec)

    def _run(self, offsets, *, stop=True):
        self.win.listening = True
        self.win.completed = False
        self.win._begin_session_from_first_click("Left", _T0, _T0 + 0.01, {})
        self.assertTrue(self.win.running)
        for off in offsets[1:]:
            press = _T0 + off / 1000.0
            self.win.record_click("Left", press, press + 0.01, {})
        if stop:
            self.win.stop_run()

    def _review(self):
        return self.win.review_text.toPlainText()

    def _set_lang(self, lang):
        self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData(lang))

    def test_eligible_fixture_review_shows_evidence(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 104])
        text = self._review()
        snap = self.win.host_evidence_snapshot
        self.assertIsNotNone(snap)
        expected_lines = format_host_evidence_review_lines(snap, self.win._tr)
        for line in expected_lines:
            self.assertIn(line, text)
        self.assertIn("Expected Slots 4", text)
        self.assertIn("In-window Host Presses 4", text)
        self.assertIn("Host Count Delta 0", text)
        self.assertIn("Outside Capture Window 1", text)
        self.win._show_workflow_page("capture")
        self.assertTrue(self.win.review_text.isVisibleTo(self.win))

    def test_legacy_review_lines_preserved_and_first(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        text = self._review()
        legacy_part = text.split("\n\n", 1)[0]
        self.assertEqual(len(legacy_part.splitlines()), 4)
        self.assertNotIn(self.win._tr("he_title"), legacy_part)
        self.assertIn(self.win._tr("he_title"), text)

    def test_review_matches_injected_snapshot(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.host_evidence_snapshot = _snapshot()
        self.win._refresh_metrics(final=True)
        text = self._review()
        for fragment in ("Expected Slots 400", "Host Count Delta -1", "Unoccupied Expected Windows 3",
                         "Multi-observation Expected Windows 2", "Unmatched Host Observations 1",
                         "Ambiguous Host Observations 1", "Outside Capture Window 2", "Minimum -1.200"):
            self.assertIn(fragment, text)

    def test_manual_review_has_no_evidence(self):
        self.win.radio_manual.setChecked(True)
        self._run([0, 25, 50, 75])
        text = self._review()
        self.assertTrue(text.strip())
        self.assertEqual(len(text.splitlines()), 4)
        self.assertNotIn(self.win._tr("he_title"), text)
        self.assertNotIn("Expected Slots", text)

    def test_fixture_auto_stop_off_has_no_evidence(self):
        self._setup_fixture(auto_sec=None)
        self._run([0, 25, 50, 75])
        text = self._review()
        self.assertIsNone(self.win.host_evidence_snapshot)
        self.assertEqual(len(text.splitlines()), 4)
        self.assertNotIn("Expected Slots", text)
        self.assertNotIn("Host Count Delta", text)

    def test_not_shown_while_running(self):
        self._setup_fixture(auto_sec="3600")
        self._run([0, 25, 50], stop=False)
        self.win._refresh_metrics(final=False)
        self.assertNotIn(self.win._tr("he_title"), self._review())

    def test_language_switch_retranslates_without_rebuild(self):
        self._setup_fixture()
        with mock.patch.object(qt_app, "build_fixture_host_evidence", wraps=build_fixture_host_evidence) as builder:
            self._run([0, 25, 50, 75])
            snap = self.win.host_evidence_snapshot
            before = copy.deepcopy(snap)
            self.assertIn("Expected Slots 4", self._review())
            self._set_lang("zh")
            zh_text = self._review()
            self.assertIn("主機觀測證據", zh_text)
            self.assertIn("預期時間窗 4", zh_text)
            self._set_lang("en")
            self.assertIn("Expected Slots 4", self._review())
            self.win._refresh_metrics(final=True)
            self.win.repaint()
        self.assertEqual(builder.call_count, 1)
        self.assertIs(self.win.host_evidence_snapshot, snap)
        self.assertEqual(snap, before)

    def test_new_run_removes_evidence_text(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.assertIn(self.win._tr("he_title"), self._review())
        self.win._show_workflow_page("capture")
        self.win.new_run()
        self.assertEqual(self._review(), "")
        self.assertFalse(self.win.review_text.isVisibleTo(self.win))
        self.win._refresh_metrics(final=False)
        self.assertNotIn(self.win._tr("he_title"), self._review())

    def test_verdict_unchanged_by_presentation(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75, 90])
        settings = self.win.locked
        annotated = legacy_app.annotate_events(list(self.win.events), settings)
        m = legacy_app.build_payload("", "", settings, annotated, run_id="x").get("metrics") or {}
        tags = legacy_app._metrics_issue_tags(m, settings, annotated)
        verdict = qt_app.qt_visible_verdict(tags, m, settings)
        self.assertEqual(self.win.val_verdict.text(), str(verdict))
        status, alert = self.win.status_label.text(), self.win.alert_label.text()
        self.win.host_evidence_snapshot = None
        self.win._refresh_metrics(final=True)
        self.assertEqual(self.win.val_verdict.text(), str(verdict))
        self.assertEqual((self.win.status_label.text(), self.win.alert_label.text()), (status, alert))

    def test_no_report_or_session_wiring(self):
        self._setup_fixture()
        self._run([0, 25, 50, 75])
        self.win.new_run()
        run = self.win.session_runs[-1]
        self.assertFalse(any("evidence" in str(k).lower() for k in run))
        report_source = Path(legacy_app.__file__).read_text(encoding="utf-8")
        for token in ("host_evidence", "format_host_evidence", "he_title"):
            self.assertNotIn(token, report_source)


if __name__ == "__main__":
    unittest.main()
