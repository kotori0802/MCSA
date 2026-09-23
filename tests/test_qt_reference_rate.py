"""Focused tests for Qt Reference Rate parsing and compatibility mapping."""
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
    parse_reference_rate_hz,
    stamp_qt_reference_rate,
)

_REFERENCE_RATE_KEYS = (
    "reference_rate_hz",
    "reference_rate_invalid",
    "mode_fixture",
)


def _qt_runtime_from_reference_rate(
    reference_rate_hz: float,
    *,
    manual: bool = False,
    auto_stop_sec: float | None = None,
) -> dict:
    """Same Qt boundary as MainWindow.settings(): parse → normalize → contain → stamp."""
    hz = 0.0 if manual else parse_reference_rate_hz(reference_rate_hz)
    base = {
        "manual_mode": manual,
        "profile_name": "Manual_Left_Stable" if manual else "Fixture_Custom",
        "focus_button": "Left",
        "button": "Left",
        "fixture_hz": hz,
        "fixture_reference_hz": hz,
    }
    if auto_stop_sec is not None:
        base["duration_sec"] = auto_stop_sec
    normalized = normalize_auto_settings({"settings": base})
    contained = contain_qt_runtime_click_expectation(normalized, auto_stop_sec)
    return stamp_qt_reference_rate(contained, manual=manual, reference_rate_hz=hz)


class ParseReferenceRateHzTests(unittest.TestCase):
    def test_valid_arbitrary_rates_are_accepted_exactly(self):
        cases = (
            ("5", 5.0),
            (5, 5.0),
            ("7.5", 7.5),
            (7.5, 7.5),
            ("12.25", 12.25),
            ("40", 40.0),
            (40, 40.0),
            ("125", 125.0),
            (125, 125.0),
            ("  7.5  ", 7.5),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_reference_rate_hz(raw), expected)

    def test_invalid_values_are_rejected_without_preset_fallback(self):
        for raw in ("", "   ", "abc", "0", 0, -5, "-1", None, math.nan, math.inf, -math.inf, True, False):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_reference_rate_hz(raw)

    def test_no_preset_snapping(self):
        self.assertEqual(parse_reference_rate_hz("7.5"), 7.5)
        self.assertEqual(parse_reference_rate_hz("12.25"), 12.25)
        self.assertEqual(parse_reference_rate_hz("35"), 35.0)
        self.assertNotEqual(parse_reference_rate_hz("7.5"), 10.0)
        self.assertNotEqual(parse_reference_rate_hz("12.25"), 10.0)
        self.assertNotEqual(parse_reference_rate_hz("35"), 40.0)
        self.assertNotEqual(parse_reference_rate_hz("35"), 20.0)


class QtReferenceRateCompatibilityTests(unittest.TestCase):
    def test_fixture_7_5_maps_to_legacy_fields_without_expected_clicks(self):
        s = _qt_runtime_from_reference_rate(7.5)
        self.assertEqual(s["profile_name"], "Fixture_Custom")
        self.assertEqual(s["fixture_hz"], 7.5)
        self.assertEqual(s["fixture_reference_hz"], 7.5)
        self.assertEqual(s["target_clicks"], 0)
        self.assertEqual(s["expected_clicks"], 0)
        self.assertEqual(s["expected_clicks_auto"], 0)

    def test_fixture_12_25_maps_to_legacy_fields_without_expected_clicks(self):
        s = _qt_runtime_from_reference_rate(12.25)
        self.assertEqual(s["profile_name"], "Fixture_Custom")
        self.assertEqual(s["fixture_hz"], 12.25)
        self.assertEqual(s["fixture_reference_hz"], 12.25)
        self.assertEqual(s["target_clicks"], 0)
        self.assertEqual(s["expected_clicks"], 0)
        self.assertEqual(s["expected_clicks_auto"], 0)

    def test_fixture_40_maps_to_legacy_fields_without_expected_clicks(self):
        s = _qt_runtime_from_reference_rate(40)
        self.assertEqual(s["profile_name"], "Fixture_Custom")
        self.assertEqual(s["fixture_hz"], 40.0)
        self.assertEqual(s["fixture_reference_hz"], 40.0)
        self.assertEqual(s["target_clicks"], 0)
        self.assertEqual(s["expected_clicks"], 0)
        self.assertEqual(s["expected_clicks_auto"], 0)

    def test_expected_count_containment_holds_for_arbitrary_rates(self):
        for rate in (5, 7.5, 12.25, 35, 40, 125):
            for auto_sec in (None, 60.0):
                with self.subTest(rate=rate, auto_sec=auto_sec):
                    s = _qt_runtime_from_reference_rate(rate, auto_stop_sec=auto_sec)
                    self.assertEqual(s["target_clicks"], 0)
                    self.assertEqual(s["expected_clicks"], 0)
                    self.assertEqual(s["expected_clicks_auto"], 0)
                    if auto_sec is not None:
                        self.assertNotEqual(s["expected_clicks"], auto_sec * rate)

    def test_manual_mode_uses_legacy_rate_zero(self):
        s = _qt_runtime_from_reference_rate(10, manual=True)
        self.assertEqual(s["fixture_hz"], 0.0)
        self.assertEqual(s["fixture_reference_hz"], 0.0)
        self.assertTrue(str(s.get("profile_name") or "").startswith("Manual_"))

    def test_profile_name_does_not_claim_a_fixed_preset_rate(self):
        lying = ("10Hz", "40Hz", "5Hz", "20Hz", "7Hz", "12Hz")
        for rate in (7.5, 10, 12.25, 35, 40):
            with self.subTest(rate=rate):
                s = _qt_runtime_from_reference_rate(rate)
                name = str(s["profile_name"])
                self.assertEqual(name, "Fixture_Custom")
                for token in lying:
                    self.assertNotIn(token, name)


class ReferenceRateI18nTests(unittest.TestCase):
    def test_supported_languages_have_reference_rate_keys(self):
        for lang in SUPPORTED_LANGS:
            table = STRINGS[lang]
            for key in _REFERENCE_RATE_KEYS:
                with self.subTest(lang=lang, key=key):
                    text = str(table.get(key) or "").strip()
                    self.assertTrue(text)
            mode = table["mode_fixture"].lower()
            self.assertNotIn("measured", mode)
            self.assertNotIn("actual", mode)
            self.assertNotIn("實測", table["mode_fixture"])
            self.assertIn("{hz}", table["mode_fixture"])


if __name__ == "__main__":
    unittest.main()
