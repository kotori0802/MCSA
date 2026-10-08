"""Stage 2C standard Measurement/Evidence artifact contract.

Standard Generate Report writes only factual Measurement + Evidence artifacts.
Screening/Validation semantics are absent unless an approved profile exists
(none are implemented). Legacy heuristic sidecars are not produced.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any

from .core import cv_pct, now_iso, percentile
from .schema import (
    EVIDENCE_SCHEMA,
    TOOL_ID,
    TOOL_NAME,
    TOOL_VERSION,
    artifact_names,
    build_host_environment,
)

STANDARD_REQUIRED_KEYS = ("evidence_json", "all_click_log_csv", "engineering_html", "engineering_xlsx")
STANDARD_OPTIONAL_KEYS: tuple[str, ...] = ()
STANDARD_BUNDLE_KEYS = STANDARD_REQUIRED_KEYS + STANDARD_OPTIONAL_KEYS

# Internal path key -> portable reference key stored in evidence JSON.
PORTABLE_ARTIFACT_KEYS = {
    "evidence_json": "evidence_json",
    "all_click_log_csv": "events_csv",
    "engineering_html": "report_html",
    "engineering_xlsx": "report_xlsx",
}

FACTUAL_EVENT_FIELDS = (
    "click_index",
    "index",
    "button",
    "accepted",
    "press_elapsed_ms",
    "press_interval_ms",
    "hold_ms",
    "capture_source",
    "device_source",
)

SETTINGS_WHITELIST = (
    "manual_mode",
    "focus_button",
    "duration_sec",
    "fixture_reference_hz",
    "fixture_hz",
    "fixture_timing_tolerance_ms",
    "profile_name",
    "capture_mode",
    "language",
)

MEASUREMENT_FIELDS = (
    "host_press_count",
    "interval_count",
    "interval_avg_ms",
    "interval_min_ms",
    "interval_max_ms",
    "interval_p50_ms",
    "interval_p99_ms",
    "interval_cv_pct",
    "hold_count",
    "hold_avg_ms",
    "hold_min_ms",
    "hold_max_ms",
    "hold_p50_ms",
    "hold_p99_ms",
    "hold_cv_pct",
)

# Exact JSON/CSV keys that belong to the retired heuristic / DUT-verdict model.
FORBIDDEN_STANDARD_KEYS = frozenset({
    "legacy_heuristic_assessment",
    "pass",
    "passed",
    "stability_score",
    "dut_score",
    "setup_score",
    "hardware_defect_result",
    "metrics_health",
    "fail_reasons",
    "warn_reasons",
    "issue_interpretation_map",
    "next_steps",
    "next_steps_en",
    "next_steps_zh",
    "click_class",
    "analysis_status",
    "issue_tags",
    "issue_detail",
    "issue_interpretation",
    "why_result",
    "why_result_en",
    "why_result_zh",
    "field_summary",
    "field_summary_en",
    "field_summary_zh",
    "operator_summary",
    "operator_summary_zh",
    "cadence_mode",
    "expected_click_index",
    "expected_time_ms",
    "drift_ms",
    "interval_error_ms",
    "interval_error_pct",
    "chatter_threshold_ms",
    "duplicate_click_threshold_ms",
    "interval_cv_limit_pct",
    "hold_cv_limit_pct",
    "max_outlier_ratio_pct",
    "low_hold_warning_ms",
    "click_session_summary",
    "click_operator_findings",
    "engineering_summary_zh",
    "all_click_events",
    "legacy_payload",
    "raw_down_up_events",
})

FORBIDDEN_CSV_COLUMNS = frozenset({
    "analysis_status",
    "result",
    "issue_tags",
    "issue_detail",
    "notes",
    "click_class",
    "expected_click_index",
    "expected_time_ms",
    "drift_ms",
    "interval_error_ms",
    "interval_error_pct",
    "release_elapsed_ms",
})

DUT_VERDICT_TOKENS = frozenset({"WARN", "FAIL", "PASS"})
# Keys whose string value must not be a DUT verdict token in Measurement-only output.
DUT_VERDICT_VALUE_KEYS = frozenset({
    "result",
    "health",
    "analysis_status",
    "pass",
    "passed",
})

HIDDEN_HEURISTIC_THRESHOLD_KEYS = frozenset({
    "chatter_threshold_ms",
    "duplicate_click_threshold_ms",
    "interval_cv_limit_pct",
    "hold_cv_limit_pct",
    "max_outlier_ratio_pct",
    "low_hold_warning_ms",
    "max_chatter_count",
    "extra_click_ceiling_ms",
    "fixture_actuation_too_short_ms",
    "pause_gap_threshold_ms",
    "long_interval_threshold_ms",
})


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


def factual_event_row(event: dict[str, Any]) -> dict[str, Any]:
    index = event.get("click_index", event.get("index"))
    row: dict[str, Any] = {
        "click_index": index,
        "index": event.get("index", index),
        "button": event.get("button"),
        "accepted": bool(event.get("accepted")),
        "press_elapsed_ms": event.get("press_elapsed_ms"),
        "press_interval_ms": event.get("press_interval_ms"),
        "hold_ms": event.get("hold_ms"),
        "capture_source": event.get("capture_source"),
        "device_source": event.get("device_source"),
    }
    return row


def factual_events(events: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for event in events or []:
        if isinstance(event, dict):
            out.append(factual_event_row(event))
    return out


def factual_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    src = dict(settings or {})
    out: dict[str, Any] = {}
    for key in SETTINGS_WHITELIST:
        if key in src:
            out[key] = src[key]
    return out


def factual_measurements(events: list[dict[str, Any]] | None, *, host_press_count: int | None = None) -> dict[str, Any]:
    rows = [e for e in (events or []) if isinstance(e, dict)]
    accepted = [e for e in rows if e.get("accepted")]
    intervals = [v for v in (_finite(e.get("press_interval_ms")) for e in accepted) if v is not None]
    holds = [v for v in (_finite(e.get("hold_ms")) for e in accepted) if v is not None]
    count = int(host_press_count) if host_press_count is not None else len(accepted)
    payload: dict[str, Any] = {
        "host_press_count": count,
        "interval_count": len(intervals),
        "interval_avg_ms": round(statistics.mean(intervals), 4) if intervals else None,
        "interval_min_ms": round(min(intervals), 4) if intervals else None,
        "interval_max_ms": round(max(intervals), 4) if intervals else None,
        "interval_p50_ms": round(percentile(intervals, 50), 4) if intervals else None,
        "interval_p99_ms": round(percentile(intervals, 99), 4) if intervals else None,
        "interval_cv_pct": round(cv_pct(intervals), 4) if intervals and cv_pct(intervals) is not None else None,
        "hold_count": len(holds),
        "hold_avg_ms": round(statistics.mean(holds), 4) if holds else None,
        "hold_min_ms": round(min(holds), 4) if holds else None,
        "hold_max_ms": round(max(holds), 4) if holds else None,
        "hold_p50_ms": round(percentile(holds, 50), 4) if holds else None,
        "hold_p99_ms": round(percentile(holds, 99), 4) if holds else None,
        "hold_cv_pct": round(cv_pct(holds), 4) if holds and cv_pct(holds) is not None else None,
    }
    return payload


def build_evidence_payload(
    *,
    run_id: str,
    run_status: str,
    target: str,
    operator: str,
    settings: dict[str, Any],
    events: list[dict[str, Any]],
    completed_model: dict[str, Any] | None = None,
    report_generated_at: str | None = None,
    host_information: dict[str, Any] | None = None,
    host_evidence: dict[str, Any] | None = None,
    artifacts: dict[str, str] | None = None,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``artifacts`` must already be package-relative (see ``portable_artifact_references``)."""
    run = (completed_model or {}).get("run") or {}
    # Report-writer time only; no frozen run-completion wall clock exists.
    stamp = report_generated_at or now_iso()
    host_press = run.get("host_press_count")
    elapsed_s = run.get("elapsed_s")
    payload: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "schema_version": EVIDENCE_SCHEMA,
        "tool_id": TOOL_ID,
        "tool_name": TOOL_NAME,
        "tool_version": TOOL_VERSION,
        "run_id": run_id,
        "run_status": run_status,
        "report_generated_at": stamp,
        "target_product": target or "",
        "operator": operator or "",
        "analysis_scope": "measurement_only",
        "elapsed_s": elapsed_s,
        "settings": factual_settings(settings),
        "measurements": factual_measurements(events, host_press_count=host_press),
        "host_information": host_information,
        "host_test_environment": build_host_environment(settings),
        "host_evidence": host_evidence,
        "events": factual_events(events),
    }
    if artifacts is not None:
        payload["artifacts"] = dict(artifacts)
    if verification is not None:
        payload["report_artifacts_verified"] = verification
    return payload


