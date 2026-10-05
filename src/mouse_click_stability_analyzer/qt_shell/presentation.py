"""User-facing aliases for legacy screening class and tag names.

Internal classifier enums, tags, and thresholds stay unchanged. These labels
are presentation only: they must not be treated as validated diagnoses.
"""
from __future__ import annotations

from typing import Any, Callable

# click_class / tag → i18n key used by Capture legends and live flags.
SCREENING_PRESENTATION_KEYS: dict[str, str] = {
    "ON_CADENCE": "legend_on_cadence",
    "CHATTER_BOUNCE": "legend_chatter",
    "CHATTER_HARD": "legend_chatter",
    "TRUE_EXTRA_CLICK": "legend_extra",
    "HIGH_PROBABILITY_DOUBLE_CLICK": "legend_extra",
    "INCOMPLETE_REBOUND": "legend_rebound",
    "FIXTURE_ACTUATION_TOO_SHORT": "legend_rebound",
    "LOW_HOLD_WARNING": "legend_rebound",
    "MISS_OR_SLOW": "legend_miss",
    "LONG_INTERVAL_SPIKE_WARN": "legend_miss",
}


def screening_presentation_label(internal_name: Any, tr: Callable[..., str]) -> str:
    """Return the Capture presentation alias for a canonical class or tag name."""
    token = str(internal_name or "")
    key = SCREENING_PRESENTATION_KEYS.get(token)
    if key:
        return tr(key)
    return token
