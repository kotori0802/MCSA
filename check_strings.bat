@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "MCSA_ROOT=%~dp0"
set "MCSA_SRC=%MCSA_ROOT%src"
set "PYTHONPATH=%MCSA_SRC%"
set "PYEXE="

if exist "%MCSA_ROOT%.venv\Scripts\python.exe" (
    "%MCSA_ROOT%.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
    if not errorlevel 1 set "PYEXE=%MCSA_ROOT%.venv\Scripts\python.exe"
)

if not defined PYEXE (
    for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)

if not defined PYEXE (
    echo [ERROR] Python 3.12 64-bit was not found.
    echo Run install.bat from this folder first.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

"!PYEXE!" -B -m mouse_click_stability_analyzer.strings check
set "CODE=!ERRORLEVEL!"
if not "!CODE!"=="0" (
    echo.
    echo String resource check failed.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
)
endlocal & exit /b %CODE%
