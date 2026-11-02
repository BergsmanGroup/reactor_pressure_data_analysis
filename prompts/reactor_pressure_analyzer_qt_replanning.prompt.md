---
mode: agent
description: Re-plan the Reactor Pressure Data Analyzer GUI modernization around PySide6 and supplied design mockups; planning only.
---

# Task: Re-plan the Reactor Pressure Data Analyzer GUI refactor (PySide6-first)

You are a repository-aware senior Python/Qt engineer and scientific-software UX designer. **Do not implement code in this task.** Inspect the actual repository, the existing GUI refactor plan (`reactor-pressure-analyzer-gui-refactor-plan.md`, if present), and all design mockup images supplied alongside this request. Produce a new, actionable, evidence-based development plan. Do not merely reword or lightly patch the earlier Tkinter-oriented plan: revisit the architecture and sequencing from first principles with **visual fidelity, usability, and maintainability** as primary objectives.

## Core decision and priorities

- **PySide6 / Qt Widgets is the preferred target GUI framework.** Plan a full GUI-layer migration from Tkinter unless repository evidence reveals a serious blocker. Discuss alternatives briefly and concretely; do not default back to Tkinter solely to minimize initial engineering effort. Prefer Qt Widgets, Qt Style Sheets, custom-painted widgets/QGraphicsView where appropriate, and model/view tables. Consider QML only if a specific requirement justifies its additional complexity.
- **Visual fidelity is a first-class acceptance criterion.** Study the supplied images closely: panel proportions, hierarchy, colors, typography, spacing, navigation, control density, splitters, scrolling, timeline, table, and overall polish. Identify discrepancies between images and written requirements, and prioritize the written requirements below where they conflict. The mockups contain illustrative, potentially inconsistent data; do not treat their labels, timing numbers, or phase names as authoritative.
- **Keep scientific logic stable.** Reuse processing, conversion, parsing, plotting, and output modules where possible, and protect their contracts with regression tests. Add thin UI adapters or presenters rather than rewriting algorithms for aesthetic reasons.
- Work in the existing repository and respect its Windows development/launch workflow. A separate, unfinished temperature-controller GUI exists, but **do not inspect it as an architectural authority, depend on it, introduce cross-repo coupling, or block this work on it**. Future aesthetic harmonization is optional and out of scope.

## Intended application scope

The application currently has analysis/plotting and recipe conversion functions. The refactor should create a polished, practical desktop scientific-instrument interface, with the **pre-run Recipe Editor** as the main new design target. Preserve the existing analysis pipeline and its outputs. Keep **post-run recorded-header correction** conceptually and technically separate from pre-run recipe creation; LabVIEW may not update the recorded header when the recipe changes mid-run.

### Recipe Editor layout: non-negotiable requirements

1. **Top row:** recipe metadata and valve metadata side by side. Make the experiment **description substantially taller**, genuinely multiline, and comfortable for longer text. Keep useful file actions, validation, and recipe/output identity visible without wasting vertical space.
2. **Bottom left:** one generously sized **combined timeline and sequence-details panel**. It must have enough vertical space for a full-run timeline plus representative-cycle detail and a compact phase-duration summary.
3. **Bottom right:** **exactly one editable timing table**, taller than in the earlier mockups, with many visible rows and comfortable vertical scrolling. Do not repeat the timing table in the timeline panel or elsewhere. The timeline may include a compact read-only phase summary, but it must not become a duplicate spreadsheet.
4. The lower panels should have practical resizable splitters, sensible minimum dimensions, and good behavior on a typical desktop display and at high DPI. Plan keyboard/focus/accessibility behavior as well as visual appearance.

### Timeline and synchronized interactions

- Show **the entire planned run as one continuous horizontal bar**, divided into color-coded sequence blocks whose widths are **proportional to actual calculated sequence runtime**, not evenly spaced.
- Overlay a draggable **time-position scrubber/playhead directly on that bar**. Clicking, dragging, keyboard navigation, and clicking a sequence block should navigate. The selected sequence is the one containing the playhead; boundaries must have deterministic behavior.
- When the playhead enters a sequence, update the **representative single-cycle timeline** for that sequence, its **compact read-only phase-duration summary**, and the **selection/scroll position in the one editable timing table**. Do not render all nominally repeated cycles individually.
- In the summary, lead with **total sequence time**, then show per-cycle and aggregated time spent in phases and their fractions of the sequence. Preserve a clear distinction between sequence identity colors and phase identity colors.
- Scrubbing changes **view state only**. Editing valid timing data recalculates durations, sequence block widths, representative-cycle detail, and summaries from one authoritative timing model. Handle unequal sequence durations, many sequences, zero-duration phases/sequences, and boundary edits.
- Plan for a readable time scale, tooltips, selected-sequence highlighting, and long/short run extremes. Do not invent controller execution semantics.

### Excel and editing behavior