def write_events_csv(path: Path, events: list[dict[str, Any]]) -> None:
    rows = factual_events(events)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FACTUAL_EVENT_FIELDS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_evidence_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def verify_standard_artifacts(paths: dict[str, str]) -> dict[str, Any]:
    """All four standard artifacts are required; any missing file fails verification."""
    status: dict[str, Any] = {}
    missing: list[str] = []
    for key in STANDARD_BUNDLE_KEYS:
        value = paths.get(key) or ""
        exists = bool(value) and Path(value).is_file()
        status[key] = {"path": value, "exists": exists}
        if not exists:
            missing.append(key)
    return {
        "ok": not missing,
        "missing": missing,
        "status": status,
        "required": list(STANDARD_REQUIRED_KEYS),
    }


def portable_artifact_references(paths: dict[str, str]) -> dict[str, str]:
    """Package-relative file names; never absolute machine paths."""
    refs: dict[str, str] = {}
    for key, portable_key in PORTABLE_ARTIFACT_KEYS.items():
        value = paths.get(key) or ""
        refs[portable_key] = Path(value).name if value else ""
    return refs


def portable_verification(verification: dict[str, Any]) -> dict[str, Any]:
    """Verification result safe to embed in evidence JSON (file names only)."""
    status = {}
    for key, entry in (verification.get("status") or {}).items():
        value = str((entry or {}).get("path") or "")
        status[PORTABLE_ARTIFACT_KEYS.get(key, key)] = {
            "file": Path(value).name if value else "",
            "exists": bool((entry or {}).get("exists")),
        }
    return {
        "ok": bool(verification.get("ok")),
        "missing": [PORTABLE_ARTIFACT_KEYS.get(k, k) for k in verification.get("missing") or []],
        "required": [PORTABLE_ARTIFACT_KEYS.get(k, k) for k in verification.get("required") or []],
        "status": status,
    }


