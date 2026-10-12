# MCSA V2 UX Workflow Contract

## Status

This document freezes the approved UX Pilot-inspired workflow direction for
Mouse Click Stability Analyzer (MCSA) V2 **before** Profile Lock / Arm Capture
is implemented.

- Baseline committed HEAD: `0ada531` (feat: wire host evidence snapshot into Qt fixture runs)
- Branch: `refactor/v2-phase2a-run-settings`
- The checkpoint candidate on top of that baseline contains:
  - Host Evidence REVIEW presentation (from the frozen run snapshot)
  - Workflow Shell foundation (navigation rail + Setup / Capture / Results / Preferences pages)
  - Raw Input UI-interaction exclusion for Fixture runs
  - Hidden Capture Test Area active-page guard
  - Fail-closed Test Area hit-test

No commit hash is recorded for the checkpoint here; it is assigned when the
reviewer commits.

This is a contract document. Sections describing *target* behaviour are not a
claim that the current runtime implements them. Section 2 and Section 10 make
the current-vs-target boundary explicit.

---

## 1. Design Source

The UX Pilot 5-screen export (`uxpilot-export-09-29-26.pdf`: Setup, Capture
Ready, Capture Running, Results, Preferences) is a **design reference** for
workflow structure, information hierarchy and layout.

It is **not** a capability specification. Values, badges, diagnostics and
fields shown in the mockups are sample content. Nothing becomes an MCSA
capability merely because it appears in the mockups. Section 7 lists the
mockup items that are explicitly quarantined.

---

## 2. Approved Workflow

### 2.1 Target workflow (to be implemented in Step 2)

```text
Setup Draft
  → Profile Validated
  → Profile Locked
  → Capture Ready / Disarmed
  → Armed                       (explicit "Arm Capture" action)
  → first accepted target-button Host Press = t0
  → Running
  → Completed
  → Results
```

Binding rules for the target workflow:

- The tester must explicitly lock the profile before Capture can become armable.
- Navigating to Capture MUST NOT start capture.
- Clicking the Test Area or a chart while Disarmed MUST NOT start capture.
- t0 is established only by the first accepted target-button Host Press
  **after** arming.
- These rules must be enforced in runtime logic, not only in UI wording.

### 2.2 Current runtime (transitional, at this checkpoint)

The current runtime does **not** implement Profile Validated, Profile Locked,
Capture Ready / Disarmed or Armed.

It still uses the transitional state:

- `listening` — waiting for a first click
- `running` — capture in progress
- `completed` — run stopped, REVIEW shown
- `self.locked` — settings snapshot taken at the first accepted Press
- `_arming_scheduled` — guards a single first-click session start

The first accepted target-button Press inside the visible Capture Test Area
starts the run and establishes t0. Step 2 will deliberately replace or contain
this start workflow.

### 2.3 Safety foundation already in place

Workflow Shell safety hardening at this checkpoint (implementation details,
not new product capabilities):

- Target-button clicks over interactive application controls (navigation
  rail, Capture action buttons, Theme / Language, visible Setup controls) are
  excluded from Fixture measurement. Page backgrounds are not excluded, so
  Fixture capture stays location-independent elsewhere.
- Hidden Capture Test Area geometry cannot count as a Test Area hit. The hit
  counts only when Capture is the current page and the Test Area is visible.
- Test Area hit-test exceptions fail closed (treated as outside the Test Area).

---

## 3. Page Ownership

### Setup

Configuration and validation. Future owner of Validate Profile / Lock Profile
& Continue and a read-only locked-profile preview.

### Capture

Arming and live operation: run state, elapsed time, click count, factual live
timing metrics, live charts, Stop (F5 / Esc). Report and export actions should
not dominate the Running view.

Transitional: REVIEW text (legacy review plus Host Evidence) and the report /
overlay buttons currently live on Capture until Step 5.

### Results

Target home for completed-run review:

- run / configuration summary
- Host Evidence
- completed-run charts
- Engineer Notes
- user-authored Conclusion
- Compare Overlay
- Generate / Export Report, Save Report As
- New Run, Edit Profile

