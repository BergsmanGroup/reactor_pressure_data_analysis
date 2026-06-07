"""
data_parser.py
--------------
Streaming parser for the InSitu Reactor newline-delimited JSON log format.

Supports two on-disk formats:

  RAW (original)
    One NDJSON record per measurement.  Pressure values are in
    ``{"type":"pressure"}`` records; step context is in separate
    ``{"type":"step"}`` records that appear before each pressure burst.

  CONDENSED
    One ``{"type":"data"}`` record per pressure measurement, with the
    ``CurrentStep`` from the immediately preceding step folded in.
    Created by ``condense_log()``.  Smaller and faster to re-parse.

Public API
----------
read_header(path) -> dict
    Read only the first line and return the parsed header payload.

stream_pressure(path, wait_time, progress_cb) -> (cycle_points, cycle_start_map)
    Stream all pressure records from either format.

    cycle_points    : {cycle_int: [(t_s, pressure), ...]}
    cycle_start_map : {cycle_int: t0_s}   (absolute time of first point)

condense_log(input_path, output_path) -> int
    Convert a raw log to the condensed format and return the number of
    data rows written.

condensed_path(raw_path) -> Path
    Return the conventional condensed-file path for a raw log.
"""

import json
from pathlib import Path


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _parse_payload(raw_payload):
    """Normalise payload — may arrive as a dict or a JSON-encoded string."""
    if isinstance(raw_payload, str):
        s = raw_payload.strip()
        if s and s[0] in "{[":
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                pass
    return raw_payload if isinstance(raw_payload, dict) else {}


# ---------------------------------------------------------------------------
#  Public functions
# ---------------------------------------------------------------------------

def read_header(path: str | Path) -> dict:
    """
    Read the first line of *path* and return the header payload dict.

    Raises
    ------
    ValueError
        If the first line is not a ``type == "header"`` record.
    """
    with open(path, encoding="utf-8") as fh:
        first = fh.readline()

    obj = json.loads(first)
    pl  = _parse_payload(obj.get("payload", {}))

    if obj.get("type") != "header":
        raise ValueError("First line is not a header record.")

    return pl


def stream_pressure(
    path:        str | Path,
    wait_time:   float = 0.0,
    progress_cb = None,
) -> tuple[dict, dict]:
    """
    Stream-parse *path* and return pressure data grouped by cycle.

    Parameters
    ----------
    path : str or Path
        Absolute path to the NDJSON log file.
    wait_time : float
        Discard all pressure records with ``TimeElapsed / 1000 < wait_time``.
    progress_cb : callable(bytes_read, file_size) or None
        Optional callback invoked periodically so the caller can update a
        progress indicator.  Called roughly every 4 MB of input.

    Returns
    -------
    cycle_points : dict[int, list[tuple[float, float]]]
        ``{cycle: [(t_s, pressure), ...]}`` — unsorted within each cycle.
    cycle_start_map : dict[int, float]
        ``{cycle: t0_s}`` — absolute time (s) of the first pressure point
        in each cycle.
    """
    path      = Path(path)
    file_size = max(path.stat().st_size, 1)

    cycle_points:    dict[int, list]  = {}
    bytes_read = 0

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            bytes_read += len(line.encode())

            try:
                obj   = json.loads(line)
                rtype = obj.get("type")
                # Accept raw 'pressure' rows and condensed 'data' rows.
                if rtype not in ("pressure", "data"):
                    continue
                pl    = _parse_payload(obj.get("payload", {}))
                t_s   = float(pl["TimeElapsed"]) / 1000.0
                if t_s < wait_time:
                    continue
                pval  = float(pl["Pressure"])
                cycle = int(pl["CurrentCycle"])
                if cycle < 1:
                    continue
                cycle_points.setdefault(cycle, []).append((t_s, pval))
            except Exception:
                pass

            if progress_cb and bytes_read % 4_000_000 < 4_000:
                progress_cb(bytes_read, file_size)

    # Build cycle_start_map from the minimum time in each cycle
    cycle_start_map: dict[int, float] = {}
    for cyc, pts in cycle_points.items():
        cycle_start_map[cyc] = min(t for t, _ in pts)

    return cycle_points, cycle_start_map


def condensed_path(raw_path: str | Path) -> Path:
    """
    Return the conventional path for the condensed version of *raw_path*.

    Example: ``foo_Data.json`` → ``foo_Data_condensed.json``
    """
    p = Path(raw_path)
    return p.with_name(f"{p.stem}_condensed{p.suffix}")


def condense_log(
    input_path:  str | Path,
    output_path: str | Path | None = None,
    progress_cb = None,
) -> int:
    """
    Convert a raw NDJSON log into the condensed format.

    Each ``pressure`` record is merged with the ``CurrentStep`` value from
    the most recent preceding ``step`` record to produce a single ``data``
    record.  The header and footer lines are copied unchanged.  All other
    record types (pure ``step`` rows, etc.) are omitted.

    Parameters
    ----------
    input_path : str or Path
    output_path : str, Path, or None
        Destination file.  Defaults to ``condensed_path(input_path)``.
    progress_cb : callable(bytes_read, file_size) or None

    Returns
    -------
    int
        Number of ``data`` rows written.
    """
    input_path  = Path(input_path)
    output_path = Path(output_path) if output_path else condensed_path(input_path)
    file_size   = max(input_path.stat().st_size, 1)

    last_step_payload: dict = {}
    rows_written = 0
    bytes_read   = 0

    with input_path.open(encoding="utf-8") as fh_in, \
         output_path.open("w", encoding="utf-8") as fh_out:

        for line in fh_in:
            bytes_read += len(line.encode())

            try:
                obj   = json.loads(line)
                rtype = obj.get("type")

                # Always copy header and footer verbatim.
                if rtype in ("header", "footer"):
                    fh_out.write(line if line.endswith("\n") else line + "\n")
                    continue

                # Track the most recent step context.
                if rtype == "step":
                    last_step_payload = _parse_payload(obj.get("payload", {}))
                    continue

                # Merge step context into each pressure record.
                if rtype == "pressure":
                    pl = _parse_payload(obj.get("payload", {}))
                    merged = {
                        "TimeElapsed": pl.get("TimeElapsed", ""),
                        "CurrentCycle": pl.get("CurrentCycle", ""),
                        "CurrentStep": last_step_payload.get("CurrentStep", ""),
                        "Pressure": pl.get("Pressure", ""),
                        "GUID": pl.get("GUID", ""),
                    }
                    data_row = {
                        "type": "data",
                        "meta": "",
                        "payload": json.dumps(merged, ensure_ascii=False,
                                              separators=(",", ":")),
                    }
                    fh_out.write(json.dumps(data_row,
                                            ensure_ascii=False,
                                            separators=(",", ":")) + "\n")
                    rows_written += 1

            except Exception:
                pass

            if progress_cb and bytes_read % 4_000_000 < 4_000:
                progress_cb(bytes_read, file_size)

    return rows_written


def subtract_baseline(cycle_points: dict) -> tuple[dict, float]:
    """
    Find the global minimum pressure across all cycles and subtract it from
    every pressure measurement in *cycle_points*.  Modifies the dict in-place.

    Returns ``(cycle_points, baseline_mTorr)`` so the caller can log the
    corrected offset.
    """
    if not cycle_points:
        return cycle_points, 0.0

    min_p = min(
        pval
        for pts in cycle_points.values()
        for _, pval in pts
    )

    for cyc in cycle_points:
        cycle_points[cyc] = [(t, p - min_p) for t, p in cycle_points[cyc]]

    return cycle_points, min_p
