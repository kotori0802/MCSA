"""Focused tests for the Phase 2B-3d1 host evidence foundation."""
from __future__ import annotations

import statistics
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.fixture_matching import (
    FixtureMatchingError,
    match_fixture_press_observations,
)
from mouse_click_stability_analyzer.fixture_schedule import (
    FixtureScheduleError,
    expected_fixture_slot_count,
    iter_expected_fixture_slots_relative_ms,
)
from mouse_click_stability_analyzer.host_evidence import (
    HostEvidenceError,
    build_fixture_host_evidence,
)
from mouse_click_stability_analyzer.measurements import descriptive_stats

_FORBIDDEN_SUBSTRINGS = (
    "pass",
    "fail",
    "verdict",
    "result",
    "health",
    "score",
    "missing_click",
    "double_click",
    "extra_click",
    "bounce",
    "chatter",
    "debounce",
    "hardware_failure",
    "root_cause",
    "diagnosis",
    "issue_count",
)

_EVALUATION_KEYS = (
    "warning",
    "review_required",
    "severity",
    "overall_status",
    "spec_result",
    "status",
)


def _all_keys(payload: object) -> list[str]:
    keys: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            keys.append(str(key).lower())
            keys.extend(_all_keys(value))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            keys.extend(_all_keys(item))
    return keys


def _all_string_values(payload: object) -> list[str]:
    values: list[str] = []
    if isinstance(payload, dict):
        for value in payload.values():
            values.extend(_all_string_values(value))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            values.extend(_all_string_values(item))
    elif isinstance(payload, str):
        values.append(payload.lower())
    return values


def _evidence(observed, *, duration=0.100, hz=40, tol=2.0):
    return build_fixture_host_evidence(duration, hz, tol, observed)


class PerfectAlignmentTests(unittest.TestCase):
    def test_perfect_40hz_host_alignment(self) -> None:
        ev = _evidence([0.0, 24.8, 50.2, 75.0])
        self.assertEqual(
            ev["counts"],
            {
                "expected_slot_count": 4,
                "raw_host_press_count": 4,
                "in_window_host_press_count": 4,
                "host_count_delta_vs_expected_slots": 0,
                "host_count_deficit_vs_expected_slots": 0,
                "host_count_excess_vs_expected_slots": 0,
            },
        )
        self.assertEqual(
            ev["matching"],
            {
                "empty_expected_slot_count": 0,
                "single_occupancy_slot_count": 4,
                "multi_occupancy_slot_count": 0,
                "matched_host_observation_count": 4,
                "unmatched_host_observation_count": 0,
                "ambiguous_host_observation_count": 0,
                "outside_capture_window_observation_count": 0,
            },
        )
        self.assertEqual(ev["timing"]["matched_delta_stats"]["count"], 4)
        self.assertEqual(ev["timing"]["matched_delta_stats"]["minimum"], -0.2)

    def test_configuration_echo(self) -> None:
        ev = _evidence([0.0])
        self.assertEqual(
            ev["configuration"],
            {
                "capture_duration_s": 0.1,
                "fixture_frequency_hz": 40.0,
                "reference_interval_ms": 25.0,
                "timing_tolerance_ms": 2.0,
                "matching_windows_can_overlap": False,
            },
        )


