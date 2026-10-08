"""W-independent nearest-slot residual math.

Schedule Association Window W is never an input. Configured Interval Range
is never an input. Python ``round()`` is not used (banker's rounding would
mis-assign the exact +T/2 boundary).
"""
from __future__ import annotations

import math
import statistics
from decimal import ROUND_FLOOR, Decimal
from typing import Any

from ..core import percentile
from ..fixture_schedule import (
    expected_fixture_slot_count,
    fixture_reference_interval_ms,
    iter_expected_fixture_slots_relative_ms,
)

RESIDUAL_RANGE_NOTE = "[-T/2, T/2)"
HALF_OPEN_TIE = (
    "k = floor(t_rel_ms / T_ms + 1/2); residual = t_rel_ms - k * T_ms. "
    "Exact +T/2 maps to the later slot so residual = -T/2. "
    "Guaranteed range is [-T/2, T/2)."
)


class CharacterizationMathError(ValueError):
    """Invalid residual-math input."""


def _finite(value: Any, *, name: str) -> float:
    if value is None or isinstance(value, bool):
        raise CharacterizationMathError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CharacterizationMathError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise CharacterizationMathError(f"{name} must be a finite number")
    return number


def reference_interval_ms(fixture_reference_hz: Any) -> float:
    """T_ms = 1000 / F from the frozen evidence Fixture Reference Rate."""
    return fixture_reference_interval_ms(fixture_reference_hz)


def duration_window_ms(duration_sec: Any) -> float:
    duration = _finite(duration_sec, name="duration_sec")
    if duration <= 0:
        raise CharacterizationMathError("duration_sec must be a finite positive number")
    return duration * 1000.0


def in_configured_window(t_rel_ms: float, duration_window_ms: float) -> bool:
    """Primary sample uses a strict upper bound: 0 <= t_rel_ms < duration_ms."""
    return 0.0 <= t_rel_ms < duration_window_ms


def nearest_slot(t_rel_ms: Any, period_ms: Any) -> dict[str, float | int]:
    """Assign t to the nearest nominal slot with deterministic +T/2 tie-break.

    For t_rel_ms >= 0:

        k = floor(t / T + 1/2)
        residual_ms = t - k * T

    Exact +T/2 is assigned to the later slot, yielding residual = -T/2.
    """
    t = _finite(t_rel_ms, name="t_rel_ms")
    period = _finite(period_ms, name="period_ms")
    if t < 0:
        raise CharacterizationMathError("t_rel_ms must be >= 0")
    if period <= 0:
        raise CharacterizationMathError("period_ms must be a finite positive number")
    t_d = Decimal(str(t))
    t_period = Decimal(str(period))
    k = int((t_d / t_period + Decimal("0.5")).to_integral_value(rounding=ROUND_FLOOR))
    residual = t_d - (Decimal(k) * t_period)
    half = t_period / Decimal(2)
    if residual >= half:
        k += 1
        residual -= t_period
    elif residual < -half:
        k -= 1
        residual += t_period
    residual_f = float(residual)
    nominal = float(Decimal(k) * t_period)
    return {
        "nearest_slot_index": k,
        "nominal_slot_time_ms": nominal,
        "wrapped_residual_ms": residual_f,
        "absolute_residual_ms": abs(residual_f),
        "boundary_distance_ms": boundary_distance_ms(residual_f, period),
    }


def boundary_distance_ms(wrapped_residual_ms: Any, period_ms: Any) -> float:
    """T/2 - |residual|. Near 0 means near the adjacent-slot midpoint."""
    residual = _finite(wrapped_residual_ms, name="wrapped_residual_ms")
    period = _finite(period_ms, name="period_ms")
    if period <= 0:
        raise CharacterizationMathError("period_ms must be a finite positive number")
    return float(Decimal(str(period)) / Decimal(2) - Decimal(str(abs(residual))))


def residual_in_half_open_range(wrapped_residual_ms: float, period_ms: float) -> bool:
    half = period_ms / 2.0
    return -half <= wrapped_residual_ms < half


def descriptive_signed(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "minimum": None,
            "maximum": None,
            "stdev": None,
        }
    return {
        "count": len(values),
        "mean": float(statistics.mean(values)),
        "median": percentile(values, 50),
        "minimum": min(values),
        "maximum": max(values),
        "stdev": float(statistics.pstdev(values)) if len(values) > 1 else 0.0,
    }


def descriptive_absolute(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "count": 0,
            "median": None,
            "p90": None,
            "p95": None,
            "p99": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "median": percentile(values, 50),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "maximum": max(values),
    }


def descriptive_boundary(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "minimum": None, "median": None}
    return {
        "count": len(values),
        "minimum": min(values),
        "median": percentile(values, 50),
    }


def ecdf_absolute(values: list[float]) -> list[dict[str, float]]:
    """Empirical CDF of |residual|. Point i has cumulative_fraction (i+1)/n.

    Uses the project linear-interpolation percentile for summaries; the ECDF
    itself is the sorted sample with rank/(n) plotting positions. Descriptive
    only; not a window-policy output.
    """
    ordered = sorted(abs(v) for v in values)
    n = len(ordered)
    if n == 0:
        return []
    return [
        {"absolute_residual_ms": value, "cumulative_fraction": (index + 1) / n}
        for index, value in enumerate(ordered)
    ]


def fraction_within_ms(absolute_values: list[float], width_ms: float | None) -> float | None:
    """Share of |residual| <= width. Context only; not a pass rate."""
    if width_ms is None or not math.isfinite(width_ms) or width_ms < 0 or not absolute_values:
        return None
    inside = sum(1 for value in absolute_values if value <= width_ms)
    return inside / len(absolute_values)


def nominal_slot_times_ms(duration_sec: Any, fixture_reference_hz: Any) -> list[float]:
    return list(iter_expected_fixture_slots_relative_ms(duration_sec, fixture_reference_hz))


def nominal_slot_count(duration_sec: Any, fixture_reference_hz: Any) -> int:
    return expected_fixture_slot_count(duration_sec, fixture_reference_hz)


def occupancy_summary(slot_counts: list[int]) -> dict[str, int]:
    occupied = sum(1 for count in slot_counts if count > 0)
    empty = sum(1 for count in slot_counts if count == 0)
    single = sum(1 for count in slot_counts if count == 1)
    multiple = sum(1 for count in slot_counts if count > 1)
    return {
        "nominal_slot_count": len(slot_counts),
        "occupied_slot_count": occupied,
        "empty_slot_count": empty,
        "slots_with_one_observation": single,
        "slots_with_multiple_observations": multiple,
    }


def tertile_edges_ms(duration_window_ms: float) -> tuple[float, float, float, float]:
    third = duration_window_ms / 3.0
    return (0.0, third, 2.0 * third, duration_window_ms)


def tertile_name(t_rel_ms: float, duration_window_ms: float) -> str:
    _lo, a, b, hi = tertile_edges_ms(duration_window_ms)
    if t_rel_ms < a:
        return "early"
    if t_rel_ms < b:
        return "middle"
    if t_rel_ms < hi:
        return "late"
    return "outside"
