"""Mouse Click Stability Analyzer — capture, metrics, and reporting core."""
from __future__ import annotations

import math
import statistics
import time
from datetime import datetime
from pathlib import Path

from .runtime import application_dir, default_report_root
from .schema import TOOL_NAME, TOOL_VERSION

APP_ROOT = application_dir()
DEFAULT_REPORT_DIR = default_report_root()

DEFAULT_SETTINGS = {
    "language": "en",
    "test_profile": "Fixture Strict",
    "capture_mode": "Windows Raw Input",
    "focus_button": "Left",
    "operator": "",
    "device_label": "",
    "device_under_test": None,
    "fixture_reference_hz": 0.0,
    "target_clicks": 1000,
    "chatter_threshold_ms": 8.0,
    "duplicate_click_threshold_ms": 30.0,
    "fixture_actuation_too_short_ms": 5.0,
    "low_hold_warning_ms": 8.0,
    "pause_gap_min_ms": 1000.0,
    "pause_gap_multiplier": 5.0,
    "max_chatter_count": 0,
    "missed_multiplier": 0.0005,
    "target_yield_pct": 99.95,
    "min_hold_ms": 1.0,
    "max_hold_ms": 500.0,
    "interval_cv_limit_pct": 5.0,
    "hold_cv_limit_pct": 25.0,
    "max_outlier_ratio_pct": 1.0,
    "rolling_window_size": 500,
    "chart_max_points": 2000,
    "fixture_expected_rate_hz": 0.0,
    "fixture_expected_interval_ms": 0.0,
    "fixture_start_delay_ms": 0.0,
    "fixture_match_tolerance_ms": 0.0,
    "fixture_expected_clicks": 0,
    "fixture_max_missed_count": 0,
}

BUTTON_MAP = {"Left": 1, "Middle": 2, "Right": 3}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_int(value, default):
    try:
        return int(value)
    except Exception:
        return default


def safe_float(value, default):
    try:
        return float(value)
    except Exception:
        return default


def normalize_settings(settings: dict | None) -> dict:
    merged = dict(DEFAULT_SETTINGS)
    merged.update(settings or {})
    merged["test_profile"] = str(merged.get("test_profile", DEFAULT_SETTINGS["test_profile"]))
    merged["capture_mode"] = str(merged.get("capture_mode", DEFAULT_SETTINGS["capture_mode"]))
    merged["focus_button"] = str(merged.get("focus_button", DEFAULT_SETTINGS["focus_button"]))
    merged["language"] = str(merged.get("language") or "en").lower()
    if merged["language"] not in ("en", "zh"):
        merged["language"] = "en"
    merged["operator"] = str(merged.get("operator") or "")
    merged["device_label"] = str(merged.get("device_label") or "")
    merged["fixture_reference_hz"] = max(0.0, safe_float(merged.get("fixture_reference_hz"), 0.0))
    merged["target_clicks"] = max(1, safe_int(merged.get("target_clicks"), DEFAULT_SETTINGS["target_clicks"]))
    merged["chatter_threshold_ms"] = safe_float(merged.get("chatter_threshold_ms"), 8.0)
    merged["duplicate_click_threshold_ms"] = safe_float(merged.get("duplicate_click_threshold_ms"), 30.0)
    merged["fixture_actuation_too_short_ms"] = safe_float(merged.get("fixture_actuation_too_short_ms"), 5.0)
    merged["low_hold_warning_ms"] = safe_float(merged.get("low_hold_warning_ms"), 8.0)
    merged["pause_gap_min_ms"] = safe_float(merged.get("pause_gap_min_ms"), 1000.0)
    merged["pause_gap_multiplier"] = safe_float(merged.get("pause_gap_multiplier"), 5.0)
    merged["max_chatter_count"] = max(0, safe_int(merged.get("max_chatter_count"), 0))
    merged["missed_multiplier"] = max(0.0, safe_float(merged.get("missed_multiplier"), 0.0005))
    merged["target_yield_pct"] = safe_float(merged.get("target_yield_pct"), 99.95)
    merged["min_hold_ms"] = safe_float(merged.get("min_hold_ms"), 1.0)
    merged["max_hold_ms"] = safe_float(merged.get("max_hold_ms"), 500.0)
    merged["interval_cv_limit_pct"] = safe_float(merged.get("interval_cv_limit_pct"), 5.0)
    merged["hold_cv_limit_pct"] = safe_float(merged.get("hold_cv_limit_pct"), 25.0)
    merged["max_outlier_ratio_pct"] = safe_float(merged.get("max_outlier_ratio_pct"), 1.0)
    merged["rolling_window_size"] = max(10, safe_int(merged.get("rolling_window_size"), 500))
    merged["chart_max_points"] = max(100, safe_int(merged.get("chart_max_points"), 2000))
    merged["fixture_expected_rate_hz"] = 0.0
    merged["fixture_expected_interval_ms"] = 0.0
    merged["fixture_start_delay_ms"] = 0.0
    merged["fixture_match_tolerance_ms"] = 0.0
    merged["fixture_expected_clicks"] = 0
    merged["fixture_max_missed_count"] = 0
    return merged


