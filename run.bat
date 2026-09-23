@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Mouse Click Stability Analyzer
echo Project folder: %~dp0
echo.

set "RUNNER="

py -3 -B -c "import mouse_click_stability_analyzer" >nul 2>&1
if not errorlevel 1 set "RUNNER=py -3"

if not defined RUNNER (
    python -B -c "import mouse_click_stability_analyzer" >nul 2>&1
    if not errorlevel 1 set "RUNNER=python"
)

if not defined RUNNER (
    py -B -c "import mouse_click_stability_analyzer" >nul 2>&1
    if not errorlevel 1 set "RUNNER=py"
)

if not defined RUNNER (
    echo [ERROR] Cannot import mouse_click_stability_analyzer.
    echo.
    echo From this folder run:
    echo   install.bat
    echo   run.bat
    echo.
    echo Run run_diagnose.bat for details.
    pause
    exit /b 1
)

echo Using: %RUNNER%
echo Reports: "%~dp0reports"  (created after you finish a local run)
echo.

%RUNNER% -B -m mouse_click_stability_analyzer %*
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo Exited with code %CODE%.
    echo Run run_diagnose.bat if the window closed too fast to read the error.
    pause
)
endlocal & exit /b %CODE%
