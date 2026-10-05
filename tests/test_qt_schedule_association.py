"""Phase 4E-A: Schedule Association Window presentation semantics."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from mouse_click_stability_analyzer.fixture_matching import match_fixture_press_observations
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell import app as qt_app
from mouse_click_stability_analyzer.qt_shell.app import (
    FIXTURE_TIMING_TOLERANCE_KEY,
    format_association_window_ms,
    format_percent_of_interval,
    schedule_association_context,
)

_VERDICT_WORDS = ("PASS", "FAIL", "WARN", "acceptance", "spec")


class ScheduleAssociationContextTests(unittest.TestCase):
    def test_percent_of_reference_interval(self):
        for hz, window, expected in (("10", "5", "5.0 %"), ("20", "5", "10.0 %"), ("40", "5", "20.0 %")):
            with self.subTest(hz=hz):
                ctx = schedule_association_context(hz, window)
                self.assertEqual(format_percent_of_interval(ctx["percent_of_interval"]), expected)
                self.assertEqual(format_association_window_ms(ctx["window_ms"]), "±5.00 ms")

    def test_overlap_uses_inclusive_two_w_ge_t(self):
        self.assertIs(schedule_association_context("40", "5")["windows_overlap"], False)
        self.assertEqual(schedule_association_context("40", "5")["reference_interval_ms"], 25.0)
        ten_ms = schedule_association_context("100", "5")
        self.assertEqual(ten_ms["reference_interval_ms"], 10.0)
        self.assertIs(ten_ms["windows_overlap"], True)
        self.assertIs(schedule_association_context("40", "12.5")["windows_overlap"], True)
        self.assertIs(schedule_association_context("40", "12.49")["windows_overlap"], False)

    def test_overlap_agrees_with_matcher_flag(self):
        for hz, window in ((10, 5.0), (40, 5.0), (40, 12.5), (100, 5.0), (6, 83.33), (6, 83.34)):
            with self.subTest(hz=hz, window=window):
                ctx = schedule_association_context(str(hz), str(window))
                matched = match_fixture_press_observations(1, hz, window, [0.0])
                self.assertEqual(ctx["windows_overlap"], matched["matching_windows_can_overlap"])
                self.assertEqual(ctx["reference_interval_ms"], matched["reference_interval_ms"])

    def test_invalid_or_incomplete_input_is_neutral(self):
        for hz, window in (("", "5"), ("abc", "5"), ("0", "5"), ("10", ""), ("10", "-1"), ("10", "nan")):
            with self.subTest(hz=hz, window=window):
                ctx = schedule_association_context(hz, window)
                self.assertIsNone(ctx["percent_of_interval"])
                self.assertIsNone(ctx["windows_overlap"])
                self.assertEqual(format_percent_of_interval(ctx["percent_of_interval"]), "—")
        self.assertEqual(format_association_window_ms(None), "—")
        self.assertEqual(format_association_window_ms(True), "—")

    def test_zero_window_is_real_and_never_overlaps(self):
        ctx = schedule_association_context("10", "0")
        self.assertEqual(ctx["window_ms"], 0.0)
        self.assertEqual(format_percent_of_interval(ctx["percent_of_interval"]), "0.0 %")
        self.assertIs(ctx["windows_overlap"], False)


class CanonicalTerminologyTests(unittest.TestCase):
    def test_canonical_labels(self):
        en, zh = STRINGS["en"], STRINGS["zh"]
        self.assertEqual(en["fixture_timing_tolerance_ms"], "Schedule Association Window (± ms)")
        self.assertEqual(en["preview_timing_tolerance"], "Schedule Association Window")
        self.assertEqual(en["tolerance"], "Schedule Association Window")
        self.assertEqual(en["assoc_window"], "Schedule Association Window")
        self.assertIn("Schedule Association Window ±{tol} ms", en["he_config"])
        self.assertEqual(zh["fixture_timing_tolerance_ms"], "排程關聯範圍 (± ms)")
        self.assertEqual(zh["preview_timing_tolerance"], "排程關聯範圍")
        self.assertEqual(zh["tolerance"], "排程關聯範圍")
        self.assertIn("排程關聯範圍 ±{tol} ms", zh["he_config"])

    def test_retired_wording_absent(self):
        for lang in SUPPORTED_LANGS:
            text = "\n".join(STRINGS[lang].values())
            for stale in ("Fixture Timing Tolerance", "Timing Tolerance", "Configured association tolerance",
                          "容許誤差"):
                self.assertNotIn(stale, text, (lang, stale))
            self.assertNotIn("legend_association_window", STRINGS[lang])

    def test_derived_wording_is_not_a_verdict(self):
        for key in ("assoc_reference_interval", "assoc_window", "assoc_relative", "assoc_overlap",
                    "assoc_overlap_note", "assoc_derived_note", "he_overlap"):
            for word in _VERDICT_WORDS:
                if word == "acceptance" and key == "assoc_derived_note":
                    continue
                self.assertNotIn(word, STRINGS["en"][key], (key, word))
        self.assertIn("Not an acceptance threshold", STRINGS["en"]["assoc_derived_note"])
        self.assertIn("Ambiguous", STRINGS["en"]["assoc_overlap_note"])


def _make_qapp():
    return QApplication.instance() or QApplication([])


class SetupAssociationContextWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qapp = _make_qapp()
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

    def _fixture(self, hz: str, window: str):
        self.win.radio_fixture.setChecked(True)
        self.win.hz_combo.setCurrentText(hz)
        self.win.timing_tol_edit.setText(window)

    def _values(self) -> dict[str, str]:
        return {key: value.text() for key, (_name, value) in self.win._assoc_context_rows.items()}

    def test_setup_label_is_canonical(self):
        self.assertEqual(self.win.timing_tol_label.text(), "Schedule Association Window (± ms)")
        names = {key: name.text() for key, (name, _value) in self.win._assoc_context_rows.items()}
        self.assertEqual(names, {
            "assoc_reference_interval": "Reference Interval",
            "assoc_window": "Schedule Association Window",
            "assoc_relative": "Relative to reference interval",
            "assoc_overlap": "Adjacent windows overlap",
        })

    def test_setup_shows_derived_context(self):
        self._fixture("10", "5")
        self.assertEqual(self._values(), {
            "assoc_reference_interval": "100.00 ms",
            "assoc_window": "±5.00 ms",
            "assoc_relative": "5.0 %",
            "assoc_overlap": "No",
        })
        self.assertTrue(self.win.assoc_overlap_note.isHidden())
        self._fixture("40", "5")
        self.assertEqual(self._values()["assoc_relative"], "20.0 %")
        self.assertEqual(self._values()["assoc_overlap"], "No")

    def test_overlap_is_informational_and_does_not_block_lock(self):
        self._fixture("100", "5")
        self.assertEqual(self._values()["assoc_reference_interval"], "10.00 ms")
        self.assertEqual(self._values()["assoc_overlap"], "Yes")
        self.assertFalse(self.win.assoc_overlap_note.isHidden())
        self.assertEqual(self.win.assoc_overlap_note.text(), STRINGS["en"]["assoc_overlap_note"])
        self.assertTrue(self.win.lock_profile())
        self.assertEqual(self.win.profile_locked_settings[FIXTURE_TIMING_TOLERANCE_KEY], 5.0)
        self.assertEqual(self.win.alert_label.text(), "")

    def test_invalid_input_shows_neutral_placeholders(self):
        self._fixture("abc", "")
        self.assertEqual(self._values(), {
            "assoc_reference_interval": "—",
            "assoc_window": "—",
            "assoc_relative": "—",
            "assoc_overlap": "—",
        })
        self.assertTrue(self.win.assoc_overlap_note.isHidden())

    def test_derived_values_are_read_only(self):
        self._fixture("10", "5")
        widgets = [w for pair in self.win._assoc_context_rows.values() for w in pair]
        widgets += [self.win.assoc_overlap_note, self.win.assoc_derived_note]
        for widget in widgets:
            self.assertNotIsInstance(widget, QLineEdit)
            self.assertEqual(widget.focusPolicy(), Qt.FocusPolicy.NoFocus)
        for _name, value in self.win._assoc_context_rows.values():
            self.assertEqual(value.textInteractionFlags(), Qt.TextInteractionFlag.NoTextInteraction)
        self.assertEqual(self.win.assoc_context_box.findChildren(QLineEdit), [])
        self.assertNotIn("assoc", " ".join(self.win.settings()))

    def test_manual_hides_association_context(self):
        self.win.radio_manual.setChecked(True)
        self.assertTrue(self.win.assoc_context_box.isHidden())
        self.win.radio_fixture.setChecked(True)
        self.assertFalse(self.win.assoc_context_box.isHidden())

    def test_matcher_receives_same_absolute_ms(self):
        captured: list[tuple] = []
        original = qt_app.build_fixture_host_evidence

        def spy(*args):
            captured.append(args)
            return original(*args)

        qt_app.build_fixture_host_evidence = spy
        try:
            self._fixture("10", "5")
            self.win.auto_stop_on.setChecked(True)
            self.win.auto_stop_sec_combo.setCurrentText("1")
            self.assertTrue(self.win.lock_profile())
            self.assertTrue(self.win.arm_capture())
            self.win._cursor_over_capture_exclusion_ui = lambda: False
            t0 = float(self.win._arm_boundary_perf) + 0.001
            self.win._begin_session_from_first_click("Left", t0, t0 + 0.01, {})
            self.win.events = [{"press_elapsed_ms": 0.0}, {"press_elapsed_ms": 100.0}]
            self.win.completed = True
            self.win._build_host_evidence_snapshot_for_completed_run()
        finally:
            qt_app.build_fixture_host_evidence = original
        self.assertEqual(len(captured), 1)
        _duration, hz, window, observed = captured[0]
        self.assertEqual(hz, 10.0)
        self.assertEqual(window, 5.0)
        self.assertEqual(window, self.win.locked[FIXTURE_TIMING_TOLERANCE_KEY])
        self.assertEqual(observed, [0.0, 100.0])
        self.assertEqual(self.win.host_evidence_snapshot["configuration"]["timing_tolerance_ms"], 5.0)


if __name__ == "__main__":
    unittest.main()
