---
description: "Qt migration step 08 — Plots & Animation page"
---

# 08 — Plots & Animation page

Prerequisite: 07.

## Tasks

1. `reactor_ui/pages/plots_page.py`: single-cycle preview with `FigureCanvasQTAgg` + `NavigationToolbar2QT`, cycle selector, plot/animation generation actions, and output-directory open/reveal actions — porting the existing Tk preview and output workflow from `gui.py`.
2. Reuse `plot_utils` functions unchanged; generation runs on the 07 worker.
3. Share state (current pipeline result, output dir) with the Analyze page via a small app-level state object, not globals.
4. Tests: preview renders for a synthetic cycle; generated PNG/CSV/GIF files match the direct backend call (structural/dimension comparison, not binary hash).
