"""Canonical completed-run presentation model for Results (and future Report V2).

Built only from frozen run-owned data: locked settings, events, elapsed stamps,
and the existing Host Evidence snapshot. Does not rebuild Host Evidence, does
not read Setup widgets, and does not mutate the input event list.
"""
from __future__ import annotations

import math
from typing import Any

from .app import (
    _is_manual_profile,
    _metrics_issue_tags,
    _result_from_tags,
    annotate_events,
    build_payload,
)
from .cadence import cadence_ms
from .measurements import actual_run_duration_s

_QT_HIDDEN_PRESENTATION_TAGS = frozenset({"OPERATOR_FATIGUE", "HOLD_VARIATION_WARN"})
_RETIRED_COUNT_PRESENTATION_TAGS = frozenset({
    "MISS_CLICK_WARN",
    "MISS_CLICK_FAIL",
    "EXCESS_CLICK_COUNT_WARN",
    "EXCESS_CLICK_COUNT_FAIL",
})
_HOLD_CV_HEALTH_REASON_PREFIX = "hold_cv_pct "

_FAIL_PRESENTATION_TAGS = frozenset({
    "CHATTER_HARD",
    "INSUFFICIENT_CLICKS",
    "WRONG_BUTTON_DETECTED",
    "CAPTURE_SOURCE_INVALID",
})

_OBSERVATION_SPECS: tuple[tuple[str, str], ...] = (
    ("FIXTURE_HZ_MISMATCH", "obs_fixture_hz_mismatch"),
    ("CHATTER_HARD", "obs_chatter_hard"),
    ("HIGH_PROBABILITY_DOUBLE_CLICK", "obs_double_click"),
    ("TRUE_EXTRA_CLICK", "obs_true_extra"),
    ("INCOMPLETE_REBOUND", "obs_incomplete_rebound"),
    ("MISS_OR_SLOW", "obs_miss_or_slow"),
    ("LONG_INTERVAL_SPIKE_WARN", "obs_miss_or_slow"),
    ("FIXTURE_ACTUATION_TOO_SHORT", "obs_actuation_short"),
    ("LOW_HOLD_WARNING", "obs_low_hold"),
    ("INTERVAL_JITTER_WARN", "obs_interval_jitter"),
    ("SETUP_ALIGNMENT_SUSPECT", "obs_setup_alignment"),
    ("TIMING_JITTER_PAIR", "obs_timing_jitter_pair"),
    ("PAUSE_GAP_EXCLUDED", "obs_pause_gap"),
    ("WRONG_BUTTON_DETECTED", "obs_wrong_button"),
    ("INSUFFICIENT_CLICKS", "obs_insufficient"),
    ("CAPTURE_SOURCE_INVALID", "obs_capture_source"),
)

TIMING_ERROR_UNAVAILABLE_REASON = (
    "host_evidence_snapshot_stores_aggregate_matched_delta_stats_only"
)


def _reason_is_hidden_hold_cv(reason: Any) -> bool:
    return str(reason or "").startswith(_HOLD_CV_HEALTH_REASON_PREFIX)


def _legacy_health_is_exclusively_hidden_hold_cv(metrics: dict[str, Any]) -> bool:
    fail = [str(r) for r in (metrics.get("fail_reasons") or []) if str(r or "").strip()]
    warn = [str(r) for r in (metrics.get("warn_reasons") or []) if str(r or "").strip()]
    if not fail and not warn:
        return False
    return all(_reason_is_hidden_hold_cv(r) for r in fail + warn)


def _legacy_health_is_exclusively_retired_count(tags: Any) -> bool:
    """True when leftover presentation tags are only retired expected-count rules."""
    remaining: list[str] = []
    for tag in tags or []:
        name = str(tag or "").strip()
        if not name or name in _QT_HIDDEN_PRESENTATION_TAGS:
            continue
        remaining.append(name)
    return bool(remaining) and all(name in _RETIRED_COUNT_PRESENTATION_TAGS for name in remaining)


def qt_present_issue_tags(tags: Any) -> list[str]:
    """Primary Qt live/review tag list.

    Hides OPERATOR_FATIGUE (retired Segment inference), HOLD_VARIATION_WARN
    (driven by unexposed hold_cv_limit_pct), and retired expected-click count
    inference (MISS_CLICK_* / EXCESS_CLICK_COUNT_*). Does not mutate the input.
    """
    hidden = _QT_HIDDEN_PRESENTATION_TAGS | _RETIRED_COUNT_PRESENTATION_TAGS
    out: list[str] = []
    for tag in tags or []:
        name = str(tag or "").strip()
        if not name or name in hidden:
            continue
        out.append(name)
    return out