class CountEvidenceTests(unittest.TestCase):
    def test_host_count_deficit(self) -> None:
        ev = _evidence([0, 25, 75])
        self.assertEqual(ev["counts"]["in_window_host_press_count"], 3)
        self.assertEqual(ev["counts"]["host_count_delta_vs_expected_slots"], -1)
        self.assertEqual(ev["counts"]["host_count_deficit_vs_expected_slots"], 1)
        self.assertEqual(ev["counts"]["host_count_excess_vs_expected_slots"], 0)
        self.assertEqual(ev["matching"]["empty_expected_slot_count"], 1)

    def test_host_count_excess(self) -> None:
        ev = _evidence([0, 24.5, 25.5, 50, 75])
        self.assertEqual(ev["counts"]["in_window_host_press_count"], 5)
        self.assertEqual(ev["counts"]["host_count_delta_vs_expected_slots"], 1)
        self.assertEqual(ev["counts"]["host_count_excess_vs_expected_slots"], 1)
        self.assertEqual(ev["counts"]["host_count_deficit_vs_expected_slots"], 0)
        self.assertGreaterEqual(ev["matching"]["multi_occupancy_slot_count"], 1)

    def test_compensating_empty_and_multi_keep_evidence(self) -> None:
        ev = _evidence([0, 24.5, 25.5, 75])
        self.assertEqual(ev["counts"]["expected_slot_count"], 4)
        self.assertEqual(ev["counts"]["in_window_host_press_count"], 4)
        self.assertEqual(ev["counts"]["host_count_delta_vs_expected_slots"], 0)
        self.assertEqual(ev["matching"]["empty_expected_slot_count"], 1)
        self.assertEqual(ev["matching"]["multi_occupancy_slot_count"], 1)

    def test_timing_outside_tolerance_with_equal_count(self) -> None:
        ev = _evidence([0, 30, 50, 75], tol=2.0)
        self.assertEqual(ev["counts"]["raw_host_press_count"], 4)
        self.assertEqual(ev["counts"]["in_window_host_press_count"], 4)
        self.assertEqual(ev["counts"]["host_count_delta_vs_expected_slots"], 0)
        self.assertEqual(ev["matching"]["empty_expected_slot_count"], 1)
        self.assertEqual(ev["matching"]["unmatched_host_observation_count"], 1)
        self.assertEqual(ev["timing"]["matched_delta_stats"]["count"], 3)


class AmbiguityTests(unittest.TestCase):
    def test_ambiguous_observation_stays_visible_and_unassigned(self) -> None:
        ev = _evidence([0, 12.5, 50, 75], tol=13.0)
        self.assertTrue(ev["configuration"]["matching_windows_can_overlap"])
        self.assertEqual(ev["matching"]["ambiguous_host_observation_count"], 1)
        self.assertEqual(ev["matching"]["matched_host_observation_count"], 3)
        self.assertEqual(ev["matching"]["single_occupancy_slot_count"], 3)
        self.assertEqual(ev["matching"]["empty_expected_slot_count"], 1)
        self.assertEqual(ev["timing"]["matched_delta_stats"]["count"], 3)
        self.assertEqual(ev["counts"]["in_window_host_press_count"], 4)


class CaptureWindowTests(unittest.TestCase):
    def test_outside_capture_window(self) -> None:
        ev = _evidence([0, 25, 50, 75, 100.0, 100.1])
        self.assertEqual(ev["counts"]["raw_host_press_count"], 6)
        self.assertEqual(ev["counts"]["in_window_host_press_count"], 4)
        self.assertEqual(ev["matching"]["outside_capture_window_observation_count"], 2)
        self.assertEqual(ev["counts"]["host_count_delta_vs_expected_slots"], 0)
        self.assertEqual(ev["timing"]["matched_delta_stats"]["count"], 4)

    def test_outside_events_do_not_change_count_delta(self) -> None:
        in_window = [0, 25, 75]
        a = _evidence(in_window)
        b = _evidence(in_window + [100.0, 120.0, 250.5])
        for key in (
            "expected_slot_count",
            "in_window_host_press_count",
            "host_count_delta_vs_expected_slots",
            "host_count_deficit_vs_expected_slots",
            "host_count_excess_vs_expected_slots",
        ):
            self.assertEqual(a["counts"][key], b["counts"][key], key)
        self.assertEqual(a["timing"], b["timing"])
        self.assertEqual(b["counts"]["raw_host_press_count"] - a["counts"]["raw_host_press_count"], 3)
        self.assertEqual(
            b["matching"]["outside_capture_window_observation_count"]
            - a["matching"]["outside_capture_window_observation_count"],
            3,
        )
        for key in (
            "empty_expected_slot_count",
            "single_occupancy_slot_count",
            "multi_occupancy_slot_count",
            "matched_host_observation_count",
            "unmatched_host_observation_count",
            "ambiguous_host_observation_count",
        ):
            self.assertEqual(a["matching"][key], b["matching"][key], key)


