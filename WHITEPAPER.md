# Reactor Pressure Data Analyzer — Technical Whitepaper

**Version:** 1.0  
**Date:** August 2026  

---

## Abstract

The Reactor Pressure Data Analyzer is a desktop application for post-processing and visualizing time-series pressure data collected from automated chemical vapor deposition (ALD/CVD-class) reactor experiments. It ingests newline-delimited JSON (NDJSON) log files produced by the reactor controller, reconstructs per-cycle phase timelines from valve-sequence metadata, generates phase-colored pressure plots, computes trapezoidal exposure integrals with leak-rate detection, and optionally assembles cycle animations. A second subsystem converts human-authored CSV recipe sheets into validated JSON payloads suitable for direct submission to the reactor controller. Both subsystems are exposed through a single Tkinter GUI with persistent session state.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Data Formats](#2-data-formats)
3. [Module Reference](#3-module-reference)
4. [Processing Pipeline — Reactor Plots](#4-processing-pipeline--reactor-plots)
5. [Processing Pipeline — Recipe Conversion](#5-processing-pipeline--recipe-conversion)
6. [Algorithms](#6-algorithms)
7. [Output Files](#7-output-files)
8. [Installation and Launch](#8-installation-and-launch)
9. [Dependencies](#9-dependencies)

---

## 1. System Architecture

The application is organized as a single-window Tkinter GUI (`reactor_plotter.py` → `gui.py`) that delegates all non-UI work to a set of stateless utility modules. Background work (file parsing, plot rendering) is dispatched to a `ThreadPoolExecutor` so the GUI remains responsive during long operations. Session parameters are persisted to the local `config_local.json` and reloaded on startup.

```
reactor_plotter.py          Entry point; instantiates ReactorApp
│
└── gui.py  (ReactorApp)    Main window with two tabs
      ├── data_parser.py    NDJSON streaming and condensing
      ├── sequence_utils.py Valve sequence → phase-bin timeline
      ├── plot_utils.py     Matplotlib figure building and exposure math
      ├── ise_utils.py      In-situ ellipsometer CSV parsing
      ├── header_editor.py  Modal header-field editor
      └── convert_to_json.py  CSV recipe → JSON payload
```

### Tab 1 — Reactor Plots

Loads a raw (or previously condensed) NDJSON data file, parses its embedded valve-sequence header, partitions pressure readings into named phases, renders one PNG per cycle, computes exposure metrics, and optionally produces an animated GIF.

### Tab 2 — Convert Recipe Sheet

Loads a CSV recipe sheet authored by the experimenter, validates its structure against a strict schema, displays warnings inline, and exports a JSON payload that the reactor controller can consume directly.

---

## 2. Data Formats

### 2.1 NDJSON Reactor Log (Input)

Each line is a self-contained JSON object. Four record types appear in order:

| Type | Role |
|------|------|
| `header` | One per file; contains experiment metadata and the full valve-sequence array |
| `step` | Context record emitted when the controller advances to a new phase/step |
| `pressure` | One per sensor sample; carries `TimeElapsed` (ms), `CurrentCycle`, and `Pressure` (mTorr) |
| `footer` | Sentinel marking end of file |

**Header payload (key fields):**

```json
{
  "Info": "ED Saturation experiment",
  "WaitTime": 3600,
  "EDR": true,
  "DID": [117, 119],
  "valveSequence": [
    [1,  7, 0, 15, 0,   0,   0, 0,  10],
    [5,  5, 4,  0, 0, 300,   0, 0, 300],
    [0,  6, 4,  0, 0,   1, 299, 0, 1800]
  ],
  "ValvePrecursor": [7, 5, 6],
  "Name": ["iSE", "TDIC", "ED"],
  "TempC": [25, 25, 25]
}
```

Each row of `valveSequence` encodes: `[cycles, valve_number, prepump, dosepump, dosen2, dose, hold, prepurge, purge]`. A `cycles` value of `0` appends the valve row to the current sequence rather than starting a new one.

**Pressure record:**

```json
{"type":"pressure","payload":{"TimeElapsed":500,"CurrentCycle":1,"Pressure":145.2}}
```

### 2.2 Condensed Log (Intermediate)

After first processing, the application can write a condensed NDJSON file where every record is of type `data` and already carries the merged step context (`CurrentStep`). Re-loading this file skips the expensive merge pass and reduces startup time for re-analysis.

```json
{"type":"data","payload":{"TimeElapsed":500,"CurrentCycle":1,"CurrentStep":"seq1_7_dosepump","Pressure":145.2}}
```

### 2.3 CSV Recipe Sheet (Input)

A structured spreadsheet with two logical sections:

**Header section (rows 1–8):**

| Row | Column A | Column B | Columns C–J |
|-----|----------|----------|-------------|
| 1 | — | Username | — |
| 2 | "Info" | Experiment description | — |
| 3 | "Wait" | Wait time (s) | — |
| 4 | "EDR" | True/False | DID device IDs |
| 5 | "Valve/precursor" | "nan" (Chamber reserved) | Valve numbers |
| 6 | "Name" | "Chamber" | Valve display names |
| 7 | "Temperature (C)" | Chamber temp | Per-valve temps (°C) |

**Recipe section (from the "Cycles" marker row onward):**

```
Cycles  Valve  PrepPump  DosePump  DoseN2  Dose  Hold  PrePurge  Purge
1       7      0         15        0       0     0     0         10
5       5      4         0         0       300   0     0         300
        6      4         0         0       1     299   0         1800
```

An empty `Cycles` cell appends a valve row to the current sequence.

### 2.4 iSE Ellipsometer Data (Input)

A two-column CSV (time, thickness) with a two-row text header, optionally using quoted tab-delimited values. The parser extracts the thickness column by index.

---

## 3. Module Reference

### 3.1 `data_parser.py`

Responsible for all file I/O against NDJSON logs.

**`read_header(path) → dict`**  
Reads only the first line and returns its `payload`. No full file scan required.

**`stream_pressure(path, wait_time, progress_cb) → (cycle_points, cycle_start_map)`**  
Iterates the file line by line, maintaining a rolling step-context buffer. Discards records where `TimeElapsed / 1000 < wait_time`. Returns:
- `cycle_points`: `{cycle_id: [(t_s, pressure_mTorr), ...]}`
- `cycle_start_map`: `{cycle_id: absolute_t0_s}` for relative timing

Calls `progress_cb(fraction)` every ~4 MB to drive the GUI progress bar.

**`condense_log(input_path, output_path, phase_lookup)`**  
Single-pass conversion of raw → condensed format. The optional `phase_lookup(cycle, t_s) → str` callback can replace raw controller step labels with computed phase names.

**`is_condensed_file(path) → bool`**  
Peeks at the first non-empty line; returns `True` if it has `"type":"data"`.

---

### 3.2 `sequence_utils.py`

Converts the raw valve-sequence array from the header into named, time-indexed phase bins.

**Phase slot order (fixed):**

```
Index:  0         1          2       3      4      5          6
Name:   prepump   dosepump   dosen2  dose   hold   prepurge   purge
```

**`convert_sequence(valve_sequence) → dict`**  
Parses the nested list from the header into a structured dict keyed by `"seq1"`, `"seq2"`, etc. Each key maps to a sub-dict containing `"cycles"` and one entry per valve.

**`apply_valve_names(seq_dict, name_map) → dict`**  
Renames valve keys from numeric (`"valve7"`) to display names (`"valveTDIC"`) using the user-supplied mapping from the GUI.

**`compute_phase_bins(seq_dict, shift) → dict`**  
For each sequence, iterates all valve timing rows and builds:
- `phase_bins`: sorted list of cumulative time breakpoints (seconds)
- `phase_names`: parallel list of label strings (e.g., `"seq1_7_dose"`)

Zero-valued slots are skipped. The `shift` parameter (GUI setting) adds a uniform offset to each breakpoint to account for systematic timing lag.

**`make_cycle_seq_map(seq_dict) → dict`**  
Returns `{cycle_id: "seqN"}` by accumulating the `cycles` count across sequences.

**`assign_phase(cycle_time_s, phase_bins, phase_names) → str | None`**  
Binary searches `phase_bins` for `cycle_time_s` and returns the associated phase name, or `None` if the time falls before the first bin.

**`build_phase_color_map(all_phase_names) → dict`**  
Generates a stable `{phase_name: (R, G, B, A)}` mapping. Colors are derived from a SHA-1 hash of the canonical phase name (with the `seqN_` prefix stripped), ensuring the same valve/phase combination receives the same color regardless of sequence number or the total number of phases present.

---

### 3.3 `plot_utils.py`

All matplotlib logic. Operates on the Agg backend (no display required) so plots can be saved from a background thread.

**`build_segments(cycle, cycle_points, cycle_start_map, seq_dict, cyc_seq_map, assign_phase_fn) → dict`**  
Walks the `(t, P)` pairs for one cycle and groups them by phase name. Adjacent points that straddle a phase boundary are duplicated into both segments to produce clean line joins with no gaps.

**`draw_cycle_figure(cycle, filename, segments, phase_color_map, xlim, ylim, seq_note) → Figure`**  
Renders a single `Figure` with:
- Phase-colored line segments, each with its own legend entry
- Gray line for unassigned (pre-first-bin) points
- Grid, axis labels, title
- Optional sequence note in a wrapped text box

**`save_cycle_figure(fig, cycle, out_dir)`**  
Saves as `cycle_NNNN.png` at 130 DPI.

**`compute_exposure_table(cycles, cycle_points, ...) → list[dict]`**  
For each cycle, integrates only the `dose` and `hold` phase points using the trapezoidal rule. Returns a list of row dicts, one per cycle per valve. See [Section 6.2](#62-exposure-integration) for the full algorithm.

**`build_animation(cycles, out_dir, fps, dpi) → str`**  
Stitches the saved cycle PNGs into an animated GIF using Pillow. Returns the output path.

---

### 3.4 `ise_utils.py`

**`parse_ise_thickness(ise_csv_path) → list[float]`**  
Reads iSE data, auto-detects quoted tab-delimited format, and returns the thickness column as a list of floats.

**`save_ise_thickness_csv(ise_csv_path, output_csv_path, blank_rows)`**  
Writes the thickness values to a single-column CSV, inserting `blank_rows` empty rows between each value (used for aligning with manual measurement logs).

---

### 3.5 `header_editor.py`

**`HeaderEditorDialog(parent, header_dict)`**  
A modal `Toplevel` window that presents the full header payload as an editable form. Scalar fields use `Entry` widgets; valve and sequence tables use `Treeview` grids. Changes are applied to a deep copy of the header; the caller receives the modified dict only if the user clicks Save.

---

### 3.6 `convert_to_json.py`

**`load_table(csv_path) → DataFrame`**  
Reads the recipe CSV with pandas, preserving all cells including blanks.

**`validate_recipe_sheet(df) → list[str]`**  
Checks structural requirements and returns a list of human-readable error strings. An empty list indicates a valid sheet. Checks include:
- Presence of the "Cycles" row marker
- Chamber valve slot reserved (`nan` in row 5, col B)
- "Chamber" literal in row 6, col B
- Numeric temperature in row 7, col B
- All recipe valve numbers declared in the header valve table
- No zero or NaN valve numbers in recipe rows

**`build_payload(df, valve_names, details) → dict`**  
Assembles the output JSON: a `"recipe"` array (list of string-encoded rows) and an `"experimentalDetails"` object containing metadata, valve declarations, and per-sequence notes.

**`build_output_filename_report(df) → str`**  
Formats a filename stem encoding the key experimental identifiers:  
`{username}_{EDR}{value}_{DID}{values}_{valve}{temp}_...`

---

### 3.7 `gui.py`

**`ReactorApp(tk.Tk)`** — the root window.

**State management:**  
On startup, the local `config_local.json` is read and all widget variables are populated from it. If it does not exist, it is copied from the tracked `config_default.json` template. Reactor header filenames identify the configured reactor type, and valve names are saved separately for each reactor type when processing starts.

**Configurable parameters exposed in the GUI:**

| Parameter | Default | Effect |
|-----------|---------|--------|
| X-axis limit | `config_default.json` | Crop or expand time axis |
| Y-axis limit | `config_default.json` | Crop or expand pressure axis |
| Phase shift | `config_default.json` | Offset applied to all phase breakpoints |
| Wait time | `config_default.json` | Discard data before this elapsed time |
| Animation FPS | `config_default.json` | Frame rate of output GIF |
| Leak-rate trim | `config_default.json` | Seconds dropped from edge of hold phase for regression |
| iSE blank rows | `config_default.json` | Blank-row spacing in ellipsometer output CSV |

**Threading:**  
File reading and all plot-generation work runs in a `ThreadPoolExecutor`. Progress updates are posted to the main thread via `widget.after(0, callback)` to avoid Tkinter thread-safety issues. The log text box receives append calls through the same mechanism.

---

## 4. Processing Pipeline — Reactor Plots

```
User selects NDJSON file
        │
        ▼
data_parser.read_header()
  → valveSequence, Info, WaitTime, DID, etc.
        │
        ▼
sequence_utils.convert_sequence()
  → seq_dict: {seqN: {cycles, valve_N: [t0..t6]}}
        │
        ├── [optional] header_editor.HeaderEditorDialog
        │     → user can modify fields in-place
        │
        ▼
sequence_utils.compute_phase_bins(seq_dict, shift)
  → phase_bins and phase_names per sequence
        │
        ▼
sequence_utils.make_cycle_seq_map(seq_dict)
  → {cycle_id: "seqN"}
        │
        ▼
data_parser.stream_pressure(path, wait_time, progress_cb)
  → cycle_points, cycle_start_map
        │
        ├── [optional] data_parser.condense_log()
        │     → write _condensed.json for fast re-runs
        │
        ▼
For each cycle:
  plot_utils.build_segments(...)
    → {phase_name: [(t, P), ...]}
          │
          ▼
  plot_utils.draw_cycle_figure(...)
    → matplotlib Figure
          │
          ▼
  plot_utils.save_cycle_figure(...)
    → cycle_NNNN.png
        │
        ▼
plot_utils.compute_exposure_table(all_cycles, ...)
  → list of per-cycle metric rows
        │
        ▼
plot_utils.save_exposure_csv(rows, out_dir, stem)
  → {stem}_exposure.csv
        │
        ▼ [optional]
plot_utils.build_animation(cycles, out_dir, fps, dpi)
  → {stem}_animation.gif
```

---

## 5. Processing Pipeline — Recipe Conversion

```
User selects CSV recipe sheet
        │
        ▼
convert_to_json.load_table(csv_path)
  → pandas DataFrame
        │
        ▼
convert_to_json.validate_recipe_sheet(df)
  → list of error strings (displayed in GUI; empty = valid)
        │
        ▼
convert_to_json.extract_header_details(df)
  → username, {Info, WaitTime, EDR, DID, ValvePrecursor, ...}
        │
        ▼
convert_to_json.build_payload(df, valve_names, details)
  → {"recipe": [...], "experimentalDetails": {...}}
        │
        ▼
convert_to_json.build_output_filename_report(df)
  → filename stem string
        │
        ▼
convert_to_json.save_payload(payload, output_path)
  → {filename}.json
```

---

## 6. Algorithms

### 6.1 Phase Binning

Given a valve-sequence table (each row: `[cycles, valve, t0, t1, t2, t3, t4, t5, t6]`), the phase-bin algorithm proceeds as follows:

1. Group rows into sequences by accumulating `cycles` counts. A row with `cycles == 0` extends the current sequence.
2. For each sequence, iterate every valve and every of its 7 phase-slot durations.
3. Skip any slot where the duration is zero.
4. For non-zero slots, advance a running cursor: `cursor += duration + shift`.
5. Record `(cursor, "{seqN}_{valve}_{phase_name}")` as a boundary.
6. Sort all boundaries by time to form `phase_bins` and `phase_names`.

At query time, `assign_phase(t)` calls `numpy.searchsorted(phase_bins, t)` for O(log n) lookup.

**Effect of the shift parameter:** A positive `shift` moves every phase boundary later in time, compensating for a known lag between the controller issuing a valve command and the pressure sensor responding. A negative shift moves boundaries earlier.

### 6.2 Exposure Integration

For each cycle, pressure points are labeled by phase. Only points in `dose` and `hold` slots contribute to the exposure calculation.

**Exposure (mTorr · s):**

$$E = \sum_{i=1}^{n} \frac{P_i + P_{i-1}}{2} \cdot (t_i - t_{i-1})$$

**Mean pressure (mTorr):**

$$\bar{P} = \frac{E}{\Delta t_\text{total}}$$

**Leak-rate detection:**  
When a valve's dose phase has effectively zero integrated exposure (i.e., the valve was never opened for dosing) but a hold phase is present, the chamber is likely measuring background leak. In this case, the algorithm:

1. Collects all `(t, P)` pairs in the hold phase.
2. Trims `leakrate_phase_reduction` seconds from both the leading and trailing edges.
3. Fits a least-squares line to the trimmed data.
4. Reports the slope as the leak rate in mTorr/s.

### 6.3 Phase Color Stability

To ensure that the same chemical process (e.g., TDIC dose) always renders in the same color regardless of where it appears in the sequence list:

1. Strip the sequence prefix from the phase name: `"seq3_7_dose"` → `"7_dose"`.
2. Compute `SHA1("7_dose")`.
3. Map the first three bytes of the digest to hue, saturation, and value in HSV space.
4. Convert HSV → RGB.

This guarantees that adding, removing, or reordering sequences never changes the color of an existing phase.

---

## 7. Output Files

All outputs are written to the same directory as the loaded input file unless the user specifies otherwise.

| File | Format | Description |
|------|--------|-------------|
| `cycle_NNNN.png` | PNG (130 DPI) | Pressure vs. time for one cycle, phase-colored |
| `{stem}_exposure.csv` | CSV | Per-cycle exposure integrals and leak rates |
| `{stem}_condensed.json` | NDJSON | Merged/condensed version of raw log for fast re-runs |
| `{stem}_animation.gif` | GIF | Animated cycle sequence |
| `{filename}.json` | JSON | Recipe payload for reactor controller |
| `{stem}_ise_thickness.csv` | CSV | Ellipsometer thickness column, optionally spaced |

### Exposure CSV Column Schema

For each declared valve `V`, the following columns appear:

| Column | Units | Description |
|--------|-------|-------------|
| `sequence` | — | Sequence label (seq1, seq2, …) |
| `V_nominal_dose` | s | Programmed dose duration |
| `V_nominal_hold` | s | Programmed hold duration |
| `V_nominal_duration` | s | Total programmed cycle duration |
| `V_exposure` | mTorr · s | Trapezoidal integral over dose + hold |
| `V_mean_pressure` | mTorr | Exposure / duration |
| `V_leak_rate` | mTorr/s | Least-squares slope (blank-dose cycles only) |

---

## 8. Installation and Launch

**First-time setup:**

```bat
setup.bat
```

Creates a `.venv` virtual environment in the project directory and installs all requirements.

**Subsequent launches:**

```bat
run_gui.bat
```

Activates `.venv`, confirms requirements, and starts the application. Alternatively:

```bat
python reactor_plotter.py
```

**Session state** is automatically saved to the ignored local `config_local.json` and restored on next launch, preserving parameter values and per-reactor valve name mappings. The tracked `config_default.json` contains the clean first-run state and is copied only when the local file is missing. Each processing run appends the current file's valve names, header GUID, filename-derived `process_datetime`, actual write-time `log_datetime`, and data filename to the ignored local `valve_name_log.jsonl`.

---

## 9. Dependencies

| Package | Minimum Version | Role |
|---------|-----------------|------|
| `matplotlib` | 3.8 | Figure rendering, Agg backend |
| `numpy` | 1.26 | Phase bin binary search, least-squares regression |
| `pandas` | 2.2 | CSV recipe sheet parsing |
| `Pillow` | 10.0 | GIF animation assembly |
| `openpyxl` | 3.1 | pandas optional Excel engine |

All UI components use the Python standard library (`tkinter`, `threading`, `json`, `hashlib`, `csv`). No external GUI frameworks are required.

---

*End of Whitepaper*
