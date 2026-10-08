"""4E-B1 nearest-slot residual math."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.characterization.math import (
    boundary_distance_ms,
    in_configured_window,
    nearest_slot,
    occupancy_summary,
    reference_interval_ms,
    residual_in_half_open_range,
)


class ReferenceIntervalTests(unittest.TestCase):
    def test_five_hz_is_200_ms(self):
        self.assertEqual(reference_interval_ms(5), 200.0)


class NearestSlotTests(unittest.TestCase):
    T = 200.0

    def _assign(self, t):
        return nearest_slot(t, self.T)

    def test_exact_nominal(self):
        hit = self._assign(200)
        self.assertEqual(hit["nearest_slot_index"], 1)
        self.assertEqual(hit["wrapped_residual_ms"], 0)
        self.assertEqual(hit["nominal_slot_time_ms"], 200)

    def test_positive_residual(self):
        hit = self._assign(207)
        self.assertEqual(hit["nearest_slot_index"], 1)
        self.assertAlmostEqual(hit["wrapped_residual_ms"], 7.0)
        self.assertAlmostEqual(hit["nominal_slot_time_ms"], 200.0)

    def test_negative_residual(self):
        hit = self._assign(396)
        self.assertEqual(hit["nearest_slot_index"], 2)
        self.assertAlmostEqual(hit["nominal_slot_time_ms"], 400.0)
        self.assertAlmostEqual(hit["wrapped_residual_ms"], -4.0)

    def test_exact_positive_half_period_goes_to_later_slot(self):
        hit = self._assign(100)
        self.assertEqual(hit["nearest_slot_index"], 1)
        self.assertAlmostEqual(hit["wrapped_residual_ms"], -100.0)
        self.assertAlmostEqual(hit["nominal_slot_time_ms"], 200.0)

    def test_does_not_use_bankers_round(self):
        # t/T = 2.5; banker's round(2.5) == 2, which would leave residual = +T/2.
        hit = self._assign(500)
        self.assertEqual(hit["nearest_slot_index"], 3)
        self.assertAlmostEqual(hit["wrapped_residual_ms"], -100.0)
        self.assertTrue(residual_in_half_open_range(hit["wrapped_residual_ms"], self.T))

    def test_range_guarantee(self):
        for t in (0, 1, 99.999, 100, 100.001, 200, 300, 399, 400, 999, 0.0, 123.456):
            hit = self._assign(t)
            self.assertTrue(
                residual_in_half_open_range(hit["wrapped_residual_ms"], self.T),
                msg=(t, hit),
            )
            self.assertGreaterEqual(hit["wrapped_residual_ms"], -self.T / 2)
            self.assertLess(hit["wrapped_residual_ms"], self.T / 2)


class BoundaryDistanceTests(unittest.TestCase):
    def test_examples(self):
        self.assertAlmostEqual(boundary_distance_ms(0, 200), 100)
        self.assertAlmostEqual(boundary_distance_ms(90, 200), 10)
        self.assertAlmostEqual(boundary_distance_ms(-100, 200), 0)


class WindowTests(unittest.TestCase):
    def test_duration_is_strict_upper_bound(self):
        self.assertTrue(in_configured_window(0, 1000))
        self.assertTrue(in_configured_window(999.9, 1000))
        self.assertFalse(in_configured_window(1000, 1000))
        self.assertFalse(in_configured_window(1001, 1000))
        self.assertFalse(in_configured_window(-0.01, 1000))


class OccupancyLanguageTests(unittest.TestCase):
    def test_empty_and_multiplicity_are_factual(self):
        summary = occupancy_summary([1, 0, 3, 1, 0])
        self.assertEqual(summary["nominal_slot_count"], 5)
        self.assertEqual(summary["occupied_slot_count"], 3)
        self.assertEqual(summary["empty_slot_count"], 2)
        self.assertEqual(summary["slots_with_one_observation"], 2)
        self.assertEqual(summary["slots_with_multiple_observations"], 1)
        blob = str(summary)
        for banned in ("miss", "missed", "duplicate", "bounce", "chatter", "defect"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
