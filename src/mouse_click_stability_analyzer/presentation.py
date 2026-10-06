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

# Report-owned English aliases (report.json). Qt Capture still uses legend_* via tr().
SCREENING_REPORT_KEYS: dict[str, str] = {
    "ON_CADENCE": "report_alias_observation",
    "OK": "report_alias_observation",
    "CHATTER_BOUNCE": "report_alias_very_short_interval",
    "CHATTER_HARD": "report_alias_very_short_interval",
    "TRUE_EXTRA_CLICK": "report_alias_short_interval",
    "HIGH_PROBABILITY_DOUBLE_CLICK": "report_alias_short_interval",
    "INCOMPLETE_REBOUND": "report_alias_short_hold",
    "FIXTURE_ACTUATION_TOO_SHORT": "report_alias_short_hold",
    "LOW_HOLD_WARNING": "report_alias_short_hold",
    "MISS_OR_SLOW": "report_alias_long_interval",
    "LONG_INTERVAL_SPIKE_WARN": "report_alias_long_interval",
    "INTERVAL_JITTER_WARN": "report_alias_interval_variation",
    "SETUP_ALIGNMENT_SUSPECT": "report_alias_hold_variation",
    "TIMING_JITTER_PAIR": "report_alias_timing_variation",
    "FIXTURE_HZ_MISMATCH": "report_alias_cadence_vs_reference",
    "PAUSE_GAP": "report_alias_pause_excluded",
    "PAUSE_GAP_EXCLUDED": "report_alias_pause_excluded",
    "WRONG_BUTTON_DETECTED": "report_alias_wrong_button",
    "INSUFFICIENT_CLICKS": "report_alias_low_press_count",
    "CAPTURE_SOURCE_INVALID": "report_alias_invalid_capture_source",
}


def _report_alias(token: str) -> str:
    from .strings.loader import report_text

    key = SCREENING_REPORT_KEYS.get(token)
    return report_text(key) if key else token


SCREENING_PRESENTATION_EN: dict[str, str] = {
    token: _report_alias(token) for token in SCREENING_REPORT_KEYS
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
    report_key = SCREENING_REPORT_KEYS.get(token)
    if report_key:
        return _report_alias(token)
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
    from .strings.loader import report_text

    return report_text(
        "report_matched_observations_used_value",
        matched=int(matched_n or 0),
        total=int(in_capture_n or 0),
    )
