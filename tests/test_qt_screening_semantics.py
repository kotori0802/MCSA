"""Phase 4D-2g-2: Screening presentation vs internal heuristics."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QLabel, QLineEdit

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.app import RULE_PRESETS
from mouse_click_stability_analyzer.cadence import class_to_tags, classify_click
from mouse_click_stability_analyzer.completed_result import RUN_STATUS_COMPLETE
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS, t
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.presentation import (
    SCREENING_PRESENTATION_KEYS,
    screening_presentation_label,
)

_FORBIDDEN_SETUP_PHRASES = (
    "Chatter",
    "Double-click",
    "Actuation short",
    "Low hold",
    "Interval CV",
    "Screening PASS",
    "Validation PASS",
)
_VISIBLE_MAP = {
    "ON_CADENCE": {"en": "Observation", "zh": "觀測"},
    "CHATTER_BOUNCE": {"en": "Very short interval", "zh": "極短間隔"},
    "CHATTER_HARD": {"en": "Very short interval", "zh": "極短間隔"},
    "TRUE_EXTRA_CLICK": {"en": "Extra observation", "zh": "額外觀測"},
    "HIGH_PROBABILITY_DOUBLE_CLICK": {"en": "Extra observation", "zh": "額外觀測"},
    "INCOMPLETE_REBOUND": {"en": "Short hold", "zh": "短按住"},
    "FIXTURE_ACTUATION_TOO_SHORT": {"en": "Short hold", "zh": "短按住"},
    "LOW_HOLD_WARNING": {"en": "Short hold", "zh": "短按住"},
    "MISS_OR_SLOW": {"en": "Long interval", "zh": "長間隔"},
    "LONG_INTERVAL_SPIKE_WARN": {"en": "Long interval", "zh": "長間隔"},
}


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover
        return None
    return QApplication.instance() or QApplication([])


def _tr(lang: str):
    return lambda key, **kwargs: t(lang, key, **kwargs)


class PresentationHelperTests(unittest.TestCase):
    def test_internal_enums_are_not_renamed(self):
        self.assertEqual(classify_click(25.0, 80.0, {"fixture_hz": 40, "fixture_reference_hz": 40}), "ON_CADENCE")
        self.assertEqual(classify_click(5.0, 80.0, {"chatter_threshold_ms": 8}), "CHATTER_BOUNCE")
        self.assertEqual(
            classify_click(20.0, 80.0, {"chatter_threshold_ms": 8, "duplicate_click_threshold_ms": 30}),
            "TRUE_EXTRA_CLICK",
        )
        self.assertEqual(
            classify_click(80.0, 3.0, {"fixture_actuation_too_short_ms": 5, "duplicate_click_threshold_ms": 30}),
            "INCOMPLETE_REBOUND",
        )
        self.assertEqual(
            classify_click(200.0, 80.0, {"fixture_hz": 10, "fixture_reference_hz": 10}),
            "MISS_OR_SLOW",
        )
        self.assertEqual(class_to_tags("CHATTER_BOUNCE", False), ["CHATTER_HARD", "CHATTER_BOUNCE"])
        self.assertEqual(class_to_tags("TRUE_EXTRA_CLICK", False), ["HIGH_PROBABILITY_DOUBLE_CLICK"])

    def test_visible_aliases_differ_from_internal_names(self):
        for internal, expected in _VISIBLE_MAP.items():
            with self.subTest(internal=internal):
                self.assertEqual(screening_presentation_label(internal, _tr("en")), expected["en"])
                self.assertEqual(screening_presentation_label(internal, _tr("zh")), expected["zh"])
                self.assertIn(internal, SCREENING_PRESENTATION_KEYS)
                self.assertNotEqual(screening_presentation_label(internal, _tr("en")), internal)

    def test_aliases_do_not_claim_root_cause(self):
        for lang in SUPPORTED_LANGS:
            for internal in _VISIBLE_MAP:
                label = screening_presentation_label(internal, _tr(lang)).lower()
                with self.subTest(lang=lang, internal=internal):
                    self.assertNotIn("on cadence", label)
                    self.assertNotIn("double-click", label)
                    self.assertNotIn("double click", label)
                    self.assertNotIn("chatter", label)
                    self.assertNotIn("bounce", label)
                    self.assertNotIn("rebound", label)
                    self.assertNotIn("delay", label)
                    self.assertNotIn("miss", label)

    def test_both_languages_have_screening_copy(self):
        self.assertEqual(STRINGS["en"]["screening"], "Screening")
        self.assertEqual(STRINGS["en"]["screening_measurement_only"], "Measurement only")
        self.assertEqual(
            STRINGS["en"]["screening_measurement_only_note"],
            "No approved screening or validation profile is applied.",
        )
        self.assertEqual(STRINGS["zh"]["screening"], "篩查")
        self.assertEqual(STRINGS["zh"]["screening_measurement_only"], "僅量測")
        self.assertEqual(STRINGS["zh"]["screening_measurement_only_note"], "未套用核准的篩查或驗證設定檔。")
        for lang in SUPPORTED_LANGS:
            note = STRINGS[lang]["screening_measurement_only_note"]
            self.assertNotIn("PASS", note)
            self.assertNotIn("FAIL", note)


class SetupScreeningPresentationTests(unittest.TestCase):
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

    def _setup_text(self) -> str:
        return " ".join(
            w.text() for w in self.win.page_setup.findChildren(QLabel) if w.isVisibleTo(self.win.page_setup)
        )

    def test_setup_has_no_editable_custom_limits(self):
        self.win._show_workflow_page("setup")
        self.assertEqual(self.win._limit_edits, {})
        self.assertEqual(self.win.setup_screening_card.findChildren(QLineEdit), [])
        labels = [w.text() for w in self.win.page_setup.findChildren(QLabel)]
        for key in qt_app._QT_CUSTOM_LIMIT_LABEL_KEYS.values():
            self.assertNotIn(self.win._tr(key), labels)
        page = self._setup_text()
        for phrase in _FORBIDDEN_SETUP_PHRASES:
            self.assertNotIn(phrase, page)

    def test_setup_shows_measurement_only_screening(self):
        self.win._show_workflow_page("setup")
        self.assertEqual(self.win.lbl_screening.text(), "SCREENING")
        self.assertEqual(self.win.lbl_screening_status.text(), "Measurement only")
        self.assertEqual(
            self.win.lbl_screening_note.text(),
            "No approved screening or validation profile is applied.",
        )
        self.assertNotIn("PASS", self.win.lbl_screening_status.text())
        self.win.lang_combo.setCurrentIndex(self.win.lang_combo.findData("zh"))
        self.assertEqual(self.win.lbl_screening.text(), "篩查")
        self.assertEqual(self.win.lbl_screening_status.text(), "僅量測")
        self.assertEqual(self.win.lbl_screening_note.text(), "未套用核准的篩查或驗證設定檔。")

    def test_lock_manual_and_fixture_still_succeed(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win._lifecycle_state(), "ready")
        self.assertTrue(self.win.arm_capture())
        self.win.edit_profile()
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("1.5")
        self.win.auto_stop_on.setChecked(True)
        self.win.auto_stop_sec_combo.setCurrentText("30")
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        self.assertEqual(snap["fixture_reference_hz"], 40.0)
        self.assertEqual(snap[qt_app.FIXTURE_TIMING_TOLERANCE_KEY], 1.5)
        self.assertEqual(self.win.hz_interval_label.text(), self.win._tr("reference_interval_derived", ms="25.00"))
        self.assertNotEqual(snap[qt_app.FIXTURE_TIMING_TOLERANCE_KEY], snap["chatter_threshold_ms"])

    def test_legacy_defaults_are_stamped_not_shown_as_product_limits(self):
        defaults = qt_app.qt_custom_limit_defaults()
        self.assertEqual(defaults, {key: float(RULE_PRESETS["Strict"][key]) for key in qt_app.QT_CUSTOM_LIMIT_KEYS})
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("2")
        self.assertTrue(self.win.lock_profile())
        snap = self.win.profile_locked_settings
        for key, value in defaults.items():
            self.assertEqual(snap[key], value)
        self.win.nav_setup.click()
        page = self._setup_text()
        self.assertNotIn("8 ms", page)
        self.assertNotIn("30 ms", page)
        self.assertNotIn("product", page.lower())
        self.assertNotIn("acceptance", page.lower())
        preview = " ".join(
            f"{key.text()} {val.text()}"
            for cell, key, val in self.win._preview_cells
            if not cell.isHidden()
        )
        for key in qt_app.QT_CUSTOM_LIMIT_KEYS:
            self.assertNotIn(key, preview)
            self.assertNotIn(key, page)

    def test_capture_live_flags_use_neutral_labels(self):
        self.win._retranslate_ui()
        extra = self.win._stat_name_labels["extra"].text()
        rebound = self.win._stat_name_labels["rebound"].text()
        delay = self.win._stat_name_labels["delay"].text()
        self.assertEqual(extra, "EXTRA OBSERVATION")
        self.assertEqual(rebound, "SHORT HOLD")
        self.assertEqual(delay, "LONG INTERVAL")
        self.assertNotIn("DOUBLE", extra)
        self.assertNotIn("REBOUND", rebound)
        self.assertNotIn("DELAY", delay)
        self.assertNotIn("CHATTER", extra)


class MeasurementContainmentTests(unittest.TestCase):
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

    def _run_fixture(self, offsets, *, hz="40", tol="2"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tol)
        self.win.auto_stop_on.setChecked(True)
        self.win.auto_stop_sec_combo.setCurrentText("1")
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        for off in offsets[1:]:
            press = t0 + off / 1000.0
            self.win.record_click("Left", press, press + 0.01, {})
        self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()
        return t0

    def test_fixed_observations_keep_measurement_and_internal_classes(self):
        offsets = [0, 25, 50, 75]
        self._run_fixture(offsets)
        facts = self.win._completed_run_facts()
        self.assertIsNotNone(facts)
        events = [e for e in self.win.events if e.get("accepted")]
        self.assertEqual(len(events), 4)
        self.assertEqual(facts["run_status"], RUN_STATUS_COMPLETE)
        self.assertEqual(self.win.val_verdict.text(), RUN_STATUS_COMPLETE)
        intervals = [e.get("press_interval_ms") for e in events]
        holds = [e.get("hold_ms") for e in events]
        classes = [row["state"] for row in facts["model"]["click_data"]]
        self.assertIsNone(intervals[0])
        for value in intervals[1:]:
            self.assertAlmostEqual(float(value), 25.0, places=3)
        for value in holds:
            self.assertAlmostEqual(float(value), 10.0, places=3)
        self.assertEqual(classes, ["ON_CADENCE", "ON_CADENCE", "ON_CADENCE", "ON_CADENCE"])
        self.assertEqual(facts["metrics"].get("click_count"), 4)
        snap = self.win.host_evidence_snapshot
        self.assertEqual(snap["matching"]["single_occupancy_slot_count"], 4)
        self.assertEqual(snap["matching"]["unmatched_host_observation_count"], 0)
        self.assertEqual(snap["timing"]["matched_delta_stats"]["count"], 4)
        self.assertEqual(self.win.profile_locked_settings["chatter_threshold_ms"], 8.0)
        self.assertEqual(self.win.profile_locked_settings["duplicate_click_threshold_ms"], 30.0)

    def test_start_capture_t0_and_auto_stop_unchanged(self):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText("40")
        self.win.timing_tol_edit.setText("2")
        self.win.auto_stop_on.setChecked(True)
        self.win.auto_stop_sec_combo.setCurrentText("1")
        self.assertTrue(self.win.lock_profile())
        self.assertFalse(self.win.capture_armed)
        self.assertIsNone(self.win.start_time)
        self.assertTrue(self.win.arm_capture())
        self.assertTrue(self.win.capture_armed)
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertTrue(self.win.running)
        self.assertAlmostEqual(float(self.win.start_time), t0)
        self.assertGreater(float(self.win.end_time), t0)
        self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()
        self.assertTrue(self.win.completed)

    def test_capture_alert_does_not_show_raw_heuristic_enums(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        for off in (5, 80, 160):
            press = t0 + off / 1000.0
            self.win.record_click("Left", press, press + 0.01, {})
        self.win.stop_run()
        if self.win._post_run_input_guard_active:
            self.win._release_post_run_input_guard()
        alert = self.win.alert_label.text()
        for token in (
            "CHATTER_HARD",
            "CHATTER_BOUNCE",
            "HIGH_PROBABILITY_DOUBLE_CLICK",
            "TRUE_EXTRA_CLICK",
            "Double-click",
            "Chatter",
        ):
            self.assertNotIn(token, alert)
        facts = self.win._completed_run_facts()
        tags = facts["model"]["assessment"]["tags_all"]
        if "CHATTER_HARD" in tags:
            self.assertIn(self.win._tr("legend_chatter"), alert)


if __name__ == "__main__":
    unittest.main()
