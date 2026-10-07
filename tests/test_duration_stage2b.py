"""Stage 2B: elapsed duration presentation helpers. Raw milliseconds stay authoritative."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mouse_click_stability_analyzer.duration import (
    EXCEL_ELAPSED_NUMBER_FORMAT,
    excel_elapsed_days,
    format_elapsed_axis_tick,
    format_elapsed_hms,
    format_elapsed_seconds_hms,
)

RUN_DURATION_CASES = (
    (20.1, "00:00:20.100"),
    (3600.0, "01:00:00.000"),
    (93_784.567, "26:03:04.567"),
)


class ElapsedFormatterTests(unittest.TestCase):
    def test_exact_table_format(self):
        cases = (
            (0, "00:00:00.000"),
            (18_006, "00:00:18.006"),
            (65_000, "00:01:05.000"),
            (3_600_000, "01:00:00.000"),
            (3_661_250, "01:01:01.250"),
            (93_784_567, "26:03:04.567"),
        )
        for ms, expected in cases:
            with self.subTest(ms=ms):
                self.assertEqual(format_elapsed_hms(ms), expected)

    def test_millisecond_precision_and_none(self):
        self.assertEqual(format_elapsed_hms(1), "00:00:00.001")
        self.assertEqual(format_elapsed_hms(None), "")
        self.assertEqual(format_elapsed_hms(float("nan")), "")

    def test_run_duration_from_seconds(self):
        for seconds, expected in RUN_DURATION_CASES:
            with self.subTest(seconds=seconds):
                self.assertEqual(format_elapsed_seconds_hms(seconds), expected)
        self.assertEqual(format_elapsed_seconds_hms(None), "")
        self.assertEqual(format_elapsed_seconds_hms(float("inf")), "")

    def test_excel_days_and_format(self):
        self.assertEqual(EXCEL_ELAPSED_NUMBER_FORMAT, "[h]:mm:ss.000")
        self.assertEqual(excel_elapsed_days(0), 0.0)
        self.assertEqual(excel_elapsed_days(86_400_000), 1.0)
        self.assertTrue(math.isclose(excel_elapsed_days(18_006), 18_006 / 86_400_000.0, rel_tol=0, abs_tol=1e-18))
        self.assertTrue(math.isclose(excel_elapsed_days(93_784_567), 93_784_567 / 86_400_000.0, rel_tol=0, abs_tol=1e-18))
        self.assertIsNone(excel_elapsed_days(None))

    def test_axis_ticks_short_medium_long(self):
        self.assertEqual(format_elapsed_axis_tick(6_400, span_ms=20_000), "6.4")
        self.assertEqual(format_elapsed_axis_tick(8_000, span_ms=20_000), "8.0")
        self.assertEqual(format_elapsed_axis_tick(90_000, span_ms=120_000), "1:30")
        self.assertEqual(format_elapsed_axis_tick(3_661_000, span_ms=4_000_000), "1:01:01")
        self.assertEqual(format_elapsed_axis_tick(3_600_000, span_ms=3_599_000), "1:00:00")
        self.assertEqual(format_elapsed_axis_tick(93_784_567, span_ms=100_000_000), "26:03:04")


if __name__ == "__main__":
    unittest.main()
