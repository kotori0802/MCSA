@echo off
setlocal EnableExtensions
REM ---------------------------------------------------------------------------
REM  MCSA clean_local.bat
REM  Removes ONLY local artifacts inside THIS project folder:
REM    - reports\mcsa_*   (your test run outputs; keeps reports\.gitkeep)
REM    - .venv\  venv\   (local Python virtual env, project root only)
REM    - __pycache__\    (under this project tree only)
REM    - *.egg-info\     (under src\ only)
REM  Does NOT touch source code, install.bat, or anything outside %ROOT%.
REM ---------------------------------------------------------------------------

set "ROOT=%~dp0"
cd /d "%ROOT%" || (
    echo [ERROR] Cannot enter project folder: %ROOT%
    exit /b 1
)

echo.
echo === MCSA local cleanup ===
echo Project root: %CD%
echo.
echo Will delete ONLY:
echo   - %CD%\reports\mcsa_*
echo   - %CD%\.venv\  %CD%\venv\
echo   - __pycache__ folders under this project
echo   - src\*.egg-info folders
echo.
echo Will NOT delete: src\, install.bat, run.bat, docs\, LICENSE, etc.
echo.
set /p CONFIRM=Type YES to continue: 
if /I not "%CONFIRM%"=="YES" (
    echo Cancelled.
    exit /b 0
)

set "COUNT=0"

REM --- reports/mcsa_* (files only; never reports\.gitkeep) ---
if exist "reports\" (
    for %%F in ("reports\mcsa_*") do (
        if exist "%%~fF" (
            echo [del] %%~fF
            del /f /q "%%~fF" 2>nul && set /a COUNT+=1
        )
    )
    for /d %%D in ("reports\mcsa_*") do (
        if exist "%%~fD" (
            echo [rmdir] %%~fD
            rd /s /q "%%~fD" 2>nul && set /a COUNT+=1
        )
    )
)

REM --- .venv / venv at project root only ---
if exist "%ROOT%.venv\" (
    echo [rmdir] %ROOT%.venv
    rd /s /q "%ROOT%.venv" 2>nul && set /a COUNT+=1
)
if exist "%ROOT%venv\" (
    echo [rmdir] %ROOT%venv
    rd /s /q "%ROOT%venv" 2>nul && set /a COUNT+=1
)

REM --- __pycache__ under project only (we are already cd'd to ROOT) ---
for /f "delims=" %%D in ('dir /s /b /ad "__pycache__" 2^>nul') do (
    echo %%D | findstr /i /b /c:"%CD%" >nul && (
        echo [rmdir] %%D
        rd /s /q "%%D" 2>nul && set /a COUNT+=1
    )
)

REM --- egg-info under src\ only ---
if exist "src\" (
    for /d %%D in ("src\*.egg-info") do (
        if exist "%%~fD" (
            echo [rmdir] %%~fD
            rd /s /q "%%~fD" 2>nul && set /a COUNT+=1
        )
    )
)

REM --- build/dist at project root (optional pip artifacts) ---
if exist "build\" (
    echo [rmdir] %ROOT%build
    rd /s /q "%ROOT%build" 2>nul && set /a COUNT+=1
)
if exist "dist\" (
    echo [rmdir] %ROOT%dist
    rd /s /q "%ROOT%dist" 2>nul && set /a COUNT+=1
)

echo.
echo Done. Removed %COUNT% item(s^).
echo reports\.gitkeep and all source files are untouched.
echo.
pause
endlocal
