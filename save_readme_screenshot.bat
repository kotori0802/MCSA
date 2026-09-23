@echo off
REM Save README hero screenshot from clipboard to docs\images\mcsa-ui-dark-listen.png
REM 1. Open MCSA in dark theme (Theme: Dark)
REM 2. Win+Shift+S capture the window, or copy image to clipboard
REM 3. Run this script

setlocal
cd /d "%~dp0" || exit /b 1
if not exist "docs\images" mkdir "docs\images"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Add-Type -AssemblyName System.Windows.Forms; ^
   if (-not [System.Windows.Forms.Clipboard]::ContainsImage()) { ^
     Write-Host 'Clipboard has no image. Copy a screenshot first (Win+Shift+S).'; exit 1 }; ^
   $img = [System.Windows.Forms.Clipboard]::GetImage(); ^
   $path = Join-Path (Get-Location) 'docs\images\mcsa-ui-dark-listen.png'; ^
   $img.Save($path, [System.Drawing.Imaging.ImageFormat]::Png); ^
   Write-Host \"Saved: $path\""

if errorlevel 1 (
    echo.
    echo Failed. Copy the dark-mode MCSA screenshot to clipboard, then retry.
    pause
    exit /b 1
)
echo.
echo OK. README will show docs/images/mcsa-ui-dark-listen.png
pause
endlocal
