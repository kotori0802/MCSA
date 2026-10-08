# Association Window Characterization (4E-B1)

Offline pipeline for measuring **Host-observed schedule timing residuals** against a nominal Fixture rate.

This document does not choose a Schedule Association Window. It does not define DUT PASS / FAIL. It does not prove a physical root cause.

Human-facing name: **Schedule Association Window**.
Persisted capture-time key: `fixture_timing_tolerance_ms`.
Primary 4E-B1 residual math **does not use** that key.

---

## Purpose

Determine empirical Host-observed nearest-slot timing behavior from **controlled physical Fixture** campaigns:

- How wide is the Host-observed wrapped residual?
- Does it change with Fixture rate, run, or Host?
- How close do observations get to adjacent-slot midpoints (`±T/2`)?
- Is there factual empty-slot / same-slot multiplicity structure?

Later 4E-B2 (real multi-run physical data) may use these outputs to discuss a window policy. **4E-B1 does not decide that policy.**

## Not purpose

- DUT PASS / FAIL / WARN
- Choosing a fixed-ms, percentage, hybrid, or other Association Window
- Changing the MCSA Setup default window
- Proving Fixture drift, Host drift, bounce, chatter, or missed clicks
- Using Stage 2D Configured Interval Range as a schedule model

Three domains stay separate:

1. Measurement (timestamps / intervals / hold)
2. Configured Interval Range (Stage 2D; ignored here)
3. Schedule Association (this pipeline)

---

## Inputs

Authoritative per-run machine input: the Stage 2C/2D package file `*_evidence.json` (`MCSA_EVIDENCE_V1`).

Do not use legacy `summary.json`, `detail.json`, or `analysis.txt` as normal inputs.

Evidence.json alone **cannot** prove a physical Fixture actuated the DUT. MCSA Fixture **software** mode only means the operator locked Fixture mode.

Eligibility therefore requires a separate **lab manifest** (CSV). See `docs/examples/characterization_manifest.example.csv`.

### Manifest fields

`run_id`, `package_path`, `campaign_id`, `purpose`, `actuation_source` (`physical_fixture` / `human` / `software` / `unknown`), `characterization_eligible` (`yes` / `no`), `exclusion_reason`, Fixture identity (`fixture_vendor`, `fixture_model`, `fixture_unit_id`, `fixture_firmware`), `control_dut_id`, `host_label`, optional `usb_port_label`, `expected_rate_hz`, `expected_duration_sec`, `repeat_index`, `auto_stop_on`, `notes`, optional vendor provenance (`vendor_timing_accuracy_ms`, `vendor_spec_reference`).

Serial numbers are not required. A local fixture-unit label is enough.

Vendor timing figures are **provenance only**. They must not set W, correct timestamps, or be called an end-to-end tolerance.

---

## Eligibility

A run enters the **eligible characterization aggregate** only when all of the following hold:

- manifest `characterization_eligible = yes`
- `actuation_source = physical_fixture`
- evidence `schema = MCSA_EVIDENCE_V1`
- `run_status = COMPLETE`
- `manual_mode = false`
- `fixture_reference_hz` finite and > 0
- `duration_sec` finite and > 0
- manifest `auto_stop_on = yes`, and evidence `settings.auto_stop_enabled = true`
- `focus_button` present
- expected rate / duration match evidence when supplied
- enough accepted focus-button timestamps exist for the metric (residual stats need a non-anchor in-window press)

`duration_sec` is a duration fact, not Auto Stop state. The analyzer never infers Auto Stop from `duration_sec`, run length, timestamps, or run status. `auto_stop_on_manifest` comes from the manifest only. `auto_stop_on_evidence` comes only from evidence `settings.auto_stop_enabled` (`true` / `false`; missing, `null`, or non-boolean → `null`).

Auto Stop checks for an eligible physical-fixture run:

| Manifest `auto_stop_on` | Evidence `settings.auto_stop_enabled` | Result |
|---|---|---|
| yes | `true` | Auto Stop requirement verified |
| yes | `false` | `ERROR auto_stop_mismatch` |
| yes | missing (older evidence) | `ERROR auto_stop_unverifiable` |
| no | any | `ERROR auto_stop_off` |
| blank | `true` | `ERROR auto_stop_unverifiable` (manifest must declare Auto Stop ON) |
| blank | `false` | `ERROR auto_stop_off` |
| blank | missing | `ERROR auto_stop_unverifiable` |

Newly generated evidence records `settings.auto_stop_enabled`. Evidence written before that field existed stays readable and is not rewritten, but its eligible physical-fixture runs remain `auto_stop_unverifiable`. Pipeline-only runs (for example human + `characterization_eligible = no`) stay pipeline-only whatever the evidence Auto Stop state. Mismatches and missing evidence state are INFO for them.

Real 4E-B2 characterization still requires `actuation_source = physical_fixture`, `characterization_eligible = yes`, manifest Auto Stop ON, and evidence Auto Stop ON. No 4E-B2 characterization has been performed yet.

Human, software, unknown, `eligible = no`, Manual, `NO_DATA`, and `INVALID` runs must not mix into that aggregate.

They may still be analyzed as **pipeline validation**. Those outputs must say **NOT CHARACTERIZATION EVIDENCE**.

Stage 2D comparison fields, if present, are ignored. Results are identical when those fields are absent.

---

## Canonical time base and residual math

- Use the first accepted focus-button Host press as t0.
- `source_t0_ms` = that press's `press_elapsed_ms`.
- `t_rel_ms = press_elapsed_ms - source_t0_ms` (first press → 0).
- Do not use `release_elapsed_ms` or wall-clock time.
- `T_ms = 1000 / F` from the frozen evidence Fixture Reference Rate. Do not derive T from observed cadence.