Currently a placeholder page. Exact runtime and report ownership is designed in
Step 5.

### Preferences

Target home for Theme / Appearance and Language, plus future explicitly
approved application preferences.

Currently a placeholder page. Theme and Language stay in the global workspace
header until Step 6.

### Global

Quick Start / User Guide remains a navigation-footer action.

---

## 4. Current Supported Inputs

Only these inputs exist in MCSA today:

- Device
- Button
- Manual / Fixture
- Reference Rate (Hz)
- Schedule Association Window (± ms) — persisted as `fixture_timing_tolerance_ms`
- Auto Stop (ON / OFF)
- Auto Stop duration (s)
- Custom Limits:
  - Chatter (ms)
  - Double-click (ms)
  - Actuation short (ms)
  - Low hold (ms)
  - Interval CV (%)

UX Pilot Setup fields that are not in this list are not MCSA inputs (see
Section 7).

---

## 5. Measurement Boundary

MCSA measures **host-observed Windows Raw Input event timing** for the target
mouse button.

MCSA does **not** claim:

- USB packet timestamps
- HID report timestamps
- physical switch transition timestamps
- electrical waveform timestamps
- independent fixture stroke timestamps
- independent fixture stroke count
- microsecond hardware synchronisation

UI wording must not expand the measurement claim beyond host-observed event
timing.

---

## 6. Host Evidence Boundary

Host Evidence compares host-observed Presses with the configured Fixture
schedule. It is neutral, data-only, built once from the frozen run snapshot,
and not used by the verdict or reports.

Allowed factual language:

- Expected Slot
- In-window Host Press
- Host Count Delta
- Host Count Deficit vs Expected Slots
- Host Count Excess vs Expected Slots
- Unoccupied Expected Window
- Multi-observation Expected Window
- Matched Host Observation
- Unmatched Host Observation
- Ambiguous Host Observation
- Outside Capture Window
- Matched Timing Delta

Forbidden physical inference, unless independent physical ground truth or an
explicitly approved policy layer exists:

- Missing Click
- Double Click
- Extra Click
- switch bounce
- debounce failure
- hardware fault
- Host Evidence PASS / FAIL

### Schedule Association Window

The Schedule Association Window (排程關聯範圍) is an absolute ± ms half-width
around each expected schedule timestamp. It only decides whether a Host
observation can be associated with a schedule slot: one candidate is Matched,
none is Unmatched, two or more is Ambiguous, and observations at or after the
capture duration are Outside capture. It is not a DUT acceptance tolerance, a
PASS / FAIL threshold, or a chatter / double-click / duplicate / miss / delay
rule; those belong to future versioned Screening / Validation Profiles.

