# Reactor Pressure Data Analyzer — PySide6 Refactor Plan

## Cutover status

The Qt application is the production interface: `reactor_plotter.py` starts
`reactor_ui.app.main()`, `run_gui.bat` uses that entry point, and the temporary
developer launcher and legacy Tk UI have been removed. The `.venv`-based
distribution remains in use; an installer is outside this migration.

The cutover comparison used identical synthetic runs with temperature telemetry
and iSE input. Tk and Qt processing options, condensed records, exposure and
thickness CSVs, and plot/summary counts matched. The Qt lifecycle regression
and 40 consecutive header-suite stress runs passed. A 600-row recipe covering
60 million nominal cycles remained compact and responsive. The interface was
reviewed at 100%, 150%, and 200% scaling; narrow layouts stack panels and retain
scroll access. See the [README](../README.md) for launch and test commands.

The remainder preserves the original planning analysis and its historical
pre-migration observations. The owner decisions and safety notes near the end
supersede earlier recommendations and open questions.

## Executive recommendation

Migrate the GUI layer to **PySide6 with Qt Widgets**. The requested product is no longer just a re-layout of two Tkinter tabs: the supplied designs call for persistent navigation, a high-density editor, resizable panels, a custom proportional timeline with a draggable playhead, synchronized selection, clipboard editing, undo/redo, and a consistent dark theme. Qt's model/view table, `QSplitter`, signals/slots, `QUndoStack`, clipboard support, and custom painting are a better fit for that interaction model than expanding the current widget-per-cell Tkinter UI.

Keep the scientific and file-processing modules as the stable backend. Build Qt pages, models, and adapters around `convert_to_json.py`, `sequence_utils.py`, `pipeline.py`, `data_parser.py`, `plot_utils.py`, and `ise_utils.py`. Do not port their algorithms for visual reasons. One small pure timing model is justified to make recipe duration calculations authoritative across the editor and conversion path, but it must first be reconciled with controller semantics.

The supplied images are accessible and have been reviewed:

- [Reactor Recipe Editor Dashboard.png](../prompts/Reactor%20Recipe%20Editor%20Dashboard.png)
- [Purple Reactor Analysis Dashboard.png](../prompts/Purple%20Reactor%20Analysis%20Dashboard.png)

The existing [Tkinter-oriented plan](reactor-pressure-analyzer-gui-refactor-plan.md) recommended retaining Tkinter. This new plan supersedes that framework recommendation based on the specific visual and interaction requirements in the supplied designs; it does not replace or edit the earlier document.

**Real costs:** add PySide6 to the Python environment, learn/package Qt's native libraries and platform plugins, port the entire visible GUI and modal dialogs, migrate background-task signaling, and validate Matplotlib embedding. No installer/build pipeline currently exists, so Windows distribution must be decided rather than assumed. Do not introduce QML: Qt Widgets and custom-painted widgets are sufficient, and QML would add another UI technology without a demonstrated need.

| GUI option | Concrete fit for this repository | Decision |
|---|---|---|
| PySide6 / Qt Widgets | `QTableView`/delegates, `QUndoStack`, `QSplitter`, signals/slots, and custom painting directly support the required editor and timeline. QSS makes the supplied shell/theme practical. The cost is a full GUI port, a new runtime dependency, Qt plugin packaging, and Qt-specific tests. | Preferred for the requested product and visual fidelity. |
| Keep Tkinter | Avoids the migration and dependency cost, and preserves the current launch path. But the current `ttk.Notebook`, callback-heavy `gui.py`, and per-cell Entry construction in `HeaderEditorDialog` would need substantial custom code for this design's model/view editing, undo, consistent dark styling, and page navigation. | Not preferred for this UX-led refactor; retain only as a temporary development-branch baseline and rollback. |
| QML | Could support animated/custom interfaces, but the current application is a desktop data-entry/analysis tool and has no declarative-UI requirement. It would add a second Qt UI paradigm. | Do not use absent a specific future requirement. |

## Repository findings (pre-migration baseline)

### Entry points, UI, and dependencies

- The former `reactor_plotter.py` imported `ReactorApp` from `gui.py` and called `mainloop()`.
- `ReactorApp._build_ui()` currently creates a `ttk.Notebook` with **Reactor Plots** and **Convert Recipe Sheet** tabs. `_build_plot_tab()` assembles the processing inputs, options, progress, logs, and output controls; `_build_recipe_tab()` loads a recipe, shows validation and JSON preview, and exports a payload. The current recipe tab is not an editor.
- `gui.py` is also the controller: it owns application state, file dialogs, error reporting, configuration persistence, conversion callbacks, and pipeline event handlers. Long analysis tasks use `threading.Thread`; `_log()` and `_set_progress()` marshal UI work through `after()`.
- The former `HeaderEditorDialog` in `header_editor.py` was a modal Tk `Toplevel` with metadata fields, valve metadata, and a manually constructed timing table. It was the post-run header editor, not the pre-run recipe editor.
- [requirements.txt](../requirements.txt) lists Matplotlib, NumPy, pandas, Pillow, and openpyxl; it has no GUI framework dependency because Tkinter is supplied by the Python installation. [run_gui.bat](../run_gui.bat) currently launches `gui.py`; [setup.bat](../setup.bat) tells users to run `reactor_plotter.py`. Make one Qt entry point authoritative at cutover and align both scripts.
- [config_default.json](../config_default.json) stores processing preferences, per-reactor valve names, and reactor types. `ReactorApp._load_settings_state()` and `_save_settings_state()` manage them; there is no current Settings or Help page.
- `gui.py` selects Matplotlib's Agg backend and embeds figures with `FigureCanvasTkAgg`. The Qt UI must replace that widget integration with QtAgg and prove that headless/batch file generation still behaves as before.

