"""Neutral arithmetic helpers for recorded click timing values.

These functions operate on already-paired numeric measurements
(press interval, hold duration, monotonic timestamps). They do not
pair host input events or apply product comparison limits.
"""
from __future__ import annotations

import math
import numbers
import statistics
from typing import Any

_MS_PER_SECOND = 1000.0
_TEXT_TYPES = (str, bytes, bytearray)


def _as_optional_finite_float(value: Any, *, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or isinstance(value, _TEXT_TYPES):
        raise ValueError(f"{name} must be a finite number")
    if not isinstance(value, numbers.Real):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _as_finite_float(value: Any, *, name: str) -> float:
    number = _as_optional_finite_float(value, name=name)
    if number is None:
        raise ValueError(f"{name} must be a finite number")
    return number


def reference_interval_ms(reference_rate_hz: Any) -> float | None:
    """Convert a configured reference rate (Hz) to an interval in milliseconds.

    None means no reference rate is configured.
    A non-positive or non-finite rate is a configuration error.
    """
    if reference_rate_hz is None:
        return None
    hz = _as_finite_float(reference_rate_hz, name="reference_rate_hz")
    if hz <= 0.0:
        raise ValueError("reference_rate_hz must be a finite positive number")
    return _MS_PER_SECOND / hz


def interval_delta_ms(
    observed_interval_ms: Any,
    reference_interval_ms_value: Any,
) -> float | None:
    """Return observed press interval minus the configured reference interval.

    None in either argument means the comparison is not configured or not
    available. Non-finite numbers are a data error.
    """
    observed = _as_optional_finite_float(observed_interval_ms, name="observed_interval_ms")
    reference = _as_optional_finite_float(
        reference_interval_ms_value, name="reference_interval_ms_value"
    )
    if observed is None or reference is None:
        return None
    return observed - reference


def descriptive_stats(values: Any) -> dict[str, Any]:
    """Return count, average, minimum, maximum, and population stdev.

    None entries are ignored (for example a first click with no prior interval).
    An empty series after ignoring None has count 0 and None summaries.
    A missing collection (None) is a caller error.
    Text scalars are not treated as sequences of measurements.
    A single finite value has stdev 0.0.
    Non-finite numbers are a data error and are not dropped.
    """
    if values is None or isinstance(values, _TEXT_TYPES):
        raise ValueError("values must be an iterable of numbers")
    try:
        series = list(values)
    except TypeError as exc:
        raise ValueError("values must be an iterable of numbers") from exc

    finite: list[float] = []
    for index, item in enumerate(series):
        if item is None:
            continue
        finite.append(_as_finite_float(item, name=f"values[{index}]"))

    if not finite:
        return {
            "count": 0,
            "average": None,
            "minimum": None,
            "maximum": None,
            "stdev": None,
        }

    count = len(finite)
    if count == 1:
        value = finite[0]
        return {
            "count": 1,
            "average": value,
            "minimum": value,
            "maximum": value,
            "stdev": 0.0,
        }

    return {
        "count": count,
        "average": statistics.mean(finite),
        "minimum": min(finite),
        "maximum": max(finite),
        "stdev": statistics.pstdev(finite),
    }


def actual_run_duration_s(
    first_accepted_press_monotonic_s: Any,
    stop_monotonic_s: Any,
) -> float | None:
    """Return how long the run was active in seconds.

    Start is the monotonic time of the first accepted target-button press.
    End is the monotonic time of explicit Stop (or a future auto-stop).
    Either missing timestamp means duration is not available.
    A stop earlier than the first press is a data error.
    """
    start = _as_optional_finite_float(
        first_accepted_press_monotonic_s,
        name="first_accepted_press_monotonic_s",
    )
    stop = _as_optional_finite_float(stop_monotonic_s, name="stop_monotonic_s")
    if start is None or stop is None:
        return None
    if stop < start:
        raise ValueError("stop_monotonic_s must be greater than or equal to first_accepted_press_monotonic_s")
    return stop - start
