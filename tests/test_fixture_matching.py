"""Focused tests for the Phase 2B-3b fixture matching foundation."""
from __future__ import annotations

import math
import sys
import unittest
from decimal import Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.fixture_matching import (
    STATUS_AMBIGUOUS,
    STATUS_MATCHED,
    STATUS_OUTSIDE_CAPTURE_WINDOW,
    STATUS_UNMATCHED,
    FixtureMatchingError,
    match_fixture_press_observations,
)
from mouse_click_stability_analyzer.fixture_schedule import (
    FixtureScheduleError,
    expected_fixture_slot_count,
    iter_expected_fixture_slots_relative_ms,
)

_FORBIDDEN_FIELDS = (
    "verdict",
    "result",
    "pass",
    "fail",
    "health",
    "diagnosis",
    "root_cause",
    "chatter",
    "bounce",
)


def _assert_no_diagnostic_fields(test: unittest.TestCase, payload: object) -> None:
    if isinstance(payload, dict):
        lowered = {str(key).lower() for key in payload}
        for forbidden in _FORBIDDEN_FIELDS:
            test.assertNotIn(forbidden, lowered)
        for value in payload.values():
            _assert_no_diagnostic_fields(test, value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_diagnostic_fields(test, item)


class UniqueMatchTests(unittest.TestCase):
    def test_40hz_unique_matches(self):
        payload = match_fixture_press_observations(
            0.100,
            40.0,
            2.0,
            [0.4, 24.8, 50.2, 75.0],
        )
        self.assertEqual(payload["expected_slot_count"], 4)
        self.assertEqual([s["expected_time_ms"] for s in payload["slots"]], [0.0, 25.0, 50.0, 75.0])
        self.assertEqual([s["occupancy"] for s in payload["slots"]], [1, 1, 1, 1])
        self.assertEqual(payload["unmatched_observation_count"], 0)
        self.assertEqual(payload["ambiguous_observation_count"], 0)
        self.assertEqual(payload["outside_capture_window_count"], 0)
        self.assertEqual(
            [o["slot_index"] for o in payload["observations"]],
            [0, 1, 2, 3],
        )
        self.assertTrue(all(o["status"] == STATUS_MATCHED for o in payload["observations"]))


class OccupancyEvidenceTests(unittest.TestCase):
    def test_multi_occupancy_same_slot_is_not_labeled_double_click(self):
        payload = match_fixture_press_observations(0.100, 40.0, 2.0, [24.5, 25.7])
        slot1 = payload["slots"][1]
        self.assertEqual(slot1["occupancy"], 2)
        self.assertEqual(slot1["observation_indexes"], [0, 1])
        self.assertEqual(payload["multi_occupancy_slot_count"], 1)
        self.assertTrue(all(o["status"] == STATUS_MATCHED for o in payload["observations"]))
        self.assertTrue(all(o["slot_index"] == 1 for o in payload["observations"]))
        blob = str(payload).lower()
        self.assertNotIn("double click", blob)
        self.assertNotIn("double_click", blob)

    def test_empty_expected_slot_is_not_labeled_missing_click(self):
        payload = match_fixture_press_observations(0.100, 40.0, 2.0, [0.0, 25.0, 75.0])
        self.assertEqual(payload["slots"][2]["occupancy"], 0)
        self.assertEqual(payload["slots"][2]["expected_time_ms"], 50.0)
        self.assertEqual(payload["empty_slot_count"], 1)
        blob = str(payload).lower()
        self.assertNotIn("missing click", blob)
        self.assertNotIn("missing_click", blob)


class UnmatchedAndBoundaryTests(unittest.TestCase):
    def test_unmatched_is_not_nearest_assigned(self):
        payload = match_fixture_press_observations(0.100, 40.0, 2.0, [12.0])
        obs = payload["observations"][0]
        self.assertEqual(obs["status"], STATUS_UNMATCHED)
        self.assertEqual(obs["candidate_slot_indexes"], [])
        self.assertIsNone(obs["slot_index"])
        self.assertEqual([s["occupancy"] for s in payload["slots"]], [0, 0, 0, 0])

    def test_exact_inclusive_tolerance_boundary(self):
        payload = match_fixture_press_observations(0.100, 40.0, 2.0, [23.0, 27.0])
        self.assertEqual(payload["observations"][0]["status"], STATUS_MATCHED)
        self.assertEqual(payload["observations"][0]["slot_index"], 1)
        self.assertEqual(payload["observations"][1]["status"], STATUS_MATCHED)
        self.assertEqual(payload["observations"][1]["slot_index"], 1)
        self.assertEqual(payload["slots"][1]["occupancy"], 2)

    def test_just_outside_tolerance_is_unmatched(self):
        payload = match_fixture_press_observations(0.100, 40.0, 2.0, [22.9999, 27.0001])
        self.assertEqual(payload["observations"][0]["status"], STATUS_UNMATCHED)
        self.assertEqual(payload["observations"][1]["status"], STATUS_UNMATCHED)


class AmbiguityTests(unittest.TestCase):
    def test_overlapping_windows_are_ambiguous_not_nearest(self):
        payload = match_fixture_press_observations(0.100, 40.0, 13.0, [12.5])
        self.assertTrue(payload["matching_windows_can_overlap"])
        obs = payload["observations"][0]
        self.assertEqual(obs["status"], STATUS_AMBIGUOUS)
        self.assertEqual(obs["candidate_slot_indexes"], [0, 1])
        self.assertIsNone(obs["slot_index"])
        self.assertEqual([s["occupancy"] for s in payload["slots"]], [0, 0, 0, 0])
        self.assertEqual(payload["ambiguous_observation_count"], 1)


class ZeroToleranceTests(unittest.TestCase):
    def test_zero_tolerance_requires_exact_expected_time(self):
        payload = match_fixture_press_observations(0.100, 40.0, 0.0, [0.0, 25.0, 50.1, 75.0])
        statuses = [o["status"] for o in payload["observations"]]
        self.assertEqual(
            statuses,
            [STATUS_MATCHED, STATUS_MATCHED, STATUS_UNMATCHED, STATUS_MATCHED],
        )
        self.assertFalse(payload["matching_windows_can_overlap"])


class CaptureWindowTests(unittest.TestCase):
    def test_at_and_after_duration_are_outside_and_do_not_occupy(self):
        payload = match_fixture_press_observations(0.100, 40.0, 2.0, [100.0, 100.1])
        self.assertEqual(payload["outside_capture_window_count"], 2)
        self.assertTrue(
            all(o["status"] == STATUS_OUTSIDE_CAPTURE_WINDOW for o in payload["observations"])
        )
        self.assertEqual([s["occupancy"] for s in payload["slots"]], [0, 0, 0, 0])
        self.assertEqual(payload["expected_slot_count"], 4)

    def test_negative_observed_time_is_rejected(self):
        with self.assertRaises(FixtureMatchingError):
            match_fixture_press_observations(0.100, 40.0, 2.0, [-0.001])


class OrderAndIdentityTests(unittest.TestCase):
    def test_unsorted_input_preserves_original_indexes(self):
        payload = match_fixture_press_observations(
            0.100,
            40.0,
            2.0,
            [75.0, 0.4, 50.2, 24.8],
        )
        self.assertEqual(
            [o["observation_index"] for o in payload["observations"]],
            [0, 1, 2, 3],
        )
        self.assertEqual(
            [o["slot_index"] for o in payload["observations"]],
            [3, 0, 2, 1],
        )
        self.assertEqual(payload["slots"][0]["observation_indexes"], [1])
        self.assertEqual(payload["slots"][1]["observation_indexes"], [3])
        self.assertEqual(payload["slots"][2]["observation_indexes"], [2])
        self.assertEqual(payload["slots"][3]["observation_indexes"], [0])


class DecimalFrequencyTests(unittest.TestCase):
    def test_7_5hz_uses_fixture_schedule_geometry(self):
        duration = 2.0
        hz = 7.5
        expected = list(iter_expected_fixture_slots_relative_ms(duration, hz))
        self.assertEqual(len(expected), expected_fixture_slot_count(duration, hz))
        self.assertEqual(len(expected), 15)
        payload = match_fixture_press_observations(duration, hz, 0.0, expected)
        self.assertEqual(payload["expected_slot_count"], 15)
        self.assertEqual(
            [s["expected_time_ms"] for s in payload["slots"]],
            expected,
        )
        self.assertEqual(payload["matched_observation_count"], 15)
        self.assertTrue(all(o["status"] == STATUS_MATCHED for o in payload["observations"]))
        self.assertEqual(
            [o["slot_index"] for o in payload["observations"]],
            list(range(15)),
        )
        for obs in payload["observations"]:
            slot = payload["slots"][obs["slot_index"]]
            self.assertEqual(obs["observed_time_ms"], slot["expected_time_ms"])
            self.assertEqual(obs["delta_ms"], 0.0)


class MatchedEvidenceInvariantTests(unittest.TestCase):
    def test_matched_delta_uses_same_published_expected_time(self):
        cases = (
            (0.100, 40.0, 2.0, [0.4, 24.8, 50.2, 75.0]),
            (0.100, 40.0, 0.0, [0.0, 25.0, 50.0, 75.0]),
            (2.0, 7.5, 0.0, list(iter_expected_fixture_slots_relative_ms(2.0, 7.5))),
            (0.100, 40.0, 2.0, [23.0, 27.0]),
            (25.0, 40.0, 2.0, [t + 0.25 for t in iter_expected_fixture_slots_relative_ms(25.0, 40.0)]),
        )
        for duration, hz, tol, observed in cases:
            with self.subTest(duration=duration, hz=hz, tol=tol):
                payload = match_fixture_press_observations(duration, hz, tol, observed)
                tol_d = Decimal(str(payload["timing_tolerance_ms"]))
                for obs in payload["observations"]:
                    if obs["status"] != STATUS_MATCHED:
                        continue
                    slot = payload["slots"][obs["slot_index"]]
                    expected_delta = float(
                        Decimal(str(obs["observed_time_ms"]))
                        - Decimal(str(slot["expected_time_ms"]))
                    )
                    self.assertEqual(obs["delta_ms"], expected_delta)
                    self.assertLessEqual(abs(Decimal(str(obs["delta_ms"]))), tol_d)


class InvalidToleranceTests(unittest.TestCase):
    def test_reject_invalid_tolerance(self):
        for bad in (-1, math.nan, math.inf, -math.inf, True, False, "2"):
            with self.subTest(bad=bad):
                with self.assertRaises(FixtureMatchingError):
                    match_fixture_press_observations(0.100, 40.0, bad, [0.0])

    def test_zero_tolerance_is_allowed(self):
        payload = match_fixture_press_observations(0.100, 40.0, 0, [0.0])
        self.assertEqual(payload["timing_tolerance_ms"], 0.0)

    def test_invalid_schedule_inputs_remain_schedule_errors(self):
        with self.assertRaises(FixtureScheduleError):
            match_fixture_press_observations(0.0, 40.0, 2.0, [0.0])
        with self.assertRaises(FixtureScheduleError):
            match_fixture_press_observations(0.100, 0.0, 2.0, [0.0])


class AlgorithmSanityTests(unittest.TestCase):
    def test_long_run_unique_matching_without_nested_slot_scan_contract(self):
        duration = 25.0
        hz = 40.0
        expected = list(iter_expected_fixture_slots_relative_ms(duration, hz))
        self.assertEqual(len(expected), 1000)
        observed = [t + 0.25 for t in expected]
        payload = match_fixture_press_observations(duration, hz, 2.0, observed)
        self.assertEqual(payload["expected_slot_count"], 1000)
        self.assertEqual(payload["matched_observation_count"], 1000)
        self.assertEqual(payload["single_occupancy_slot_count"], 1000)
        self.assertEqual(payload["empty_slot_count"], 0)
        self.assertEqual(payload["ambiguous_observation_count"], 0)


class NeutralContractTests(unittest.TestCase):
    def test_result_has_no_diagnostic_fields(self):
        payload = match_fixture_press_observations(
            0.100,
            40.0,
            13.0,
            [0.0, 12.5, 50.0, 100.0],
        )
        _assert_no_diagnostic_fields(self, payload)


if __name__ == "__main__":
    unittest.main()