def qt_visible_verdict(
    tags: Any,
    metrics: dict[str, Any] | None,
    settings: dict[str, Any] | None = None,
) -> str:
    """Primary Qt live/review verdict from presentation tags.

    Does not mutate the legacy tag list or metrics. OPERATOR_FATIGUE,
    HOLD_VARIATION_WARN, and retired expected-click count tags cannot drive
    the visible VERDICT. metrics.health is kept unless structured fail/warn
    reasons prove it is exclusively hidden hold-CV, or leftover tags are
    exclusively the retired count rules.
    """
    m = dict(metrics or {})
    if int(m.get("click_count") or m.get("actual_clicks") or 0) <= 0:
        return "IDLE"
    if _legacy_health_is_exclusively_hidden_hold_cv(m) or _legacy_health_is_exclusively_retired_count(tags):
        m.pop("health", None)
    return _result_from_tags(qt_present_issue_tags(tags), m, settings)


def _finite_intervals(values: list[float]) -> list[float]:
    return [
        float(v) for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
    ]


def histogram_bin_edges(values: list[float], *, max_bins: int = 16) -> list[tuple[float, float]]:
    """Deterministic bin edges from a finite interval domain."""
    finite = _finite_intervals(values)
    if not finite:
        return []
    vmin = min(finite)
    vmax = max(finite)
    if vmax <= vmin:
        return [(vmin, vmin + 1.0)]
    n = min(max_bins, max(6, int(len(finite) ** 0.5) + 1))
    width = (vmax - vmin) / n
    edges = [(vmin + i * width, vmin + (i + 1) * width) for i in range(n)]
    edges[-1] = (edges[-1][0], vmax)
    return edges


def count_histogram(values: list[float], edges: list[tuple[float, float]]) -> list[dict[str, float | int]]:
    """Count finite values into the supplied [lo, hi) edges; last bin includes hi."""
    if not edges:
        return []
    bins = [{"lo": lo, "hi": hi, "count": 0} for lo, hi in edges]
    last = len(bins) - 1
    lo0 = float(edges[0][0])
    hi_last = float(edges[-1][1])
    span = hi_last - lo0
    n = len(bins)
    for v in _finite_intervals(values):
        if v >= hi_last:
            idx = last
        elif span <= 0:
            idx = 0
        else:
            idx = min(last, max(0, int((v - lo0) / span * n)))
        bins[idx]["count"] = int(bins[idx]["count"]) + 1
    return bins


def interval_histogram_bins(values: list[float], *, max_bins: int = 16) -> list[dict[str, float | int]]:
    """Deterministic interval histogram. Empty or single-value inputs are defined."""
    return count_histogram(values, histogram_bin_edges(values, max_bins=max_bins))


def paired_interval_histograms(
    current: list[float],
    overlay: list[float],
    *,
    max_bins: int = 16,
) -> tuple[list[dict[str, float | int]], list[dict[str, float | int]]]:
    """Current and overlay counts against the same edges when overlay is present."""
    overlay_finite = _finite_intervals(overlay)
    if not overlay_finite:
        return interval_histogram_bins(current, max_bins=max_bins), []
    edges = histogram_bin_edges(_finite_intervals(current) + overlay_finite, max_bins=max_bins)
    return count_histogram(current, edges), count_histogram(overlay, edges)


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _observation_rows_for_rule(
    rule: str,
    *,
    metrics: dict[str, Any],
    settings: dict[str, Any],
    reference_ms: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if rule == "FIXTURE_HZ_MISMATCH":
        observed = _finite(metrics.get("interval_avg_ms"))
        if observed is not None:
            rows.append({"label_key": "observed_average", "value": observed, "unit": "ms"})
        if reference_ms is not None:
            rows.append({"label_key": "configured_reference", "value": reference_ms, "unit": "ms"})
        if observed is not None and reference_ms is not None:
            rows.append({"label_key": "difference", "value": observed - reference_ms, "unit": "ms"})
        return rows
    if rule == "CHATTER_HARD":
        rows.append({"label_key": "measured", "value": int(metrics.get("chatter_count") or 0), "unit": ""})
        return rows
    if rule in {"HIGH_PROBABILITY_DOUBLE_CLICK", "TRUE_EXTRA_CLICK"}:
        extra = int(metrics.get("true_extra_click_count") or metrics.get("duplicate_click_risk_count") or 0)
        rows.append({"label_key": "measured", "value": extra, "unit": ""})
        return rows
    if rule == "INTERVAL_JITTER_WARN":
        cv = _finite(metrics.get("interval_cv_pct"))
        limit = _finite(settings.get("interval_cv_limit_pct"))
        if cv is not None:
            rows.append({"label_key": "measured", "value": cv, "unit": "%"})
        if limit is not None:
            rows.append({"label_key": "configured_reference", "value": limit, "unit": "%"})
        return rows
    return rows


def _build_observations(
    visible_tags: list[str],
    *,
    metrics: dict[str, Any],
    settings: dict[str, Any],
    reference_ms: float | None,
) -> list[dict[str, Any]]:
    seen_titles: set[str] = set()
    findings: list[dict[str, Any]] = []
    spec_map = dict(_OBSERVATION_SPECS)
    for tag in visible_tags:
        title_key = spec_map.get(tag)
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)
        findings.append({
            "rule": tag,
            "severity": "fail" if tag in _FAIL_PRESENTATION_TAGS else "warn",
            "title_key": title_key,
            "rows": _observation_rows_for_rule(tag, metrics=metrics, settings=settings, reference_ms=reference_ms),
        })
    return findings


