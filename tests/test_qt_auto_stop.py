"""Focused tests for Qt Auto Stop run-control parsing (no GUI required)."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.app import normalize_auto_settings
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell.app import (
    contain_qt_runtime_click_expectation,
    parse_auto_stop_seconds,
    qt_button_label,
    setup_controls_editable,
)

_AUTO_STOP_KEYS = (
    "auto_stop",
    "auto_stop_after",
    "auto_stop_invalid",
    "recording_fixture_autostop",
)


def _qt_runtime_settings(fixture_hz: float, auto_stop_sec: float | None) -> dict:
    """Same Qt boundary as MainWindow.settings(): normalize, then contain."""
    base = {
        "manual_mode": False,
        "fixture_hz": fixture_hz,
        "focus_button": "Left",
        "button": "Left",
    }
    if auto_stop_sec is not None:
        base["duration_sec"] = auto_stop_sec
    normalized = normalize_auto_settings({"settings": base})
    return contain_qt_runtime_click_expectation(normalized, auto_stop_sec)


class ParseAutoStopSecondsTests(unittest.TestCase):
    def test_disabled_ignores_field(self):
        self.assertIsNone(parse_auto_stop_seconds(False, "60"))
        self.assertIsNone(parse_auto_stop_seconds(False, "abc"))
        self.assertIsNone(parse_auto_stop_seconds(False, ""))
        self.assertIsNone(parse_auto_stop_seconds(False, None))

    def test_enabled_positive_seconds(self):
        self.assertEqual(parse_auto_stop_seconds(True, "60"), 60.0)
        self.assertEqual(parse_auto_stop_seconds(True, "30"), 30.0)
        self.assertEqual(parse_auto_stop_seconds(True, 12.5), 12.5)

    def test_enabled_rejects_invalid_without_defaulting_to_60(self):
        for raw in ("", "abc", "0", "-5", "0.0", None, math.nan, math.inf, -math.inf):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_auto_stop_seconds(True, raw)


class QtRuntimeClickExpectationTests(unittest.TestCase):
    def test_auto_stop_off_has_no_duration_derived_expectation(self):
        s = _qt_runtime_settings(10.0, None)
        self.assertEqual(s["target_clicks"], 0)
        self.assertEqual(s["expected_clicks"], 0)
        self.assertEqual(s["expected_clicks_auto"], 0)
        self.assertNotEqual(s.get("duration_sec"), 60)
        self.assertEqual(s.get("duration_sec"), 0)

    def test_auto_stop_on_60s_does_not_create_click_expectation(self):
        s = _qt_runtime_settings(10.0, 60.0)
        self.assertEqual(s["duration_sec"], 60.0)
        self.assertEqual(s["target_clicks"], 0)
        self.assertEqual(s["expected_clicks"], 0)
        self.assertEqual(s["expected_clicks_auto"], 0)

    def test_fixture_hz_does_not_create_seconds_times_hz_expectation(self):
        off_10 = _qt_runtime_settings(10.0, None)
        off_40 = _qt_runtime_settings(40.0, None)
        on_10 = _qt_runtime_settings(10.0, 60.0)
        on_40 = _qt_runtime_settings(40.0, 60.0)
        for s in (off_10, off_40, on_10, on_40):
            self.assertEqual(s["expected_clicks"], 0)
            self.assertEqual(s["expected_clicks_auto"], 0)
            self.assertEqual(s["target_clicks"], 0)
        self.assertNotEqual(on_40["expected_clicks"], 60 * 40)
        self.assertNotEqual(on_10["expected_clicks"], 60 * 10)


class AutoStopI18nTests(unittest.TestCase):
    def test_supported_languages_have_auto_stop_keys(self):
        for lang in SUPPORTED_LANGS:
            table = STRINGS[lang]
            for key in _AUTO_STOP_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(table.get(key) or "").strip())


class QtUiPolishHelpersTests(unittest.TestCase):
    def test_finish_button_ampersand_is_escaped_for_qt(self):
        self.assertEqual(qt_button_label("Finish & Generate Report"), "Finish && Generate Report")
        self.assertEqual(qt_button_label("完成並產生報告"), "完成並產生報告")

    def test_setup_editable_only_when_not_running_and_not_completed(self):
        self.assertTrue(setup_controls_editable(running=False, completed=False))
        self.assertFalse(setup_controls_editable(running=True, completed=False))
        self.assertFalse(setup_controls_editable(running=False, completed=True))
        self.assertFalse(setup_controls_editable(running=True, completed=True))


if __name__ == "__main__":
    unittest.main()
