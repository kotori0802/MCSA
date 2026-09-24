"""Neutral observed-Press vs expected-fixture-slot matching.

Measurement Workbench comparison only:

- COMPARE host-observed Press times against the expected fixture schedule
- Uses ONLY an explicit tester-configured ±X ms timing tolerance
- Does NOT classify Missing / Extra / Double Click
- Does NOT produce Spec PASS / FAIL, health, diagnosis, or scores
- Does NOT use legacy cadence ratios (0.72 / 1.35) or nearest-slot fallback

Expected geometry is owned by ``fixture_schedule``:

    expected slot k at 1000 * k / F milliseconds
    include k iff k / F < capture_duration_s

Public expected times are the same Python float values published by
``iter_expected_fixture_slots_relative_ms``. High-precision Decimal
arithmetic is used only to derive candidate indexes. Final inclusive
tolerance checks, returned ``expected_time_ms``, and ``delta_ms`` all use
that ONE published float representation.

Matching rule (inclusive, no hidden epsilon):

    abs(observed_ms - published_expected_ms(k)) <= timing_tolerance_ms

Invariant for uniquely MATCHED observations:

    delta_ms == observed_time_ms - slots[k].expected_time_ms
    abs(delta_ms) <= timing_tolerance_ms

Assignment:

- exactly one candidate slot → uniquely MATCHED to that slot
- zero candidates → UNMATCHED
- two or more candidates → AMBIGUOUS (never auto-resolved)

Occupancy counts uniquely MATCHED observations only.
AMBIGUOUS / UNMATCHED / OUTSIDE_CAPTURE_WINDOW do not occupy slots.

Capture window for observations (milliseconds):

    0 <= observed_ms < capture_duration_s * 1000

observed_ms >= capture duration → OUTSIDE_CAPTURE_WINDOW (not invalid).
Negative observed times are invalid and are rejected.

Session-anchor limitation (V2 Qt today):
t0 is the first accepted host-observed fixture Press. The matcher compares
relative Press times against a schedule anchored at that t0. Physical fixture
strokes before t0 are not represented and cannot be claimed as missed here.

Recommend future callers pass Qt ``press_elapsed_ms`` (relative to first
accepted Press). This module does not read Qt events itself.
"""
from __future__ import annotations

import math
import numbers
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from mouse_click_stability_analyzer.fixture_schedule import (
    expected_fixture_slot_count,
    fixture_reference_interval_ms,
)

_TEXT_TYPES = (str, bytes, bytearray)

STATUS_MATCHED = "MATCHED"
STATUS_UNMATCHED = "UNMATCHED"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_OUTSIDE_CAPTURE_WINDOW = "OUTSIDE_CAPTURE_WINDOW"

_MS_PER_SECOND = Decimal(1000)


class FixtureMatchingError(ValueError):
    """Invalid fixture matching inputs."""


def _as_finite_number(value: Any, *, name: str) -> float:
    if isinstance(value, bool) or isinstance(value, _TEXT_TYPES):
        raise FixtureMatchingError(f"{name} must be a finite number")
    if not isinstance(value, numbers.Real):
        raise FixtureMatchingError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise FixtureMatchingError(f"{name} must be a finite number")
    return number


def _as_decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _as_non_negative_tolerance_ms(value: Any) -> float:
    number = _as_finite_number(value, name="timing_tolerance_ms")
    if number < 0.0:
        raise FixtureMatchingError("timing_tolerance_ms must be a finite non-negative number")
    return number


def _as_non_negative_observed_ms(value: Any, *, name: str) -> float:
    number = _as_finite_number(value, name=name)
    if number < 0.0:
        raise FixtureMatchingError(f"{name} must be a finite non-negative number")
    return number


