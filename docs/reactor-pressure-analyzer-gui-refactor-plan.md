# Reactor Pressure Data Analyzer GUI Refactor Plan

> Historical pre-migration plan. Its Tkinter recommendation and repository
> observations have been superseded by the completed
> [PySide6 migration](reactor-pressure-analyzer-pyside6-refactor-plan.md);
> see the [README](../README.md) for the current interface and launch commands.

## Executive summary

Modernize the Recipe Sheet tab into a pre-run recipe editor and timeline, while keeping Excel as the canonical authoring file and preserving the existing JSON payload contract. Keep Tkinter for the first release. The repository already has a working Tkinter application, Windows launch scripts, and processing code that is mostly independent of the UI; a framework migration would add packaging and regression risk without being necessary to deliver the requested layout.

The central prerequisite is a small, tested timing model shared by the new editor and the existing payload/time calculations. The current code serializes nonzero timing slots in valve-row order, but repository evidence does not establish that this matches the controller's actual execution semantics. In addition, the workbook timing-column labels do not map cleanly to the phase names in `sequence_utils.py`. Do not present calculated sequence durations or phase names as authoritative until the slot mapping and execution order have been confirmed against controller documentation or a known run.

Keep recipe authoring and post-run header correction as distinct workflows. The current Header Editor writes edits directly into the selected NDJSON file; the redesigned workflow should default to a separate, provenance-bearing correction artifact and use corrected metadata only for derived analysis outputs. Do not silently rewrite the original run.

## Evidence and scope

This plan is based on the checked-in Python modules, workbook templates, sample payloads, and the textual requirements supplied with the task. No separate visual mockup assets, `docs/` directory, `tests/` directory, test configuration, or packaging/build configuration were found. The text requirements are therefore the visual reference for this plan. The unfinished temperature-controller project was not inspected or used as a dependency.

The current tree includes:

- The former app entry point created `ReactorApp` from `gui.py`.
- Processing modules: [pipeline.py](../pipeline.py), [data_parser.py](../data_parser.py), [sequence_utils.py](../sequence_utils.py), [plot_utils.py](../plot_utils.py), and [ise_utils.py](../ise_utils.py).
- Recipe conversion and validation in [convert_to_json.py](../convert_to_json.py); header parsing and persistence helpers in [header_text.py](../header_text.py); the former modal post-run editor in `header_editor.py`.
- Runtime dependencies in [requirements.txt](../requirements.txt), and Windows environment/launch scripts in [setup.bat](../setup.bat) and [run_gui.bat](../run_gui.bat).
- A current and old Excel template, CSV recipe examples, payload examples, and the DID000141 workbook and condensed run output. There are generated plots and an exposure CSV under `DID000141/`.
- [WHITEPAPER.md](../WHITEPAPER.md) and [PROCESSING_WORKFLOW_REVIEW.md](../PROCESSING_WORKFLOW_REVIEW.md). The whitepaper's statement that iSE attachment is not implemented is stale: `ReactorPipeline.attach_ise()` and cycle-summary support are present in the current code.

`Old scripts/` contains legacy programs and is not part of the current application entry path. No automated regression tests are present in the tracked tree.

## Current-state architecture and behavior

### UI and recipe conversion

`ReactorApp` in `gui.py` builds two notebook tabs. `_build_plot_tab()` owns raw/condensed-file selection, header actions, temperature and iSE inputs, valve labels, processing options, progress, and output controls. Processing operations are started on worker threads and UI updates are marshalled with `after()`. `_build_recipe_tab()` currently provides file selection, a JSON payload preview, validation feedback, and payload export; it is not a recipe editor and has no timing table or timeline.

`load_table()` in `convert_to_json.py` reads CSV and Excel data into a pandas DataFrame. `validate_recipe_sheet()` checks the newer workbook metadata layout and valve coverage while deliberately skipping some old-format sheets. `extract_timing_table()` finds the row whose first cell is `Cycles`, takes up to ten columns, and normalizes cycles, valve numbers, and timing values. `build_payload()` then produces the existing `{recipe, username, experimentalDetails}` JSON shape; `save_payload()` writes the adjacent `_payload.json` by default. The workbook is not written by this conversion path.

