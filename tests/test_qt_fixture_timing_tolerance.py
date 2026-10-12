"""Focused tests for the Phase 2B-3d2a.1 Fixture Timing Tolerance run setting."""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from mouse_click_stability_analyzer.core import normalize_settings
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.artifact_contract import AUTO_STOP_ENABLED_KEY
from mouse_click_stability_analyzer.qt_shell.app import (
    FIXTURE_TIMING_TOLERANCE_KEY,
    parse_fixture_timing_tolerance_ms,
    stamp_qt_auto_stop_enabled,
    stamp_qt_fixture_timing_tolerance,
)

_I18N_KEYS = (
    "fixture_timing_tolerance_ms",
    "fixture_timing_tolerance_placeholder",
    "fixture_timing_tolerance_invalid",
)


class ParseFixtureTimingToleranceTests(unittest.TestCase):
    def test_zero_is_a_real_configured_value(self):
        self.assertEqual(parse_fixture_timing_tolerance_ms("0"), 0.0)
        self.assertEqual(parse_fixture_timing_tolerance_ms(0), 0.0)

    def test_arbitrary_finite_non_negative_values_accepted_exactly(self):
        cases = (
            ("2.5", 2.5),
            ("0.1", 0.1),
            ("0.5", 0.5),
            ("1", 1.0),
            ("12.5", 12.5),
            ("13", 13.0),
            ("100", 100.0),
            ("  2  ", 2.0),
            (2.5, 2.5),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_fixture_timing_tolerance_ms(raw), expected)

    def test_invalid_values_rejected_without_default(self):
        for raw in (
            "", "   ", None, "abc", "-1", -1, -0.1, "nan", "inf", "-inf",
            math.nan, math.inf, -math.inf, True, False, [], {},
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_fixture_timing_tolerance_ms(raw)

    def test_overlapping_window_value_is_valid_input(self):
        self.assertEqual(parse_fixture_timing_tolerance_ms("13"), 13.0)


class StampFixtureTimingToleranceTests(unittest.TestCase):
    def test_fixture_value_stamped(self):
        out = stamp_qt_fixture_timing_tolerance({"a": 1}, manual=False, tolerance_ms=2.5)
        self.assertEqual(out[FIXTURE_TIMING_TOLERANCE_KEY], 2.5)
        self.assertEqual(out["a"], 1)

    def test_fixture_zero_stays_zero(self):
        out = stamp_qt_fixture_timing_tolerance({}, manual=False, tolerance_ms=0.0)
        self.assertEqual(out[FIXTURE_TIMING_TOLERANCE_KEY], 0.0)
        self.assertIsNotNone(out[FIXTURE_TIMING_TOLERANCE_KEY])

    def test_manual_is_none_not_zero(self):
        out = stamp_qt_fixture_timing_tolerance({}, manual=True, tolerance_ms=2.5)
        self.assertIsNone(out[FIXTURE_TIMING_TOLERANCE_KEY])

    def test_unconfigured_fixture_is_none(self):
        out = stamp_qt_fixture_timing_tolerance({}, manual=False, tolerance_ms=None)
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, out)

    def test_input_not_mutated(self):
        src = {"x": 1}
        stamp_qt_fixture_timing_tolerance(src, manual=False, tolerance_ms=1.0)
        self.assertEqual(src, {"x": 1})


class StampAutoStopEnabledTests(unittest.TestCase):
    def test_explicit_boolean_independent_of_duration(self):
        self.assertIs(stamp_qt_auto_stop_enabled({"duration_sec": 60}, enabled=True)[AUTO_STOP_ENABLED_KEY], True)
        self.assertIs(stamp_qt_auto_stop_enabled({"duration_sec": 60}, enabled=False)[AUTO_STOP_ENABLED_KEY], False)
        self.assertIs(stamp_qt_auto_stop_enabled({"duration_sec": 0}, enabled=True)[AUTO_STOP_ENABLED_KEY], True)

    def test_input_not_mutated(self):
        src = {"x": 1}
        stamp_qt_auto_stop_enabled(src, enabled=True)
        self.assertEqual(src, {"x": 1})