### Existing backend boundaries and behavior to preserve

- [convert_to_json.py](../convert_to_json.py): `load_table()` reads CSV and Excel into a DataFrame; `validate_recipe_sheet()` checks newer recipe metadata/valve coverage while allowing some legacy formats; `extract_timing_table()` normalizes recipe rows; `build_payload()` and `save_payload()` produce the existing controller-facing JSON. `build_payload()` computes `ProcessTimeHr` and `EndTime` through `_estimate_process_times()`.
- [sequence_utils.py](../sequence_utils.py): `convert_sequence()` parses header `valveSequence`; `compute_phase_bins()` builds phase boundaries; `make_cycle_seq_map()` associates measured global cycles with sequences; `assign_phase()` finds a phase for measured time.
- [data_parser.py](../data_parser.py): `read_header()`, `stream_pressure()`, and `condense_log()` parse and condense NDJSON. It also loads temperature/service logs, restores a missing condensed-header `startTime`, and writes cycle summaries.
- [pipeline.py](../pipeline.py): `ReactorPipeline` orchestrates condensation, phase labeling, optional temperature and iSE attachment, cycle preview, plots, exposure calculations, animation, and cycle summaries. UI code can call it through a worker/controller adapter.
- [plot_utils.py](../plot_utils.py): `build_segments()`, `draw_cycle_figure()`, exposure calculation/CSV output, and animation generation. [ise_utils.py](../ise_utils.py): iSE parsing and cycle alignment.
- [header_text.py](../header_text.py): parses/serializes header text, compares sequence payloads, and computes related artifact paths.
- [WHITEPAPER.md](../WHITEPAPER.md) and [PROCESSING_WORKFLOW_REVIEW.md](../PROCESSING_WORKFLOW_REVIEW.md) are the available project documentation. The whitepaper's claim that iSE attachment is not implemented is stale; current `pipeline.py` has `attach_ise()` and cycle-summary support.

The repository includes old/current workbook templates, CSV recipes and payloads, and a DID000141 workbook with a **condensed** run and generated outputs. No automated test suite or test configuration is tracked. There is no separate installer/build configuration. The mockup PNGs are the only design references found; no Figma project or additional mockup source is available.

### File mutation and header workflow

Recipe conversion loads the Excel/CSV source and writes a `_payload.json`; it does not save to the workbook. Keep that source-ownership rule in the Qt editor.

The current post-run header editor is a different workflow. `gui.py::_edit_header()` may rename associated artifacts, calls `_rewrite_header_payload()`, and can also update a header text file. `_rewrite_header_payload()` reads the entire NDJSON file and rewrites the selected file directly with the new first-line payload. `gui.py::_use_header_text_as_raw_header()` uses that same helper. This is a source mutation and the current write is not atomic.

`ReactorPipeline.condense()` writes a sibling `_condensed.json` for raw input when persistence is enabled, but uses the selected path itself when the input is already condensed. Later pipeline stages can therefore rewrite an already-condensed selected input. The Qt UI must show the exact source and working/output paths and must not imply that the selected file is immutable. A broad correction-sidecar redesign is a follow-on phase, not a prerequisite for the main GUI migration.

## Mockup-to-widget mapping

Both images are 1670 × 940 screenshots. Their proportions are a visual starting point, not fixed pixel requirements. Derive layout from Qt layouts, font metrics, and screen DPI; do not hard-code screenshot pixel coordinates.

### Shared application shell

| Mockup element | Qt implementation |
|---|---|
| Dark left navigation rail, about 180 px in the reference | Fixed-width/collapsible `QFrame` with checkable `QToolButton`s and icons; retain a text label at normal width and an accessible name when collapsed. |
| Analyze, Recipe Editor, Plots & Animation, Settings, Help navigation | `QStackedWidget` pages switched by sidebar actions. Make Analyze, Recipe Editor, and Plots & Animation functional as their migration stages land. Settings should surface the existing persisted preferences when ready; Help can link to maintained project documentation. Do not ship fake active pages or make Settings/Help a prerequisite for the editor. |
| Dark navy/purple background, outlined cards, bright violet primary actions | Central `QPalette` plus a small Qt Style Sheet token layer for backgrounds, card borders, focus, selection, buttons, and validation. Start with approximate colors sampled from the supplied images, then compare actual screenshots. Use a Segoe UI/system font stack, consistent spacing, and visible keyboard focus. |
| Top application title and page heading/subtitle | `QMainWindow` title bar plus page header widget, preserving the instrument/application identity and contextual title. |

### Recipe Editor page

The recipe mockup has a compact action row, side-by-side metadata cards, then a lower two-pane work area. In the 1670 × 940 reference the left rail takes roughly 11% of width; the metadata row is roughly one quarter of content height, and the lower timeline/table region takes most of the remaining space.

