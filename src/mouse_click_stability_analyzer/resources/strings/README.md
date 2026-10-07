# Copy resources

Edit user-facing wording here. Do not edit Python for ordinary Setup, Capture, Results, Preferences, or report label changes.

## Where to edit

| File | What it owns |
|---|---|
| `common.json` | Shell, navigation, shared actions, dialogs |
| `setup.json` | Setup page |
| `capture.json` | Capture page |
| `results.json` | Results page |
| `preferences.json` | Preferences page |
| `report.json` | HTML/XLSX report labels (English only) |
| `terminology.json` | Shared engineering terms used on more than one surface |

If changing a page-specific instruction, edit the page JSON.

If changing a shared engineering term, edit `terminology.json`.

Before editing a term, read its `note` and `help`. Do not redefine that term’s exact wording in a page file.

## Shared concepts

| Concept | What it is | What it is not |
|---|---|---|
| Schedule Association Window | ± window used to associate a Host observation with a schedule slot | DUT acceptance tolerance, PASS/FAIL threshold |
| Reference Rate | Configured nominal rate | Fixture Frequency / Fixture Hz wording, a measured cadence |
| Reference Interval | 1000 / Reference Rate (Setup / report test info) | Observed Interval, matched timing error |
| Configured reference | Chart comparison marker | Product acceptance target |
| Host observation | Accepted Host-recorded press | PASS, a “good click” |
| Measurement only | No Screening or Validation Profile applied | A run result state |
| Association statuses | Matcher evidence (matched / not matched / ambiguous / outside capture) | DUT PASS/FAIL |
| Run statuses | Display labels for COMPLETE / NO_DATA / INVALID | Localized stored tokens, validation PASS |

Page files reference a term with `{@term.key}`:

    "en": "{@term.schedule_association_window} (± ms)"

English page strings resolve the English term; `zh-TW` page strings resolve the `zh-TW` term. Term expansion happens before `{placeholder}` formatting. Terms must not reference other terms.

## How to validate

From the project folder:

    check_strings.bat

Or:

    python -m mouse_click_stability_analyzer.strings check

Fix every error before launching the app.

## How to launch after editing

    run.bat

## Rules

- Ordinary copy edits do not require Python changes.
- Do not rename JSON keys unless a Stage 2 alias exists for the old name.
- Do not add, remove, or rename `{placeholders}`.
- Use a single `&` in button text (`Edit Setup & New Run`). Do not type `&&`.
- Qt entries need both `en` and `zh-TW`.
- Report entries need `en` only. Reports stay English for now.
- Canonical `term.*` keys live only in `terminology.json`.
- Run `check_strings.bat` after every edit.

Temporary key aliases (mapping only, no copy) live in Python `KEY_ALIASES`. Current alias: `tolerance` → `assoc_window`.

## Entry shape

```json
"nav_setup": {
  "en": "Setup",
  "zh-TW": "設定"
}
```

Term reference (do not change the placeholder names):

```json
"fixture_timing_tolerance_ms": {
  "en": "{@term.schedule_association_window} (± ms)",
  "zh-TW": "{@term.schedule_association_window} (± ms)"
}
```

UTF-8 is required. A UTF-8 BOM from Windows editors is accepted.