The current workbook is explicitly titled “PRE-RUN ONLY” and instructs users not to insert, delete, or reorder rows/columns in the A:J recipe area. It contains Excel process-time/end-time formulas outside that area (`M6` and `M8` in the current template). The converter separately computes `ProcessTimeHr` and `EndTime` in `_estimate_process_times()`. This is a reason to preserve the workbook as the primary authoring environment, not to promise workbook round-tripping from the GUI.

### Timing and sequence processing

`convert_sequence()` in `sequence_utils.py` interprets a positive cycle-count cell as the start of a sequence and blank/zero as a continuation row. It stores each valve row and seven numeric timing slots. `compute_phase_bins()` flattens those slots in valve-row order, accumulates each nonzero value, and omits zero-length slots. `make_cycle_seq_map()` expands sequence cycle counts to global cycle numbers. `assign_phase()` maps a measured cycle-relative timestamp into those bins.

`_estimate_process_times()` in `convert_to_json.py` independently groups continuation rows, sums timing columns 2–8 for each sequence, and multiplies that sum by the sequence's cycle count. It adds `WaitTime` when estimating `EndTime` but excludes it from `ProcessTimeHr`. `compute_phase_bins()` also accepts a `shift`, which is used by post-run phase labeling; it adds that shift to each nonzero slot. This post-run adjustment must not be reused as planned recipe time.

There is a material naming discrepancy to resolve. The workbook timing headers are `PrePurge, N2Dose, PumpDose, Dose, Hold, PrePurge, Purge`; `HeaderEditorDialog` labels the first timing slots `Pre-dose Pump, N2 Dose, Pump Dose`; and `PHASE_TYPES` in `sequence_utils.py` calls them `prepump, dosepump, dosen2, dose, hold, prepurge, purge`. The DID000141 phase-bin note also records a difference between the workbook and loaded-header values for a 0.5-second timing value. These sources show that the UI must not silently relabel or “correct” timing slots. Confirm the controller's canonical slot order and whether any operations overlap before finalizing names and calculations.

### Processing and outputs to preserve

`ReactorPipeline` in `pipeline.py` orchestrates:

1. `condense()` uses `data_parser.condense_log()` and `stream_pressure()` to make a condensed working file and load measured pressure points.
2. `label_phases()` derives phase bins and optionally bakes labels into condensed data.
3. Optional `attach_temperature()` loads temperature and service-config logs, detects/uses zones, and writes annotations.
4. Optional `attach_ise()` aligns ellipsometer data to cycles.
5. `preview_cycle()` and `generate_outputs()` render plots, compute exposure rows, create optional thickness output, build an animation, and write cycle summaries.

`plot_utils.py` owns phase-colored plot segments, per-cycle figures, exposure calculations, CSV output, and animation generation. `ise_utils.py` owns iSE parsing and cycle alignment. The redesign should keep these functions and output formats unchanged unless regression evidence proves a necessary adapter is missing.

One file-ownership behavior must be made explicit: when a selected input is already condensed and `write_condensed_json` is enabled, `ReactorPipeline.condense()` sets the working target to the selected file. Later labeling, temperature attachment, and cycle-summary writing can therefore update that selected condensed file in place. For a raw input, the normal target is a sibling `_condensed.json`. The redesigned UI must show the exact working/output paths and must not imply that every selected input remains untouched.

### Header correction is a separate, post-run workflow

The task specification establishes that LabVIEW does not update the recorded run header when a recipe changes mid-run. The existing `Edit Header...` flow is consequently a post-run correction path, not a way to edit a pre-run recipe.

In the current implementation, `read_header()` loads the first record's payload. `HeaderEditorDialog` edits header metadata and timing rows, can regenerate selected fields from a recipe workbook, and optionally writes a header text file. `gui.py::_edit_header()` resolves and may rename related artifacts, then calls `_rewrite_header_payload()`. That helper reads every line into memory and opens the selected NDJSON file with `"w"` to replace the first record; it is a direct in-place rewrite, not an atomic replace or a backed-up correction. `gui.py::_use_header_text_as_raw_header()` uses the same rewrite helper after comparing a header text file. The editor's row insertion/deletion controls belong to this correction UI; they do not mean the pre-run recipe tab already supports editing.