def _walk_mapping_keys(payload: Any, *, prefix: str = "") -> list[tuple[str, str, Any]]:
    found: list[tuple[str, str, Any]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.append((path, str(key), value))
            found.extend(_walk_mapping_keys(value, prefix=path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload[:5000]):
            found.extend(_walk_mapping_keys(item, prefix=f"{prefix}[{index}]"))
    return found


def scan_forbidden_semantics(payload: Any, *, source: str = "json") -> list[str]:
    """Inspect structured keys/values. Does not substring-search prose."""
    hits: list[str] = []
    for path, key, value in _walk_mapping_keys(payload):
        if key in FORBIDDEN_STANDARD_KEYS or key in HIDDEN_HEURISTIC_THRESHOLD_KEYS:
            hits.append(f"{source}:{path}")
            continue
        if key in DUT_VERDICT_VALUE_KEYS and isinstance(value, str) and value.strip().upper() in DUT_VERDICT_TOKENS:
            hits.append(f"{source}:{path}={value}")
        elif key in DUT_VERDICT_VALUE_KEYS and isinstance(value, bool) and key in {"pass", "passed"}:
            hits.append(f"{source}:{path}={value}")
    return hits


def scan_csv_headers(headers: list[str]) -> list[str]:
    hits: list[str] = []
    for name in headers:
        if name in FORBIDDEN_CSV_COLUMNS or name in FORBIDDEN_STANDARD_KEYS:
            hits.append(f"csv:{name}")
    return hits


def standard_bundle_filenames(run_id: str) -> dict[str, str]:
    return artifact_names(run_id)
