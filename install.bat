@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Mouse Click Stability Analyzer - install
echo Project folder: %~dp0
echo.

set "ANY_OK=0"

where python >nul 2>&1
if not errorlevel 1 (
    echo --- python -m pip install -e ".[gui]" ---
    python -m pip install -e ".[gui]"
    if errorlevel 1 python -m pip install -e . PySide6 openpyxl
    if not errorlevel 1 set "ANY_OK=1"
    echo.
)

where py >nul 2>&1
if not errorlevel 1 (
    echo --- py -3 -m pip install -e ".[gui]" ---
    py -3 -m pip install -e ".[gui]"
    if errorlevel 1 py -3 -m pip install -e . PySide6 openpyxl
    if not errorlevel 1 set "ANY_OK=1"
    echo.
)

if "%ANY_OK%"=="0" (
    echo [ERROR] Neither python nor py was found on PATH.
    pause
    exit /b 1
)

echo Done. Next: run.bat
pause
endlocal