- **Excel remains the primary recipe construction tool** because users rely on formulas and copy/paste to build timing rows. Do not propose a full Excel replacement or a new formula engine.
- The GUI should import/inspect recipes and support convenient **direct edits**, including single-cell edits, rectangular clipboard copy/paste, row operations, selection, validation, and ideally undo/redo, using a Qt model/view design.
- Preserve the existing workbook and controller-facing JSON payload format. Do not promise lossless Excel round-trip if the current converter cannot support it. Clearly define whether GUI edits live in an in-memory draft, a separate draft format, or exported JSON; do not silently modify the source workbook.
- Include an explicit design for error states, stale previews, export blocking on invalid data, and provenance of edited drafts.

### Header correction and analysis

- Treat **pre-run recipe editing** and **post-run header correction** as separate workflows, even if they share some visual components. A corrected run header describes what actually happened, not the original planned recipe.
- Review the current header-writing behavior and potential source-file mutation, but **do not let a broad header-correction safety redesign delay the main GUI migration**. Recommend a clearly isolated follow-on phase with explicit file-ownership safeguards and tests.
- Preserve pressure condensation, phase labeling, temperature attachment, iSE attachment, plotting, animations, CSV/JSON outputs, and existing user-facing analysis capabilities. Identify any input/output operations that currently mutate selected files and ensure the new GUI accurately communicates that behavior.

## Repository investigation requirements

Inspect actual files and cite specific paths/functions in the plan. At minimum, investigate:

- Current entry points, GUI composition, event handlers, threading, dialogs, and window sizing.
- `gui.py`, `reactor_plotter.py`, `convert_to_json.py`, `sequence_utils.py`, `pipeline.py`, `data_parser.py`, `plot_utils.py`, `ise_utils.py`, `header_editor.py`, `header_text.py`, dependencies, Windows setup/launch scripts, workbook templates, sample payloads, and any tests/docs that exist. Adjust this list if the repository has evolved.
- Qt migration implications: `QApplication`, main window/navigation, `QSplitter`, `QTableView` + `QAbstractTableModel`/delegates, custom timeline painting or graphics scene, signal/slot data flow, background tasks (`QThread`/thread pool), Matplotlib embedding, dialogs, logging/progress, theme tokens/QSS, DPI behavior, and packaging on Windows.
- Timing semantics and uncertainties: workbook timing-slot labels versus header editor and phase utilities; sequential versus overlapping phases; continuation rows; cycle-count multipliers; wait time; planned versus measured time; and any post-run phase shift. **Do not silently resolve mismatches**: propose validation against controller documentation or known runs and state what can be prototyped before confirmation.
- Existing data mutation and output path behavior, especially raw versus already-condensed inputs and header edits.

## Required planning deliverable

Write a new Markdown plan to `docs/reactor-pressure-analyzer-pyside6-refactor-plan.md` (create `docs/` if needed), or a similarly named plan if repository conventions require it. The plan must include:

1. **Executive recommendation** explaining why PySide6 is appropriate for this UX-driven refactor and its real costs/risks.
2. **Repository findings** with file/function references, existing dependencies, reusable backend boundaries, and any missing assets/tests.
3. **Mockup-to-widget mapping**: explicit panel hierarchy, approximate responsive sizing, navigation, Qt widgets, styling/theme approach, and where custom drawing is necessary. If images were not actually accessible, say so and request them; do not pretend to have reviewed them.
4. **Proposed architecture** with module boundaries, UI state vs recipe/timing models, event flow, threading, and no accidental backend rewrite. Include a concise proposed file/module tree.
5. **Detailed sequence timeline design**: runtime computation assumptions, proportional widths, playhead interaction, selection synchronization, representative-cycle rendering, phase summary, and edge cases.
6. **Qt table/editing design**: model/delegate, clipboard behavior, row edits, undo/redo, validation, and export compatibility.
7. **Staged implementation plan** prioritizing an early **working PySide6 vertical slice** with a credible attractive layout, followed by synchronization, editing, full analysis integration, polish, and a separately scoped header-correction improvement. Identify what can be done in a short first development session versus what should wait.
8. **Regression and UX test plan** with acceptance criteria for scientific outputs, correct proportional timelines, keyboard/scroll behavior, high-DPI resizing, threading/responsiveness, and visual comparison to supplied mockups.
9. **Risk register and approval gates**, distinguishing genuine blockers (such as uncertain timing semantics) from issues that can be deferred without preventing a useful UI prototype.
10. **Migration/rollback strategy** that allows comparison with the functioning Tkinter application on the development branch without requiring a permanent dual-GUI architecture.
11. **Decisions/questions for the owner**, ordered by importance, with your recommended defaults.

Be specific about implementation effort and tradeoffs; avoid generic framework evangelism. **Do not edit application source files, install dependencies, or implement the GUI yet.** Your only authorized repository change for this task is the planning document. At the end, summarize your recommended first implementation milestone and the top unresolved decisions in chat.
