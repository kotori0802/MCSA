# Characterization Artifact Contract

Machine-readable provenance for later **offline timing characterization**.
This document is not a DUT acceptance criterion and does not define PASS / WARN / FAIL.

Human-facing name: **Schedule Association Window**.
Persisted key: `fixture_timing_tolerance_ms` (numeric milliseconds).

---

## 1. Authoritative inputs (whitelist)

Future characterization analysis may use only these fields from MCSA report artifacts.

### Run identity / context

| Field | Artifact | Meaning |
|---|---|---|
| `run_id` | `_evidence.json` (Stage 2C+). Historical: `_summary.json`, `_detail.json` | Run identity |
| `run_status` | same | Authoritative capture/data status: `COMPLETE`, `NO_DATA`, or `INVALID` |
| `tool_version` | same | Tool version that wrote the artifacts |

### Configuration

| Field | Artifact | Meaning |
|---|---|---|
| `settings.manual_mode` | `_evidence.json` `settings` | Software mode. `false` is Fixture **software** mode, not proof of physical Fixture actuation |
| `settings.focus_button` | `_evidence.json` `settings` | Target button |
| `settings.duration_sec` | `_evidence.json` `settings` | Configured Auto Stop duration in seconds (`0` / absent means Auto Stop off) |
| `settings.fixture_reference_hz` | `_evidence.json` `settings` | Configured Reference Rate. Defines the **nominal configured schedule** for characterization |
| `settings.fixture_timing_tolerance_ms` | `_evidence.json` `settings` | Operational Schedule Association Window for that run (numeric ms) |

### Primary observation timeline

| Field | Artifact | Meaning |
|---|---|---|
| `events[].accepted` | `_evidence.json` | Whether the event is an accepted Host press |
| `events[].button` | `_evidence.json` | Button for that event |
| `events[].press_elapsed_ms` | `_evidence.json` | Primary Host-observed timeline, relative to the first accepted Host press (t0) |

### Optional factual context (if present)

| Field | Artifact | Meaning |
|---|---|---|
| `events[].hold_ms` | `_evidence.json` | This click's release minus this click's press |
| `host_test_environment` | `_evidence.json` | Host/platform/capture backend recorded at write time |
| `events[].capture_source` | `_evidence.json` | Capture backend label when persisted |
| `events[].device_source` | `_evidence.json` | Raw Input device path when persisted |

`release_elapsed_ms` is **not** relative to t0. It is relative to the first accepted **release**. Do not treat it as a schedule-relative time.

---

## 2. Schedule Association Window persistence

Upstream origin: the locked Setup value `fixture_timing_tolerance_ms`, frozen into the completed-run model as `run.timing_tolerance_ms` (with the locked settings snapshot in `run.settings`).

One numeric source of truth per report bundle: when one completed report bundle is written, the **frozen completed-run model** is the canonical source for every artifact:

    locked Setup
      -> completed model (frozen): run.timing_tolerance_ms
           -> _evidence.json settings.fixture_timing_tolerance_ms
           -> HTML
           -> XLSX

The report writer does not read the window from the caller's `settings` argument, and no renderer re-reads mutable live Setup state. When no completed model is supplied, the writer builds one from the given settings first and then follows the same path. There is no separate report-only window calculation.

| Frozen model state | JSON value |
|---|---|
| Fixture, configured | number (including `0.0`) |
| Manual (key present, run value null) | JSON `null` |
| Key absent from the frozen `run.settings` (old input) | **key absent** |

Human-facing report text may round for display (`±20.00 ms`, `±20.000 ms`). JSON stores the original numeric value and must not be reconstructed from that formatted text.

---

## 3. Backward compatibility

Old JSON files do not contain `fixture_timing_tolerance_ms`.

| Condition | Rule |
|---|---|
| Field present as a number | Use that number |
| Field present as JSON `null` | Manual / not applicable. This is **not** 0 ms |
| Field missing | Schedule Association Window provenance is **incomplete** |

Do **not** silently substitute:

- `0`
- a preset
- `chatter_threshold_ms`
- `duplicate_click_threshold_ms`
- `fixture_match_tolerance_ms`
- report display defaults

Recovering the value from paired HTML/XLSX text, if ever done, must be labelled:

    recovered from formatted report text

not native JSON provenance. This repository does not implement report-text recovery.

---

## 4. Non-authoritative / forbidden characterization inputs

These exist in **legacy** `*_summary.json` / `*_detail.json` files only. Stage 2C standard Generate Report does **not** emit them. They are **not** measurement truth for characterization.

### Run / metric / score blocks

- `metrics.pass`
- `metrics.result` (mirrors `run_status` in current JSON; still not a DUT verdict)
- `dut_score`, `setup_score`, `stability_score`
- `cadence_mode`
- `missed_estimated`, `miss_or_slow_count`
- `chatter_count`, `duplicate_click_risk_count`
- `issue_tags`
- `legacy_heuristic_assessment` (including its `result`, which may be WARN / FAIL)

`legacy_heuristic_assessment.authoritative` is `false`. Do not promote it.

Authoritative run outcome remains `run_status` only: `COMPLETE` / `NO_DATA` / `INVALID`.
PASS / WARN / FAIL are not authoritative run outcomes.

### Event annotation fields

Do not treat these as the characterization schedule model:

- `click_class`
- `analysis_status`
- event `result`
- `expected_time_ms` (index-based `(n−1)×interval`, not matcher slots)
- `expected_click_index`
- `drift_ms`
- `interval_error_ms`
- `interval_error_pct`

The analyzer must reconstruct its nominal schedule from:

    press_elapsed_ms
    fixture_reference_hz
    duration_sec

plus explicitly chosen analysis rules. It must not inherit old heuristic/classification semantics merely because those fields exist in legacy JSON.

---

## 5. Software mode is not physical actuation source

`settings.manual_mode = false` (Fixture software mode) does **not** prove that a physical Fixture actuated the DUT.

A human-hand run can still lock Fixture mode. Do not infer:

    actuation_source = fixture

from Fixture software mode alone.

Physical actuation source is **external lab metadata** until a later design adds a persisted field. Do not fabricate `actuation_source` in artifacts.

Future characterization datasets must record, outside the artifact for now:

    actuation_source = fixture | human | other | unknown

Pilot run `20261005_172910` (lab metadata, not a DUT verdict):

    purpose = artifact pipeline pilot
    actuation_source = human
    characterization_eligible = no

That run used Fixture software mode with hand actuation. It is valid only as an artifact/data-pipeline pilot. Its timing distribution must not be used to choose fixed-ms / percentage / hybrid.

---

## 6. Schema version

Stage 2C standard machine-readable contract:

- evidence: `MCSA_EVIDENCE_V1` (`schema` / `schema_version`)

Historical files may still use:

- summary: `MCSA_REPORT_V1`
- detail: `1`

Overlay loaders accept `_evidence.json` and fall back to historical `_detail.json`.

## 7. Report package layout (Stage 2C closeout)

Generate Report writes one per-run package under the configured reports root:

```text
reports/
  mcsa_<run_id>/
    mcsa_<run_id>_events.csv
    mcsa_<run_id>_evidence.json
    mcsa_<run_id>_report.html
    mcsa_<run_id>_report.xlsx
```

- All four files are required. A missing file (including XLSX) means generation failed.
- `artifacts` and `report_artifacts_verified` inside the evidence JSON hold package-relative file names only (`evidence_json`, `events_csv`, `report_html`, `report_xlsx`). No absolute machine path is stored.
- `report_generated_at` is the report-writer wall-clock time. It is not a run completion time; no frozen completion timestamp exists. Run duration is `elapsed_s`.
- Historical flat files directly under `reports/` (`mcsa_<id>_evidence.json`, `_detail.json`, `_summary.json`) are not migrated and remain readable. Discovery prefers the nested package evidence, then flat evidence, then flat detail; one entry per run id. Siblings are resolved relative to the discovered file's folder.
