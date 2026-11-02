"""Shared recipe timing identities and per-cycle arithmetic."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


SLOT_LABELS = ("PrePump", "N2Dose", "PumpDose", "Dose", "Hold", "PrePurge", "Purge")
PHASE_NAMES = ("prepump", "dosen2", "dosepump", "dose", "hold", "prepurge", "purge")
TIMING_COLUMNS = ("Cycle", "Valve", *SLOT_LABELS, "Notes")


def cycle_seconds(phase_rows: Iterable[Sequence[float]]) -> float:
    """Sum phase durations in source-row order, as the converter does."""
    total = 0.0
    for row in phase_rows:
        total += sum(row)
    return total