- Use a top action bar for recipe identity, **New**, **Open**, and clearly named export actions. Avoid duplicating Save/Save As controls in both the toolbar and footer.
- Use a vertical `QSplitter` for the metadata row and lower work area. In the metadata row, place Recipe Metadata and Valve Metadata in a horizontal `QSplitter`; give the description a real multiline `QPlainTextEdit`/`QTextEdit` with several visible lines and optional growth, not a one-line field.
- In the lower work area, use a horizontal `QSplitter`, initially near 50/50. The left pane is one combined Run Timeline & Sequence Details card; the right pane is exactly one `QTableView` with a tall viewport and vertical scrollbar.
- Keep validation, dirty/stale status, and recipe/output paths visible in a compact footer. Give the timeline enough height to show the full-run bar, representative-cycle detail, and phase summary at once.
- Use an initial window around 1440 × 900 logical pixels and a practical minimum around 1180 × 720, with Qt high-DPI scaling and a collapsible sidebar. These are starting targets; verify against actual supported displays and preserve usability at smaller windows with scrolling/compact layouts.

### Analyze and Plots & Animation pages

The analysis mockup uses the same shell and card styling. Map its left column to input files, temperature data, valve-name mapping, output directory, pipeline stages, Run Analysis, and a bounded log viewer. Map the right column to plot/analysis options and valve metadata. Use `QScrollArea` where stacked controls exceed the available height; collapse optional sections rather than squeezing inputs.

The mockup says **Value Metadata** and shows **Value #**; repository concepts and the current UI use valve metadata and valve number. Treat that as a mockup typo, and label it **Valve Metadata** / **Valve #**. The mockup also places leak-rate reduction, animation FPS, and thickness blank rows beside recipe metadata; current `ProcessingOptions` treats these as analysis/output options, not controller recipe fields. Keep them on the Analyze or Plots & Animation page and do not put them into the recipe payload.

Plots & Animation should host the existing single-cycle preview and generated-output workflow, preserving the cycle selector, Matplotlib toolbar/navigation where useful, and output-directory actions. The new page arrangement changes navigation, not scientific outputs.

### Visual discrepancies and precedence

Written requirements take precedence over illustrative mockup content:

1. The recipe mockup's **Per-Sequence / Full Run** toggle must not hide or replace the required continuous full-run bar. Default to the entire run. A separate sequence-focused view is optional only if it preserves the full-run overview.
2. The mockup timing table appears expanded by cycle and has a “Cycles per Sequence” spinner. The workbook stores source rows with a cycle count on a sequence's first row and blank/zero continuation rows. Use one editable row per source timing row; show sequence context as derived/read-only, and do not expand every repeated cycle into duplicate editable rows.
3. The mockup phase labels, valve names, cycle counts, durations, and colors are illustrative. In particular, do not copy the displayed phase mapping into code until the workbook/header/utility mismatch is resolved.
4. The mockup's phase summary is a compact read-only summary, not a second editable timing grid.
5. The recipe mockup's top row includes Wait Time and processing-specific controls. Wait Time is recipe metadata and currently also feeds `ProcessingOptions.wait_time` for pressure trimming; keep it in recipe metadata while making its analysis effect explicit, rather than silently treating it as an unrelated plot option. Keep leak-rate reduction, animation FPS, and thickness blank rows with analysis/output controls.

## Proposed Qt architecture

Use a thin presentation layer and preserve the existing processing modules. Suggested initial module tree:

```text
reactor_plotter.py                 # final single application entry point
reactor_ui/
  app.py                            # QApplication, theme, top-level startup
  main_window.py                    # navigation shell and QStackedWidget
  theme.py                          # palette/QSS tokens, reusable card/button styles
  pages/
    recipe_editor_page.py           # recipe metadata, valve metadata, timeline/table layout
    analyze_page.py                 # files, options, pipeline actions, status/log
    plots_page.py                   # preview, plots, animation and output links
  models/
    recipe_document.py              # loaded source, draft, metadata, validation/dirty state
    recipe_table_model.py           # QAbstractTableModel for source recipe rows
    recipe_timing.py                # pure validation and timing calculation
  widgets/
    run_timeline.py                 # painted full-run bar, ruler, playhead, cycle detail
    phase_summary.py                # compact read-only summary
  workers/
    pipeline_worker.py              # Qt worker signals around existing ReactorPipeline
  adapters/
    recipe_conversion.py            # existing converter boundary
    analysis_controller.py          # UI actions -> existing pipeline options/stages
```

Keep the tree compact: do not add a generic service framework or move backend functions just to match this layout. A `header_correction_page.py`/dialog and sidecar service belong to the separately scoped safety phase.

### State and event flow

- `RecipeDocument` owns the source path, loaded DataFrame/metadata, source timing rows, in-memory draft, dirty state, validation messages, and intended export path. It must not write to the source workbook.
- `RecipeTableModel` owns view-facing row/column roles and delegates edits to the document. Use `QAbstractTableModel` and `QStyledItemDelegate` for typed cells; do not create one QWidget per cell.
- A pure timing result (typed sequence/event data plus cumulative boundaries) is recomputed from a validated document snapshot. Both the timeline and phase summary consume this result; widgets do not calculate duration independently.
- Page state owns selected sequence and playhead seconds, separate from recipe data. Signals connect the timeline, table view, and detail panel. Editing a valid cell emits one model change, recalculates the result, and updates all three views.
- Analysis forms build an immutable `ProcessingOptions` snapshot and pass it with the path/header selection to the worker. UI controls are disabled or protected while a pipeline run is active; worker updates return through queued Qt signals.