The recipe conversion flow writes a JSON payload beside the recipe workbook; the header correction flow can write the raw or condensed run header, a header text artifact, and rename related artifacts. Keep these save paths, prompts, and labels separate.

## Recommendation: retain Tkinter for the first release

| Option | Benefits | Costs and risks | Recommendation |
|---|---|---|---|
| Keep Tkinter/ttk | Already used by `ReactorApp` and `HeaderEditorDialog`; standard-library UI dependency; existing threading and Matplotlib integration can be retained; lowest risk to scientific processing and Windows launch scripts. `ttk.Panedwindow`, `Canvas`, and a model-backed table are sufficient for the requested split layout, scrubber, and one table. | Native theme behavior varies by platform; a consistent dark theme and dense table styling need deliberate work. `ttk.Treeview` is not a spreadsheet widget, so editing, paste, and undo need explicit implementation. Existing `gui.py` is large and couples state, layout, and callbacks. | **Use for MVP.** Extract the recipe view and timing model from `gui.py` without migrating the application framework. |
| Migrate to Qt/PySide6 | Stronger model/view widgets, splitters, keyboard and clipboard support, styling, accessibility, and more natural custom timeline interactions. Could be preferable if a polished, distributable scientific desktop product becomes the main goal. | Adds a large native dependency and Qt platform plugins; `requirements.txt`, environment setup, launch/packaging, CI, and user installation all need updates. Existing Tk dialogs, callbacks, styles, threading, and Matplotlib embedding must be rewritten and retested. Migration does not remove the need for a correct timing model or clarify execution semantics. | Do not migrate for this release. Reconsider only after a focused UI prototype demonstrates a concrete Tkinter limitation or a distributable installer is approved. |

No executable packaging configuration currently exists; `run_gui.bat` creates/uses `.venv` and runs `gui.py`. A Qt decision therefore also requires an explicit Windows distribution/install plan, not just adding `PySide6` to requirements.

## Proposed UI and interaction model

### Recipe Editor tab

Keep the existing plot/analysis workflow as a separate tab. Rename the recipe tab to make its pre-run role explicit, for example **Recipe Editor (pre-run)**. Use a compact action/status strip for Open Workbook, Open in Excel, Export JSON Payload, output location, dirty state, and validation feedback.

Below the strip, use a resizable top row:

- **Left: Recipe metadata.** Username, a visibly taller multiline experimental description, wait time, EDR, and applicable identifiers (DID/SID/EID/PID).
- **Right: Valve metadata.** One aligned set of valve number, name, and temperature fields, including the chamber row; retain the workbook's column associations.

Use a resizable lower row:

- **Bottom left: one combined “Run Timeline & Sequence Details” panel.** Show the entire planned run as one continuous horizontal bar with one block per sequence and widths proportional to validated sequence runtime. Overlay a draggable playhead; clicks on blocks and keyboard navigation select sequences. Display elapsed planned time, sequence, and the cycle within that sequence. Under the bar, show only one representative cycle for the selected sequence, with its ordered valve/phase operations. Include a compact, non-editable phase-duration summary with sequence total first, then per-cycle duration, aggregate sequence duration, and fraction of that sequence.
- **Bottom right: the only editable timing table.** Display the workbook A:J timing area, including its sequence-notes column, with comfortable row height, a vertical scrollbar, and no duplicate editable timing table elsewhere. Filter or scroll the selected sequence's rows into view and highlight them. Phase summaries and timeline labels are read-only visualizations, not another table.

Use weighted `ttk.Panedwindow` splitters with minimum pane sizes and sensible initial proportions. Provide a compact layout at smaller window sizes rather than allowing fixed-width controls to push the timeline or table off-screen. Keep file actions and validation feedback visible without dedicating a large permanent area to the current payload preview; offer a collapsible or secondary JSON preview if users need it.

