@echo off
rem Start-Dev.cmd - double-click to open a PowerShell dev terminal in this workspace.
rem Only the new process environment changes; nothing is installed or started.
setlocal
cd /d "%~dp0"
powershell -NoLogo -NoExit -ExecutionPolicy Bypass -File "%~dp0tools\Enter-Dev.ps1"
if errorlevel 1 pause
endlocal
