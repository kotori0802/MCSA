# MCSA v1.0.0 (draft)

Mouse Click Stability Analyzer is a Windows engineering tool for capturing and
reporting host-observed mouse click timing. It is **measurement only**: it does
not issue a PASS/FAIL verdict, a DUT score, or a recommended association window.

## Included

- Click interval and hold duration measurement
- Fixture and Manual workflows
- Optional Configured Interval Range (inclusive Below / Within / Above counts;
  not a PASS/FAIL criterion)
- Explicit Auto Stop ON/OFF recorded in evidence
- Windows Raw Input capture (user-space; no driver, no admin)
- Four-artifact report package: evidence JSON, events CSV, HTML, XLSX
- Host Information (manufacturer, model, OS, CPU, BIOS, USB controllers, runtime)
- Compare / Overlay from a previous `mcsa_<run_id>_evidence.json`
- Stage 2E chart names and Fit All Data navigation:
  Elapsed time vs Click interval, Click interval distribution,
  Elapsed time vs Hold duration, Click interval vs Hold duration

## Known limitations

- Schedule Association is optional / historical. No recommended Association
  Window (W) is published. Real 4E-B2 characterization has not started.
- No formal DUT validation / screening profile is applied.
- The Windows EXE is unsigned. Windows SmartScreen may show a reputation prompt.
- No custom application icon is bundled.

## Runtime

- Windows 10 / 11 64-bit portable folder: extract and run `MCSA.exe`
- No Python install and no administrator rights required
- Reports are written next to `MCSA.exe` under `reports\`
