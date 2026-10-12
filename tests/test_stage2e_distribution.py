"""Stage 2E: classification-first Click interval distribution. No Qt."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.completed_result import (
    classified_interval_histogram,
    histogram_observation_count,
    inject_bound_splits,
    interval_histogram_bins,
    paired_interval_histograms,
)
from mouse_click_stability_analyzer.interval_comparison import (
    POSITION_ABOVE,
    POSITION_BELOW,
    POSITION_NOT_COMPARABLE,
    POSITION_WITHIN,
    classify_interval,
)


def _contract(lower: float, upper: float) -> dict:
    return {
        "enabled": True,
        "lower_bound_ms": lower,
        "upper_bound_ms": upper,
        "reference_interval_ms": (lower + upper) / 2.0,
        "basis": "ms",
        "configured_value": (upper - lower) / 2.0,
        "tolerance_ms": (upper - lower) / 2.0,
        "tolerance_pct": None,
    }


def _signature(bins):
    return [(float(b["lo"]), float(b["hi"]), int(b["count"]), b.get("position")) for b in bins]


class BoundSplitTests(unittest.TestCase):
    def test_injects_lower_and_upper_into_intersected_bins(self):
        edges = [(240.0, 280.0), (280.0, 320.0), (320.0, 420.0)]
        split = inject_bound_splits(edges, 266.67, 400.0)
        points = [split[0][0]] + [hi for _lo, hi in split]
        self.assertIn(266.67, points)
        self.assertIn(400.0, points)
        for lo, hi in split:
            self.assertGreater(hi, lo)
            self.assertFalse(lo < 266.67 < hi)
            self.assertFalse(lo < 400.0 < hi)


class ClassificationFirstHistogramTests(unittest.TestCase):
    def setUp(self):
        self.lower = 266.67
        self.upper = 400.00
        self.contract = _contract(self.lower, self.upper)
        self.values = [200.0, 266.67, 300.0, 400.0, 450.0]

    def test_exact_bounds_are_within(self):
        self.assertEqual(classify_interval(self.lower, self.contract), POSITION_WITHIN)
        self.assertEqual(classify_interval(self.upper, self.contract), POSITION_WITHIN)
        self.assertEqual(classify_interval(200.0, self.contract), POSITION_BELOW)
        self.assertEqual(classify_interval(300.0, self.contract), POSITION_WITHIN)
        self.assertEqual(classify_interval(450.0, self.contract), POSITION_ABOVE)
        self.assertEqual(classify_interval(None, self.contract), POSITION_NOT_COMPARABLE)

    def test_counts_sum_to_comparable(self):
        bins = classified_interval_histogram(self.values, self.contract)
        positions = [classify_interval(value, self.contract) for value in self.values]
        below = positions.count(POSITION_BELOW)
        within = positions.count(POSITION_WITHIN)
        above = positions.count(POSITION_ABOVE)
        self.assertEqual(below + within + above, 5)
        self.assertEqual(histogram_observation_count(bins), 5)
        by_pos = {POSITION_BELOW: 0, POSITION_WITHIN: 0, POSITION_ABOVE: 0}
        for item in bins:
            by_pos[item["position"]] += int(item["count"])
        self.assertEqual(by_pos[POSITION_BELOW], below)
        self.assertEqual(by_pos[POSITION_WITHIN], within)
        self.assertEqual(by_pos[POSITION_ABOVE], above)

    def test_classified_bar_does_not_mix_below_with_within(self):
        bins = classified_interval_histogram(self.values, self.contract)
        for item in bins:
            lo, hi, position = float(item["lo"]), float(item["hi"]), item["position"]
            if position == POSITION_BELOW:
                self.assertLessEqual(hi, self.lower)
            elif position == POSITION_WITHIN:
                self.assertGreaterEqual(lo, self.lower)
                self.assertLessEqual(hi, self.upper)
            elif position == POSITION_ABOVE:
                self.assertGreaterEqual(lo, self.upper)
            members = [
                v for v in self.values
                if classify_interval(v, self.contract) == position and lo <= v <= hi
            ]
            self.assertTrue(all(classify_interval(v, self.contract) == position for v in members))

    def test_disabled_is_neutral_and_keeps_all_comparable(self):
        bins = classified_interval_histogram(self.values, {"enabled": False})
        self.assertEqual(bins, interval_histogram_bins(self.values))
        self.assertTrue(all("position" not in item for item in bins))
        self.assertEqual(histogram_observation_count(bins), 5)

    def test_first_press_absent_interval_is_excluded(self):
        values = [None, 200.0, 300.0]
        finite = [200.0, 300.0]
        bins = classified_interval_histogram([v for v in values if v is not None], self.contract)
        self.assertEqual(histogram_observation_count(bins), 2)
        self.assertEqual(histogram_observation_count(bins), len(finite))


class OverlayHistogramSafetyTests(unittest.TestCase):
    def test_overlay_is_not_classified_with_current_range(self):
        a_contract = _contract(100.0, 150.0)
        current = [145.0]
        overlay = [145.0]
        cur, ov = paired_interval_histograms(current, overlay, contract=a_contract)
        self.assertTrue(all(item.get("position") == POSITION_WITHIN for item in cur if item["count"]))
        self.assertTrue(all(item.get("position") is None for item in ov))
        self.assertEqual(histogram_observation_count(ov), 1)

    def test_paired_without_contract_matches_plain_histogram(self):
        current = [10.0, 12.0, 11.0, 13.0]
        solo, empty = paired_interval_histograms(current, [])
        self.assertEqual(empty, [])
        self.assertEqual(solo, interval_histogram_bins(current))


class NavigationDoesNotRebinTests(unittest.TestCase):
    def test_model_is_independent_of_viewport_arguments(self):
        contract = _contract(266.67, 400.0)
        values = [200.0, 266.67, 300.0, 400.0, 450.0, 2000.0]
        first = _signature(classified_interval_histogram(values, contract))
        again = _signature(classified_interval_histogram(values, contract))
        self.assertEqual(first, again)
        self.assertEqual(histogram_observation_count(classified_interval_histogram(values, contract)), 6)


if __name__ == "__main__":
    unittest.main()
