---
description: "Qt migration step 03 — Recipe Editor vertical slice: open, metadata, table view, validation, export"
---

# 03 — Recipe Editor vertical slice (read/validate/export)

Prerequisite: 02. Read the plan's **Recipe Editor page**, **Open, draft, and export semantics**, and **Resolved owner decisions**.

## Tasks

1. `reactor_ui/models/recipe_document.py`: `RecipeDocument` (plain Python + Qt signals via a `QObject`) holding source path, loaded DataFrame, header metadata (`extract_header_details`), valve metadata, source timing rows (`extract_timing_table`), sequence notes, validation messages (`validate_recipe_sheet`), wait time, start time, and dirty/stale flags. It never writes to the source file.
2. `reactor_ui/models/recipe_table_model.py`: read-only (for now) `QAbstractTableModel` over source rows. Columns: `#`, `Seq` (derived, read-only), then `Cycle, Valve, PrePump, N2Dose, PumpDose, Dose, Hold, PrePurge, Purge, Notes`. Use these owner-confirmed labels regardless of workbook header text.
3. `reactor_ui/pages/recipe_editor_page.py` layout per the mockup and plan:
   - page header with **New** (empty document), **Open…**, **Export Payload…**;
   - vertical `QSplitter`: top row = horizontal splitter with **Recipe Metadata** card (username, multiline Info/description, DID, EDR, **Wait time (s)**, **Start time** `QDateTimeEdit` defaulting to now, read-only **Run duration** and **Predicted end time** = start + wait + run duration) and **Valve Metadata** card (valve #, name, temperature);
   - bottom = horizontal splitter ~50/50: left placeholder card "Run Timeline & Sequence Details" (implemented in 05; show sequence count and run duration text for now), right one `QTableView`;
   - footer: validation status, source path, last export path.
4. Run duration must come from the same per-sequence algorithm as the converter. Expose a small public helper in `convert_to_json.py` (e.g. `estimate_process_seconds(df)`) that `_estimate_process_times()` reuses, so there is one implementation.
5. Export: `adapters/recipe_conversion.py` calls `build_payload()` + `save_payload()`. Add an optional `start_time` parameter to `build_payload()`/`_estimate_process_times()` so `EndTime` = start + wait + process; default remains `now()` so CLI/Tk behavior is unchanged. Default output name follows the existing `build_output_filename()` / `_payload.json` behavior. Block export when validation has blocking errors.
6. Wire the page into the shell's Recipe Editor navigation.
7. Tests: document loads the CSV and both workbooks; table row/column counts; exported payload equals direct `build_payload()` output (minus `EndTime`); `EndTime` uses supplied start time; source hash unchanged; existing 01 tests still pass.

## Acceptance

Open a real sample, see metadata/valves/rows, export a payload identical in content to the Tk path, never touch the source workbook.
