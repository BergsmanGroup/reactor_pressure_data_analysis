"""
ise_utils.py
------------
Helpers for extracting ellipsometer thickness data from iSE exports.

Supported input variants:
- Properly split two-column CSV after two header rows (``parse_ise_thickness``).
- Single-column rows containing tab-separated values wrapped in quotes,
  e.g. "5.540308\t0.172921\t".
- Cycle-aligned exports (xlsx or csv) with ``Cycle``/``Thickness`` columns,
  e.g. one row per half-cycle measurement (``parse_ise_cycle_thickness``).
"""

from __future__ import annotations

import csv
import io
import math
import re
from pathlib import Path

_NUM_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _to_numeric_tokens(parts: list[str]) -> list[float]:
    nums: list[float] = []
    for part in parts:
        token = part.strip().strip('"')
        if not token:
            continue
        try:
            nums.append(float(token))
            continue
        except ValueError:
            pass
        for match in _NUM_RE.findall(token):
            try:
                nums.append(float(match))
            except ValueError:
                continue
    return nums


def parse_ise_thickness(ise_csv_path: str | Path) -> list[float]:
    """Return thickness values parsed from an iSE CSV export."""
    path = Path(ise_csv_path)
    if path.suffix.casefold() in {".xlsx", ".xls"}:
        return []
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    except (OSError, UnicodeError):
        return []
    if not lines:
        return []

    thickness_vals: list[float] = []
    header_index = None
    thickness_index = None
    for index, raw in enumerate(lines[:5]):
        try:
            row = next(csv.reader([raw]))
        except csv.Error:
            continue
        for column, value in enumerate(row):
            if value.strip().casefold().startswith("thickness"):
                header_index = index
                thickness_index = column
                break
        if thickness_index is not None:
            break

    start_index = header_index + 1 if header_index is not None else min(2, len(lines))
    for raw in lines[start_index:]:
        line = raw.strip()
        if not line:
            continue

        # Handle quoted single-column tab-delimited rows first.
        if "\t" in line:
            parts = [p for p in line.strip().strip('"').split("\t") if p.strip()]
        else:
            parsed_rows = list(csv.reader([line]))
            parts = parsed_rows[0] if parsed_rows else []

        if thickness_index is not None and thickness_index < len(parts):
            try:
                value = float(parts[thickness_index].strip().strip('"'))
            except ValueError:
                continue
            if math.isfinite(value):
                thickness_vals.append(value)
            continue

        nums = _to_numeric_tokens(parts)
        if len(nums) >= 2 and math.isfinite(nums[1]):
            thickness_vals.append(nums[1])

    return thickness_vals


def map_ise_thickness_to_cycles(
    thickness_values: list[float],
    cycles: list[int],
    cycle_sequence_map: dict[int, str],
    phased_sequences: dict,
    ise_valve: str = "Valve7",
    first_cycle: float = 1.0,
) -> dict[int, dict[str, list]]:
    """Assign sequential iSE readings to occurrences of *ise_valve*.

    Every cycle receives the maximum number of valve-occurrence rows found in
    the recipe. Missing readings are represented by ``None`` so figure
    summaries can render them as ``NaN``.
    """
    target = str(ise_valve).strip()
    start_cycle = int(math.floor(first_cycle))
    start_instance = 1 if first_cycle - start_cycle >= 0.5 else 0

    instances_by_cycle: dict[int, int] = {}
    for cycle in cycles:
        if cycle < start_cycle:
            continue
        seq_key = cycle_sequence_map.get(cycle)
        valve_rows = phased_sequences.get(seq_key, {}).get("valve_rows", [])
        instances_by_cycle[cycle] = sum(
            1 for valve, _timing in valve_rows if str(valve) == target
        )

    max_instances = max(instances_by_cycle.values(), default=0)
    if max_instances == 0:
        return {}

    values_by_slot: dict[tuple[int, int], float] = {}
    value_index = 0
    for cycle in cycles:
        count = instances_by_cycle.get(cycle, 0)
        first_instance = start_instance if cycle == start_cycle else 0
        for instance in range(first_instance, count):
            if value_index >= len(thickness_values):
                break
            values_by_slot[(cycle, instance)] = thickness_values[value_index]
            value_index += 1

    return {
        cycle: {
            "Cycle": [cycle + 0.5 * instance for instance in range(max_instances)],
            "ThicknessNm": [
                values_by_slot.get((cycle, instance))
                for instance in range(max_instances)
            ],
        }
        for cycle in cycles
        if cycle >= start_cycle
    }


def save_ise_thickness_csv(
    ise_csv_path: str | Path,
    output_csv_path: str | Path,
    blank_rows: int = 0,
) -> int:
    """Parse iSE thickness data and write it as a single-column CSV."""
    thickness_vals = parse_ise_thickness(ise_csv_path)
    out_path = Path(output_csv_path)
    blank_rows = max(0, int(blank_rows))

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["thickness"])
        for idx, value in enumerate(thickness_vals):
            writer.writerow([f"{value:.6f}"])
            if idx < len(thickness_vals) - 1:
                for _ in range(blank_rows):
                    writer.writerow([""])

    return len(thickness_vals)


def parse_ise_cycle_thickness(ise_path: str | Path) -> dict[int, dict[str, list]]:
    """
    Parse a cycle-aligned iSE export (xlsx or csv) with ``Cycle`` and
    ``Thickness ...`` columns -- e.g. a half-cycle thickness log with rows
    at ``Cycle = 0, 0.5, 1, 1.5, ...``.

    Returns ``{cycle_int: {"Cycle": [c0, c1, ...], "ThicknessNm": [t0, t1, ...]}}``
    grouping every row by ``floor(cycle)``, so cycle 1's bucket holds both
    its own reading and any half-cycle reading at 1.5.

    Returns an empty dict (rather than raising) if the file doesn't have a
    recognizable ``Cycle``/``Thickness`` column pair, so callers can try
    this opportunistically alongside the simpler ``parse_ise_thickness``.
    """
    import pandas as pd

    path = Path(ise_path)
    ext = path.suffix.lower()
    try:
        if ext in (".xlsx", ".xls"):
            with path.open("rb") as fh:
                data = fh.read()
            df = pd.read_excel(io.BytesIO(data))
        elif ext == ".csv":
            df = pd.read_csv(path)
        else:
            return {}
    except Exception:
        return {}

    cycle_col = next((c for c in df.columns if str(c).strip().lower() == "cycle"), None)
    thickness_col = next(
        (c for c in df.columns if str(c).strip().lower().startswith("thickness")), None
    )
    if cycle_col is None or thickness_col is None:
        return {}

    by_cycle: dict[int, dict[str, list]] = {}
    for cycle_value, thickness_value in zip(df[cycle_col], df[thickness_col]):
        try:
            cycle_f = float(cycle_value)
            thickness_f = float(thickness_value)
        except (TypeError, ValueError):
            continue
        if math.isnan(cycle_f) or math.isnan(thickness_f):
            continue
        bucket = by_cycle.setdefault(int(math.floor(cycle_f)), {"Cycle": [], "ThicknessNm": []})
        bucket["Cycle"].append(cycle_f)
        bucket["ThicknessNm"].append(thickness_f)

    return by_cycle
