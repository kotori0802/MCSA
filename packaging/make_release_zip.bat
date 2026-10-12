@echo off
setlocal EnableExtensions
cd /d "%~dp0\.." || exit /b 1

set "SRC=%CD%\dist\MCSA-1.0.0-win64"
set "OUTDIR=%CD%\release"
set "ZIP=%OUTDIR%\MCSA-1.0.0-win64.zip"

if not exist "%SRC%\MCSA.exe" (
    echo [ERROR] Build the package first: build_exe.bat
    echo Missing: %SRC%\MCSA.exe
    exit /b 1
)

if not exist "%OUTDIR%" mkdir "%OUTDIR%"
if exist "%ZIP%" del /f /q "%ZIP%"

echo Creating %ZIP%
powershell.exe -NoProfile -Command ^
  "Compress-Archive -Path '%SRC%' -DestinationPath '%ZIP%' -CompressionLevel Optimal"
if errorlevel 1 exit /b 1

powershell.exe -NoProfile -Command ^
  "$z='%ZIP%'; $h=Get-FileHash $z -Algorithm SHA256; '{0}  {1}  {2} bytes' -f $h.Hash, $z, (Get-Item $z).Length"

endlocal
exit /b 0
