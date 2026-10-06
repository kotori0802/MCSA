@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

echo Mouse Click Stability Analyzer
echo Project folder: %~dp0
echo Supported runtime: Python 3.12 64-bit
echo.

set "MCSA_ROOT=%~dp0"
set "MCSA_SRC=%MCSA_ROOT%src"
set "PYTHONPATH=%MCSA_SRC%"
set "PYEXE="
set "NEED_PYSIDE=1"

echo %*| findstr /i /c:"--ui tk" >nul
if not errorlevel 1 set "NEED_PYSIDE=0"

if not exist "%MCSA_SRC%\mouse_click_stability_analyzer\__init__.py" (
    echo [ERROR] MCSA source folder is missing:
    echo         %MCSA_SRC%\mouse_click_stability_analyzer
    echo Copy or unzip the full project, then run install.bat from that folder.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

if exist "%MCSA_ROOT%.venv\Scripts\python.exe" (
    "%MCSA_ROOT%.venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
    if not errorlevel 1 (
        set "PYEXE=%MCSA_ROOT%.venv\Scripts\python.exe"
    ) else (
        echo [ERROR] Project .venv exists but is not Python 3.12 64-bit.
        echo Delete the .venv folder and run install.bat again.
        echo This release does not use a newer Python automatically.
        if /I not "%MCSA_NOPAUSE%"=="1" pause
        exit /b 1
    )
)

if not defined PYEXE (
    for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)

if not defined PYEXE (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)

if not defined PYEXE (
    echo [ERROR] Python 3.12 64-bit was not found.
    echo This release requires Python 3.12 64-bit. Newer or older versions are not selected automatically.
    echo Install Python 3.12 x64 from python.org, then run install.bat from this folder.
    echo Recommended project folder: C:\MCSA\  or  C:\Tools\MCSA\
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

"!PYEXE!" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Selected interpreter is not Python 3.12 64-bit:
    echo         !PYEXE!
    echo This release does not fall back to another Python version.
    echo Install Python 3.12 x64, then run install.bat.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

echo Using: "!PYEXE!"
"!PYEXE!" -B -c "import sys; print('Python:', sys.version.split()[0], '(64-bit)' if sys.maxsize>2**32 else '(32-bit)')"

"!PYEXE!" -B -c "import mouse_click_stability_analyzer as m; print('Source:', m.__file__)"
if errorlevel 1 (
    echo [ERROR] Cannot import mouse_click_stability_analyzer from this folder.
    echo         Expected: %MCSA_SRC%\mouse_click_stability_analyzer
    echo From this folder run: install.bat
    echo Then: run_diagnose.bat
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

if "!NEED_PYSIDE!"=="1" (
    "!PYEXE!" -B -c "import PySide6; print('PySide6:', PySide6.__version__)"
    if errorlevel 1 (
        echo [ERROR] PySide6 is not available in the selected Python 3.12 environment.
        echo From this folder run: install.bat
        echo That creates a local .venv and installs the verified GUI packages.
        if /I not "%MCSA_NOPAUSE%"=="1" pause
        exit /b 1
    )
)

"!PYEXE!" -B -c "import openpyxl" >nul 2>&1
if errorlevel 1 (
    echo [WARN] openpyxl is not installed. HTML/JSON/CSV reports still work; XLSX export is unavailable.
)

echo Reports: "%MCSA_ROOT%reports"
echo.

"!PYEXE!" -B -m mouse_click_stability_analyzer %*
set "CODE=!ERRORLEVEL!"
if not "!CODE!"=="0" (
    echo.
    echo Exited with code !CODE!.
    echo Run run_diagnose.bat if the window closed too fast to read the error.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
)
endlocal & exit /b %CODE%
