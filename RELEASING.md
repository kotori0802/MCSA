# Releasing v1.0.0

## 0. Clean local artifacts (safe script)

From the project folder:

```bat
clean_local.bat
```

Type `YES` when prompted. This removes **only**:

- `reports\mcsa_*` (your test runs; keeps `reports\.gitkeep`)
- `.venv\` / `venv\` (project root)
- `__pycache__\` (under this project)
- `src\*.egg-info\`, `build\`, `dist\`

It does **not** delete source code, `install.bat`, `docs\`, etc.

## 1. README screenshot

```bat
save_readme_screenshot.bat
```

1. Open MCSA → Theme **Dark** → LISTEN screen  
2. `Win+Shift+S` capture → image on clipboard  
3. Run script above → saves `docs\images\mcsa-ui-dark-listen.png`

## 2. Verify build

```bat
install.bat
run.bat
run.bat --mode self-test
```

---

## Path A — Git installed (recommended)

Install Git for Windows (once):

```bat
winget install Git.Git
```

Close and reopen Command Prompt, then:

```bat
cd C:\mouse_click_stability_analyzer
git init
git add .
git status
git commit -m "Release v1.0.0 - Mouse Click Stability Analyzer"
```

Create an empty repo on GitHub (no README), then:

```bat
git branch -M main
git remote add origin https://github.com/kotori0802/mouse-click-stability-analyzer.git
git push -u origin main
git tag v1.0.0
git push origin v1.0.0
```

On GitHub: **Releases → Draft new release → tag v1.0.0**.

---

## Path B — No Git on this PC

```bat
clean_local.bat
pack_for_upload.bat
```

1. Add screenshot to `_dist_upload\docs\images\mcsa-ui-dark-listen.png`  
2. Zip the `_dist_upload` folder  
3. GitHub → **New repository** → **Upload files** → drag zip contents  

Or install Git later and switch to Path A.

---

## Release candidate evidence

RC acceptance requires a **live hardware run** (real mouse, Fixture or Manual) on the
build being released, followed by Generate Report and a check of all four artifacts
(`_evidence.json`, `_events.csv`, `_report.html`, `_report.xlsx`) and opening the XLSX
in Microsoft Excel.

A scripted run (simulated clicks driven through the Qt window) is acceptable only for
artifact-generation, report-contract and chart title/axis regression checks. It is
**not** hardware or live acceptance evidence. Scripted runs that place click
timestamps in the future and force Auto Stop record `elapsed_s = null`; this is a
property of the script, not of the live producer path, which records the real
elapsed time.

## Before upload — manual check

```bat
dir reports
```

You should see only `.gitkeep` (no `mcsa_*.json` you care about in the upload folder).

- [ ] No real device names you do not want public in committed files  
- [ ] `SECURITY.md` / `PRIVACY.md` present  
- [ ] `docs/images/mcsa-workflow.svg` present  

## Do not upload

| Path | Reason |
|------|--------|
| `reports/mcsa_*` | Local test sessions |
| `.venv/` / `venv/` | Python environment |
| `src/**/*.egg-info/` | pip install artifact |
| `__pycache__/` | Bytecode |
