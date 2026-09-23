# Mouse Click Stability Analyzer

> **An independent QA prototype for capturing, measuring, visualizing, and reporting mouse click behavior.**

Author: **Leo Cheng, PMP** · License: [MIT](LICENSE)

## Screenshots

**Dark theme — LISTEN (ready to test)**

![MCSA dark UI — listen phase](docs/images/mcsa-ui-dark-listen.png)

**30-second workflow**

![MCSA workflow](./docs/images/mcsa-workflow.png)

| Step | Action |
|------|--------|
| 1 | `install.bat` → `run.bat` |
| 2 | Choose **Manual** or **Fixture**, button, rules |
| 3 | Click in **Test Area** — first click starts recording |
| 4 | **F5 / Esc** to stop (avoids contaminating data) |
| 5 | **Finish & Generate Report** → HTML/JSON/CSV locally |

## Why I Built This

Intermittent mouse click issues are difficult to explain with words or video alone. This project converts raw mouse events into measurable engineering evidence: press/release timing, hold duration, click intervals, cadence alignment, chatter/bounce indicators, and missed/excess events.

The analyzer **separates potential DUT behavior from setup/fixture instability** to reduce false conclusions — a real double-click risk is not the same as a shaky fixture or wrong Hz setting.

## What It Measures

- Press / release pairing and hold time
- Press interval and fixture cadence alignment
- Chatter, bounce, and true extra-click classification
- Missed / excess click counts vs expected cadence
- DUT integrity score vs SETUP alignment score
- Timing error (bias, σ, P99 |error|) for fixture profiles

## Requirements

- **Windows 10/11** (Phase 1 — Raw Input capture)
- Python **3.10+**
- Optional: `openpyxl` for Excel reports (`pip install openpyxl`)

## Quick Start

```bat
cd C:\mouse_click_stability_analyzer
install.bat
run.bat
```

`install.bat` installs the package plus **PySide6** (modern GUI). `run.bat` prefers the Qt shell when available; fall back with:

```bat
run.bat --ui tk
```

Or manually:

```bat
cd C:\mouse_click_stability_analyzer
python -m pip install -e ".[gui]"
python -m mouse_click_stability_analyzer
python -m mouse_click_stability_analyzer --ui tk
```

**Important:** run `install.bat` (or `pip install -e .`) **inside the project folder**, not from `C:\Windows\System32`. `run.bat` picks the first Python that can import the package (`py -3`, then `python`, then `py`). `install.bat` installs for both `python` and `py -3` when available.

Before publishing: run `clean_local.bat` to remove local test reports and build cache (see [RELEASING.md](RELEASING.md)).

If the window flashes and closes, run `run_diagnose.bat` to see the error, or:

```bat
python -B -m mouse_click_stability_analyzer
```

Or headless self-test (synthetic data, no GUI):

```bat
python -m mouse_click_stability_analyzer --mode self-test
```

Reports are written to `reports/` **after you complete a local run**. This repository does not ship real device sessions.

## Typical Workflow

1. Launch (`run.bat`) — app opens in **LISTEN**
2. Set Manual/Fixture, button, rules (left rail)
3. Move cursor to **Test Area**, click target button to **start**
4. Stop with **F5** or **Esc** (not the Stop button, to keep data clean)
5. Review live charts + verdict → **New Run** or **Finish & Generate Report**
6. Optional: **Compare Overlay** with a previous `*_detail.json`

Reports land in `reports/` on your machine only (never committed — see [RELEASING.md](RELEASING.md)).

## Reading a Report — Demo Mouse A (fictional)

This example uses a **fictional device** for teaching only. Your real reports appear only after a local test.

| Field | Demo Mouse A example |
|-------|----------------------|
| DUT label | Demo Mouse A |
| Profile | Fixture 10 Hz Strict |
| Expected / Actual | 600 / 598 clicks |
| Result | WARN |
| Issue tags | `MISS_CLICK_WARN` (2 missed) |
| DUT score | 96 |
| SETUP score | 100 |

**How to interpret:**

- **Low DUT + low extra count** → possible missed clicks or switch behavior
- **`FIXTURE_HZ_MISMATCH`** → count gap is likely wrong Hz setting, not 149 extras
- **High SETUP suspicion** → check fixture travel, probe point, or vibration first

Open the HTML report: green = on-cadence cloud, red = extra/chatter, orange = rebound, black X = slow/miss.

## Project Structure

```text
src/mouse_click_stability_analyzer/
  app.py          # Tk GUI + reporting (legacy / fallback)
  qt_shell/       # PySide6 portfolio shell (default when installed)
  core.py         # Metrics engine (importable)
  cadence.py      # Classification & DUT/SETUP scoring
  schema.py       # MCSA_REPORT_V1 schema
  cli.py          # mcsa command
  adapters/       # Windows Raw Input capture
```

## Roadmap

- [x] Phase 1A–1B: Public repo, MCSA schema, standalone GUI + self-test
- [x] Phase UI: PySide6 shell (Listen → first click → charts → review/report)
- [x] Phase UI+: Chart axes/legends, compare overlay, rules preset, dark theme, EFIGS+CJK UI
- [ ] Phase 1C: Device scan & bind (mouse HID enumeration)
- [ ] Phase 1D: Report localization beyond EN/ZH
- [ ] Phase 2: macOS capture adapter, packaging, CI


## Library API (preview)

```python
from mouse_click_stability_analyzer import build_payload, compute_metrics, make_synthetic_events

events = make_synthetic_events(count=100, interval_ms=100.0, hold_ms=12.0)
payload = build_payload("Demo Mouse A", "", {"fixture_hz": 10}, events, run_id="demo")
metrics = payload["metrics"]
```

## Privacy

See **[PRIVACY.md](PRIVACY.md)** for what data MCSA stores locally and what it does **not** collect.

See **[SECURITY.md](SECURITY.md)** for vulnerability reporting and the local-only security model.

- Operator name is **optional** (not auto-filled from Windows username)
- Do not commit `reports/` — real VID/PID sessions stay local
- Compare overlay JSON is capped at **32 MiB / 150,000 events**
- GitHub repo ships **no real test sessions** (`reports/*` is gitignored; only `reports/.gitkeep` is tracked)

## Acknowledgements

Built as a personal portfolio project. Development methodology used AI-assisted iteration; the analysis logic is deterministic event processing, not ML inference.
