"""Validated, Qt-independent timing model for source recipe rows."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence

from recipe_timing_core import SLOT_LABELS, TIMING_COLUMNS, cycle_seconds


@dataclass(frozen=True)
class TimingIssue:
    row: int
    column: int
    message: str


class RecipeTimingError(ValueError):
    def __init__(self, issues: Sequence[TimingIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in issues))


@dataclass(frozen=True)
class PhaseEvent:
    slot: str
    valve: int
    row_index: int
    start_s: float
    duration_s: float


@dataclass(frozen=True)
class SequenceTiming:
    index: int
    first_row: int
    row_indices: tuple[int, ...]
    cycle_count: int
    cycle_duration_s: float
    start_s: float
    end_s: float
    events: tuple[PhaseEvent, ...]


@dataclass(frozen=True)
class RunTiming:
    sequences: tuple[SequenceTiming, ...]
    run_duration_s: float


@dataclass(frozen=True)
class PhaseSummary:
    name: str
    per_cycle_s: float
    total_s: float
    fraction: float | None


def _integer(value: object, *, blank_is_zero: bool) -> int | None:
    text = str(value).strip()
    if not text and blank_is_zero:
        return 0
    try:
        number = Decimal(text)
        if not number.is_finite() or not math.isfinite(float(number)) or number != number.to_integral_value():
            return None
        return int(number)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def compute_run_timing(rows: Sequence[Sequence[object]]) -> RunTiming:
    """Validate source rows and compute serial, per-sequence timing."""
    issues: list[TimingIssue] = []
    parsed: list[tuple[int, int, list[float]]] = []
    have_sequence = False

    for row_index, row in enumerate(rows):
        if len(row) < 9:
            issues.append(TimingIssue(row_index, len(row), "A timing row must contain Cycle, Valve and seven slots."))
            continue
        cycles = _integer(row[0], blank_is_zero=True)
        if cycles is None or cycles < 0:
            issues.append(TimingIssue(row_index, 0, "Cycle must be a non-negative integer."))
            cycles = 0
        elif cycles > 0:
            have_sequence = True
        elif not have_sequence:
            issues.append(TimingIssue(row_index, 0, "The first row must start a sequence with a positive Cycle count."))

        valve = _integer(row[1], blank_is_zero=False)
        if valve is None or valve <= 0:
            issues.append(TimingIssue(row_index, 1, "Valve must be a positive integer."))
            valve = 0

        phases: list[float] = []
        for column, value in enumerate(row[2:9], start=2):
            text = str(value).strip()
            try:
                seconds = float(text) if text else 0.0
            except ValueError:
                seconds = math.nan
            if not math.isfinite(seconds) or seconds < 0:
                issues.append(
                    TimingIssue(row_index, column, f"{TIMING_COLUMNS[column]} must be a finite non-negative number.")
                )
                seconds = 0.0
            phases.append(seconds)
        parsed.append((cycles, valve, phases))

    if issues:
        raise RecipeTimingError(issues)
    if not parsed:
        return RunTiming((), 0.0)

    groups: list[list[tuple[int, int, int, list[float]]]] = []
    for row_index, (cycles, valve, phases) in enumerate(parsed):
        if cycles > 0:
            groups.append([])
        groups[-1].append((row_index, cycles, valve, phases))

    sequences: list[SequenceTiming] = []
    elapsed = 0.0
    for index, group in enumerate(groups, start=1):
        count = group[0][1]
        duration = cycle_seconds(item[3] for item in group)
        sequence_duration = duration * count
        end = elapsed + sequence_duration
        if not math.isfinite(duration) or not math.isfinite(sequence_duration) or not math.isfinite(end):
            raise RecipeTimingError(
                [TimingIssue(group[0][0], 0, "The estimated duration is outside the supported numeric range.")]
            )

        events: list[PhaseEvent] = []
        row_start = 0.0
        for row_index, _, valve, phases in group:
            phase_start = row_start
            for slot, seconds in zip(SLOT_LABELS, phases):
                if seconds:
                    events.append(PhaseEvent(slot, valve, row_index, phase_start, seconds))
                phase_start += seconds
            row_start += sum(phases)

        sequences.append(
            SequenceTiming(
                index=index,
                first_row=group[0][0],
                row_indices=tuple(item[0] for item in group),
                cycle_count=count,
                cycle_duration_s=duration,
                start_s=elapsed,
                end_s=end,
                events=tuple(events),
            )
        )
        elapsed = end
    return RunTiming(tuple(sequences), elapsed)


def sequence_at(run: RunTiming, time_s: float) -> SequenceTiming | None:
    """Resolve elapsed time using half-open intervals and a final-end clamp."""
    if not math.isfinite(time_s):
        raise ValueError("Elapsed time must be finite.")
    if not run.sequences:
        return None
    if time_s >= run.run_duration_s:
        return run.sequences[-1]
    time_s = max(0.0, time_s)
    return next((seq for seq in run.sequences if seq.start_s <= time_s < seq.end_s), run.sequences[-1])


def cycle_index(sequence: SequenceTiming, time_s: float) -> int | None:
    if not math.isfinite(time_s):
        raise ValueError("Elapsed time must be finite.")
    if sequence.cycle_duration_s <= 0:
        return None
    if time_s >= sequence.end_s:
        return sequence.cycle_count
    elapsed = max(0.0, time_s - sequence.start_s)
    completed = int(elapsed / sequence.cycle_duration_s)
    if elapsed >= (completed + 1) * sequence.cycle_duration_s:
        completed += 1
    elif completed > 0 and elapsed < completed * sequence.cycle_duration_s:
        completed -= 1
    return min(sequence.cycle_count, completed + 1)


def phase_summary(sequence: SequenceTiming) -> tuple[PhaseSummary, ...]:
    totals = {slot: 0.0 for slot in SLOT_LABELS}
    for event in sequence.events:
        totals[event.slot] += event.duration_s
    fraction = 1.0 if sequence.cycle_duration_s > 0 else None
    rows = [PhaseSummary("Total", sequence.cycle_duration_s, sequence.end_s - sequence.start_s, fraction)]
    for slot in SLOT_LABELS:
        per_cycle = totals[slot]
        rows.append(
            PhaseSummary(
                slot,
                per_cycle,
                per_cycle * sequence.cycle_count,
                per_cycle / sequence.cycle_duration_s if sequence.cycle_duration_s > 0 else None,
            )
        )
    return tuple(rows)
