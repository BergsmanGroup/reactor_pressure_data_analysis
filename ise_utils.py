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
    lines = path.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    if len(lines) <= 2:
        return []

    thickness_vals: list[float] = []

    # Skip two header rows by file convention.
    for raw in lines[2:]:
        line = raw.strip()
        if not line:
            continue

        # Handle quoted single-column tab-delimited rows first.
        if "\t" in line:
            parts = [p for p in line.strip().strip('"').split("\t") if p.strip()]
        else:
            parsed_rows = list(csv.reader([line]))
            parts = parsed_rows[0] if parsed_rows else []

        nums = _to_numeric_tokens(parts)
        if len(nums) >= 2:
            thickness_vals.append(nums[1])

    return thickness_vals


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
