@echo off
chcp 65001 > nul 2>&1
cd /d "%~dp0"
title J.A.R.V.I.S.

echo.
echo ================================================
echo    Starting J.A.R.V.I.S.
echo ================================================
echo.

REM Activate venv if present
if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo [OK] Virtual environment activated.
) else (
    echo [INFO] No .venv - using global Python.
)

if not exist .env (
    echo [INFO] No .env - using hardcoded keys in jarvis_nerve.py.
)

echo.
echo [INFO] Loading ^(first time ~30s for CosyVoice model^)...
echo.

REM Use -u for unbuffered output so we see logs in real time
python -u jarvis_nerve.py
set EXITCODE=%errorlevel%

echo.
echo ================================================
echo    J.A.R.V.I.S. exited (code: %EXITCODE%)
echo ================================================
echo.

REM Force keep window open EVEN if pause is skipped somehow
echo Press any key to close this window...
pause > nul
