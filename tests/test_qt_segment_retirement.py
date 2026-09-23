"""Focused tests for Qt Segment retirement from the primary live path."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.app import _result_from_tags, normalize_auto_settings
from mouse_click_stability_analyzer.i18n import STRINGS, SUPPORTED_LANGS, t
from mouse_click_stability_analyzer.qt_shell.app import (
    contain_qt_runtime_click_expectation,
    qt_present_issue_tags,
    qt_visible_verdict,
    stamp_qt_reference_rate,
)


def _qt_manual_runtime_settings() -> dict:
    """Same Qt Manual settings path: no tester-configured Segment field."""
    base = {
        "manual_mode": True,
        "profile_name": "Manual_Left_Stable",
        "focus_button": "Left",
        "button": "Left",
        "fixture_hz": 0.0,
        "fixture_reference_hz": 0.0,
    }
    normalized = normalize_auto_settings({"settings": base})
    contained = contain_qt_runtime_click_expectation(normalized, None)
    return stamp_qt_reference_rate(contained, manual=True, reference_rate_hz=0.0)


class QtManualSettingsNoSegmentTests(unittest.TestCase):
    def test_manual_settings_do_not_require_segment_value(self):
        s = _qt_manual_runtime_settings()
        self.assertTrue(s.get("manual_mode"))
        self.assertEqual(s["fixture_hz"], 0.0)
        self.assertEqual(s["target_clicks"], 0)
        self.assertEqual(s["expected_clicks"], 0)
        self.assertEqual(s["expected_clicks_auto"], 0)

    def test_qt_base_does_not_supply_tester_configured_segment(self):
        base = {
            "manual_mode": True,
            "profile_name": "Manual_Left_Stable",
            "focus_button": "Left",
            "button": "Left",
            "fixture_hz": 0.0,
            "fixture_reference_hz": 0.0,
        }
        self.assertNotIn("manual_segment_sec", base)


class QtOperatorFatiguePresentationTests(unittest.TestCase):
    def test_operator_fatigue_is_hidden_from_qt_presentation(self):
        raw = ["INTERVAL_JITTER_WARN", "OPERATOR_FATIGUE", "HIGH_PROBABILITY_DOUBLE_CLICK"]
        shown = qt_present_issue_tags(raw)
        self.assertEqual(
            shown,
            ["INTERVAL_JITTER_WARN", "HIGH_PROBABILITY_DOUBLE_CLICK"],
        )
        self.assertNotIn("OPERATOR_FATIGUE", shown)
        self.assertEqual(raw, ["INTERVAL_JITTER_WARN", "OPERATOR_FATIGUE", "HIGH_PROBABILITY_DOUBLE_CLICK"])

    def test_fatigue_alone_does_not_drive_qt_visible_warn(self):
        raw = ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "OPERATOR_FATIGUE"]
        settings = {
            "manual_mode": True,
            "profile_name": "Manual_Left_Stable",
        }
        metrics = {"click_count": 20}
        # Legacy engine would WARN because of OPERATOR_FATIGUE.
        self.assertEqual(_result_from_tags(list(raw), metrics, settings), "WARN")
        visible = qt_visible_verdict(raw, metrics, settings)
        self.assertNotEqual(visible, "WARN")
        self.assertEqual(visible, "PASS")
        self.assertEqual(raw, ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "OPERATOR_FATIGUE"])
        self.assertEqual(
            qt_present_issue_tags(raw),
            ["MANUAL_PROFILE_NO_EXPECTED_COUNT"],
        )

    def test_interval_jitter_still_produces_qt_visible_warn(self):
        raw = ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "INTERVAL_JITTER_WARN"]
        settings = {"manual_mode": True, "profile_name": "Manual_Left_Stable"}
        metrics = {"click_count": 20}
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "WARN")
        self.assertEqual(raw, ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "INTERVAL_JITTER_WARN"])

    def test_chatter_hard_still_produces_qt_visible_fail(self):
        raw = ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "CHATTER_HARD"]
        settings = {"manual_mode": True, "profile_name": "Manual_Left_Stable"}
        metrics = {"click_count": 20}
        self.assertEqual(qt_visible_verdict(raw, metrics, settings), "FAIL")
        self.assertEqual(_result_from_tags(list(raw), metrics, settings), "FAIL")
        self.assertEqual(raw, ["MANUAL_PROFILE_NO_EXPECTED_COUNT", "CHATTER_HARD"])


class ManualModeI18nTests(unittest.TestCase):
    def test_mode_manual_is_neutral_and_has_no_segment_placeholder(self):
        banned = (
            "{seg}",
            "segment",
            "segments",
            "segmente",
            "segmento",
            "segmentos",
            "分段",
            "区間",
            "구간",
            "fatigue",
            "stable",
            "unstable",
            "stability",
            "stabilité",
            "stabilità",
            "stabilität",
            "estabilidad",
            "穩定",
            "安定",
            "안정",
        )
        for lang in SUPPORTED_LANGS:
            with self.subTest(lang=lang):
                text = STRINGS[lang]["mode_manual"]
                self.assertTrue(str(text).strip())
                lowered = text.lower()
                for token in banned:
                    self.assertNotIn(token, lowered)
                    self.assertNotIn(token, text)
                rendered = t(lang, "mode_manual")
                self.assertNotIn("{seg}", rendered)
                self.assertNotIn("{", rendered)


if __name__ == "__main__":
    unittest.main()
