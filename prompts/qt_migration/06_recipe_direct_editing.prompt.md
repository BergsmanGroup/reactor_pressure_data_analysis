---
description: "Qt migration step 06 — direct editing, clipboard, undo/redo, validation"
---

# 06 — Direct recipe editing

Prerequisite: 05. Read the plan's **Clipboard, row operations, validation, undo**.

## Tasks

1. Make `RecipeTableModel` editable (except `#`/`Seq`). Edits go through `RecipeDocument`, which owns the draft rows and a `QUndoStack`.
2. Delegates: integer cycle (blank allowed = continuation), valve number (validated against Valve Metadata), non-negative float seconds for timing slots, free text Notes.
3. Undo commands: cell edit, rectangular TSV paste (one undo step), row insert above/below, row delete, plus metadata edits (wait time, start time, info, valve metadata).
4. Clipboard: Ctrl+C copies selection as TSV; Ctrl+V pastes a rectangle starting at the current cell; report shape/type errors without partial application.
5. Validation is per-cell (decoration + tooltip) and document-level (footer). Invalid text stays visible. Export disabled while blocking errors exist.
6. Every valid change recomputes `RunTiming` once and updates timeline, summary, run duration, and predicted end time.
7. Export builds the payload from the **draft** (construct a DataFrame in the same layout `build_payload()` expects, or add a narrow builder that shares its normalization) — never writes Excel. Dirty indicator tracks the undo stack clean index; prompt on New/Open/close with unsaved draft changes.
8. Tests: edit → recompute; paste → one undo step; undo/redo exact restore; invalid blocks export; exported draft payload matches an equivalent sheet's payload; source hash unchanged.
