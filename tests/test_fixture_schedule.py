"""Focused tests for the Phase 2B-3a1 configured-duration schedule foundation."""
from __future__ import annotations

import math
import sys
import unittest
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.fixture_schedule import (
    FixtureScheduleError,
    expected_fixture_slot_count,
    fixture_period_s,
    fixture_reference_interval_ms,
    iter_expected_fixture_slots_monotonic_s,
    iter_expected_fixture_slots_relative_ms,
    scheduled_end_monotonic_s,
)


def _legacy_end_minus_start_count(start: float, duration: float, hz: float) -> int:
    """Reproduce the rejected 2B-3a endpoint-subtraction geometry."""
    end = start + duration
    ratio = (Decimal(str(end)) - Decimal(str(start))) * Decimal(str(hz))
    floored = int(ratio.to_integral_value(rounding=ROUND_FLOOR))
    if ratio == Decimal(floored):
        return floored
    return floored + 1


class ConfiguredDurationRegressionTests(unittest.TestCase):
    def test_start_123_456789_duration_10_must_be_400_not_endpoint_drift(self):
        start = 123.456789
        duration = 10.0
        hz = 40.0
        # Prove the old end-start path invents an extra slot for this anchor.
        self.assertEqual(_legacy_end_minus_start_count(start, duration, hz), 401)
        self.assertEqual(expected_fixture_slot_count(duration, hz), 400)
        rel = list(iter_expected_fixture_slots_relative_ms(duration, hz))
        self.assertEqual(len(rel), 400)
        self.assertEqual(rel[0], 0.0)
        self.assertEqual(rel[-1], 9975.0)
        self.assertNotIn(10000.0, rel)
        mono = list(iter_expected_fixture_slots_monotonic_s(start, duration, hz))
        self.assertEqual(len(mono), 400)
        self.assertAlmostEqual(mono[0], start, places=9)
        self.assertAlmostEqual(mono[-1], start + 9.975, places=9)

    def test_start_1234567_duration_10_is_400(self):
        start = 1_234_567.890123
        self.assertEqual(expected_fixture_slot_count(10.0, 40.0), 400)
        rel = list(iter_expected_fixture_slots_relative_ms(10.0, 40.0))
        self.assertEqual(rel[0], 0.0)
        self.assertEqual(rel[-1], 9975.0)
        mono = list(iter_expected_fixture_slots_monotonic_s(start, 10.0, 40.0))
        self.assertEqual(len(mono), 400)

    def test_many_anchors_share_identical_relative_schedule(self):
        duration = 10.0
        hz = 40.0
        anchors = (
            0.0,
            1.0,
            123.456789,
            98765.4321,
            1_234_567.890123,
            9_876_543.210987,
        )
        baseline = list(iter_expected_fixture_slots_relative_ms(duration, hz))
        self.assertEqual(len(baseline), 400)
        self.assertEqual(baseline[0], 0.0)
        self.assertEqual(baseline[-1], 9975.0)
        for start in anchors:
            with self.subTest(start=start):
                self.assertEqual(expected_fixture_slot_count(duration, hz), 400)
                self.assertEqual(
                    list(iter_expected_fixture_slots_relative_ms(duration, hz)),
                    baseline,
                )
                mono = list(iter_expected_fixture_slots_monotonic_s(start, duration, hz))
                self.assertEqual(len(mono), 400)
                self.assertEqual(mono[0], float(Decimal(str(start))))
                # Absolute slots share the same index geometry as relative slots.
                # Do not re-derive relative ms via float (mono - start).
                hz_d = Decimal(str(hz))
                start_d = Decimal(str(start))
                for k, abs_t in enumerate(mono):
                    self.assertEqual(abs_t, float(start_d + (Decimal(k) / hz_d)))
                    self.assertEqual(baseline[k], float((Decimal(k) / hz_d) * Decimal(1000)))


