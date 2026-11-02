---
description: "Qt migration step 01 — regression baselines and PySide6/QtAgg spike"
---

# 01 — Regression baselines and PySide6/QtAgg spike

Read [the PySide6 refactor plan](../../docs/reactor-pressure-analyzer-pyside6-refactor-plan.md), especially **Resolved owner decisions**, before starting. This is Stage 0 of that plan.

## Goal

Create a safety net before any GUI code changes, and prove PySide6 works in the existing `.venv` workflow.

## Tasks

1. Create a `tests/` package using standard-library `unittest` only (no new test-runner dependency).
2. Add recipe-conversion regression tests in `tests/test_recipe_conversion.py`:
   - Convert `Example recipe sheet.csv` with `convert_to_json.load_table()` + `build_payload()` and compare `recipe` and `username` with `Example recipe sheet_payload.json`. Parse `experimentalDetails` as JSON and compare it with `EndTime` removed (time-dependent).
   - Load `Recipe sheet workbook format.xlsx` and `Recipe sheet workbook format (old).xlsx`; assert `validate_recipe_sheet()` and `build_payload()` complete and produce 9-column recipe rows.
   - A synthetic multi-sequence fixture (built in-test as a DataFrame) reproducing the owner's example: seq 1 = valve 12 × 1 cycle; seq 2 = valve 7 × 1; seq 3 = valves 5,5,7,8,8,7 × 40 cycles; seq 4 = valve 12 × 1. Assert `ProcessTimeHr` equals the hand-calculated per-sequence sum.
   - Assert that conversion never modifies the source file bytes (hash before/after).
3. Add `tests/test_sequence_utils.py` covering `convert_sequence()` sequence-start/continuation behavior on the same fixture.
4. Add a light pipeline smoke test only if a small, fast fixture is available in the repository (e.g. a truncated synthetic NDJSON written to a temp dir); otherwise document the gap in the test module docstring. Never write into tracked data folders.
5. Add `PySide6` to `requirements.txt` and install it into `.venv`.
6. Add `tests/test_qt_spike.py` that, with `QT_QPA_PLATFORM=offscreen`:
   - creates a `QApplication`, a `QMainWindow`, and an embedded `FigureCanvasQTAgg`;
   - runs a `QThread`/worker object that emits progress and error signals, verified to arrive on the GUI thread;
   - confirms `matplotlib` batch `savefig()` to a temp PNG still works after the Qt canvas exists.
   Skip cleanly if PySide6 is not importable.
7. Verify the existing Tk app still imports (`import gui`) without launching a window.

## Acceptance

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` passes.
- No backend module behavior changes; no tracked data files modified.
- Document the test command in the plan doc's test section.

## Out of scope

Any Qt UI beyond the spike; launcher changes.
