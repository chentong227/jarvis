@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

REM ============================================================================
REM   J.A.R.V.I.S. Auto Installer
REM   Double-click to run. About 10-15 minutes (PyTorch is the slow part).
REM ============================================================================

cd /d "%~dp0"
title J.A.R.V.I.S. - Installer

echo.
echo ================================================
echo    J.A.R.V.I.S. Auto Installer
echo    Iron Man's Personal AI Butler
echo ================================================
echo.
echo  This will check your environment and install all dependencies.
echo  Please keep the network connection up. About 10-15 minutes.
echo.
pause


REM ============================================================================
REM  [1/6] Check Python
REM ============================================================================
echo.
echo [1/6] Checking Python...
where python > nul 2>&1
if errorlevel 1 (
    echo.
    echo ##############################################
    echo #  ERROR: Python is not installed!
    echo ##############################################
    echo.
    echo  How to fix:
    echo.
    echo  1. Open this URL in your browser:
    echo     https://www.python.org/downloads/release/python-3913/
    echo.
    echo  2. Scroll down to "Files".
    echo.
    echo  3. Click "Windows installer ^(64-bit^)" ^(about 28MB^).
    echo.
    echo  4. Run the installer.
    echo.
    echo  5. IMPORTANT: Check the box "Add Python to PATH" at the bottom!
    echo.
    echo  6. Click "Install Now" and wait 1-2 minutes.
    echo.
    echo  7. Then double-click this install.bat again.
    echo.
    pause
    exit /b 1
)

REM Check Python version (must be 3.9 or 3.10)
python -c "import sys; sys.exit(0 if sys.version_info[:2] in [(3,9),(3,10)] else 1)" 2>nul
if errorlevel 1 (
    echo.
    echo ##############################################
    echo #  ERROR: Wrong Python version!
    echo ##############################################
    echo.
    python --version
    echo.
    echo  J.A.R.V.I.S. requires Python 3.9 or 3.10.
    echo.
    echo  How to fix:
    echo  1. Uninstall the current Python ^(Control Panel - Programs^).
    echo  2. Install 3.9.13: https://www.python.org/downloads/release/python-3913/
    echo  3. Check "Add Python to PATH" during install.
    echo  4. Run install.bat again.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version') do set PYVER=%%v
echo     OK: !PYVER!


REM ============================================================================
REM  [2/6] Create virtual environment
REM ============================================================================
echo.
echo [2/6] Creating virtual environment ^(.venv folder^)...
if exist .venv (
    echo     Already exists, reusing.
) else (
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo  ERROR: Failed to create venv. Check disk space ^(need ~5GB free^).
        pause
        exit /b 1
    )
    echo     Created.
)


REM ============================================================================
REM  [3/6] Activate venv + upgrade pip
REM ============================================================================
echo.
echo [3/6] Activating venv and upgrading pip...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
echo     OK


REM ============================================================================
REM  [4/6] Install PyTorch (CUDA 12.1)
REM ============================================================================
echo.
echo [4/6] Installing PyTorch ^(NVIDIA GPU acceleration^)...
echo       This downloads about 2GB. May take 5-15 minutes.
echo       ^(Requires NVIDIA GPU. AMD/Intel-only laptops will not work.^)
echo.

REM Skip if already installed
python -c "import torch; assert torch.__version__ == '2.3.1+cu121'" 2>nul
if not errorlevel 1 (
    echo     PyTorch 2.3.1+cu121 already installed, skipping.
) else (
    pip install torch==2.3.1+cu121 torchaudio==2.3.1+cu121 --index-url https://download.pytorch.org/whl/cu121
    if errorlevel 1 (
        echo.
        echo  ERROR: PyTorch install failed. Possible reasons:
        echo    1. Network problem - check https://download.pytorch.org access.
        echo    2. Disk full - need 5GB+ free.
        echo    3. No NVIDIA GPU - this project does not support CPU-only mode.
        pause
        exit /b 1
    )
    echo     PyTorch installed.
)


REM ============================================================================
REM  [5/6] Install other dependencies
REM ============================================================================
echo.
echo [5/6] Installing other dependencies ^(~50 packages, 3-5 min^)...
pip install -r requirements-dev.txt
if errorlevel 1 (
    echo.
    echo  ERROR: Dependency install failed. Please send the error log above
    echo  to the person who gave you this code.
    pause
    exit /b 1
)
echo     OK


REM ============================================================================
REM  [6/6] Set up .env file
REM ============================================================================
echo.
echo [6/6] Setting up API key config ^(.env^)...
if exist .env (
    echo     .env already exists, skipping.
) else (
    if exist .env.example (
        copy .env.example .env > nul
        echo     Created .env from .env.example.
    ) else (
        echo  WARN: .env.example not found.
    )
)


REM ============================================================================
REM  Done - prompt for .env edit
REM ============================================================================
echo.
echo.
echo ================================================
echo    Installation complete!
echo    Last step: Fill in your API keys in .env
echo ================================================
echo.
echo  About to open .env in Notepad.
echo.
echo  Replace each "REPLACE_ME" with your real API key:
echo    - 5 OpenRouter keys   (https://openrouter.ai/keys)
echo    - 3 Google AI keys    (https://aistudio.google.com/apikey)
echo.
echo  If you don't have keys yet, press Ctrl+C to exit,
echo  apply for the keys online, then run install.bat again.
echo.
pause

start notepad .env

echo.
echo ================================================
echo    All done!
echo    Next step: double-click run.bat to start J.A.R.V.I.S.
echo ================================================
echo.
echo  If anything goes wrong, see README.md "Troubleshooting" section.
echo.
pause
exit /b 0
