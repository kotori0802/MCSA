"""Unit tests for the Phase 1 neutral measurement helpers."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.measurements import (
    actual_run_duration_s,
    descriptive_stats,
    interval_delta_ms,
    reference_interval_ms,
)

_STAT_FIELDS = ("count", "average", "minimum", "maximum", "stdev")
_FORBIDDEN_FIELDS = (
    "result",
    "verdict",
    "health",
    "score",
    "diagnosis",
    "root_cause",
    "issue_tag",
)


class ReferenceIntervalTests(unittest.TestCase):
    def test_none_means_not_configured(self):
        self.assertIsNone(reference_interval_ms(None))

    def test_ten_hz(self):
        self.assertEqual(reference_interval_ms(10), 100.0)

    def test_forty_hz(self):
        self.assertEqual(reference_interval_ms(40), 25.0)

    def test_twelve_point_five_hz(self):
        self.assertEqual(reference_interval_ms(12.5), 80.0)

    def test_zero_raises(self):
        with self.assertRaises(ValueError):
            reference_interval_ms(0)

    def test_negative_raises(self):
        with self.assertRaises(ValueError):
            reference_interval_ms(-10)

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            reference_interval_ms(math.nan)

    def test_infinity_raises(self):
        with self.assertRaises(ValueError):
            reference_interval_ms(math.inf)
        with self.assertRaises(ValueError):
            reference_interval_ms(-math.inf)

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            reference_interval_ms(True)
        with self.assertRaises(ValueError):
            reference_interval_ms(False)

    def test_text_raises(self):
        with self.assertRaises(ValueError):
            reference_interval_ms("10")


class IntervalDeltaTests(unittest.TestCase):
    def test_positive_delta(self):
        self.assertAlmostEqual(interval_delta_ms(106.42, 100.00), 6.42, places=10)

    def test_negative_delta(self):
        self.assertAlmostEqual(interval_delta_ms(97.5, 100.0), -2.5, places=10)

    def test_none_observed(self):
        self.assertIsNone(interval_delta_ms(None, 100.0))

    def test_none_reference(self):
        self.assertIsNone(interval_delta_ms(106.42, None))

    def test_both_none(self):
        self.assertIsNone(interval_delta_ms(None, None))

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            interval_delta_ms(math.nan, 100.0)
        with self.assertRaises(ValueError):
            interval_delta_ms(100.0, math.nan)

    def test_infinity_raises(self):
        with self.assertRaises(ValueError):
            interval_delta_ms(math.inf, 100.0)
        with self.assertRaises(ValueError):
            interval_delta_ms(100.0, -math.inf)

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            interval_delta_ms(True, 100.0)

    def test_text_raises(self):
        with self.assertRaises(ValueError):
            interval_delta_ms(100.0, "100")


class DescriptiveStatsTests(unittest.TestCase):
    def test_empty(self):
        stats = descriptive_stats([])
        self.assertEqual(stats["count"], 0)
        self.assertIsNone(stats["average"])
        self.assertIsNone(stats["minimum"])
        self.assertIsNone(stats["maximum"])
        self.assertIsNone(stats["stdev"])

    def test_none_entries_are_ignored(self):
        stats = descriptive_stats([None, None])
        self.assertEqual(stats["count"], 0)
        self.assertIsNone(stats["average"])
        self.assertIsNone(stats["minimum"])
        self.assertIsNone(stats["maximum"])
        self.assertIsNone(stats["stdev"])

        mixed = descriptive_stats([None, 1.0, None, 3.0])
        self.assertEqual(mixed["count"], 2)
        self.assertAlmostEqual(mixed["average"], 2.0)
        self.assertEqual(mixed["minimum"], 1.0)
        self.assertEqual(mixed["maximum"], 3.0)
        self.assertAlmostEqual(mixed["stdev"], 1.0)

    def test_single_value_stdev_zero(self):
        stats = descriptive_stats([10.0])
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["average"], 10.0)
        self.assertEqual(stats["minimum"], 10.0)
        self.assertEqual(stats["maximum"], 10.0)
        self.assertEqual(stats["stdev"], 0.0)

    def test_known_population_sequence(self):
        # mean 5, population stdev 2
        stats = descriptive_stats([2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0])
        self.assertEqual(stats["count"], 8)
        self.assertAlmostEqual(stats["average"], 5.0)
        self.assertEqual(stats["minimum"], 2.0)
        self.assertEqual(stats["maximum"], 9.0)
        self.assertAlmostEqual(stats["stdev"], 2.0)

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            descriptive_stats([1.0, math.nan])

    def test_infinity_raises(self):
        with self.assertRaises(ValueError):
            descriptive_stats([1.0, math.inf])
        with self.assertRaises(ValueError):
            descriptive_stats([-math.inf])

    def test_returned_fields_are_measurement_only(self):
        stats = descriptive_stats([2.0, 4.0, 6.0])
        self.assertEqual(tuple(stats.keys()), _STAT_FIELDS)
        for field in _FORBIDDEN_FIELDS:
            self.assertNotIn(field, stats)

    def test_missing_collection_raises(self):
        with self.assertRaises(ValueError):
            descriptive_stats(None)

    def test_bool_entries_raise(self):
        with self.assertRaises(ValueError):
            descriptive_stats([True])
        with self.assertRaises(ValueError):
            descriptive_stats([False])

    def test_text_collection_raises(self):
        with self.assertRaises(ValueError):
            descriptive_stats("10")
        with self.assertRaises(ValueError):
            descriptive_stats("")
        with self.assertRaises(ValueError):
            descriptive_stats(b"10")
        with self.assertRaises(ValueError):
            descriptive_stats(bytearray(b"10"))

    def test_generator_of_numbers_is_supported(self):
        stats = descriptive_stats(x for x in [None, 1.0, 3.0])
        self.assertEqual(stats["count"], 2)
        self.assertAlmostEqual(stats["average"], 2.0)
        self.assertEqual(stats["minimum"], 1.0)
        self.assertEqual(stats["maximum"], 3.0)
        self.assertAlmostEqual(stats["stdev"], 1.0)


class ActualRunDurationTests(unittest.TestCase):
    def test_known_monotonic_span(self):
        self.assertAlmostEqual(actual_run_duration_s(100.000, 162.318), 62.318, places=10)

    def test_missing_start(self):
        self.assertIsNone(actual_run_duration_s(None, 162.318))

    def test_missing_stop(self):
        self.assertIsNone(actual_run_duration_s(100.000, None))

    def test_both_missing(self):
        self.assertIsNone(actual_run_duration_s(None, None))

    def test_stop_before_first_press_raises(self):
        with self.assertRaises(ValueError):
            actual_run_duration_s(162.318, 100.000)

    def test_equal_timestamps_are_zero(self):
        self.assertEqual(actual_run_duration_s(100.0, 100.0), 0.0)

    def test_nan_raises(self):
        with self.assertRaises(ValueError):
            actual_run_duration_s(math.nan, 162.318)
        with self.assertRaises(ValueError):
            actual_run_duration_s(100.0, math.nan)

    def test_infinity_raises(self):
        with self.assertRaises(ValueError):
            actual_run_duration_s(math.inf, 162.318)
        with self.assertRaises(ValueError):
            actual_run_duration_s(100.0, math.inf)
        with self.assertRaises(ValueError):
            actual_run_duration_s(100.0, -math.inf)

    def test_bool_raises(self):
        with self.assertRaises(ValueError):
            actual_run_duration_s(True, 2.0)

    def test_text_raises(self):
        with self.assertRaises(ValueError):
            actual_run_duration_s(1.0, "2")


class NeutralContractTests(unittest.TestCase):
    def test_reference_and_delta_return_plain_numbers(self):
        self.assertIsInstance(reference_interval_ms(10), float)
        self.assertIsInstance(interval_delta_ms(106.42, 100.0), float)
        self.assertIsInstance(actual_run_duration_s(100.0, 162.318), float)


if __name__ == "__main__":
    unittest.main()
