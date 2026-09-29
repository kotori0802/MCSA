"""Neutral host-only evidence summary against the configured fixture schedule.

Answers only: what did the Host observe relative to the configured schedule?

Composes accepted foundations without re-implementing them:

- ``fixture_schedule``  expected slot geometry and count
- ``fixture_matching``  ±X timing-window matching and slot occupancy
- ``measurements``      descriptive statistics (population stdev)

This module does NOT classify Missing / Double / Extra Click, switch bounce,
or hardware faults, and produces no PASS / FAIL, warning, severity, or score.
An empty expected slot is not a physical missed stroke, and multiple host
observations in one expected window are not a physical double click; no
independent fixture stroke signal exists to establish either.

Count semantics:

- raw_host_press_count: every supplied host Press observation, including
  observations at or after the configured capture duration
- in_window_host_press_count: observations with 0 <= t < capture duration
- expected_slot_count: from ``fixture_schedule`` only (configured duration
  is authoritative; never actual elapsed time x frequency)
- host_count_delta_vs_expected_slots: in-window count minus expected slots

A count delta of zero does not remove empty, multi-occupancy, unmatched, or
ambiguous evidence; compensating differences can net to zero.

A configured capture duration is required. Runs without one (for example
Qt Auto Stop OFF) have no expected slot count and should not call this.

Host-only t0 anchor contract: t0 is the first accepted host-observed fixture
Press, so a valid observation set is non-empty and contains an observation
at exactly 0.0 ms (Qt ``press_elapsed_ms`` of the first accepted Press).
Input is never rebased and no synthetic anchor is inserted. Order is not
required; only presence of the 0.0 ms anchor. This rule belongs to the
Host-only mode; ``fixture_matching`` stays anchor-agnostic.

The anchor only means the first HOST observation defines schedule t0. The
summary cannot tell whether a physical fixture stroke occurred before t0 or
whether the first physical stroke was missed.
"""
from __future__ import annotations

from typing import Any

from mouse_click_stability_analyzer.fixture_matching import (
    STATUS_MATCHED,
    match_fixture_press_observations,
)
from mouse_click_stability_analyzer.measurements import descriptive_stats


class HostEvidenceError(ValueError):
    """Observations violate the Host-only first-Press t0 anchor contract."""


def build_fixture_host_evidence(
    capture_duration_s: Any,
    fixture_frequency_hz: Any,
    timing_tolerance_ms: Any,
    observed_press_times_ms: Any,
) -> dict[str, Any]:
    """Summarize host-observed Press times against the expected fixture schedule.

    ``observed_press_times_ms`` are relative-to-t0 Press times (future Qt
    source: ``press_elapsed_ms``) and must include the 0.0 ms t0 anchor;
    otherwise ``HostEvidenceError``. The input is consumed once, by the matcher.
    Per-slot and per-observation detail is available from
    ``match_fixture_press_observations`` directly.
    """
    matching = match_fixture_press_observations(
        capture_duration_s,
        fixture_frequency_hz,
        timing_tolerance_ms,
        observed_press_times_ms,
    )

    observations = matching["observations"]
    if not observations:
        raise HostEvidenceError("no host Press observations: first-Press t0 anchor does not exist")
    if not any(o["observed_time_ms"] == 0.0 for o in observations):
        raise HostEvidenceError("no host Press observation at 0.0 ms: first-Press t0 anchor missing")

    expected = matching["expected_slot_count"]
    raw = len(observations)
    outside = matching["outside_capture_window_count"]
    in_window = raw - outside
    delta = in_window - expected

    matched_deltas = [o["delta_ms"] for o in observations if o["status"] == STATUS_MATCHED]

    return {
        "configuration": {
            "capture_duration_s": matching["capture_duration_s"],
            "fixture_frequency_hz": matching["fixture_frequency_hz"],
            "reference_interval_ms": matching["reference_interval_ms"],
            "timing_tolerance_ms": matching["timing_tolerance_ms"],
            "matching_windows_can_overlap": matching["matching_windows_can_overlap"],
        },
        "counts": {
            "expected_slot_count": expected,
            "raw_host_press_count": raw,
            "in_window_host_press_count": in_window,
            "host_count_delta_vs_expected_slots": delta,
            "host_count_deficit_vs_expected_slots": max(0, -delta),
            "host_count_excess_vs_expected_slots": max(0, delta),
        },
        "matching": {
            "empty_expected_slot_count": matching["empty_slot_count"],
            "single_occupancy_slot_count": matching["single_occupancy_slot_count"],
            "multi_occupancy_slot_count": matching["multi_occupancy_slot_count"],
            "matched_host_observation_count": matching["matched_observation_count"],
            "unmatched_host_observation_count": matching["unmatched_observation_count"],
            "ambiguous_host_observation_count": matching["ambiguous_observation_count"],
            "outside_capture_window_observation_count": outside,
        },
        "timing": {
            "matched_delta_stats": descriptive_stats(matched_deltas),
            "matched_absolute_delta_stats": descriptive_stats(abs(d) for d in matched_deltas),
        },
    }