### Selection, editing, and recalculation

Keep UI state distinct from recipe data:

- A recipe document owns the source path, loaded values, editable in-memory draft, validation results, and output path.
- A pure timing result owns validated sequences, per-cycle/per-sequence durations, phase summaries, cumulative sequence boundaries, and total planned time.
- View state owns the selected sequence and elapsed-time playhead. Scrubbing changes only view state; it never edits timing cells.

On a valid edit, recompute the timing result once and redraw the timeline, selected-sequence cycle view, and summary from that same result. Preserve the existing converter as the payload boundary or add a thin adapter around it; do not make widgets responsible for JSON formatting. Keep Save/Export explicit: export the edited draft through the existing payload schema to a JSON path, and never write changes back into the source workbook. Show the selected workbook and output JSON paths so file ownership is obvious.

For table editing, support single-cell edit, rectangular tab-delimited clipboard paste, multi-row selection, row insertion/deletion, and undo/redo for editor changes. These are bounded editing conveniences, not an Excel formula engine. Do not interpret pasted formula strings as formulas. Validate an edit before using it in timing calculations; keep invalid draft text visible, identify the affected cells, block export until resolved, and clearly indicate when a preview is stale. Do not silently replace invalid values with zero.

### Planned timing contract and edge cases

Pending controller confirmation, the repository's current assumption can be expressed as:

```text
for each timing row in source order:
    positive cycle count starts a sequence
    blank/zero cycle count continues the current sequence
    each valve row contributes the seven timing slots in their approved order
per_cycle_seconds = sum(approved sequential operation durations in that sequence)
sequence_seconds = cycles * per_cycle_seconds
sequence_start = sum(previous sequence_seconds)
run_seconds = sum(sequence_seconds)
```

For a selected sequence, aggregate phase time is the per-cycle time for that phase identity multiplied by the sequence cycle count; its fraction is aggregate phase time divided by total sequence time. Group repeated valve/phase identities deliberately and preserve source row order for the representative cycle. `WaitTime` should initially be displayed separately as a pre-run delay, not included in the sequence bar, because the current converter includes it in `EndTime` but not `ProcessTimeHr`; confirm this with the owner before release.

The formula above is a description of current repository assumptions, not a verified statement about LabVIEW execution. Confirm whether operations are sequential or can overlap and reconcile the workbook headers, converter columns, header-editor labels, and `PHASE_TYPES`. Separate a stable timing-slot identity from its approved display label so a labeling correction cannot reorder or rewrite recipe data. Keep post-run `shift` out of this planned-time model.

Validation and display rules:

- A first usable timing row must start a sequence with a positive integer cycle count. In the existing file convention, blank/zero cycle cells continue a sequence; zero does not create an independent zero-cycle sequence. A continuation before any sequence is an error. Negative or fractional cycle counts are invalid.
- Require a valid valve number on each populated timing row and ensure metadata covers used valves. Require finite, nonnegative timing values; zero phases are valid and omitted from operation visuals. Preserve blank/zero normalization only where the existing converter contract requires it.
- An all-zero-duration sequence has zero proportional width and an undefined phase fraction. Keep it accessible by sequence selection and show a clear warning; do not inflate its width in a way that distorts other runtime proportions.
- Empty recipe, empty phases, one-row sequences, very long recipes, and unequal sequence durations must be supported. Use elapsed seconds for model boundaries, and derive canvas coordinates from normalized total runtime rather than creating one widget per nominal cycle.
- Use half-open sequence intervals `[start, end)` so an exact boundary selects the following nonzero sequence; clamp the final endpoint to the final sequence. If an edit changes boundaries while the playhead is stationary, retain elapsed seconds and resolve the selected sequence again, clamping only if the new run is shorter.
- Label this visualization **planned** timing. Measured run time comes from logged `TimeElapsed`/`CurrentCycle` records and belongs to post-run analysis; do not blend it with the recipe estimate.

## Safe post-run header correction workflow

