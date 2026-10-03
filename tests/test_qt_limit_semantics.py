"""Characterization and containment tests for Qt Custom Limit semantics."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.app import _result_from_tags, normalize_auto_settings
from mouse_click_stability_analyzer.cadence import (
    CADENCE_LO_RATIO,
    chatter_ms,
    classify_click,
    extra_click_ceiling_ms,
    is_extreme_cadence,
)
from mouse_click_stability_analyzer.core import compute_metrics, make_synthetic_events
from mouse_click_stability_analyzer.qt_shell.app import (
    QT_CUSTOM_LIMIT_KEYS,
    contain_qt_runtime_click_expectation,
    parse_qt_custom_limits,
    qt_explicit_limit_snapshot,
    qt_present_issue_tags,
    qt_visible_verdict,
    stamp_qt_custom_limit_metadata,
    stamp_qt_explicit_limits,
    stamp_qt_reference_rate,
)

_ARBITRARY_LIMITS = {
    "chatter_threshold_ms": "7.25",
    "duplicate_click_threshold_ms": "22.5",
    "fixture_actuation_too_short_ms": "4.25",
    "low_hold_warning_ms": "9.5",
    "interval_cv_limit_pct": "11.5",
}


def _qt_runtime_settings(
    *,
    button: str = "Left",
    hz: float = 10.0,
    manual: bool = False,
    raw_limits: dict | None = None,
) -> dict:
    limits = parse_qt_custom_limits(raw_limits or _ARBITRARY_LIMITS)
    rate = 0.0 if manual else hz
    base = {
        "manual_mode": manual,
        "profile_name": "Manual_Left_Stable" if manual else "Fixture_Custom",
        "focus_button": button,
        "button": button,
        "fixture_hz": rate,
        "fixture_reference_hz": rate,
        "judgement_mode": "Custom",
        **limits,
    }
    if not manual:
        base["test_profile"] = "Fixture Custom"
    normalized = normalize_auto_settings({"settings": base})
    contained = contain_qt_runtime_click_expectation(normalized, None)
    stamped = stamp_qt_reference_rate(contained, manual=manual, reference_rate_hz=rate)
    stamped = stamp_qt_custom_limit_metadata(stamped, manual=manual)
    return stamp_qt_explicit_limits(stamped, limits)


class ExplicitLimitPreservationTests(unittest.TestCase):
    def test_arbitrary_limits_survive_normalization_for_left(self):
        s = _qt_runtime_settings(button="Left")
        snap = qt_explicit_limit_snapshot(s)
        self.assertEqual(snap["chatter_threshold_ms"], 7.25)
        self.assertEqual(snap["duplicate_click_threshold_ms"], 22.5)
        self.assertEqual(snap["fixture_actuation_too_short_ms"], 4.25)
        self.assertEqual(snap["low_hold_warning_ms"], 9.5)
        self.assertEqual(snap["interval_cv_limit_pct"], 11.5)
        self.assertEqual(s["fixture_hz"], 10.0)

    def test_middle_button_preset_does_not_replace_explicit_limits(self):
        s = _qt_runtime_settings(button="Middle")
        snap = qt_explicit_limit_snapshot(s)
        self.assertEqual(snap["chatter_threshold_ms"], 7.25)
        self.assertEqual(snap["duplicate_click_threshold_ms"], 22.5)
        self.assertEqual(snap["fixture_actuation_too_short_ms"], 4.25)
        self.assertEqual(snap["low_hold_warning_ms"], 9.5)
        self.assertEqual(snap["interval_cv_limit_pct"], 11.5)
        self.assertNotEqual(snap["fixture_actuation_too_short_ms"], 8.0)
        self.assertNotEqual(snap["interval_cv_limit_pct"], 15.0)

    def test_x1_button_preset_does_not_replace_explicit_limits(self):
        s = _qt_runtime_settings(button="X1")
        snap = qt_explicit_limit_snapshot(s)
        self.assertEqual(snap["chatter_threshold_ms"], 7.25)
        self.assertEqual(snap["duplicate_click_threshold_ms"], 22.5)
        self.assertEqual(snap["fixture_actuation_too_short_ms"], 4.25)
        self.assertEqual(snap["low_hold_warning_ms"], 9.5)
        self.assertEqual(snap["interval_cv_limit_pct"], 11.5)

    def test_snapshot_is_a_copy_without_defaults_or_cadence_transform(self):
        src = {"chatter_threshold_ms": 7.25, "duplicate_click_threshold_ms": 22.5}
        snap = qt_explicit_limit_snapshot(src)
        self.assertEqual(snap["chatter_threshold_ms"], 7.25)
        self.assertNotIn("interval_cv_limit_pct", snap)
        snap["chatter_threshold_ms"] = 1.0
        self.assertEqual(src["chatter_threshold_ms"], 7.25)
        self.assertEqual(set(QT_CUSTOM_LIMIT_KEYS) & set(snap), {"chatter_threshold_ms", "duplicate_click_threshold_ms"})


class HiddenHoldCvPresentationTests(unittest.TestCase):
    def test_operator_fatigue_still_contained(self):
        raw = ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "OPERATOR_FATIGUE"]
        settings = {"manual_mode": True, "profile_name": "Manual_Left_Stable"}
        metrics = {"click_count": 20}
        self.assertEqual(_result_from_tags(list(raw), metrics, settings), "WARN")
        self.assertEqual(qt_present_issue_tags(raw), ["MANUAL_PROFILE_NO_EXPECTED_COUNT"])
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "PASS")
        self.assertEqual(raw, ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "OPERATOR_FATIGUE"])

    def test_hold_variation_tag_is_hidden_from_qt_presentation(self):
        raw = ["HOLD_VARIATION_WARN", "INTERVAL_JITTER_WARN"]
        self.assertEqual(qt_present_issue_tags(raw), ["INTERVAL_JITTER_WARN"])
        self.assertEqual(raw, ["HOLD_VARIATION_WARN", "INTERVAL_JITTER_WARN"])

    def test_hidden_hold_cv_warn_tag_does_not_alone_drive_manual_qt_warn(self):
        raw = ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "HOLD_VARIATION_WARN"]
        settings = {"manual_mode": True, "profile_name": "Manual_Left_Stable"}
        metrics = {"click_count": 20}
        self.assertEqual(_result_from_tags(list(raw), metrics, settings), "WARN")
        self.assertEqual(qt_present_issue_tags(raw), ["MANUAL_PROFILE_NO_EXPECTED_COUNT"])
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "PASS")
        self.assertEqual(raw, ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "HOLD_VARIATION_WARN"])

    def test_exclusive_documented_hold_cv_health_does_not_drive_qt_verdict(self):
        raw = ["HOLD_VARIATION_WARN"]
        settings = {"manual_mode": False, "profile_name": "Fixture_Custom", "fixture_hz": 10.0}
        metrics = {
            "click_count": 20,
            "health": "FAIL",
            "fail_reasons": ["hold_cv_pct 40.0000% > limit 25.0000%"],
            "warn_reasons": [],
        }
        snapshot = dict(metrics)
        self.assertEqual(_result_from_tags(list(raw), metrics, settings), "WARN")
        self.assertEqual(qt_present_issue_tags(raw), [])
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "PASS")
        self.assertEqual(raw, ["HOLD_VARIATION_WARN"])
        self.assertEqual(metrics, snapshot)

    def test_compute_metrics_exclusive_hold_cv_health_is_neutralized(self):
        settings = _qt_runtime_settings(button="Left", hz=10.0)
        events = make_synthetic_events(19, 100.0, 12.0)
        for i, event in enumerate(events):
            event["hold_ms"] = 8.0 if i % 2 == 0 else 30.0
        metrics = compute_metrics(events, settings)
        hold_reasons = [r for r in (metrics.get("fail_reasons") or []) if str(r).startswith("hold_cv_pct ")]
        other_fail = [r for r in (metrics.get("fail_reasons") or []) if not str(r).startswith("hold_cv_pct ")]
        other_warn = [r for r in (metrics.get("warn_reasons") or []) if not str(r).startswith("hold_cv_pct ")]
        self.assertTrue(hold_reasons)
        self.assertEqual(other_fail, [])
        self.assertEqual(other_warn, [])
        self.assertEqual(metrics["health"], "FAIL")
        raw = ["HOLD_VARIATION_WARN"]
        snapshot_health = metrics["health"]
        snapshot_fail = list(metrics["fail_reasons"])
        verdict = qt_visible_verdict(raw, metrics, settings)
        self.assertNotEqual(verdict, "FAIL")
        if verdict == "WARN":
            from mouse_click_stability_analyzer.completed_result import qt_visible_issue_tags
            self.assertTrue(qt_visible_issue_tags(raw, metrics, settings))
        self.assertEqual(metrics["health"], snapshot_health)
        self.assertEqual(metrics["fail_reasons"], snapshot_fail)
        self.assertEqual(raw, ["HOLD_VARIATION_WARN"])

    def test_unrelated_health_fail_surfaces_existing_chatter_code(self):
        raw = ["HOLD_VARIATION_WARN"]
        settings = {"manual_mode": False, "profile_name": "Fixture_Custom", "fixture_hz": 10.0}
        metrics = {
            "click_count": 20,
            "health": "FAIL",
            "fail_reasons": ["chatter_count 2 > max_chatter_count 0"],
            "warn_reasons": [],
        }
        snapshot = dict(metrics)
        self.assertEqual(qt_present_issue_tags(raw), [])
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "FAIL")
        from mouse_click_stability_analyzer.completed_result import qt_visible_issue_tags
        self.assertIn("CHATTER_HARD", qt_visible_issue_tags(raw, metrics, settings))
        self.assertEqual(raw, ["HOLD_VARIATION_WARN"])
        self.assertEqual(metrics, snapshot)

    def test_unrelated_health_warn_without_visible_code_is_not_silent_warn(self):
        raw: list[str] = []
        settings = {"manual_mode": False, "profile_name": "Fixture_Custom", "fixture_hz": 40.0}
        metrics = {
            "click_count": 20,
            "health": "WARN",
            "fail_reasons": [],
            "warn_reasons": ["hold_outlier_ratio_pct 5.0000% > limit"],
        }
        snapshot = dict(metrics)
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "PASS")
        self.assertEqual(raw, [])
        self.assertEqual(metrics, snapshot)

    def test_health_fail_without_structured_reasons_is_not_silent_fail(self):
        raw = ["HOLD_VARIATION_WARN"]
        settings = {"manual_mode": False, "profile_name": "Fixture_Custom", "fixture_hz": 10.0}
        metrics = {"click_count": 20, "health": "FAIL"}
        snapshot = dict(metrics)
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "PASS")
        self.assertEqual(raw, ["HOLD_VARIATION_WARN"])
        self.assertEqual(metrics, snapshot)

    def test_mixed_hold_cv_and_other_fail_reason_preserves_health(self):
        raw = ["HOLD_VARIATION_WARN"]
        settings = {"manual_mode": False, "profile_name": "Fixture_Custom", "fixture_hz": 10.0}
        metrics = {
            "click_count": 20,
            "health": "FAIL",
            "fail_reasons": [
                "hold_cv_pct 40.0000% > limit 25.0000%",
                "chatter_count 2 > max_chatter_count 0",
            ],
            "warn_reasons": [],
        }
        snapshot = dict(metrics)
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "FAIL")
        self.assertEqual(metrics, snapshot)

    def test_hidden_hold_cv_limit_survives_as_legacy_setting(self):
        left = _qt_runtime_settings(button="Left")
        middle = _qt_runtime_settings(button="Middle")
        self.assertEqual(left["hold_cv_limit_pct"], 25.0)
        self.assertEqual(middle["hold_cv_limit_pct"], 35.0)

    def test_visible_interval_cv_still_drives_qt_visible_warn(self):
        raw = ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "INTERVAL_JITTER_WARN"]
        settings = {"manual_mode": True, "profile_name": "Manual_Left_Stable"}
        metrics = {"click_count": 20, "health": "PASS"}
        snapshot = dict(metrics)
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "WARN")
        self.assertEqual(raw, ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "INTERVAL_JITTER_WARN"])
        self.assertEqual(metrics, snapshot)


class ExpectedCountContainmentTests(unittest.TestCase):
    def test_qt_runtime_keeps_expected_counts_at_zero(self):
        for button in ("Left", "Middle", "X1"):
            s = _qt_runtime_settings(button=button, hz=40.0)
            self.assertEqual(s["target_clicks"], 0)
            self.assertEqual(s["expected_clicks"], 0)
            self.assertEqual(s["expected_clicks_auto"], 0)


class ReferenceRateRegressionTests(unittest.TestCase):
    def test_reference_rate_7_5_and_40_remain_exact(self):
        s75 = _qt_runtime_settings(hz=7.5)
        s40 = _qt_runtime_settings(hz=40.0)
        self.assertEqual(s75["fixture_hz"], 7.5)
        self.assertEqual(s75["fixture_reference_hz"], 7.5)
        self.assertEqual(s40["fixture_hz"], 40.0)
        self.assertEqual(s40["fixture_reference_hz"], 40.0)


class HighRateCadenceCharacterizationTests(unittest.TestCase):
    """Document current cadence.py behavior. Do not treat this as the V2 contract."""

    def _settings(self, hz: float, duplicate: float = 30.0) -> dict:
        return _qt_runtime_settings(
            hz=hz,
            raw_limits={
                "chatter_threshold_ms": "8",
                "duplicate_click_threshold_ms": str(duplicate),
                "fixture_actuation_too_short_ms": "5",
                "low_hold_warning_ms": "8",
                "interval_cv_limit_pct": "10",
            },
        )

    def test_10hz_uses_configured_duplicate_threshold_as_extra_ceiling(self):
        s = self._settings(10.0, 30.0)
        self.assertFalse(is_extreme_cadence(s))
        self.assertEqual(extra_click_ceiling_ms(s), 30.0)
        self.assertEqual(classify_click(100.0, 10.0, s), "ON_CADENCE")
        self.assertEqual(classify_click(25.0, 10.0, s), "TRUE_EXTRA_CLICK")

    def test_40hz_current_effective_ceiling_is_cadence_derived(self):
        s = self._settings(40.0, 30.0)
        cad = 1000.0 / 40.0
        self.assertTrue(is_extreme_cadence(s))
        self.assertEqual(extra_click_ceiling_ms(s), min(30.0, cad * CADENCE_LO_RATIO))
        self.assertAlmostEqual(extra_click_ceiling_ms(s), 18.0)
        self.assertEqual(s["duplicate_click_threshold_ms"], 30.0)
        # Current behavior: a valid 25 ms / 40 Hz beat is ON_CADENCE even though
        # 25 < the visible 30 ms Double-click Threshold. Do not treat this as
        # the V2 Custom Limit contract.
        self.assertEqual(classify_click(25.0, 10.0, s), "ON_CADENCE")
        self.assertEqual(classify_click(29.9, 10.0, s), "ON_CADENCE")
        self.assertEqual(classify_click(15.0, 10.0, s), "TRUE_EXTRA_CLICK")

    def test_125hz_current_effective_ceiling_is_cadence_derived(self):
        s = self._settings(125.0, 30.0)
        cad = 1000.0 / 125.0
        self.assertTrue(is_extreme_cadence(s))
        self.assertEqual(extra_click_ceiling_ms(s), min(30.0, cad * CADENCE_LO_RATIO))
        self.assertAlmostEqual(extra_click_ceiling_ms(s), cad * CADENCE_LO_RATIO)
        self.assertEqual(s["duplicate_click_threshold_ms"], 30.0)
        self.assertLess(extra_click_ceiling_ms(s), chatter_ms(s))
        self.assertEqual(classify_click(8.0, 10.0, s), "ON_CADENCE")
        self.assertEqual(classify_click(5.0, 10.0, s), "CHATTER_BOUNCE")


if __name__ == "__main__":
    unittest.main()