def percentile(values: list[float], pct: float):
    data = sorted([v for v in values if v is not None])
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    k = (len(data) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return data[int(k)]
    return data[f] * (c - k) + data[c] * (k - f)


def cv_pct(values: list[float]):
    if len(values) < 2:
        return None
    avg = statistics.mean(values)
    if avg == 0:
        return None
    return statistics.pstdev(values) / avg * 100.0


def high_outlier_count(values: list[float], floor_ms: float = 10.0):
    if len(values) < 20:
        return 0, None
    med = percentile(values, 50)
    deviations = [abs(v - med) for v in values]
    mad = percentile(deviations, 50)
    if not mad:
        avg = statistics.mean(values)
        sd = statistics.pstdev(values) if len(values) > 1 else 0
        spread = 3 * sd
    else:
        spread = 3 * 1.4826 * mad
    threshold = med + max(float(floor_ms), spread)
    return len([v for v in values if v > threshold]), threshold


def interval_value(event: dict, preferred: str = "press"):
    if preferred == "press":
        v = event.get("press_interval_ms")
        if v is not None:
            return v
    return event.get("interval_ms")


def estimate_reference_interval_ms(interval_events: list[dict], settings: dict) -> float | None:
    hz = safe_float(settings.get("fixture_reference_hz"), 0.0)
    if hz > 0:
        return 1000.0 / hz
    vals = [interval_value(e, "press") for e in interval_events if interval_value(e, "press") is not None]
    vals = [v for v in vals if v < settings["pause_gap_min_ms"]]
    return percentile(vals, 50)


def pause_gap_threshold_ms(reference_interval_ms: float | None, settings: dict) -> float:
    if reference_interval_ms and reference_interval_ms > 0:
        return max(settings["pause_gap_min_ms"], reference_interval_ms * settings["pause_gap_multiplier"])
    return settings["pause_gap_min_ms"]


def hold_spike_threshold(holds: list[float]) -> float | None:
    if len(holds) < 20:
        return None
    med = percentile(holds, 50)
    deviations = [abs(v - med) for v in holds]
    mad = percentile(deviations, 50) or 0
    return med + max(10.0, 3 * 1.4826 * mad)


def long_interval_threshold_ms(values: list[float], reference_interval_ms: float | None):
    clean = [v for v in values if v is not None and v < 1000]
    if len(clean) < 20:
        if reference_interval_ms:
            return reference_interval_ms * 1.5
        return None
    med = percentile(clean, 50)
    deviations = [abs(v - med) for v in clean]
    mad = percentile(deviations, 50) or 0
    robust = med + max(20.0, 6 * 1.4826 * mad)
    if reference_interval_ms:
        return max(robust, reference_interval_ms * 1.5)
    return robust


def compressed_release_after_hold_spike_count(events: list[dict], duplicate_threshold_ms: float, hold_threshold: float | None):
    if hold_threshold is None:
        return 0
    count = 0
    for i in range(1, len(events)):
        cur, prev = events[i], events[i - 1]
        release_interval = cur.get("interval_ms")
        press_interval = cur.get("press_interval_ms")
        prev_hold = prev.get("hold_ms")
        if release_interval is None or prev_hold is None:
            continue
        if release_interval < duplicate_threshold_ms and prev_hold > hold_threshold:
            if press_interval is None or press_interval >= duplicate_threshold_ms:
                count += 1
    return count


def timing_jitter_pair_count(interval_events, expected_interval_ms, duplicate_threshold_ms, pause_threshold_ms):
    if not expected_interval_ms:
        return 0
    count = 0
    tolerance_sum = max(10.0, expected_interval_ms * 0.20)
    early_limit = expected_interval_ms * 0.90
    late_limit = expected_interval_ms * 1.10
    vals = [(e, interval_value(e, "press")) for e in interval_events]
    vals = [(e, v) for e, v in vals if v is not None]
    for i in range(len(vals) - 1):
        _, a = vals[i]
        _, b = vals[i + 1]
        if a >= pause_threshold_ms or b >= pause_threshold_ms:
            continue
        if a < duplicate_threshold_ms or b < duplicate_threshold_ms:
            continue
        early_late = a < early_limit and b > late_limit
        late_early = a > late_limit and b < early_limit
        if not (early_late or late_early):
            continue
        if abs((a + b) - (2 * expected_interval_ms)) <= tolerance_sum:
            count += 1
    return count


def compute_metrics(events: list[dict], settings: dict | None) -> dict:
    from .cadence import (
        cadence_band_ms,
        cadence_ms,
        compute_class_counts,
        compute_dut_setup_scores,
        compute_timing_error_metrics,
        extra_click_ceiling_ms,
        is_extreme_cadence,
    )

    s = normalize_settings(settings)
    if settings:
        for key in ("fixture_hz", "profile_name", "expected_clicks", "duration_sec", "duplicate_click_threshold_ms"):
            if key in settings and settings.get(key) is not None:
                s[key] = settings[key]
        if settings.get("fixture_hz") and not s.get("fixture_reference_hz"):
            s["fixture_reference_hz"] = float(settings.get("fixture_hz") or 0)

    target_clicks = s["target_clicks"]
    extreme = is_extreme_cadence(s)
    accepted_events = [e for e in events if e.get("accepted")]
    click_count = len(accepted_events)
    run_complete = click_count >= target_clicks if target_clicks else False
    completion_pct = min(100.0, click_count / target_clicks * 100.0) if target_clicks else 0.0

    interval_events = [e for e in accepted_events if interval_value(e, "press") is not None]
    raw_press_intervals = [interval_value(e, "press") for e in interval_events if interval_value(e, "press") is not None]
    raw_release_intervals = [e.get("interval_ms") for e in accepted_events if e.get("interval_ms") is not None]
    holds = [e["hold_ms"] for e in accepted_events if e.get("hold_ms") is not None]

    reference_interval = estimate_reference_interval_ms(interval_events, s)
    pause_threshold = pause_gap_threshold_ms(reference_interval, s)
    pause_gap_count = len([v for v in raw_press_intervals if v >= pause_threshold])
    valid_intervals = [v for v in raw_press_intervals if v < pause_threshold]

    extra_ceiling = extra_click_ceiling_ms(s)
    cadence_lo, cadence_hi = cadence_band_ms(s)
    if extreme and cadence_lo is not None and cadence_hi is not None:
        stats_intervals = [v for v in valid_intervals if cadence_lo <= v <= cadence_hi] or valid_intervals
        chatter_count = len([v for v in valid_intervals if v < s["chatter_threshold_ms"]])
        duplicate_click_risk_count = len([v for v in valid_intervals if s["chatter_threshold_ms"] <= v < extra_ceiling])
    else:
        stats_intervals = valid_intervals
        chatter_count = len([v for v in valid_intervals if v < s["chatter_threshold_ms"]])
        duplicate_click_risk_count = len([v for v in valid_intervals if v < s["duplicate_click_threshold_ms"]])

    long_interval_threshold = long_interval_threshold_ms(stats_intervals, reference_interval)
    long_interval_spike_count = len([
        v for v in valid_intervals
        if long_interval_threshold is not None and v > long_interval_threshold
    ])
    hold_threshold = hold_spike_threshold(holds)
    compressed_release_count = compressed_release_after_hold_spike_count(
        accepted_events,
        extra_ceiling if extreme else s["duplicate_click_threshold_ms"],
        hold_threshold,
    )
    fixture_actuation_too_short_count = len([v for v in holds if v < s["fixture_actuation_too_short_ms"]])
    low_hold_warning_count = len([
        v for v in holds
        if s["fixture_actuation_too_short_ms"] <= v < s["low_hold_warning_ms"]
    ])
    timing_jitter_count = timing_jitter_pair_count(
        interval_events, reference_interval,
        extra_ceiling if extreme else s["duplicate_click_threshold_ms"],
        pause_threshold,
    )
    short_hold_count = len([v for v in holds if v < s["min_hold_ms"]])
    long_hold_count = len([v for v in holds if v > s["max_hold_ms"]])
    missed_estimated = max(0, target_clicks - click_count) if target_clicks else 0
    yield_pct = min(100.0, click_count / target_clicks * 100.0) if target_clicks else 100.0
    missed_limit = target_clicks * s["missed_multiplier"] if target_clicks else 0

    interval_cv = cv_pct(stats_intervals)
    hold_cv = cv_pct(holds)
    interval_median = percentile(stats_intervals, 50) if stats_intervals else None
    interval_outlier_floor_ms = max(5.0, (interval_median or 0) * 0.10) if stats_intervals else 10.0
    interval_outlier_count, interval_outlier_threshold = high_outlier_count(stats_intervals, floor_ms=interval_outlier_floor_ms)
    hold_outlier_count, hold_outlier_threshold = high_outlier_count(holds, floor_ms=10.0)
    interval_outlier_ratio = interval_outlier_count / max(1, len(stats_intervals)) * 100.0
    hold_outlier_ratio = hold_outlier_count / max(1, len(holds)) * 100.0
    interval_avg = statistics.mean(stats_intervals) if stats_intervals else None
    interval_stdev = statistics.pstdev(stats_intervals) if len(stats_intervals) > 1 else None
    hold_avg = statistics.mean(holds) if holds else None
    hold_stdev = statistics.pstdev(holds) if len(holds) > 1 else None

    fail_reasons, warn_reasons = [], []
    if run_complete and target_clicks and yield_pct < s["target_yield_pct"]:
        fail_reasons.append(f"yield {yield_pct:.4f}% < target {s['target_yield_pct']:.4f}%")
    if run_complete and missed_estimated > missed_limit:
        fail_reasons.append(f"missed_estimated {missed_estimated} > missed_limit {missed_limit:.4f}")
    if chatter_count > s["max_chatter_count"]:
        fail_reasons.append(f"chatter_count {chatter_count} > max_chatter_count {s['max_chatter_count']}")
    if duplicate_click_risk_count > 0:
        fail_reasons.append(f"duplicate_click_risk_count {duplicate_click_risk_count} where press_interval < {extra_ceiling}ms")
    if interval_cv is not None and interval_cv > s["interval_cv_limit_pct"]:
        fail_reasons.append(f"press_interval_cv_pct {interval_cv:.4f}% > limit {s['interval_cv_limit_pct']:.4f}%")
    if hold_cv is not None and hold_cv > s["hold_cv_limit_pct"]:
        (warn_reasons if extreme else fail_reasons).append(f"hold_cv_pct {hold_cv:.4f}% > limit {s['hold_cv_limit_pct']:.4f}%")
    if interval_outlier_ratio > s["max_outlier_ratio_pct"]:
        fail_reasons.append(f"press_interval_outlier_ratio_pct {interval_outlier_ratio:.4f}% > limit")
    if hold_outlier_ratio > s["max_outlier_ratio_pct"]:
        (warn_reasons if extreme else fail_reasons).append(f"hold_outlier_ratio_pct {hold_outlier_ratio:.4f}% > limit")

    if fail_reasons:
        health, passed = "FAIL", False
    elif warn_reasons:
        health, passed = "WARN", True if run_complete else None
    elif run_complete:
        health, passed = "PASS", True
    else:
        health, passed = "RUNNING", None

    stability_score = max(0.0, round(
        100.0
        - min(40.0, chatter_count * 5.0)
        - min(40.0, duplicate_click_risk_count * 10.0)
        - (min(25.0, max(0.0, s["target_yield_pct"] - yield_pct) * 5.0) if run_complete else 0)
        - (min(20.0, max(0.0, (interval_cv or 0) - s["interval_cv_limit_pct"]) * 2.0) if interval_cv is not None else 0)
        - (min(10.0, max(0.0, (hold_cv or 0) - s["hold_cv_limit_pct"])) if hold_cv is not None else 0),
        4,
    ))

    result = {
        "target_clicks": target_clicks,
        "click_count": click_count,
        "run_complete": run_complete,
        "completion_pct": round(completion_pct, 4),
        "fixture_reference_hz": s["fixture_reference_hz"],
        "reference_interval_ms": round(reference_interval, 4) if reference_interval is not None else None,
        "pause_gap_threshold_ms": round(pause_threshold, 4),
        "pause_gap_count": pause_gap_count,
        "effective_interval_count": len(valid_intervals),
        "long_interval_threshold_ms": round(long_interval_threshold, 4) if long_interval_threshold is not None else None,
        "long_interval_spike_count": long_interval_spike_count,
        "duplicate_click_threshold_ms": s["duplicate_click_threshold_ms"],
        "duplicate_click_risk_count": duplicate_click_risk_count,
        "compressed_release_after_hold_spike_count": compressed_release_count,
        "timing_jitter_pair_count": timing_jitter_count,
        "fixture_actuation_too_short_ms": s["fixture_actuation_too_short_ms"],
        "fixture_actuation_too_short_count": fixture_actuation_too_short_count,
        "low_hold_warning_ms": s["low_hold_warning_ms"],
        "low_hold_warning_count": low_hold_warning_count,
        "missed_estimated": missed_estimated,
        "yield_pct": round(yield_pct, 4),
        "chatter_threshold_ms": s["chatter_threshold_ms"],
        "max_chatter_count": s["max_chatter_count"],
        "chatter_count": chatter_count,
        "interval_avg_ms": round(interval_avg, 4) if interval_avg is not None else None,
        "interval_cv_pct": round(interval_cv, 4) if interval_cv is not None else None,
        "interval_p99_ms": round(percentile(stats_intervals, 99), 4) if stats_intervals else None,
        "hold_avg_ms": round(hold_avg, 4) if hold_avg is not None else None,
        "hold_cv_pct": round(hold_cv, 4) if hold_cv is not None else None,
        "hold_p99_ms": round(percentile(holds, 99), 4) if holds else None,
        "stability_score": stability_score,
        "health": health,
        "pass": passed,
        "fail_reasons": fail_reasons,
        "warn_reasons": warn_reasons,
        "cadence_mode": "extreme_40hz" if extreme else "fixture_defect",
        "extra_click_ceiling_ms": round(extra_ceiling, 4),
    }
    valid_median = percentile(valid_intervals, 50) if valid_intervals else None
    result["measured_interval_ms"] = round(valid_median, 4) if valid_median is not None else None
    result["measured_hz"] = round(1000.0 / valid_median, 2) if valid_median and valid_median > 0 else None
    result.update(compute_timing_error_metrics(valid_intervals, cadence_ms(s)))
    class_counts = compute_class_counts(accepted_events)
    result.update(compute_dut_setup_scores(result, s, class_counts))
    return result


def build_payload(target: str, operator: str, settings: dict, events: list[dict], run_id: str = "") -> dict:
    merged = normalize_settings(settings)
    merged.update(settings or {})
    return {
        "schema_version": 1,
        "tool": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "run_id": run_id,
        "created_at": now_iso(),
        "target": target,
        "operator": operator,
        "settings": merged,
        "metrics": compute_metrics(events, merged),
        "events": events,
    }


def make_synthetic_events(count: int = 1000, interval_ms: float = 20.0, hold_ms: float = 8.0) -> list[dict]:
    events = []
    first_press = first_release = last_press = last_release = None
    t0 = time.perf_counter()
    for i in range(count):
        press = t0 + i * (interval_ms / 1000.0)
        release = press + (hold_ms / 1000.0)
        if first_press is None:
            first_press = press
        if first_release is None:
            first_release = release
        press_interval = None if last_press is None else (press - last_press) * 1000
        release_interval = None if last_release is None else (release - last_release) * 1000
        last_press, last_release = press, release
        events.append({
            "index": i + 1,
            "timestamp": now_iso(),
            "press_elapsed_ms": round((press - first_press) * 1000, 4),
            "press_interval_ms": round(press_interval, 4) if press_interval is not None else None,
            "release_elapsed_ms": round((release - first_release) * 1000, 4),
            "elapsed_ms": round((release - first_release) * 1000, 4),
            "button": "Left",
            "event_type": "click",
            "accepted": True,
            "hold_ms": round(hold_ms, 4),
            "interval_ms": round(release_interval, 4) if release_interval is not None else None,
            "x": 100 + (i % 500),
            "y": 100,
            "capture_source": "self_test",
            "device_source": "synthetic",
            "flags": [],
        })
    return events