def _ceil_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _floor_int(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _published_expected_time_ms(slot_index: int, hz_d: Decimal) -> float:
    """Same float publication path as fixture_schedule relative slots."""
    return float((Decimal(slot_index) / hz_d) * _MS_PER_SECOND)


def _candidate_slot_indexes(
    observed_ms_d: Decimal,
    tolerance_ms_d: Decimal,
    hz_d: Decimal,
    published_expected_ms: list[float],
) -> list[int]:
    """Integer k with |obs - published_expected(k)| <= tol.

    Candidate index range is derived from schedule regularity using Decimal.
    Final inclusive verification uses only the published float expected times.
    """
    slot_count = len(published_expected_ms)
    if slot_count <= 0:
        return []
    span = tolerance_ms_d * hz_d / _MS_PER_SECOND
    center = observed_ms_d * hz_d / _MS_PER_SECOND
    k_lo = max(0, _ceil_int(center - span) - 1)
    k_hi = min(slot_count - 1, _floor_int(center + span) + 1)
    if k_lo > k_hi:
        return []
    matched: list[int] = []
    for k in range(k_lo, k_hi + 1):
        published_d = _as_decimal(published_expected_ms[k])
        if abs(observed_ms_d - published_d) <= tolerance_ms_d:
            matched.append(k)
    return matched


def match_fixture_press_observations(
    capture_duration_s: Any,
    fixture_frequency_hz: Any,
    timing_tolerance_ms: Any,
    observed_press_times_ms: Any,
) -> dict[str, Any]:
    """Compare host-observed Press times to the expected fixture schedule.

    ``observed_press_times_ms`` is a sequence of relative-to-t0 Press times.
    Original order is preserved via ``observation_index``.
    """
    slot_count = expected_fixture_slot_count(capture_duration_s, fixture_frequency_hz)
    reference_interval_ms = fixture_reference_interval_ms(fixture_frequency_hz)
    duration_s = _as_decimal(_as_finite_number(capture_duration_s, name="capture_duration_s"))
    hz = _as_finite_number(fixture_frequency_hz, name="fixture_frequency_hz")
    hz_d = _as_decimal(hz)
    tolerance = _as_non_negative_tolerance_ms(timing_tolerance_ms)
    tolerance_d = _as_decimal(tolerance)
    duration_ms_d = duration_s * _MS_PER_SECOND
    published_expected_ms = [_published_expected_time_ms(k, hz_d) for k in range(slot_count)]

    if observed_press_times_ms is None or isinstance(observed_press_times_ms, _TEXT_TYPES):
        raise FixtureMatchingError("observed_press_times_ms must be an iterable of numbers")
    try:
        raw_observations = list(observed_press_times_ms)
    except TypeError as exc:
        raise FixtureMatchingError("observed_press_times_ms must be an iterable of numbers") from exc

    observations: list[dict[str, Any]] = []
    occupancy: list[list[int]] = [[] for _ in range(slot_count)]

    for index, raw in enumerate(raw_observations):
        observed = _as_non_negative_observed_ms(raw, name=f"observed_press_times_ms[{index}]")
        observed_d = _as_decimal(observed)
        observed_f = float(observed_d)
        record: dict[str, Any] = {
            "observation_index": index,
            "observed_time_ms": observed_f,
            "status": STATUS_UNMATCHED,
            "slot_index": None,
            "candidate_slot_indexes": [],
            "delta_ms": None,
        }
        if observed_d >= duration_ms_d:
            record["status"] = STATUS_OUTSIDE_CAPTURE_WINDOW
            observations.append(record)
            continue
        candidates = _candidate_slot_indexes(
            observed_d,
            tolerance_d,
            hz_d,
            published_expected_ms,
        )
        record["candidate_slot_indexes"] = list(candidates)
        if len(candidates) == 1:
            k = candidates[0]
            expected_f = published_expected_ms[k]
            record["status"] = STATUS_MATCHED
            record["slot_index"] = k
            record["delta_ms"] = float(observed_d - _as_decimal(expected_f))
            occupancy[k].append(index)
        elif len(candidates) > 1:
            record["status"] = STATUS_AMBIGUOUS
        observations.append(record)

    slots: list[dict[str, Any]] = []
    empty = single = multi = 0
    for k in range(slot_count):
        expected_f = published_expected_ms[k]
        assigned = occupancy[k]
        n = len(assigned)
        if n == 0:
            empty += 1
        elif n == 1:
            single += 1
        else:
            multi += 1
        observed_times = [observations[i]["observed_time_ms"] for i in assigned]
        deltas = [observations[i]["delta_ms"] for i in assigned]
        slots.append(
            {
                "slot_index": k,
                "expected_time_ms": expected_f,
                "occupancy": n,
                "observation_indexes": list(assigned),
                "observed_times_ms": observed_times,
                "delta_ms": deltas,
            }
        )

    matched_n = sum(1 for o in observations if o["status"] == STATUS_MATCHED)
    unmatched_n = sum(1 for o in observations if o["status"] == STATUS_UNMATCHED)
    ambiguous_n = sum(1 for o in observations if o["status"] == STATUS_AMBIGUOUS)
    outside_n = sum(1 for o in observations if o["status"] == STATUS_OUTSIDE_CAPTURE_WINDOW)

    overlap_possible = (Decimal(2) * tolerance_d) >= _as_decimal(reference_interval_ms)

    return {
        "capture_duration_s": float(duration_s),
        "fixture_frequency_hz": hz,
        "timing_tolerance_ms": float(tolerance_d),
        "reference_interval_ms": reference_interval_ms,
        "expected_slot_count": slot_count,
        "matching_windows_can_overlap": overlap_possible,
        "slots": slots,
        "observations": observations,
        "empty_slot_count": empty,
        "single_occupancy_slot_count": single,
        "multi_occupancy_slot_count": multi,
        "matched_observation_count": matched_n,
        "unmatched_observation_count": unmatched_n,
        "ambiguous_observation_count": ambiguous_n,
        "outside_capture_window_count": outside_n,
    }
