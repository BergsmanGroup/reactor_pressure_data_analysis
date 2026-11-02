---
description: Develop a repository-aware implementation plan for the Reactor Pressure Data Analyzer GUI redesign without changing code.
agent: agent
---

# Task: Plan the Reactor Pressure Data Analyzer GUI Refactor

You are acting as a senior software architect and scientific-software developer. Inspect the **current repository in depth** and write a practical, repository-specific development plan for modernizing the Reactor Pressure Data Analyzer. **This is planning only: do not implement changes, install packages, or refactor code.** Cite actual files, functions, classes, data structures, and dependencies in your findings; distinguish verified behavior from assumptions and open questions.

## Objectives and scope

The existing application is functional. Preserve its underlying scientific processing, file compatibility, and outputs wherever possible. Prioritize a better GUI, maintainability, responsive layout, and a short path to a working first release. The temperature controller is undergoing a separate, unfinished refactor: **do not inspect or depend on its implementation, propose shared libraries, or require coordination with that project.** Aesthetic alignment can happen later. Use the provided mockups and specifications as the visual reference, not the other application's code.

Evaluate the existing GUI toolkit and recommend whether to retain it or migrate (for example, to Qt/PySide6 if justified). Explicitly compare the costs, risks, packaging implications, and likely benefits of keeping the current framework versus migrating. Do not assume a migration is required.

## Target layout

Use a desktop scientific-instrument interface with a clear hierarchy, dark theme, restrained purple/blue accents, readable dense tables, and resizable panels. The desired Recipe Editor layout is:

1. **Top row:** Recipe metadata on the left and valve metadata on the right. Give the multiline experimental **description** substantially more height than the current editor. Keep relevant metadata fields and valve number/name/temperature editing.
2. **Bottom left:** One combined **Run Timeline & Sequence Details** panel, with generous vertical height.
3. **Bottom right:** One tall **editable timing table** with enough height for many visible rows and comfortable vertical scrolling. **There must be only one timing table; do not duplicate tables elsewhere in the view.**
4. Keep file actions, validation feedback, and save/export controls easy to find without wasting screen space. Plan responsive splitters or other resizing mechanisms.

## Combined timeline behavior

- Show the **entire run as one continuous horizontal bar** segmented into color-coded sequence blocks. Block widths must be proportional to each sequence's calculated runtime, not equally spaced.
- Overlay a **draggable scrubber/playhead** on this same bar. Moving it continuously through elapsed run time selects whichever sequence contains the playhead; show elapsed time and sequence identification, optionally the cycle within that sequence. Clicking a block or using keyboard navigation should also work.
- **Below the full-run bar, in the same combined panel**, show a **representative single-cycle timeline** for the selected sequence, displaying the order/durations of the relevant valve operations and phases. Do not plot every nominally repeated cycle separately.
- Also show a **compact per-sequence phase-duration summary** (phase, time per cycle, aggregate time across sequence, fraction of sequence), with total sequence time first. This summary is **not a second editable timing table**. It may sit beside or beneath the representative cycle visualization inside the combined panel.
- Synchronize the selected sequence with the single editable timing table on the bottom right, filtering or scrolling to that sequence's rows as appropriate. Scrubbing must never modify recipe data.
- Editing timing data should recalculate cycle/sequence durations, overall runtime, timeline block widths, and summary figures from one authoritative timing model. Address edge cases: zero cycles, empty phases, long recipes, unequal sequences, invalid values, and changes that alter boundaries while scrubbing.
- Derive visualizations from the **actual timing semantics** in the repository. Do not infer that all named phases are mutually exclusive or simply sum every numeric field without verifying execution semantics. Distinguish planned timing from measured timing and explain how to validate the calculations.

## Excel and recipe editing

Excel remains the **primary authoring environment** because formulas, fill, and copy/paste make constructing recipe timing rows efficient. Preserve Excel import and existing recipe-sheet-to-JSON conversion and file conventions. The GUI should enable inspection, validation, and modest direct editing without forcing repeated Excel reloads. Investigate whether the current editor supports clipboard rectangular paste, multi-row edits, insertion/deletion, and undo; recommend an appropriate limited feature set without rebuilding Excel's formula engine. Do not promise lossless Excel round-trip editing unless the repository supports it; explain file ownership and save/export semantics.

## Crucial workflow distinction: header correction

**Pre-run recipe editing is not the same as post-run header correction.** LabVIEW writes a run header but does **not** live-update it when the operator changes the recipe mid-run. The existing Header Editor is a post-run correction workflow for reconciling the recorded header with what actually happened. Investigate the real code and data flow for both workflows and plan separate entry points, load/save behavior, validation, and user-facing language. They may share reusable metadata/timing table widgets, but must not silently share file-writing logic or overwrite raw source data. Recommend safe backup/provenance handling and how corrected headers relate to condensed JSON or analysis outputs. Treat multi-segment actual-run reconstruction as a potential later enhancement, not a required first-release feature.

## Preserve existing analysis functionality

Inventory and protect the application's existing features, including as applicable: raw data/header selection and parsing, recipe conversion, valve names, temperature log discovery/zone selection/attachment, optional ISE data, data condensation, sequence/phase labeling, plot generation and preview, animation, configuration, logs, output directories, and relevant file formats. Map the UI events to existing processing functions and identify any processing changes truly necessary for the new GUI. Prefer thin adapters and minimal backend changes. Highlight thread-safety, long-running operations, cancellation/progress, UI responsiveness, error handling, and file-path behavior.

## Required investigation

1. Map repository structure, app entry points, GUI modules, service/processing modules, dependencies, packaging/build scripts, tests, and representative inputs/outputs.
2. Trace the complete recipe-sheet → JSON → header/processing pipeline and the independent raw-data → corrected-header → analysis pipeline. Document any uncertain or divergent paths.
3. Determine how sequences, cycles, timing rows, valve assignments, and phase durations are encoded; give an evidence-based formula or pseudocode for computing per-cycle, per-sequence, and full-run timing. Flag ambiguity explicitly.
4. Assess the safest UI architecture: component boundaries, state model, selection/scrubber coordination, editable table model, validation, theme system, and interfaces to existing services.
5. Identify performance/scaling risks for large recipes and any need for table virtualization or efficient timeline rendering.
6. Inventory regression tests and propose fixtures or golden-file comparisons to verify identical outputs before/after UI work.

## Deliverable: a concrete plan, not code

Write a Markdown plan in the repository (suggest an appropriate location such as `docs/reactor-pressure-analyzer-gui-refactor-plan.md`; if repository conventions differ, follow them). Include:

- Executive summary and recommendation, including whether to retain or change GUI framework.
- Current-state architecture map with **specific file/function references**.
- Proposed screen layout and interaction/state-flow description, including one timing table and the combined timeline panel.
- Data and timing model, calculations, validation rules, and unresolved semantics.
- Clear separation of recipe editing and post-run header correction.
- Backend impact analysis: **what remains unchanged, what requires adapters, and what (if anything) must change in the service/processing scripts**, with explicit risks/benefits.
- A staged implementation plan: a **minimal functional GUI overhaul first**, followed by polish/optional enhancements. For each stage, list affected files, dependencies, deliverables, acceptance criteria, and rollback strategy.
- Testing and regression checklist, including a real representative recipe, uneven sequence durations, boundary scrubbing, editing and recalculation, Excel/JSON compatibility, and corrected-header safety.
- Risk register, open questions, and decisions requiring my approval.

Do not invent repository facts. If something cannot be established, say what must be inspected or tested. **Stop after producing the plan; do not start implementation.**