### Qt and plotting details

- `QMainWindow` holds the navigation rail and central stack. Use nested `QSplitter`s for the required resizable recipe layout; save/restore splitter positions only if it can be done without hiding required content.
- Use a custom-painted `QWidget` for the compact timeline first: draw blocks, ruler, playhead, labels, selection, and hit-test in elapsed-time coordinates. It has no per-cycle widget cost. Move to `QGraphicsView` only if measured sequence counts require zooming/panning beyond a custom widget's practical hit-testing.
- Use Qt's `QFileDialog`, `QMessageBox`, `QProgressBar`, `QPlainTextEdit`, and native keyboard/focus conventions. Limit log blocks to keep memory bounded.
- Use a `QThread` worker or `QThreadPool`/`QRunnable` with a `QObject` signal proxy for long analysis work. Do not touch Qt widgets or models from worker threads. Preserve existing progress and save-retry errors as structured signals; catch exceptions at the worker boundary and show/log their actual messages. Cooperative cancellation is a later addition unless pipeline loops gain cancellation checkpoints; never present a cancel button that cannot stop work.
- Replace `FigureCanvasTkAgg` with `FigureCanvasQTAgg` for interactive Qt previews. Keep PNG/CSV/GIF generation in existing backend helpers and regression-test both interactive embedding and non-interactive output. Avoid setting a Tk or Qt canvas in shared processing modules.
- Qt's automatic DPI scaling helps, but verify high-DPI font metrics, table row height, splitter minimums, and icon sizing on Windows at 100%, 150%, and 200%.

## Timing timeline and authoritative model

### What current code does—and does not prove

`sequence_utils.PHASE_TYPES` is `prepump, dosepump, dosen2, dose, hold, prepurge, purge`. The current workbook labels its seven slots `PrePurge, N2Dose, PumpDose, Dose, Hold, PrePurge, Purge`; `HeaderEditorDialog.TIMING_COLUMNS` uses `Pre-dose Pump, N2 Dose, Pump Dose, Dose, Hold, Pre-Purge, Purge`. This is a real unresolved mapping, not a UI naming choice.

`convert_sequence()` reads a positive cycle count as a new sequence and blank/zero as a continuation row. `compute_phase_bins()` flattens each valve row's seven timing slots in order and accumulates nonzero durations. `_estimate_process_times()` independently sums columns 2–8 for each grouped sequence and multiplies by that sequence's cycle count. These implementations model sequential row/phase durations, but do not prove that the controller schedules every operation serially or that all phases are mutually exclusive.

Also, `compute_phase_bins(shift=...)` adds shift to each nonzero slot for post-run phase labeling. Do not reuse that shift as a planned recipe duration. `WaitTime` is added to the converter's estimated `EndTime` but excluded from `ProcessTimeHr`; display it separately from sequence runtime unless the owner approves another interpretation.

The workbook template formula at `M6` is `SUM(C15:I26)*A15`, with `M8` based on that value. It applies the first sequence's cycle-count cell to the summed timing range. The converter instead groups and multiplies per sequence. Compare the intended Excel behavior and converter outputs for unequal cycle counts; neither should be declared the oracle without confirmation.

### Proposed calculations after slot semantics are confirmed

Represent each approved row as ordered timing-slot events. For a sequence:

```text
cycle_duration = sum(event durations for one source cycle)
sequence_duration = cycle_count * cycle_duration
sequence_start = cumulative sum of earlier sequence durations
sequence_end = sequence_start + sequence_duration
run_duration = sum(sequence_duration for all sequences)
block_width_px = timeline_width_px * sequence_duration / run_duration
```

Phase summary aggregates durations per approved phase identity within one cycle, multiplies by the sequence cycle count, and divides by sequence duration for the fraction. Show total sequence time first. Keep sequence colors distinct from phase colors: e.g. a restrained sequence palette for the full-run overview and a separate phase-identity palette for cycle detail. Do not infer identity or meaning from colors in the screenshots.

### Interactions and edge cases

- Draw a single full-run bar with one block per sequence and a readable elapsed-time ruler. Mark sequence start/end and duration in tooltips; give the selected sequence a high-contrast outline. Keep labels minimal when blocks are narrow.
- Map playhead x-coordinate to elapsed seconds and resolve the containing sequence; clicking a block selects its interior, dragging updates continuously, keyboard left/right moves among sequence boundaries, and a keyboard-accessible time control is available for precise navigation.
- Use half-open intervals `[start, end)` so an exact internal boundary selects the following nonzero sequence; clamp the final endpoint to the last sequence. Recompute selection when valid edits move boundaries; preserve elapsed time and clamp only if total duration shrinks below it.
- The selected sequence drives the representative one-cycle operation view, summary, and scroll/selection position in the single editable table. Do not draw repeated cycles; show cycle index as `floor(sequence_elapsed / cycle_duration) + 1` when duration is positive.
- Empty recipe: show an empty state and block export. Empty/all-zero phases: preserve the sequence and row selection, report zero runtime, and show undefined fraction as “—”. Do not assign artificial width that falsifies runtime proportions.
- Many sequences: keep calculation/rendering proportional to sequence and phase count, not total nominal cycles. Provide tooltips and keyboard selection for subpixel blocks; if zoom is needed, add a scroll/zoom detail view without replacing the full-run overview.
- Very long runtime: retain floating-point seconds as the model unit, format the ruler in seconds/minutes/hours based on span, and avoid integer overflow or per-cycle expansion.
- Invalid values: keep invalid draft text visible, identify the cell, mark preview stale, and disable export until corrected. Reject non-finite/negative timing and invalid cycle counts rather than silently coercing them to zero.
- Keep this labeled **planned timing**. Measured timing remains from NDJSON `TimeElapsed`/`CurrentCycle`, outside the recipe timeline.