def _click_rows(
    annotated: list[dict[str, Any]],
    *,
    manual: bool,
    reference_ms: float | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in annotated:
        if not event.get("accepted"):
            continue
        interval = _finite(event.get("press_interval_ms"))
        ref_delta = None
        if not manual and interval is not None and reference_ms is not None:
            ref_delta = interval - reference_ms
        visible = qt_present_issue_tags(
            [t for t in str(event.get("issue_tags") or "").replace(",", ";").split(";") if t.strip()]
        )
        rows.append({
            "index": event.get("click_index") or event.get("index"),
            "elapsed_ms": _finite(event.get("press_elapsed_ms")),
            "button": str(event.get("button") or ""),
            "interval_ms": interval,
            "hold_ms": _finite(event.get("hold_ms")),
            "state": str(event.get("click_class") or ""),
            "tags": visible,
            "reference_delta_ms": ref_delta,
        })
    return rows


def _analysis_payload(
    annotated: list[dict[str, Any]],
    *,
    manual: bool,
    reference_ms: float | None,
) -> dict[str, Any]:
    series: list[tuple[float, float]] = []
    points: list[tuple[float, float, str]] = []
    intervals: list[float] = []
    for event in annotated:
        if not event.get("accepted"):
            continue
        interval = _finite(event.get("press_interval_ms"))
        hold = _finite(event.get("hold_ms"))
        elapsed = _finite(event.get("press_elapsed_ms"))
        cls = str(event.get("click_class") or "ON_CADENCE")
        if interval is not None:
            intervals.append(interval)
            if elapsed is not None:
                series.append((elapsed, interval))
            if hold is not None:
                points.append((interval, hold, cls))
    return {
        "interval_series": series,
        "scatter_points": points,
        "intervals": intervals,
        "histogram": interval_histogram_bins(intervals),
        "reference_interval_ms": None if manual else reference_ms,
        "timing_error_available": False,
        "timing_error_reason": TIMING_ERROR_UNAVAILABLE_REASON,
    }


def build_completed_result_model(
    *,
    locked: dict[str, Any] | None,
    events: list[dict[str, Any]],
    run_id: str,
    target: str,
    operator: str = "",
    start_time: float | None = None,
    stop_time: float | None = None,
    host_evidence_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return one frozen completed-run interpretation, or None if no completed snapshot."""
    if locked is None:
        return None
    settings = locked
    annotated = annotate_events(list(events), settings)
    payload = build_payload(target, operator, settings, annotated, run_id=run_id)
    metrics = dict(payload.get("metrics") or {})
    tags_all = _metrics_issue_tags(metrics, settings, annotated)
    visible_tags = qt_present_issue_tags(tags_all)
    verdict = qt_visible_verdict(tags_all, metrics, settings)
    manual = _is_manual_profile(settings)
    try:
        elapsed_s = actual_run_duration_s(start_time, stop_time)
    except (TypeError, ValueError):
        elapsed_s = None
    reference_ms = cadence_ms(settings)
    hz = _finite(settings.get("fixture_reference_hz") or settings.get("fixture_hz"))
    duration = _finite(settings.get("duration_sec"))
    auto_stop_sec = duration if (not manual and duration is not None and duration > 0) else None
    snapshot = host_evidence_snapshot if host_evidence_snapshot else None
    return {
        "run": {
            "run_id": run_id,
            "target": str(target or "").strip(),
            "button": str(settings.get("focus_button") or settings.get("button") or "Left"),
            "manual": manual,
            "elapsed_s": elapsed_s,
            "host_press_count": int(metrics.get("click_count") or 0),
            "reference_hz": None if manual else hz,
            "reference_interval_ms": None if manual else reference_ms,
            "timing_tolerance_ms": None if manual else _finite(settings.get("fixture_timing_tolerance_ms")),
            "auto_stop_sec": auto_stop_sec,
            "settings": settings,
        },
        "assessment": {
            "verdict": verdict,
            "tags": visible_tags,
            "tags_all": tags_all,
            "metrics": metrics,
        },
        "observations": _build_observations(
            visible_tags, metrics=metrics, settings=settings, reference_ms=reference_ms,
        ),
        "analysis": _analysis_payload(annotated, manual=manual, reference_ms=reference_ms),
        "host_evidence": {
            "applicable": snapshot is not None,
            "snapshot": snapshot,
            "timing_error_chart": "unavailable_aggregate_only" if snapshot is not None else "not_applicable",
        },
        "click_data": _click_rows(annotated, manual=manual, reference_ms=reference_ms),
    }
