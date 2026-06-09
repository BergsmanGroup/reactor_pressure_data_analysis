@echo off
setlocal

REM Run from this script's directory so relative paths always work.
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [INFO] .venv not found. Creating virtual environment...
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -m venv .venv
    ) else (
        python -m venv .venv
    )

    if errorlevel 1 (
        echo [ERROR] Failed to create .venv. Install Python 3 and try again.
        exit /b 1
    )
)

REM Optional one-shot dependency install/update.
REM Usage: run_gui.bat --setup
if /I "%~1"=="--setup" (
    shift
    echo [INFO] Upgrading pip...
    "%VENV_PY%" -m pip install --upgrade pip
    if errorlevel 1 (
        echo [ERROR] pip upgrade failed.
        exit /b 1
    )

    if exist "requirements.txt" (
        echo [INFO] Installing dependencies from requirements.txt...
        "%VENV_PY%" -m pip install -r requirements.txt
        if errorlevel 1 (
            echo [ERROR] Dependency installation failed.
            exit /b 1
        )
    )
)

REM Useful runtime defaults.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo [INFO] Launching Reactor Pressure Data Analyzer...
"%VENV_PY%" "gui.py" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Program exited with code %EXIT_CODE%.
)

exit /b %EXIT_CODE%
