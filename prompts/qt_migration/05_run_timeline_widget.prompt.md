---
description: "Qt migration step 05 — run timeline, sequence details, and table synchronization"
---

# 05 — Run timeline widget and synchronization

Prerequisite: 04. Read the plan's **Interactions and edge cases** and **Visual discrepancies and precedence**.

## Tasks

1. `reactor_ui/widgets/run_timeline.py`: custom-painted `QWidget` consuming `RunTiming`. One full-run bar with one block per sequence, proportional widths, elapsed-time ruler with s/min/h units, draggable playhead, selected-sequence outline, tooltips (sequence #, cycles, start/end/duration). Click/drag/keyboard (Left/Right between sequence boundaries, Home/End). Signals: `playheadChanged(float)`, `sequenceSelected(int)`. No per-cycle drawing or widgets.
2. Representative-cycle strip below the bar: the selected sequence's one cycle as proportional phase blocks coloured by slot identity (separate palette from sequences), plus current cycle index `floor(elapsed_in_seq / cycle_duration) + 1`.
3. `reactor_ui/widgets/phase_summary.py`: compact read-only summary (total first, then per-slot per-cycle / total / fraction, "—" for undefined).
4. Replace the 03 placeholder card with timeline + cycle strip + summary + a precise time control (`QDoubleSpinBox` or time edit).
5. Synchronize: selecting a sequence scrolls/selects its rows in the single `QTableView`; selecting a table row moves the playhead to that sequence start. Scrubbing never edits data.
6. Empty recipe → empty state. Wait time is not drawn in the bar (shown in metadata card only).
7. Tests (offscreen): block width ratios, boundary hit-testing, keyboard navigation, table selection sync, exactly one editable table on the page.

## Acceptance

Timeline matches hand-calculated proportions for the owner's 4-sequence example; selection sync works in both directions.