The slot order, possible overlap, and duration formula are a **release blocker for numeric claims**, but not for building the Qt shell, loading/editing source rows, or prototyping the timeline with a clearly labeled provisional estimate.

## Qt table, recipe editing, and file ownership

### One editable table

Use one `QTableView` backed by the source-row `QAbstractTableModel`. A practical visible column set is row number and derived sequence context (read-only), followed by the source workbook columns: `Cycles`, `Valve`, seven timing slots, and `Sequence Notes`. The cycle count remains on the first row of each sequence; continuation rows keep their existing blank/zero convention. Do not expand one source row into a row for every repeated cycle, and do not add a second editable timing grid.

Use delegates for cycle counts, valve selection/number, and timing numeric input. Preserve source order—do not sort the model or proxy model in a way that changes sequence grouping. Use `scrollTo()`/row selection to synchronize sequence changes from the timeline. A read-only phase summary can be drawn as compact labels/bars; it is not an editable table.

### Clipboard, row operations, validation, undo

- Copy/paste a rectangular TSV selection through `QClipboard`, including multi-cell and multi-row paste. Reject or report incompatible shapes explicitly; do not interpret formulas.
- Support row insertion/deletion within the draft, with validation for sequence-start/continuation rules and valve metadata. Group a whole paste/row operation as one undoable command.
- Use `QUndoStack` with commands for cell edit, rectangular paste, row insertion, and row deletion. Dirty state follows undo/redo back to the saved/exported snapshot.
- Validate cycles as positive integers at sequence starts; blank/zero as continuation only; valve identifiers as valid and declared; timing as finite nonnegative seconds; and required metadata through the existing validator where compatible.
- Keep validation errors per-cell and at document level. Disable export while blocking errors exist; if input changes after preview, show “Preview is stale” until recalculated.

### Open, draft, and export semantics

- **Open** imports `.xlsx`, `.xls`, or `.csv` through the existing `load_table()` path. The workbook/CSV remains the user's authoring source and is treated read-only by the GUI.
- **New** starts an in-memory draft. Edit its metadata and timing cells directly; use rectangular Ctrl+C/Ctrl+V, row controls, and Undo/Redo. Invalid cells remain visible and block export. Unsaved changes are confirmed before New, Open, or closing.
- The first implementation keeps edits in an in-memory draft. Label the primary action **Export Payload…**, not ambiguous “Save Recipe”: call the existing conversion/validation boundary and write the established controller-facing JSON schema to a user-selected path. “Export As…” chooses another payload path. Never write the draft back into Excel.
- Do not imply that exported controller JSON preserves Excel formulas, formatting, comments, or lossless round-trip editing. If persistent GUI drafts are required, add a distinct versioned draft envelope and provenance in a later decision; do not confuse it with the LabVIEW payload.
- Preserve `username`, `experimentalDetails`, `SequenceNotes`, normalized recipe rows, and current output naming behavior unless golden tests demonstrate a bug that the owner approves changing.

## Staged implementation plan

Effort estimates are rough engineering ranges for one developer, excluding owner review delays and Windows packaging decisions.

### Stage 0 — Baseline and Qt migration spike (about 0.5–1.5 days)

**Files:** new standard-library tests; a small standalone Qt startup/Matplotlib experiment; no production backend edits.

**Dependencies:** choose a supported Python/PySide6 combination; no controller timing decision required to start the UI spike.

**Deliverables:** capture payload and processing baselines; confirm PySide6 installation/startup in the existing virtual-environment workflow; verify `QApplication`, QtAgg preview, and a `QThread` worker; record how the two supplied screenshots will be visually compared.

**Acceptance:** Qt launches on the target Windows Python; Tkinter app continues to launch; opening a Qt window does not alter pipeline outputs; worker progress/errors reach the UI through signals; a Matplotlib figure can be embedded and batch outputs still save.

**Rollback:** discard the isolated Qt spike and keep the current entry points. No data migration or backend changes.

### Stage 1 — First-session PySide6 vertical slice (about 1–2 days)

**Files:** new `reactor_ui/` shell and Recipe Editor page; a temporary developer launcher; `requirements.txt` updated only when the spike passes. Keep `reactor_plotter.py` and `gui.py` as the working Tk baseline during development.

**Dependencies:** Stage 0 succeeds. Use repository sample recipes; no timing-semantics sign-off is needed if the estimate is visibly marked provisional.

**Deliverables:** attractive dark Qt shell with sidebar, page header/action bar, responsive metadata/valve cards, combined lower timeline/table layout, actual Open of an existing CSV/XLSX, validation feedback, and Export Payload through existing conversion functions. The first timeline can show the current serial estimate only with a visible “provisional timing model” note.

**Acceptance:** on the supplied 1670 × 940 reference size, the visual hierarchy and panel proportions are credible; metadata and source rows load from a real fixture; table is viewable with vertical scrolling; one source table only; export matches existing payload behavior; no source workbook mutation.

