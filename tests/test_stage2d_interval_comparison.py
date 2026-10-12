"""Stage 2D: pure Configured Interval Range arithmetic. No Qt, no DUT verdict."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.interval_comparison import (
    BASIS_MILLISECONDS,
    BASIS_PERCENT,
    POSITION_ABOVE,
    POSITION_BELOW,
    POSITION_NOT_COMPARABLE,
    POSITION_WITHIN,
    SETTINGS_BASIS,
    SETTINGS_ENABLED,
    SETTINGS_VALUE,
    IntervalComparisonError,
    classify_interval,
    convert_authoritative_value,
    disabled_contract,
    evidence_interval_comparison,
    freeze_interval_comparison,
    parse_comparison_value,
    resolve_configured_range,
    summarize_positions,
)


class EightHzPercentTests(unittest.TestCase):
    def test_20_percent_is_100_to_150(self):
        rng = resolve_configured_range(reference_hz=8, basis=BASIS_PERCENT, value=20)
        self.assertEqual(rng["reference_interval_ms"], 125.0)
        self.assertEqual(rng["tolerance_ms"], 25.0)
        self.assertEqual(rng["tolerance_pct"], 20.0)
        self.assertEqual(rng["lower_bound_ms"], 100.0)
        self.assertEqual(rng["upper_bound_ms"], 150.0)
        self.assertEqual(rng["basis"], BASIS_PERCENT)
        self.assertEqual(rng["configured_value"], 20.0)


class FiveHzMillisecondsTests(unittest.TestCase):
    def test_20_ms_is_180_to_220_and_10_percent(self):
        rng = resolve_configured_range(reference_hz=5, basis=BASIS_MILLISECONDS, value=20)
        self.assertEqual(rng["reference_interval_ms"], 200.0)
        self.assertEqual(rng["tolerance_ms"], 20.0)
        self.assertEqual(rng["tolerance_pct"], 10.0)
        self.assertEqual(rng["lower_bound_ms"], 180.0)
        self.assertEqual(rng["upper_bound_ms"], 220.0)


class BoundaryInclusionTests(unittest.TestCase):
    def setUp(self):
        self.rng = resolve_configured_range(reference_hz=8, basis=BASIS_PERCENT, value=20)

    def test_exactly_lower_is_within(self):
        self.assertEqual(classify_interval(100.0, self.rng), POSITION_WITHIN)

    def test_exactly_upper_is_within(self):
        self.assertEqual(classify_interval(150.0, self.rng), POSITION_WITHIN)

    def test_interior_is_within(self):
        self.assertEqual(classify_interval(125.0, self.rng), POSITION_WITHIN)

    def test_below_lower(self):
        self.assertEqual(classify_interval(99.999, self.rng), POSITION_BELOW)

    def test_above_upper(self):
        self.assertEqual(classify_interval(150.001, self.rng), POSITION_ABOVE)

    def test_first_interval_none_is_not_comparable(self):
        self.assertEqual(classify_interval(None, self.rng), POSITION_NOT_COMPARABLE)

    def test_disabled_is_not_comparable(self):
        self.assertEqual(classify_interval(125.0, disabled_contract()), POSITION_NOT_COMPARABLE)
        self.assertEqual(classify_interval(125.0, None), POSITION_NOT_COMPARABLE)


class UnitSwitchTests(unittest.TestCase):
    def test_percent_to_ms_preserves_100_150(self):
        ms = convert_authoritative_value(
            reference_hz=8, from_basis=BASIS_PERCENT, value=20, to_basis=BASIS_MILLISECONDS,
        )
        self.assertEqual(ms, 25.0)
        rng = resolve_configured_range(reference_hz=8, basis=BASIS_MILLISECONDS, value=ms)
        self.assertEqual(rng["lower_bound_ms"], 100.0)
        self.assertEqual(rng["upper_bound_ms"], 150.0)

    def test_ms_back_to_percent(self):
        pct = convert_authoritative_value(
            reference_hz=8, from_basis=BASIS_MILLISECONDS, value=25, to_basis=BASIS_PERCENT,
        )
        self.assertEqual(pct, 20.0)


class ReferenceRateChangeTests(unittest.TestCase):
    def test_percent_basis_keeps_percent(self):
        eight = resolve_configured_range(reference_hz=8, basis=BASIS_PERCENT, value=20)
        ten = resolve_configured_range(reference_hz=10, basis=BASIS_PERCENT, value=20)
        self.assertEqual(eight["configured_value"], 20.0)
        self.assertEqual(ten["configured_value"], 20.0)
        self.assertEqual(ten["tolerance_ms"], 20.0)
        self.assertEqual(ten["lower_bound_ms"], 80.0)
        self.assertEqual(ten["upper_bound_ms"], 120.0)

    def test_ms_basis_keeps_ms(self):
        eight = resolve_configured_range(reference_hz=8, basis=BASIS_MILLISECONDS, value=20)
        ten = resolve_configured_range(reference_hz=10, basis=BASIS_MILLISECONDS, value=20)
        self.assertEqual(eight["configured_value"], 20.0)
        self.assertEqual(ten["configured_value"], 20.0)
        self.assertEqual(eight["tolerance_pct"], 16.0)
        self.assertEqual(ten["tolerance_pct"], 20.0)


class ValidationTests(unittest.TestCase):
    def test_nan_rejected(self):
        with self.assertRaises(IntervalComparisonError) as ctx:
            parse_comparison_value(math.nan)
        self.assertEqual(ctx.exception.key, "interval_comparison_invalid")

    def test_infinity_rejected(self):
        with self.assertRaises(IntervalComparisonError) as ctx:
            parse_comparison_value(math.inf)
        self.assertEqual(ctx.exception.key, "interval_comparison_invalid")

    def test_negative_rejected(self):
        with self.assertRaises(IntervalComparisonError) as ctx:
            parse_comparison_value(-0.1)
        self.assertEqual(ctx.exception.key, "interval_comparison_invalid")

    def test_percent_above_100_rejected(self):
        with self.assertRaises(IntervalComparisonError) as ctx:
            resolve_configured_range(reference_hz=8, basis=BASIS_PERCENT, value=100.01)
        self.assertEqual(ctx.exception.key, "interval_comparison_percent_range")

    def test_ms_above_reference_rejected(self):
        with self.assertRaises(IntervalComparisonError) as ctx:
            resolve_configured_range(reference_hz=8, basis=BASIS_MILLISECONDS, value=125.01)
        self.assertEqual(ctx.exception.key, "interval_comparison_ms_range")

    def test_exactly_100_percent_is_valid_zero_lower_bound(self):
        rng = resolve_configured_range(reference_hz=8, basis=BASIS_PERCENT, value=100)
        self.assertEqual(rng["lower_bound_ms"], 0.0)
        self.assertEqual(rng["upper_bound_ms"], 250.0)

    def test_exactly_reference_interval_ms_is_valid(self):
        rng = resolve_configured_range(reference_hz=8, basis=BASIS_MILLISECONDS, value=125)
        self.assertEqual(rng["lower_bound_ms"], 0.0)
        self.assertEqual(rng["upper_bound_ms"], 250.0)

    def test_no_silent_clamp(self):
        with self.assertRaises(IntervalComparisonError):
            resolve_configured_range(reference_hz=8, basis=BASIS_PERCENT, value=200)


class FreezeAndDefaultTests(unittest.TestCase):
    def test_migrated_settings_default_disabled(self):
        frozen = freeze_interval_comparison({"fixture_reference_hz": 8.0, "manual_mode": False}, manual=False)
        self.assertEqual(frozen, {"enabled": False})

    def test_manual_never_applies(self):
        settings = {
            "manual_mode": True,
            SETTINGS_ENABLED: True,
            SETTINGS_BASIS: BASIS_PERCENT,
            SETTINGS_VALUE: 20.0,
            "fixture_reference_hz": 8.0,
        }
        self.assertEqual(freeze_interval_comparison(settings, manual=True), {"enabled": False})

    def test_enabled_fixture_freezes_derived_values(self):
        settings = {
            "manual_mode": False,
            "fixture_reference_hz": 8.0,
            SETTINGS_ENABLED: True,
            SETTINGS_BASIS: BASIS_PERCENT,
            SETTINGS_VALUE: 20.0,
        }
        frozen = freeze_interval_comparison(settings, manual=False)
        self.assertTrue(frozen["enabled"])
        self.assertEqual(frozen["lower_bound_ms"], 100.0)
        self.assertEqual(frozen["upper_bound_ms"], 150.0)
        self.assertEqual(frozen["tolerance_ms"], 25.0)

    def test_disabled_evidence_has_no_fake_counts(self):
        payload = evidence_interval_comparison(disabled_contract(), events=[{"accepted": True, "press_interval_ms": 125}])
        self.assertEqual(payload, {"enabled": False})
        self.assertNotIn("within_count", payload)

    def test_enabled_without_value_freezes_disabled(self):
        frozen = freeze_interval_comparison(
            {
                "fixture_reference_hz": 8.0,
                SETTINGS_ENABLED: True,
                SETTINGS_BASIS: BASIS_PERCENT,
            },
            manual=False,
        )
        self.assertEqual(frozen, {"enabled": False})


class SummaryTests(unittest.TestCase):
    def test_counts_and_percent(self):
        summary = summarize_positions([
            POSITION_NOT_COMPARABLE,
            POSITION_WITHIN, POSITION_WITHIN,
            POSITION_BELOW, POSITION_ABOVE, POSITION_ABOVE,
        ])
        self.assertEqual(summary["comparable_interval_count"], 5)
        self.assertEqual(summary["within_count"], 2)
        self.assertEqual(summary["outside_count"], 3)
        self.assertEqual(summary["below_count"], 1)
        self.assertEqual(summary["above_count"], 2)
        self.assertEqual(summary["within_pct"], 40.0)

    def _assert_identities(self, summary):
        comparable = summary["comparable_interval_count"]
        self.assertEqual(summary["within_count"] + summary["below_count"] + summary["above_count"], comparable)
        self.assertEqual(summary["outside_count"], summary["below_count"] + summary["above_count"])
        if comparable:
            self.assertAlmostEqual(summary["within_pct"], summary["within_count"] / comparable * 100.0)
        else:
            self.assertIsNone(summary["within_pct"])

    def test_identities_hold_with_unknown_and_blank_tokens(self):
        summary = summarize_positions([
            POSITION_NOT_COMPARABLE, "", None, "garbage",
            POSITION_WITHIN, POSITION_BELOW, POSITION_ABOVE,
        ])
        self.assertEqual(summary["comparable_interval_count"], 3)
        self._assert_identities(summary)

    def test_only_first_press_is_not_comparable(self):
        summary = summarize_positions([POSITION_NOT_COMPARABLE])
        self.assertEqual(summary["comparable_interval_count"], 0)
        self._assert_identities(summary)

    def test_model_comparable_count_excludes_first_press(self):
        from mouse_click_stability_analyzer.completed_result import build_completed_result_model

        events = AssociationIndependenceTests()._events()
        model = build_completed_result_model(
            locked=AssociationIndependenceTests()._settings(window_ms=20.0, enabled=True, value=20.0),
            events=events, run_id="s", target="DUT", host_evidence_snapshot=None,
        )
        positions = [row["range_position"] for row in model["click_data"]]
        self.assertEqual(positions[0], POSITION_NOT_COMPARABLE)
        summary = summarize_positions(positions)
        self.assertEqual(summary["comparable_interval_count"], len(events) - 1)
        self.assertEqual(
            (summary["within_count"], summary["below_count"], summary["above_count"]), (2, 1, 1),
        )
        self._assert_identities(summary)


class ReferenceRateInvalidationTests(unittest.TestCase):
    def test_ms_value_invalid_after_rate_change_is_not_clamped(self):
        valid = resolve_configured_range(reference_hz=5, basis=BASIS_MILLISECONDS, value=120)
        self.assertEqual((valid["lower_bound_ms"], valid["upper_bound_ms"]), (80.0, 320.0))
        with self.assertRaises(IntervalComparisonError) as ctx:
            resolve_configured_range(reference_hz=10, basis=BASIS_MILLISECONDS, value=120)
        self.assertEqual(ctx.exception.key, "interval_comparison_ms_range")
        fixed = resolve_configured_range(reference_hz=10, basis=BASIS_MILLISECONDS, value=50)
        self.assertEqual(fixed["basis"], BASIS_MILLISECONDS)
        self.assertEqual((fixed["lower_bound_ms"], fixed["upper_bound_ms"]), (50.0, 150.0))


class HoldSeriesTests(unittest.TestCase):
    def test_hold_series_uses_finite_non_negative_holds_only(self):
        from mouse_click_stability_analyzer.completed_result import _analysis_payload

        events = AssociationIndependenceTests()._events()
        events[1]["hold_ms"] = None
        events[2]["hold_ms"] = math.nan
        events[3]["hold_ms"] = 55.5
        events.append({"accepted": False, "press_elapsed_ms": 600.0, "hold_ms": 40.0})
        events.append({"accepted": True, "press_elapsed_ms": 700.0, "hold_ms": -1.0})
        events.append({"accepted": True, "press_elapsed_ms": math.inf, "hold_ms": 40.0})
        series = _analysis_payload(events, manual=False, reference_ms=125.0)["hold_series"]
        self.assertEqual([x for x, _ in series], [0.0, 385.0, 510.0])
        self.assertEqual([h for _, h in series], [40.0, 55.5, 40.0])
        self.assertTrue(all(math.isfinite(h) and h >= 0 for _, h in series))


class AssociationIndependenceTests(unittest.TestCase):
    def _events(self):
        intervals = [0.0, 125.0, 90.0, 170.0, 125.0]
        out, t = [], 0.0
        for i, step in enumerate(intervals):
            t += step if i else 0.0
            out.append({
                "index": i + 1,
                "click_index": i + 1,
                "button": "Left",
                "accepted": True,
                "press_elapsed_ms": t,
                "press_interval_ms": None if i == 0 else step,
                "hold_ms": 40.0,
                "capture_source": "Windows Raw Input",
            })
        return out

    def _settings(self, *, window_ms: float, enabled: bool, value: float):
        return {
            "manual_mode": False,
            "focus_button": "Left",
            "fixture_reference_hz": 8.0,
            "fixture_hz": 8.0,
            "duration_sec": 1.0,
            "fixture_timing_tolerance_ms": window_ms,
            SETTINGS_ENABLED: enabled,
            SETTINGS_BASIS: BASIS_PERCENT,
            SETTINGS_VALUE: value,
        }

    def _matching(self, model):
        snap = model["host_evidence"]["snapshot"]
        return {
            "counts": snap["counts"],
            "matching": snap["matching"],
            "timing": snap["timing"],
            "window": snap["configuration"]["timing_tolerance_ms"],
        }

    def test_changing_comparison_does_not_change_host_evidence(self):
        from mouse_click_stability_analyzer.completed_result import build_completed_result_model
        from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence

        events = self._events()
        times = [e["press_elapsed_ms"] for e in events]
        snap = build_fixture_host_evidence(1.0, 8.0, 20.0, times)
        a = build_completed_result_model(
            locked=self._settings(window_ms=20.0, enabled=True, value=20.0),
            events=events, run_id="a", target="DUT", host_evidence_snapshot=snap,
        )
        b = build_completed_result_model(
            locked=self._settings(window_ms=20.0, enabled=True, value=5.0),
            events=events, run_id="b", target="DUT", host_evidence_snapshot=snap,
        )
        self.assertEqual(self._matching(a), self._matching(b))
        self.assertEqual(a["interval_comparison"]["lower_bound_ms"], 100.0)
        self.assertEqual(b["interval_comparison"]["lower_bound_ms"], 118.75)

    def test_changing_association_window_does_not_change_comparison_bounds(self):
        from mouse_click_stability_analyzer.completed_result import build_completed_result_model
        from mouse_click_stability_analyzer.host_evidence import build_fixture_host_evidence

        events = self._events()
        times = [e["press_elapsed_ms"] for e in events]
        snap_wide = build_fixture_host_evidence(1.0, 8.0, 40.0, times)
        snap_tight = build_fixture_host_evidence(1.0, 8.0, 5.0, times)
        wide = build_completed_result_model(
            locked=self._settings(window_ms=40.0, enabled=True, value=20.0),
            events=events, run_id="w", target="DUT", host_evidence_snapshot=snap_wide,
        )
        tight = build_completed_result_model(
            locked=self._settings(window_ms=5.0, enabled=True, value=20.0),
            events=events, run_id="t", target="DUT", host_evidence_snapshot=snap_tight,
        )
        self.assertEqual(wide["interval_comparison"]["lower_bound_ms"], 100.0)
        self.assertEqual(tight["interval_comparison"]["lower_bound_ms"], 100.0)
        self.assertEqual(wide["interval_comparison"]["upper_bound_ms"], 150.0)
        self.assertEqual(tight["interval_comparison"]["upper_bound_ms"], 150.0)
        positions = [row["range_position"] for row in wide["click_data"]]
        self.assertEqual(positions, [row["range_position"] for row in tight["click_data"]])
        self.assertNotEqual(self._matching(wide)["window"], self._matching(tight)["window"])
        self.assertNotEqual(self._matching(wide)["matching"], self._matching(tight)["matching"])


class ArtifactContractTests(unittest.TestCase):
    def test_standard_package_has_factual_comparison_and_no_verdict(self):
        import csv
        import json
        import re
        import tempfile
        from pathlib import Path

        from mouse_click_stability_analyzer import app as legacy_app
        from mouse_click_stability_analyzer.artifact_contract import (
            FACTUAL_EVENT_FIELDS,
            FORBIDDEN_CSV_COLUMNS,
            scan_csv_headers,
            scan_forbidden_semantics,
        )
        from mouse_click_stability_analyzer.completed_result import (
            RUN_STATUS_COMPLETE,
            build_completed_result_model,
        )
        from mouse_click_stability_analyzer.schema import artifact_names, legacy_artifact_names

        events = []
        t = 0.0
        for i, step in enumerate([0.0, 125.0, 90.0, 170.0]):
            t += step if i else 0.0
            events.append({
                "index": i + 1, "click_index": i + 1, "button": "Left", "accepted": True,
                "press_elapsed_ms": t, "press_interval_ms": None if i == 0 else step, "hold_ms": 40.0,
                "capture_source": "Windows Raw Input",
            })
        settings = {
            "manual_mode": False, "focus_button": "Left", "fixture_reference_hz": 8.0,
            "fixture_hz": 8.0, "duration_sec": 1.0, "fixture_timing_tolerance_ms": 20.0,
            SETTINGS_ENABLED: True, SETTINGS_BASIS: BASIS_PERCENT, SETTINGS_VALUE: 20.0,
            "profile_name": "Fixture_Custom", "language": "en",
            "capture_mode": "Windows Raw Input",
        }
        model = build_completed_result_model(
            locked=settings, events=events, run_id="s2d1", target="DUT", operator="op",
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = legacy_app.write_reports(
                Path(tmp), "DUT", "op", settings, events, "s2d1", completed_model=model,
            )
            package = Path(tmp) / "mcsa_s2d1"
            names = artifact_names("s2d1")
            self.assertEqual(sorted(p.name for p in package.iterdir()), sorted(names.values()))
            for fname in legacy_artifact_names("s2d1").values():
                self.assertFalse((package / fname).exists(), fname)
            evidence = json.loads(Path(paths["evidence_json"]).read_text(encoding="utf-8"))
            html = Path(paths["engineering_html"]).read_text(encoding="utf-8")
            with Path(paths["all_click_log_csv"]).open(encoding="utf-8-sig", newline="") as handle:
                headers = list(csv.DictReader(handle).fieldnames or [])
        cmp_block = evidence["interval_comparison"]
        self.assertTrue(cmp_block["enabled"])
        self.assertEqual(cmp_block["basis"], "percent")
        self.assertEqual(cmp_block["configured_value"], 20.0)
        self.assertEqual(cmp_block["lower_bound_ms"], 100.0)
        self.assertEqual(cmp_block["upper_bound_ms"], 150.0)
        self.assertEqual(cmp_block["comparable_interval_count"], 3)
        self.assertEqual(cmp_block["within_count"], 1)
        self.assertEqual(cmp_block["below_count"], 1)
        self.assertEqual(cmp_block["above_count"], 1)
        self.assertNotIn("pass", cmp_block)
        self.assertNotIn("fail", cmp_block)
        self.assertNotIn("verdict", cmp_block)
        self.assertEqual(scan_forbidden_semantics(evidence, source="evidence"), [])
        self.assertEqual(evidence["run_status"], RUN_STATUS_COMPLETE)
        self.assertEqual(evidence["analysis_scope"], "measurement_only")
        self.assertEqual(headers, list(FACTUAL_EVENT_FIELDS))
        self.assertEqual(scan_csv_headers(headers), [])
        for name in FORBIDDEN_CSV_COLUMNS:
            self.assertNotIn(name, headers)
        self.assertIsNone(re.search(r"\b(PASS|WARN|FAIL)\b", html))
        self.assertIn("Measurement only", html)
        self.assertIn("Within configured interval range", html)
        self.assertIn("100.00–150.00 ms", html)
        self.assertNotIn("DUT result", html)

    def test_completed_model_does_not_follow_later_settings_mutation(self):
        from mouse_click_stability_analyzer.completed_result import build_completed_result_model

        settings = {
            "manual_mode": False, "focus_button": "Left", "fixture_reference_hz": 8.0,
            "duration_sec": 1.0, "fixture_timing_tolerance_ms": 20.0,
            SETTINGS_ENABLED: True, SETTINGS_BASIS: BASIS_PERCENT, SETTINGS_VALUE: 20.0,
        }
        events = [
            {"index": 1, "accepted": True, "press_elapsed_ms": 0.0, "press_interval_ms": None, "hold_ms": 8.0, "button": "Left", "capture_source": "Windows Raw Input"},
            {"index": 2, "accepted": True, "press_elapsed_ms": 125.0, "press_interval_ms": 125.0, "hold_ms": 8.0, "button": "Left", "capture_source": "Windows Raw Input"},
        ]
        model = build_completed_result_model(locked=settings, events=events, run_id="frz", target="DUT")
        settings[SETTINGS_VALUE] = 5.0
        self.assertEqual(model["interval_comparison"]["lower_bound_ms"], 100.0)
        self.assertEqual(model["click_data"][1]["range_position"], POSITION_WITHIN)


if __name__ == "__main__":
    unittest.main()