class LegacyFieldSeparationTests(unittest.TestCase):
    def test_new_key_is_not_legacy_key(self):
        self.assertEqual(FIXTURE_TIMING_TOLERANCE_KEY, "fixture_timing_tolerance_ms")
        self.assertNotEqual(FIXTURE_TIMING_TOLERANCE_KEY, "fixture_match_tolerance_ms")

    def test_legacy_normalization_unchanged(self):
        merged = normalize_settings({FIXTURE_TIMING_TOLERANCE_KEY: 2.5, "fixture_match_tolerance_ms": 9.0})
        self.assertEqual(merged["fixture_match_tolerance_ms"], 0.0)
        self.assertEqual(merged[FIXTURE_TIMING_TOLERANCE_KEY], 2.5)


class I18nTests(unittest.TestCase):
    def test_all_languages_have_keys(self):
        for lang in SUPPORTED_LANGS:
            for key in _I18N_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(STRINGS[lang].get(key) or "").strip())

    def test_label_does_not_claim_other_semantics(self):
        label = STRINGS["en"]["fixture_timing_tolerance_ms"].lower()
        for word in ("match", "double", "missing", "debounce", "acceptance", "tolerance"):
            self.assertNotIn(word, label)
        self.assertIn("±", STRINGS["en"]["fixture_timing_tolerance_ms"])
        self.assertEqual(STRINGS["en"]["fixture_timing_tolerance_ms"], "Schedule Association Window (± ms)")
        self.assertEqual(STRINGS["zh"]["fixture_timing_tolerance_ms"], "排程關聯範圍 (± ms)")


def _make_qapp():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # pragma: no cover - environment without Qt
        return None
    return QApplication.instance() or QApplication([])