Add a separately named entry point in the analysis tab, such as **Correct recorded run header...**, and present the selected run file and original header as immutable context. Reuse metadata and timing-table widgets where useful, but do not call the pre-run recipe export path or silently load the current recipe as the actual run.

Recommended default:

1. Save a distinct correction sidecar, not the selected raw/condensed input. Include the source path and a content fingerprint, the original and corrected header payloads, correction timestamp, and an operator-supplied reason. Do not add these provenance fields to the LabVIEW header payload.
2. Let the user explicitly select whether analysis should use the original or corrected header. Pass the selected header model to phase mapping and ensure any derived condensed output carries the selected header. Keep the original raw file unchanged and link derived outputs to the correction sidecar.
3. Keep header-text export as a separate, explicit output. Do not rename raw, condensed, or text artifacts just because a corrected username changes.
4. If the lab requires in-place correction for an established workflow, make it a separate, explicit action with a confirmation, verified backup, atomic temp-file replacement, and a clear audit trail. Do not make it the default Save button.

This needs a small, explicit processing adapter: `ReactorPipeline` currently receives `seq_dict` at construction, but `condense_log()` copies the embedded source header and `gui.py` currently rewrites the selected input to apply a correction. The adapter should accept a header override for derived processing/output, without mutating the source. Never silently process a condensed file in place when a correction sidecar is selected; show the derived output path and preserve the source artifact.

## Staged implementation plan

### Stage 1 — Characterize timing and protect existing contracts

**Affected files:** new `tests/` cases and a pure timing-model module (proposed `recipe_timing.py`); adapters in `convert_to_json.py` and, only if calculations are proven equivalent, `sequence_utils.py`.

**Dependencies:** use the checked-in workbook/payload fixtures and obtain controller slot-order guidance. No new runtime package is required; use standard-library `unittest`.

**Deliverables:** documented slot mapping; a single validated timing result for the editor and conversion time estimate; baseline tests for existing payload and phase-bin behavior. Do not change JSON keys, file naming, slot ordering, or scientific processing in this stage.

**Acceptance criteria:**

- `Example recipe sheet.csv` and the DID000141 workbook produce the existing payload structure and timing rows; normalize time-dependent `EndTime` values for comparisons.
- The new model matches existing `ProcessTimeHr` and sequence/phase calculations for compatible fixtures, with a specific test demonstrating the behavior of different cycle counts and durations per sequence.
- The controller phase-slot mapping and overlap assumption are approved or visibly marked as unresolved; the UI must not claim verified durations while unresolved.
- Invalid values fail visibly; blanks, continuation rows, zero durations, and legacy sheets retain documented behavior.

**Rollback:** keep the existing converter and sequence helpers callable until characterization passes. Revert only the adapter to the current calculation if any golden output changes unexpectedly; do not alter input fixtures.

### Stage 2 — Minimal functional Recipe Editor

**Affected files:** `gui.py`; new recipe view/model modules (for example `recipe_editor.py` and `recipe_timing.py`); existing `convert_to_json.py`; new focused tests. No new runtime dependency is expected.

**Dependencies:** Stage 1 characterization and a decision on timing labels/semantics; the current converter remains the export compatibility boundary.

**Deliverables:** target split layout, responsive splitters, metadata and valve editing, one timing table, validation, JSON preview/export, and synchronized planned timeline, representative cycle, and compact phase summary.

**Acceptance criteria:**

- Exactly one editable timing table is rendered. It includes the source timing columns and sequence notes, supports bounded clipboard paste, row insertion/deletion, and undo/redo.
- Editing a valid cell updates per-cycle and sequence totals, overall run length, proportional block widths, phase summary, and sequence selection without changing the source workbook.
- Dragging, clicking, and keyboard navigation select the same sequence at tested boundaries; scrubbing does not change recipe data.
- Unequal sequence durations create visibly unequal blocks in the mathematically correct ratio. Zero-duration sequences remain accessible without distorting nonzero blocks.
- Exported JSON matches existing naming, normalization, metadata encoding, and controller-facing schema; the selected workbook remains unchanged.
- The layout remains usable at the current app minimum size and at a narrower window, with both lower panes resizable.

