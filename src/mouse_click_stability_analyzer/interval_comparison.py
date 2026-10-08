"""Configured Interval Range: factual comparison of observed press intervals.

Independent of Schedule Association Window. No DUT verdict, PASS/FAIL, or
heuristic classification. Comparison is inclusive on the frozen bounds.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

BASIS_PERCENT = "percent"
BASIS_MILLISECONDS = "milliseconds"
VALID_BASES = frozenset({BASIS_PERCENT, BASIS_MILLISECONDS})

POSITION_NOT_COMPARABLE = "not_comparable"
POSITION_WITHIN = "within"
POSITION_BELOW = "below"
POSITION_ABOVE = "above"
OUTSIDE_POSITIONS = frozenset({POSITION_BELOW, POSITION_ABOVE})

SETTINGS_ENABLED = "interval_comparison_enabled"
SETTINGS_BASIS = "interval_comparison_basis"
SETTINGS_VALUE = "interval_comparison_value"

RANGE_POSITION_SORT_RANK = {
    POSITION_WITHIN: 0,
    POSITION_BELOW: 1,
    POSITION_ABOVE: 2,
}


class IntervalComparisonError(ValueError):
    """Invalid engineer input. ``key`` is an i18n message key."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


def _finite_number(raw: Any, *, key: str) -> float:
    if raw is None or isinstance(raw, bool):
        raise IntervalComparisonError(key)
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise IntervalComparisonError(key)
        try:
            value = float(text)
        except ValueError as exc:
            raise IntervalComparisonError(key) from exc
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise IntervalComparisonError(key) from exc
    if not math.isfinite(value):
        raise IntervalComparisonError(key)
    return value


def parse_comparison_value(raw: Any) -> float:
    """Parse the authoritative tolerance. Finite and >= 0. No silent clamp."""
    value = _finite_number(raw, key="interval_comparison_invalid")
    if value < 0.0:
        raise IntervalComparisonError("interval_comparison_invalid")
    return value


def parse_basis(raw: Any) -> str:
    token = str(raw or "").strip().lower()
    if token in VALID_BASES:
        return token
    raise IntervalComparisonError("interval_comparison_invalid")


def reference_interval_ms(hz: Any) -> float:
    rate = _finite_number(hz, key="reference_rate_invalid")
    if rate <= 0.0:
        raise IntervalComparisonError("reference_rate_invalid")
    return 1000.0 / rate


def resolve_configured_range(
    *,
    reference_hz: Any,
    basis: Any,
    value: Any,
) -> dict[str, Any]:
    """Deterministic frozen range from the single authoritative input."""
    t_ms = reference_interval_ms(reference_hz)
    token = parse_basis(basis)
    configured = parse_comparison_value(value)
    if token == BASIS_PERCENT:
        if configured > 100.0:
            raise IntervalComparisonError("interval_comparison_percent_range")
        tolerance_pct = configured
        tolerance_ms = t_ms * configured / 100.0
    else:
        if configured > t_ms:
            raise IntervalComparisonError("interval_comparison_ms_range")
        tolerance_ms = configured
        tolerance_pct = configured / t_ms * 100.0
    lower_ms = t_ms - tolerance_ms
    upper_ms = t_ms + tolerance_ms
    if lower_ms < 0.0:
        raise IntervalComparisonError(
            "interval_comparison_percent_range" if token == BASIS_PERCENT else "interval_comparison_ms_range"
        )
    return {
        "enabled": True,
        "basis": token,
        "configured_value": configured,
        "reference_interval_ms": t_ms,
        "tolerance_pct": tolerance_pct,
        "tolerance_ms": tolerance_ms,
        "lower_bound_ms": lower_ms,
        "upper_bound_ms": upper_ms,
    }


def convert_authoritative_value(
    *,
    reference_hz: Any,
    from_basis: Any,
    value: Any,
    to_basis: Any,
) -> float:
    """Preserve the same physical range while switching the authoritative unit."""
    resolved = resolve_configured_range(reference_hz=reference_hz, basis=from_basis, value=value)
    dest = parse_basis(to_basis)
    if dest == resolved["basis"]:
        return float(resolved["configured_value"])
    if dest == BASIS_PERCENT:
        return float(resolved["tolerance_pct"])
    return float(resolved["tolerance_ms"])


def disabled_contract() -> dict[str, Any]:
    return {"enabled": False}


