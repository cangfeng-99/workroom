@echo off
rem Configure-MySQL.cmd - LOCAL LOGIN VERIFICATION ONLY.
rem It does NOT configure MySQL, does NOT create a database or user,
rem does NOT store the password, and does NOT write the user name to any report.
setlocal
cd /d "%~dp0"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
echo This only checks a local MySQL login. Nothing is configured or saved.
"%PY%" "%~dp0tools\check_mysql.py" --report "%~dp0tasks\reports\mysql-check.json"
set "RC=%ERRORLEVEL%"
echo Exit code: %RC%
pause
endlocal & exit /b %RC%