Nearest slot (W-independent):

    k = floor(t_rel_ms / T_ms + 1/2)
    residual_ms = t_rel_ms - k * T_ms

Range: `[-T/2, T/2)`. Exact `+T/2` maps to the **later** slot so residual = `-T/2`. Python `round()` is not used.

The anchor defines t0 and slot 0 but is **excluded** from residual statistics (residual 0 by construction). Occupancy counts may include the anchor; that is documented in the JSON contract.

Configured duration is a strict window: `0 <= t_rel_ms < duration_sec * 1000`. Observations at or after that bound are counted as **observation outside configured characterization window**, not as failures.

Boundary distance = `T/2 - |residual|`. Near 0 means near the adjacent-slot midpoint. It is not DUT quality.

### Occupancy language

- **empty slot**: nearest-slot count 0. Not a miss / missed click.
- **same-slot multiplicity**: count > 1. Not duplicate / bounce / chatter / defect.

### Capture-time W

`fixture_timing_tolerance_ms` is shown only as **Current-window context** (including an empirical `|residual| ≤ W` fraction). It does not filter residuals, eligibility, or nearest-slot assignment.

Different W values across a campaign do not invalidate W-independent residuals. They **do** prevent mixing Host Evidence matched-rate numbers without noting the configuration change.

---

## Summaries

Per-run first. Then group **run-level** metrics (median/range of run p95/p99/max `|residual|`, run-to-run signed residual shift) by campaign, rate, Host, fixture unit, and control DUT.

Do not pool clicks as IID replicates. Do not bootstrap events. Within-run spread is descriptive. Repeat-to-repeat variation is the primary robustness evidence.

Wrapped residual vs elapsed is exported. Early/middle/late window-span summaries are diagnostic. Global unwrapping is not performed.

---

## Outputs

Written **outside** the normal four-file field-test package (`evidence.json`, `events.csv`, `report.html`, `report.xlsx`).

    characterization_out/<campaign_id>/
        characterization_run_summary.csv
        characterization_group_summary.csv
        characterization_residuals.csv
        characterization_slot_occupancy.csv
        characterization_analysis.json
        characterization_report.html

Do not commit generated outputs. Do not copy them into `reports/mcsa_<run_id>/`.

The HTML report is an engineering notebook, not a DUT report.

---

## CLI

    python -m mouse_click_stability_analyzer.characterization --mode validate --manifest <manifest.csv>
    python -m mouse_click_stability_analyzer.characterization --mode analyze --manifest <manifest.csv> --output characterization_out/<campaign>

No administrator rights. No network access.

Issue levels:

- `ERROR` — cannot analyze reliably
- `EXCLUDED` — intentionally not characterization evidence
- `INFO` — factual note

These are not DUT WARN / FAIL.

---

## Proposed controlled campaign (configurable)

This matrix is a **lab plan**, not analyzer constants. Rates come from the physical Fixture and the manifest.

If the Fixture supports them, a starting core campaign is:

| Rate | 30 s × 3 | 120 s × 3 | 600 s × 2 |
|---|---|---|---|
| 5 Hz | 3 | 3 | 2 |
| 10 Hz | 3 | 3 | 2 |
| 20 Hz | 3 | 3 | 2 |
| 40 Hz | 3 | 3 | 2 |

Total: 32 core runs across four rates.

Use Auto Stop ON and whole-second durations. Keep the same controlled Fixture + DUT configuration inside a campaign unless the manifest records a change.

---

## Lab procedure

1. Physical Fixture, controlled DUT, known Host and USB port/configuration.
2. Setup: Fixture mode, intended Reference Rate, Auto Stop ON, whole-second duration. Leave Association Window at the current product default unless the campaign is explicitly studying W-dependent Host Evidence (primary residuals still ignore W).
3. Lock, capture, Generate Report (standard four-file package).
4. Register the package in the lab manifest (`actuation_source`, eligibility, rate, duration, Host, fixture unit, repeat index).
5. Run `--mode validate`, then `--mode analyze`.
6. Confirm source report files were not modified.

### Data-quality checks

- Expected rate / duration match evidence.
- Auto Stop duration > 0 (duration only; it does not verify Auto Stop state).
- Evidence `settings.auto_stop_enabled = true` (generated by a build that records it).
- Accepted focus-button presses exist.
- Manifest actuation source is honest. A hand-clicked Fixture-mode run is `human` and `characterization_eligible = no`.

### Exclusion

Record `exclusion_reason`. Excluded runs may still be processed as pipeline validation. They must not enter the eligible aggregate.

### Interpretation

Host residual cannot identify the causal subsystem (Fixture, DUT, Host, USB, software). Empty nominal slots are not automatically misses. Same-slot multiplicity is not automatically bounce.

### Repeat strategy

Compare runs, not thousands of clicks inside one run. Cross-Host and cross-rate questions need enough repeats at each cell of the matrix.

---

## Polling / quantization (optional context)

If a known polling interval P exists in lab notes, `P / sqrt(12)` is an idealized theoretical quantization scale only. Do not infer P. Do not treat it as observed uncertainty. Do not subtract it from residuals. Do not use it to choose W.

---

## What 4E-B1 does not do

- Decide or recommend W
- Change Setup defaults or add rate/Host profiles
- Auto-calibrate or re-anchor for drift
- Treat unmatched Host Evidence as a DUT defect
- Start 4E-B2
