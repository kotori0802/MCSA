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
| `settings.duration_sec` | `_evidence.json` `settings` | Configured duration in seconds. A duration/configuration fact only; **not** Auto Stop provenance (see below) |
| `settings.fixture_reference_hz` | `_evidence.json` `settings` | Configured Reference Rate. Defines the **nominal configured schedule** for characterization |
| `settings.fixture_timing_tolerance_ms` | `_evidence.json` `settings` | Operational Schedule Association Window for that run (numeric ms) |

Configured Interval Range fields are not characterization inputs. See section 8.

#### Auto Stop provenance

- `duration_sec` may reflect current producer behavior (for example, the current Qt capture path writes `0` when Auto Stop is off). That is an implementation detail, not authoritative Auto Stop provenance.
- Current `MCSA_EVIDENCE_V1` has **no explicit Auto Stop enabled/disabled state**.
- Characterization must not infer `auto_stop_on = true` or `auto_stop_on = false` from `duration_sec`, run length, timestamps, or run status.
- Characterization therefore records `auto_stop_on_evidence = null` unless a future evidence contract records Auto Stop explicitly. `auto_stop_on_manifest` comes from the lab manifest only.
- **4E-B2 blocker:** real eligible physical-fixture runs are currently blocked (`ERROR auto_stop_unverifiable`) because Auto Stop ON cannot be independently verified from `MCSA_EVIDENCE_V1`.
- A future evidence-format change must record Auto Stop state explicitly before eligible physical-fixture runs can enter the characterization aggregate.

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

Physical actuation source is **external lab metadata**. Do not fabricate `actuation_source` in `evidence.json`.

4E-B1 records actuation in a separate lab manifest CSV (`docs/ASSOCIATION_WINDOW_CHARACTERIZATION.md`):

    actuation_source = physical_fixture | human | software | unknown

Eligible characterization aggregate requires `physical_fixture` **and** `characterization_eligible = yes` plus factual evidence checks. Fixture software mode alone is never enough.

Pilot / pipeline runs:

    purpose = artifact pipeline pilot
    actuation_source = human   (or software)
    characterization_eligible = no

Those packages may exercise discovery, parsing, math, and output generation. They must be labelled **NOT CHARACTERIZATION EVIDENCE** and must not enter the eligible aggregate. Their timing distribution must not be used to choose fixed-ms / percentage / hybrid.

Characterization outputs are written to a separate directory (`characterization_out/<campaign>/`), never into the normal four-file field-test package.

---

## 6. Schema version

Stage 2C/2D standard machine-readable contract:

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

## 8. Configured Interval Range (Stage 2D)

Independent of Schedule Association Window. Persisted settings keys:

- `interval_comparison_enabled`
- `interval_comparison_basis` (`percent` | `milliseconds`)
- `interval_comparison_value` (one authoritative number)

Frozen evidence (when enabled) also stores derived `tolerance_pct`, `tolerance_ms`, `lower_bound_ms`, `upper_bound_ms`, and factual counts. This is observation-versus-range evidence only. It is not a DUT verdict and does not change `run_status`.

`events.csv` does not store range position. Reconstruct it from `press_interval_ms` plus the frozen comparison contract.

Do not infer interval comparison from `fixture_timing_tolerance_ms`. Do not use `fixture_timing_tolerance_ms` as the comparison range.

Characterization does not depend on these fields. Eligibility, inputs, and math are identical whether comparison was enabled, disabled, or absent (pre-Stage 2D artifacts). Readers may ignore every `interval_comparison*` key. They are not characterization inputs, filters, or weights.

Primary 4E-B1 residual analysis is also independent of `fixture_timing_tolerance_ms`. That value is capture-time Association Window **context** only. Changing it must not change W-independent nearest-slot residuals. The analyzer reconstructs the nominal schedule from `press_elapsed_ms`, `fixture_reference_hz`, and `duration_sec` using the documented half-open nearest-slot rule. It does not inherit Host Evidence matched/unmatched arithmetic.
