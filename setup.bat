@echo off
setlocal

REM Move to the folder that contains this script
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv...
    python -m venv .venv
    if errorlevel 1 (
        echo Failed to create virtual environment. Make sure Python is installed.
        exit /b 1
    )
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Failed to activate virtual environment.
    exit /b 1
)

echo Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    exit /b 1
)

echo Installing dependencies from requirements.txt...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Dependency installation failed.
    exit /b 1
)

if not exist "gui_processing_state.json" (
    echo Generating default GUI state file...
    python -c "import json; from pathlib import Path; Path('gui_processing_state.json').write_text(json.dumps({'last_processing_settings': {}, 'valve_names_by_header': {}, 'valve_names_by_set': {}, 'last_valve_names': {}}, indent=2), encoding='utf-8')"
)

echo.
echo Setup complete.
echo You can run the app with:
echo     python reactor_plotter.py