**Rollback:** remove the temporary Qt launcher/dependency change on the feature branch; the Tk launcher remains untouched.

**Short first development session:** target a Qt launch, shared navigation rail, Recipe Editor visual shell, actual sample-file loading, and basic payload export. Defer cross-view scrub synchronization, bulk edits, full analysis migration, installer packaging, and header safety redesign.

### Stage 2 — Timing model and synchronized timeline (about 2–4 days, plus semantics review)

**Files:** new `reactor_ui/models/recipe_timing.py`, `widgets/run_timeline.py`, sequence/editor adapters, focused timing tests.

**Dependencies:** Stage 1; owner/controller confirmation of slot identities, ordering, and overlap for release-quality values. Prototyping may continue with provisional labels.

**Deliverables:** one authoritative timing result, proportional full-run blocks, time ruler and playhead, deterministic boundaries, click/drag/keyboard selection, representative cycle, total-first phase summary, and synchronization to the one table.

**Acceptance:** hand-calculated unequal-duration fixtures have correctly proportional widths; all boundary and zero-duration behavior is deterministic; scrubbing does not change recipe values; an edit moves boundaries and updates every view from one model result; no per-cycle widget creation.

**Rollback:** retain the Qt editor without enabling the unverified numeric timeline; do not modify current post-run `compute_phase_bins()` behavior.

### Stage 3 — Direct editing and validation (about 2–4 days)

**Files:** `recipe_document.py`, `recipe_table_model.py`, delegates, editor page, conversion adapter, Qt model tests.

**Dependencies:** Stage 2 model interface; preserve existing payload builder as the compatibility boundary.

**Deliverables:** typed cell editing, rectangular clipboard operations, row insertion/deletion, selection, `QUndoStack`, draft dirty/stale states, export blocking, and source/output identity.

**Acceptance:** edits recalculate totals/blocks/summary; invalid data is visible and cannot export; undo/redo restores exact draft state; clipboard paste produces expected values and is one undo step; exported JSON remains compatible; Excel source hash is unchanged.

**Rollback:** disable editing and ship the Qt viewer/export path only; the Tk baseline remains available on the development branch until migration cutover.

### Stage 4 — Port analysis and plot workflows (about 4–8 days)

**Files:** new `analyze_page.py`, `plots_page.py`, `pipeline_worker.py`, Qt dialogs/logging, `reactor_plotter.py`, `run_gui.bat`, `setup.bat` launch message; minimal pipeline adapters only where Qt signals or explicit output paths require them.

**Dependencies:** Stages 0–3; PySide6/QtAgg spike proven; scientific baselines available.

**Deliverables:** full Qt navigation and analysis flow: raw/condensed selection, header load/compare, temperature discovery/zone selection, iSE attachment, valve names, output directory, plot options, staged and Run Analysis operations, progress/logging, previews, plots, animations, and CSV/JSON outputs. Port the existing Header Editor as a separate Qt dialog with an explicit warning when Save changes the selected run file; defer a broad sidecar redesign.

**Acceptance:** existing `ReactorPipeline` outputs match baselines; UI remains interactive during long processing; exceptions and retryable save failures are reported; source/working/output paths are accurate for raw and already-condensed inputs; all Qt widgets are updated only on the GUI thread.

**Rollback:** keep the Qt app on the development branch with its temporary launcher and run the existing Tk app for production until output/UX parity passes. Do not maintain a permanent dual-GUI release.

### Stage 5 — Visual/accessibility polish and cutover (about 2–4 days)

**Files:** theme, widgets, Qt pages, docs, `reactor_plotter.py`, `run_gui.bat`, `setup.bat`.

**Dependencies:** analysis parity and full feature checklist from Stage 4.

**Deliverables:** refined QSS/theme tokens, icon consistency, responsive splitter defaults, keyboard/focus/accessibility, high-DPI behavior, long-recipe performance, and one Qt default entry point. Align both Windows scripts and update the whitepaper/workflow documentation.

**Acceptance:** side-by-side visual review against supplied mockups at 100%, 150%, and 200% Windows scaling; no clipped description/table columns at supported window sizes; keyboard-only navigation; no scientific output diffs; one production GUI path and no Tk widgets in the shipped application.

**Rollback:** revert the entry-point/launcher cutover commit or release to the previous Tk revision. Since recipe and run data formats are unchanged, rollback requires no file conversion.

### Stage 6 — Isolated post-run header-correction safety improvement (follow-on, about 2–4 days)

**Files:** Qt header-correction dialog, `header_text.py`, `data_parser.py`, `pipeline.py`, correction/sidecar tests.

**Dependencies:** completed Qt migration; owner decision on sidecar versus explicit in-place correction. This stage must not block Stages 1–5.

**Deliverables:** distinguish pre-run recipe from recorded-run correction; document current in-place behavior; propose sidecar provenance and derived-header override, with explicit file ownership. Do not silently use the recipe editor's export/write flow for corrections.

**Acceptance:** correction cannot silently overwrite raw or condensed source; derived outputs identify the header used; failures are explicit; any retained in-place action is confirmed, backed up, and atomic.

**Rollback:** keep the distinct Qt correction dialog with current behavior clearly labeled and confirmed; revert the safety adapter independently of the recipe editor and Qt shell.

## Regression and UX test plan

