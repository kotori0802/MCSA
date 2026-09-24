"""Focused tests for Qt Custom Limits parsing and mapping (no GUI required)."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.app import RULE_PRESETS, normalize_auto_settings
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS
from mouse_click_stability_analyzer.qt_shell.app import (
    QT_CUSTOM_LIMIT_KEYS,
    QtCustomLimitsError,
    contain_qt_runtime_click_expectation,
    parse_qt_custom_limits,
    qt_custom_limit_defaults,
    qt_visible_verdict,
    stamp_qt_custom_limit_metadata,
    stamp_qt_reference_rate,
)

_CUSTOM_LIMIT_I18N_KEYS = (
    "custom_limits",
    "limit_chatter_ms",
    "limit_double_click_ms",
    "limit_actuation_short_ms",
    "limit_low_hold_ms",
    "limit_interval_cv_pct",
    "custom_limits_invalid",
    "custom_limits_order_invalid",
)


def _valid_raw(**overrides: object) -> dict:
    raw = {key: qt_custom_limit_defaults()[key] for key in QT_CUSTOM_LIMIT_KEYS}
    raw.update(overrides)
    return raw


def _qt_runtime_from_limits(raw: dict, *, manual: bool = False) -> dict:
    limits = parse_qt_custom_limits(raw)
    hz = 0.0 if manual else 10.0
    base = {
        "manual_mode": manual,
        "profile_name": "Manual_Left_Stable" if manual else "Fixture_Custom",
        "focus_button": "Left",
        "button": "Left",
        "fixture_hz": hz,
        "fixture_reference_hz": hz,
        "judgement_mode": "Custom",
        **limits,
    }
    if not manual:
        base["test_profile"] = "Fixture Custom"
    normalized = normalize_auto_settings({"settings": base})
    contained = contain_qt_runtime_click_expectation(normalized, None)
    stamped = stamp_qt_reference_rate(contained, manual=manual, reference_rate_hz=hz)
    return stamp_qt_custom_limit_metadata(stamped, manual=manual)


class QtCustomLimitDefaultsTests(unittest.TestCase):
    def test_defaults_match_strict_and_are_a_copy(self):
        defaults = qt_custom_limit_defaults()
        strict = RULE_PRESETS["Strict"]
        self.assertEqual(set(defaults), set(QT_CUSTOM_LIMIT_KEYS))
        for key in QT_CUSTOM_LIMIT_KEYS:
            self.assertEqual(defaults[key], float(strict[key]))
        defaults["chatter_threshold_ms"] = 99.0
        self.assertEqual(RULE_PRESETS["Strict"]["chatter_threshold_ms"], 8.0)
        self.assertNotIn("Loose", defaults)
        self.assertNotIn("Medium", defaults)
        self.assertNotIn("Strict", defaults)


class ParseQtCustomLimitsTests(unittest.TestCase):
    def test_arbitrary_decimals_are_preserved(self):
        parsed = parse_qt_custom_limits({
            "chatter_threshold_ms": "7.25",
            "duplicate_click_threshold_ms": "18.5",
            "fixture_actuation_too_short_ms": "4.5",
            "low_hold_warning_ms": "9.75",
            "interval_cv_limit_pct": "12.25",
        })
        self.assertEqual(parsed["chatter_threshold_ms"], 7.25)
        self.assertEqual(parsed["duplicate_click_threshold_ms"], 18.5)
        self.assertEqual(parsed["fixture_actuation_too_short_ms"], 4.5)
        self.assertEqual(parsed["low_hold_warning_ms"], 9.75)
        self.assertEqual(parsed["interval_cv_limit_pct"], 12.25)

    def test_invalid_values_are_rejected_without_defaulting(self):
        for bad in ("", "abc", "0", 0, -1, None, math.nan, math.inf, -math.inf, True, False):
            with self.subTest(bad=bad):
                raw = _valid_raw(chatter_threshold_ms=bad)
                with self.assertRaises(QtCustomLimitsError) as ctx:
                    parse_qt_custom_limits(raw)
                self.assertEqual(ctx.exception.code, "numeric")

    def test_does_not_mutate_caller_dict(self):
        raw = _valid_raw(chatter_threshold_ms="7.5")
        snapshot = dict(raw)
        parse_qt_custom_limits(raw)
        self.assertEqual(raw, snapshot)

    def test_chatter_must_be_below_duplicate(self):
        with self.assertRaises(QtCustomLimitsError) as ctx:
            parse_qt_custom_limits(_valid_raw(
                chatter_threshold_ms=30,
                duplicate_click_threshold_ms=30,
            ))
        self.assertEqual(ctx.exception.code, "order")
        with self.assertRaises(QtCustomLimitsError):
            parse_qt_custom_limits(_valid_raw(
                chatter_threshold_ms=31,
                duplicate_click_threshold_ms=30,
            ))
        parsed = parse_qt_custom_limits(_valid_raw(
            chatter_threshold_ms=8,
            duplicate_click_threshold_ms=30,
        ))
        self.assertEqual(parsed["chatter_threshold_ms"], 8.0)

    def test_actuation_too_short_must_be_below_low_hold(self):
        with self.assertRaises(QtCustomLimitsError) as ctx:
            parse_qt_custom_limits(_valid_raw(
                fixture_actuation_too_short_ms=8,
                low_hold_warning_ms=8,
            ))
        self.assertEqual(ctx.exception.code, "order")
        parsed = parse_qt_custom_limits(_valid_raw(
            fixture_actuation_too_short_ms=5,
            low_hold_warning_ms=8,
        ))
        self.assertEqual(parsed["fixture_actuation_too_short_ms"], 5.0)

    def test_no_preset_selection_is_required(self):
        parsed = parse_qt_custom_limits(_valid_raw())
        self.assertEqual(set(parsed), set(QT_CUSTOM_LIMIT_KEYS))


class QtCustomLimitsMappingTests(unittest.TestCase):
    def test_legacy_threshold_keys_flow_into_runtime_settings(self):
        raw = {
            "chatter_threshold_ms": "7.5",
            "duplicate_click_threshold_ms": "22.5",
            "fixture_actuation_too_short_ms": "4.25",
            "low_hold_warning_ms": "9.5",
            "interval_cv_limit_pct": "11.5",
        }
        s = _qt_runtime_from_limits(raw)
        self.assertEqual(s["chatter_threshold_ms"], 7.5)
        self.assertEqual(s["duplicate_click_threshold_ms"], 22.5)
        self.assertEqual(s["fixture_actuation_too_short_ms"], 4.25)
        self.assertEqual(s["low_hold_warning_ms"], 9.5)
        self.assertEqual(s["interval_cv_limit_pct"], 11.5)
        self.assertEqual(s["judgement_mode"], "Custom")
        self.assertEqual(s["test_profile"], "Fixture Custom")
        self.assertEqual(s["profile_name"], "Fixture_Custom")
        self.assertEqual(s["target_clicks"], 0)
        self.assertEqual(s["expected_clicks"], 0)
        self.assertEqual(s["expected_clicks_auto"], 0)
        self.assertNotIn("Strict", str(s.get("judgement_mode")))
        self.assertNotIn("Loose", str(s.get("test_profile")))

    def test_manual_keeps_compatibility_profile_name(self):
        s = _qt_runtime_from_limits(_valid_raw(), manual=True)
        self.assertEqual(s["profile_name"], "Manual_Left_Stable")
        self.assertEqual(s["judgement_mode"], "Custom")
        self.assertEqual(s["fixture_hz"], 0.0)


class CustomLimitsI18nTests(unittest.TestCase):
    def test_supported_languages_have_custom_limit_keys(self):
        for lang in SUPPORTED_LANGS:
            table = STRINGS[lang]
            for key in _CUSTOM_LIMIT_I18N_KEYS:
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(str(table.get(key) or "").strip())
            self.assertNotIn("Strict", table["custom_limits"])
            self.assertNotIn("Loose", table["custom_limits"])
            self.assertNotIn("Medium", table["custom_limits"])


class CustomLimitsRegressionTests(unittest.TestCase):
    def test_fatigue_still_does_not_drive_qt_visible_verdict(self):
        raw = ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "OPERATOR_FATIGUE"]
        settings = {"manual_mode": True, "profile_name": "Manual_Left_Stable"}
        metrics = {"click_count": 20}
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "PASS")
        self.assertEqual(raw, ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "OPERATOR_FATIGUE"])


if __name__ == "__main__":
    unittest.main()
