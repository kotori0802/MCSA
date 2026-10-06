"""Copy-resource package: loader, validator, and report English lookup."""
from __future__ import annotations

from .loader import (
    KEY_OWNERS,
    REPORT_STRINGS,
    STRINGS,
    lookup_qt,
    reload_string_tables,
    report_text,
)

__all__ = [
    "KEY_OWNERS",
    "REPORT_STRINGS",
    "STRINGS",
    "lookup_qt",
    "reload_string_tables",
    "report_text",
]
