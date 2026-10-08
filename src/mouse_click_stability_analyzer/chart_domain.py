"""Presentation-only axis domains shared by Qt charts and HTML report charts.

Elapsed, Interval, Hold and Count are physically non-negative. Auto-fit padding
must not push their visible lower bound below zero. Signed quantities (Interval
delta vs reference, matched timing error, residuals) are not routed through
this helper and may still display negative values.

Never mutates data, binning, or outliers.
"""
from __future__ import annotations

import math
from typing import Iterable

DOMAIN_ELAPSED = "elapsed"
DOMAIN_INTERVAL = "interval"
DOMAIN_HOLD = "hold"
DOMAIN_COUNT = "count"
DOMAIN_SIGNED = "signed"

NON_NEGATIVE_DOMAINS = frozenset({DOMAIN_ELAPSED, DOMAIN_INTERVAL, DOMAIN_HOLD, DOMAIN_COUNT})


def _finite(values: Iterable[object] | None) -> list[float]:
    out: list[float] = []
    for raw in values or ():
        if raw is None or isinstance(raw, bool):
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append(v)
    return out


def physical_lower_floor(values: Iterable[object] | None) -> float:
    """Lowest permitted visible bound: 0, or the data minimum if data itself is negative."""
    nums = _finite(values)
    return min(0.0, min(nums)) if nums else 0.0


def domain_axis_bounds(
    lo: float,
    hi: float,
    *,
    domain: str,
    values: Iterable[object] | None = None,
) -> tuple[float, float]:
    """Return display bounds for ``domain``. Only non-negative domains are floored.

    The upper bound is kept; if flooring would collapse the span, the original
    span is preserved above the floor.
    """
    if domain not in NON_NEGATIVE_DOMAINS:
        return lo, hi
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return lo, hi
    floor = physical_lower_floor(values)
    if lo >= floor:
        return lo, hi
    span = hi - lo
    new_hi = hi if hi > floor else floor + span
    return floor, new_hi
