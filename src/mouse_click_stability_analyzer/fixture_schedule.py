"""Deterministic expected fixture stroke schedule for a configured capture duration.

Measurement Workbench foundation only:

- RECORD / CALCULATE schedule geometry from Fixture Frequency
- Does NOT match clicks to slots
- Does NOT classify Missing / Extra / Double Click
- Does NOT produce Spec PASS / FAIL
- Does NOT apply timing tolerance or legacy cadence ratios (0.72 / 1.35)

Capture window is half-open relative to the session anchor t0:

    [0, capture_duration_s)

Expected relative slot times:

    t_k = k / F   (seconds), for integer k >= 0

Include slot k iff:

    t_k < capture_duration_s

A slot exactly equal to the configured duration is excluded.

Authoritative geometry inputs:

- capture_duration_s   (tester-authored configured duration)
- fixture_frequency_hz (tester-authored Fixture Frequency)

Do NOT reconstruct configured duration by subtracting two independently
serialized absolute monotonic endpoints (``end - start``). That can invent
extra float noise (e.g. 10.00000000000001) and corrupt expected slot counts.

Runtime cutoff helper:

- scheduled_end_monotonic_s(start, capture_duration_s) = start + duration

Absolute monotonic slot iteration uses start plus the same relative geometry.
Relative schedules and counts depend only on (duration, frequency), never on
the absolute magnitude of start.

Session-anchor limitation (V2 Qt today):
When the capture window is anchored at the first accepted host-observed
fixture press (t0), this schedule describes expected strokes from that
anchor forward only. Fixture strokes that may have occurred before t0
are outside the represented window and cannot be claimed as detected or
missed by this foundation.
"""
from __future__ import annotations

import math
import numbers
from collections.abc import Iterator
from decimal import Decimal, ROUND_FLOOR
from typing import Any

_TEXT_TYPES = (str, bytes, bytearray)


class FixtureScheduleError(ValueError):
    """Invalid fixture schedule inputs."""


def _as_finite_number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or isinstance(value, _TEXT_TYPES):
        raise FixtureScheduleError(f"{name} must be a finite number")
    if not isinstance(value, numbers.Real):
        raise FixtureScheduleError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise FixtureScheduleError(f"{name} must be a finite number")
    return number


def _as_positive_frequency_hz(value: Any) -> float:
    hz = _as_finite_number(value, name="fixture_frequency_hz")
    if hz <= 0.0:
        raise FixtureScheduleError("fixture_frequency_hz must be a finite positive number")
    return hz


def _as_positive_duration_s(value: Any) -> float:
    duration = _as_finite_number(value, name="capture_duration_s")
    if duration <= 0.0:
        raise FixtureScheduleError("capture_duration_s must be a finite positive number")
    return duration


def _as_decimal(value: float) -> Decimal:
    # Prefer decimal text form so exact user decimals (e.g. 7.5, 10.001) stay
    # exact when they round-trip cleanly through float→str. Schedule geometry
    # always multiplies configured duration × frequency — never (end - start).
    return Decimal(str(value))


def _count_from_ratio(ratio: Decimal) -> int:
    """Count integers k >= 0 with k < ratio (half-open index space).

    No hidden floating epsilon: exact integer ratios use floor(ratio) slots
    (k = 0 .. n-1 when ratio == n). Non-integer ratios include k = floor(ratio).
    """
    if ratio <= 0:
        return 0
    floored = int(ratio.to_integral_value(rounding=ROUND_FLOOR))
    if ratio == Decimal(floored):
        return floored
    return floored + 1


def _duration_hz_ratio(capture_duration_s: float, fixture_frequency_hz: float) -> Decimal:
    """Authoritative ratio: configured_duration * frequency."""
    return _as_decimal(capture_duration_s) * _as_decimal(fixture_frequency_hz)


def fixture_period_s(fixture_frequency_hz: Any) -> float:
    """Return the nominal fixture stroke period in seconds: 1 / F."""
    hz = _as_positive_frequency_hz(fixture_frequency_hz)
    return float(Decimal(1) / _as_decimal(hz))


def fixture_reference_interval_ms(fixture_frequency_hz: Any) -> float:
    """Return the nominal reference interval in milliseconds: 1000 / F."""
    return fixture_period_s(fixture_frequency_hz) * 1000.0


def scheduled_end_monotonic_s(
    start_monotonic_s: Any,
    capture_duration_s: Any,
) -> float:
    """Runtime cutoff: start + configured duration (float add for wall cutoff).

    Schedule geometry/count must still use capture_duration_s directly, not
    ``scheduled_end - start``.
    """
    start = _as_finite_number(start_monotonic_s, name="start_monotonic_s")
    duration = _as_positive_duration_s(capture_duration_s)
    return start + duration


def expected_fixture_slot_count(
    capture_duration_s: Any,
    fixture_frequency_hz: Any,
) -> int:
    """Return how many expected fixture slots lie in [0, capture_duration_s).

    Deterministic from (configured duration, frequency) only. Independent of
    absolute perf_counter start magnitude. Does not use GUI elapsed text,
    QTimer latency, ``end - start``, or ``round(duration * hz)``.
    """
    duration = _as_positive_duration_s(capture_duration_s)
    hz = _as_positive_frequency_hz(fixture_frequency_hz)
    return _count_from_ratio(_duration_hz_ratio(duration, hz))


def iter_expected_fixture_slots_relative_ms(
    capture_duration_s: Any,
    fixture_frequency_hz: Any,
) -> Iterator[float]:
    """Yield relative slot times in milliseconds: ``1000 * k / F``, k with t_k < duration.

    First slot is always 0. Independent of absolute monotonic start.
    """
    duration = _as_positive_duration_s(capture_duration_s)
    hz = _as_positive_frequency_hz(fixture_frequency_hz)
    hz_d = _as_decimal(hz)
    count = _count_from_ratio(_duration_hz_ratio(duration, hz))
    for k in range(count):
        yield float((Decimal(k) / hz_d) * Decimal(1000))


def iter_expected_fixture_slots_monotonic_s(
    start_monotonic_s: Any,
    capture_duration_s: Any,
    fixture_frequency_hz: Any,
) -> Iterator[float]:
    """Yield absolute monotonic slot times: ``start + k / F`` for included k.

    Slot membership uses configured duration (relative geometry), not a
    reconstructed ``end - start`` duration.
    """
    start = _as_finite_number(start_monotonic_s, name="start_monotonic_s")
    duration = _as_positive_duration_s(capture_duration_s)
    hz = _as_positive_frequency_hz(fixture_frequency_hz)
    start_d = _as_decimal(start)
    hz_d = _as_decimal(hz)
    count = _count_from_ratio(_duration_hz_ratio(duration, hz))
    for k in range(count):
        yield float(start_d + (Decimal(k) / hz_d))
