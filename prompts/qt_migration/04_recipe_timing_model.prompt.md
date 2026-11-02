---
description: "Qt migration step 04 — pure recipe timing model"
---

# 04 — Pure recipe timing model

Prerequisite: 03. Read the plan's **Timing timeline and authoritative model** and **Resolved owner decisions** items 1–3.

## Tasks

1. `reactor_ui/models/recipe_timing.py` (no Qt imports): dataclasses `PhaseEvent(slot, valve, row_index, start_s, duration_s)`, `SequenceTiming(index, first_row, row_indices, cycle_count, cycle_duration_s, start_s, end_s, events)`, `RunTiming(sequences, run_duration_s)`.
2. `compute_run_timing(rows)` takes normalized source rows (as from `extract_timing_table`) and returns `RunTiming`. Slot order `PrePump, N2Dose, PumpDose, Dose, Hold, PrePurge, Purge`; serial execution; numbered Cycle = new sequence; blank/zero = continuation. Rows before the first numbered row are reported as a validation error, not silently dropped.
3. Validation: non-finite or negative durations, non-integer or negative cycle counts → structured errors with (row, column).
4. Helpers: `sequence_at(run, t)` with half-open `[start, end)` and final-endpoint clamp; `cycle_index(seq, t)`; `phase_summary(seq)` → total first, then per-slot per-cycle seconds, total seconds, and fraction (`None` when undefined).
5. Make `convert_to_json.estimate_process_seconds()` (from 03) and this model agree; add a test asserting equality on every fixture.
6. Tests: owner's 4-sequence example; unequal durations; zero-duration sequences; empty recipe; boundaries; many sequences (performance proportional to rows, not cycles — e.g. 10⁶ cycles is instant).

7. **Flagged label mismatch:** `sequence_utils.PHASE_TYPES` is `prepump, dosepump, dosen2, dose, hold, prepurge, purge`, but the owner-confirmed slot order is `PrePump, N2Dose, PumpDose, …`, so slots 2 and 3 are labelled swapped in post-run phase names (timing values are unaffected; the leak-rate check is symmetric). Define one shared slot-label constant used by the timing model, recipe table, and header editor. Change `PHASE_TYPES` to `prepump, dosen2, dosepump, …` only with a note in the summary that post-run phase-name labels in new outputs will change, and add a test pinning the order.

## Acceptance

All timing tests pass; no Qt dependency in the model; converter and model durations agree.
