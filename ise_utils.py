"""
ise_utils.py
------------
Helpers for extracting ellipsometer thickness data from iSE CSV exports.

Supported input variants:
- Properly split two-column CSV after two header rows.
- Single-column rows containing tab-separated values wrapped in quotes,
  e.g. "5.540308\t0.172921\t".
"""

from __future__ import annotations

import csv
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
