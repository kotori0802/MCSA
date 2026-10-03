from __future__ import annotations

import csv
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _agent_log(*_args, **_kwargs) -> None:
    return


from .schema import artifact_names, build_host_environment
from .report_v2 import host_information_rows, write_report_html, write_report_xlsx
from .core import build_payload, normalize_settings, now_iso, safe_float, safe_int, make_synthetic_events
from .adapters.raw_input_subprocess import WindowsRawInputSubprocess
from .cadence import (
    cadence_band_ms,
    cadence_ms,
    classify_click,
    class_to_tags,
    compute_class_counts,
    compute_dut_setup_scores,
    delta_cards,
    extra_click_ceiling_ms,
    fixture_hz,
    is_extreme_cadence,
    apply_manual_delay_classes,
    manual_focus_xmax_ms,
    maybe_mark_setup_suspect,
    ranking_metrics,
)


ArtifactNamePolicy = None

TOOL_ID = "mouse_click_stability_analyzer"
TOOL_NAME = "Mouse Click Stability Analyzer"
TOOL_VERSION = "1.0.0"
SUMMARY_SCHEMA = "MCSA_REPORT_V1"
ARMING_SEC = 0.0  # first click in Test Area is t0; no post-arm discard window
SOP_LISTEN = "Click in the Test Area to start."
SOP_RUNNING_MANUAL = "Recording… Stop with F5 or Esc"
SOP_RUNNING_FIXTURE = "Recording… Stop fixture before timer ends · F5/Esc to Stop"
SOP_REVIEW = "Review this run, then New Run or Finish Report."
MANUAL_SEGMENT_SEC_DEFAULT = 10.0
MANUAL_FATIGUE_RATIO = 1.25
MANUAL_FATIGUE_MIN_CLICKS = 4
DEFAULT_DURATIONS = [30, 60, 120, 300, 600, 1200, 1800, 3600, 14400]
BUTTONS = ["Left", "Right", "Middle", "X1", "X2"]

BUTTON_PRESETS: dict[str, dict[str, Any]] = {
    "Left": {"profile_name":"Fixture_Left_10Hz_Strict", "fixture_hz":10, "manual_mode":False, "chatter_threshold_ms":8.0, "duplicate_click_threshold_ms":30.0, "fixture_actuation_too_short_ms":5.0, "low_hold_warning_ms":8.0, "interval_cv_limit_pct":10.0, "hold_cv_limit_pct":25.0, "max_missed_count":1},
    "Right": {"profile_name":"Fixture_Right_10Hz_Strict", "fixture_hz":10, "manual_mode":False, "chatter_threshold_ms":8.0, "duplicate_click_threshold_ms":30.0, "fixture_actuation_too_short_ms":5.0, "low_hold_warning_ms":8.0, "interval_cv_limit_pct":10.0, "hold_cv_limit_pct":25.0, "max_missed_count":1},
    "Middle": {"profile_name":"Fixture_Middle_5Hz_Normal", "fixture_hz":5, "manual_mode":False, "chatter_threshold_ms":8.0, "duplicate_click_threshold_ms":30.0, "fixture_actuation_too_short_ms":8.0, "low_hold_warning_ms":12.0, "interval_cv_limit_pct":15.0, "hold_cv_limit_pct":35.0, "max_missed_count":1},
    "X1": {"profile_name":"Fixture_SideBack_5Hz_Normal", "fixture_hz":5, "manual_mode":False, "chatter_threshold_ms":8.0, "duplicate_click_threshold_ms":30.0, "fixture_actuation_too_short_ms":6.0, "low_hold_warning_ms":10.0, "interval_cv_limit_pct":15.0, "hold_cv_limit_pct":35.0, "max_missed_count":1},
    "X2": {"profile_name":"Fixture_SideFront_5Hz_Normal", "fixture_hz":5, "manual_mode":False, "chatter_threshold_ms":8.0, "duplicate_click_threshold_ms":30.0, "fixture_actuation_too_short_ms":6.0, "low_hold_warning_ms":10.0, "interval_cv_limit_pct":15.0, "hold_cv_limit_pct":35.0, "max_missed_count":1},
    "Left40": {"profile_name":"Fixture_Left_40Hz_Extreme", "fixture_hz":40, "manual_mode":False, "chatter_threshold_ms":8.0, "duplicate_click_threshold_ms":18.0, "fixture_actuation_too_short_ms":5.0, "low_hold_warning_ms":8.0, "interval_cv_limit_pct":10.0, "hold_cv_limit_pct":25.0, "max_missed_count":2},
}

PROFILE_PRESETS: dict[str, dict[str, Any]] = {
    "Fixture_Left_10Hz_Strict": {**BUTTON_PRESETS["Left"], "button":"Left", "test_profile":"Fixture Strict"},
    "Fixture_Right_10Hz_Strict": {**BUTTON_PRESETS["Right"], "button":"Right", "test_profile":"Fixture Strict"},
    "Fixture_Middle_5Hz_Normal": {**BUTTON_PRESETS["Middle"], "button":"Middle", "test_profile":"Fixture Normal"},
    "Fixture_SideBack_5Hz_Normal": {**BUTTON_PRESETS["X1"], "button":"X1", "test_profile":"Fixture Normal"},
    "Fixture_SideFront_5Hz_Normal": {**BUTTON_PRESETS["X2"], "button":"X2", "test_profile":"Fixture Normal"},
    "Fixture_Left_40Hz_Extreme": {**BUTTON_PRESETS["Left40"], "button":"Left", "test_profile":"Fixture Extreme 40Hz"},
    "Manual_Left_Stable": {**BUTTON_PRESETS["Left"], "button":"Left", "profile_name":"Manual_Left_Stable", "fixture_hz":0, "manual_mode":True, "test_profile":"Manual Stable", "interval_cv_limit_pct":40.0, "hold_cv_limit_pct":60.0, "max_missed_count":0},
    "Manual_Right_Stable": {**BUTTON_PRESETS["Right"], "button":"Right", "profile_name":"Manual_Right_Stable", "fixture_hz":0, "manual_mode":True, "test_profile":"Manual Stable", "interval_cv_limit_pct":40.0, "hold_cv_limit_pct":60.0, "max_missed_count":0},
    "Manual_AllButton_Debug": {**BUTTON_PRESETS["Left"], "button":"Left", "profile_name":"Manual_AllButton_Debug", "fixture_hz":0, "manual_mode":True, "test_profile":"Manual Debug", "interval_cv_limit_pct":80.0, "hold_cv_limit_pct":80.0, "max_missed_count":0},
}

PROFILE_NAMES = list(PROFILE_PRESETS.keys()) + ["Custom"]

RULE_PRESETS: dict[str, dict[str, Any]] = {
    "Loose": {
        "chatter_threshold_ms": 4.0,
        "duplicate_click_threshold_ms": 20.0,
        "fixture_actuation_too_short_ms": 3.0,
        "low_hold_warning_ms": 5.0,
        "interval_cv_limit_pct": 20.0,
    },
    "Medium": {
        "chatter_threshold_ms": 6.0,
        "duplicate_click_threshold_ms": 16.0,
        "fixture_actuation_too_short_ms": 4.0,
        "low_hold_warning_ms": 6.0,
        "interval_cv_limit_pct": 15.0,
    },
    "Strict": {
        "chatter_threshold_ms": 8.0,
        "duplicate_click_threshold_ms": 30.0,
        "fixture_actuation_too_short_ms": 5.0,
        "low_hold_warning_ms": 8.0,
        "interval_cv_limit_pct": 10.0,
    },
}
RULE_PRESET_LABELS = [
    ("Loose", "寬鬆 Loose"),
    ("Medium", "中等 Medium"),
    ("Strict", "嚴苛 Strict"),
    ("Customize", "自訂 Customize"),
]

ISSUE_DESCRIPTIONS_ZH = {
    "CHATTER_HARD": "出現低於 chatter hard threshold 的極短間隔，通常不可能是正常單次點擊。",
    "CHATTER_BOUNCE": "節拍內的極短額外周期，屬 switch bounce / chatter，不是治具 40Hz 節拍。",
    "HIGH_PROBABILITY_DOUBLE_CLICK": "出現高機率連點：兩次 press 間隔低於 double-click threshold。",
    "TRUE_EXTRA_CLICK": "在 25ms 節拍之外多出一次完整 down-up，遊戲/OS 會當成多一次 click。",
    "INCOMPLETE_REBOUND": "按住時間過短或回彈不完整後再下壓，較像治具/甜蜜點，不是真連點。",
    "MISS_OR_SLOW": "間隔明顯長於治具節拍，可能漏 KEY 或治具晃動。",
    "SETUP_ALIGNMENT_SUSPECT": "Hold 變異與回彈/漏點同時出現，請先檢查下壓點與治具晃動，不要直接判滑鼠。",
    "MISS_CLICK_WARN": "實際點擊數少於治具預期點擊數，可能有少量漏點或治具中斷。",
    "MISS_CLICK_FAIL": "實際點擊數明顯少於治具預期點擊數，疑似漏 key 或治具沒有穩定敲擊。",
    "EXCESS_CLICK_COUNT_WARN": "實際點擊數高於預期，可能是治具過快、重複觸發或設定不一致。",
    "EXCESS_CLICK_COUNT_FAIL": "實際點擊數明顯高於預期，需優先檢查是否有連點、治具彈跳或 expected clicks 設定錯誤。",
    "LONG_INTERVAL_SPIKE_WARN": "有長間隔尖峰，可能是治具短暫停頓、漏點或 OS/event batching。",
    "FIXTURE_ACTUATION_TOO_SHORT": "按住時間過短，優先檢查治具壓下深度與接觸是否穩定。",
    "LOW_HOLD_WARNING": "按住時間偏低，可能接近治具/按鍵判讀邊界。",
    "INTERVAL_JITTER_WARN": "點擊間隔變異偏大，請確認點擊器固定與滑鼠是否有震動。",
    "HOLD_VARIATION_WARN": "按住時間變異偏大，請檢查治具敲擊行程與按鍵機構。",
    "PAUSE_GAP_EXCLUDED": "測試中出現長停頓並已排除於主要 interval 統計之外。",
    "INSUFFICIENT_CLICKS": "有效點擊數不足，無法完成設定時間或目標點擊數判定。",
    "CAPTURE_SOURCE_INVALID": "未使用工程建議的 Raw Input capture source，結果僅適合 UI smoke。",
    "WRONG_BUTTON_DETECTED": "收到非目標按鍵事件，請確認治具位置與按鍵設定。",
    "TIMING_JITTER_PAIR": "發現早晚補償型 timing pair，較像治具/時序抖動而非真連點。",
    "MANUAL_PROFILE_NO_EXPECTED_COUNT": "Manual profile 不以治具預期次數硬判漏點，只保留連點與穩定度觀察。",
    "FIXTURE_HZ_MISMATCH": "實測節拍與設定 Hz 差超過約 10%，次數對不上多半是 Hz 設錯，不是 149 顆 extra。",
    "WARMUP_EXCLUDED": "Arming 窗內的點擊不列入次數與分類。",
    "OPERATOR_FATIGUE": "後半段平均間隔明顯變長，較像操作者手痠／節奏崩壞，不宜直接判 DUT。",
}

ISSUE_DESCRIPTIONS_EN = {
    "CHATTER_HARD": "Extremely short press interval below the chatter hard threshold; unlikely to be normal single-click timing.",
    "CHATTER_BOUNCE": "Sub-beat extra cycle in the chatter band; bounce, not the fixture cadence.",
    "HIGH_PROBABILITY_DOUBLE_CLICK": "High-probability double-click risk: press interval is below the configured double-click threshold.",
    "TRUE_EXTRA_CLICK": "An extra full down-up off the fixture cadence; the OS/game would count a second click.",
    "INCOMPLETE_REBOUND": "Hold too short or re-press after incomplete release; setup/sweet-spot, not a true extra click.",
    "MISS_OR_SLOW": "Interval clearly longer than the fixture beat; missed key or fixture shake.",
    "SETUP_ALIGNMENT_SUSPECT": "Hold variation plus rebound/miss together; check probe position and shake before blaming the DUT.",
    "MISS_CLICK_WARN": "Captured count is slightly below the fixture expected count; check fixture continuity before judging the DUT.",
    "MISS_CLICK_FAIL": "Captured count is clearly below the fixture expected count; possible missed clicks or fixture actuation loss.",
    "EXCESS_CLICK_COUNT_WARN": "Captured count is slightly above expected; check fixture speed or expected-count settings.",
    "EXCESS_CLICK_COUNT_FAIL": "Captured count is clearly above expected; possible repeated triggering, fixture bounce, or wrong expected count.",
    "LONG_INTERVAL_SPIKE_WARN": "Long interval spike observed; often caused by human pause, fixture pause, missed cycle, or OS event batching.",
    "FIXTURE_ACTUATION_TOO_SHORT": "Hold time is too short; check fixture press depth and button contact.",
    "LOW_HOLD_WARNING": "Hold time is near the warning boundary; review fixture actuation depth.",
    "INTERVAL_JITTER_WARN": "Click interval variation is high; usually fixture timing or human stability variation.",
    "HOLD_VARIATION_WARN": "Hold-time variation is high; check fixture travel and button mechanics.",
    "PAUSE_GAP_EXCLUDED": "A long pause was detected and excluded from main interval statistics.",
    "INSUFFICIENT_CLICKS": "Too few accepted clicks were captured to complete the run.",
    "CAPTURE_SOURCE_INVALID": "Capture source is not the engineering Raw Input source; result is suitable for UI smoke only.",
    "WRONG_BUTTON_DETECTED": "Events from a non-target button were received; check fixture location and button setting.",
    "TIMING_JITTER_PAIR": "Early/late timing pair observed; usually fixture/human timing jitter rather than a true double-click.",
    "MANUAL_PROFILE_NO_EXPECTED_COUNT": "Manual profile does not use expected click count as hard missed/excess evidence; timing is observation-first.",
    "FIXTURE_HZ_MISMATCH": "Measured cadence differs from set Hz by more than ~10%; count mismatch is likely the Hz setting, not extra clicks.",
    "WARMUP_EXCLUDED": "Clicks inside the arming window are excluded from count and classification.",
    "OPERATOR_FATIGUE": "Later segments show clearly longer average intervals; likely operator fatigue, not DUT failure.",
}


