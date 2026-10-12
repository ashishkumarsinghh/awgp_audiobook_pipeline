@echo off
setlocal
cd /d "%~dp0"
echo ======================================================
echo    AWGP Audiobook Production Pipeline Launcher
echo ======================================================
echo Launching services on Windows...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
endlocal
