"""Package metadata and public API surface."""
from __future__ import annotations

from .schema import (
    DETAIL_SCHEMA,
    SETTINGS_SCHEMA,
    SUMMARY_SCHEMA,
    TOOL_ID,
    TOOL_NAME,
    TOOL_VERSION,
)
from .core import build_payload, compute_metrics, make_synthetic_events, normalize_settings
from .cadence import classify_click, compute_class_counts, is_extreme_cadence

__all__ = [
    "TOOL_ID",
    "TOOL_NAME",
    "TOOL_VERSION",
    "SUMMARY_SCHEMA",
    "DETAIL_SCHEMA",
    "SETTINGS_SCHEMA",
    "build_payload",
    "compute_metrics",
    "make_synthetic_events",
    "normalize_settings",
    "classify_click",
    "compute_class_counts",
    "is_extreme_cadence",
]