The repository has no tracked test suite. Begin with `unittest` for backend contracts and Qt's `QtTest`/offscreen platform for view/model interaction; introduce no test-runner dependency unless the project chooses one.

**Implemented in prompt 01.** Run the suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Golden baselines live in `tests/golden/` (normalized payloads for the example CSV, both workbook templates, and the DID000141 workbook; a full pipeline summary for a temporary copy of the DID000141 condensed run). Regenerate them only for a reviewed, intentional output change with `.\.venv\Scripts\python.exe tests\_baseline.py`. The tracked example payload and DID000141 outputs predate the current converter/pipeline, so the goldens pin current behavior instead. No raw (uncondensed) NDJSON fixture is tracked, so raw-input condensation remains uncovered.

### Scientific and file-format regression

- Load `Example recipe sheet.csv`, `Example recipe sheet_payload.json`, the old and current workbook templates, and the DID000141 workbook/payload. Normalize dynamic `EndTime` before comparing payloads.
- Add fixtures with unequal cycle counts and runtimes, fractional timings, continuation rows, empty phases, zero-duration sequences, invalid/non-finite values, and many sequences.
- Compare `recipe`, `username`, and `experimentalDetails` schema and normalization; do not compare a time-dependent field byte-for-byte.
- Keep baseline behavior for `ReactorPipeline.condense()`, phase labels, temperature attachment, iSE attachment, exposure CSV, cycle summaries, PNG plots, and animation. Compare structured data and image dimensions/content tolerances rather than brittle binary PNG hashes.
- Test both raw and already-condensed input with “Write condensed data JSON” on/off, and assert exactly which file was read and written.
- Verify recipe export leaves workbook bytes unchanged. Verify header correction's current behavior is labeled and separately tested until Stage 6 changes it.

### Timeline, table, and interaction

- Test block width ratios using unequal durations and a known total; test exact internal/final boundaries, drag, click, keyboard navigation, and time display units.
- Test that selected sequence updates representative-cycle detail, phase summary, table selection/scroll position, and no unrelated row is edited.
- Test phase summary total-first order, per-cycle and aggregate arithmetic, fractions summing to one for positive runtime, and “—” for undefined zero-time fractions.
- Test source-row grouping, clipboard rectangular paste, undo/redo, row operations, focus traversal, and export disable/re-enable around validation errors.
- Assert there is exactly one editable timing model/table in the Recipe Editor; the phase summary is read-only.
- Add Qt screenshots for the supplied design fixture and compare layout hierarchy, card proportions, spacing, colors, and typography at matched 1670 × 940 and common laptop sizes. Do not compare illustrative labels/numbers as ground truth.
- Test window resizing, splitter minimums, table scroll, keyboard-only navigation, screen-reader/accessibility names, and 100%/150%/200% DPI scaling on Windows.

### Threading, responsiveness, and packaging

- Run a representative large condensed file while interacting with navigation; verify the UI event loop remains responsive and progress/log updates are ordered and bounded.
- Test worker success, exception, permission failure/retry, and window shutdown during work. Cancellation is only an acceptance item if cooperative cancellation is implemented.
- Verify Qt imports and startup through the documented `.venv`/Windows scripts on a clean environment. A packaged executable is a separate deliverable requiring an approved packaging tool and Qt plugin collection.

## Risk register and approval gates (original plan)

| Risk | Priority | Treatment |
|---|---|---|
| Workbook/header/phase utility disagree on timing-slot labels; overlap/order is unverified. | **Blocker for authoritative runtime claims**, not for shell prototype. | Confirm against controller documentation or a known run; preserve raw slot indices and mark any earlier estimate provisional. |
| Excel formula `M6` and converter's per-sequence sum can differ for unequal cycle counts. | High, but testable independently. | Ask owner which output is intended; test unequal-sequence fixtures before sharing the timing model with payload metadata. |
| Current processing may rewrite a selected condensed input; header edits rewrite the selected NDJSON. | High data-ownership risk. | Make paths/warnings visible during migration; isolate sidecar correction hardening in Stage 6, but do not falsely promise source immutability. |
| PySide6 adds native runtime and Windows packaging burden. | High release/operations risk; not a prototype blocker. | Confirm target Python and installation model; first run in the current virtual environment, then make an explicit installer decision. |
| Matplotlib backend coupling. | Medium. | Prove QtAgg preview and batch saving in Stage 0 before porting the plot page. |
| Many timing rows/sequences and DPI scaling. | Medium. | Use Qt model/view rather than cell widgets; test long recipes and common DPI settings before cutover. |
| No automated regression suite or true uncondensed representative run checked in. | Medium. | Add focused tests and a synthetic raw fixture; request a safe raw fixture if available. |
| Mockup data differs from actual workbook semantics and existing code. | Expected, not a blocker. | Copy layout and visual hierarchy only; do not copy values, phase labels, or the “Value Metadata” label. |

## Migration and rollback strategy

1. Create a migration branch and capture current Tk screenshots and output baselines. Do not change data schemas or processing implementations while building the Qt shell.
2. Keep the existing Tk app as the working comparison baseline on that branch. Develop the Qt package behind a temporary developer launcher; do not add a permanent runtime framework toggle or dual-GUI product.
3. Compare Qt and Tk runs on the same fixtures, options, and output directories. Validate JSON/CSV values, cycle assignments, filenames, and mutation paths before switching launchers.
4. At cutover, update `reactor_plotter.py` to start the Qt `QApplication`, update `run_gui.bat` to call the authoritative entry point, and correct the `setup.bat` help text. Remove obsolete Tk UI code only after parity and rollback sign-off.
5. Roll back by reverting the cutover/Qt commits or deploying the previous revision. Since recipe, header, and analysis formats remain unchanged, no user data migration is needed.