Setup shows derived, read-only context: Reference Interval (T = 1000 / Hz),
window relative to T (W / T × 100), and whether adjacent windows overlap
(2W ≥ T, inclusive, the matcher's own condition). Overlap is informational and
never blocks Profile Lock.

The window applies to timestamps, not intervals. Interval-domain charts
(Elapsed time vs Click interval, Click interval distribution, Click interval vs
Hold duration — in Capture, Results and report charts) show only the configured
reference interval and no association band.

Fixed ms, period-relative percentage, hybrid, or drift handling is not decided.
Future fixture / host timing characterization (actuation jitter, fixture clock
accuracy, Host timestamp and polling behavior, observed unmatched / ambiguous
rates) will determine the model. Until then the matcher keeps the absolute ± ms
rule.

### t0 anchor limitation

The schedule is anchored at the first accepted Host press (t0). Matched timing
(Host − schedule) therefore describes the relative schedule residual and drift
after t0. It does not measure absolute fixture-to-host latency or first
actuation latency.

---

## 7. UX Pilot Mockup-Only Items

| Mockup item | Current MCSA support | Decision |
|---|---|---|
| Stability Score (e.g. 98.2%) | No approved contract | Do not implement |
| Time Series Fourier (FFT) | No approved contract | Do not implement |
| Jitter RMS / "Within Specs" | No approved spec contract | Do not display |
| VALID / NEAR-THRES / NOMINAL / VARIANCE_DETECT status tags | No approved classification | Do not display |
| Signal Integrity column / score | Not measured | Do not display |
| Stability Window: OK | No approved contract | Do not display |
| Signal Strength | Not measured | Do not display |
| HID OK / Timing Sync OK | Not measured | Do not display |
| Latency 0.12 ms | Not measured | Do not display |
| Buffer Health | Not measured | Do not display |
| Clock Sync ±2 µs | Not measured | Do not display |
| Environment Nominal | Not measured | Do not display |
| Safety Interlock / Bypass | No interlock exists | Do not display |
| Profile validation HASH badge | No contract | Do not display |
| "HID Driver v3.2 loaded · 1 device found" | Not sourced | Do not display |
| Serial Number | Not a current input or source | Do not add |
| Connection Type (e.g. Bluetooth 5.0) | Not detected | Do not add |
| Auto-reconnect on drop | No behaviour | Do not add |
| Polling Rate (auto-detection) | Not measured by MCSA | Do not display |
| DPI Setting | Not a current input | Do not add |
| Sensor Type | Not sourced | Do not add |
| Surface Compensation | Not applicable | Do not add |
| Firmware version | Not sourced | Do not add |
| Number of Clicks (as a protocol input) | Not a current input (Auto Stop duration is) | Future decision |
| Deviation Threshold ±ms | Not an acceptance threshold; the Schedule Association Window is association-only | Do not add as a new field |
| Timing Units selector | No contract | Future decision |
| Auto-save Capture Runs | No contract | Future decision |
| Detailed Telemetry / Include HID driver events | No source or contract | Future decision |
| System Default theme | Only Light / Dark exist | Future decision |
| Continuous Mode | No contract | Future decision |
| Reset to Defaults / Discard Changes / Apply & Save | No Apply / Reset contract | Future decision |
| Pause Sequence | No pause semantics | Future decision |
| Live feed of recent events | No contract | Future decision |
| Save & Commit Run | No contract | Future decision |

---

## 8. Responsive UI Contract

Target window sizes:

- 1280×720
- 1280×840
- 1600×900
- 1920×1080

Target Windows display scaling: 100%, 125%, 150%.

Layout rule:

```text
wide              → multi-column
medium            → fewer columns
compact / high-DPI → stacked content + vertical scrolling
```

- Prefer scroll over squeeze.
- Never shrink controls until they overlap or become unreliable to click.
- Preserve comfortable logical control sizes. Do not hard-code one
  physical-pixel geometry.
- A sensible main-window minimum size may prevent catastrophic collapse but is
  not a substitute for scrolling. Current minimum: 1024×640.

---

## 9. Migration Steps

| Step | Scope | Model |
|---|---|---|
| Step 2 | Profile Lock + Capture Arm State Machine | GROK 4.6 HIGH |
| Step 3 | Setup Page UX | AUTO |
| Step 4 | Capture Ready / Running UX | AUTO |
| Step 5 | Results Ownership Migration | GROK 4.6 HIGH |
| Step 6 | Preferences Migration | AUTO |
| Step 7 | Responsive / DPI Hardening | AUTO |

---

## 10. Explicit Non-Goals of Current Checkpoint

The current checkpoint does **not** implement:

- profile validation state
- profile lock state
- capture ready / disarmed state
- armed state
- Results ownership migration (REVIEW, Host Evidence, report and overlay actions remain on Capture)
- Theme / Language migration to Preferences
- final responsive / DPI polish

Known visual debt (not checkpoint blockers while controls stay usable, nothing
overlaps and runtime semantics are correct):

- Setup content underuses wide-screen space.
- Capture action layout needs density polish.
- Results is a placeholder.
- Preferences is a placeholder.
- Final Windows DPI responsiveness is not complete.

These belong to Steps 3–7.
