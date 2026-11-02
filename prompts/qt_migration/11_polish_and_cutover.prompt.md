---
description: "Qt migration step 11 — polish, accessibility, and launcher cutover"
---

# 11 — Visual/accessibility polish and cutover

Prerequisite: 03–10 complete and parity verified against the Tk app on the same fixtures.

## Tasks

1. Visual review against both mockups at 1670×940 and at 100/150/200% scaling; fix clipping, splitter minimums, table row heights, icon sizes.
2. Keyboard-only navigation, focus order, accessible names on the rail and custom widgets.
3. Long-recipe performance check (hundreds of rows, large cycle counts).
4. Cutover: `reactor_plotter.py` starts `reactor_ui.app.main()`; `run_gui.bat` launches `reactor_plotter.py`; `setup.bat` message matches. Remove `run_qt_dev.py`.
5. Remove Tk UI code (`gui.py` Tk parts, Tk `HeaderEditorDialog`) only after parity sign-off; keep backend helpers they host by moving them to non-UI modules if needed.
6. Update `WHITEPAPER.md`, the plan doc, and a short README section on running and testing.
7. Full test suite passes.
