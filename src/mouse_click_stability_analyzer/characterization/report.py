"""Characterization CSV / JSON / HTML writers. Not a DUT report."""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from html import escape as _e
from pathlib import Path
from typing import Any

from . import ANALYSIS_CONTRACT, RESIDUAL_CONVENTION
from .analysis import package_ref
from .math import HALF_OPEN_TIE, RESIDUAL_RANGE_NOTE

OUTPUT_NAMES = {
    "run_summary": "characterization_run_summary.csv",
    "group_summary": "characterization_group_summary.csv",
    "residuals": "characterization_residuals.csv",
    "occupancy": "characterization_slot_occupancy.csv",
    "analysis_json": "characterization_analysis.json",
    "report_html": "characterization_report.html",
}

_BANNED_COPY = (
    "recommended Association Window",
    "recommended window",
    "optimal W",
    "best tolerance",
    "pass threshold",
    "fail threshold",
    "DUT pass",
    "DUT fail",
)

_RUN_CSV_FIELDS = [
    "run_id", "campaign_id", "role", "characterization_evidence",
    "not_characterization_evidence", "purpose", "actuation_source",
    "host_label", "control_dut_id", "fixture_unit_id", "repeat_index",
    "fixture_reference_hz", "reference_interval_ms", "duration_sec",
    "configured_association_window_ms", "w_over_t", "adjacent_window_overlap",
    "source_t0_ms", "analyzed_residual_count",
    "signed_mean", "signed_median", "signed_min", "signed_max", "signed_stdev",
    "abs_median", "abs_p90", "abs_p95", "abs_p99", "abs_max",
    "boundary_min", "boundary_median",
    "current_window_context_fraction_abs_le_w",
    "nominal_slot_count", "occupied_slot_count", "empty_slot_count",
    "slots_with_one_observation", "slots_with_multiple_observations",
    "observation_outside_configured_window_count",
    "vendor_timing_accuracy_ms", "vendor_spec_reference",
]

_RESIDUAL_FIELDS = [
    "run_id", "event_index", "is_anchor", "in_residual_sample",
    "t_rel_ms", "nearest_slot_index", "nominal_slot_time_ms",
    "wrapped_residual_ms", "absolute_residual_ms", "boundary_distance_ms",
    "window_span",
]

_OCCUPANCY_FIELDS = [
    "run_id", "nearest_slot_index", "nominal_slot_time_ms", "observation_count",
    "empty_slot", "same_slot_multiplicity",
]

_GROUP_FIELDS = [
    "group_id", "group_kind", "campaign_id", "fixture_reference_hz", "host_label",
    "run_count", "run_ids", "aggregation_unit",
    "p95_min", "p95_median", "p95_max", "p95_range",
    "p99_min", "p99_median", "p99_max", "p99_range",
    "max_abs_min", "max_abs_median", "max_abs_max", "max_abs_range",
    "signed_mean_range", "association_window_varied",
]


def _num(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return f"{value:.6g}"
    return value


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _num(row.get(key)) for key in fieldnames})