**Rollback:** retain the existing “Convert Recipe Sheet” tab behind a feature branch/toggle during rollout. Because export continues to use the existing converter contract, switching back to the old tab must still produce the same payload.

### Stage 3 — Separate and make header correction safe

**Affected files:** `gui.py`, `header_editor.py`, `header_text.py`, `data_parser.py`, `pipeline.py`, plus correction/processing tests.

**Dependencies:** Stage 1 file-format characterization and agreement on sidecar-by-default correction; no new runtime package is required.

**Deliverables:** distinct correction entry point and labels; sidecar persistence/provenance; explicit original-versus-corrected analysis selection; derived output header override; optional guarded legacy in-place action only if approved.

**Acceptance criteria:**

- Recipe editing never writes a run header. Header correction never writes the recipe workbook or recipe payload.
- Choosing sidecar correction leaves source bytes unchanged. The selected correction is reflected in the derived condensed header and phase mapping; the original header remains recoverable and is identified in provenance.
- Errors during correction save leave the source and previous correction artifact intact and are shown to the user.
- Existing header text comparison remains available and does not implicitly modify either file.
- For any explicitly retained in-place action, the backup is verified before replacement, replacement is atomic, and the UI names every file that will change.

**Rollback:** preserve legacy header comparison and editor entry points until the sidecar flow passes the safety suite. Do not silently fall back to in-place writes if sidecar persistence or override processing fails.

### Stage 4 — Visual polish and scale validation

**Affected files:** recipe view/theme modules and directly related documentation, including the stale sections in `WHITEPAPER.md`.

**Dependencies:** the Stage 2 interaction model is stable; Stage 3 safety behavior is included before release if correction is part of the shipped workflow. Keep this stage presentation-only unless profiling demonstrates a concrete performance need.

**Deliverables:** dark theme with restrained purple/blue accents, readable dense tables, keyboard/focus states, consistent validation messages, high-DPI/layout checks, performance improvements justified by profiling, and updated documentation.

**Acceptance criteria:** no scientific payload/output differences from the Stage 1 baselines; no UI freezes during large-file analysis; responsive progress/error reporting; recipe table performance is acceptable for the largest representative workbook; theme remains legible at common display scaling.

**Rollback:** theme and optional polish remain presentation-only and can be reverted independently of the editor model and processing adapters.

## Testing and regression checklist

There is no current test suite or test runner configuration. Add focused standard-library `unittest` coverage first, avoiding a runtime dependency for testing unless the project later chooses a test framework.

### Timing model and editor

- Parse the new and old workbook templates, example CSVs, and DID000141 workbook; test expected metadata, valve assignments, sequence notes, and payload rows.
- Test equal and unequal sequence cycle counts, unequal runtimes, fractional-second timings, blank/zero continuation rows, malformed first rows, empty phases, all-zero durations, and negative/non-finite values.
- Verify total run time, per-cycle time, per-phase aggregate time, phase fractions, sequence cumulative boundaries, and proportional timeline widths against hand-calculated fixtures after slot semantics are approved.
- Test playhead at zero, inside each sequence, exactly at every boundary, final endpoint, and after edits that move boundaries. Test mouse dragging, block click, and keyboard navigation against a single selection state.
- Test rectangular TSV paste, clipping at table bounds, multi-row selection, insertion/deletion, undo/redo, and export-blocking validation errors.
- Confirm selection, timeline, representative-cycle view, and timing table stay synchronized and that only one editable timing table is present.
- Compare exported payloads with `Example recipe sheet_payload.json` and `DID000141/260819 TDIC & DAMDPA high dose purge testing recipe sheet(1)_payload.json`, normalizing dynamic `EndTime`.
- Verify source workbook bytes are unchanged after editing and export. Test formulas/cached values in Excel-created workbooks; do not treat formulas as portable GUI edits.

### Processing and outputs

