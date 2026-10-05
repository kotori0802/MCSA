from __future__ import annotations

import statistics
from typing import Any

from .measurements import reference_interval_ms_or_none

HIGH_SPEED_HZ_FLOOR = 30.0
# 25Hz beat is 40ms. Typed 25/28Hz would miss hz>=30; treat cad<=40ms as extreme.
EXTREME_CADENCE_MS = 40.0
EXTRA_BAND_LO_MS = 10.0
EXTRA_BAND_HI_MS = 16.0
CADENCE_LO_RATIO = 0.72
CADENCE_HI_RATIO = 1.35


def fixture_hz(settings: dict[str, Any] | None) -> float:
    s = settings or {}
    try:
        return float(s.get("fixture_hz") or s.get("fixture_reference_hz") or 0)
    except Exception:
        return 0.0


def is_extreme_cadence(settings: dict[str, Any] | None) -> bool:
    s = settings or {}
    name = str(s.get("profile_name") or s.get("test_profile") or "")
    hz = fixture_hz(s)
    cad = cadence_ms(s)
    return (
        hz >= HIGH_SPEED_HZ_FLOOR
        or (cad is not None and cad <= EXTREME_CADENCE_MS)
        or "40Hz" in name
        or name.startswith("HighSpeed")
    )


def cadence_ms(settings: dict[str, Any] | None) -> float | None:
    hz = fixture_hz(settings)
    if hz > 0:
        return reference_interval_ms_or_none(hz)
    return None


