---
description: "Qt migration step 09 — Qt header editor with overwrite safety"
---

# 09 — Qt header-correction dialog with overwrite safety

Prerequisite: 07. Owner decision: *"we need to be extra safe about editing in place … be careful about executing any overwrites and include lots of warning about what files are going to be affected."*

## Tasks

1. Port `HeaderEditorDialog` to a Qt dialog (`reactor_ui/dialogs/header_editor_dialog.py`) using the same model/delegate table approach as the recipe editor, owner-confirmed slot labels, row insert/delete, and reset.
2. Before any write, compute a **change plan** (pure function, testable): every file that will be rewritten, renamed, or created (selected NDJSON, header text file, associated artifacts from `header_text` path helpers), with old → new paths.
3. Show a confirmation dialog listing every affected file, clearly stating "This will overwrite the following files", requiring an explicit typed or checkbox confirmation. Default button = Cancel.
4. Create a timestamped backup of every file to be overwritten (e.g. `<name>.bak-YYYYMMDD-HHMMSS`) before writing; write via temp file + atomic replace; on any failure, stop and report which files were changed and where backups are.
5. Apply the same plan/confirm/backup treatment to "use header text as raw header" and any other in-place rewrite path currently in `gui.py`.
6. Tests: change-plan contents for representative cases; backup created; failure mid-way leaves originals restorable; cancel writes nothing.
