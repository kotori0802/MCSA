# Releasing v1.0.0

This document has three parts. Only **Part 1** produces the v1.0.0 release.

| Part | Purpose | Produces the v1.0.0 release? |
|------|---------|------------------------------|
| [1. Windows EXE release — canonical](#part-1--windows-exe-release--canonical) | Build, verify, and publish `MCSA-1.0.0-win64.zip` | **Yes** — the only v1.0.0 release procedure |
| [2. Source / Git workflow](#part-2--source--git-workflow) | Keep the source repository clean and pushed | No — source hygiene only |
| [3. Optional legacy / manual upload](#part-3--optional-legacy--manual-upload-no-git) | Upload source without Git | No — source upload only |

The `v1.0.0` tag and the GitHub Release are created **only** at the end of Part 1,
after every Part 1 gate passes. Parts 2 and 3 never tag or publish a release.

---

## Part 1 — Windows EXE release — canonical

This is the supported end-user distribution. It does not require a system Python
install, administrator rights, or an installer.

### 1.1 Build environment

- Windows 10/11 64-bit
- Python **3.12 64-bit** only (`py -3.12`)
- `requirements-build.txt` pins `PySide6==6.11.0`, `openpyxl==3.1.5`, `PyInstaller==6.13.0`
- Dedicated venv: `.venv-build` (do not reuse the developer `.venv` if you want a clean build)
- MCSA installed **editable from this repository** (`pip install -e .`)

```bat
py -3.12 -m venv .venv-build
.venv-build\Scripts\python -m pip install -U pip
.venv-build\Scripts\python -m pip install -r requirements-build.txt
.venv-build\Scripts\python -m pip install -e .
build_exe.bat
```

`build_exe.bat` runs `packaging\check_build_env.py` before PyInstaller and stops
without building if any of these differ:

- Python 3.12 64-bit
- PyInstaller 6.13.0, PySide6 6.11.0, openpyxl 3.1.5
- `mouse-click-stability-analyzer` 1.0.0, imported from this repository's `src\`

It never installs or upgrades packages itself; on failure it prints the
provisioning commands above.

A rebuild deletes `dist\MCSA-1.0.0-win64\`, including its `reports\` folder.
`build_exe.bat` therefore also stops, without deleting anything, when
`dist\MCSA-1.0.0-win64\reports\` contains any `mcsa_*` report package. Back up or
move those reports out of `dist\` first.

Expected output:

    dist\MCSA-1.0.0-win64\MCSA.exe

That folder is a one-directory PyInstaller bundle (`console=False`, UPX off,
`asInvoker`). Reports are written to `dist\MCSA-1.0.0-win64\reports\`.
The legacy Tk UI is not bundled; `MCSA.exe --ui tk` shows a controlled message.

Create a ZIP candidate only after packaged smoke tests pass:

```bat
packaging\make_release_zip.bat
```

This writes `release\MCSA-1.0.0-win64.zip` and prints SHA-256. Do not commit
`dist\`, `build\`, or `release\`.

### 1.2 Packaged smoke checklist

Development machine (actual `MCSA.exe`, not `run.bat`):

- [ ] Launch with no console window and no Qt plugin / missing-DLL error
- [ ] Setup, strings, SVG nav icons, wheel-safe combos, Auto Stop ON/OFF
- [ ] Real mouse Raw Input capture, hold duration, press interval
- [ ] Generate Report → four artifacts, COMPLETE, measurement_only
- [ ] HTML opens; XLSX opens in **Microsoft Excel** without repair
- [ ] Open Reports Folder
- [ ] Restart; settings persist (`%AppData%\MCSA\MouseClickStabilityAnalyzer.ini`)
- [ ] Copy the folder to a path with spaces and a non-ASCII path
- [ ] Launch from a different current directory (`cd C:\Windows\System32` then full EXE path)
- [ ] Launch with project Python / `.venv` removed from PATH

Clean Windows machine / VM (required before GitHub v1.0.0):

- [ ] No project checkout, no project venv, Python may be absent
- [ ] Unpack ZIP, run `MCSA.exe`, real mouse run, Generate Report
- [ ] Record Windows version, whether Python was installed, ZIP SHA-256, result

### 1.3 Release candidate evidence

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

Scripted helper startup (`MCSA.exe --mcsa-raw-input-helper` reporting `ready`) proves
the frozen helper launches; it is not physical Raw Input acceptance.

### 1.4 Third-party notice gate (final dist audit)

`packaging\THIRD_PARTY_NOTICES.txt` lists the bundled components and points at
copied license texts under `licenses\`. It is a reference, not a compliance
statement. `build_exe.bat` copies `packaging\licenses\` into the release folder.
`verify_bundle.py` checks those files are present; it does not interpret licenses.

Local texts copied for v1.0.0:

- [x] Python 3.12.10 `LICENSE.txt` → `licenses\python_LICENSE.txt`
- [x] openpyxl 3.1.5 `LICENCE.rst`
- [x] et-xmlfile 2.0.0 `LICENCE.rst` and `LICENCE.python`
- [x] PyInstaller 6.13.0 `COPYING.txt` (GPL-2.0-or-later with bootloader exception)
- [x] PySide6 wheel `LicenseRef-Qt-Commercial.txt` as shipped
- [x] PySide6 / shiboken6 / Qt libraries — METADATA declares
      `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`. The wheels do not ship
      those texts, so the unmodified files come from
      `https://code.qt.io/cgit/pyside/pyside-setup.git` tag `v6.11.0`
      (commit `04cd59c10681242e387d125cfe5269902962ded1`), `LICENSES/`:
      `qt_LGPL-3.0-only.txt`, `qt_GPL-3.0-only.txt`, `qt_GPL-2.0-only.txt`

When upgrading PySide6, refresh these from the matching Qt for Python tag.
Presence of license files is a technical gate only; organizational/legal
review of the distribution is separate and is not claimed here.

### 1.5 Git tag / GitHub Release (do not run until every Part 1 gate passes)

```bat
git tag -a v1.0.0 -m "MCSA v1.0.0"
git push <remote> <branch>
git push <remote> v1.0.0
```

GitHub Release title: `MCSA v1.0.0`. Attach `MCSA-1.0.0-win64.zip` and the SHA-256.
Code signing is not configured; unsigned SmartScreen prompts are expected.

Smart App Control (Windows 11): v1.0.0 is unsigned. On systems where Smart App
Control enforces blocking of unsigned or untrusted applications, `MCSA.exe` may
be blocked before launch. Clean-machine validation of the v1.0.0 candidate
(Windows 11 26H2, build 26300.9550) recorded: Smart App Control ON, launch
blocked; Smart App Control OFF, the application ran normally. Treat this as a
known unsigned-distribution limitation, not a runtime defect. Do not document
disabling Defender as a normal step.

Custom application icon: not included (no existing project icon). Default EXE icon is a documented polish item, not a packaging blocker.

---

## Part 2 — Source / Git workflow

Use this to keep the source repository clean and pushed. It does **not** create the
v1.0.0 release; tagging and the GitHub Release belong to Part 1.5.

### 2.1 Clean local artifacts (safe script)

From the project folder:

```bat
clean_local.bat
```

Type `YES` when prompted. This removes **only**:

- `reports\mcsa_*` (your test runs; keeps `reports\.gitkeep`)
- `.venv\` / `venv\` / `.venv-build\` (project root)
- `__pycache__\` (under this project)
- `src\*.egg-info\`, `build\`, `dist\`, `release\`

It does **not** delete source code, `install.bat`, `docs\`, etc.

### 2.2 README screenshot

```bat
save_readme_screenshot.bat
```

1. Open MCSA → Theme **Dark** → LISTEN screen  
2. `Win+Shift+S` capture → image on clipboard  
3. Run script above → saves `docs\images\mcsa-ui-dark-listen.png`

### 2.3 Verify the source checkout

```bat
install.bat
run.bat
run.bat --mode self-test
```

### 2.4 Commit and push source (Git installed)

Install Git for Windows (once):

```bat
winget install Git.Git
```

First-time repository setup only (skip if the folder is already a Git repository):

```bat
cd C:\mouse_click_stability_analyzer
git init
git branch -M main
git remote add origin https://github.com/kotori0802/mouse-click-stability-analyzer.git
```

Then commit and push:

```bat
git add .
git status
git commit -m "<message>"
git push -u origin main
```

Do not tag `v1.0.0` here. Follow Part 1.5 after the Part 1 gates pass.

### 2.5 Before upload — manual check

```bat
dir reports
```

You should see only `.gitkeep` (no `mcsa_*.json` you care about in the upload folder).

- [ ] No real device names you do not want public in committed files  
- [ ] `SECURITY.md` / `PRIVACY.md` present  
- [ ] `docs/images/mcsa-workflow.svg` present  

### 2.6 Do not upload

| Path | Reason |
|------|--------|
| `reports/mcsa_*` | Local test sessions |
| `.venv/` / `venv/` / `.venv-build/` | Python environments |
| `build/` / `dist/` / `release/` | Generated EXE build output and ZIP |
| `src/**/*.egg-info/` | pip install artifact |
| `__pycache__/` | Bytecode |

---

## Part 3 — Optional legacy / manual upload (no Git)

Historical path for a PC without Git. It uploads **source only** and does not create
the v1.0.0 release or tag. The end-user `MCSA-1.0.0-win64.zip` is published only
through Part 1.5.

```bat
clean_local.bat
pack_for_upload.bat
```

1. Add screenshot to `_dist_upload\docs\images\mcsa-ui-dark-listen.png`
2. Zip the `_dist_upload` folder
3. GitHub → **New repository** → **Upload files** → drag zip contents

Apply the checks in Part 2.5 and 2.6 before uploading. Or install Git later and use Part 2.4.
