"""User-facing aliases for legacy screening class and tag names.

Qt-free presentation helpers shared by the Qt shell and headless reports.
Internal classifier enums, tags, and thresholds stay unchanged. These labels
are presentation only: they must not be treated as validated diagnoses.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable

# click_class / tag → i18n key used by Capture, Results, and reports.
SCREENING_PRESENTATION_KEYS: dict[str, str] = {
    "ON_CADENCE": "legend_on_cadence",
    "OK": "legend_on_cadence",
    "CHATTER_BOUNCE": "legend_chatter",
    "CHATTER_HARD": "legend_chatter",
    "TRUE_EXTRA_CLICK": "legend_extra",
    "HIGH_PROBABILITY_DOUBLE_CLICK": "legend_extra",
    "INCOMPLETE_REBOUND": "legend_rebound",
    "FIXTURE_ACTUATION_TOO_SHORT": "legend_rebound",
    "LOW_HOLD_WARNING": "legend_rebound",
    "MISS_OR_SLOW": "legend_miss",
    "LONG_INTERVAL_SPIKE_WARN": "legend_miss",
    "INTERVAL_JITTER_WARN": "legend_interval_variation",
    "SETUP_ALIGNMENT_SUSPECT": "legend_hold_variation",
    "TIMING_JITTER_PAIR": "legend_timing_variation",
    "FIXTURE_HZ_MISMATCH": "legend_cadence_vs_reference",
    "PAUSE_GAP": "legend_pause_excluded",
    "PAUSE_GAP_EXCLUDED": "legend_pause_excluded",
    "WRONG_BUTTON_DETECTED": "legend_wrong_button",
    "INSUFFICIENT_CLICKS": "legend_low_press_count",
    "CAPTURE_SOURCE_INVALID": "legend_invalid_capture_source",
}

# English fallbacks so HTML/XLSX can share the same aliases without Qt i18n.
SCREENING_PRESENTATION_EN: dict[str, str] = {
    "ON_CADENCE": "Observation",
    "OK": "Observation",
    "CHATTER_BOUNCE": "Very short interval",
    "CHATTER_HARD": "Very short interval",
    "TRUE_EXTRA_CLICK": "Short interval",
    "HIGH_PROBABILITY_DOUBLE_CLICK": "Short interval",
    "INCOMPLETE_REBOUND": "Short hold",
    "FIXTURE_ACTUATION_TOO_SHORT": "Short hold",
    "LOW_HOLD_WARNING": "Short hold",
    "MISS_OR_SLOW": "Long interval",
    "LONG_INTERVAL_SPIKE_WARN": "Long interval",
    "INTERVAL_JITTER_WARN": "Interval variation",
    "SETUP_ALIGNMENT_SUSPECT": "Hold variation",
    "TIMING_JITTER_PAIR": "Timing variation",
    "FIXTURE_HZ_MISMATCH": "Cadence vs reference",
    "PAUSE_GAP": "Pause excluded",
    "PAUSE_GAP_EXCLUDED": "Pause excluded",
    "WRONG_BUTTON_DETECTED": "Wrong button",
    "INSUFFICIENT_CLICKS": "Low press count",
    "CAPTURE_SOURCE_INVALID": "Invalid capture source",
}


def screening_presentation_label(
    internal_name: Any,
    tr: Callable[..., str] | None = None,
) -> str:
    """Return the human-facing presentation alias for a canonical class or tag name."""
    token = str(internal_name or "")
    if not token:
        return ""
    key = SCREENING_PRESENTATION_KEYS.get(token)
    if key and callable(tr):
        return tr(key)
    return SCREENING_PRESENTATION_EN.get(token, token)


def screening_presentation_labels(
    names: Iterable[Any] | None,
    tr: Callable[..., str] | None = None,
) -> list[str]:
    """Deduped human-facing aliases, preserving first-seen order."""
    out: list[str] = []
    seen: set[str] = set()
    for name in names or []:
        label = screening_presentation_label(name, tr)
        if not label or label in seen:
            continue
        seen.add(label)
        out.append(label)
    return out


MEASUREMENT_NEUTRAL_DISPLAY = "—"


def measurement_only_timing_observation_label() -> str:
    """Results Click Data in Measurement-only mode: no Screening/Validation category."""
    return MEASUREMENT_NEUTRAL_DISPLAY


def matched_observations_used_text(matched_n: Any, in_capture_n: Any) -> str:
    """English matched-timing denominator: matched of Host observations in capture.

    Outside-capture observations never enter schedule association, so they are
    not part of this population. Matching calculations are unchanged.
    """
    return f"{int(matched_n or 0)} of {int(in_capture_n or 0)} in capture"