def compute_manual_segments(
    events: list[dict[str, Any]],
    *,
    segment_sec: float = MANUAL_SEGMENT_SEC_DEFAULT,
    fatigue_ratio: float = MANUAL_FATIGUE_RATIO,
    min_clicks: int = MANUAL_FATIGUE_MIN_CLICKS,
) -> dict[str, Any]:
    """Bucket manual clicks into time segments and flag late-session fatigue."""
    seg_ms = max(1000.0, float(segment_sec or MANUAL_SEGMENT_SEC_DEFAULT) * 1000.0)
    buckets: dict[int, list[float]] = {}
    for e in events:
        if not e.get("accepted"):
            continue
        tags = str(e.get("issue_tags") or "")
        if "PAUSE_GAP_EXCLUDED" in tags or "WARMUP_EXCLUDED" in tags:
            continue
        elapsed = e.get("press_elapsed_ms")
        interval = e.get("press_interval_ms")
        if elapsed is None or interval is None:
            continue
        try:
            elapsed_f = float(elapsed)
            interval_f = float(interval)
        except Exception:
            continue
        if interval_f <= 0:
            continue
        idx = int(elapsed_f // seg_ms)
        buckets.setdefault(idx, []).append(interval_f)

    segments: list[dict[str, Any]] = []
    for idx in sorted(buckets):
        vals = buckets[idx]
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        mean = avg
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        cv = (var ** 0.5) / mean * 100.0 if mean > 0 else 0.0
        segments.append({
            "index": idx,
            "start_sec": round(idx * segment_sec, 2),
            "end_sec": round((idx + 1) * segment_sec, 2),
            "click_count": len(vals),
            "avg_interval_ms": round(avg, 3),
            "cv_pct": round(cv, 2),
            "p95_interval_ms": round(sorted(vals)[min(len(vals) - 1, int(len(vals) * 0.95))], 3),
        })

    fatigue = False
    fatigue_after_sec = None
    baseline_avgs = [s["avg_interval_ms"] for s in segments[:2] if s["click_count"] >= min_clicks]
    if baseline_avgs:
        baseline = sum(baseline_avgs) / len(baseline_avgs)
        for s in segments[2:]:
            if s["click_count"] < min_clicks:
                continue
            if s["avg_interval_ms"] >= baseline * float(fatigue_ratio):
                fatigue = True
                fatigue_after_sec = s["start_sec"]
                break
    return {
        "segment_sec": float(segment_sec),
        "segments": segments,
        "operator_fatigue": fatigue,
        "fatigue_after_sec": fatigue_after_sec,
        "baseline_avg_interval_ms": round(sum(baseline_avgs) / len(baseline_avgs), 3) if baseline_avgs else None,
    }


def _now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(value: str) -> str:
    import re
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("_")
    return text or "mcsa_run"


def _profile_defaults(profile_name: str, button: str) -> dict[str, Any]:
    if profile_name in PROFILE_PRESETS:
        return dict(PROFILE_PRESETS[profile_name])
    if button in BUTTON_PRESETS:
        return dict(BUTTON_PRESETS[button])
    return dict(BUTTON_PRESETS["Left"])


def _is_manual_profile(settings: dict[str, Any]) -> bool:
    profile = str(settings.get("profile_name") or settings.get("test_profile") or "")
    mode = str(settings.get("judgement_mode") or settings.get("test_profile") or "")
    return bool(settings.get("manual_mode")) or profile.startswith("Manual_") or "Manual" in mode


def normalize_auto_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    settings = dict(payload.get("settings") or payload)
    fixture = dict(payload.get("fixture") or {})
    requested_profile = str(settings.get("profile_name") or "Fixture_Left_10Hz_Strict")
    button = str(settings.get("button") or settings.get("focus_button") or _profile_defaults(requested_profile, "Left").get("button") or "Left")
    if button not in BUTTONS:
        button = "Left"
    preset = _profile_defaults(requested_profile, button)
    if requested_profile in PROFILE_PRESETS:
        button = str(settings.get("button") or settings.get("focus_button") or preset.get("button") or button)
        if button not in BUTTONS:
            button = "Left"
    duration = int(float(settings.get("duration_sec") or settings.get("test_duration_sec") or preset.get("duration_sec") or 60))
    if duration < 1:
        duration = 60
    fixture_hz_raw = settings.get("fixture_hz") if "fixture_hz" in settings else settings.get("fixture_reference_hz", fixture.get("fixture_hz", preset.get("fixture_hz", 10)))
    try:
        fixture_hz = float(fixture_hz_raw or 0)
    except Exception:
        fixture_hz = float(preset.get("fixture_hz", 10) or 0)
    manual_mode = bool(settings.get("manual_mode", preset.get("manual_mode", False))) or requested_profile.startswith("Manual_")
    if manual_mode:
        fixture_hz = 0.0
    auto_expected = int(round(duration * fixture_hz)) if fixture_hz > 0 else 0
    expected_clicks = int(float(settings.get("expected_clicks") or settings.get("target_clicks") or auto_expected or 0))
    if not manual_mode and expected_clicks <= 0:
        expected_clicks = max(1, auto_expected or 600)
    if manual_mode and expected_clicks <= 0:
        expected_clicks = 0
    profile_name = str(settings.get("profile_name") or preset.get("profile_name") or ("Manual_Left_Stable" if manual_mode else f"Fixture_{button}_{int(fixture_hz)}Hz"))
    mode = str(settings.get("judgement_mode") or settings.get("test_profile") or preset.get("test_profile") or ("Manual Stable" if manual_mode else "Fixture Strict"))
    capture_mode = str(settings.get("capture_mode") or "Windows Raw Input / 裝置RawInput")
    out = {
        "profile_name": profile_name,
        "test_profile": mode,
        "manual_mode": bool(manual_mode),
        "capture_mode": capture_mode,
        "focus_button": button,
        "button": button,
        "duration_sec": duration,
        "fixture_hz": fixture_hz,
        "fixture_reference_hz": fixture_hz,
        "target_clicks": expected_clicks,
        "expected_clicks": expected_clicks,
        "expected_clicks_auto": auto_expected,
        "auto_start_delay_sec": float(settings.get("auto_start_delay_sec", 5 if not manual_mode else 0)),
        "chatter_threshold_ms": float(settings.get("chatter_threshold_ms", preset.get("chatter_threshold_ms", 8.0))),
        "duplicate_click_threshold_ms": float(settings.get("duplicate_click_threshold_ms", preset.get("duplicate_click_threshold_ms", 30.0))),
        "fixture_actuation_too_short_ms": float(settings.get("fixture_actuation_too_short_ms", preset.get("fixture_actuation_too_short_ms", 5.0))),
        "low_hold_warning_ms": float(settings.get("low_hold_warning_ms", preset.get("low_hold_warning_ms", 8.0))),
        "max_chatter_count": int(settings.get("max_chatter_count", 0)),
        "max_missed_count": int(settings.get("max_missed_count", preset.get("max_missed_count", 0 if manual_mode else 1))),
        "target_yield_pct": float(settings.get("target_yield_pct", 99.9 if button in {"Middle", "X1", "X2"} else 99.95)),
        "min_hold_ms": float(settings.get("min_hold_ms", 1.0)),
        "max_hold_ms": float(settings.get("max_hold_ms", 500.0)),
        "interval_cv_limit_pct": float(settings.get("interval_cv_limit_pct", preset.get("interval_cv_limit_pct", 10.0))),
        "hold_cv_limit_pct": float(settings.get("hold_cv_limit_pct", preset.get("hold_cv_limit_pct", 25.0))),
        "max_outlier_ratio_pct": float(settings.get("max_outlier_ratio_pct", 1.0)),
        "pause_gap_min_ms": float(settings.get("pause_gap_min_ms", 1000.0)),
        "pause_gap_multiplier": float(settings.get("pause_gap_multiplier", 5.0)),
        "rolling_window_size": int(settings.get("rolling_window_size", 500)),
        "chart_max_points": int(settings.get("chart_max_points", 2000)),
        "mouse_mold": str(settings.get("mouse_mold") or ""),
        "probe_note": str(settings.get("probe_note") or ""),
        "manual_segment_sec": float(settings.get("manual_segment_sec") or MANUAL_SEGMENT_SEC_DEFAULT),
    }
    return out


def _metrics_issue_tags(metrics: dict[str, Any], settings: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    tags: list[str] = []
    manual = _is_manual_profile(settings)

    def add(tag: str):
        if tag not in tags:
            tags.append(tag)

    if str(settings.get("capture_mode", "")).startswith("Windows Raw Input") is False:
        add("CAPTURE_SOURCE_INVALID")

    if int(metrics.get("chatter_count") or 0) > int(settings.get("max_chatter_count") or 0):
        add("CHATTER_HARD")
    extreme = is_extreme_cadence(settings)
    extra_count = int(metrics.get("true_extra_click_count") or metrics.get("duplicate_click_risk_count") or 0)
    if extreme:
        if extra_count > 0:
            add("TRUE_EXTRA_CLICK")
    elif extra_count > 0 or int(metrics.get("duplicate_click_risk_count") or 0) > 0:
        add("HIGH_PROBABILITY_DOUBLE_CLICK")
    if int(metrics.get("incomplete_rebound_count") or 0) > 0:
        add("INCOMPLETE_REBOUND")
    miss_slow = int(metrics.get("miss_or_slow_count") or 0)
    spike = int(metrics.get("long_interval_spike_count") or 0)
    if miss_slow > 0 or (not manual and spike > 0):
        add("MISS_OR_SLOW")
        add("LONG_INTERVAL_SPIKE_WARN")
    if metrics.get("setup_alignment_suspect"):
        add("SETUP_ALIGNMENT_SUSPECT")
    if int(metrics.get("fixture_actuation_too_short_count") or 0) > 0:
        add("FIXTURE_ACTUATION_TOO_SHORT")
    if int(metrics.get("low_hold_warning_count") or 0) > 0:
        add("LOW_HOLD_WARNING")
    if int(metrics.get("pause_gap_count") or 0) > 0:
        add("PAUSE_GAP_EXCLUDED")
    if int(metrics.get("timing_jitter_pair_count") or 0) > 0:
        add("TIMING_JITTER_PAIR")
    if (metrics.get("interval_cv_pct") is not None) and float(metrics.get("interval_cv_pct") or 0) > float(settings.get("interval_cv_limit_pct") or 999):
        add("INTERVAL_JITTER_WARN")
    if (metrics.get("hold_cv_pct") is not None) and float(metrics.get("hold_cv_pct") or 0) > float(settings.get("hold_cv_limit_pct") or 999):
        add("HOLD_VARIATION_WARN")

    hz_mismatch = False
    if not manual:
        try:
            set_hz = float(settings.get("fixture_hz") or settings.get("fixture_reference_hz") or 0)
        except Exception:
            set_hz = 0.0
        try:
            meas_hz = float(metrics.get("measured_hz")) if metrics.get("measured_hz") is not None else None
        except Exception:
            meas_hz = None
        if set_hz > 0 and meas_hz is not None and meas_hz > 0 and abs(meas_hz - set_hz) / set_hz >= 0.10:
            add("FIXTURE_HZ_MISMATCH")
            hz_mismatch = True

    expected = int(settings.get("expected_clicks") or settings.get("target_clicks") or 0)
    actual = int(metrics.get("click_count") or 0)
    allowed = int(settings.get("max_missed_count") or 0)
    if manual:
        add("MANUAL_PROFILE_NO_EXPECTED_COUNT")
        seg = compute_manual_segments(
            events,
            segment_sec=float(settings.get("manual_segment_sec") or MANUAL_SEGMENT_SEC_DEFAULT),
        )
        metrics["manual_segments"] = seg
        if seg.get("operator_fatigue"):
            add("OPERATOR_FATIGUE")
            metrics["fatigue_after_sec"] = seg.get("fatigue_after_sec")
    elif expected > 0:
        if actual < expected:
            missed = expected - actual
            if hz_mismatch or missed <= allowed:
                add("MISS_CLICK_WARN")
            else:
                add("MISS_CLICK_FAIL")
        elif actual > expected:
            extra = actual - expected
            if hz_mismatch or extra <= allowed:
                add("EXCESS_CLICK_COUNT_WARN")
            else:
                add("EXCESS_CLICK_COUNT_FAIL")
    if actual <= 0:
        add("INSUFFICIENT_CLICKS")

    target_button = str(settings.get("focus_button") or settings.get("button") or "")
    wrong = [e for e in events if e.get("button") and target_button and e.get("button") != target_button]
    if wrong:
        add("WRONG_BUTTON_DETECTED")
    return tags


def _result_from_tags(tags: list[str], metrics: dict[str, Any], settings: dict[str, Any] | None = None) -> str:
    settings = settings or {}
    manual = _is_manual_profile(settings)
    actual = int(metrics.get("click_count") or metrics.get("actual_clicks") or 0)

    # v0.1.3: manual profiles are observation-first. Human fatigue, long
    # pauses, interval CV, and missing expected count are not production hard
    # fails. Real hardware-risk evidence is still surfaced and can fail when
    # severe.
    if manual:
        if actual <= 0 or "INSUFFICIENT_CLICKS" in tags:
            return "FAIL"
        if "WRONG_BUTTON_DETECTED" in tags or "CAPTURE_SOURCE_INVALID" in tags:
            return "FAIL"
        if "CHATTER_HARD" in tags:
            return "FAIL"
        # A single accidental <30 ms pair in a manual run should be treated as
        # review evidence rather than automatic hardware failure. Repeated
        # double-click risk remains a FAIL candidate.
        duplicate_count = int(metrics.get("duplicate_click_risk_count") or metrics.get("high_probability_double_click_count") or 0)
        if "HIGH_PROBABILITY_DOUBLE_CLICK" in tags and duplicate_count >= 3:
            return "FAIL"
        warn_tags = [t for t in tags if t not in {"MANUAL_PROFILE_NO_EXPECTED_COUNT", "PAUSE_GAP_EXCLUDED"}]
        # Manual is operator-stability first. Clear outcomes for demos/interviews:
        # PASS = stable rhythm, no hardware-risk tags
        # WARN = fatigue / high CV / sparse doubles (explain as operator, not DUT)
        # FAIL = chatter / repeated doubles / wrong capture
        if "OPERATOR_FATIGUE" in tags or "INTERVAL_JITTER_WARN" in tags or "HOLD_VARIATION_WARN" in tags:
            return "WARN"
        if "HIGH_PROBABILITY_DOUBLE_CLICK" in tags:
            return "WARN"
        return "WARN" if warn_tags else "PASS"

    fail_tags = {"CHATTER_HARD", "CHATTER_BOUNCE", "TRUE_EXTRA_CLICK", "HIGH_PROBABILITY_DOUBLE_CLICK", "MISS_CLICK_FAIL", "EXCESS_CLICK_COUNT_FAIL", "INSUFFICIENT_CLICKS", "WRONG_BUTTON_DETECTED"}
    if is_extreme_cadence(settings):
        fail_tags = fail_tags - {"HIGH_PROBABILITY_DOUBLE_CLICK"}
    if any(t in fail_tags for t in tags):
        return "FAIL"
    warn_tags = [t for t in tags if t not in {"MANUAL_PROFILE_NO_EXPECTED_COUNT"}]
    if warn_tags:
        return "WARN"
    if str(metrics.get("health", "")).upper() == "FAIL":
        return "FAIL"
    if str(metrics.get("health", "")).upper() == "WARN":
        return "WARN"
    return "PASS"


def _row_severity(tags: list[str], status: str = "") -> str:
    hard_fail = {"CHATTER_HARD", "CHATTER_BOUNCE", "TRUE_EXTRA_CLICK", "HIGH_PROBABILITY_DOUBLE_CLICK", "MISS_CLICK_FAIL", "EXCESS_CLICK_COUNT_FAIL", "WRONG_BUTTON_DETECTED", "CAPTURE_SOURCE_INVALID"}
    orange = {"TIMING_JITTER_PAIR"}
    yellow = {"FIXTURE_ACTUATION_TOO_SHORT", "LOW_HOLD_WARNING", "INTERVAL_JITTER_WARN", "HOLD_VARIATION_WARN", "LONG_INTERVAL_SPIKE_WARN", "MISS_CLICK_WARN", "EXCESS_CLICK_COUNT_WARN", "INCOMPLETE_REBOUND", "MISS_OR_SLOW", "SETUP_ALIGNMENT_SUSPECT", "FIXTURE_HZ_MISMATCH", "OPERATOR_FATIGUE"}
    gray = {"PAUSE_GAP_EXCLUDED", "WARMUP_EXCLUDED", "MANUAL_PROFILE_NO_EXPECTED_COUNT"}
    if any(t in hard_fail for t in tags) or str(status).upper() == "FAIL":
        return "FAIL"
    if any(t in orange for t in tags):
        return "TIMING"
    if any(t in yellow for t in tags) or str(status).upper() == "WARN":
        return "WARN"
    if any(t in gray for t in tags):
        return "EXCLUDED"
    return "OK"


def annotate_events(events: list[dict[str, Any]], settings: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    duplicate = float(settings.get("duplicate_click_threshold_ms") or 30)
    chatter = float(settings.get("chatter_threshold_ms") or 8)
    too_short = float(settings.get("fixture_actuation_too_short_ms") or 5)
    low_hold = float(settings.get("low_hold_warning_ms") or 8)
    fixture_hz = float(settings.get("fixture_hz") or settings.get("fixture_reference_hz") or 0)
    expected_interval_ms = (1000.0 / fixture_hz) if fixture_hz > 0 else None
    pause = max(float(settings.get("pause_gap_min_ms") or 1000), (expected_interval_ms or 200.0) * float(settings.get("pause_gap_multiplier") or 5))
    target_button = str(settings.get("focus_button") or "")
    manual = _is_manual_profile(settings)
    accepted_idx = 0
    for e in events:
        row = dict(e)
        tags: list[str] = []
        interval = row.get("press_interval_ms")
        hold = row.get("hold_ms")
        accepted = bool(row.get("accepted"))
        existing_tags = [t.strip() for t in str(e.get("issue_tags") or "").replace(",", ";").split(";") if t.strip()]
        if e.get("warmup_excluded") or "WARMUP_EXCLUDED" in existing_tags:
            tags.append("WARMUP_EXCLUDED")
        if accepted:
            accepted_idx += 1
        row["click_index"] = accepted_idx if accepted else ""
        row["press_time_ms"] = row.get("press_elapsed_ms")
        row["release_time_ms"] = row.get("release_elapsed_ms") or row.get("elapsed_ms")
        row["expected_interval_ms"] = round(expected_interval_ms, 4) if expected_interval_ms is not None else ""
        row["expected_click_index"] = accepted_idx if (accepted and expected_interval_ms is not None) else ""
        row["expected_time_ms"] = round((accepted_idx - 1) * expected_interval_ms, 4) if (accepted and expected_interval_ms is not None) else ""
        if accepted and expected_interval_ms is not None and row.get("press_elapsed_ms") is not None:
            row["drift_ms"] = round(float(row.get("press_elapsed_ms")) - ((accepted_idx - 1) * expected_interval_ms), 4)
        else:
            row["drift_ms"] = ""
        if interval is not None and expected_interval_ms:
            row["interval_error_ms"] = round(float(interval) - expected_interval_ms, 4)
            row["interval_error_pct"] = round((float(interval) - expected_interval_ms) / expected_interval_ms * 100.0, 4)
        else:
            row["interval_error_ms"] = ""
            row["interval_error_pct"] = ""
        if row.get("button") != target_button:
            tags.append("WRONG_BUTTON_DETECTED")
        click_class = "RAW"
        if "WARMUP_EXCLUDED" in tags:
            click_class = "WARMUP_EXCLUDED"
        elif accepted and row.get("event_type") in (None, "click", "up"):
            click_class = classify_click(interval, hold, settings)
            tags.extend(class_to_tags(click_class, is_extreme_cadence(settings)))
            if click_class == "MISS_OR_SLOW" and "LONG_INTERVAL_SPIKE_WARN" not in tags:
                tags.append("LONG_INTERVAL_SPIKE_WARN")
            if hold is not None and float(hold) < too_short and "FIXTURE_ACTUATION_TOO_SHORT" not in tags:
                tags.append("FIXTURE_ACTUATION_TOO_SHORT")
            elif hold is not None and float(hold) < low_hold:
                tags.append("LOW_HOLD_WARNING")
        elif interval is not None:
            if float(interval) < chatter:
                tags.append("CHATTER_HARD")
            elif float(interval) < duplicate:
                tags.append("HIGH_PROBABILITY_DOUBLE_CLICK")
            elif float(interval) >= pause:
                tags.append("PAUSE_GAP_EXCLUDED")
        row["click_class"] = click_class
        if manual and not tags:
            pass
        row["issue_tags"] = ";".join(dict.fromkeys(tags))
        row["analysis_status"] = _row_severity(tags)
        row["result"] = row["analysis_status"]
        row["issue_detail"] = "; ".join(ISSUE_DESCRIPTIONS_ZH.get(t, t) for t in dict.fromkeys(tags))
        row["notes"] = row.get("issue_detail", "")
        out.append(row)
    out = apply_manual_delay_classes(out, settings)
    for row in out:
        tags = [t for t in str(row.get("issue_tags") or "").split(";") if t]
        row["analysis_status"] = _row_severity(tags)
        row["result"] = row["analysis_status"]
        row["issue_detail"] = "; ".join(ISSUE_DESCRIPTIONS_ZH.get(t, t) for t in dict.fromkeys(tags))
        row["notes"] = row.get("issue_detail", "")
    return out


def _verify_artifacts(paths: dict[str, str]) -> dict[str, Any]:
    required = ["summary_json", "detail_json", "all_click_log_csv", "engineering_html", "txt"]
    optional = ["engineering_xlsx"]
    status = {}
    missing = []
    for key in required + optional:
        value = paths.get(key) or ""
        exists = bool(value) and Path(value).exists()
        status[key] = {"path": value, "exists": exists, "optional": key in optional}
        if key in required and not exists:
            missing.append(key)
    return {"ok": not missing, "missing": missing, "status": status, "xlsx_skipped": not status.get("engineering_xlsx", {}).get("exists")}


RESULT_SEMANTICS_RUN_STATUS = "run_status"
LEGACY_HEURISTIC_ASSESSMENT_NOTE = (
    "Non-authoritative. Derived from configurable heuristics with no approved "
    "acceptance criterion; not a DUT PASS / WARN / FAIL. The authoritative "
    "outcome is run_status."
)
# compute_metrics health fields: heuristic verdicts, exported only under legacy_heuristic_assessment.
_LEGACY_HEALTH_METRIC_KEYS = ("health", "passed", "fail_reasons", "warn_reasons")


def _report_fallback_model(target: str, operator: str, settings: dict[str, Any], events: list[dict[str, Any]], run_id: str) -> dict[str, Any]:
    """Canonical model for callers without a frozen Results model (no expected-count promotion)."""
    from .completed_result import build_completed_result_model

    locked = normalize_settings(settings)
    locked.update(settings)
    locked["target_product"] = target or locked.get("target_product", "")
    return build_completed_result_model(locked=locked, events=list(events), run_id=run_id, target=target, operator=operator)


def write_reports(
    report_root: Path,
    target: str,
    operator: str,
    settings: dict[str, Any],
    events: list[dict[str, Any]],
    run_id: str,
    raw_events: list[dict[str, Any]] | None = None,
    completed_model: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write the full report bundle.

    Engineering HTML/XLSX render ``completed_model`` (the Results model); JSON,
    CSV, and TXT sidecars keep their legacy layout, except that ``result`` /
    ``run_status`` carry the authoritative run status and every legacy
    heuristic verdict field lives under ``legacy_heuristic_assessment``.
    """
    report_root.mkdir(parents=True, exist_ok=True)
    if completed_model is None:
        completed_model = _report_fallback_model(target, operator, settings, events, run_id)
    run_status = str(completed_model["run"]["run_status"])
    settings_norm = normalize_settings(settings)
    settings_norm.update(settings)
    settings_norm = normalize_auto_settings({"settings": settings_norm})
    settings_norm["target_product"] = target or settings_norm.get("target_product", "")
    events = annotate_events(events, settings_norm)
    legacy_payload = build_payload(target, operator, settings_norm, events, run_id=run_id)
    metrics = dict(legacy_payload.get("metrics") or {})
    tags = _metrics_issue_tags(metrics, settings_norm, events)
    legacy_result = _result_from_tags(tags, metrics, settings_norm)
    legacy_health = {key: metrics.pop(key) for key in _LEGACY_HEALTH_METRIC_KEYS if key in metrics}
    expected = int(settings_norm.get("expected_clicks") or settings_norm.get("target_clicks") or 0)
    actual = int(metrics.get("click_count") or 0)
    metrics.update({
        "result": run_status,
        "issue_tags": tags,
        "expected_clicks": None if _is_manual_profile(settings_norm) else expected,
        "actual_clicks": actual,
        "excess_click_count": None if _is_manual_profile(settings_norm) else max(0, actual - expected) if expected else 0,
        "missed_click_count": None if _is_manual_profile(settings_norm) else max(0, expected - actual) if expected else None,
        "duration_sec": float(settings_norm.get("duration_sec") or 0),
        "fixture_hz": float(settings_norm.get("fixture_hz") or settings_norm.get("fixture_reference_hz") or 0),
        "manual_mode": _is_manual_profile(settings_norm),
    })
    click_session = _click_session_summary(legacy_result, settings_norm, metrics, tags)
    rid = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    names = artifact_names(rid)
    summary_path = report_root / names["summary_json"]
    detail_path = report_root / names["detail_json"]
    csv_path = report_root / names["all_click_log_csv"]
    xlsx_path = report_root / names["engineering_xlsx"]
    html_path = report_root / names["engineering_html"]
    txt_path = report_root / names["txt"]
    paths: dict[str, str] = {
        "summary_json": str(summary_path),
        "detail_json": str(detail_path),
        "all_click_log_csv": str(csv_path),
        "engineering_xlsx": str(xlsx_path),
        "engineering_html": str(html_path),
        "txt": str(txt_path),
    }
    summary = {
        "schema_version": SUMMARY_SCHEMA,
        "tool_id": TOOL_ID,
        "tool_name": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "run_id": run_id,
        "run_state": "COMPLETED",
        "run_status": run_status,
        "result": run_status,
        "result_semantics": RESULT_SEMANTICS_RUN_STATUS,
        "created_at": now_iso(),
        "completed_at": now_iso(),
        "target_product": target or "",
        "operator": operator or "",
        "completed_cycles": 1,
        "target_cycles": 1,
        "failed_cycles": None,
        "settings": settings_norm,
        "metrics": metrics,
        "issue_tags": tags,
        "engineering_summary_zh": _engineering_summary(settings_norm, metrics, tags),
        "engineering_reports": paths,
        "host_test_environment": build_host_environment(settings_norm),
        "legacy_heuristic_assessment": {
            "authoritative": False,
            "note": LEGACY_HEURISTIC_ASSESSMENT_NOTE,
            "result": legacy_result,
            "issue_tags": tags,
            "metrics_health": legacy_health,
            "operator_summary_zh": _operator_summary(legacy_result, settings_norm, metrics, tags),
            "why_result_zh": click_session.get("why_result_zh"),
            "why_result_en": click_session.get("why_result_en"),
            "field_summary_zh": click_session.get("field_summary_zh"),
            "field_summary_en": click_session.get("field_summary_en"),
            "next_steps_zh": ["Manual profile 若只有 timing 變動，請先以同一按鍵重測或改用治具 profile 確認硬體連點。", "若出現 chatter 或多筆 <30ms interval，請開啟 Engineering HTML/XLSX 查看 All Click Log。"],
            "next_steps_en": ["If manual mode only shows timing variation, retest the same button or use fixture profile before judging hardware failure.", "If chatter or repeated <30 ms intervals appear, open Engineering HTML/XLSX and inspect the All Click Log."],
            "click_session_summary": click_session,
            "click_operator_findings": {
                "issue_tags": tags,
                "button": settings_norm.get("focus_button"),
                "profile_name": settings_norm.get("profile_name"),
                "manual_mode": _is_manual_profile(settings_norm),
                "profile_type": click_session.get("profile_type"),
                "expected_count_source": click_session.get("expected_count_source"),
                "fixture_hz": settings_norm.get("fixture_hz") or settings_norm.get("fixture_reference_hz"),
                "expected_clicks": click_session.get("expected_clicks"),
                "actual_clicks": actual,
                "hardware_defect_result": click_session.get("hardware_defect_result"),
                "manual_observation_result": click_session.get("manual_observation_result"),
            },
        },
    }
    detail = {
        "schema_version": 1,
        "tool_id": TOOL_ID,
        "tool_name": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "created_at": now_iso(),
        "run_id": run_id,
        "run_status": run_status,
        "result_semantics": RESULT_SEMANTICS_RUN_STATUS,
        "target": target,
        "operator": operator,
        "settings": settings_norm,
        "metrics": metrics,
        "events": events,
        "all_click_events": events,
        "legacy_payload": {
            **legacy_payload,
            "metrics": {
                key: value for key, value in (legacy_payload.get("metrics") or {}).items()
                if key not in _LEGACY_HEALTH_METRIC_KEYS
            },
        },
        "legacy_heuristic_assessment": {
            "authoritative": False,
            "note": LEGACY_HEURISTIC_ASSESSMENT_NOTE,
            "result": legacy_result,
            "issue_tags": tags,
            "metrics_health": legacy_health,
        },
        "engineering_reports": paths,
        "raw_down_up_events": raw_events or [],
    }
    # Write engineering artifacts first, then write Summary JSON with verified artifact paths.
    detail_path.write_text(json.dumps(detail, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    _write_all_click_csv(csv_path, events)
    host_info = host_information_rows(build_host_environment(completed_model["run"]["settings"]), tool_version=TOOL_VERSION)
    report_kwargs = {"host_info": host_info, "generated_at": summary["created_at"]}
    xlsx_written = write_report_xlsx(xlsx_path, completed_model, **report_kwargs)
    if not xlsx_written:
        paths["engineering_xlsx"] = ""
        summary["xlsx_skipped"] = True
        summary["xlsx_skip_reason"] = "openpyxl not installed"
        summary["engineering_reports"] = paths
        detail["engineering_reports"] = paths
    write_report_html(html_path, completed_model, **report_kwargs)
    txt_path.write_text(_summary_txt(summary), encoding="utf-8")
    # Write provisional Summary before existence verification so summary_json itself is a verified artifact.
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    verification = _verify_artifacts(paths)
    summary["report_artifacts_verified"] = verification
    detail["report_artifacts_verified"] = verification
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    # Rewrite detail after verification so the engineering report package is self-describing.
    detail_path.write_text(json.dumps(detail, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    if not verification.get("ok"):
        raise RuntimeError("Mouse Click report artifact generation incomplete: " + ", ".join(verification.get("missing") or []))
    return paths

def _write_all_click_csv(path: Path, events: list[dict[str, Any]]) -> None:
    headers = [
        "click_index", "index", "timestamp", "analysis_status", "result", "issue_tags", "issue_detail", "button", "event_type", "accepted",
        "press_time_ms", "release_time_ms", "hold_ms", "press_interval_ms", "expected_interval_ms", "expected_click_index", "expected_time_ms", "drift_ms", "interval_error_ms", "interval_error_pct",
        "press_elapsed_ms", "release_elapsed_ms", "elapsed_ms", "interval_ms",
        "x", "y", "capture_source", "device_source", "raw_hdevice", "raw_dx", "raw_dy", "flags", "notes",
    ]
    for e in events:
        for k in e.keys():
            if k not in headers:
                headers.append(k)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for e in events:
            row = dict(e)
            for k, v in list(row.items()):
                if isinstance(v, (list, dict)):
                    row[k] = json.dumps(v, ensure_ascii=False)
            writer.writerow(row)


def _issue_interpretation_map(tags: list[str]) -> dict[str, dict[str, str]]:
    return {
        str(t): {
            "zh": ISSUE_DESCRIPTIONS_ZH.get(str(t), str(t)),
            "en": ISSUE_DESCRIPTIONS_EN.get(str(t), str(t)),
        }
        for t in tags
    }


def _hardware_defect_result(tags: list[str], metrics: dict[str, Any], settings: dict[str, Any]) -> str:
    manual = _is_manual_profile(settings)
    if "CHATTER_HARD" in tags or "WRONG_BUTTON_DETECTED" in tags:
        return "FAIL"
    duplicate_count = int(metrics.get("duplicate_click_risk_count") or metrics.get("high_probability_double_click_count") or 0)
    if "HIGH_PROBABILITY_DOUBLE_CLICK" in tags:
        if not manual or duplicate_count >= 3:
            return "FAIL"
        return "WARN"
    if any(t in tags for t in ["MISS_CLICK_FAIL", "EXCESS_CLICK_COUNT_FAIL"]):
        return "FAIL"
    if any(t in tags for t in ["MISS_CLICK_WARN", "EXCESS_CLICK_COUNT_WARN", "FIXTURE_ACTUATION_TOO_SHORT", "LOW_HOLD_WARNING", "FIXTURE_HZ_MISMATCH"]):
        return "WARN"
    return "PASS"


def _manual_observation_result(tags: list[str], metrics: dict[str, Any], settings: dict[str, Any]) -> str:
    if not _is_manual_profile(settings):
        return "NOT_APPLICABLE"
    observation_tags = {
        "LONG_INTERVAL_SPIKE_WARN", "TIMING_JITTER_PAIR", "INTERVAL_JITTER_WARN", "HOLD_VARIATION_WARN",
        "PAUSE_GAP_EXCLUDED", "MANUAL_PROFILE_NO_EXPECTED_COUNT", "LOW_HOLD_WARNING", "FIXTURE_ACTUATION_TOO_SHORT",
    }
    if any(t in tags for t in ["CHATTER_HARD", "HIGH_PROBABILITY_DOUBLE_CLICK", "WRONG_BUTTON_DETECTED"]):
        return "WARN"
    if any(t in observation_tags for t in tags):
        return "WARN"
    return "PASS" if int(metrics.get("click_count") or 0) > 0 else "FAIL"


def _click_why_result(result: str, settings: dict[str, Any], metrics: dict[str, Any], tags: list[str], lang: str = "zh") -> str:
    manual = _is_manual_profile(settings)
    actual = metrics.get("actual_clicks", metrics.get("click_count", "-"))
    double_count = int(metrics.get("duplicate_click_risk_count") or 0)
    chatter_count = int(metrics.get("chatter_count") or 0)
    if lang == "en":
        if manual:
            if result == "FAIL":
                return f"Manual Click result is FAIL because hardware-risk evidence was detected, such as chatter={chatter_count} or repeated double-click risk={double_count}."
            if tags:
                return "Manual Click result is WARN because timing variation or review-only observations were detected. Manual profile does not hard-fail expected-count mismatch; it separates human/fixture stability from confirmed hardware failure."
            return f"Manual Click result is PASS because {actual} clicks were captured and no double-click, chatter, wrong-button, or major timing issue was detected."
        if "FIXTURE_HZ_MISMATCH" in tags:
            extra_n = int(metrics.get("true_extra_click_count") or 0) + int(metrics.get("chatter_bounce_count") or 0)
            return (
                f"Set {settings.get('fixture_hz')}Hz vs measured ~{metrics.get('measured_hz')}Hz; "
                f"count {actual}/{metrics.get('expected_clicks') or settings.get('expected_clicks')} is cadence mismatch, not extra clicks (extra={extra_n})."
            )
        return "Fixture Click result is based on expected count, double-click/chatter thresholds, hold-time quality, and interval repeatability."
    if manual:
        if result == "FAIL":
            return f"Manual Click 結果為 FAIL，原因是偵測到硬體風險證據，例如 chatter={chatter_count} 或重複 double-click risk={double_count}。"
        if tags:
            return "Manual Click 結果為 WARN，因為偵測到人工/治具 timing 變動或需要複查的觀察項。Manual profile 不會因 expected count 不存在而硬判漏點，會把人手/治具穩定度與硬體故障分開解讀。"
        return f"Manual Click 結果為 PASS，因為已擷取 {actual} 次 click，未偵測到連點、chatter、錯誤按鍵或主要 timing 異常。"
    if "FIXTURE_HZ_MISMATCH" in tags:
        extra_n = int(metrics.get("true_extra_click_count") or 0) + int(metrics.get("chatter_bounce_count") or 0)
        return (
            f"設定 {settings.get('fixture_hz')}Hz、實測 ~{metrics.get('measured_hz')}Hz；"
            f"次數 {actual}/{metrics.get('expected_clicks') or settings.get('expected_clicks')} 是節拍不符，extra={extra_n}（連點）需分開看。"
        )
    return "Fixture Click 結果根據 expected count、double-click/chatter threshold、hold-time 品質與 interval 重複性判定。"


def _click_field_summary(result: str, settings: dict[str, Any], metrics: dict[str, Any], tags: list[str], lang: str = "en") -> str:
    button = settings.get("focus_button") or settings.get("button") or ""
    profile = settings.get("profile_name") or settings.get("test_profile") or ""
    manual = _is_manual_profile(settings)
    actual = metrics.get("actual_clicks", metrics.get("click_count", "-"))
    expected = metrics.get("expected_clicks") or settings.get("expected_clicks") or settings.get("target_clicks")
    double_count = metrics.get("duplicate_click_risk_count", metrics.get("high_probability_double_click_count", 0))
    chatter_count = metrics.get("chatter_count", 0)
    interval_cv = metrics.get("interval_cv_pct", "-")
    hold_cv = metrics.get("hold_cv_pct", "-")
    if lang == "zh":
        expected_text = "Manual 不硬判" if manual else str(expected or "-")
        main = _click_why_result(result, settings, metrics, tags, "zh")
        return "\n".join([
            f"DUT: {settings.get('target_product','')}",
            f"Test: Mouse Click Stability Analyzer, button={button}, profile={profile}, actual={actual}, expected={expected_text}.",
            f"Result: {result}. double-click risk={double_count}; chatter={chatter_count}; interval CV={interval_cv}%; hold CV={hold_cv}%.",
            f"Main point: {main}",
        ])
    expected_text = "manual observation" if manual else str(expected or "-")
    main = _click_why_result(result, settings, metrics, tags, "en")
    return "\n".join([
        f"Test: Mouse Click Stability Analyzer, button={button}, profile={profile}, actual={actual}, expected={expected_text}.",
        f"Result: {result}. double-click risk={double_count}; chatter={chatter_count}; interval CV={interval_cv}%; hold CV={hold_cv}%.",
        f"Main point: {main}",
    ])


def _click_session_summary(result: str, settings: dict[str, Any], metrics: dict[str, Any], tags: list[str]) -> dict[str, Any]:
    manual = _is_manual_profile(settings)
    expected = int(settings.get("expected_clicks") or settings.get("target_clicks") or 0)
    actual = int(metrics.get("click_count") or metrics.get("actual_clicks") or 0)
    profile_type = "manual_human" if manual else "fixture_validation"
    expected_source = "not_applicable_manual" if manual else "fixture_profile"
    return {
        "session_mode": "manual" if manual else "fixture_auto",
        "profile_type": profile_type,
        "profile_name": settings.get("profile_name"),
        "button": settings.get("focus_button") or settings.get("button"),
        "completed_clicks": actual,
        "expected_clicks": None if manual else expected,
        "expected_count_source": expected_source,
        "high_probability_double_click_count": int(metrics.get("duplicate_click_risk_count") or 0),
        "chatter_count": int(metrics.get("chatter_count") or 0),
        "missing_click_count": None if manual else max(0, expected - actual),
        "excess_click_count": None if manual else max(0, actual - expected),
        "long_interval_spike_count": int(metrics.get("long_interval_spike_count") or 0),
        "timing_jitter_pair_count": int(metrics.get("timing_jitter_pair_count") or 0),
        "interval_cv_pct": metrics.get("interval_cv_pct"),
        "hold_cv_pct": metrics.get("hold_cv_pct"),
        "manual_observation_result": _manual_observation_result(tags, metrics, settings),
        "hardware_defect_result": _hardware_defect_result(tags, metrics, settings),
        "issue_tags": tags,
        "issue_interpretation_map": _issue_interpretation_map(tags),
        "why_result_zh": _click_why_result(result, settings, metrics, tags, "zh"),
        "why_result_en": _click_why_result(result, settings, metrics, tags, "en"),
        "field_summary_zh": _click_field_summary(result, settings, metrics, tags, "zh"),
        "field_summary_en": _click_field_summary(result, settings, metrics, tags, "en"),
        "result": result,
    }


def _operator_summary(result: str, settings: dict[str, Any], metrics: dict[str, Any], tags: list[str]) -> str:
    button = settings.get("focus_button") or settings.get("button")
    expected = metrics.get("expected_clicks") or settings.get("target_clicks")
    actual = metrics.get("click_count") or metrics.get("actual_clicks")
    manual = _is_manual_profile(settings)
    double_count = metrics.get("duplicate_click_risk_count", 0)
    chatter_count = metrics.get("chatter_count", 0)
    if manual:
        if result == "PASS":
            return f"{button} manual click 測試通過。實際擷取 {actual} 次 click；Manual profile 不使用 expected count 硬判漏點，且未偵測到連點或 chatter。"
        if result == "WARN":
            return f"{button} manual click 測試為 WARN。實際擷取 {actual} 次 click；主要是人工/治具 timing 觀察項，不代表已確認硬體故障。Issue: {', '.join(tags) if tags else '-'}。"
        return f"{button} manual click 測試為 {result}。實際擷取 {actual} 次 click；偵測到需要工程確認的硬體風險證據，例如 double risk={double_count}, chatter={chatter_count}。"
    if result == "PASS":
        return f"{button} fixture click 測試通過。實際 {actual}/{expected} clicks，未偵測到連點、明顯漏點或主要治具異常。"
    return f"{button} fixture click 測試為 {result}。實際 {actual}/{expected} clicks，主要 issue：{', '.join(tags) if tags else '請查看 detail log'}。"


def _engineering_summary(settings: dict[str, Any], metrics: dict[str, Any], tags: list[str]) -> str:
    return (
        f"Button={settings.get('focus_button')}, fixture_hz={settings.get('fixture_hz') or settings.get('fixture_reference_hz')}, "
        f"measured_hz={metrics.get('measured_hz')}, measured_interval={metrics.get('measured_interval_ms')}ms, "
        f"duration={settings.get('duration_sec')}s, interval_avg={metrics.get('interval_avg_ms')}ms, "
        f"interval_cv={metrics.get('interval_cv_pct')}%, hold_avg={metrics.get('hold_avg_ms')}ms, "
        f"timing_bias={metrics.get('timing_bias_ms')}ms, p99_abs_error={metrics.get('p99_abs_error_ms')}ms, "
        f"chatter={metrics.get('chatter_count')}, duplicate_risk={metrics.get('duplicate_click_risk_count')}, tags={tags}"
    )


def _summary_txt(summary: dict[str, Any]) -> str:
    m = summary.get("metrics") or {}
    lines = [
        "Mouse Click Stability Analyzer Summary",
        "=" * 32,
        f"Run Status: {summary.get('run_status') or summary.get('result')}",
        f"Tool: {summary.get('tool_name')} {summary.get('tool_version')}",
        f"Created: {summary.get('created_at')}",
        f"Button: {(summary.get('settings') or {}).get('focus_button')}",
        f"Clicks: {m.get('click_count')} / {m.get('expected_clicks') if m.get('expected_clicks') is not None else 'manual observation'}",
        f"Set Hz / Measured Hz: {(summary.get('settings') or {}).get('fixture_hz')} / {m.get('measured_hz')}",
        f"Target ms / Measured ms: {m.get('reference_interval_ms')} / {m.get('measured_interval_ms')}",
        f"Timing bias / σ / P99 |error|: {m.get('timing_bias_ms')} / {m.get('timing_sigma_ms')} / {m.get('p99_abs_error_ms')} ms",
        f"Within ±0.5ms / ±1ms: {m.get('within_0_5ms_pct')}% / {m.get('within_1ms_pct')}%",
        f"Issue Tags: {', '.join(summary.get('issue_tags') or [])}",
        "",
        summary.get("engineering_summary_zh", ""),
    ]
    return "\n".join(lines)


class ClickToolApp:
    def __init__(self, root, *, auto_settings: dict[str, Any] | None = None, run_id: str | None = None, report_root: str | Path | None = None, target: str = "", operator: str = "", auto_mode: bool = False, self_test_events: list[dict[str, Any]] | None = None, standalone_mode: bool = False):
        import tkinter as tk
        from tkinter import ttk, messagebox
        from collections import defaultdict, deque
        self.tk = tk; self.ttk = ttk; self.messagebox = messagebox
        self.root = root
        self.auto_mode = auto_mode
        self.standalone_mode = True
        self.target = target
        self.operator = operator or ""
        self.run_id = run_id or _now_run_id()
        default_root = Path(__file__).resolve().parents[2] / "reports"
        self.report_root = Path(report_root or default_root)
        self.self_test_events = self_test_events
        self.events: list[dict[str, Any]] = []
        self.raw_events: list[dict[str, Any]] = []
        self.running = False
        self.completed = False
        self.raw_input = None
        self.device_press_queues: dict[tuple[str, str], deque] = defaultdict(deque)
        self.capture_lock = threading.Lock()
        self.first_press_time = None
        self.last_press_time = None
        self.first_release_time = None
        self.last_release_time = None
        self.start_time = None
        self.end_time = None
        self.last_metric_update = 0.0
        self.last_chart_update = 0.0
        self.report_paths: dict[str, str] = {}
        self.handoff_payload: dict[str, Any] = {}
        self._applying_profile = False
        self._applying_rules = False
        self._ui_dirty = False
        self._locked_button = "Left"
        self._locked_capture_is_raw = True
        self.overlay_events: list[dict[str, Any]] = []
        self.overlay_metrics: dict[str, Any] = {}
        self.overlay_label = "A"
        self.overlay_path = ""
        self.listening = False
        self.report_written = False
        self._status_alert = ""
        self._ignore_arm_until = 0.0
        self.session_runs: list[dict[str, Any]] = []
        self.locked_setting_snapshot: dict[str, Any] | None = None

        cfg = normalize_auto_settings(auto_settings or {"settings": dict(PROFILE_PRESETS["Manual_Left_Stable"])})
        self.cfg = cfg

        self.root.title(TOOL_NAME)
        self.root.geometry("1280x840")
        self.root.minsize(1100, 720)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.configure(bg="#f5f5f7")
        self._build_ui()
        try:
            self.root.state("zoomed")
        except Exception:
            self._center_window()
        self._apply_cfg_to_vars(cfg)
        self._update_settings_preview()
        self._apply_mode_ui()
        self._update_control_states()
        self._wheel_log_count = 0
        self._chart_log_count = 0
        self.root.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
        self.root.bind("<F5>", self._on_f5_hotkey)
        self.root.bind("<space>", self._on_space_hotkey)
        self.root.bind("<Escape>", self._on_escape_hotkey)
        self.auto_delay_end = None
        self.auto_pending_start = False
        self._tick()
        if self.auto_mode:
            delay = max(0.0, float(cfg.get("auto_start_delay_sec") or 0))
            self.auto_pending_start = True
            self.auto_delay_end = time.perf_counter() + delay
            self.phase_var.set("PREPARE")
            self.status_var.set(f"Auto starts in {delay:.0f}s. Place click fixture now.")
            self.root.after(int(delay * 1000) + 100, self._auto_delayed_start)
        else:
            self.root.after(200, self.enter_listen)

    def _auto_delayed_start(self):
        if not self.auto_mode or self.completed or self.running:
            return
        self.auto_pending_start = False
        self.auto_delay_end = None
        self.start()

    def _build_ui(self):
        tk = self.tk; ttk = self.ttk
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Root.TFrame", background="#f5f5f7")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Card.TLabelframe", background="#ffffff", borderwidth=1, relief="solid")
        style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#1d1d1f", font=("Segoe UI", 10, "bold"))
        style.configure("Title.TLabel", background="#f5f5f7", foreground="#1d1d1f", font=("Segoe UI", 18, "bold"))
        style.configure("Big.TLabel", background="#ffffff", foreground="#1d1d1f", font=("Segoe UI", 48, "bold"))
        style.configure("Subtle.TLabel", background="#ffffff", foreground="#6e6e73", font=("Segoe UI", 9))
        style.configure("Alert.TLabel", background="#ffffff", foreground="#c0392b", font=("Segoe UI", 10, "bold"))
        style.configure("Primary.TButton", padding=(12, 8), font=("Segoe UI", 9, "bold"))
        style.configure("Secondary.TButton", padding=(10, 7), font=("Segoe UI", 9))
        outer = ttk.Frame(self.root, padding=14, style="Root.TFrame")
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, style="Root.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text=TOOL_NAME, style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="?", width=3, style="Secondary.TButton", command=self._show_guide).pack(side="right")
        ttk.Button(header, text="Advanced", style="Secondary.TButton", command=self._toggle_advanced).pack(side="right", padx=(0, 8))
        body = ttk.Frame(outer, style="Root.TFrame")
        body.pack(fill="both", expand=True, pady=(12, 0))
        left = ttk.Frame(body, style="Root.TFrame", width=300)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        self._left_panel = left
        right = ttk.Frame(body, style="Root.TFrame")
        right.pack(side="left", fill="both", expand=True)

        setup = ttk.LabelFrame(left, text="Setup", padding=12, style="Card.TLabelframe")
        setup.pack(fill="x")
        self.profile_var = tk.StringVar()
        self.button_var = tk.StringVar()
        self.fixture_var = tk.StringVar()
        self.duration_var = tk.StringVar()
        self.expected_var = tk.StringVar()
        self.capture_var = tk.StringVar()
        self.mode_choice_var = tk.StringVar(value="Manual")
        self.device_name_var = tk.StringVar(value=self.target or "")
        self.segment_var = tk.StringVar(value=str(int(MANUAL_SEGMENT_SEC_DEFAULT)))
        self.param_widgets = []
        self._combo_widgets = []
        self._editable_combos = []
        self._fixture_rows = []
        self._manual_rows = []

        ttk.Label(setup, text="Mode", background="#ffffff").grid(row=0, column=0, sticky="w", pady=5, padx=(0, 8))
        mode_row = ttk.Frame(setup, style="Card.TFrame")
        mode_row.grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Radiobutton(mode_row, text="Manual", variable=self.mode_choice_var, value="Manual", command=self._on_mode_choice).pack(side="left")
        ttk.Radiobutton(mode_row, text="Fixture", variable=self.mode_choice_var, value="Fixture", command=self._on_mode_choice).pack(side="left", padx=(8, 0))

        ttk.Label(setup, text="Device", background="#ffffff").grid(row=1, column=0, sticky="w", pady=5, padx=(0, 8))
        device_e = ttk.Entry(setup, textvariable=self.device_name_var, width=22)
        device_e.grid(row=1, column=1, sticky="ew", pady=5)
        self.param_widgets.append(device_e)

        ttk.Label(setup, text="Button", background="#ffffff").grid(row=2, column=0, sticky="w", pady=5, padx=(0, 8))
        button_w = ttk.Combobox(setup, textvariable=self.button_var, values=BUTTONS, width=20, state="readonly")
        button_w.grid(row=2, column=1, sticky="ew", pady=5)
        self.param_widgets.append(button_w)
        self._combo_widgets.append(button_w)

        self._lbl_hz = ttk.Label(setup, text="Fixture Hz", background="#ffffff")
        self._lbl_hz.grid(row=3, column=0, sticky="w", pady=5, padx=(0, 8))
        hz_w = ttk.Combobox(setup, textvariable=self.fixture_var, values=["5", "10", "20", "40"], width=20, state="normal")
        hz_w.grid(row=3, column=1, sticky="ew", pady=5)
        self.param_widgets.append(hz_w)
        self._combo_widgets.append(hz_w)
        self._editable_combos.append(hz_w)
        self._fixture_rows.extend([self._lbl_hz, hz_w])

        self._lbl_dur = ttk.Label(setup, text="Duration sec", background="#ffffff")
        self._lbl_dur.grid(row=4, column=0, sticky="w", pady=5, padx=(0, 8))
        dur_w = ttk.Combobox(setup, textvariable=self.duration_var, values=["30", "60", "120", "300", "3600"], width=20, state="normal")
        dur_w.grid(row=4, column=1, sticky="ew", pady=5)
        self.param_widgets.append(dur_w)
        self._combo_widgets.append(dur_w)
        self._editable_combos.append(dur_w)
        self._fixture_rows.extend([self._lbl_dur, dur_w])

        self._lbl_exp = ttk.Label(setup, text="Expected", background="#ffffff")
        self._lbl_exp.grid(row=5, column=0, sticky="w", pady=5, padx=(0, 8))
        exp_w = ttk.Entry(setup, textvariable=self.expected_var, width=22, state="readonly")
        exp_w.grid(row=5, column=1, sticky="ew", pady=5)
        self.param_widgets.append(exp_w)
        self._fixture_rows.extend([self._lbl_exp, exp_w])

        self._lbl_seg = ttk.Label(setup, text="Segment sec", background="#ffffff")
        self._lbl_seg.grid(row=6, column=0, sticky="w", pady=5, padx=(0, 8))
        seg_w = ttk.Combobox(setup, textvariable=self.segment_var, values=["5", "10", "15"], width=20, state="normal")
        seg_w.grid(row=6, column=1, sticky="ew", pady=5)
        self.param_widgets.append(seg_w)
        self._combo_widgets.append(seg_w)
        self._editable_combos.append(seg_w)
        self._manual_rows.extend([self._lbl_seg, seg_w])

        setup.columnconfigure(0, minsize=100)
        setup.columnconfigure(1, weight=1)
        self.mouse_mold_var = tk.StringVar()
        self.probe_note_var = tk.StringVar()
        self.button_var.trace_add("write", lambda *_: self._on_button_changed())
        self.fixture_var.trace_add("write", lambda *_: self._update_expected_from_duration())
        self.duration_var.trace_add("write", lambda *_: self._update_expected_from_duration())

        rules = ttk.LabelFrame(left, text="Rules", padding=12, style="Card.TLabelframe")
        rules.pack(fill="x", pady=(10, 0))
        self.rule_preset_var = tk.StringVar(value="Strict")
        preset_row = ttk.Frame(rules, style="Card.TFrame")
        preset_row.pack(fill="x")
        for i, (key, label) in enumerate(RULE_PRESET_LABELS):
            short = key
            ttk.Button(preset_row, text=short, style="Secondary.TButton", command=lambda k=key: self._set_rule_preset(k)).grid(row=0, column=i, sticky="ew", padx=2, pady=2)
            preset_row.columnconfigure(i, weight=1)
        self.chatter_var = tk.StringVar()
        self.double_var = tk.StringVar()
        self.short_hold_var = tk.StringVar()
        self.low_hold_var = tk.StringVar()
        self.interval_cv_var = tk.StringVar()
        self._rules_advanced = ttk.Frame(rules, style="Card.TFrame")
        adv_rows = [
            ("Chatter hard ms", self.chatter_var),
            ("Double click ms", self.double_var),
            ("Too-short hold ms", self.short_hold_var),
            ("Low hold warn ms", self.low_hold_var),
            ("Interval CV %", self.interval_cv_var),
        ]
        for i, (label, var) in enumerate(adv_rows):
            ttk.Label(self._rules_advanced, text=label, background="#ffffff").grid(row=i, column=0, sticky="w", pady=4, padx=(0, 8))
            w = ttk.Entry(self._rules_advanced, textvariable=var, width=12)
            w.grid(row=i, column=1, sticky="w", pady=4)
            self.param_widgets.append(w)

        self.controls = ttk.LabelFrame(left, text="Controls", padding=12, style="Card.TLabelframe")
        if not self.auto_mode:
            self.controls.pack(fill="x", pady=(10, 0))
            self.stop_button = ttk.Button(self.controls, text="Stop (F5 / Esc)", style="Primary.TButton", command=self.stop_run)
            self.stop_button.pack(fill="x", pady=3)
            self.new_run_button = ttk.Button(self.controls, text="New Run", style="Secondary.TButton", command=self.new_run)
            self.new_run_button.pack(fill="x", pady=3)
            self.finish_button = ttk.Button(self.controls, text="Finish & Generate Report", style="Primary.TButton", command=self.finish_and_return)
            self.finish_button.pack(fill="x", pady=3)
            self.save_as_button = ttk.Button(self.controls, text="Save Report As…", style="Secondary.TButton", command=self.save_report_as)
            self.save_as_button.pack(fill="x", pady=3)
            self._advanced_box = ttk.Frame(self.controls, style="Card.TFrame")
            ttk.Button(self._advanced_box, text="Compare previous run", style="Secondary.TButton", command=self.load_overlay_run).pack(fill="x", pady=3)
            ttk.Button(self._advanced_box, text="Clear compare", style="Secondary.TButton", command=self.clear_overlay).pack(fill="x", pady=3)
            mold_row = ttk.Frame(self._advanced_box, style="Card.TFrame")
            mold_row.pack(fill="x", pady=(6, 0))
            ttk.Label(mold_row, text="Mold", background="#ffffff").pack(anchor="w")
            mold_e = ttk.Entry(mold_row, textvariable=self.mouse_mold_var)
            mold_e.pack(fill="x")
            ttk.Label(mold_row, text="Probe", background="#ffffff").pack(anchor="w", pady=(4, 0))
            probe_e = ttk.Entry(mold_row, textvariable=self.probe_note_var)
            probe_e.pack(fill="x")
            self.param_widgets.extend([mold_e, probe_e])
        else:
            for w in self.param_widgets:
                try:
                    w.configure(state="disabled")
                except Exception:
                    pass

        status_card = ttk.LabelFrame(right, text="Live", padding=16, style="Card.TLabelframe")
        status_card.pack(fill="x")
        self.phase_var = tk.StringVar(value="LISTEN")
        self.countdown_var = tk.StringVar(value="--")
        self.click_count_var = tk.StringVar(value="0")
        self.last_interval_var = tk.StringVar(value="--")
        self.last_hold_var = tk.StringVar(value="--")
        self.status_var = tk.StringVar(value=SOP_LISTEN)
        self.dut_score_var = tk.StringVar(value="--")
        self.setup_score_var = tk.StringVar(value="--")
        self.mode_var = tk.StringVar(value="Manual · stability")
        self.extra_count_var = tk.StringVar(value="--")
        self.rebound_count_var = tk.StringVar(value="--")
        self.delay_count_var = tk.StringVar(value="--")
        self.ratio_var = tk.StringVar(value="--")
        self.overlay_status_var = tk.StringVar(value="")
        self.delta_var = tk.StringVar(value="")
        self.timing_var = tk.StringVar(value="")
        self.alert_var = tk.StringVar(value="")
        self._ignore_arm_until = 0.0
        self.seg_avg_var = tk.StringVar(value="--")
        self.cv_var = tk.StringVar(value="--")
        self.verdict_var = tk.StringVar(value="--")
        self.issues_hint_var = tk.StringVar(value="")
        ttk.Label(status_card, textvariable=self.mode_var, background="#ffffff", foreground="#007aff", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 4))
        # Row 1 — session / stability stats
        stats = ttk.Frame(status_card, style="Card.TFrame")
        stats.pack(fill="x")
        ttk.Label(stats, text="STATS", background="#ffffff", foreground="#6e6e73", font=("Segoe UI", 7, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        for i, (title, var) in enumerate([
            ("PHASE", self.phase_var),
            ("TIME", self.countdown_var),
            ("CLICKS", self.click_count_var),
            ("INTERVAL", self.last_interval_var),
            ("HOLD", self.last_hold_var),
            ("SEG AVG", self.seg_avg_var),
            ("SEG CV", self.cv_var),
            ("VERDICT", self.verdict_var),
        ], start=1):
            box = ttk.Frame(stats, style="Card.TFrame")
            box.grid(row=0, column=i, sticky="nsew", padx=3)
            ttk.Label(box, text=title, background="#ffffff", foreground="#6e6e73", font=("Segoe UI", 7)).pack(anchor="w")
            ttk.Label(box, textvariable=var, background="#ffffff", foreground="#1d1d1f", font=("Segoe UI", 12, "bold")).pack(anchor="w")
            stats.columnconfigure(i, weight=1)
        # Row 2 — issue counts (separate block)
        issues = ttk.Frame(status_card, style="Card.TFrame")
        issues.pack(fill="x", pady=(6, 0))
        ttk.Label(issues, text="ISSUES", background="#ffffff", foreground="#6e6e73", font=("Segoe UI", 7, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        for i, (title, var) in enumerate([
            ("EXTRA", self.extra_count_var),
            ("REBOUND", self.rebound_count_var),
            ("DELAY", self.delay_count_var),
            ("DUT", self.dut_score_var),
            ("SETUP", self.setup_score_var),
        ], start=1):
            box = ttk.Frame(issues, style="Card.TFrame")
            box.grid(row=0, column=i, sticky="nsew", padx=3)
            ttk.Label(box, text=title, background="#ffffff", foreground="#6e6e73", font=("Segoe UI", 7)).pack(anchor="w")
            ttk.Label(box, textvariable=var, background="#ffffff", foreground="#1d1d1f", font=("Segoe UI", 12, "bold")).pack(anchor="w")
            issues.columnconfigure(i, weight=1)
        ttk.Label(status_card, textvariable=self.issues_hint_var, style="Subtle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(status_card, textvariable=self.timing_var, style="Subtle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(status_card, textvariable=self.status_var, style="Subtle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(status_card, textvariable=self.alert_var, style="Alert.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(status_card, textvariable=self.overlay_status_var, style="Subtle.TLabel").pack(anchor="w")
        ttk.Label(status_card, textvariable=self.delta_var, style="Subtle.TLabel", wraplength=900).pack(anchor="w")

        charts = ttk.LabelFrame(right, text="Charts", padding=8, style="Card.TLabelframe")
        charts.pack(fill="both", expand=True, pady=(8, 0))
        self._charts_frame = charts
        self.test_area = tk.Frame(charts, bg="#fbfbfd", highlightthickness=2, highlightbackground="#007aff", highlightcolor="#007aff")
        self.test_area.pack(fill="both", expand=True)
        self.test_area_hint = tk.Label(
            self.test_area,
            text="TEST AREA\nClick here with the target button to start\nStop: F5 or Esc (avoids contaminating data)",
            bg="#fbfbfd",
            fg="#6e6e73",
            font=("Segoe UI", 13, "bold"),
            justify="center",
        )
        self.test_area_hint.place(relx=0.5, rely=0.42, anchor="center")
        self.xy_canvas = tk.Canvas(self.test_area, bg="#ffffff", highlightthickness=1, highlightbackground="#d2d2d7", height=300)
        self.xy_canvas.pack(fill="both", expand=True, padx=6, pady=(6, 3))
        self.canvas = tk.Canvas(self.test_area, bg="#ffffff", highlightthickness=1, highlightbackground="#d2d2d7", height=170)
        self.canvas.pack(fill="both", expand=True, padx=6, pady=(3, 6))
        for widget in (self.test_area, self.xy_canvas, self.canvas, self.test_area_hint):
            widget.bind("<ButtonPress-1>", self._on_test_area_press)
            widget.bind("<ButtonRelease-1>", self._on_test_area_release)
        self.metrics_text = tk.Text(charts, height=5, wrap="word", bg="#fbfbfd", relief="flat", font=("Consolas", 9), highlightthickness=1, highlightbackground="#d2d2d7")
        # shown only in REVIEW
        self._advanced_visible = False
        self._metrics_visible = False

    def _on_global_mousewheel(self, event):
        w = event.widget
        cls = ""
        try:
            cls = str(w.winfo_class())
        except Exception:
            cls = type(w).__name__
        before = {
            "profile": self.profile_var.get() if hasattr(self, "profile_var") else "",
            "fixture": self.fixture_var.get() if hasattr(self, "fixture_var") else "",
            "duration": self.duration_var.get() if hasattr(self, "duration_var") else "",
        }
        # #region agent log
        if getattr(self, "_wheel_log_count", 0) < 25:
            self._wheel_log_count = getattr(self, "_wheel_log_count", 0) + 1
            _agent_log("A", "hub_click_tool.py:_on_global_mousewheel", "mousewheel", {
                "cls": cls,
                "delta": int(getattr(event, "delta", 0) or 0),
                "before": before,
                "count": self._wheel_log_count,
            })
        # #endregion
        try:
            self.root.after(0, lambda b=before, c=cls: self._log_wheel_after(b, c))
        except Exception:
            pass

    def _log_wheel_after(self, before: dict[str, str], cls: str):
        after = {
            "profile": self.profile_var.get() if hasattr(self, "profile_var") else "",
            "fixture": self.fixture_var.get() if hasattr(self, "fixture_var") else "",
            "duration": self.duration_var.get() if hasattr(self, "duration_var") else "",
        }
        if after != before:
            # #region agent log
            _agent_log("A", "hub_click_tool.py:_log_wheel_after", "combobox value changed by wheel", {
                "cls": cls,
                "before": before,
                "after": after,
            })
            # #endregion
        else:
            n = getattr(self, "_wheel_unchanged_logs", 0)
            if n < 8:
                self._wheel_unchanged_logs = n + 1
                # #region agent log
                _agent_log("A", "hub_click_tool.py:_log_wheel_after", "combobox value unchanged after wheel", {
                    "cls": cls,
                    "before": before,
                    "after": after,
                    "runId": "post-fix",
                })
                # #endregion

    def _on_param_mousewheel(self, event):
        before = {
            "profile": self.profile_var.get() if hasattr(self, "profile_var") else "",
            "fixture": self.fixture_var.get() if hasattr(self, "fixture_var") else "",
            "duration": self.duration_var.get() if hasattr(self, "duration_var") else "",
        }
        # #region agent log
        _agent_log("A", "hub_click_tool.py:_on_param_mousewheel", "wheel on param combobox", {
            "delta": int(getattr(event, "delta", 0) or 0),
            "duration": before["duration"],
            "fixture": before["fixture"],
            "blocked": True,
            "runId": "post-fix",
        })
        # #endregion
        try:
            self.root.after(0, lambda b=before: self._log_wheel_after(b, "TCombobox"))
        except Exception:
            pass
        return "break"

    def _restore_param_widget_states(self):
        editable = set(getattr(self, "_editable_combos", []) or [])
        for w in self.param_widgets:
            try:
                if w in editable:
                    w.configure(state="normal")
                elif str(w.winfo_class()) == "TCombobox":
                    # Button is readonly; Hz/Duration/Segment editable
                    tv = str(w.cget("textvariable") or "")
                    if hasattr(self, "button_var") and tv == str(self.button_var):
                        w.configure(state="readonly")
                    else:
                        w.configure(state="normal")
                elif hasattr(self, "expected_var") and str(w.cget("textvariable") or "") == str(self.expected_var):
                    w.configure(state="readonly")
                else:
                    w.configure(state="normal")
            except Exception:
                pass

    def _log_combo_open(self, name: str):
        # #region agent log
        _agent_log("E", "hub_click_tool.py:_log_combo_open", "combobox down-arrow", {"name": name})
        # #endregion

    def _center_window(self):
        try:
            self.root.update_idletasks()
            w = self.root.winfo_width(); h = self.root.winfo_height()
            sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
            x = max(0, int((sw - w)/2)); y = max(0, int((sh - h)/2))
            self.root.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _apply_window_shell(self, initial: bool = False):
        """Fullscreen lab shell with state-based topmost.

        Setup / parameter editing: fullscreen=True, topmost=False so dropdowns and
        screen capture overlays are not interrupted. Running capture: topmost=True
        once, with no watchdog and no focus_force loop.
        """
        try:
            self.root.attributes("-fullscreen", True)
        except Exception:
            try:
                self.root.state("zoomed")
            except Exception:
                pass
        try:
            self.root.attributes("-topmost", False)
        except Exception:
            pass
        try:
            self.root.resizable(False, False)
        except Exception:
            pass

    def _set_capture_topmost(self, active: bool):
        try:
            self.root.attributes("-topmost", bool(active))
        except Exception:
            pass

    def _apply_cfg_to_vars(self, cfg: dict[str, Any]):
        self.profile_var.set(str(cfg.get("profile_name") or "Manual_Left_Stable"))
        self.button_var.set(str(cfg.get("focus_button") or "Left"))
        fx = float(cfg.get("fixture_hz") or cfg.get("fixture_reference_hz") or 0)
        manual = _is_manual_profile(cfg) or fx <= 0
        if hasattr(self, "mode_choice_var"):
            self.mode_choice_var.set("Manual" if manual else "Fixture")
        self.fixture_var.set("10" if manual else str(int(fx) if float(fx).is_integer() else fx))
        self.duration_var.set(str(int(float(cfg.get("duration_sec") or 60))))
        exp = int(float(cfg.get("expected_clicks") or cfg.get("target_clicks") or 0))
        self.expected_var.set("manual" if manual and exp <= 0 else str(exp or 600))
        self.capture_var.set(str(cfg.get("capture_mode") or "Windows Raw Input / 裝置RawInput"))
        self.chatter_var.set(str(cfg.get("chatter_threshold_ms") or 8))
        self.double_var.set(str(cfg.get("duplicate_click_threshold_ms") or 30))
        self.short_hold_var.set(str(cfg.get("fixture_actuation_too_short_ms") or 5))
        self.low_hold_var.set(str(cfg.get("low_hold_warning_ms") or 8))
        self.interval_cv_var.set(str(cfg.get("interval_cv_limit_pct") or 10))
        if hasattr(self, "segment_var"):
            self.segment_var.set(str(int(float(cfg.get("manual_segment_sec") or MANUAL_SEGMENT_SEC_DEFAULT))))
        if hasattr(self, "device_name_var") and not self.device_name_var.get():
            self.device_name_var.set(str(self.target or ""))
        if hasattr(self, "mouse_mold_var"):
            self.mouse_mold_var.set(str(cfg.get("mouse_mold") or ""))
            self.probe_note_var.set(str(cfg.get("probe_note") or ""))
        self._sync_hidden_profile()
        if hasattr(self, "rule_preset_var"):
            self._set_rule_preset("Strict")

    def _on_profile_changed(self):
        return

    def _sync_hidden_profile(self):
        button = self.button_var.get() or "Left"
        manual = hasattr(self, "mode_choice_var") and self.mode_choice_var.get() == "Manual"
        hz = 0.0 if manual else self._fixture_value()
        if manual or hz <= 0:
            name = "Manual_Left_Stable" if button == "Left" else ("Manual_Right_Stable" if button == "Right" else "Manual_AllButton_Debug")
        elif hz >= 25:
            name = "Fixture_Left_40Hz_Extreme"
        elif button == "Left":
            name = "Fixture_Left_10Hz_Strict"
        elif button == "Right":
            name = "Fixture_Right_10Hz_Strict"
        elif button == "Middle":
            name = "Fixture_Middle_5Hz_Normal"
        elif button == "X1":
            name = "Fixture_SideBack_5Hz_Normal"
        elif button == "X2":
            name = "Fixture_SideFront_5Hz_Normal"
        else:
            name = "Fixture_Left_10Hz_Strict"
        self.profile_var.set(name)

    def _set_rule_preset(self, name: str):
        if self.running or self.auto_mode:
            return
        labels = dict(RULE_PRESET_LABELS)
        self.rule_preset_var.set(labels.get(name, name))
        if name == "Customize":
            if hasattr(self, "_rules_advanced") and not self._rules_advanced.winfo_ismapped():
                self._rules_advanced.pack(fill="x", pady=(8, 0))
            return
        preset = RULE_PRESETS.get(name) or RULE_PRESETS["Strict"]
        self._applying_rules = True
        try:
            self.chatter_var.set(str(preset["chatter_threshold_ms"]))
            dup = float(preset["duplicate_click_threshold_ms"])
            if is_extreme_cadence({"fixture_hz": self._fixture_value(), "profile_name": self.profile_var.get()}):
                hz = self._fixture_value()
                cad = (1000.0 / hz) if hz > 0 else 18.0
                dup = min(dup, cad * 0.72, 18.0)
            self.double_var.set(str(dup))
            self.short_hold_var.set(str(preset["fixture_actuation_too_short_ms"]))
            self.low_hold_var.set(str(preset["low_hold_warning_ms"]))
            self.interval_cv_var.set(str(preset["interval_cv_limit_pct"]))
        finally:
            self._applying_rules = False
        if hasattr(self, "_rules_advanced") and self._rules_advanced.winfo_ismapped():
            self._rules_advanced.pack_forget()

    def _on_button_changed(self):
        if self.auto_mode or getattr(self, "_applying_profile", False):
            return
        self._sync_hidden_profile()
        self._update_expected_from_duration()

    def _on_mode_choice(self):
        if self.running:
            return
        self._sync_hidden_profile()
        self._apply_mode_ui()
        self._update_expected_from_duration()
        if hasattr(self, "mode_var"):
            self.mode_var.set(self._mode_label_text())
        if hasattr(self, "mode_choice_var") and self.mode_choice_var.get() == "Fixture":
            try:
                self.status_var.set("Fixture mode needs a click fixture at the set Hz. Hand-clicking will usually WARN (Hz mismatch).")
            except Exception:
                pass
        elif hasattr(self, "status_var") and not self.running and not self.completed:
            try:
                self.status_var.set(SOP_LISTEN)
            except Exception:
                pass

    def _apply_mode_ui(self):
        manual = hasattr(self, "mode_choice_var") and self.mode_choice_var.get() == "Manual"
        for w in getattr(self, "_fixture_rows", []):
            try:
                if manual:
                    w.grid_remove()
                else:
                    w.grid()
            except Exception:
                pass
        for w in getattr(self, "_manual_rows", []):
            try:
                if manual:
                    w.grid()
                else:
                    w.grid_remove()
            except Exception:
                pass

    def _fixture_value(self) -> float:
        if hasattr(self, "mode_choice_var") and self.mode_choice_var.get() == "Manual":
            return 0.0
        text = str(self.fixture_var.get()).strip().lower()
        if text in {"manual", "manual / 無", "none", "0", ""}:
            return 0.0
        try:
            return float(text)
        except Exception:
            return 0.0

    def _mode_label_text(self, settings: dict[str, Any] | None = None) -> str:
        s = settings or self.settings()
        hz = float(s.get("fixture_hz") or 0)
        cad = cadence_ms(s)
        if hz <= 0 or _is_manual_profile(s):
            seg = int(float(s.get("manual_segment_sec") or MANUAL_SEGMENT_SEC_DEFAULT))
            return f"Manual · stability · {seg}s segments"
        kind = "Fixture extreme" if is_extreme_cadence(s) else "Fixture"
        if cad:
            return f"{kind} {hz:g}Hz · beat {cad:g}ms"
        return f"{kind} {hz:g}Hz"

    def _timing_line(self, m: dict[str, Any], settings: dict[str, Any] | None = None) -> str:
        s = settings or self.settings()
        if _is_manual_profile(s):
            after = m.get("fatigue_after_sec")
            parts = []
            if m.get("interval_avg_ms") is not None and m.get("interval_cv_pct") is not None:
                parts.append(f"Session avg {m.get('interval_avg_ms')} ms · Session CV {m.get('interval_cv_pct')}%")
            segs = (m.get("manual_segments") or {}).get("segments") or []
            if segs:
                last = segs[-1]
                parts.append(f"Last segment avg {last.get('avg_interval_ms')} ms · SEG CV {last.get('cv_pct')}%")
            if after is not None:
                parts.append(f"Fatigue after ~{after:g}s")
            return " · ".join(parts)
        if not cadence_ms(s):
            return ""
        bias = m.get("timing_bias_ms")
        sigma = m.get("timing_sigma_ms")
        p99 = m.get("p99_abs_error_ms")
        if bias is None and sigma is None and p99 is None:
            return ""
        w05 = m.get("within_0_5ms_pct")
        w1 = m.get("within_1ms_pct")
        set_hz = float(s.get("fixture_hz") or 0)
        meas_hz = m.get("measured_hz")
        target_ms = cadence_ms(s)
        meas_ms = m.get("measured_interval_ms")
        parts = [
            f"bias {bias:+.3f}ms" if bias is not None else None,
            f"σ {sigma:.3f}ms" if sigma is not None else None,
            f"P99|err| {p99:.3f}ms" if p99 is not None else None,
            f"±0.5ms {w05:.1f}%" if w05 is not None else None,
            f"±1ms {w1:.1f}%" if w1 is not None else None,
        ]
        if set_hz > 0 and meas_hz is not None:
            parts.append(f"set {set_hz:g}Hz · measured ~{float(meas_hz):g}Hz")
        if bias is not None and target_ms is not None and meas_ms is not None:
            parts.append(f"target {target_ms:g}ms / measured {float(meas_ms):.1f}ms")
        return " · ".join(p for p in parts if p)

    def _validate_run_settings(self) -> str | None:
        manual = hasattr(self, "mode_choice_var") and self.mode_choice_var.get() == "Manual"
        if not manual:
            hz_text = str(self.fixture_var.get()).strip()
            try:
                hz = float(hz_text)
            except Exception:
                return "Fixture Hz must be 1–80."
            if hz < 1 or hz > 80:
                return "Fixture Hz must be 1–80."
            try:
                dur = float(str(self.duration_var.get()).strip())
            except Exception:
                return "Duration must be 5–3600 sec."
            if dur < 5 or dur > 3600:
                return "Duration must be 5–3600 sec."
        else:
            try:
                seg = float(str(self.segment_var.get()).strip())
            except Exception:
                return "Segment must be 5–60 sec."
            if seg < 5 or seg > 60:
                return "Segment must be 5–60 sec."
        return None

    def _update_expected_from_duration(self):
        if self.running:
            return
        try:
            hz = self._fixture_value()
            self._sync_hidden_profile()
            if hz <= 0:
                self.expected_var.set("manual")
            else:
                duration = safe_float(self.duration_var.get(), 0.0)
                if duration <= 0:
                    return
                expected = int(round(duration * hz))
                if expected > 0:
                    self.expected_var.set(str(expected))
            if hasattr(self, "mode_var"):
                self.mode_var.set(self._mode_label_text())
            preset_name = str(self.rule_preset_var.get() if hasattr(self, "rule_preset_var") else "")
            if "Customize" not in preset_name and not getattr(self, "_applying_rules", False):
                key = "Strict"
                for k, label in RULE_PRESET_LABELS:
                    if label == preset_name or k == preset_name:
                        key = k
                        break
                base_dup = float((RULE_PRESETS.get(key) or RULE_PRESETS["Strict"])["duplicate_click_threshold_ms"])
                if is_extreme_cadence({"fixture_hz": hz, "profile_name": self.profile_var.get()}):
                    cad = (1000.0 / hz) if hz > 0 else 18.0
                    self.double_var.set(str(round(min(base_dup, cad * 0.72, 18.0), 1)))
                else:
                    self.double_var.set(str(base_dup))
        except Exception as exc:
            _agent_log("D", "hub_click_tool.py:_update_expected_from_duration", "expected update failed", {
                "hz": self.fixture_var.get() if hasattr(self, "fixture_var") else "",
                "duration": self.duration_var.get() if hasattr(self, "duration_var") else "",
                "err": type(exc).__name__,
            })

    def _update_settings_preview(self):
        self._update_expected_from_duration()

    def settings(self) -> dict[str, Any]:
        manual = hasattr(self, "mode_choice_var") and self.mode_choice_var.get() == "Manual"
        device = self.device_name_var.get().strip() if hasattr(self, "device_name_var") else ""
        if device:
            self.target = device
        return normalize_auto_settings({"settings": {
            "profile_name": self.profile_var.get(),
            "focus_button": self.button_var.get(),
            "button": self.button_var.get(),
            "fixture_hz": 0.0 if manual else self._fixture_value(),
            "fixture_reference_hz": 0.0 if manual else self._fixture_value(),
            "duration_sec": safe_int(self.duration_var.get(), 60),
            "expected_clicks": 0 if manual else safe_int(self.expected_var.get(), 600),
            "target_clicks": 0 if manual else safe_int(self.expected_var.get(), 600),
            "manual_mode": manual,
            "manual_segment_sec": safe_float(self.segment_var.get(), MANUAL_SEGMENT_SEC_DEFAULT) if hasattr(self, "segment_var") else MANUAL_SEGMENT_SEC_DEFAULT,
            "capture_mode": self.capture_var.get() or "Windows Raw Input / 裝置RawInput",
            "chatter_threshold_ms": safe_float(self.chatter_var.get(), 8),
            "duplicate_click_threshold_ms": safe_float(self.double_var.get(), 30),
            "fixture_actuation_too_short_ms": safe_float(self.short_hold_var.get(), 5),
            "low_hold_warning_ms": safe_float(self.low_hold_var.get(), 8),
            "interval_cv_limit_pct": safe_float(self.interval_cv_var.get(), 10),
            "mouse_mold": self.mouse_mold_var.get() if hasattr(self, "mouse_mold_var") else "",
            "probe_note": self.probe_note_var.get() if hasattr(self, "probe_note_var") else "",
        }})

    def _focused_widget_is_editable(self) -> bool:
        try:
            w = self.root.focus_get()
            if w is None:
                return False
            cls = str(w.winfo_class()).lower()
            return cls in {"entry", "tentry", "combobox", "tcombobox", "spinbox", "text"}
        except Exception:
            return False

    def _commit_settings_before_start(self) -> bool:
        """Commit pending Entry/Combobox edits before capture starts.

        v20449 hotkey policy: Start must never consume uncommitted operator input.
        F5 commits + validates + locks a settings snapshot; Space is only a fallback
        when focus is not in an editable field.
        """
        try:
            w = self.root.focus_get()
            if w is not None:
                try: w.event_generate("<FocusOut>")
                except Exception: pass
                try: w.selection_clear()
                except Exception: pass
                try: w.icursor("end")
                except Exception: pass
        except Exception:
            pass
        try:
            self.root.focus_set()
        except Exception:
            pass
        try:
            err = self._validate_run_settings()
            if err:
                try: self.status_var.set(err)
                except Exception: pass
                try: self.messagebox.showerror("Settings", err, parent=self.root)
                except Exception: pass
                return False
            self._update_expected_from_duration()
            self._update_settings_preview()
            self.locked_setting_snapshot = self.settings()
            return True
        except Exception as exc:
            try: self.status_var.set(f"Setting needs confirmation / 設定需要確認: {exc}")
            except Exception: pass
            return False

    def _on_space_hotkey(self, event=None):
        if self._focused_widget_is_editable():
            return "break"
        if self.running:
            self.stop_run()
        return "break"

    def _on_f5_hotkey(self, event=None):
        if self.running:
            self.stop_run()
        return "break"

    def _on_escape_hotkey(self, event=None):
        if self.auto_mode:
            return "break"
        if self.running:
            self.stop_run()
        return "break"

    def _manual_toggle(self):
        if self.auto_mode:
            return "break"
        if self.running:
            self.stop_run()
        return "break"

    def _show_guide(self):
        """Modal guide that cannot start a run when dismissed over the Test Area."""
        self._ignore_arm_until = time.perf_counter() + 2.0
        win = self.tk.Toplevel(self.root)
        win.title("Quick Start")
        win.transient(self.root)
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        body = self.ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        lines = [
            "1. Choose Manual or Fixture.",
            "2. Move the cursor into the Test Area, then click the target button to start.",
            "3. Manual has no timer — press F5 or Esc to Stop (avoids contaminating data).",
            "4. Fixture runs until Duration ends, or Stop with F5 / Esc.",
            "5. Review charts, then New Run or Finish & Generate Report.",
            "6. Save Report As… copies artifacts to a folder you choose.",
        ]
        self.ttk.Label(body, text="Quick Start", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        for line in lines:
            self.ttk.Label(body, text=line, wraplength=420, justify="left").pack(anchor="w", pady=2)
        self.ttk.Label(
            body,
            text="Tip: prefer F5 / Esc to stop. Clicking Stop with the mouse may add an extra click in Fixture mode.",
            wraplength=420,
            foreground="#6e6e73",
        ).pack(anchor="w", pady=(10, 8))

        def _close():
            self._ignore_arm_until = time.perf_counter() + 1.0
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        self.ttk.Button(body, text="OK", command=_close).pack(anchor="e")
        win.protocol("WM_DELETE_WINDOW", _close)
        # Place dialog on the left so OK is not over the Test Area.
        try:
            self.root.update_idletasks()
            x = self.root.winfo_rootx() + 40
            y = self.root.winfo_rooty() + 120
            win.geometry(f"+{x}+{y}")
            win.grab_set()
            win.focus_force()
        except Exception:
            pass

    def _cursor_over_chrome(self) -> bool:
        """True when cursor is over left controls / header (not the Test Area)."""
        try:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery()
            left = getattr(self, "_left_panel", None)
            if left is not None:
                lx, ly = left.winfo_rootx(), left.winfo_rooty()
                if lx <= x <= lx + left.winfo_width() and ly <= y <= ly + left.winfo_height():
                    return True
            # Top header band (~56px)
            rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
            if rx <= x <= rx + self.root.winfo_width() and ry <= y <= ry + 64:
                return True
        except Exception:
            return False
        return False

    def _should_accept_capture_at_cursor(self) -> bool:
        if self._cursor_over_chrome():
            return False
        settings = self.locked_setting_snapshot or self.settings()
        if _is_manual_profile(settings):
            return self._cursor_in_test_area()
        # Fixture: accept global presses unless cursor is on UI chrome (Stop click).
        return True

    def _toggle_advanced(self):
        box = getattr(self, "_advanced_box", None)
        if box is None:
            return
        self._advanced_visible = not getattr(self, "_advanced_visible", False)
        if self._advanced_visible:
            box.pack(fill="x", pady=(8, 0))
        else:
            box.pack_forget()

    def _set_test_area_hint(self, visible: bool):
        hint = getattr(self, "test_area_hint", None)
        if hint is None:
            return
        try:
            if visible:
                hint.place(relx=0.5, rely=0.42, anchor="center")
                hint.lift()
            else:
                hint.place_forget()
        except Exception:
            pass

    def _set_metrics_visible(self, visible: bool):
        mt = getattr(self, "metrics_text", None)
        if mt is None:
            return
        try:
            if visible and not getattr(self, "_metrics_visible", False):
                mt.pack(fill="x", pady=(10, 0))
                self._metrics_visible = True
            elif not visible and getattr(self, "_metrics_visible", False):
                mt.pack_forget()
                self._metrics_visible = False
        except Exception:
            pass

    def _set_alert(self, text: str):
        self._status_alert = text or ""
        try:
            self.alert_var.set(self._status_alert)
        except Exception:
            pass

    def _update_control_states(self):
        if self.auto_mode:
            return
        phase = str(self.phase_var.get() or "")
        running = self.running
        review = phase == "REVIEW" or (self.completed and not running)
        try:
            self.stop_button.configure(state=("normal" if running else "disabled"))
        except Exception:
            pass
        try:
            self.new_run_button.configure(state=("normal" if (review or phase == "LISTEN") else "disabled"))
        except Exception:
            pass
        try:
            self.finish_button.configure(state=("normal" if review else "disabled"))
        except Exception:
            pass
        try:
            self.save_as_button.configure(state=("normal" if self.report_written else "disabled"))
        except Exception:
            pass

    def enter_listen(self):
        if self.auto_mode:
            return
        self.listening = True
        self.running = False
        self.completed = False
        self.report_written = False
        self._arming_scheduled = False
        self.phase_var.set("LISTEN")
        self.status_var.set(SOP_LISTEN)
        self.countdown_var.set("--")
        self._set_test_area_hint(True)
        self._set_metrics_visible(False)
        self._set_capture_topmost(False)
        self._restore_param_widget_states()
        self._apply_mode_ui()
        self._update_control_states()
        s = self.settings()
        self._locked_button = str(s.get("focus_button") or "Left")
        self._locked_capture_is_raw = True
        if str(s.get("capture_mode", "")).startswith("Windows Raw Input"):
            try:
                self.ensure_raw_input()
            except Exception as exc:
                self._set_alert(f"Raw Input failed: {exc}")

    def _on_test_area_press(self, event=None):
        if self.running or self.auto_mode:
            return
        if not self.listening or self.completed:
            return
        self._ui_pad_press_t = time.perf_counter()

    def _on_test_area_release(self, event=None):
        if self.running or self.auto_mode:
            return
        if not self.listening or self.completed:
            return
        # UI-pad path only when Raw Input is unavailable; Raw Input uses first device click.
        if self.raw_input is not None:
            return
        press = getattr(self, "_ui_pad_press_t", None) or time.perf_counter()
        release = time.perf_counter()
        button = self.button_var.get() or "Left"
        self._begin_session_from_first_click(button, press, release, {
            "capture_source": "ui_pad",
            "device_source": "test_area",
            "x": getattr(event, "x", ""),
            "y": getattr(event, "y", ""),
        })

    def start(self):
        """Auto-mode entry: begin immediately (no Test Area arming)."""
        if self.running:
            return
        if not self._commit_settings_before_start():
            return
        self.reset(clear_only=True)
        s = self.locked_setting_snapshot or self.settings()
        t0 = time.perf_counter()
        self._begin_running(s, t0=t0, record_first=False)
        if self.self_test_events is not None:
            self.events = list(self.self_test_events)
            self.root.after(500, lambda: self.stop_run(write_report=True))
            return
        if str(s.get("capture_mode", "")).startswith("Windows Raw Input"):
            self.ensure_raw_input()

    def _cursor_in_test_area(self) -> bool:
        area = getattr(self, "test_area", None)
        if area is None:
            return True
        try:
            x = self.root.winfo_pointerx()
            y = self.root.winfo_pointery()
            left = area.winfo_rootx()
            top = area.winfo_rooty()
            right = left + max(1, area.winfo_width())
            bottom = top + max(1, area.winfo_height())
            return left <= x <= right and top <= y <= bottom
        except Exception:
            return True

    def _begin_session_from_first_click(self, button: str, press_time: float, release_time: float, event: dict[str, Any]):
        if self.running or self.completed:
            self._arming_scheduled = False
            return
        if time.perf_counter() < float(getattr(self, "_ignore_arm_until", 0.0) or 0.0):
            self._arming_scheduled = False
            return
        if not self._cursor_in_test_area():
            self._arming_scheduled = False
            return
        if self._cursor_over_chrome():
            self._arming_scheduled = False
            return
        if not self._commit_settings_before_start():
            self._arming_scheduled = False
            return
        s = self.locked_setting_snapshot or self.settings()
        target = str(s.get("focus_button") or "Left")
        if button != target:
            self._set_alert(f"Wrong button: got {button}, expected {target}")
            self._arming_scheduled = False
            return
        # Clear prior listen noise but keep this first click.
        with self.capture_lock:
            self.events.clear()
            self.raw_events.clear()
            self.device_press_queues.clear()
            self.first_press_time = self.last_press_time = self.first_release_time = self.last_release_time = None
        self._begin_running(s, t0=press_time, record_first=False)
        self.record_click(button, press_time, release_time, event)
        self._ui_dirty = True

    def _begin_running(self, s: dict[str, Any], *, t0: float, record_first: bool):
        self.cfg = dict(s)
        self.locked_setting_snapshot = dict(s)
        for w in self.param_widgets:
            try:
                w.configure(state="disabled")
            except Exception:
                pass
        self._set_capture_topmost(True)
        self.start_time = t0
        manual = _is_manual_profile(s)
        if manual:
            self.end_time = None
            self.status_var.set("Recording… Stop with F5 or Esc")
        else:
            self.end_time = self.start_time + float(s.get("duration_sec") or 60)
            self.status_var.set("Recording… Stop fixture before timer ends · F5/Esc to Stop")
        self.running = True
        self.completed = False
        self.listening = False
        self.report_written = False
        self._locked_button = str(s.get("focus_button") or "Left")
        self._locked_capture_is_raw = str(s.get("capture_mode", "")).startswith("Windows Raw Input")
        self.phase_var.set("RUNNING")
        self._warmup_last_press = None
        self._set_test_area_hint(False)
        self._set_metrics_visible(False)
        self._set_alert("")
        self._update_control_states()

    def ensure_raw_input(self):
        if self.raw_input is None:
            self.raw_input = WindowsRawInputSubprocess(self.on_raw_input_event)
        try:
            self.raw_input.start()
        except Exception as exc:
            self.listening = False
            self.running = False
            self.status_var.set(f"Raw Input start failed: {exc}")
            self._set_alert(f"Raw Input start failed: {exc}")
            if self.auto_mode:
                self.root.after(500, lambda: self.stop_run(write_report=True))

    def on_raw_input_event(self, event: dict[str, Any]):
        try:
            self._pair_raw_event(event)
        except Exception:
            pass
        self._ui_dirty = True

    def _ui_after_capture(self):
        if not self.running and not self.completed:
            return
        if not self.capture_lock.acquire(timeout=0.05):
            return
        try:
            accepted = [e for e in self.events if e.get("accepted")]
            last = accepted[-1] if accepted else None
            count = len(accepted)
        finally:
            self.capture_lock.release()
        exp = self.expected_var.get()
        if str(exp).lower().startswith("manual") or not exp:
            self.click_count_var.set(str(count))
        else:
            self.click_count_var.set(f"{count} / {exp}")
        if last:
            if last.get("press_interval_ms") is not None:
                self.last_interval_var.set(f"{last['press_interval_ms']:.2f} ms")
            if last.get("hold_ms") is not None:
                self.last_hold_var.set(f"{last['hold_ms']:.2f} ms")

    def _pair_raw_event(self, event: dict[str, Any]):
        if not self.running and not (self.listening and not self.completed):
            return
        if event.get("capture_source") != "windows_raw_input" and getattr(self, "_locked_capture_is_raw", True):
            return
        button = event.get("button")
        event_type = event.get("event_type")
        device_source = event.get("device_source") or "unknown_device"
        t_perf = float(event.get("time_perf") or time.perf_counter())
        target_button = getattr(self, "_locked_button", None) or (self.button_var.get() if hasattr(self, "button_var") else "Left")
        raw_row = {
            "timestamp": now_iso(),
            "button": button,
            "event_type": event_type,
            "accepted": False,
            "time_perf": t_perf,
            "capture_source": event.get("capture_source"),
            "device_source": device_source,
            "raw_hdevice": event.get("raw_hdevice"),
            "raw_dx": event.get("raw_dx"),
            "raw_dy": event.get("raw_dy"),
        }
        with self.capture_lock:
            if self.running:
                self.raw_events.append(raw_row)
            if button != target_button:
                if self.running and event_type == "up":
                    row = {"index": len(self.events)+1, "timestamp": now_iso(), "button": button, "event_type": "click", "accepted": False, "capture_source": event.get("capture_source"), "device_source": device_source, "raw_hdevice": event.get("raw_hdevice"), "raw_dx": event.get("raw_dx"), "raw_dy": event.get("raw_dy")}
                    self.events.append(row)
                    self._set_alert(f"Wrong button detected: {button}")
                return
            key = (device_source, str(button))
            if event_type == "down":
                self.device_press_queues[key].append(t_perf)
            elif event_type == "up":
                queue = self.device_press_queues[key]
                if not queue:
                    return
                press = queue.popleft()
                if self.running:
                    if self._should_accept_capture_at_cursor():
                        self.record_click(button, press, t_perf, event)
                elif self.listening and not getattr(self, "_arming_scheduled", False):
                    # First complete target click arms the session (Scheme 1).
                    self._arming_scheduled = True
                    self.root.after(0, lambda b=button, p=press, r=t_perf, e=dict(event): self._begin_session_from_first_click(b, p, r, e))

    def handle_external_mouse_event(self, event: dict[str, Any]):
        self._pair_raw_event(event)

    def record_click(self, button: str, press_time: float, release_time: float, event: dict[str, Any]):
        warmup = bool(ARMING_SEC > 0 and self.start_time is not None and (press_time - float(self.start_time)) < ARMING_SEC)
        hold_ms = (release_time - press_time) * 1000.0
        if warmup:
            last_w = getattr(self, "_warmup_last_press", None)
            press_interval = None if last_w is None else (press_time - last_w) * 1000.0
            self._warmup_last_press = press_time
            row = {
                "index": len(self.events) + 1,
                "timestamp": now_iso(),
                "button": button,
                "event_type": "click",
                "accepted": False,
                "warmup_excluded": True,
                "issue_tags": "WARMUP_EXCLUDED",
                "press_elapsed_ms": None,
                "press_interval_ms": round(press_interval, 4) if press_interval is not None else None,
                "release_elapsed_ms": None,
                "elapsed_ms": None,
                "interval_ms": None,
                "hold_ms": round(hold_ms, 4),
                "x": event.get("x", ""),
                "y": event.get("y", ""),
                "capture_source": event.get("capture_source", "windows_raw_input"),
                "device_source": event.get("device_source", "unknown_device"),
                "raw_hdevice": event.get("raw_hdevice", ""),
                "raw_dx": event.get("raw_dx", ""),
                "raw_dy": event.get("raw_dy", ""),
                "flags": event.get("flags", []),
            }
            self.events.append(row)
            return
        if self.first_press_time is None:
            self.first_press_time = press_time
        if self.first_release_time is None:
            self.first_release_time = release_time
        press_elapsed = (press_time - self.first_press_time) * 1000.0
        release_elapsed = (release_time - self.first_release_time) * 1000.0
        press_interval = None if self.last_press_time is None else (press_time - self.last_press_time) * 1000.0
        release_interval = None if self.last_release_time is None else (release_time - self.last_release_time) * 1000.0
        self.last_press_time = press_time
        self.last_release_time = release_time
        row = {
            "index": len(self.events) + 1,
            "timestamp": now_iso(),
            "button": button,
            "event_type": "click",
            "accepted": True,
            "press_elapsed_ms": round(press_elapsed, 4),
            "press_interval_ms": round(press_interval, 4) if press_interval is not None else None,
            "release_elapsed_ms": round(release_elapsed, 4),
            "elapsed_ms": round(release_elapsed, 4),
            "interval_ms": round(release_interval, 4) if release_interval is not None else None,
            "hold_ms": round(hold_ms, 4),
            "x": event.get("x", ""),
            "y": event.get("y", ""),
            "capture_source": event.get("capture_source", "windows_raw_input"),
            "device_source": event.get("device_source", "unknown_device"),
            "raw_hdevice": event.get("raw_hdevice", ""),
            "raw_dx": event.get("raw_dx", ""),
            "raw_dy": event.get("raw_dy", ""),
            "flags": event.get("flags", []),
        }
        self.events.append(row)

    def reset(self, clear_only: bool = False):
        if not clear_only:
            self.stop_adapters()
        self.running = False
        self.completed = False
        self.listening = False
        self.report_written = False
        self._arming_scheduled = False
        self.events.clear()
        self.raw_events.clear()
        self.device_press_queues.clear()
        self.first_press_time = self.last_press_time = self.first_release_time = self.last_release_time = None
        self._warmup_last_press = None
        self.start_time = self.end_time = None
        self.phase_var.set("LISTEN")
        self.countdown_var.set("--")
        self.click_count_var.set("0")
        self.last_interval_var.set("--")
        self.last_hold_var.set("--")
        self.status_var.set(SOP_LISTEN)
        self._set_alert("")
        self._ui_dirty = False
        self._restore_param_widget_states()
        if self.auto_mode:
            for w in self.param_widgets:
                try:
                    w.configure(state="disabled")
                except Exception:
                    pass
        self._set_capture_topmost(False)
        self._set_test_area_hint(True)
        self._set_metrics_visible(False)
        self._draw_chart()
        if not clear_only:
            self._update_metrics_text({})
        self._update_control_states()

    def new_run(self):
        if self.running:
            return
        self.run_id = _now_run_id()
        self.reset(clear_only=False)
        self.enter_listen()

    def stop_adapters(self):
        if self.raw_input is not None:
            try:
                self.raw_input.stop()
            except Exception:
                pass
            self.raw_input = None

    def stop_run(self, write_report: bool = False):
        if self.completed and not self.running:
            if write_report:
                self._write_reports_now()
            return
        self.running = False
        self.listening = False
        self.completed = True
        self.stop_adapters()
        self._set_capture_topmost(False)
        self._restore_param_widget_states()
        settings = self.locked_setting_snapshot or self.settings()
        try:
            self._refresh_final_live(settings)
        except Exception:
            pass
        if write_report or self.auto_mode:
            self._write_reports_now()
            return
        self.phase_var.set("REVIEW")
        self.status_var.set(SOP_REVIEW)
        self._set_metrics_visible(True)
        # Keep a session entry so "Compare previous run" does not require picking JSON filenames.
        try:
            settings = self.locked_setting_snapshot or self.settings()
            accepted = [e for e in self.events if e.get("accepted")]
            self.session_runs.append({
                "run_id": self.run_id,
                "label": f"{self.run_id} · session · {len(accepted)} clicks",
                "detail_path": "",
                "path": "",
                "events": [dict(e) for e in self.events],
                "metrics": {},
            })
        except Exception:
            pass
        self._update_control_states()

    def _write_reports_now(self):
        self.phase_var.set("FINALIZING")
        self.status_var.set("Writing report…")
        settings = self.locked_setting_snapshot or self.settings()
        try:
            self._refresh_final_live(settings)
            self.report_paths = write_reports(self.report_root, self.target, self.operator, settings, self.events, self.run_id, raw_events=list(self.raw_events))
            verification = _verify_artifacts(self.report_paths)
            if not verification.get("ok"):
                missing = ", ".join(verification.get("missing") or [])
                raise RuntimeError("Missing report artifacts: " + missing)
            self.report_written = True
            if verification.get("xlsx_skipped"):
                self.phase_var.set("REVIEW")
                self.status_var.set("Report ready (Excel skipped — install openpyxl).")
            else:
                self.phase_var.set("REVIEW")
                self.status_var.set("Report ready.")
            if self.auto_mode:
                print(json.dumps({"type": "auto_complete", **self.report_paths}, ensure_ascii=False), flush=True)
                self.root.after(1200, self.root.destroy)
        except Exception as exc:
            self.phase_var.set("ERROR")
            self.status_var.set(f"Report failed: {type(exc).__name__}: {exc}")
            self._set_alert(f"Report failed: {type(exc).__name__}")
            if self.auto_mode:
                print(json.dumps({"type": "auto_failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
                self.root.after(1200, self.root.destroy)
            else:
                try:
                    self.messagebox.showerror("Report generation failed", f"{type(exc).__name__}: {exc}", parent=self.root)
                except Exception:
                    pass
        finally:
            try:
                self._refresh_final_live(settings)
            except Exception:
                pass
            self._set_metrics_visible(True)
            self._update_control_states()

    def _handoff_and_close(self) -> bool:
        self.phase_var.set("REVIEW")
        self.status_var.set("Report ready.")
        return True

    def finish_and_return(self):
        if self.running:
            self.stop_run(write_report=True)
            return
        if not self.completed and not self.events:
            self._set_alert("No run to report yet.")
            return
        self.completed = True
        self._write_reports_now()

    def save_report_as(self):
        if not self.report_written or not self.report_paths:
            self.finish_and_return()
            if not self.report_written:
                return
        from tkinter import filedialog
        import shutil
        dest = filedialog.askdirectory(parent=self.root, title="Save report folder to…")
        if not dest:
            return
        out_dir = Path(dest) / f"mcsa_{self.run_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        copied = []
        for key, path in (self.report_paths or {}).items():
            if not path:
                continue
            src = Path(path)
            if src.exists():
                target = out_dir / src.name
                shutil.copy2(src, target)
                copied.append(target.name)
        self.status_var.set(f"Saved {len(copied)} files to {out_dir}")

    def finalize(self, return_to_hub: bool = False):
        # Compatibility: old callers treat finalize as stop + write.
        self.stop_run(write_report=True)

    def _refresh_final_live(self, settings: dict[str, Any] | None = None):
        settings = settings or self.locked_setting_snapshot or self.settings()
        snapshot = []
        if self.capture_lock.acquire(timeout=0.2):
            try:
                snapshot = [dict(e) for e in self.events]
            finally:
                self.capture_lock.release()
        annotated = annotate_events(snapshot, settings)
        self._ui_after_capture()
        self._refresh_metrics(events=annotated, settings=settings)

    def _tick(self):
        t_tick0 = time.perf_counter()
        now = t_tick0
        if getattr(self, "_ui_dirty", False):
            self._ui_dirty = False
            try:
                self._ui_after_capture()
            except Exception:
                pass
        if self.auto_pending_start and self.auto_delay_end:
            remain_prepare = max(0.0, self.auto_delay_end - now)
            self.countdown_var.set(f"Prepare {remain_prepare:.1f}s")
            self.phase_var.set("PREPARE")
        if self.running:
            if self.end_time is None:
                # Manual: elapsed only (no hard stop)
                elapsed = max(0.0, now - float(self.start_time or now))
                self.countdown_var.set(f"{elapsed:.1f}s")
            else:
                remain = max(0.0, float(self.end_time) - now)
                self.countdown_var.set(f"{remain:.1f}s")
                if remain <= 0:
                    self.stop_run(write_report=False)
        n_live = len(self.events)
        metric_every = 1.5 if (self.running and n_live > 2500) else 0.5
        need_metrics = now - self.last_metric_update > metric_every
        need_chart = now - self.last_chart_update > 0.5
        annotated = None
        settings = None
        if need_metrics or need_chart:
            idle_empty = (not self.running) and (not self.completed)
            if idle_empty:
                with self.capture_lock:
                    n_acc = sum(1 for e in self.events if e.get("accepted"))
                if n_acc == 0:
                    if need_metrics:
                        self._refresh_metrics(idle_empty=True)
                        self.last_metric_update = now
                    if need_chart:
                        self._draw_chart(current=[], settings=self.settings())
                        self.last_chart_update = now
                    annotated = []
            if annotated is None:
                settings = self.locked_setting_snapshot or self.settings()
                snapshot = None
                if self.capture_lock.acquire(timeout=0.05):
                    try:
                        snapshot = [dict(e) for e in self.events]
                    finally:
                        self.capture_lock.release()
                # Lock timeout with empty snapshot would wipe charts → visible flash.
                if snapshot is None:
                    pass
                else:
                    annotated = annotate_events(snapshot, settings)
                    if need_metrics:
                        self._refresh_metrics(events=annotated, settings=settings)
                        self.last_metric_update = now
                    if need_chart:
                        # Avoid empty redraw while a run is active (transient race).
                        if annotated or not (self.running or self.completed):
                            self._draw_chart(current=annotated, settings=settings)
                            self.last_chart_update = now
                        elif need_chart and (self.running or self.completed):
                            self.last_chart_update = now
        try:
            self.root.after(100, self._tick)
        except Exception:
            pass

    def _refresh_metrics(self, events=None, settings=None, idle_empty: bool = False):
        if idle_empty:
            try:
                self.dut_score_var.set("--")
                self.setup_score_var.set("--")
            except Exception:
                pass
            self._update_overlay_deltas({})
            self._update_metrics_text({
                "click_count": 0,
                "health": "IDLE",
                "dut_score": "--",
                "setup_score": "--",
                "issue_tags": [],
            })
            try:
                self.extra_count_var.set("--")
                self.rebound_count_var.set("--")
                self.delay_count_var.set("--")
                self.ratio_var.set("--")
                self.timing_var.set("")
                self.mode_var.set(self._mode_label_text())
            except Exception:
                pass
            # #region agent log
            n = getattr(self, "_idle_metric_logs", 0)
            if n < 3:
                self._idle_metric_logs = n + 1
                _agent_log("B", "hub_click_tool.py:_refresh_metrics", "idle metrics", {
                    "health": "IDLE",
                    "dut": "--",
                    "setup": "--",
                    "tags": [],
                    "phase": self.phase_var.get() if hasattr(self, "phase_var") else "",
                    "expected": self.expected_var.get() if hasattr(self, "expected_var") else "",
                    "fixture": self.fixture_var.get() if hasattr(self, "fixture_var") else "",
                    "duration": self.duration_var.get() if hasattr(self, "duration_var") else "",
                    "double": self.double_var.get() if hasattr(self, "double_var") else "",
                    "skipped_fail": True,
                    "runId": "post-fix",
                })
            # #endregion
            return
        settings = settings or self.settings()
        if events is None:
            with self.capture_lock:
                snapshot = [dict(e) for e in self.events]
            events = annotate_events(snapshot, settings)
        payload = build_payload(self.target, self.operator, settings, events, run_id=self.run_id)
        m = payload.get("metrics") or {}
        judging = self.running or self.completed
        if judging:
            tags = _metrics_issue_tags(m, settings, events)
        else:
            tags = [t for t in _metrics_issue_tags(m, settings, events) if t not in {
                "MISS_CLICK_FAIL", "MISS_CLICK_WARN", "INSUFFICIENT_CLICKS",
                "EXCESS_CLICK_COUNT_FAIL", "EXCESS_CLICK_COUNT_WARN",
            }]
            if int(m.get("click_count") or 0) == 0:
                m = {**m, "dut_score": "--", "setup_score": "--", "health": "IDLE"}
        verdict = _result_from_tags(tags, m, settings) if (m.get("health") != "IDLE" and int(m.get("click_count") or 0) > 0) else "IDLE"
        if _is_manual_profile(settings) and int(m.get("click_count") or 0) > 0:
            m = {**m, "health": verdict, "verdict": verdict}
        elif judging:
            m = {**m, "verdict": verdict}
        try:
            if _is_manual_profile(settings):
                self.dut_score_var.set("n/a")
                self.setup_score_var.set("n/a")
                self.issues_hint_var.set("EXTRA=extra/chatter clicks · REBOUND=incomplete press · DELAY=long gap  |  DUT/SETUP = Fixture only")
            else:
                self.dut_score_var.set(f"{m.get('dut_score', '--')}")
                self.setup_score_var.set(f"{m.get('setup_score', '--')}")
                self.issues_hint_var.set("EXTRA=off-cadence extras · REBOUND=incomplete press · DELAY=miss/slow vs beat  |  DUT=device integrity · SETUP=fixture alignment")
            extra_n = int(m.get("true_extra_click_count") or 0) + int(m.get("chatter_bounce_count") or 0)
            self.extra_count_var.set(str(extra_n))
            self.rebound_count_var.set(str(int(m.get("incomplete_rebound_count") or 0)))
            self.delay_count_var.set(str(int(m.get("miss_or_slow_count") or 0)))
            expected = int(settings.get("expected_clicks") or 0)
            actual = int(m.get("click_count") or 0)
            if _is_manual_profile(settings) or expected <= 0:
                self.click_count_var.set(str(actual))
                self.ratio_var.set(str(actual))
            else:
                self.click_count_var.set(f"{actual} / {expected}")
                self.ratio_var.set(f"{actual} / {expected}")
            self.mode_var.set(self._mode_label_text(settings))
            self.timing_var.set(self._timing_line(m, settings))
            # SEG AVG + SEG CV are a matched pair (last 10s window).
            # Session CV stays on the timing line to avoid conflicting big numbers.
            segs = (m.get("manual_segments") or {}).get("segments") or []
            if segs:
                last = segs[-1]
                self.seg_avg_var.set(f"{last.get('avg_interval_ms')} ms")
                self.cv_var.set(f"{float(last.get('cv_pct') or 0):.2f}")
            elif m.get("interval_avg_ms") is not None:
                self.seg_avg_var.set(f"{m.get('interval_avg_ms')} ms")
                if m.get("interval_cv_pct") is not None:
                    self.cv_var.set(f"{float(m.get('interval_cv_pct')):.2f}")
                else:
                    self.cv_var.set("--")
            else:
                self.seg_avg_var.set("--")
                if m.get("interval_cv_pct") is not None:
                    self.cv_var.set(f"{float(m.get('interval_cv_pct')):.2f}")
                else:
                    self.cv_var.set("--")
            self.verdict_var.set(str(verdict))
            # Plain-language verdict for demos / interviews (REVIEW only; don't overwrite Running SOP)
            if (self.completed or str(self.phase_var.get()) == "REVIEW") and int(m.get("click_count") or 0) > 0:
                self.status_var.set(self._verdict_plain_language(verdict, tags, m, settings))
            alert_bits = []
            if "OPERATOR_FATIGUE" in tags:
                after = m.get("fatigue_after_sec")
                alert_bits.append(f"OPERATOR_FATIGUE after ~{after:g}s" if after is not None else "OPERATOR_FATIGUE")
            if "WRONG_BUTTON_DETECTED" in tags:
                alert_bits.append("WRONG_BUTTON_DETECTED")
            if "FIXTURE_HZ_MISMATCH" in tags:
                alert_bits.append("FIXTURE_HZ_MISMATCH")
            if "HIGH_PROBABILITY_DOUBLE_CLICK" in tags or "CHATTER_HARD" in tags or "TRUE_EXTRA_CLICK" in tags:
                alert_bits.append("double-click / chatter risk")
            if "INTERVAL_JITTER_WARN" in tags:
                alert_bits.append("high interval CV")
            if alert_bits:
                self._set_alert(" · ".join(alert_bits))
        except Exception:
            pass
        self._update_overlay_deltas(m)
        self._update_metrics_text({**m, "issue_tags": tags}, settings=settings)
        # #region agent log
        if (not self.running) and (int(m.get("click_count") or 0) == 0):
            n = getattr(self, "_idle_metric_logs", 0)
            if n < 3:
                self._idle_metric_logs = n + 1
                _agent_log("B", "hub_click_tool.py:_refresh_metrics", "idle metrics", {
                    "health": m.get("health"),
                    "dut": m.get("dut_score"),
                    "setup": m.get("setup_score"),
                    "tags": tags,
                    "phase": self.phase_var.get() if hasattr(self, "phase_var") else "",
                    "expected": self.expected_var.get() if hasattr(self, "expected_var") else "",
                    "fixture": self.fixture_var.get() if hasattr(self, "fixture_var") else "",
                    "duration": self.duration_var.get() if hasattr(self, "duration_var") else "",
                    "double": self.double_var.get() if hasattr(self, "double_var") else "",
                })
        # #endregion

    def _update_metrics_text(self, m: dict[str, Any], settings: dict[str, Any] | None = None):
        last_classes = []
        accepted = []
        if self.capture_lock.acquire(timeout=0.05):
            try:
                accepted = [e for e in self.events if e.get("accepted")]
            finally:
                self.capture_lock.release()
        settings = settings or getattr(self, "locked_setting_snapshot", None) or self.settings()
        annotated = annotate_events(accepted[-30:], settings) if accepted else []
        for e in annotated[-12:]:
            last_classes.append(
                f"#{e.get('click_index') or e.get('index')} {e.get('click_class') or '-'} "
                f"int={e.get('press_interval_ms')} hold={e.get('hold_ms')}"
            )
        expected = self.expected_var.get()
        verdict = m.get("verdict") or m.get("health") or "-"
        elapsed_s = None
        try:
            if self.start_time:
                end_ref = self.end_time if (self.end_time and self.completed) else None
                # Prefer displayed TIME when available
                ttxt = str(self.countdown_var.get() or "").replace("s", "").strip()
                if ttxt and ttxt != "--":
                    elapsed_s = float(ttxt)
        except Exception:
            elapsed_s = None
        if _is_manual_profile(settings) and int(m.get("click_count") or 0) > 0:
            health_line = f"Verdict: {verdict} (Manual = operator stability, not DUT fail) | DUT n/a | SETUP n/a"
            duration_line = f"Elapsed: {elapsed_s:.1f}s (no duration cap)" if elapsed_s is not None else "Elapsed: open-ended (no duration cap)"
        else:
            health_line = f"Verdict: {verdict} | DUT {m.get('dut_score')} | SETUP {m.get('setup_score')}"
            duration_line = f"Duration setting: {self.duration_var.get()}s" + (f" · Elapsed: {elapsed_s:.1f}s" if elapsed_s is not None else "")
        timing_line = self._timing_line(m, settings)
        lines = [
            f"Mode: {self._mode_label_text(settings)} | Button: {self.button_var.get()} | {duration_line}",
            f"Mold: {self.mouse_mold_var.get() if hasattr(self, 'mouse_mold_var') else ''} | Probe: {self.probe_note_var.get() if hasattr(self, 'probe_note_var') else ''}",
            f"Clicks: {m.get('click_count', 0)}" + (f" / {expected}" if not _is_manual_profile(settings) else ""),
            health_line,
        ]
        if timing_line:
            lines.append(timing_line)
        lines.extend([
            f"Cadence extras: true={m.get('true_extra_click_count')} chatter={m.get('chatter_bounce_count')} rebound={m.get('incomplete_rebound_count')} miss={m.get('miss_or_slow_count')}",
            f"Interval avg/CV/P99: {m.get('interval_avg_ms')} ms / {m.get('interval_cv_pct')}% / {m.get('interval_p99_ms')} ms",
            f"Hold avg/CV/P99: {m.get('hold_avg_ms')} ms / {m.get('hold_cv_pct')}% / {m.get('hold_p99_ms')} ms",
            f"Issue tags: {', '.join(m.get('issue_tags') or []) if m.get('issue_tags') else '-'}",
            "Log: " + " | ".join(last_classes[-6:]),
        ])
        self.metrics_text.configure(state="normal")
        self.metrics_text.delete("1.0", "end")
        self.metrics_text.insert("1.0", "\n".join(lines))
        self.metrics_text.configure(state="disabled")

    def _plot_points(self, events: list[dict[str, Any]]) -> list[tuple[float, float, str]]:
        points = []
        for e in events:
            if not e.get("accepted"):
                continue
            interval = e.get("press_interval_ms")
            hold = e.get("hold_ms")
            if interval is None or hold is None:
                continue
            points.append((float(interval), float(hold), str(e.get("click_class") or "ON_CADENCE")))
        return points

    def _draw_chart(self, current=None, settings=None):
        t0 = time.perf_counter()
        settings = settings or self.settings()
        if current is None:
            snapshot = []
            if self.capture_lock.acquire(timeout=0.05):
                try:
                    snapshot = [dict(e) for e in self.events]
                finally:
                    self.capture_lock.release()
            current = annotate_events(snapshot, settings)
        overlay = annotate_events(self.overlay_events, settings) if self.overlay_events else []
        xy_items = self._draw_xy_chart(current, overlay, settings)
        ts_items = self._draw_interval_time_chart(current, settings)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        n = len([e for e in current if e.get("accepted")])
        # #region agent log
        self._chart_log_count = getattr(self, "_chart_log_count", 0) + 1
        if self._chart_log_count <= 8 or elapsed_ms >= 25 or n >= 200 or (self.running and self._chart_log_count % 3 == 0):
            _agent_log("C", "hub_click_tool.py:_draw_chart", "chart draw cost", {
                "elapsed_ms": round(elapsed_ms, 3),
                "accepted": n,
                "running": self.running,
                "count": self._chart_log_count,
                "xy_items": xy_items,
                "ts_items": ts_items,
                "fixture": settings.get("fixture_hz"),
                "runId": "post-fix",
            })
        # #endregion

    def _run_cadence_title(self, settings: dict[str, Any]) -> str:
        hz = fixture_hz(settings)
        cad = cadence_ms(settings)
        if not cad or hz <= 0 or _is_manual_profile(settings):
            return "人手觀察 Manual · 無治具節拍"
        return f"本run節拍 = {cad:.0f}ms（{hz:g}Hz）"

    def _locked_interval_xmax_ms(self, pts: list[tuple[float, float, str]], settings: dict[str, Any]) -> float:
        hz = fixture_hz(settings)
        cad = cadence_ms(settings)
        if not cad or hz <= 0 or _is_manual_profile(settings):
            ints = [p[0] for p in pts]
            return manual_focus_xmax_ms(ints)
        if is_extreme_cadence(settings) or hz >= 30:
            return 80.0
        if hz >= 20:
            return 120.0
        if hz >= 10:
            return 220.0
        return 400.0

    def _locked_interval_ymax_ms(self, values: list[float], settings: dict[str, Any]) -> float:
        hz = fixture_hz(settings)
        cad = cadence_ms(settings)
        if not cad or hz <= 0 or _is_manual_profile(settings):
            sorted_v = sorted(values) if values else [80.0]
            p95 = sorted_v[min(len(sorted_v) - 1, int(len(sorted_v) * 0.95))]
            return max(80.0, p95 * 1.3)
        if is_extreme_cadence(settings) or hz >= 30:
            return 70.0
        if hz >= 20:
            return 120.0
        if hz >= 10:
            return 220.0
        return 400.0

    def _locked_error_ylim_ms(self, settings: dict[str, Any]) -> float:
        hz = fixture_hz(settings)
        if is_extreme_cadence(settings) or hz >= 30:
            return 12.0
        if hz >= 20:
            return 20.0
        if hz >= 10:
            return 40.0
        return 80.0

    def _focus_axis_ms(self, pts: list[tuple[float, float, str]], settings: dict[str, Any]) -> tuple[float, float]:
        xmax = self._locked_interval_xmax_ms(pts, settings)
        holds = [p[1] for p in pts] or [8.0]
        ymax = max(12.0, sorted(holds)[int(len(holds) * 0.95)] * 1.35 if holds else 12.0)
        return xmax, ymax

    def _draw_xy_chart(self, current: list[dict[str, Any]], overlay: list[dict[str, Any]], settings: dict[str, Any]):
        c = getattr(self, "xy_canvas", None)
        if c is None:
            return 0
        c.delete("all")
        w = max(100, c.winfo_width()); h = max(80, c.winfo_height())
        left, top, right, bottom = 64, 72, w - 24, h - 36
        c.create_rectangle(left, top, right, bottom, outline="#d2d2d7")
        cur_pts = self._plot_points(current)
        ov_pts = self._plot_points(overlay)
        if not cur_pts and not ov_pts:
            c.create_text((left+right)/2, (top+bottom)/2, text="Waiting for click data", fill="#6e6e73", font=("Segoe UI", 14, "bold"))
            return 1
        cad = cadence_ms(settings)
        lo, hi = cadence_band_ms(settings)
        extra_ceil = extra_click_ceiling_ms(settings)
        extreme = is_extreme_cadence(settings)
        manual = _is_manual_profile(settings) or not cad
        xmax, ymax = self._focus_axis_ms(cur_pts + ov_pts, settings)

        def sx(x):
            return left + (right - left) * (min(x, xmax) / xmax)

        def sy(y):
            return bottom - (bottom - top) * (min(y, ymax) / ymax)

        for pct in [0, 0.25, 0.5, 0.75, 1]:
            x = left + (right - left) * pct
            y = bottom - (bottom - top) * pct
            c.create_line(x, top, x, bottom, fill="#eef0f3")
            c.create_line(left, y, right, y, fill="#eef0f3")
            c.create_text(x, bottom + 12, text=f"{xmax*pct:.0f}ms", anchor="n", fill="#6e6e73", font=("Segoe UI", 8))
            c.create_text(left - 8, y, text=f"{ymax*pct:.0f}ms", anchor="e", fill="#6e6e73", font=("Segoe UI", 8))

        if not manual:
            if lo and hi:
                c.create_rectangle(sx(lo), top, sx(hi), bottom, fill="#e8f5e9", outline="")
            if extreme:
                c.create_rectangle(sx(10.0), top, sx(16.0), bottom, fill="#ffe8e0", outline="")
            if cad:
                c.create_line(sx(cad), top, sx(cad), bottom, fill="#34c759", dash=(4, 3))
            c.create_line(sx(extra_ceil), top, sx(extra_ceil), bottom, fill="#ff9500", dash=(4, 3))
        too_short = float(settings.get("fixture_actuation_too_short_ms") or 5)
        c.create_line(left, sy(too_short), right, sy(too_short), fill="#af52de", dash=(3, 3))

        extra_n = sum(1 for _, _, cls in cur_pts if cls in {"TRUE_EXTRA_CLICK", "CHATTER_BOUNCE"})
        rebound_n = sum(1 for _, _, cls in cur_pts if cls == "INCOMPLETE_REBOUND")
        miss_n = sum(1 for _, _, cls in cur_pts if cls == "MISS_OR_SLOW")
        off_n = sum(1 for x, _, _ in cur_pts if x > xmax)
        title = self._run_cadence_title(settings)
        if manual:
            line2 = "不畫治具節拍線  超短連點=紅點  過慢=黑X/軸外（與 Delay 同一門檻）"
        elif extreme:
            line2 = "綠線=節拍  桃帶=10–16ms連點  橙線=連點上限  過慢=黑X/軸外"
        else:
            line2 = f"綠線=節拍  橙線=連點上限 {extra_ceil:g}ms  過慢=黑X/軸外"
        line3 = f"extra={extra_n}  rebound={rebound_n}  delay={miss_n}  軸外={off_n}"
        c.create_text(left + 6, 4, text=title, anchor="nw", fill="#1d1d1f", font=("Segoe UI", 10, "bold"))
        c.create_text(left + 6, 22, text=line2, anchor="nw", fill="#6e6e73", font=("Segoe UI", 8))
        c.create_text(left + 6, 38, text=line3, anchor="nw", fill="#1d1d1f", font=("Segoe UI", 8, "bold"))

        nx, ny = 48, 28
        cell_w = (right - left) / nx
        cell_h = (bottom - top) / ny
        cloud = {"ON_CADENCE", "OK", ""}

        def fill_grid(pts):
            grid = [[0] * ny for _ in range(nx)]
            for x, y, cls in pts:
                if cls not in cloud:
                    continue
                ix = min(nx - 1, max(0, int((min(x, xmax) / xmax) * nx)))
                iy = min(ny - 1, max(0, int((min(y, ymax) / ymax) * ny)))
                grid[ix][iy] += 1
            return grid

        items = 0
        ov_grid = fill_grid(ov_pts) if ov_pts else None
        cur_grid = fill_grid(cur_pts) if cur_pts else None
        if ov_grid:
            for ix in range(nx):
                for iy in range(ny):
                    if not ov_grid[ix][iy]:
                        continue
                    x0 = left + ix * cell_w
                    y1 = bottom - iy * cell_h
                    c.create_rectangle(x0, y1 - cell_h, x0 + cell_w, y1, fill="#0a84ff", outline="", stipple="gray25")
                    items += 1
        if cur_grid:
            cloud_fill = "#8e8e93" if ov_grid else "#5ac8fa"
            for ix in range(nx):
                for iy in range(ny):
                    if not cur_grid[ix][iy]:
                        continue
                    x0 = left + ix * cell_w
                    y1 = bottom - iy * cell_h
                    c.create_rectangle(x0, y1 - cell_h, x0 + cell_w, y1, fill=cloud_fill, outline="")
                    items += 1

        class_color = {
            "TRUE_EXTRA_CLICK": "#c53030",
            "CHATTER_BOUNCE": "#ff3b30",
            "INCOMPLETE_REBOUND": "#ff9500",
            "MISS_OR_SLOW": "#1d1d1f",
        }
        anomalies = [(x, y, cls) for x, y, cls in cur_pts if cls in class_color]
        if len(anomalies) > 240:
            step = len(anomalies) / 240
            anomalies = [anomalies[int(i * step)] for i in range(240)]
        for x, y, cls in anomalies:
            px, py = sx(x), sy(y)
            if cls == "MISS_OR_SLOW":
                c.create_line(px - 4, py - 4, px + 4, py + 4, fill=class_color[cls], width=2)
                c.create_line(px - 4, py + 4, px + 4, py - 4, fill=class_color[cls], width=2)
            else:
                c.create_oval(px - 4, py - 4, px + 4, py + 4, fill=class_color[cls], outline="")
            items += 1
        for x, y, _cls in cur_pts:
            if x <= xmax:
                continue
            py = sy(y)
            c.create_line(right - 10, py, right - 2, py, fill="#1d1d1f", width=2)
            items += 1
        if ov_pts:
            c.create_text(right - 8, 8, text="A藍雲  B青雲  extra紅  rebound橙  delay黑X", anchor="ne", fill="#6e6e73", font=("Segoe UI", 8))
        return items

    def _draw_interval_time_chart(self, current: list[dict[str, Any]], settings: dict[str, Any]):
        c = self.canvas
        c.delete("all")
        w = max(100, c.winfo_width()); h = max(80, c.winfo_height())
        left, top, right, bottom = 64, 44, w-24, h-28
        c.create_rectangle(left, top, right, bottom, outline="#d2d2d7")
        accepted = [e for e in current if e.get("accepted") and e.get("press_interval_ms") is not None]
        if not accepted:
            c.create_text((left+right)/2, (top+bottom)/2, text="Interval over time / 間隔時序", fill="#6e6e73", font=("Segoe UI", 12, "bold"))
            return 1
        values = [float(e["press_interval_ms"]) for e in accepted]
        cad = cadence_ms(settings)
        extra_ceil = extra_click_ceiling_ms(settings)
        manual = _is_manual_profile(settings) or not cad
        title = self._run_cadence_title(settings)
        if not manual and cad:
            return self._draw_timing_error_chart(c, left, top, right, bottom, values, settings, cad, extra_ceil, title)
        ymax = self._locked_interval_ymax_ms(values, settings)
        for pct in [0, .25, .5, .75, 1]:
            y = bottom - (bottom-top)*pct
            c.create_line(left, y, right, y, fill="#eef0f3")
            c.create_text(left-8, y, text=f"{ymax*pct:.0f}ms", anchor="e", fill="#6e6e73", font=("Segoe UI", 8))
        cols = max(1, int(right - left))
        buckets: list[list[float]] = [[] for _ in range(cols)]
        n = len(values)
        for i, v in enumerate(values):
            b = min(cols - 1, int(i / max(1, n - 1) * (cols - 1))) if n > 1 else 0
            buckets[b].append(v)
        coords: list[float] = []
        extra_xs: list[float] = []
        delay_xs: list[float] = []
        delay_limit = manual_focus_xmax_ms(values)
        for i, bucket in enumerate(buckets):
            if not bucket:
                continue
            med = sorted(bucket)[len(bucket) // 2]
            x = left + i
            y = bottom - (bottom - top) * (min(med, ymax) / ymax)
            coords.extend([x, y])
            if min(bucket) < extra_ceil:
                extra_xs.append(x)
            if max(bucket) > delay_limit:
                delay_xs.append(x)
        items = 0
        if len(coords) >= 4:
            c.create_line(*coords, fill="#007aff", width=2)
            items += 1
        elif len(coords) == 2:
            c.create_oval(coords[0]-2, coords[1]-2, coords[0]+2, coords[1]+2, fill="#007aff", outline="")
            items += 1
        for x in extra_xs[:120]:
            c.create_line(x, top + 4, x, top + 14, fill="#ff3b30", width=2)
            items += 1
        for x in delay_xs[:120]:
            c.create_line(x, bottom - 14, x, bottom - 4, fill="#1d1d1f", width=2)
            items += 1
        legend = "人手觀察 · 不畫節拍線  紅短線=超短連點  黑短線=過慢超出軸"
        c.create_text(left, 4, text=title, anchor="nw", fill="#1d1d1f", font=("Segoe UI", 10, "bold"))
        c.create_text(left, 22, text=legend, anchor="nw", fill="#6e6e73", font=("Segoe UI", 8))
        return items

    def _draw_timing_error_chart(
        self,
        c,
        left: int,
        top: int,
        right: int,
        bottom: int,
        values: list[float],
        settings: dict[str, Any],
        cad: float,
        extra_ceil: float,
        title: str,
    ) -> int:
        ylim = self._locked_error_ylim_ms(settings)
        errors = [v - cad for v in values]
        extra_err = extra_ceil - cad

        def sy(err: float) -> float:
            clamped = max(-ylim, min(ylim, err))
            return bottom - (bottom - top) * ((clamped + ylim) / (2.0 * ylim))

        for pct in [0, .25, .5, .75, 1]:
            err = -ylim + (2.0 * ylim) * pct
            y = sy(err)
            c.create_line(left, y, right, y, fill="#eef0f3")
            c.create_text(left-8, y, text=f"{err:+.0f}", anchor="e", fill="#6e6e73", font=("Segoe UI", 8))
        zero_y = sy(0.0)
        c.create_line(left, zero_y, right, zero_y, fill="#34c759", dash=(5, 3))
        cols = max(1, int(right - left))
        buckets: list[list[float]] = [[] for _ in range(cols)]
        n = len(errors)
        for i, err in enumerate(errors):
            b = min(cols - 1, int(i / max(1, n - 1) * (cols - 1))) if n > 1 else 0
            buckets[b].append(err)
        coords: list[float] = []
        extra_xs: list[float] = []
        delay_xs: list[float] = []
        for i, bucket in enumerate(buckets):
            if not bucket:
                continue
            med = sorted(bucket)[len(bucket) // 2]
            x = left + i
            y = sy(med)
            coords.extend([x, y])
            if min(bucket) < extra_err:
                extra_xs.append(x)
            if max(bucket) > ylim or min(bucket) < -ylim:
                delay_xs.append(x)
        items = 0
        if len(coords) >= 4:
            c.create_line(*coords, fill="#007aff", width=2)
            items += 1
        elif len(coords) == 2:
            c.create_oval(coords[0]-2, coords[1]-2, coords[0]+2, coords[1]+2, fill="#007aff", outline="")
            items += 1
        for x in extra_xs[:120]:
            c.create_line(x, top + 4, x, top + 14, fill="#ff3b30", width=2)
            items += 1
        for x in delay_xs[:120]:
            c.create_line(x, bottom - 14, x, bottom - 4, fill="#1d1d1f", width=2)
            items += 1
        legend = "Y=Interval−節拍  綠線=0ms  紅短線=連點/過快  黑短線=超出軸"
        c.create_text(left, 4, text=title, anchor="nw", fill="#1d1d1f", font=("Segoe UI", 10, "bold"))
        c.create_text(left, 22, text=legend, anchor="nw", fill="#6e6e73", font=("Segoe UI", 8))
        return items

    def _verdict_plain_language(self, verdict: str, tags: list[str], metrics: dict[str, Any], settings: dict[str, Any]) -> str:
        manual = _is_manual_profile(settings)
        if manual:
            if verdict == "PASS":
                return "PASS — operator rhythm looks stable (not a DUT hardware score)."
            if verdict == "WARN":
                reasons = []
                if "OPERATOR_FATIGUE" in tags:
                    reasons.append("later segments slowed (fatigue)")
                if "INTERVAL_JITTER_WARN" in tags:
                    reasons.append(f"interval CV high ({metrics.get('interval_cv_pct')}%)")
                if "HIGH_PROBABILITY_DOUBLE_CLICK" in tags:
                    reasons.append("possible double-click pairs")
                if not reasons:
                    reasons.append("stability caution")
                return "WARN — " + "; ".join(reasons) + ". Usually operator-side, not DUT fail."
            if verdict == "FAIL":
                return "FAIL — hardware-risk evidence (chatter / repeated doubles / wrong button)."
            return SOP_REVIEW
        if verdict == "PASS":
            return "PASS — cadence and counts look healthy."
        if verdict == "WARN":
            return "WARN — review tags before blaming DUT (check Hz / fixture first)."
        if verdict == "FAIL":
            return "FAIL — clear miss/excess or double-click risk vs fixture profile."
        return SOP_REVIEW

    def _list_overlay_candidates(self) -> list[dict[str, Any]]:
        """Recent runs a tester can compare without knowing detail vs summary filenames."""
        root = Path(self.report_root)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        # Prefer in-session runs first
        for run in reversed(list(getattr(self, "session_runs", []) or [])):
            rid = str(run.get("run_id") or "")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            items.append(run)
        if root.exists():
            for detail in sorted(root.glob("mcsa_*_detail.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
                rid = detail.name.replace("mcsa_", "").replace("_detail.json", "")
                if rid in seen:
                    continue
                seen.add(rid)
                summary = root / f"mcsa_{rid}_summary.json"
                label = rid
                result = "?"
                clicks = "?"
                try:
                    if summary.exists():
                        payload = json.loads(summary.read_text(encoding="utf-8"))
                        result = str(payload.get("result") or "?")
                        clicks = str((payload.get("metrics") or {}).get("click_count") or "?")
                        target = payload.get("target_product") or ""
                        if target:
                            label = f"{rid} · {target}"
                except Exception:
                    pass
                items.append({
                    "run_id": rid,
                    "label": f"{label} · {result} · {clicks} clicks",
                    "detail_path": str(detail),
                    "summary_path": str(summary) if summary.exists() else "",
                })
        return items

    def load_overlay_run(self):
        candidates = self._list_overlay_candidates()
        if not candidates:
            self.messagebox.showinfo(
                "Compare run",
                "No previous runs found yet.\nFinish a run first, then use Load overlay to compare.",
                parent=self.root,
            )
            return
        win = self.tk.Toplevel(self.root)
        win.title("Compare with previous run")
        win.transient(self.root)
        win.resizable(False, False)
        frame = self.ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        self.ttk.Label(frame, text="Pick a previous run (auto-loads detail events):", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.ttk.Label(
            frame,
            text="You do not need to choose between summary/detail JSON files.",
            foreground="#6e6e73",
        ).pack(anchor="w", pady=(0, 8))
        listbox = self.tk.Listbox(frame, width=72, height=min(12, max(4, len(candidates))), font=("Segoe UI", 9))
        listbox.pack(fill="both", expand=True)
        for item in candidates:
            listbox.insert("end", item.get("label") or item.get("run_id"))
        listbox.selection_set(0)

        def _apply(path: str):
            try:
                payload = json.loads(Path(path).read_text(encoding="utf-8"))
            except Exception as exc:
                self.messagebox.showerror("Load overlay failed", str(exc), parent=self.root)
                return
            events = payload.get("events") or payload.get("all_click_events") or (payload.get("legacy_payload") or {}).get("events") or []
            metrics = payload.get("metrics") or {}
            if not events and payload.get("summary_json"):
                # summary-only: try sibling detail
                pass
            if not events:
                self.messagebox.showerror("Load overlay failed", "No events in that run (need a detail report).", parent=self.root)
                return
            self.overlay_events = events
            self.overlay_metrics = ranking_metrics(metrics, metrics)
            self.overlay_path = path
            self.overlay_status_var.set(f"Overlay: {Path(path).name}")
            self._draw_chart()
            self._refresh_metrics()
            win.destroy()

        def _on_ok():
            sel = listbox.curselection()
            if not sel:
                return
            item = candidates[int(sel[0])]
            # In-session run may already hold events in memory
            if item.get("events"):
                self.overlay_events = list(item["events"])
                self.overlay_metrics = ranking_metrics(item.get("metrics") or {}, item.get("metrics") or {})
                self.overlay_path = f"session:{item.get('run_id')}"
                self.overlay_status_var.set(f"Overlay: session {item.get('run_id')}")
                self._draw_chart()
                self._refresh_metrics()
                win.destroy()
                return
            path = item.get("detail_path") or item.get("summary_path") or item.get("path")
            if not path:
                self.messagebox.showerror("Load overlay failed", "That run has no saved detail file.", parent=self.root)
                return
            _apply(str(path))

        btns = self.ttk.Frame(frame)
        btns.pack(fill="x", pady=(10, 0))
        self.ttk.Button(btns, text="Browse file…", command=lambda: self._load_overlay_browse(win)).pack(side="left")
        self.ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        self.ttk.Button(btns, text="Compare", style="Primary.TButton", command=_on_ok).pack(side="right", padx=(0, 8))
        try:
            win.grab_set()
        except Exception:
            pass

    def _load_overlay_browse(self, parent_win=None):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Browse overlay JSON (prefer *_detail.json)",
            filetypes=[("MCSA detail JSON", "*_detail.json"), ("JSON", "*.json"), ("All", "*.*")],
            initialdir=str(self.report_root),
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            self.messagebox.showerror("Load overlay failed", str(exc), parent=self.root)
            return
        events = payload.get("events") or payload.get("all_click_events") or (payload.get("legacy_payload") or {}).get("events") or []
        metrics = payload.get("metrics") or {}
        if not events:
            self.messagebox.showerror(
                "Load overlay failed",
                "No click events in this file.\nChoose a *_detail.json (summary.json has no event list).",
                parent=self.root,
            )
            return
        self.overlay_events = events
        self.overlay_metrics = ranking_metrics(metrics, metrics)
        self.overlay_path = path
        self.overlay_status_var.set(f"Overlay: {Path(path).name}")
        self._draw_chart()
        self._refresh_metrics()
        if parent_win is not None:
            try:
                parent_win.destroy()
            except Exception:
                pass

    def clear_overlay(self):
        self.overlay_events = []
        self.overlay_metrics = {}
        self.overlay_path = ""
        self.overlay_status_var.set("")
        self.delta_var.set("")
        self._draw_chart()

    def _update_overlay_deltas(self, current_metrics: dict[str, Any]):
        if not self.overlay_metrics:
            self.delta_var.set("")
            return
        current = ranking_metrics(current_metrics, current_metrics)
        a_extra = int(self.overlay_metrics.get("true_extra_click_count") or 0)
        b_extra = int(current.get("true_extra_click_count") or 0)
        a_delay = int(self.overlay_metrics.get("miss_or_slow_count") or 0)
        b_delay = int(current.get("miss_or_slow_count") or 0)
        lead = f"A extra={a_extra} delay={a_delay}  ·  B extra={b_extra} delay={b_delay}"
        a_p99 = self.overlay_metrics.get("p99_abs_error_ms")
        b_p99 = current.get("p99_abs_error_ms")
        if a_p99 is not None or b_p99 is not None:
            lead += f"  ·  A P99|err|={a_p99}  B P99|err|={b_p99}"
        parts = [lead]
        cards = delta_cards(current, self.overlay_metrics)
        for card in cards:
            winner = card.get("winner") or "-"
            parts.append(f"{card['label']}: A={card['a']} B={card['b']} ({winner})")
        self.delta_var.set("  ·  ".join(parts))

    def on_close(self):
        self._set_capture_topmost(False)
        self.stop_adapters()
        try:
            self.root.destroy()
        except Exception:
            pass


def _show_fullscreen_preparation_countdown(delay_sec: float, title: str = "Click Validation", subtitle: str = "Fixture Preparation") -> None:
    delay_sec = max(0.0, float(delay_sec or 0))
    if delay_sec <= 0:
        return
    import tkinter as tk
    prep = tk.Tk()
    prep.title(f"{title} - Preparation Countdown")
    prep.configure(bg="#050505")
    try:
        prep.attributes("-fullscreen", True)
        prep.attributes("-topmost", True)
    except Exception:
        prep.geometry("1000x650")
    frame = tk.Frame(prep, bg="#050505")
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text=title, bg="#050505", fg="#ffffff", font=("Segoe UI", 42, "bold")).pack(pady=(90, 10))
    tk.Label(frame, text=subtitle + " / 治具準備", bg="#050505", fg="#d2d2d7", font=("Segoe UI", 28, "bold")).pack(pady=(0, 40))
    count_var = tk.StringVar(value=str(int(round(delay_sec))))
    tk.Label(frame, textvariable=count_var, bg="#050505", fg="#ffffff", font=("Segoe UI", 112, "bold")).pack(pady=(0, 20))
    tk.Label(frame, text="Place the click fixture now. Formal capture starts when the countdown reaches zero. / 請放好點擊治具，倒數結束後直接進入正式擷取。", bg="#050505", fg="#b8b8bd", font=("Segoe UI", 18), wraplength=1100, justify="center").pack(pady=(10, 0))
    end = time.perf_counter() + delay_sec
    def tick():
        remain = max(0.0, end - time.perf_counter())
        count_var.set(str(int(remain) + (1 if remain > 0.05 else 0)))
        if remain <= 0:
            try:
                prep.destroy()
            except Exception:
                pass
            return
        prep.after(100, tick)
    prep.after(50, tick)
    prep.mainloop()


def run_visible_ui(*, auto_settings: dict[str, Any] | None = None, run_id: str | None = None, report_root: str | Path | None = None, target: str = "", operator: str = "", auto_mode: bool = False, self_test_events: list[dict[str, Any]] | None = None, standalone_mode: bool = False) -> int:
    import tkinter as tk
    payload = dict(auto_settings or {})
    cfg = normalize_auto_settings(payload)
    if auto_mode:
        delay = max(0.0, float(cfg.get("auto_start_delay_sec") or 0))
        _show_fullscreen_preparation_countdown(delay, "Click Validation", "Fixture Preparation")
        settings = dict(payload.get("settings") or payload)
        settings["auto_start_delay_sec"] = 0
        if "settings" in payload:
            payload["settings"] = settings
        else:
            payload = {"settings": settings}
    root = tk.Tk()
    ClickToolApp(root, auto_settings=payload, run_id=run_id, report_root=report_root, target=target, operator=operator, auto_mode=auto_mode, self_test_events=self_test_events, standalone_mode=standalone_mode)
    root.mainloop()
    return 0


def run_synthetic(report_root: str | Path, run_id: str = "synthetic_10hz_flatline") -> dict[str, str]:
    settings = normalize_auto_settings({"settings": {"focus_button": "Left", "button": "Left", "fixture_hz": 10, "duration_sec": 60, "expected_clicks": 600, "target_clicks": 600}})
    events = make_synthetic_events(count=600, interval_ms=100.0, hold_ms=12.0)
    return write_reports(Path(report_root), "synthetic", "gate", settings, events, run_id)


def _gate_result(settings: dict[str, Any], events: list[dict[str, Any]]) -> tuple[str, dict[str, Any], list[str]]:
    annotated = annotate_events(events, settings)
    payload = build_payload("gate", "gate", settings, annotated, run_id="gate")
    metrics = dict(payload.get("metrics") or {})
    tags = _metrics_issue_tags(metrics, settings, annotated)
    result = _result_from_tags(tags, metrics, settings)
    return result, metrics, tags


def run_cadence_gates(report_root: str | Path) -> dict[str, Any]:
    report_root = Path(report_root)
    report_root.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []

    settings_10 = normalize_auto_settings({"settings": dict(PROFILE_PRESETS["Fixture_Left_10Hz_Strict"], duration_sec=6, expected_clicks=60, target_clicks=60)})
    events_10 = make_synthetic_events(60, 100.0, 12.0)
    result_10, metrics_10, tags_10 = _gate_result(settings_10, events_10)
    paths_10 = write_reports(report_root, "gate10", "gate", settings_10, events_10, "synthetic_10hz_flatline")
    if result_10 != "PASS":
        failures.append(f"10Hz flatline expected PASS, got {result_10} tags={tags_10}")
    if "FIXTURE_HZ_MISMATCH" in tags_10:
        failures.append(f"10Hz flatline should not be Hz mismatch, tags={tags_10}")

    settings_40 = normalize_auto_settings({"settings": dict(PROFILE_PRESETS["Fixture_Left_40Hz_Extreme"], duration_sec=2, expected_clicks=80, target_clicks=80)})
    events_40 = make_synthetic_events(80, 25.0, 8.0)
    result_40, metrics_40, tags_40 = _gate_result(settings_40, events_40)
    write_reports(report_root, "gate40", "gate", settings_40, events_40, "synthetic_40hz_flatline")
    if result_40 != "PASS":
        failures.append(f"40Hz flatline expected PASS, got {result_40} tags={tags_40} extras={metrics_40.get('true_extra_click_count')} dup={metrics_40.get('duplicate_click_risk_count')}")
    if "FIXTURE_HZ_MISMATCH" in tags_40:
        failures.append(f"40Hz flatline should not be Hz mismatch, tags={tags_40} measured={metrics_40.get('measured_hz')}")
    bias_40 = metrics_40.get("timing_bias_ms")
    p99_40 = metrics_40.get("p99_abs_error_ms")
    if bias_40 is None or p99_40 is None or abs(float(bias_40)) > 0.05 or float(p99_40) > 0.05:
        failures.append(f"40Hz flatline expected ~0 timing error, bias={bias_40} p99={p99_40}")
    annotated_40 = annotate_events(events_40, settings_40)
    err0 = annotated_40[1].get("interval_error_ms") if len(annotated_40) > 1 else None
    if err0 not in (0, 0.0):
        failures.append(f"40Hz interval_error_ms expected 0, got {err0}")

    settings_old = normalize_auto_settings({"settings": dict(PROFILE_PRESETS["Fixture_Left_10Hz_Strict"], duration_sec=2, expected_clicks=80, target_clicks=80)})
    result_old, metrics_old, tags_old = _gate_result(settings_old, events_40)
    if result_old != "FAIL":
        failures.append(f"25ms data under 10Hz/30ms rule expected FAIL, got {result_old} dup={metrics_old.get('duplicate_click_risk_count')}")

    extra_events = make_synthetic_events(40, 25.0, 8.0)
    extra_events[20]["press_interval_ms"] = 12.0
    extra_events[20]["hold_ms"] = 8.0
    settings_extra = normalize_auto_settings({"settings": dict(PROFILE_PRESETS["Fixture_Left_40Hz_Extreme"], duration_sec=1, expected_clicks=40, target_clicks=40)})
    result_extra, metrics_extra, tags_extra = _gate_result(settings_extra, extra_events)
    write_reports(report_root, "gate12ms", "gate", settings_extra, extra_events, "synthetic_12ms_extra")
    if "TRUE_EXTRA_CLICK" not in tags_extra and extra_events[20].get("click_class") != "TRUE_EXTRA_CLICK":
        annotated_extra = annotate_events(extra_events, settings_extra)
        cls = annotated_extra[20].get("click_class")
        if cls not in {"TRUE_EXTRA_CLICK", "CHATTER_BOUNCE"}:
            failures.append(f"12ms extra expected TRUE_EXTRA_CLICK, got class={cls} tags={tags_extra} result={result_extra}")

    rebound_events = make_synthetic_events(40, 25.0, 8.0)
    rebound_events[12]["press_interval_ms"] = 12.0
    rebound_events[12]["hold_ms"] = 3.0
    result_rebound, _, tags_rebound = _gate_result(settings_extra, rebound_events)
    annotated_rebound = annotate_events(rebound_events, settings_extra)
    if annotated_rebound[12].get("click_class") != "INCOMPLETE_REBOUND":
        failures.append(f"short-hold extra expected INCOMPLETE_REBOUND, got {annotated_rebound[12].get('click_class')} result={result_rebound}")

    miss_events = make_synthetic_events(40, 25.0, 8.0)
    miss_events[18]["press_interval_ms"] = 55.0
    annotated_miss = annotate_events(miss_events, settings_extra)
    if annotated_miss[18].get("click_class") != "MISS_OR_SLOW":
        failures.append(f"long gap expected MISS_OR_SLOW, got {annotated_miss[18].get('click_class')}")

    wild_hold = make_synthetic_events(40, 25.0, 8.0)
    for i, e in enumerate(wild_hold):
        if i % 3 == 0:
            e["hold_ms"] = 3.0
            e["press_interval_ms"] = 12.0 if i else e.get("press_interval_ms")
    _, metrics_wild, tags_wild = _gate_result(settings_extra, wild_hold)
    if not metrics_wild.get("setup_alignment_suspect") and "SETUP_ALIGNMENT_SUSPECT" not in tags_wild and "INCOMPLETE_REBOUND" not in tags_wild:
        failures.append(f"wild hold expected setup/rebound tags, got {tags_wild}")

    settings_man = normalize_auto_settings({"settings": dict(PROFILE_PRESETS["Manual_Left_Stable"], duration_sec=60, expected_clicks=0, target_clicks=0)})
    events_man = make_synthetic_events(200, 200.0, 100.0)
    for i in (20, 40, 60, 70, 75):
        events_man[i]["press_interval_ms"] = 400.0
    annotated_man = annotate_events(events_man, settings_man)
    delay_n = sum(1 for e in annotated_man if e.get("click_class") == "MISS_OR_SLOW")
    extra_n = sum(1 for e in annotated_man if e.get("click_class") in {"TRUE_EXTRA_CLICK", "CHATTER_BOUNCE"})
    man_ints = [float(e["press_interval_ms"]) for e in annotated_man if e.get("press_interval_ms") is not None]
    man_xmax = manual_focus_xmax_ms(man_ints)
    off_n = sum(1 for v in man_ints if man_xmax < v < 1000)
    if extra_n:
        failures.append(f"manual 200ms should not be extra, extra={extra_n}")
    if delay_n != off_n or delay_n < 5:
        failures.append(f"manual delay should match off-scale, delay={delay_n} off={off_n} xmax={man_xmax}")
    result_man, metrics_man, tags_man = _gate_result(settings_man, events_man)
    if int(metrics_man.get("miss_or_slow_count") or 0) != delay_n:
        failures.append(f"manual miss_or_slow_count {metrics_man.get('miss_or_slow_count')} != delay {delay_n}")
    if float(metrics_man.get("dut_score") or 0) != 100.0:
        failures.append(f"manual DUT should ignore CV/delay, got {metrics_man.get('dut_score')}")
    if "MISS_OR_SLOW" not in tags_man:
        failures.append(f"manual delay tags expected MISS_OR_SLOW, got {tags_man}")
    if result_man == "FAIL":
        failures.append(f"manual delay should stay observation WARN/PASS, got {result_man}")

    settings_mm = normalize_auto_settings({"settings": dict(PROFILE_PRESETS["Fixture_Left_10Hz_Strict"], fixture_hz=20, duration_sec=30, expected_clicks=600, target_clicks=600)})
    events_mm = make_synthetic_events(749, 40.0, 8.0)
    result_mm, metrics_mm, tags_mm = _gate_result(settings_mm, events_mm)
    meas_mm = metrics_mm.get("measured_hz")
    extra_mm = int(metrics_mm.get("true_extra_click_count") or 0) + int(metrics_mm.get("chatter_bounce_count") or 0)
    if "FIXTURE_HZ_MISMATCH" not in tags_mm:
        failures.append(f"20Hz set + ~25Hz data expected FIXTURE_HZ_MISMATCH, got tags={tags_mm} measured={meas_mm}")
    if "EXCESS_CLICK_COUNT_FAIL" in tags_mm:
        failures.append(f"Hz mismatch must not FAIL count as extras, tags={tags_mm} extra={extra_mm}")
    if result_mm == "FAIL":
        failures.append(f"20Hz set + ~25Hz data should be WARN not FAIL, got {result_mm} tags={tags_mm}")
    if meas_mm is None or abs(float(meas_mm) - 25.0) > 2.0:
        failures.append(f"measured_hz expected ~25, got {meas_mm}")
    if extra_mm > 5:
        failures.append(f"Hz mismatch extra should stay small, extra={extra_mm}")

    skip_check = _verify_artifacts({**paths_10, "engineering_xlsx": ""})
    if not skip_check.get("ok") or not skip_check.get("xlsx_skipped"):
        failures.append(f"xlsx optional verify failed: {skip_check}")

    ok = not failures
    summary = {
        "ok": ok,
        "failures": failures,
        "ten_hz": {"result": result_10, "tags": tags_10},
        "forty_hz": {"result": result_40, "dut_score": metrics_40.get("dut_score"), "duplicate": metrics_40.get("duplicate_click_risk_count")},
        "old_30ms_rule_on_25ms": {"result": result_old, "duplicate": metrics_old.get("duplicate_click_risk_count")},
        "extra_12ms": {"result": result_extra, "tags": tags_extra},
        "hz_mismatch_20_vs_25": {"result": result_mm, "tags": tags_mm, "measured_hz": meas_mm, "extra": extra_mm},
        "report_root": str(report_root),
    }
    (report_root / "cadence_gates.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if failures:
        raise RuntimeError("Cadence gates failed: " + "; ".join(failures))
    return summary