class TimingStatsTests(unittest.TestCase):
    def test_matched_delta_stats_match_descriptive_stats(self) -> None:
        observed = [0.0, 24.0, 51.0, 75.5]
        deltas = [0.0, -1.0, 1.0, 0.5]
        matching = match_fixture_press_observations(0.100, 40, 2.0, observed)
        self.assertEqual([o["delta_ms"] for o in matching["observations"]], deltas)
        ev = _evidence(observed)
        stats = ev["timing"]["matched_delta_stats"]
        self.assertEqual(stats, descriptive_stats(deltas))
        self.assertEqual(stats["count"], 4)
        self.assertAlmostEqual(stats["average"], 0.125)
        self.assertEqual(stats["minimum"], -1.0)
        self.assertEqual(stats["maximum"], 1.0)
        self.assertAlmostEqual(stats["stdev"], statistics.pstdev(deltas))

    def test_matched_absolute_delta_stats(self) -> None:
        ev = _evidence([0.0, 24.0, 51.0, 75.5])
        self.assertEqual(
            ev["timing"]["matched_absolute_delta_stats"],
            descriptive_stats([0.0, 1.0, 1.0, 0.5]),
        )

    def test_stats_use_matcher_deltas_only(self) -> None:
        observed = [0.0, 12.0, 24.9, 30.0, 51.5, 100.2]
        matching = match_fixture_press_observations(0.100, 40, 2.0, observed)
        expected_deltas = [o["delta_ms"] for o in matching["observations"] if o["status"] == "MATCHED"]
        ev = _evidence(observed)
        self.assertEqual(ev["timing"]["matched_delta_stats"], descriptive_stats(expected_deltas))
        self.assertEqual(ev["timing"]["matched_delta_stats"]["count"], 3)


class AnchorContractTests(unittest.TestCase):
    def test_empty_observations_have_no_t0(self) -> None:
        with self.assertRaises(HostEvidenceError):
            _evidence([])

    def test_empty_generator_has_no_t0(self) -> None:
        with self.assertRaises(HostEvidenceError):
            _evidence(v for v in ())

    def test_missing_zero_anchor_rejected(self) -> None:
        for observed in ([12.0, 37.0], [0.4, 24.8, 50.2, 75.0], [0.0001, 25.0], [100.0]):
            with self.assertRaises(HostEvidenceError):
                _evidence(observed)

    def test_only_outside_window_observations_rejected(self) -> None:
        with self.assertRaises(HostEvidenceError):
            _evidence([100.0, 125.0])

    def test_error_is_value_error_and_not_foundation_error(self) -> None:
        with self.assertRaises(HostEvidenceError) as ctx:
            _evidence([12.0])
        self.assertIsInstance(ctx.exception, ValueError)
        self.assertNotIsInstance(ctx.exception, (FixtureMatchingError, FixtureScheduleError))

    def test_foundation_errors_take_precedence(self) -> None:
        with self.assertRaises(FixtureMatchingError):
            _evidence([12.0, -1.0])
        with self.assertRaises(FixtureScheduleError):
            build_fixture_host_evidence(0, 40, 2.0, [])

    def test_observations_not_rebased(self) -> None:
        ev = _evidence([0.0, 26.0, 50.0, 75.0])
        self.assertEqual(ev["timing"]["matched_delta_stats"]["maximum"], 1.0)
        self.assertEqual(ev["counts"]["raw_host_press_count"], 4)

    def test_zero_anchor_need_not_be_first_element(self) -> None:
        ordered = _evidence([0.0, 25.0, 50.0, 75.0])
        unordered = _evidence([25.0, 0.0, 50.0, 75.0])
        self.assertEqual(ordered["counts"], unordered["counts"])
        self.assertEqual(ordered["matching"], unordered["matching"])
        self.assertEqual(ordered["timing"], unordered["timing"])

    def test_integer_zero_anchor_accepted(self) -> None:
        ev = _evidence([0, 25, 50, 75])
        self.assertEqual(ev["matching"]["single_occupancy_slot_count"], 4)

    def test_anchor_does_not_claim_physical_first_stroke(self) -> None:
        keys = _all_keys(_evidence([0.0, 25.0, 50.0, 75.0]))
        for forbidden in ("physical", "first_stroke", "pre_t0", "stroke"):
            for key in keys:
                self.assertNotIn(forbidden, key)


