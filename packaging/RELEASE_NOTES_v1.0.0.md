# MCSA v1.0.0

Mouse Click Stability Analyzer v1.0.0 is a Windows 10/11 64-bit engineering
tool for host-observed mouse click timing. It is **measurement only**: it does
not issue a PASS/FAIL verdict, a DUT score, or a recommended association window.

Extract `MCSA-1.0.0-win64.zip` to a writable folder and run `MCSA.exe`. No
Python install and no administrator rights are required. Reports are written
next to the executable under `reports\`.

## Included

- Click interval and hold duration measurement
- Fixture and Manual workflows
- Optional Configured Interval Range (inclusive Below / Within / Above counts;
  not a PASS/FAIL criterion)
- Explicit Auto Stop ON/OFF recorded in evidence
- Windows Raw Input capture (user-space; no driver, no admin)
- Results charts and navigation, plus Compare Overlay from a previous run
- Four-artifact report package: evidence JSON, events CSV, HTML, XLSX
- Host Information (manufacturer, model, OS, CPU, BIOS, USB controllers, runtime)

## Known limitations

- No formal DUT validation / screening profile is applied.
- Schedule Association is optional / historical. No recommended Association
  Window (W) is published. Real 4E-B2 characterization has not started.
- The Windows EXE is unsigned. Windows SmartScreen may show a reputation prompt.
- No custom application icon is bundled.
- Third-party license texts for Python, openpyxl, et-xmlfile, the PyInstaller
  bootloader, and PySide6 / Qt 6.11.0 (LGPL-3.0, GPL-3.0, GPL-2.0, taken from
  the official Qt for Python v6.11.0 source tag) are included under
  `licenses\`. See `THIRD_PARTY_NOTICES.txt`.