def _percentile_sorted(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def compute_timing_error_metrics(intervals: list[float], target_ms: float | None) -> dict[str, Any]:
    empty = {
        "timing_target_ms": None,
        "timing_bias_ms": None,
        "timing_sigma_ms": None,
        "p99_abs_error_ms": None,
        "within_0_5ms_pct": None,
        "within_1ms_pct": None,
    }
    if not target_ms or target_ms <= 0 or not intervals:
        return empty
    errors = [float(v) - float(target_ms) for v in intervals]
    abs_err = [abs(e) for e in errors]
    n = len(abs_err)
    p99 = _percentile_sorted(abs_err, 99)
    return {
        "timing_target_ms": round(float(target_ms), 4),
        "timing_bias_ms": round(statistics.mean(errors), 4),
        "timing_sigma_ms": round(statistics.pstdev(errors), 4) if n > 1 else 0.0,
        "p99_abs_error_ms": round(p99, 4) if p99 is not None else None,
        "within_0_5ms_pct": round(100.0 * sum(1 for e in abs_err if e <= 0.5) / n, 4),
        "within_1ms_pct": round(100.0 * sum(1 for e in abs_err if e <= 1.0) / n, 4),
    }


def manual_focus_xmax_ms(intervals: list[float]) -> float:
    """Locked Manual Hold×Interval X: P95×1.25, not stretched by one pause."""
    ints = sorted(float(v) for v in intervals if v is not None) or [80.0]
    p95 = ints[min(len(ints) - 1, int(len(ints) * 0.95))]
    return max(80.0, p95 * 1.25)


def apply_manual_delay_classes(events: list[dict[str, Any]], settings: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Mark Manual long-tail clicks as MISS_OR_SLOW using the same off-scale X as the chart."""
    if cadence_ms(settings):
        return events
    intervals: list[float] = []
    for e in events:
        if not e.get("accepted"):
            continue
        iv = e.get("press_interval_ms")
        if iv is None:
            continue
        val = float(iv)
        if val >= 1000 or str(e.get("click_class") or "") == "PAUSE_GAP":
            continue
        intervals.append(val)
    if len(intervals) < 5:
        return events
    xmax = manual_focus_xmax_ms(intervals)
    out = []
    delay_tags = class_to_tags("MISS_OR_SLOW", False)
    for e in events:
        row = dict(e)
        iv = row.get("press_interval_ms")
        cls = str(row.get("click_class") or "")
        if (
            row.get("accepted")
            and iv is not None
            and cls in {"ON_CADENCE", "OK", ""}
            and 1000 > float(iv) > xmax
        ):
            row["click_class"] = "MISS_OR_SLOW"
            tags = [t for t in str(row.get("issue_tags") or "").split(";") if t]
            for tag in delay_tags:
                if tag not in tags:
                    tags.append(tag)
            row["issue_tags"] = ";".join(tags)
        out.append(row)
    return out


def extra_click_ceiling_ms(settings: dict[str, Any] | None) -> float:
    """Intervals below this are sub-beat extras, not the intended fixture beat."""
    s = settings or {}
    configured = float(s.get("duplicate_click_threshold_ms") or 30.0)
    cad = cadence_ms(s)
    if cad and is_extreme_cadence(s):
        return min(configured, cad * CADENCE_LO_RATIO)
    return configured


def cadence_band_ms(settings: dict[str, Any] | None) -> tuple[float | None, float | None]:
    cad = cadence_ms(settings)
    if not cad:
        return None, None
    return cad * CADENCE_LO_RATIO, cad * CADENCE_HI_RATIO


def chatter_ms(settings: dict[str, Any] | None) -> float:
    s = settings or {}
    return float(s.get("chatter_threshold_ms") or 8.0)


def too_short_hold_ms(settings: dict[str, Any] | None) -> float:
    s = settings or {}
    return float(s.get("fixture_actuation_too_short_ms") or 5.0)


def classify_click(
    interval_ms: float | None,
    hold_ms: float | None,
    settings: dict[str, Any] | None,
    *,
    prev_hold_ms: float | None = None,
) -> str:
    """Return a single primary class for one accepted click."""
    s = settings or {}
    if interval_ms is None:
        return "ON_CADENCE" if is_extreme_cadence(s) else "OK"

    cad = cadence_ms(s)
    chatter = chatter_ms(s)
    extra_ceil = extra_click_ceiling_ms(s)
    too_short = too_short_hold_ms(s)
    hold = float(hold_ms) if hold_ms is not None else None
    interval = float(interval_ms)

    pause_min = float(s.get("pause_gap_min_ms") or 1000.0)
    if interval >= pause_min:
        return "PAUSE_GAP"

    if is_extreme_cadence(s) and cad:
        lo, hi = cadence_band_ms(s)
        miss_limit = max((hi or cad) * 1.05, cad * 1.5)
        if interval < chatter:
            return "CHATTER_BOUNCE"
        if interval < extra_ceil:
            if hold is not None and hold < too_short:
                return "INCOMPLETE_REBOUND"
            return "TRUE_EXTRA_CLICK"
        if interval > miss_limit:
            return "MISS_OR_SLOW"
        if lo is not None and hi is not None and lo <= interval <= hi:
            if hold is not None and hold < too_short:
                return "INCOMPLETE_REBOUND"
            return "ON_CADENCE"
        if interval < (lo or extra_ceil):
            if hold is not None and hold < too_short:
                return "INCOMPLETE_REBOUND"
            return "TRUE_EXTRA_CLICK"
        return "MISS_OR_SLOW"

    if interval < chatter:
        return "CHATTER_BOUNCE"
    if interval < extra_ceil:
        if hold is not None and hold < too_short:
            return "INCOMPLETE_REBOUND"
        return "TRUE_EXTRA_CLICK"
    if cad and interval > cad * 1.5:
        return "MISS_OR_SLOW"
    if hold is not None and hold < too_short:
        return "INCOMPLETE_REBOUND"
    return "ON_CADENCE"


def class_to_tags(click_class: str, extreme: bool) -> list[str]:
    mapping = {
        "CHATTER_BOUNCE": ["CHATTER_HARD", "CHATTER_BOUNCE"],
        "TRUE_EXTRA_CLICK": ["TRUE_EXTRA_CLICK"] + ([] if extreme else ["HIGH_PROBABILITY_DOUBLE_CLICK"]),
        "INCOMPLETE_REBOUND": ["INCOMPLETE_REBOUND", "FIXTURE_ACTUATION_TOO_SHORT"],
        "MISS_OR_SLOW": ["MISS_OR_SLOW", "LONG_INTERVAL_SPIKE_WARN"],
        "PAUSE_GAP": ["PAUSE_GAP_EXCLUDED"],
        "ON_CADENCE": [],
        "OK": [],
    }
    if not extreme and click_class == "TRUE_EXTRA_CLICK":
        return ["HIGH_PROBABILITY_DOUBLE_CLICK"]
    return list(mapping.get(click_class, []))


def compute_class_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "ON_CADENCE": 0,
        "CHATTER_BOUNCE": 0,
        "TRUE_EXTRA_CLICK": 0,
        "INCOMPLETE_REBOUND": 0,
        "MISS_OR_SLOW": 0,
        "PAUSE_GAP": 0,
        "SETUP_ALIGNMENT_SUSPECT": 0,
    }
    for e in events:
        if not e.get("accepted"):
            continue
        cls = str(e.get("click_class") or "")
        if cls in counts:
            counts[cls] += 1
        tags = str(e.get("issue_tags") or "")
        if "SETUP_ALIGNMENT_SUSPECT" in tags:
            counts["SETUP_ALIGNMENT_SUSPECT"] += 1
    return counts


def compute_dut_setup_scores(
    metrics: dict[str, Any],
    settings: dict[str, Any] | None,
    class_counts: dict[str, int],
) -> dict[str, Any]:
    s = settings or {}
    accepted = max(1, int(metrics.get("click_count") or 0))
    expected = int(s.get("expected_clicks") or s.get("target_clicks") or 0)
    missed = int(metrics.get("missed_estimated") or metrics.get("missed_click_count") or 0)
    if expected > 0:
        missed = max(missed, max(0, expected - int(metrics.get("click_count") or 0)))

    extra = int(class_counts.get("TRUE_EXTRA_CLICK") or 0)
    chatter = int(class_counts.get("CHATTER_BOUNCE") or metrics.get("chatter_count") or 0)
    incomplete = int(class_counts.get("INCOMPLETE_REBOUND") or 0)
    miss_slow = int(class_counts.get("MISS_OR_SLOW") or 0)
    interval_cv = metrics.get("interval_cv_pct")
    hold_cv = metrics.get("hold_cv_pct")
    interval_limit = float(s.get("interval_cv_limit_pct") or 10.0)
    hold_limit = float(s.get("hold_cv_limit_pct") or 25.0)

    extra_rate = extra / accepted * 1000.0
    manual = cadence_ms(s) is None
    miss_for_dut = 0 if manual else miss_slow
    miss_rate_pct = (missed + miss_for_dut) / max(expected, accepted) * 100.0

    dut = 100.0
    dut -= min(40.0, miss_rate_pct * 4.0)
    dut -= min(40.0, extra * 8.0)
    dut -= min(20.0, chatter * 5.0)
    if interval_cv is not None and not manual:
        dut -= min(20.0, max(0.0, float(interval_cv) - interval_limit) * 2.0)
    dut = max(0.0, round(dut, 4))

    setup = 100.0
    if hold_cv is not None:
        setup -= min(40.0, max(0.0, float(hold_cv) - hold_limit))
    setup -= min(30.0, incomplete * 3.0)
    setup_suspect = bool(class_counts.get("SETUP_ALIGNMENT_SUSPECT"))
    if setup_suspect or (hold_cv is not None and float(hold_cv) > hold_limit and (incomplete > 0 or miss_slow > 0)):
        setup -= 15.0
        setup_suspect = True
    setup = max(0.0, round(setup, 4))

    return {
        "dut_score": dut,
        "setup_score": setup,
        "setup_alignment_suspect": setup_suspect,
        "true_extra_click_count": extra,
        "incomplete_rebound_count": incomplete,
        "miss_or_slow_count": miss_slow,
        "chatter_bounce_count": chatter,
        "on_cadence_count": int(class_counts.get("ON_CADENCE") or 0),
        "extra_click_rate_per_1000": round(extra_rate, 4),
        "miss_rate_pct": round(miss_rate_pct, 4),
    }


def ranking_metrics(metrics: dict[str, Any], scores: dict[str, Any]) -> dict[str, Any]:
    return {
        "dut_score": scores.get("dut_score"),
        "setup_score": scores.get("setup_score"),
        "miss_rate_pct": scores.get("miss_rate_pct"),
        "true_extra_click_count": scores.get("true_extra_click_count"),
        "miss_or_slow_count": scores.get("miss_or_slow_count") or metrics.get("miss_or_slow_count"),
        "incomplete_rebound_count": scores.get("incomplete_rebound_count") or metrics.get("incomplete_rebound_count"),
        "extra_click_rate_per_1000": scores.get("extra_click_rate_per_1000"),
        "interval_p99_ms": metrics.get("interval_p99_ms"),
        "interval_cv_pct": metrics.get("interval_cv_pct"),
        "hold_cv_pct": metrics.get("hold_cv_pct"),
        "click_count": metrics.get("click_count"),
        "timing_bias_ms": metrics.get("timing_bias_ms"),
        "timing_sigma_ms": metrics.get("timing_sigma_ms"),
        "p99_abs_error_ms": metrics.get("p99_abs_error_ms"),
        "within_0_5ms_pct": metrics.get("within_0_5ms_pct"),
        "within_1ms_pct": metrics.get("within_1ms_pct"),
    }


def delta_cards(current: dict[str, Any], overlay: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [
        ("dut_score", "DUT score", False),
        ("miss_rate_pct", "Miss rate %", True),
        ("true_extra_click_count", "Extra clicks", True),
        ("miss_or_slow_count", "Delay / miss", True),
        ("interval_p99_ms", "Interval P99 ms", True),
        ("p99_abs_error_ms", "P99 |error| ms", True),
        ("timing_bias_ms", "Timing bias ms", True),
        ("interval_cv_pct", "Interval CV %", True),
        ("setup_score", "SETUP score", False),
    ]
    cards = []
    for key, label, lower_better in keys:
        a = overlay.get(key)
        b = current.get(key)
        winner = None
        try:
            if a is not None and b is not None:
                fa, fb = float(a), float(b)
                if abs(fa - fb) < 1e-9:
                    winner = "tie"
                elif lower_better:
                    winner = "A" if fa < fb else "B"
                else:
                    winner = "A" if fa > fb else "B"
        except Exception:
            winner = None
        cards.append({"key": key, "label": label, "a": a, "b": b, "winner": winner, "lower_better": lower_better})
    return cards


def maybe_mark_setup_suspect(events: list[dict[str, Any]], scores: dict[str, Any]) -> list[dict[str, Any]]:
    if not scores.get("setup_alignment_suspect"):
        return events
    out = []
    for e in events:
        row = dict(e)
        tags = [t for t in str(row.get("issue_tags") or "").split(";") if t]
        if "SETUP_ALIGNMENT_SUSPECT" not in tags and row.get("click_class") in {"INCOMPLETE_REBOUND", "MISS_OR_SLOW"}:
            tags.append("SETUP_ALIGNMENT_SUSPECT")
            row["issue_tags"] = ";".join(tags)
        out.append(row)
    return out


def mean_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return statistics.mean(values)
