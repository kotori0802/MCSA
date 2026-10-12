@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0" || exit /b 1

echo MCSA 1.0.0 Windows EXE build
echo Repository: %~dp0
echo Required: Python 3.12 64-bit
echo.

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "VENV=%ROOT%\.venv-build"
set "DISTDIR=%ROOT%\dist\MCSA-1.0.0-win64"
set "WORKDIR=%ROOT%\build\pyinstaller"
set "PYEXE="

if exist "%VENV%\Scripts\python.exe" (
    set "PYEXE=%VENV%\Scripts\python.exe"
)

if not defined PYEXE (
    for /f "delims=" %%I in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)

if not defined PYEXE (
    echo [ERROR] Python 3.12 64-bit was not found.
    echo Create the build environment first:
    echo     py -3.12 -m venv .venv-build
    echo     .venv-build\Scripts\python -m pip install -U pip
    echo     .venv-build\Scripts\python -m pip install -r requirements-build.txt
    echo     .venv-build\Scripts\python -m pip install -e .
    echo Then run build_exe.bat again.
    exit /b 1
)

"%PYEXE%" -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Build interpreter is not Python 3.12 64-bit:
    echo         %PYEXE%
    echo This release does not fall back to another Python version.
    exit /b 1
)

echo Using: %PYEXE%
echo Verifying pinned build toolchain and existing reports ...
"%PYEXE%" "%ROOT%\packaging\check_build_env.py" "%ROOT%"
if errorlevel 1 (
    echo Build stopped. No release was produced.
    exit /b 1
)

echo Cleaning previous build output ...
if exist "%DISTDIR%" rd /s /q "%DISTDIR%"
if exist "%WORKDIR%" rd /s /q "%WORKDIR%"
if exist "%ROOT%\dist\MCSA.exe" del /f /q "%ROOT%\dist\MCSA.exe"

echo Running PyInstaller ...
"%PYEXE%" -m PyInstaller --noconfirm --clean --workpath "%WORKDIR%" --distpath "%ROOT%\dist" "%ROOT%\packaging\mcsa.spec"
if errorlevel 1 (
    echo [ERROR] PyInstaller failed.
    exit /b 1
)

if not exist "%DISTDIR%\MCSA.exe" (
    echo [ERROR] Expected output missing:
    echo         %DISTDIR%\MCSA.exe
    exit /b 1
)

copy /y "%ROOT%\LICENSE" "%DISTDIR%\LICENSE" >nul
copy /y "%ROOT%\packaging\QUICK_START.txt" "%DISTDIR%\QUICK_START.txt" >nul
copy /y "%ROOT%\packaging\THIRD_PARTY_NOTICES.txt" "%DISTDIR%\THIRD_PARTY_NOTICES.txt" >nul
if exist "%ROOT%\PRIVACY.md" copy /y "%ROOT%\PRIVACY.md" "%DISTDIR%\PRIVACY.md" >nul
if exist "%ROOT%\SECURITY.md" copy /y "%ROOT%\SECURITY.md" "%DISTDIR%\SECURITY.md" >nul

"%PYEXE%" "%ROOT%\packaging\verify_bundle.py" "%DISTDIR%"
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo Release folder:
echo   %DISTDIR%
echo.
endlocal
exit /b 0
