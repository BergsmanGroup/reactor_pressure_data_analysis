---
description: "Qt migration step 07 — Analyze page and pipeline worker"
---

# 07 — Analyze page and pipeline worker

Prerequisite: 01–02 (independent of 03–06). Read the plan's **Analyze and Plots & Animation pages** and **Qt and plotting details**, and study `gui.py::_build_plot_tab()` and its handlers thoroughly; this is a port, not a redesign of processing.

## Tasks

1. `reactor_ui/workers/pipeline_worker.py`: `QObject` worker run in a `QThread`, wrapping `ReactorPipeline` with signals `progress(int, str)`, `log(str)`, `finished(object)`, `failed(str)`. Widgets are never touched off the GUI thread. No cancel button unless cooperative cancellation exists.
2. `reactor_ui/adapters/analysis_controller.py`: builds an immutable `ProcessingOptions` snapshot from the form and dispatches stage actions exactly as `gui.py` does today.
3. `reactor_ui/pages/analyze_page.py` (mockup left column / right column): input data file (raw/condensed), header load/compare, temperature data discovery and zone selection, iSE file, valve-name mapping, output directory, pipeline stage buttons and **Run Analysis**, progress bar, bounded log (`QPlainTextEdit.setMaximumBlockCount`). Right: analysis/plot options (leak-rate reduction, thickness blank rows, FPS, etc. — whatever `ProcessingOptions` has) and valve metadata. Label "Valve Metadata"/"Valve #" (mockup "Value" is a typo).
4. Show exact source, working (condensed), and output paths, with a visible warning when the selected input is already condensed and will be updated in place.
5. Persist settings through the existing `config_local.json` load/save logic (reuse, do not fork the format).
6. Tests: options snapshot matches the Tk mapping for the same inputs; worker success/exception signal paths; outputs from a synthetic run match running `ReactorPipeline` directly.
