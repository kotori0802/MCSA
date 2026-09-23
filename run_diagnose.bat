@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo === MCSA launch diagnostic ===
echo Project folder: %~dp0
echo Current folder: %CD%
echo.

where py 2>nul && echo [OK] py launcher found || echo [--] py not found
where python 2>nul && echo [OK] python found || echo [--] python not found
echo.

set "PICK="
call :test_runner "py -3"
call :test_runner python
call :test_runner py

echo.
if defined PICK (
    echo run.bat would use: %PICK%
    echo You can launch with: run.bat
) else (
    echo run.bat cannot start until import works.
    echo From THIS folder run: install.bat
    echo   ^(or: cd /d "%~dp0" then python -m pip install -e .^)
)
echo.
pause
exit /b 0

:test_runner
echo --- Testing %~1 ---
%~1 -c "import sys; print('  executable:', sys.executable); print('  version:', sys.version.split()[0])" 2>&1
if errorlevel 1 (
    echo   runner failed to start
    echo.
    exit /b 0
)
set "IMPORT_OK=0"
%~1 -c "import mouse_click_stability_analyzer; print('  import mouse_click_stability_analyzer: OK')" 2>&1
if not errorlevel 1 set "IMPORT_OK=1"
if "%IMPORT_OK%"=="0" echo   import mouse_click_stability_analyzer: FAILED
%~1 -c "import tkinter; print('  import tkinter: OK')" 2>&1
if errorlevel 1 echo   import tkinter: FAILED - GUI cannot start
if "%IMPORT_OK%"=="1" if not defined PICK set "PICK=%~1"
echo.
exit /b 0
