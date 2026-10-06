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
| `terminology.json` | Reserved for Stage 2 shared engineering terms. Do not add active keys yet. |

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
- Do not rename JSON keys.
- Do not add, remove, or rename `{placeholders}`.
- Use a single `&` in button text (`Edit Setup & New Run`). Do not type `&&`.
- Qt entries need both `en` and `zh-TW`.
- Report entries need `en` only. Reports stay English for now.
- Run `check_strings.bat` after every edit.

## Entry shape

```json
"nav_setup": {
  "en": "Setup",
  "zh-TW": "設定"
}
```

Template (do not change the placeholder names):

```json
"matched_observations_used_value": {
  "en": "{matched} of {total} in capture",
  "zh-TW": "{matched} / {total}（擷取內）",
  "placeholders": ["matched", "total"]
}
```

Optional engineer note:

```json
"legend_configured_reference": {
  "en": "Configured reference",
  "zh-TW": "設定參考值",
  "note": "Configured reference only. Not a PASS/FAIL threshold."
}
```

UTF-8 is required. A UTF-8 BOM from Windows editors is accepted.
