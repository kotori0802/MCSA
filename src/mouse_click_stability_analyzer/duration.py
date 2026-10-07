"""Presentation-only elapsed duration formatting.

Raw measurement data stays in milliseconds. These helpers never parse display
text back into measurement values.
"""
from __future__ import annotations

import math
from typing import Any

MS_PER_HOUR = 3_600_000
MS_PER_MINUTE = 60_000
MS_PER_SECOND = 1_000
MS_PER_DAY = 86_400_000.0
EXCEL_ELAPSED_NUMBER_FORMAT = "[h]:mm:ss.000"
AXIS_SPAN_MINUTE_MS = 60_000.0
AXIS_SPAN_HOUR_MS = 3_600_000.0


def _finite_ms(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def split_elapsed_ms(ms: float) -> tuple[int, int, int, int]:
    """Return (hours, minutes, seconds, milliseconds) with hours unbounded."""
    total = int(round(max(0.0, float(ms))))
    hours, rem = divmod(total, MS_PER_HOUR)
    minutes, rem = divmod(rem, MS_PER_MINUTE)
    seconds, millis = divmod(rem, MS_PER_SECOND)
    return hours, minutes, seconds, millis


def format_elapsed_hms(value_ms: Any) -> str:
    """Exact table/report elapsed: [h]:mm:ss.fff with hours not wrapping at 24."""
    ms = _finite_ms(value_ms)
    if ms is None:
        return ""
    hours, minutes, seconds, millis = split_elapsed_ms(ms)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def format_elapsed_seconds_hms(value_s: Any) -> str:
    """Run-duration display from seconds; same [h]:mm:ss.fff contract."""
    seconds = _finite_ms(value_s)
    if seconds is None:
        return ""
    return format_elapsed_hms(seconds * MS_PER_SECOND)


def excel_elapsed_days(value_ms: Any) -> float | None:
    """Excel serial day fraction: elapsed_ms / 86_400_000."""
    ms = _finite_ms(value_ms)
    if ms is None:
        return None
    return float(ms) / MS_PER_DAY


def format_elapsed_axis_tick(value_ms: float, *, span_ms: float) -> str:
    """Compact elapsed tick label. Coordinates remain milliseconds."""
    ms = float(value_ms)
    horizon = max(0.0, float(span_ms), abs(ms))
    if horizon < AXIS_SPAN_MINUTE_MS:
        seconds = ms / MS_PER_SECOND
        av = abs(seconds)
        if av >= 10:
            return f"{seconds:.1f}"
        if av >= 1:
            return f"{seconds:.1f}"
        return f"{seconds:.2f}"
    hours, minutes, seconds, _millis = split_elapsed_ms(ms)
    if horizon < AXIS_SPAN_HOUR_MS:
        return f"{hours * 60 + minutes}:{seconds:02d}"
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def elapsed_axis_uses_seconds(span_ms: float) -> bool:
    return max(0.0, float(span_ms)) < AXIS_SPAN_MINUTE_MS
