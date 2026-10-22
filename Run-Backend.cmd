@echo off
rem Run-Backend.cmd - double-click to migrate the local dev DB and start Django.
rem Local dev only: 127.0.0.1:8000. Ctrl+C stops it. Nothing is downloaded.
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] Missing virtualenv interpreter: %PY%
    echo Create .venv and install the locked dev requirements first.
    pause
    exit /b 1
)

"%PY%" -c "import django" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Django is not importable from %PY%
    echo Install the locked dev requirements first. Nothing was downloaded.
    pause
    exit /b 1
)

echo Applying migrations to the local dev database...
"%PY%" "%~dp0backend\manage.py" migrate --noinput
if errorlevel 1 (
    echo [ERROR] Migration failed. The window stays open for review.
    pause
    exit /b 1
)

echo Starting Django on http://127.0.0.1:8000/ (Ctrl+C to stop)
"%PY%" "%~dp0backend\manage.py" runserver 127.0.0.1:8000
if errorlevel 1 (
    echo [ERROR] runserver exited with an error. The window stays open.
    pause
    exit /b 1
)

endlocal
