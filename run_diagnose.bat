@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
echo === MCSA launch diagnostic ===
echo Project folder: %~dp0
echo Current folder: %CD%
echo Supported runtime: Python 3.12 64-bit
echo Recommended root: C:\MCSA\  or  C:\Tools\MCSA\
echo.

set "MCSA_ROOT=%~dp0"
set "MCSA_SRC=%MCSA_ROOT%src"
set "PYTHONPATH=%MCSA_SRC%"
set "PYEXE="

if not exist "%MCSA_SRC%\mouse_click_stability_analyzer\__init__.py" (
    echo [ERROR] Source folder missing: %MCSA_SRC%\mouse_click_stability_analyzer
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

if exist "%MCSA_ROOT%.venv\Scripts\python.exe" (
    echo [OK] project .venv found
    "%MCSA_ROOT%.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=%MCSA_ROOT%.venv\Scripts\python.exe"
    ) else (
        echo [ERROR] .venv exists but is not Python 3.12 64-bit
    )
) else (
    echo [--] project .venv not found  ^(run install.bat^)
)

if not defined PYEXE (
    for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
    if defined PYEXE echo [OK] py -3.12 found
)

if not defined PYEXE (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)

if not defined PYEXE (
    echo [ERROR] Python 3.12 64-bit was not found.
    echo run.bat will not fall back to a newer Python.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

echo.
echo Selected interpreter: !PYEXE!
"!PYEXE!" -c "import sys; print('  version:', sys.version.split()[0]); print('  64-bit:', sys.maxsize>2**32); print('  executable:', sys.executable)"
if errorlevel 1 (
    echo   interpreter failed to start
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

"!PYEXE!" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Selected interpreter is not Python 3.12 64-bit.
    echo run.bat will refuse to launch.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

echo.
"!PYEXE!" -B -c "import mouse_click_stability_analyzer as m; print('  import mouse_click_stability_analyzer: OK'); print('  source:', m.__file__)"
if errorlevel 1 (
    echo   import mouse_click_stability_analyzer: FAILED
    echo   PYTHONPATH is set to: %MCSA_SRC%
)

"!PYEXE!" -B -c "import PySide6; print('  import PySide6: OK', PySide6.__version__)"
if errorlevel 1 (
    echo   import PySide6: FAILED
    echo   Normal run.bat cannot start until PySide6 is installed. Run install.bat.
    echo   Legacy Tk is not used automatically. Explicit only: run.bat --ui tk
)

"!PYEXE!" -B -c "import openpyxl; print('  import openpyxl: OK', openpyxl.__version__)"
if errorlevel 1 (
    echo   import openpyxl: MISSING
    echo   MCSA still launches; XLSX export will be unavailable.
)

echo.
echo run.bat uses this folder's src\ via PYTHONPATH and prefers .venv when present.
echo.
if /I not "%MCSA_NOPAUSE%"=="1" pause
exit /b 0