class MainWindowToleranceTests(unittest.TestCase):
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

    def _fixture(self, tolerance_text: str, *, auto_stop: bool = False, hz: str = "10"):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(tolerance_text)
        (self.win.auto_stop_on if auto_stop else self.win.auto_stop_off).setChecked(True)
        if auto_stop:
            self.win.auto_stop_sec_combo.setCurrentText("1")

    def _lock_and_arm(self):
        self.assertTrue(self.win.lock_profile())
        self.assertTrue(self.win.arm_capture())
        self.win._cursor_over_capture_exclusion_ui = lambda: False

    def _begin(self):
        self._lock_and_arm()
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})

    def test_initial_state_is_blank(self):
        self.assertEqual(self.win.timing_tol_edit.text(), "")
        self.assertTrue(self.win.timing_tol_edit.placeholderText())

    def test_settings_ignores_hidden_field(self):
        self._fixture("2.5")
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.settings())
        self._fixture("0")
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.settings())
        self._fixture("10")
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.settings())

    def test_settings_does_not_raise_when_unconfigured(self):
        self._fixture("")
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.settings())

    def test_blank_fixture_locks_without_association(self):
        self._fixture("")
        self.assertTrue(self.win.lock_profile())
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.profile_locked_settings)
        self.assertEqual(self.win.events, [])

    def test_invalid_hidden_text_does_not_block_lock(self):
        for text in ("-1", "abc", "nan", "inf", "-inf"):
            with self.subTest(text=text):
                self._fixture(text)
                self.assertTrue(self.win.lock_profile())
                self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.profile_locked_settings)
                self.assertTrue(self.win.edit_profile())

    def test_normal_fixture_run_has_no_association_window(self):
        self._fixture("2.5")
        self._begin()
        self.assertTrue(self.win.running)
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)
        self.assertEqual(self.win.events[0]["press_elapsed_ms"], 0.0)

    def test_hidden_zero_is_not_synthesized(self):
        self._fixture("0")
        self._begin()
        self.assertTrue(self.win.running)
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)

    def test_auto_stop_off_locks_without_association(self):
        self._fixture("", auto_stop=False)
        self._begin()
        self.assertTrue(self.win.running)
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)
        self.assertEqual(self.win.locked["duration_sec"], 0)

    def test_auto_stop_on_does_not_stamp_hidden_window(self):
        self._fixture("1.5", auto_stop=True)
        self._begin()
        self.assertTrue(self.win.running)
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)
        self.assertEqual(self.win.locked["duration_sec"], 1.0)

    def test_fixture_setup_hides_association_widgets(self):
        self.win.radio_fixture.setChecked(True)
        for widget in (
            self.win.lbl_schedule_association, self.win.timing_tol_label,
            self.win.timing_tol_edit, self.win.assoc_context_box,
        ):
            self.assertFalse(widget.isVisibleTo(self.win), widget)

    def test_manual_blank_is_valid_and_not_applicable(self):
        self.win.radio_manual.setChecked(True)
        self.win.timing_tol_edit.setText("")
        self.assertFalse(self.win.timing_tol_edit.isVisibleTo(self.win))
        self._begin()
        self.assertTrue(self.win.running)
        self.assertIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)
        self.assertIsNone(self.win.locked[FIXTURE_TIMING_TOLERANCE_KEY])

    def test_manual_ignores_leftover_fixture_text(self):
        self.win.radio_manual.setChecked(True)
        self.win.timing_tol_edit.setText("5")
        self._begin()
        self.assertIsNone(self.win.locked[FIXTURE_TIMING_TOLERANCE_KEY])

    def test_locked_absence_immutable_after_widget_change(self):
        self._fixture("2.5")
        self._begin()
        self.win.timing_tol_edit.setText("9")
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)
        self.win.stop_run()
        self.win.timing_tol_edit.setText("7")
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, self.win.locked)

    def test_setup_lock_follows_other_controls(self):
        self._fixture("2.5")
        self.win._update_controls()
        self.assertTrue(self.win.timing_tol_edit.isEnabled())
        self.assertTrue(self.win.lock_profile())
        self.assertFalse(self.win.timing_tol_edit.isEnabled())
        self.assertTrue(self.win.arm_capture())
        t0 = float(self.win._arm_boundary_perf) + 0.001
        self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
        self.assertFalse(self.win.timing_tol_edit.isEnabled())
        self.assertEqual(self.win.timing_tol_edit.isEnabled(), self.win.hz_combo.isEnabled())
        self.win.stop_run()
        self.assertFalse(self.win.timing_tol_edit.isEnabled())
        self.assertEqual(self.win.timing_tol_edit.isEnabled(), self.win.hz_combo.isEnabled())

    def test_new_run_clears_run_lock_and_keeps_profile(self):
        self._fixture("2.5")
        self._begin()
        self.win.stop_run()
        self.win.new_run()
        self.assertIsNone(self.win.locked)
        self.assertIsNotNone(self.win.profile_locked_settings)
        self.assertFalse(self.win.timing_tol_edit.isEnabled())
        self.assertEqual(self.win.timing_tol_edit.text(), "2.5")
        self.assertEqual(self.win.hz_combo.currentText(), "10")

    def test_legacy_key_not_repurposed_in_settings(self):
        self._fixture("2.5")
        s = self.win.settings()
        self.assertIn(s.get("fixture_match_tolerance_ms", 0.0), (0.0, None))
        self.assertNotIn(FIXTURE_TIMING_TOLERANCE_KEY, s)

    def test_settings_auto_stop_enabled_follows_toggle(self):
        self._fixture("2.5", auto_stop=True)
        self.assertIs(self.win.settings()[AUTO_STOP_ENABLED_KEY], True)
        self._fixture("2.5", auto_stop=False)
        self.assertIs(self.win.settings()[AUTO_STOP_ENABLED_KEY], False)

    def test_auto_stop_enabled_is_locked_and_reaches_evidence(self):
        for auto_stop in (True, False):
            with self.subTest(auto_stop=auto_stop):
                self._fixture("2.5", auto_stop=auto_stop)
                self._begin()
                self.assertIs(self.win.locked[AUTO_STOP_ENABLED_KEY], auto_stop)
                self.win.stop_run()
                (self.win.auto_stop_off if auto_stop else self.win.auto_stop_on).setChecked(True)
                self.assertIs(self.win.settings()[AUTO_STOP_ENABLED_KEY], not auto_stop)
                self.win.finish_report(notify=False)
                evidence = json.loads(Path(self.win.report_paths["evidence_json"]).read_text(encoding="utf-8"))
                self.assertIs(evidence["settings"][AUTO_STOP_ENABLED_KEY], auto_stop)
                self.win.new_run()
                self.win.edit_setup_new_run()


if __name__ == "__main__":
    unittest.main()
