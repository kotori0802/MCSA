@echo off
REM Prepare a clean folder for manual zip upload (no Git required).
REM Run clean_local.bat first if you have local test reports to remove.

setlocal
cd /d "%~dp0" || exit /b 1

set "OUT=%~dp0_dist_upload"
if exist "%OUT%" (
    echo Removing old %OUT% ...
    rd /s /q "%OUT%"
)

echo Creating upload copy at:
echo   %OUT%
echo.

robocopy "%~dp0" "%OUT%" /E /XD reports .venv venv build dist __pycache__ _dist_upload .git ^
    characterization_out .pytest_cache .mypy_cache .ruff_cache *.egg-info .eggs .idea .vscode ^
    /XF *.pyc *.pyo *.log ~$* .env settings.local.json ^
    /NFL /NDL /NJH /NJS /nc /ns /np

REM Ensure empty reports placeholder exists in upload bundle
if not exist "%OUT%\reports" mkdir "%OUT%\reports"
if exist "%~dp0reports\.gitkeep" copy /y "%~dp0reports\.gitkeep" "%OUT%\reports\" >nul

echo.
echo === Next steps (no Git on this PC) ===
echo 1. Add screenshot: %OUT%\docs\images\mcsa-ui-dark-listen.png
echo 2. Zip folder _dist_upload
echo 3. GitHub.com - New repository - Upload the zip contents
echo.
echo Or install Git: winget install Git.Git
echo Then see RELEASING.md
echo.
pause
endlocal
