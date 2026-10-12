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
  "$src='%SRC%'; $zip='%ZIP%'; $stage=Join-Path $env:TEMP ('mcsa-zip-'+[guid]::NewGuid().ToString()); New-Item -ItemType Directory -Path $stage | Out-Null; Copy-Item -Path $src -Destination (Join-Path $stage 'MCSA-1.0.0-win64') -Recurse; $rel=Join-Path $stage 'MCSA-1.0.0-win64'; Remove-Item (Join-Path $rel 'reports') -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item (Join-Path $rel 'mcsa_startup.log') -Force -ErrorAction SilentlyContinue; Compress-Archive -Path (Join-Path $stage 'MCSA-1.0.0-win64') -DestinationPath $zip -CompressionLevel Optimal; Remove-Item $stage -Recurse -Force"
if errorlevel 1 exit /b 1

powershell.exe -NoProfile -Command ^
  "$z='%ZIP%'; $h=Get-FileHash $z -Algorithm SHA256; '{0}  {1}  {2} bytes' -f $h.Hash, $z, (Get-Item $z).Length"

endlocal
exit /b 0