- Use the DID000141 workbook and corresponding condensed run as representative inputs; retain the current generated PNG, GIF, exposure CSV, condensed JSON, and cycle summaries as behavior references where stable.
- Include at least one synthetic fixture with different cycle counts and durations by sequence; the repository's existing sample has a small number of cycles and must not be the only test of uneven sequences.
- Compare phase labels, cycle-to-sequence mapping, exposure CSV columns/values, plot data segments, and animation frame count before and after the UI work.
- Verify planned timing is distinct from measured `TimeElapsed`; no recipe timeline operation should mutate pressure, phase labels, or the source recipe as a side effect.
- Exercise raw input, condensed input, “write condensed” enabled/disabled, optional temperature zones, optional iSE input, and error/permission paths. Assert the exact output path and whether the selected file is changed.

### Header correction safety

- Test raw-header and header-text parsing, comparison, and correction sidecar export with existing sample headers.
- Hash the selected source before and after sidecar save, correction cancellation, analysis using the original header, and analysis using the corrected header; source hashes must remain unchanged.
- Verify the derived condensed header/phase labeling uses the selected header and the sidecar records the source fingerprint and correction reason.
- Simulate output permission failures and interrupted writes; no success-shaped fallback, partial correction, or loss of the previous artifact is acceptable.
- If an in-place compatibility action is approved, test backup verification, atomic replacement, restore, artifact rename prompts, and preserving `startTime`/other raw fields.

## Risks, open questions, and approval gates

| Topic | Evidence / risk | Decision needed |
|---|---|---|
| Timing-slot semantics | Workbook labels, `HeaderEditorDialog.TIMING_COLUMNS`, and `sequence_utils.PHASE_TYPES` disagree on the first timing slots. Current code treats all nonzero slots as a serial cumulative timeline; this does not verify controller execution or overlap. | Confirm slot mapping, phase names, and whether phases can overlap before publishing calculated durations. |
| Existing workbook time formula | Current template uses `M6 = SUM(C15:I26)*A15` and `M8 = NOW()+M6/3600/24`; converter computes per-sequence cycle totals instead. The sheet formula multiplies a sum across rows by the first sequence's cycle count, so unequal sequence counts need explicit verification. | Identify the intended formula behavior for unequal sequence counts and designate a tested oracle. |
| Wait time | `WaitTime` affects estimated `EndTime`, but not `ProcessTimeHr`; it is not represented in `valveSequence`. | Confirm that the timeline shows it separately before the first sequence rather than including it in sequence widths. |
| Correction policy | Current header Save and “Use Header JSON” rewrite the selected NDJSON in place; raw/condensed input identity affects whether processing also writes in place. | Approve sidecar-by-default correction and explicit analysis selection. Decide whether a guarded in-place compatibility action is still required. |
| Representative raw input | The checked-in DID000141 run is condensed, so the repository does not include a matching uncondensed raw run for a full raw-to-corrected-header golden test. | Supply/approve a safe representative raw fixture or test raw parsing with a small synthetic fixture. |
| Excel behavior | Excel remains the authoring environment by requirement. The workbook contains helper formulas; the GUI must not claim lossless Excel round-trip and must handle formula cached values correctly. | Confirm the expected editing/export workflow and whether modified drafts need a separate persistent draft format in addition to JSON payload export. |
| UI framework and distribution | Tkinter is the only current GUI framework; launch scripts use a local virtual environment and no installer/build configuration exists. | Retain Tkinter for MVP (recommended). Approve a separate Qt/distribution spike only if packaging or UI requirements justify it. |
| Visual assets | No mockup image files were present in the repository tree. | If there is a separate mockup, provide it before visual polish; otherwise use the textual target layout and theme requirements. |

## Release recommendation

Proceed with a Tkinter MVP only after approving the timing-slot mapping and corrected-header save policy. Keep the existing processing algorithms and output schema behind thin adapters, use the Excel workbook as the source of truth, and deliver the new editor as a separate pre-run workflow. Do not release proportional timeline numbers as scientifically authoritative while execution order/overlap is unresolved, and do not ship a generic header “Save” action that silently overwrites the selected run file.