def settings_comparison_fields(
    *,
    enabled: bool,
    basis: str = BASIS_PERCENT,
    value: float | None = None,
) -> dict[str, Any]:
    """Persistable settings keys. Value may be omitted until the engineer configures it."""
    out: dict[str, Any] = {
        SETTINGS_ENABLED: bool(enabled),
        SETTINGS_BASIS: parse_basis(basis) if basis else BASIS_PERCENT,
    }
    if value is not None:
        out[SETTINGS_VALUE] = float(value)
    return out


def read_settings_fields(settings: dict[str, Any] | None) -> dict[str, Any]:
    src = dict(settings or {})
    enabled = bool(src.get(SETTINGS_ENABLED))
    raw_basis = src.get(SETTINGS_BASIS) or BASIS_PERCENT
    try:
        basis = parse_basis(raw_basis)
    except IntervalComparisonError:
        basis = BASIS_PERCENT
    value = src.get(SETTINGS_VALUE)
    return {"enabled": enabled, "basis": basis, "value": value}


def freeze_interval_comparison(
    settings: dict[str, Any] | None,
    *,
    manual: bool,
) -> dict[str, Any]:
    """Frozen run contract. Manual and unconfigured Fixture runs stay disabled."""
    if manual:
        return disabled_contract()
    fields = read_settings_fields(settings)
    if not fields["enabled"]:
        return disabled_contract()
    hz = (settings or {}).get("fixture_reference_hz")
    if hz is None:
        hz = (settings or {}).get("fixture_hz")
    try:
        return resolve_configured_range(
            reference_hz=hz,
            basis=fields["basis"],
            value=fields["value"],
        )
    except IntervalComparisonError:
        return disabled_contract()


def classify_interval(interval_ms: Any, contract: dict[str, Any] | None) -> str:
    """Return not_comparable / within / below / above. Inclusive bounds."""
    if not contract or not contract.get("enabled"):
        return POSITION_NOT_COMPARABLE
    if interval_ms is None or isinstance(interval_ms, bool):
        return POSITION_NOT_COMPARABLE
    try:
        observed = float(interval_ms)
    except (TypeError, ValueError):
        return POSITION_NOT_COMPARABLE
    if not math.isfinite(observed):
        return POSITION_NOT_COMPARABLE
    lower = float(contract["lower_bound_ms"])
    upper = float(contract["upper_bound_ms"])
    if lower <= observed <= upper:
        return POSITION_WITHIN
    if observed < lower:
        return POSITION_BELOW
    return POSITION_ABOVE


def distance_from_range(interval_ms: Any, contract: dict[str, Any] | None) -> float | None:
    """Signed distance past the nearest bound: negative below, positive above, 0 within."""
    position = classify_interval(interval_ms, contract)
    if position == POSITION_NOT_COMPARABLE:
        return None
    observed = float(interval_ms)
    if position == POSITION_WITHIN:
        return 0.0
    if position == POSITION_BELOW:
        return observed - float(contract["lower_bound_ms"])
    return observed - float(contract["upper_bound_ms"])


def summarize_positions(positions: Iterable[str]) -> dict[str, Any]:
    within = 0
    below = 0
    above = 0
    for raw in positions:
        token = str(raw or "")
        if token == POSITION_WITHIN:
            within += 1
        elif token == POSITION_BELOW:
            below += 1
        elif token == POSITION_ABOVE:
            above += 1
    outside = below + above
    comparable = within + outside
    within_pct = (within / comparable * 100.0) if comparable else None
    return {
        "comparable_interval_count": comparable,
        "within_count": within,
        "outside_count": outside,
        "below_count": below,
        "above_count": above,
        "within_pct": within_pct,
    }


def evidence_interval_comparison(
    contract: dict[str, Any] | None,
    *,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Machine-readable evidence section. Disabled runs do not invent zero counts."""
    if not contract or not contract.get("enabled"):
        return disabled_contract()
    positions = []
    for event in events or []:
        if not isinstance(event, dict) or not event.get("accepted"):
            continue
        positions.append(classify_interval(event.get("press_interval_ms"), contract))
    summary = summarize_positions(positions)
    payload = {
        "enabled": True,
        "basis": contract["basis"],
        "configured_value": contract["configured_value"],
        "reference_interval_ms": contract["reference_interval_ms"],
        "tolerance_pct": contract["tolerance_pct"],
        "tolerance_ms": contract["tolerance_ms"],
        "lower_bound_ms": contract["lower_bound_ms"],
        "upper_bound_ms": contract["upper_bound_ms"],
        **summary,
    }
    return payload


def range_bounds(contract: dict[str, Any] | None) -> tuple[float, float] | None:
    if not contract or not contract.get("enabled"):
        return None
    return float(contract["lower_bound_ms"]), float(contract["upper_bound_ms"])