def _analysis_json(campaign: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    analyzed = campaign["analyzed"]
    return {
        "schema": ANALYSIS_CONTRACT,
        "analysis_contract_version": ANALYSIS_CONTRACT,
        "residual_convention_id": RESIDUAL_CONVENTION,
        "residual_convention": HALF_OPEN_TIE,
        "residual_range": RESIDUAL_RANGE_NOTE,
        "percentile_convention": "linear interpolation between closest ranks (core.percentile)",
        "ecdf_convention": "sorted |residual|; cumulative_fraction = (i+1)/n",
        "anchor_rule": "first accepted focus-button press is t0 and slot 0; excluded from residual sample; included in slot occupancy",
        "window_rule": "0 <= t_rel_ms < duration_sec * 1000",
        "independent_of_association_window": True,
        "independent_of_configured_interval_range": True,
        "window_policy_decision": None,
        "window_policy_status": "not decided in 4E-B1",
        "iid_event_bootstrap": False,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "campaign_ids": campaign["campaign_ids"],
        "has_characterization_evidence": campaign["has_characterization_evidence"],
        "eligible_run_count": campaign["eligible_run_count"],
        "pipeline_only_run_count": campaign["pipeline_only_run_count"],
        "unusable_run_count": campaign["unusable_run_count"],
        "source_run_ids": [item["summary"].get("run_id") for item in analyzed],
        "source_evidence_refs": [
            {
                "run_id": item["summary"].get("run_id"),
                "package_ref": item["summary"].get("package_ref") or "",
                "evidence_file": item["summary"].get("evidence_file") or "",
            }
            for item in analyzed
        ],
        "manifest_rows": [
            {"package_ref": package_ref(row)} | {key: row.get(key) for key in (
                "run_id", "campaign_id", "purpose", "actuation_source",
                "characterization_eligible", "exclusion_reason", "host_label",
                "expected_rate_hz", "expected_duration_sec", "repeat_index",
                "auto_stop_on",
            )}
            for row in rows
        ],
        "issues": campaign["issues"],
        "per_run": [item["summary"] | {"ecdf": item["ecdf"]} for item in analyzed],
        "groups": campaign["groups"],
        "notices": [
            "NOT CHARACTERIZATION EVIDENCE" if not campaign["has_characterization_evidence"] else "Eligible physical-fixture runs are listed separately from pipeline-only runs.",
            "Configured Interval Range fields are ignored.",
            "Schedule Association Window is capture-time context only.",
            "Vendor timing accuracy is provenance/context only.",
            "4E-B1 does not choose a Schedule Association Window.",
        ],
    }


def _run_csv_row(summary: dict[str, Any]) -> dict[str, Any]:
    occ = summary.get("occupancy") or {}
    signed = summary.get("signed_residual") or {}
    absolute = summary.get("absolute_residual") or {}
    boundary = summary.get("boundary_distance") or {}
    return {
        "run_id": summary.get("run_id"),
        "campaign_id": summary.get("campaign_id"),
        "role": summary.get("role"),
        "characterization_evidence": summary.get("characterization_evidence"),
        "not_characterization_evidence": summary.get("not_characterization_evidence"),
        "purpose": summary.get("purpose"),
        "actuation_source": summary.get("actuation_source"),
        "host_label": summary.get("host_label"),
        "control_dut_id": summary.get("control_dut_id"),
        "fixture_unit_id": summary.get("fixture_unit_id"),
        "repeat_index": summary.get("repeat_index"),
        "fixture_reference_hz": summary.get("fixture_reference_hz"),
        "reference_interval_ms": summary.get("reference_interval_ms"),
        "duration_sec": summary.get("duration_sec"),
        "configured_association_window_ms": summary.get("configured_association_window_ms"),
        "w_over_t": summary.get("w_over_t"),
        "adjacent_window_overlap": summary.get("adjacent_window_overlap"),
        "source_t0_ms": summary.get("source_t0_ms"),
        "analyzed_residual_count": summary.get("analyzed_residual_count"),
        "signed_mean": signed.get("mean"),
        "signed_median": signed.get("median"),
        "signed_min": signed.get("minimum"),
        "signed_max": signed.get("maximum"),
        "signed_stdev": signed.get("stdev"),
        "abs_median": absolute.get("median"),
        "abs_p90": absolute.get("p90"),
        "abs_p95": absolute.get("p95"),
        "abs_p99": absolute.get("p99"),
        "abs_max": absolute.get("maximum"),
        "boundary_min": boundary.get("minimum"),
        "boundary_median": boundary.get("median"),
        "current_window_context_fraction_abs_le_w": summary.get("current_window_context_fraction_abs_le_w"),
        "nominal_slot_count": occ.get("nominal_slot_count"),
        "occupied_slot_count": occ.get("occupied_slot_count"),
        "empty_slot_count": occ.get("empty_slot_count"),
        "slots_with_one_observation": occ.get("slots_with_one_observation"),
        "slots_with_multiple_observations": occ.get("slots_with_multiple_observations"),
        "observation_outside_configured_window_count": summary.get("observation_outside_configured_window_count"),
        "vendor_timing_accuracy_ms": summary.get("vendor_timing_accuracy_ms"),
        "vendor_spec_reference": summary.get("vendor_spec_reference"),
    }


def _group_csv_row(group: dict[str, Any]) -> dict[str, Any]:
    p95 = group["run_p95_absolute_residual_ms"]
    p99 = group["run_p99_absolute_residual_ms"]
    mx = group["run_maximum_absolute_residual_ms"]
    return {
        "group_id": group["group_id"],
        "group_kind": group["group_kind"],
        "campaign_id": group.get("campaign_id"),
        "fixture_reference_hz": group.get("fixture_reference_hz"),
        "host_label": group.get("host_label"),
        "run_count": group["run_count"],
        "run_ids": " ".join(group["run_ids"]),
        "aggregation_unit": group["aggregation_unit"],
        "p95_min": p95["minimum"], "p95_median": p95["median"], "p95_max": p95["maximum"], "p95_range": p95["range"],
        "p99_min": p99["minimum"], "p99_median": p99["median"], "p99_max": p99["maximum"], "p99_range": p99["range"],
        "max_abs_min": mx["minimum"], "max_abs_median": mx["median"], "max_abs_max": mx["maximum"], "max_abs_range": mx["range"],
        "signed_mean_range": group.get("run_to_run_signed_residual_shift_ms"),
        "association_window_varied": group.get("association_window_varied"),
    }


def _occupancy_rows(item: dict[str, Any]) -> list[dict[str, Any]]:
    summary = item["summary"]
    period = summary.get("reference_interval_ms")
    rows = []
    for index, count in enumerate(item.get("slot_counts") or []):
        rows.append({
            "run_id": summary.get("run_id"),
            "nearest_slot_index": index,
            "nominal_slot_time_ms": (index * period) if period is not None else "",
            "observation_count": count,
            "empty_slot": count == 0,
            "same_slot_multiplicity": count > 1,
        })
    return rows


def _scale(value: float, lo: float, hi: float, a: float, b: float) -> float:
    if hi <= lo:
        return (a + b) / 2
    return a + (value - lo) / (hi - lo) * (b - a)


def _svg_residual(residuals: list[dict[str, Any]], period: float | None) -> str:
    if not residuals or not period:
        return "<p class='note'>No residual sample for this run.</p>"
    xs = [float(r["t_rel_ms"]) for r in residuals]
    ys = [float(r["wrapped_residual_ms"]) for r in residuals]
    w, h, l, r, t, btm = 640, 220, 48, 16, 12, 36
    xmin, xmax = min(xs), max(xs)
    if xmax <= xmin:
        xmax = xmin + 1
    half = period / 2.0
    ymin, ymax = -half, half
    pts = " ".join(
        f"{_scale(x, xmin, xmax, l, w - r):.1f},{_scale(y, ymin, ymax, h - btm, t):.1f}"
        for x, y in zip(xs, ys)
    )
    y0 = _scale(0, ymin, ymax, h - btm, t)
    y_hi = _scale(half, ymin, ymax, h - btm, t)
    y_lo = _scale(-half, ymin, ymax, h - btm, t)
    return (
        f"<svg viewBox='0 0 {w} {h}' role='img'>"
        f"<line x1='{l}' y1='{t}' x2='{l}' y2='{h - btm}' class='ax'/>"
        f"<line x1='{l}' y1='{h - btm}' x2='{w - r}' y2='{h - btm}' class='ax'/>"
        f"<line x1='{l}' y1='{y_hi:.1f}' x2='{w - r}' y2='{y_hi:.1f}' class='lim'/>"
        f"<line x1='{l}' y1='{y_lo:.1f}' x2='{w - r}' y2='{y_lo:.1f}' class='lim'/>"
        f"<line x1='{l}' y1='{y0:.1f}' x2='{w - r}' y2='{y0:.1f}' class='zero'/>"
        f"<polyline points='{pts}' class='series'/>"
        f"<text x='{w / 2:.0f}' y='{h - 8}' class='lb'>Elapsed from t0 (ms)</text>"
        f"<text x='12' y='{h / 2:.0f}' class='lb' transform='rotate(-90 12 {h / 2:.0f})'>Wrapped residual (ms)</text>"
        "</svg>"
        "<p class='note'>Solid line at 0 ms. Dashed lines at ±T/2 (adjacent-slot boundary). "
        "Configured Association Window is not drawn as an acceptance band.</p>"
    )


def _svg_ecdf(ecdf: list[dict[str, float]]) -> str:
    if not ecdf:
        return "<p class='note'>No ECDF (no residual sample).</p>"
    w, h, l, r, t, btm = 640, 220, 48, 16, 12, 36
    xs = [p["absolute_residual_ms"] for p in ecdf]
    ys = [p["cumulative_fraction"] for p in ecdf]
    xmax = max(xs) if max(xs) > 0 else 1
    pts = " ".join(
        f"{_scale(x, 0, xmax, l, w - r):.1f},{_scale(y, 0, 1, h - btm, t):.1f}"
        for x, y in zip(xs, ys)
    )
    return (
        f"<svg viewBox='0 0 {w} {h}' role='img'>"
        f"<line x1='{l}' y1='{t}' x2='{l}' y2='{h - btm}' class='ax'/>"
        f"<line x1='{l}' y1='{h - btm}' x2='{w - r}' y2='{h - btm}' class='ax'/>"
        f"<polyline points='{pts}' class='series'/>"
        f"<text x='{w / 2:.0f}' y='{h - 8}' class='lb'>|residual| (ms)</text>"
        f"<text x='12' y='{h / 2:.0f}' class='lb' transform='rotate(-90 12 {h / 2:.0f})'>Cumulative fraction</text>"
        "</svg>"
        "<p class='note'>Empirical distribution of absolute residual. Descriptive only; not an acceptance cutoff and not a window policy.</p>"
    )


def render_html(campaign: dict[str, Any]) -> str:
    banner = ""
    if not campaign["has_characterization_evidence"]:
        banner = (
            "<div class='banner'>NOT CHARACTERIZATION EVIDENCE. "
            "Runs in this output are pipeline validation and/or excluded. "
            "4E-B1 does not choose a Schedule Association Window.</div>"
        )
    issue_rows = "".join(
        f"<tr><td>{_e(item.get('level'))}</td><td>{_e(item.get('code'))}</td>"
        f"<td>{_e(item.get('run_id') or item.get('campaign_id') or '')}</td>"
        f"<td>{_e(item.get('message'))}</td></tr>"
        for item in campaign["issues"]
    )
    run_blocks = []
    for item in campaign["analyzed"]:
        s = item["summary"]
        evidence_flag = (
            "Eligible physical-fixture characterization evidence"
            if s.get("characterization_evidence")
            else "NOT CHARACTERIZATION EVIDENCE"
        )
        occ = s.get("occupancy") or {}
        signed = s.get("signed_residual") or {}
        absolute = s.get("absolute_residual") or {}
        boundary = s.get("boundary_distance") or {}
        host = s.get("host") or {}
        w = s.get("configured_association_window_ms")
        w_line = (
            f"Configured Association Window at capture: ±{w:.4g} ms (context only; not an acceptance limit)"
            if isinstance(w, (int, float)) and math.isfinite(w)
            else "Configured Association Window at capture: not recorded"
        )
        overlap = s.get("adjacent_window_overlap")
        overlap_text = "yes" if overlap else ("no" if overlap is False else "n/a")
        run_blocks.append(
            "<section>"
            f"<h2>Run {_e(str(s.get('run_id')))}</h2>"
            f"<p class='flag'>{_e(evidence_flag)}</p>"
            "<table class='kv'>"
            f"<tr><th>Campaign</th><td>{_e(str(s.get('campaign_id') or ''))}</td></tr>"
            f"<tr><th>Purpose</th><td>{_e(str(s.get('purpose') or ''))}</td></tr>"
            f"<tr><th>Actuation source</th><td>{_e(str(s.get('actuation_source') or ''))}</td></tr>"
            f"<tr><th>Eligibility role</th><td>{_e(str(s.get('role') or ''))}</td></tr>"
            f"<tr><th>Host label</th><td>{_e(str(s.get('host_label') or ''))}</td></tr>"
            f"<tr><th>Control DUT</th><td>{_e(str(s.get('control_dut_id') or ''))}</td></tr>"
            f"<tr><th>Fixture unit</th><td>{_e(str(s.get('fixture_unit_id') or ''))}</td></tr>"
            f"<tr><th>Repeat</th><td>{_e(str(s.get('repeat_index') if s.get('repeat_index') is not None else ''))}</td></tr>"
            f"<tr><th>Reference Rate</th><td>{_e(_num(s.get('fixture_reference_hz')))} Hz</td></tr>"
            f"<tr><th>Reference Interval T</th><td>{_e(_num(s.get('reference_interval_ms')))} ms</td></tr>"
            f"<tr><th>Configured duration</th><td>{_e(_num(s.get('duration_sec')))} s</td></tr>"
            f"<tr><th>t0 (source_t0_ms)</th><td>{_e(_num(s.get('source_t0_ms')))} ms</td></tr>"
            f"<tr><th>Analyzed residual count</th><td>{_e(str(s.get('analyzed_residual_count')))} (anchor excluded)</td></tr>"
            f"<tr><th>Outside configured window</th><td>{_e(str(s.get('observation_outside_configured_window_count')))}</td></tr>"
            "</table>"
            f"<p class='note'>{_e(w_line)}. W/T={_e(_num(s.get('w_over_t')))}. Adjacent-window overlap 2W≥T: {_e(overlap_text)}.</p>"
            f"<p class='note'>Current-window context: fraction with |residual| ≤ W is {_e(_num(s.get('current_window_context_fraction_abs_le_w')))}. "
            "This is not a pass rate and not a required W.</p>"
            "<h3>Signed residual (ms)</h3>"
            f"<p>mean {_e(_num(signed.get('mean')))}; median {_e(_num(signed.get('median')))}; "
            f"min {_e(_num(signed.get('minimum')))}; max {_e(_num(signed.get('maximum')))}; "
            f"stdev {_e(_num(signed.get('stdev')))}</p>"
            "<h3>Absolute residual (ms)</h3>"
            f"<p>median {_e(_num(absolute.get('median')))}; p90 {_e(_num(absolute.get('p90')))}; "
            f"p95 {_e(_num(absolute.get('p95')))}; p99 {_e(_num(absolute.get('p99')))}; "
            f"max {_e(_num(absolute.get('maximum')))}</p>"
            "<h3>Boundary distance (ms)</h3>"
            f"<p>minimum {_e(_num(boundary.get('minimum')))}; median {_e(_num(boundary.get('median')))}. "
            "Larger is farther from the adjacent-slot midpoint.</p>"
            "<h3>Slot occupancy / multiplicity</h3>"
            f"<p>nominal {occ.get('nominal_slot_count')}; occupied {occ.get('occupied_slot_count')}; "
            f"empty slots {occ.get('empty_slot_count')}; one observation {occ.get('slots_with_one_observation')}; "
            f"same-slot multiplicity {occ.get('slots_with_multiple_observations')}. "
            "Empty slots are not misses. Same-slot multiplicity is not bounce or duplicate.</p>"
            "<h3>Wrapped residual vs elapsed</h3>"
            f"{_svg_residual(item.get('residuals') or [], s.get('reference_interval_ms'))}"
            "<h3>Absolute residual ECDF</h3>"
            f"{_svg_ecdf(item.get('ecdf') or [])}"
            "<h3>Host context</h3>"
            "<table class='kv'>"
            f"<tr><th>Manufacturer</th><td>{_e(str(host.get('host_manufacturer') or ''))}</td></tr>"
            f"<tr><th>Model</th><td>{_e(str(host.get('host_model') or ''))}</td></tr>"
            f"<tr><th>Windows</th><td>{_e(str(host.get('os_name') or ''))} {_e(str(host.get('os_version') or ''))}</td></tr>"
            f"<tr><th>CPU</th><td>{_e(str(host.get('cpu_model') or ''))}</td></tr>"
            f"<tr><th>BIOS</th><td>{_e(str(host.get('bios_vendor') or ''))} {_e(str(host.get('bios_version') or ''))}</td></tr>"
            f"<tr><th>USB host controllers</th><td>{_e(str(host.get('usb_host_controllers') or ''))}</td></tr>"
            f"<tr><th>Capture backend</th><td>{_e(str(host.get('capture_backend') or ''))}</td></tr>"
            f"<tr><th>Tool / Python / Qt</th><td>{_e(str(host.get('tool_version') or ''))} / {_e(str(host.get('python_version') or ''))} / {_e(str(host.get('qt_version') or ''))}</td></tr>"
            "</table>"
            f"<p class='note'>DUT-to-controller attributed: {'yes' if host.get('dut_usb_controller_attributed') else 'no'}. Host differences are observed context, not causal diagnosis.</p>"
            f"<p class='note'>Vendor timing accuracy: {_e(_num(s.get('vendor_timing_accuracy_ms')))} ({_e(str(s.get('vendor_spec_reference') or 'no spec reference'))}). Provenance only; not an end-to-end tolerance and not W.</p>"
            "</section>"
        )
    group_rows = "".join(
        f"<tr><td>{_e(g['group_kind'])}</td><td>{_e(str(g.get('campaign_id') or ''))}</td>"
        f"<td>{_e(_num(g.get('fixture_reference_hz')))}</td><td>{_e(str(g.get('host_label') or ''))}</td>"
        f"<td>{g['run_count']}</td>"
        f"<td>{_e(_num(g['run_p95_absolute_residual_ms']['median']))}</td>"
        f"<td>{_e(_num(g['run_p95_absolute_residual_ms']['range']))}</td>"
        f"<td>{_e(_num(g['run_p99_absolute_residual_ms']['median']))}</td>"
        f"<td>{_e(_num(g['run_maximum_absolute_residual_ms']['range']))}</td>"
        f"<td>{_e(_num(g.get('run_to_run_signed_residual_shift_ms')))}</td></tr>"
        for g in campaign["groups"]
    )
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>Association Window characterization</title>
<style>
body{{margin:0;background:#f4f6f8;color:#1f2933;font:14px/1.5 "Segoe UI",system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 48px}}
h1{{font-size:22px;margin:0 0 8px}}
h2{{font-size:17px;margin:16px 0 8px}}
h3{{font-size:14px;margin:12px 0 6px;color:#5f6b7a}}
section{{background:#fff;border:1px solid #d9dee5;border-radius:10px;padding:16px 18px;margin:0 0 16px}}
.banner{{background:#fff7ed;border:1px solid #fdba74;padding:12px 14px;border-radius:8px;margin:0 0 16px;font-weight:600}}
.note{{font-size:12px;color:#5f6b7a}}
.flag{{font-weight:700}}
table{{border-collapse:collapse;width:100%}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #d9dee5;vertical-align:top}}
table.kv th{{width:38%;color:#5f6b7a}}
svg{{display:block;width:100%;height:auto}}
svg .ax{{stroke:#9aa5b1;stroke-width:1}}
svg .zero{{stroke:#111827;stroke-width:1}}
svg .lim{{stroke:#6b7280;stroke-width:1;stroke-dasharray:4 3}}
svg .series{{fill:none;stroke:#2563eb;stroke-width:1.4}}
svg .lb{{font-size:11px;fill:#5f6b7a}}
</style></head><body><main>
<h1>Schedule Association Window characterization</h1>
<p class="note">Offline 4E-B1 engineering analysis. Not a DUT report. Does not choose W.
Configured Interval Range is unused. Primary residuals are independent of the capture-time Association Window.</p>
{banner}
<section><h2>Campaign issues</h2>
<p class="note">ERROR cannot be analyzed reliably. EXCLUDED is intentionally not characterization evidence. INFO is a factual note. These are not DUT outcomes.</p>
<table><thead><tr><th>Level</th><th>Code</th><th>Id</th><th>Message</th></tr></thead>
<tbody>{issue_rows or "<tr><td colspan='4'>None</td></tr>"}</tbody></table>
</section>
<section><h2>Repeat-to-repeat groups</h2>
<p class="note">Grouped from per-run metrics. Clicks are not treated as independent replicates. Empty if no eligible physical-fixture runs.</p>
<table><thead><tr><th>Kind</th><th>Campaign</th><th>Rate</th><th>Host</th><th>Runs</th><th>p95 median</th><th>p95 range</th><th>p99 median</th><th>max |r| range</th><th>signed-mean shift</th></tr></thead>
<tbody>{group_rows or "<tr><td colspan='10'>No eligible characterization aggregate.</td></tr>"}</tbody></table>
</section>
{''.join(run_blocks)}
</main></body></html>
"""
    return html


def write_outputs(output_dir: Path, campaign: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    analyzed = campaign["analyzed"]
    run_rows = [_run_csv_row(item["summary"]) for item in analyzed]
    residual_rows = [obs for item in analyzed for obs in item.get("residuals") or []]
    occupancy_rows = [row for item in analyzed for row in _occupancy_rows(item)]
    group_rows = [_group_csv_row(group) for group in campaign["groups"]]
    paths = {key: str(output_dir / name) for key, name in OUTPUT_NAMES.items()}
    _write_csv(Path(paths["run_summary"]), _RUN_CSV_FIELDS, run_rows)
    _write_csv(Path(paths["group_summary"]), _GROUP_FIELDS, group_rows)
    _write_csv(Path(paths["residuals"]), _RESIDUAL_FIELDS, residual_rows)
    _write_csv(Path(paths["occupancy"]), _OCCUPANCY_FIELDS, occupancy_rows)
    Path(paths["analysis_json"]).write_text(
        json.dumps(_analysis_json(campaign, rows), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    html = render_html(campaign)
    Path(paths["report_html"]).write_text(html, encoding="utf-8")
    return paths


def contains_banned_copy(text: str) -> list[str]:
    found = []
    lower = text
    for phrase in _BANNED_COPY:
        if phrase.lower() in lower.lower():
            found.append(phrase)
    return found
