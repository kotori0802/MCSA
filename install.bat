@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Mouse Click Stability Analyzer - install
echo Project folder: %~dp0
echo Target: project-local .venv with Python 3.12 64-bit
echo Does not install into global Python and does not require Administrator.
echo.
echo Recommended project folder: C:\MCSA\  or  C:\Tools\MCSA\
echo A deep OneDrive / Desktop tree can push PySide6 files in .venv past 260 characters
echo on PCs that do not have Windows long-path support enabled.
echo.

set "MCSA_ROOT=%~dp0"
set "VENV_PY=%MCSA_ROOT%.venv\Scripts\python.exe"
set "BASEPY="

if not exist "%MCSA_ROOT%src\mouse_click_stability_analyzer\__init__.py" (
    echo [ERROR] MCSA source folder is missing:
    echo         %MCSA_ROOT%src\mouse_click_stability_analyzer
    echo Copy or unzip the full project before running install.bat.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

py -3.12 -c "import sys; raise SystemExit(0 if sys.maxsize>2**32 else 1)" >nul 2>&1
if not errorlevel 1 set "BASEPY=py -3.12"

if not defined BASEPY (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
    if not errorlevel 1 set "BASEPY=python"
)

if not defined BASEPY (
    echo [ERROR] Python 3.12 64-bit was not found.
    echo Install Python 3.12 x64 from python.org, then run install.bat again.
    echo This release does not install into newer Python versions.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

echo Base interpreter: %BASEPY%
echo.

if exist "%VENV_PY%" (
    "%VENV_PY%" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Existing .venv is not Python 3.12 64-bit.
        echo Delete the .venv folder and run install.bat again.
        if /I not "%MCSA_NOPAUSE%"=="1" pause
        exit /b 1
    )
    echo Reusing existing .venv
) else (
    echo Creating .venv ...
    %BASEPY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create .venv. Python 3.12 venv module is required.
        if /I not "%MCSA_NOPAUSE%"=="1" pause
        exit /b 1
    )
)

echo --- "%VENV_PY%" -m pip install -e ".[gui]" ---
"%VENV_PY%" -m pip install -e ".[gui]"
if errorlevel 1 (
    echo [ERROR] pip install into .venv failed.
    echo Check internet / proxy access to PyPI, then retry.
    if /I not "%MCSA_NOPAUSE%"=="1" pause
    exit /b 1
)

echo.
echo Done. Next: run.bat
echo Launch uses this folder's src\ and .venv\ only.
if /I not "%MCSA_NOPAUSE%"=="1" pause
endlocal
