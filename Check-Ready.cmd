@echo off
rem Check-Ready.cmd - double-click to run the local preflight.
rem Command line: Check-Ready.cmd --no-pause
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" "%~dp0tools\preflight.py"
set "RC=%ERRORLEVEL%"
if /I not "%~1"=="--no-pause" pause
endlocal & exit /b %RC%
