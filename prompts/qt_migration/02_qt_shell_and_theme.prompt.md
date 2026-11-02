---
description: "Qt migration step 02 — application shell, navigation, and dark theme"
---

# 02 — Qt application shell, navigation, and theme

Prerequisite: 01 complete (PySide6 installed, tests passing). Read the plan's **Mockup-to-widget mapping → Shared application shell** and the two mockups in `prompts/` (`Reactor Recipe Editor Dashboard.png`, `Purple Reactor Analysis Dashboard.png`).

## Tasks

1. Create package `reactor_ui/` with `app.py` (QApplication creation, high-DPI defaults, theme application, `main()`), `main_window.py`, and `theme.py`.
2. `theme.py`: a small token set (background, surface/card, card border, text, muted text, primary violet, focus, selection, error, warning, success) sampled approximately from the mockups; a `QPalette` and a QSS string built from those tokens. Segoe UI / system font stack. Visible keyboard focus.
3. `main_window.py`: `QMainWindow` with a left navigation rail (`QFrame` + checkable `QToolButton`s in an exclusive group) and a `QStackedWidget`. Navigation entries: **Analyze**, **Recipe Editor**, **Plots & Animation**, **Settings**, **Help**. Pages not yet implemented must show nothing fake: either omit them from the rail or show a plain "Not yet migrated — use the current app" notice. Do not invent features.
4. A reusable `Card` widget (title + content layout) and a page-header widget (title + subtitle + action area) under `reactor_ui/widgets/`.
5. Initial window ~1440×900, minimum ~1180×720.
6. Temporary developer launcher `run_qt_dev.py` at repo root calling `reactor_ui.app.main()`. Do **not** change `reactor_plotter.py`, `gui.py`, `run_gui.bat`, or `setup.bat` yet.
7. Tests (`tests/test_qt_shell.py`, offscreen): window constructs, navigation switches pages, theme applies without QSS parse warnings.

## Acceptance

- `.\.venv\Scripts\python.exe run_qt_dev.py` opens the themed shell.
- Offscreen screenshot saved to a temp path looks structurally like the mockup shell (rail + content).
- All tests pass; Tk app unchanged.
