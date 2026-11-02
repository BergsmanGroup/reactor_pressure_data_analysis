# Reactor Pressure Data Analyzer

## Run on Windows

From the project directory, set up the virtual environment and dependencies:

```bat
setup.bat
run_gui.bat
```

For later launches, use `run_gui.bat`. To install or update dependencies
explicitly, use `run_gui.bat --setup`. The equivalent Python entry point is
`.venv\Scripts\python.exe reactor_plotter.py`.

The Recipe Editor keeps changes in memory and exports a separate controller
JSON; it does not overwrite the source CSV or workbook. Timing is a provisional
serial estimate, with wait time included separately in the predicted end time.
Header corrections list affected files and require confirmation and backups.
Ordinary analysis also warns before overwriting existing condensed files or
outputs, but does not make header-correction backups.

## Run tests

In PowerShell, use the existing virtual environment:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For application details and data formats, see [WHITEPAPER.md](WHITEPAPER.md).
