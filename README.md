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

The interface uses solid, compact action buttons and color-coded sections:
blue for input/plot controls, green for temperature/valve data, purple for
recipe actions, and amber for file-ownership warnings. Numeric fields stay
compact while file paths remain expandable. On the Analyze page, the
Processing panel sits in the right column below Analysis and Plot Options;
its Run All action has checkboxes to attach temperature and iSE data. The
log spans the full page width below both columns and stays in view while
the columns scroll. Processing behavior and confirmation safeguards are
unchanged.

## Run tests

In PowerShell, use the existing virtual environment:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

For application details and data formats, see [WHITEPAPER.md](WHITEPAPER.md).
