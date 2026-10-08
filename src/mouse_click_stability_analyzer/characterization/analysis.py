"""Per-run and cross-run characterization analysis.

Primary residual math is independent of Schedule Association Window W and of
Stage 2D Configured Interval Range. Repeat-to-repeat (run-level) summaries are
the aggregation unit. Individual clicks are never treated as IID replicates.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..core import percentile
from ..schema import EVIDENCE_SCHEMA
from .evidence import (
    accepted_focus_presses,
    comparison_fields_present,
    host_context,
    load_evidence_json,
    resolve_evidence_path,
    schema_ok,
    settings_of,
)
from .issues import LEVEL_ERROR, LEVEL_EXCLUDED, LEVEL_INFO, issue
from .manifest import ACTUATION_PHYSICAL
from .math import (
    HALF_OPEN_TIE,
    RESIDUAL_RANGE_NOTE,
    descriptive_absolute,
    descriptive_boundary,
    descriptive_signed,
    duration_window_ms,
    ecdf_absolute,
    fraction_within_ms,
    in_configured_window,
    nearest_slot,
    nominal_slot_count,
    occupancy_summary,
    reference_interval_ms,
    tertile_name,
)

ROLE_ELIGIBLE = "eligible_characterization"
ROLE_PIPELINE = "pipeline_only"
ROLE_UNUSABLE = "unusable"

RUN_STATUS_COMPLETE = "COMPLETE"


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9


def _event_index(event: dict[str, Any], fallback: int) -> Any:
    if event.get("click_index") not in (None, ""):
        return event.get("click_index")
    if event.get("index") not in (None, ""):
        return event.get("index")
    return fallback


def package_ref(row: dict[str, Any]) -> str:
    """Manifest-supplied package reference, never the resolved absolute path."""
    return str(row.get("package_path_raw") or "").replace("\\", "/")


def evidence_file_ref(package: Path | None, evidence_path: Path | None) -> str:
    if evidence_path is None:
        return ""
    if package is not None and package.is_dir():
        try:
            return evidence_path.resolve().relative_to(package.resolve()).as_posix()
        except ValueError:
            pass
    return evidence_path.name


def auto_stop_from_evidence(payload: dict[str, Any] | None) -> bool | None:
    """Explicit Auto Stop state recorded in evidence, or None when not recorded.

    MCSA_EVIDENCE_V1 has no explicit Auto Stop field. duration_sec is a duration
    fact and must not be read as Auto Stop state, so this is always None until
    the evidence contract records the state directly.
    """
    _ = payload
    return None


def classify_role(row: dict[str, Any], issues: list[dict[str, Any]]) -> str:
    if any(item["level"] == LEVEL_ERROR for item in issues):
        return ROLE_UNUSABLE
    if any(item["level"] == LEVEL_EXCLUDED for item in issues):
        return ROLE_PIPELINE
    if row.get("characterization_eligible") and row.get("actuation_source") == ACTUATION_PHYSICAL:
        return ROLE_ELIGIBLE
    return ROLE_PIPELINE


def validate_run(row: dict[str, Any]) -> tuple[dict[str, Any] | None, Path | None, list[dict[str, Any]]]:
    """Load and check one manifest row. Never mutates source evidence."""
    issues: list[dict[str, Any]] = []
    run_id = row.get("run_id") or ""
    package = Path(row["package_path"]) if row.get("package_path") else None
    if package is None:
        issues.append(issue(LEVEL_ERROR, "missing_package_path", "package_path is empty", run_id=run_id))
        return None, None, issues
    if not package.exists():
        issues.append(issue(
            LEVEL_ERROR, "missing_package",
            f"package path does not exist: {package_ref(row) or package.name}",
            run_id=run_id,
        ))
        return None, package, issues
    evidence_path = resolve_evidence_path(package)
    if evidence_path is None:
        issues.append(issue(
            LEVEL_ERROR, "missing_evidence_json",
            "MCSA_EVIDENCE_V1 evidence.json was not found (legacy summary/detail are not inputs)",
            run_id=run_id,
        ))
        return None, package, issues
    try:
        payload = load_evidence_json(evidence_path)
    except (OSError, ValueError) as exc:
        issues.append(issue(
            LEVEL_ERROR, "invalid_evidence_json",
            f"evidence.json could not be parsed: {exc}",
            run_id=run_id,
        ))
        return None, evidence_path, issues
    if not schema_ok(payload):
        issues.append(issue(
            LEVEL_ERROR, "invalid_schema",
            f"schema must be {EVIDENCE_SCHEMA}",
            run_id=run_id,
        ))
        return payload, evidence_path, issues

    if comparison_fields_present(payload):
        issues.append(issue(
            LEVEL_INFO, "stage2d_ignored",
            "Stage 2D Configured Interval Range fields are present and ignored",
            run_id=run_id,
        ))

    evidence_run_id = str(payload.get("run_id") or "")
    if evidence_run_id and run_id and evidence_run_id != run_id:
        issues.append(issue(
            LEVEL_ERROR, "run_id_mismatch",
            f"manifest run_id {run_id!r} does not match evidence run_id {evidence_run_id!r}",
            run_id=run_id,
        ))

    settings = settings_of(payload)
    run_status = str(payload.get("run_status") or "")
    manual = bool(settings.get("manual_mode"))
    hz = _finite(settings.get("fixture_reference_hz"))
    duration = _finite(settings.get("duration_sec"))
    focus = str(settings.get("focus_button") or "").strip()
    window = _finite(settings.get("fixture_timing_tolerance_ms"))

    wants_real = bool(row.get("characterization_eligible")) and row.get("actuation_source") == ACTUATION_PHYSICAL
    purpose = str(row.get("purpose") or "")

    if not row.get("characterization_eligible"):
        issues.append(issue(
            LEVEL_EXCLUDED, "manifest_not_eligible",
            row.get("exclusion_reason") or "characterization_eligible = no",
            run_id=run_id,
        ))
    elif row.get("actuation_source") != ACTUATION_PHYSICAL:
        issues.append(issue(
            LEVEL_EXCLUDED, "actuation_not_physical_fixture",
            f"actuation_source={row.get('actuation_source')}; Fixture software mode does not prove physical actuation",
            run_id=run_id,
        ))

    if manual:
        issues.append(issue(
            LEVEL_EXCLUDED, "manual_mode",
            "Manual mode is not Fixture-schedule characterization evidence",
            run_id=run_id,
        ))
    if run_status != RUN_STATUS_COMPLETE:
        issues.append(issue(
            LEVEL_EXCLUDED, "run_status_not_complete",
            f"run_status={run_status or 'missing'} is not COMPLETE",
            run_id=run_id,
        ))
    if hz is None or hz <= 0:
        issues.append(issue(
            LEVEL_ERROR, "invalid_reference_rate",
            "fixture_reference_hz must be finite and > 0",
            run_id=run_id,
        ))
    if duration is None or duration <= 0:
        issues.append(issue(
            LEVEL_ERROR, "invalid_duration",
            "duration_sec must be finite and > 0",
            run_id=run_id,
        ))
    if not focus:
        issues.append(issue(LEVEL_ERROR, "missing_focus_button", "focus_button is missing", run_id=run_id))

    expected_rate = row.get("expected_rate_hz")
    expected_duration = row.get("expected_duration_sec")
    if expected_rate is not None and hz is not None and not _close(expected_rate, hz):
        issues.append(issue(
            LEVEL_ERROR, "reference_rate_mismatch",
            f"manifest expected_rate_hz={expected_rate} does not match evidence fixture_reference_hz={hz}",
            run_id=run_id,
        ))
    if expected_duration is not None and duration is not None and not _close(expected_duration, duration):
        issues.append(issue(
            LEVEL_ERROR, "duration_mismatch",
            f"manifest expected_duration_sec={expected_duration} does not match evidence duration_sec={duration}",
            run_id=run_id,
        ))
    if row.get("auto_stop_on") is False:
        issues.append(issue(
            LEVEL_EXCLUDED if not wants_real else LEVEL_ERROR,
            "auto_stop_off",
            "Auto Stop is off; characterization window is the configured duration",
            run_id=run_id,
        ))
    manifest_auto_stop = row.get("auto_stop_on")
    evidence_auto_stop = auto_stop_from_evidence(payload)
    if evidence_auto_stop is None:
        if wants_real and manifest_auto_stop is not False:
            issues.append(issue(
                LEVEL_ERROR,
                "auto_stop_unverifiable",
                "evidence does not record an explicit Auto Stop state; "
                "controlled characterization requires Auto Stop ON to be verifiable",
                run_id=run_id,
            ))
        elif not wants_real:
            issues.append(issue(
                LEVEL_INFO,
                "auto_stop_evidence_unavailable",
                "Auto Stop evidence state unavailable",
                run_id=run_id,
            ))
    elif manifest_auto_stop is not None and manifest_auto_stop != evidence_auto_stop:
        issues.append(issue(
            LEVEL_ERROR if wants_real else LEVEL_INFO,
            "auto_stop_mismatch",
            f"manifest auto_stop_on={'yes' if manifest_auto_stop else 'no'} does not match "
            f"evidence Auto Stop={'on' if evidence_auto_stop else 'off'}",
            run_id=run_id,
        ))
    elif wants_real and manifest_auto_stop is None and evidence_auto_stop is False:
        issues.append(issue(
            LEVEL_ERROR,
            "auto_stop_off",
            "evidence records Auto Stop off; controlled characterization requires Auto Stop ON",
            run_id=run_id,
        ))
    if "pipeline" in purpose.lower() or "pilot" in purpose.lower():
        if wants_real and row.get("actuation_source") != ACTUATION_PHYSICAL:
            issues.append(issue(
                LEVEL_INFO, "pipeline_pilot",
                "purpose indicates a pipeline pilot",
                run_id=run_id,
            ))

    presses = accepted_focus_presses(payload) if focus and hz and duration else []
    if wants_real and not any(item["level"] in (LEVEL_ERROR, LEVEL_EXCLUDED) for item in issues):
        if len(presses) < 1:
            issues.append(issue(
                LEVEL_ERROR, "no_accepted_focus_presses",
                "no accepted focus-button timestamps",
                run_id=run_id,
            ))

    _ = window  # retained as capture-time context only
    return payload, evidence_path, issues


def analyze_run(row: dict[str, Any], payload: dict[str, Any], evidence_path: Path, issues: list[dict[str, Any]]) -> dict[str, Any]:
    settings = settings_of(payload)
    hz = _finite(settings.get("fixture_reference_hz"))
    duration = _finite(settings.get("duration_sec"))
    window_w = _finite(settings.get("fixture_timing_tolerance_ms"))
    presses = accepted_focus_presses(payload)
    role = classify_role(row, issues)
    source_t0 = float(presses[0]["press_elapsed_ms"]) if presses else None
    period = reference_interval_ms(hz) if hz and hz > 0 else None
    window_ms = duration_window_ms(duration) if duration and duration > 0 else None

    observations: list[dict[str, Any]] = []
    occupancy_outside_nominal = 0
    outside_window = 0
    malformed = 0
    slot_count = 0
    slot_hits: list[int] = []
    if period and window_ms is not None and presses:
        slot_count = nominal_slot_count(duration, hz)
        slot_hits = [0] * slot_count
        for ordinal, event in enumerate(presses):
            press = float(event["press_elapsed_ms"])
            t_rel = press - float(source_t0)
            if t_rel < 0:
                malformed += 1
                continue
            if not in_configured_window(t_rel, window_ms):
                outside_window += 1
                continue
            assigned = nearest_slot(t_rel, period)
            k = int(assigned["nearest_slot_index"])
            is_anchor = ordinal == 0
            record = {
                "run_id": row["run_id"],
                "event_index": _event_index(event, ordinal + 1),
                "accepted_focus_ordinal": ordinal,
                "is_anchor": is_anchor,
                "press_elapsed_ms": press,
                "t_rel_ms": t_rel,
                "nearest_slot_index": k,
                "nominal_slot_time_ms": assigned["nominal_slot_time_ms"],
                "wrapped_residual_ms": assigned["wrapped_residual_ms"],
                "absolute_residual_ms": assigned["absolute_residual_ms"],
                "boundary_distance_ms": assigned["boundary_distance_ms"],
                "in_residual_sample": (not is_anchor),
                "window_span": tertile_name(t_rel, window_ms),
            }
            observations.append(record)
            if 0 <= k < slot_count:
                slot_hits[k] += 1
            else:
                occupancy_outside_nominal += 1

    residual_rows = [row_obs for row_obs in observations if row_obs["in_residual_sample"]]
    signed = [float(item["wrapped_residual_ms"]) for item in residual_rows]
    absolute = [float(item["absolute_residual_ms"]) for item in residual_rows]
    boundary = [float(item["boundary_distance_ms"]) for item in residual_rows]

    if residual_rows:
        issues.append(issue(
            LEVEL_INFO, "residual_sample_excludes_anchor",
            "first accepted focus-button press is t0/slot 0 and is excluded from residual statistics",
            run_id=row["run_id"],
        ))

    overlap = None
    w_over_t = None
    if period and window_w is not None:
        w_over_t = window_w / period
        overlap = (2.0 * window_w) >= period

    occupancy = occupancy_summary(slot_hits) if slot_hits else occupancy_summary([])
    occupancy["observations_assigned_outside_nominal_slots"] = occupancy_outside_nominal
    occupancy["anchor_included_in_occupancy"] = True
    occupancy["observation_outside_configured_window_count"] = outside_window
    occupancy["malformed_negative_t_rel_count"] = malformed

    tertiles: dict[str, dict[str, Any]] = {}
    for name in ("early", "middle", "late"):
        values = [item["wrapped_residual_ms"] for item in residual_rows if item["window_span"] == name]
        tertiles[name] = descriptive_signed(values)

    w_fraction = fraction_within_ms(absolute, window_w)
    host = host_context(payload)
    not_real = role != ROLE_ELIGIBLE

    summary = {
        "run_id": row["run_id"],
        "role": role,
        "characterization_evidence": role == ROLE_ELIGIBLE,
        "not_characterization_evidence": not_real,
        "campaign_id": row.get("campaign_id") or "",
        "purpose": row.get("purpose") or "",
        "actuation_source": row.get("actuation_source"),
        "exclusion_reason": row.get("exclusion_reason") or "",
        "fixture_vendor": row.get("fixture_vendor") or "",
        "fixture_model": row.get("fixture_model") or "",
        "fixture_unit_id": row.get("fixture_unit_id") or "",
        "fixture_firmware": row.get("fixture_firmware") or "",
        "control_dut_id": row.get("control_dut_id") or "",
        "host_label": row.get("host_label") or "",
        "usb_port_label": row.get("usb_port_label") or "",
        "repeat_index": row.get("repeat_index"),
        "vendor_timing_accuracy_ms": row.get("vendor_timing_accuracy_ms"),
        "vendor_spec_reference": row.get("vendor_spec_reference") or "",
        "vendor_spec_is_informational_only": True,
        "package_ref": package_ref(row),
        "evidence_file": evidence_file_ref(
            Path(row["package_path"]) if row.get("package_path") else None, evidence_path,
        ),
        "evidence_run_id": payload.get("run_id"),
        "run_status": payload.get("run_status"),
        "tool_version": payload.get("tool_version"),
        "analysis_scope": payload.get("analysis_scope"),
        "manual_mode": bool(settings.get("manual_mode")),
        "focus_button": settings.get("focus_button"),
        "fixture_reference_hz": hz,
        "reference_interval_ms": period,
        "duration_sec": duration,
        "auto_stop_on_manifest": row.get("auto_stop_on"),
        "auto_stop_on_evidence": auto_stop_from_evidence(payload),
        "configured_association_window_ms": window_w,
        "configured_association_window_is_context_only": True,
        "w_over_t": w_over_t,
        "adjacent_window_overlap": overlap,
        "source_t0_ms": source_t0,
        "accepted_focus_press_count": len(presses),
        "in_window_observation_count": len(observations),
        "analyzed_residual_count": len(residual_rows),
        "observation_outside_configured_window_count": outside_window,
        "signed_residual": descriptive_signed(signed),
        "absolute_residual": descriptive_absolute(absolute),
        "boundary_distance": descriptive_boundary(boundary),
        "current_window_context_fraction_abs_le_w": w_fraction,
        "occupancy": occupancy,
        "window_span_residuals": tertiles,
        "host": host,
        "issues": issues,
        "residual_convention": HALF_OPEN_TIE,
        "residual_range": RESIDUAL_RANGE_NOTE,
    }
    return {
        "summary": summary,
        "observations": observations,
        "residuals": residual_rows,
        "ecdf": ecdf_absolute(absolute),
        "slot_counts": slot_hits,
        "issues": issues,
        "role": role,
        "row": row,
        "payload": payload,
    }


def _metric_pack(values: list[float | None]) -> dict[str, float | None]:
    finite = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not finite:
        return {"run_count": 0, "minimum": None, "maximum": None, "median": None, "range": None}
    return {
        "run_count": len(finite),
        "minimum": min(finite),
        "maximum": max(finite),
        "median": percentile(finite, 50),
        "range": max(finite) - min(finite),
    }


def _group_from_runs(runs: list[dict[str, Any]], *, group_id: str, group_kind: str, **labels: Any) -> dict[str, Any]:
    abs_p95 = [r["summary"]["absolute_residual"]["p95"] for r in runs]
    abs_p99 = [r["summary"]["absolute_residual"]["p99"] for r in runs]
    abs_max = [r["summary"]["absolute_residual"]["maximum"] for r in runs]
    signed_mean = [r["summary"]["signed_residual"]["mean"] for r in runs]
    signed_median = [r["summary"]["signed_residual"]["median"] for r in runs]
    windows = sorted({
        r["summary"]["configured_association_window_ms"]
        for r in runs
        if r["summary"]["configured_association_window_ms"] is not None
    })
    hosts = sorted({str(r["summary"]["host_label"] or "") for r in runs})
    units = sorted({str(r["summary"]["fixture_unit_id"] or "") for r in runs})
    rates = sorted({r["summary"]["fixture_reference_hz"] for r in runs if r["summary"]["fixture_reference_hz"]})
    return {
        "group_id": group_id,
        "group_kind": group_kind,
        "characterization_evidence": True,
        "run_ids": [r["summary"]["run_id"] for r in runs],
        "run_count": len(runs),
        "aggregation_unit": "run",
        "iid_event_bootstrap": False,
        "pooled_click_distribution": False,
        "hosts": hosts,
        "fixture_units": units,
        "fixture_reference_hz_values": rates,
        "configured_association_windows_ms": windows,
        "association_window_varied": len(windows) > 1,
        "run_p95_absolute_residual_ms": _metric_pack(abs_p95),
        "run_p99_absolute_residual_ms": _metric_pack(abs_p99),
        "run_maximum_absolute_residual_ms": _metric_pack(abs_max),
        "run_signed_residual_mean_ms": _metric_pack(signed_mean),
        "run_signed_residual_median_ms": _metric_pack(signed_median),
        "run_to_run_signed_residual_shift_ms": _metric_pack(signed_mean)["range"],
        **labels,
    }


def group_runs(analyzed: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible = [item for item in analyzed if item["role"] == ROLE_ELIGIBLE]
    extra_issues: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    by_rate_host: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    by_rate: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    by_campaign: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in eligible:
        summary = item["summary"]
        campaign = summary.get("campaign_id") or ""
        rate = summary.get("fixture_reference_hz")
        host = summary.get("host_label") or ""
        by_rate_host[(campaign, rate, host)].append(item)
        by_rate[(campaign, rate)].append(item)
        by_campaign[campaign].append(item)
    for (campaign, rate, host), runs in sorted(by_rate_host.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0, str(kv[0][2]))):
        groups.append(_group_from_runs(
            runs,
            group_id=f"{campaign}|{rate}|{host}",
            group_kind="rate_host",
            campaign_id=campaign,
            fixture_reference_hz=rate,
            host_label=host,
        ))
    for (campaign, rate), runs in sorted(by_rate.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0)):
        groups.append(_group_from_runs(
            runs,
            group_id=f"{campaign}|{rate}|cross_host",
            group_kind="rate_cross_host",
            campaign_id=campaign,
            fixture_reference_hz=rate,
        ))
    for campaign, runs in sorted(by_campaign.items()):
        windows = {r["summary"]["configured_association_window_ms"] for r in runs}
        if len(windows) > 1:
            extra_issues.append(issue(
                LEVEL_INFO, "association_window_varied",
                "configured Association Window differs between runs in this campaign; "
                "W-independent residuals remain valid; do not mix W-dependent Host Evidence match rates",
                campaign_id=campaign,
            ))
        groups.append(_group_from_runs(
            runs,
            group_id=f"{campaign}|all",
            group_kind="campaign",
            campaign_id=campaign,
        ))
    return groups, extra_issues


def analyze_campaign(rows: list[dict[str, Any]], *, manifest_issues: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    analyzed: list[dict[str, Any]] = []
    all_issues = list(manifest_issues or [])
    for row in rows:
        payload, evidence_path, issues = validate_run(row)
        all_issues.extend(issues)
        if payload is None or evidence_path is None:
            analyzed.append({
                "summary": {
                    "run_id": row.get("run_id"),
                    "role": ROLE_UNUSABLE,
                    "characterization_evidence": False,
                    "not_characterization_evidence": True,
                    "campaign_id": row.get("campaign_id") or "",
                    "purpose": row.get("purpose") or "",
                    "actuation_source": row.get("actuation_source"),
                    "package_ref": package_ref(row),
                    "evidence_file": evidence_file_ref(
                        Path(row["package_path"]) if row.get("package_path") else None, evidence_path,
                    ),
                    "auto_stop_on_manifest": row.get("auto_stop_on"),
                    "auto_stop_on_evidence": None,
                    "issues": issues,
                },
                "observations": [],
                "residuals": [],
                "ecdf": [],
                "slot_counts": [],
                "issues": issues,
                "role": ROLE_UNUSABLE,
                "row": row,
                "payload": None,
            })
            continue
        result = analyze_run(row, payload, evidence_path, issues)
        analyzed.append(result)
    groups, group_issues = group_runs(analyzed)
    all_issues.extend(group_issues)
    eligible_count = sum(1 for item in analyzed if item["role"] == ROLE_ELIGIBLE)
    campaign_ids = sorted({str(row.get("campaign_id") or "") for row in rows if row.get("campaign_id")})
    return {
        "analyzed": analyzed,
        "groups": groups,
        "issues": all_issues,
        "eligible_run_count": eligible_count,
        "pipeline_only_run_count": sum(1 for item in analyzed if item["role"] == ROLE_PIPELINE),
        "unusable_run_count": sum(1 for item in analyzed if item["role"] == ROLE_UNUSABLE),
        "campaign_ids": campaign_ids,
        "has_characterization_evidence": eligible_count > 0,
    }