## Original decisions for the owner, in priority order

1. **Timing semantics:** confirm the seven workbook slot identities/order and whether valve/phase operations execute serially or overlap. Recommended default: do not publish authoritative run-time estimates until confirmed; prototype with a visible provisional label.
2. **Excel formula oracle:** for different cycle counts per sequence, should the GUI/converter follow the current per-sequence algorithm or update the workbook's apparent first-count formula? Recommended default: per-sequence calculations after controller confirmation; treat workbook formula comparison as a test, not authority.
3. **Wait time:** should it be a separate pre-run delay or part of the continuous sequence timeline? Recommended default: show separately, consistent with current `ProcessTimeHr` behavior.
4. **Save semantics:** is in-memory edit state plus **Export Payload…** sufficient for v1, or is a separate persistent draft format needed? Recommended default: in-memory only, export to controller JSON, never overwrite Excel.
5. **Qt distribution:** is a venv-based Python desktop launch acceptable, or is a Windows installer/executable required for release? Recommended default: preserve the current venv workflow for the migration and scope packaging separately.
6. **Settings/Help pages:** should these be fully implemented in the initial shell or added after the main Analyze/Recipe/Plots pages? Recommended default: implement only what existing config/docs support; no placeholder features.
7. **Header corrections:** approve a later sidecar/provenance safety phase, or require preserving the existing explicit in-place correction action indefinitely? Recommended default: keep the current flow separate and clearly warned during migration; design sidecar-by-default after the main Qt cutover.

## Resolved owner decisions (2026-11-01)

These answers supersede the open questions above wherever they conflict. Implementation prompts live in [prompts/qt_migration](../prompts/qt_migration/).

1. **Timing slot labels — resolved; scheduling remains unconfirmed.** The owner identified the nine recipe-table columns as `Cycle, Valve, PrePump, N2Dose, PumpDose, Dose, Hold, PrePurge, Purge`. The seven timing slots are therefore `PrePump, N2Dose, PumpDose, Dose, Hold, PrePurge, Purge`; workbook column C is labelled "PrePurge" in the current template. The owner did not explicitly confirm whether controller operations overlap. The existing backend adds the slot durations serially, so the GUI must identify resulting times as estimates rather than confirmed controller timing.
2. **Multi-sequence cycle counts — resolved.** A number in the Cycle column marks the first row of a sequence and is that sequence's cycle count; blank (or zero) rows belong to the sequence above. The existing serial estimate is `cycle_count × sum(slot durations of its rows)` per sequence, summed over sequences. This cycle-count interpretation is authoritative, but the resulting duration remains provisional until controller scheduling is confirmed. The workbook `M6` formula is not an oracle.
3. **Wait time — separate.** The Recipe Editor exposes **Wait time** and **Start time** fields. Predicted end time = start time + wait time + run duration. Wait time is not drawn inside the run timeline.
4. **Save semantics — in-memory draft + Export Payload…**, never overwrite Excel.
5. **Distribution — existing `.venv` workflow**; packaging is out of scope.
6. **Settings/Help — only what existing config/docs support**; no placeholder features.
7. **Header corrections — extra safety.** Any action that rewrites an existing file must list every affected file (and renames) before execution, require explicit confirmation, and create a backup first. A sidecar-by-default design remains a follow-on.

**Phase-label migration approved:** post-run labels for the second and third timing slots change from `dosepump, dosen2` to `dosen2, dosepump`, matching the owner-specified recipe labels. Plot dimensions can change as a result; the owner accepted that change and stated that backwards compatibility for the PrePump/PrePurge label mix-up is not required. The serial timing calculation remains an estimate until controller scheduling is confirmed.

### Qt header-correction safeguards

The Analyze page's **Edit Data Header** and **Use Header Text as Data Header** actions first show every planned overwrite, creation, optional associated-file rename, backup, and temporary path. Applying the plan requires a separate checkbox confirmation; Cancel is the default. Each existing file involved in the correction receives a timestamped backup before originals change, and rewritten files are staged and atomically replaced. Existing rename destinations, symlink inputs, and conflicting file aliases are rejected. If an operation fails partway through, the error lists completed changes and backup paths so originals can be restored manually. Header comparison itself is read-only.

These backups apply to explicit header corrections. Normal analysis still separately warns and asks before overwriting an existing condensed working file or generated outputs; it does not create header-correction backups for those processing operations.

## Recommended first implementation milestone

Start with **Stage 0 plus the Stage 1 vertical slice**: establish a small output baseline, prove PySide6 and QtAgg in the existing Windows virtual environment, and build the dark navigation shell with the Recipe Editor's actual metadata cards, single source-row table, file loading, validation, and payload export. Include a visibly provisional timeline so visual layout and Qt interaction can be reviewed without claiming unverified controller timing.

The first genuine release gate is timing-slot/order/overlap confirmation. The other major owner decision is whether PySide6 will be distributed through the existing venv workflow or a Windows installer. Keep post-run header correction safety redesign separate so it does not delay the Qt GUI migration.