class DecimalFrequencyTests(unittest.TestCase):
    def test_7_5_hz_consistent_with_foundations(self) -> None:
        published = list(iter_expected_fixture_slots_relative_ms(2.0, 7.5))
        ev = build_fixture_host_evidence(2.0, 7.5, 0.0, published)
        self.assertEqual(ev["counts"]["expected_slot_count"], expected_fixture_slot_count(2.0, 7.5))
        self.assertEqual(ev["counts"]["expected_slot_count"], 15)
        self.assertEqual(ev["counts"]["host_count_delta_vs_expected_slots"], 0)
        self.assertEqual(ev["matching"]["matched_host_observation_count"], 15)
        self.assertEqual(ev["matching"]["single_occupancy_slot_count"], 15)
        stats = ev["timing"]["matched_delta_stats"]
        self.assertEqual(stats["minimum"], 0.0)
        self.assertEqual(stats["maximum"], 0.0)
        self.assertAlmostEqual(ev["configuration"]["reference_interval_ms"], 1000.0 / 7.5)


class InputHandlingTests(unittest.TestCase):
    def test_generator_input_consumed_once(self) -> None:
        values = [0.0, 24.8, 50.2, 75.0, 100.5]
        consumed: list[float] = []

        def gen():
            for v in values:
                consumed.append(v)
                yield v

        ev = build_fixture_host_evidence(0.100, 40, 2.0, gen())
        self.assertEqual(consumed, values)
        self.assertEqual(ev["counts"]["raw_host_press_count"], 5)
        self.assertEqual(ev["counts"]["in_window_host_press_count"], 4)
        self.assertEqual(ev["matching"]["matched_host_observation_count"], 4)

    def test_invalid_duration_and_frequency(self) -> None:
        for bad in (0, -1, float("nan"), float("inf"), "1", True, None):
            with self.assertRaises((FixtureScheduleError, FixtureMatchingError)):
                build_fixture_host_evidence(bad, 40, 2.0, [0.0])
            with self.assertRaises((FixtureScheduleError, FixtureMatchingError)):
                build_fixture_host_evidence(0.1, bad, 2.0, [0.0])

    def test_invalid_tolerance(self) -> None:
        for bad in (-0.1, float("nan"), "2", True, None):
            with self.assertRaises(FixtureMatchingError):
                build_fixture_host_evidence(0.1, 40, bad, [0.0])

    def test_invalid_observations(self) -> None:
        for bad in (None, "0,25", b"0", 5):
            with self.assertRaises(FixtureMatchingError):
                build_fixture_host_evidence(0.1, 40, 2.0, bad)
        for bad_item in (-0.1, float("nan"), "25", True, None):
            with self.assertRaises(FixtureMatchingError):
                build_fixture_host_evidence(0.1, 40, 2.0, [0.0, bad_item])


class SemanticBoundaryTests(unittest.TestCase):
    def _samples(self):
        return [
            _evidence([0.0, 24.8, 50.2, 75.0]),
            _evidence([0, 24.5, 25.5, 75]),
            _evidence([0, 12.5, 50, 75, 100.0], tol=13.0),
            _evidence([0.0, 30.0, 100.0]),
        ]

    def test_no_diagnostic_fields(self) -> None:
        for ev in self._samples():
            for key in _all_keys(ev):
                for forbidden in _FORBIDDEN_SUBSTRINGS:
                    self.assertNotIn(forbidden, key)
            for value in _all_string_values(ev):
                for forbidden in _FORBIDDEN_SUBSTRINGS:
                    self.assertNotIn(forbidden, value)

    def test_no_evaluation_fields(self) -> None:
        for ev in self._samples():
            keys = set(_all_keys(ev))
            for forbidden in _EVALUATION_KEYS:
                self.assertNotIn(forbidden, keys)

    def test_top_level_shape(self) -> None:
        ev = _evidence([0.0])
        self.assertEqual(set(ev), {"configuration", "counts", "matching", "timing"})
        self.assertNotIn("physical_expected_stroke_count", _all_keys(ev))


if __name__ == "__main__":
    unittest.main()