class ExactDurationCountTests(unittest.TestCase):
    def test_40hz_for_exactly_10s(self):
        self.assertEqual(expected_fixture_slot_count(10.0, 40.0), 400)
        rel = list(iter_expected_fixture_slots_relative_ms(10.0, 40.0))
        self.assertEqual(len(rel), 400)
        self.assertEqual(rel[0], 0.0)
        self.assertEqual(rel[-1], 9975.0)
        self.assertNotIn(10000.0, rel)
        self.assertTrue(all(t < 10000.0 for t in rel))

    def test_10hz_for_exactly_10s(self):
        self.assertEqual(expected_fixture_slot_count(10.0, 10.0), 100)

    def test_5hz_for_exactly_20s(self):
        self.assertEqual(expected_fixture_slot_count(20.0, 5.0), 100)

    def test_7_5hz_for_exactly_2s(self):
        self.assertEqual(expected_fixture_slot_count(2.0, 7.5), 15)
        rel = list(iter_expected_fixture_slots_relative_ms(2.0, 7.5))
        self.assertEqual(len(rel), 15)
        self.assertEqual(rel[0], 0.0)
        self.assertAlmostEqual(rel[1], 1000.0 / 7.5, places=10)


class HalfOpenBoundaryTests(unittest.TestCase):
    def test_slot_exactly_at_configured_duration_is_excluded(self):
        # 10 Hz → period 0.1 s; duration 0.5 includes 0..0.4 — not 0.5
        self.assertEqual(expected_fixture_slot_count(0.5, 10.0), 5)
        rel = list(iter_expected_fixture_slots_relative_ms(0.5, 10.0))
        self.assertEqual(rel, [0.0, 100.0, 200.0, 300.0, 400.0])
        self.assertNotIn(500.0, rel)
        mono = list(iter_expected_fixture_slots_monotonic_s(10.0, 0.5, 10.0))
        self.assertEqual(mono, [10.0, 10.1, 10.2, 10.3, 10.4])

    def test_duration_10_001_at_40hz_is_401(self):
        count = expected_fixture_slot_count(10.001, 40.0)
        self.assertEqual(count, 401)
        self.assertNotEqual(count, round(10.001 * 40.0))
        rel = list(iter_expected_fixture_slots_relative_ms(10.001, 40.0))
        self.assertEqual(len(rel), 401)
        self.assertEqual(rel[-1], 10000.0)
        self.assertTrue(rel[-1] < 10.001 * 1000.0)


class InvalidInputTests(unittest.TestCase):
    def test_reject_non_positive_frequency(self):
        for bad in (0, 0.0, -1, -10.5):
            with self.subTest(bad=bad):
                with self.assertRaises(FixtureScheduleError):
                    expected_fixture_slot_count(1.0, bad)

    def test_reject_nan_inf_bool_text_frequency(self):
        for bad in (math.nan, math.inf, -math.inf, True, False, "40", "10Hz"):
            with self.subTest(bad=bad):
                with self.assertRaises(FixtureScheduleError):
                    expected_fixture_slot_count(1.0, bad)

    def test_reject_invalid_duration(self):
        for bad in (0, 0.0, -1, math.nan, math.inf, -math.inf, True, False, "10"):
            with self.subTest(bad=bad):
                with self.assertRaises(FixtureScheduleError):
                    expected_fixture_slot_count(bad, 40.0)

    def test_reject_invalid_start_for_monotonic_iter(self):
        with self.assertRaises(FixtureScheduleError):
            list(iter_expected_fixture_slots_monotonic_s(math.nan, 10.0, 40.0))
        with self.assertRaises(FixtureScheduleError):
            list(iter_expected_fixture_slots_monotonic_s(True, 10.0, 40.0))
        with self.assertRaises(FixtureScheduleError):
            scheduled_end_monotonic_s("0", 10.0)


class ScheduledEndHelperTests(unittest.TestCase):
    def test_scheduled_end_is_start_plus_duration(self):
        start = 123.456789
        end = scheduled_end_monotonic_s(start, 10.0)
        self.assertEqual(end, start + 10.0)
        # Cutoff float noise must not affect authoritative count.
        self.assertEqual(expected_fixture_slot_count(10.0, 40.0), 400)


class GeneratorMemoryTests(unittest.TestCase):
    def test_count_does_not_require_materializing_slots(self):
        count = expected_fixture_slot_count(3600.0, 40.0)
        self.assertEqual(count, 144_000)
        gen = iter_expected_fixture_slots_relative_ms(3600.0, 40.0)
        self.assertEqual(next(gen), 0.0)
        self.assertTrue(hasattr(gen, "__next__"))

    def test_period_helpers(self):
        self.assertEqual(fixture_period_s(40.0), 0.025)
        self.assertEqual(fixture_reference_interval_ms(40.0), 25.0)
        self.assertEqual(fixture_reference_interval_ms(10.0), 100.0)
        self.assertEqual(fixture_reference_interval_ms(5.0), 200.0)


if __name__ == "__main__":
    unittest.main()
