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

condense_log(input_path, output_path, ..., return_stats=False) -> int|dict
    Convert a raw log to the condensed format and return the number of
    data rows written, or detailed stats when ``return_stats=True``.

condensed_path(raw_path) -> Path
    Return the conventional condensed-file path for a raw log.
"""

import json
import os
import tempfile
from bisect import bisect_left
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


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


def _parse_log_timestamp(value):
    """Parse the ISO timestamps emitted by the temperature controller."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    return parsed.timestamp()


def _temperature_record(obj):
    """Return ``(timestamp, zones)`` for a telemetry record, if present."""
    if not isinstance(obj, dict):
        return None
    timestamp = _parse_log_timestamp(obj.get("ts"))
    telemetry = obj.get("telemetry")
    if timestamp is None or not isinstance(telemetry, dict):
        return None
    raw_zones = telemetry.get("zones")
    if not isinstance(raw_zones, dict):
        return None
    zones = {}
    for zone, values in raw_zones.items():
        if not isinstance(values, dict):
            continue
        if "pv_c" not in values and "sp_abs" not in values:
            continue
        zones[str(zone)] = {
            "TemperatureC": values.get("pv_c"),
            "SetPointC": values.get("sp_abs"),
        }
    return (timestamp, zones) if zones else None


def load_temperature_data(source: str | Path) -> list[tuple[float, dict]]:
    """Load temperature samples from a telemetry directory or run log file."""
    source_path = Path(source)
    if source_path.is_dir():
        paths = sorted(
            path for path in source_path.rglob("*")
            if path.is_file() and path.suffix.casefold() in {".jsonl", ".log", ".json"}
        )
    elif source_path.is_file():
        paths = [source_path]
    else:
        raise FileNotFoundError(f"Temperature source does not exist: {source}")

    samples = []
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    record = _temperature_record(json.loads(line))
                except (json.JSONDecodeError, TypeError):
                    continue
                if record:
                    samples.append(record)
    samples.sort(key=lambda item: item[0])
    return samples


def temperature_zones(samples: list[tuple[float, dict]]) -> list[str]:
    """Return the sorted zone identifiers present in temperature samples."""
    return sorted(
        {zone for _, zones in samples for zone in zones},
        key=lambda value: (int(value) if value.isdigit() else float("inf"), value),
    )


def load_service_config_data(source: str | Path) -> list[tuple[float, dict]]:
    """Load timestamped temperature connection metadata from service logs."""
    source_path = Path(source)
    directory = source_path if source_path.is_dir() else source_path.parent
    paths = sorted(directory.glob("*_service_config_log.jsonl"))
    samples = []
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                timestamp = _parse_log_timestamp(obj.get("ts"))
                config = obj.get("config")
                if timestamp is None or not isinstance(config, dict):
                    continue
                zone_names = config.get("zone_names", {})
                if not isinstance(zone_names, dict):
                    zone_names = {}
                samples.append((timestamp, {
                    "com_port": config.get("last_serial_port", ""),
                    "tcp_host": config.get("last_tcp_host", ""),
                    "zone_names": {
                        str(zone): str(name)
                        for zone, name in zone_names.items()
                    },
                }))
    samples.sort(key=lambda item: item[0])
    return samples


def _service_config_at(samples, times, timestamp):
    if not samples or timestamp is None:
        return None
    index = bisect_left(times, timestamp)
    if index == len(samples) or times[index] > timestamp:
        index -= 1
    return samples[index][1] if index >= 0 else None


def _header_start_timestamp(payload: dict):
    value = payload.get("startTime")
    if not isinstance(value, str):
        return None
    # Header timestamps append "(PST/PDT)" rather than a numeric offset.
    value = value.split(" (", 1)[0].strip()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    return parsed.timestamp()


def _temperature_at(samples, times, timestamp):
    if not samples or timestamp is None:
        return None
    index = bisect_left(times, timestamp)
    if index == 0:
        nearest = 0
    elif index == len(samples):
        nearest = index - 1
    else:
        nearest = index if times[index] - timestamp < timestamp - times[index - 1] else index - 1
    return samples[nearest][1]


def detect_sample_interval_s(samples: list[tuple[float, dict]]) -> float | None:
    """
    Return the median interval (seconds) between consecutive sample
    timestamps, or None if fewer than two samples are available. Used to
    auto-suggest an "effective sample interval" for downsampling.
    """
    if len(samples) < 2:
        return None
    deltas = sorted(
        b[0] - a[0] for a, b in zip(samples, samples[1:]) if b[0] > a[0]
    )
    if not deltas:
        return None
    mid = len(deltas) // 2
    if len(deltas) % 2:
        return deltas[mid]
    return (deltas[mid - 1] + deltas[mid]) / 2.0


def downsample_samples(
    samples: list[tuple[float, dict]], interval_s: float | None
) -> list[tuple[float, dict]]:
    """
    Keep only the first sample within each *interval_s*-wide time bucket.
    Returns *samples* unchanged if *interval_s* is falsy or samples are empty.
    Samples must already be sorted by timestamp (as returned by
    ``load_temperature_data``/``load_service_config_data``).
    """
    if not interval_s or interval_s <= 0 or not samples:
        return samples
    kept: list[tuple[float, dict]] = []
    next_allowed = float("-inf")
    for sample in samples:
        if sample[0] >= next_allowed:
            kept.append(sample)
            next_allowed = sample[0] + interval_s
    return kept


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
    target_cycle: int | None = None,
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
    target_cycle : int or None
        If provided, retain only this explicitly-labelled cycle.  Raw files
        are ordered by cycle, so parsing stops when a later cycle is reached.

    Returns
    -------
    cycle_points : dict[int, list[tuple[float, float]]]
        ``{cycle: [(t_s, pressure), ...]}`` — unsorted within each cycle.
    cycle_start_map : dict[int, float]
        ``{cycle: t0_s}`` — absolute time (s) of the first retained pressure
        point in each cycle, after ``wait_time`` filtering.
    """
    path      = Path(path)
    file_size = max(path.stat().st_size, 1)

    cycle_points:    dict[int, list]  = {}
    cycle_start_map: dict[int, float] = {}
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
                cycle = int(pl["CurrentCycle"])
                if t_s < wait_time:
                    continue
                if target_cycle is not None and cycle > target_cycle:
                    break
                if cycle >= 1 and cycle not in cycle_start_map:
                    cycle_start_map[cycle] = t_s
                pval  = float(pl["Pressure"])
                if cycle < 1:
                    continue
                if target_cycle is None or cycle == target_cycle:
                    cycle_points.setdefault(cycle, []).append((t_s, pval))
            except Exception:
                pass

            if progress_cb and bytes_read % 4_000_000 < 4_000:
                progress_cb(bytes_read, file_size)

    # Ensure trimmed-in cycles always have a t0, even if no earlier points existed.
    for cyc, pts in cycle_points.items():
        if cyc not in cycle_start_map and pts:
            cycle_start_map[cyc] = min(t for t, _ in pts)

    return cycle_points, cycle_start_map


def condensed_path(raw_path: str | Path) -> Path:
    """
    Return the conventional path for the condensed version of *raw_path*.

    Example: ``foo_Data.json`` → ``foo_Data_condensed.json``
    """
    p = Path(raw_path)
    return p.with_name(f"{p.stem}_condensed{p.suffix}")


def is_condensed_file(path: str | Path) -> bool:
    """
    Return True if *path* is already a condensed log.

    Detection uses two independent signals:
    * The stem ends with ``_condensed``.
    * The first non-header NDJSON line has ``type == "data"``.
    Either is sufficient.
    """
    p = Path(path)
    if p.stem.endswith("_condensed"):
        return True
    try:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if obj.get("type") == "header":
                    continue
                return obj.get("type") == "data"
    except Exception:
        pass
    return False


def condense_log(
    input_path:  str | Path,
    output_path: str | Path | None = None,
    progress_cb = None,
    phase_lookup = None,
    temperature_samples = None,
    temperature_zones_to_keep = None,
    service_config_samples = None,
    return_stats: bool = False,
) -> int | dict:
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
    phase_lookup : callable(cycle_int, time_s, raw_step, payload_dict) -> str|None
        Optional callback used to replace ``CurrentStep`` with an exact phase
        label (for example, ``seq2_TDIC_Dose``).
    temperature_samples : list or None
        Timestamped temperature samples used to add ``TemperatureZones`` to
        each condensed data payload.
    temperature_zones_to_keep : iterable or None
        Optional zone identifiers to retain in ``TemperatureZones``.
    service_config_samples : list or None
        Timestamped service configuration metadata used to populate each
        condensed data row's ``meta`` field.
    return_stats : bool
        When True, return a dict with row and file-size statistics.

    Returns
    -------
    int | dict
        Number of ``data`` rows written, or a stats dict when
        ``return_stats=True``.
    """
    input_path  = Path(input_path)
    output_path = Path(output_path) if output_path else condensed_path(input_path)
    file_size   = max(input_path.stat().st_size, 1)
    same_file = False
    try:
        same_file = input_path.resolve() == output_path.resolve()
    except Exception:
        same_file = str(input_path) == str(output_path)

    write_path = output_path
    if same_file:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{output_path.stem}.",
            suffix=".tmp",
            dir=str(output_path.parent),
        )
        os.close(fd)
        write_path = Path(tmp_name)

    last_step_payload: dict = {}
    header_start_timestamp = None
    selected_zones = (
        {str(zone) for zone in temperature_zones_to_keep}
        if temperature_zones_to_keep is not None else None
    )
    # Precompute the timestamp index once -- building it per-row (as earlier
    # revisions of this function did) turned temperature/service-config
    # lookups into an O(rows x samples) operation instead of O(rows log samples).
    temperature_times = (
        [sample[0] for sample in temperature_samples] if temperature_samples else None
    )
    service_config_times = (
        [sample[0] for sample in service_config_samples] if service_config_samples else None
    )
    rows_written = 0
    bytes_read   = 0
    total_rows   = 0
    pressure_rows = 0

    try:
        with input_path.open(encoding="utf-8") as fh_in, \
             write_path.open("w", encoding="utf-8") as fh_out:

            for line in fh_in:
                total_rows += 1
                bytes_read += len(line.encode())

                try:
                    obj   = json.loads(line)
                    rtype = obj.get("type")

                    # Always copy header, footer, and cycle_summary rows verbatim.
                    if rtype in ("header", "footer", "cycle_summary"):
                        fh_out.write(line if line.endswith("\n") else line + "\n")
                        if rtype == "header":
                            header_start_timestamp = _header_start_timestamp(
                                _parse_payload(obj.get("payload", {}))
                            )
                        continue

                    # Track the most recent step context.
                    if rtype == "step":
                        last_step_payload = _parse_payload(obj.get("payload", {}))
                        continue

                    # Merge step context into each pressure record.
                    if rtype in ("pressure", "data"):
                        pressure_rows += 1
                        pl = _parse_payload(obj.get("payload", {}))
                        try:
                            cycle = int(pl.get("CurrentCycle", ""))
                        except (TypeError, ValueError):
                            cycle = -1
                        try:
                            t_s = float(pl.get("TimeElapsed", "")) / 1000.0
                        except (TypeError, ValueError):
                            t_s = 0.0

                        if rtype == "data":
                            raw_step = pl.get("CurrentStep", "")
                        else:
                            raw_step = last_step_payload.get("CurrentStep", "")

                        if phase_lookup:
                            try:
                                phase_step = phase_lookup(cycle, t_s, raw_step, pl)
                            except Exception:
                                phase_step = None
                            current_step = phase_step if phase_step else "unassigned"
                        else:
                            current_step = raw_step

                        # When re-processing an already-condensed "data" row (a later
                        # pipeline pass), start from its existing fields so values
                        # baked in by an earlier pass (e.g. TemperatureZones) survive
                        # a pass that doesn't recompute them.
                        merged = dict(pl) if rtype == "data" else {}
                        merged["TimeElapsed"]  = pl.get("TimeElapsed", "")
                        merged["CurrentCycle"] = pl.get("CurrentCycle", "")
                        merged["CurrentStep"]  = current_step
                        merged["Pressure"]     = pl.get("Pressure", "")
                        merged["GUID"]         = pl.get("GUID", "")
                        if temperature_samples:
                            try:
                                absolute_timestamp = (
                                    header_start_timestamp + t_s
                                    if header_start_timestamp is not None else None
                                )
                                temperatures = _temperature_at(
                                    temperature_samples, temperature_times, absolute_timestamp
                                )
                                if temperatures:
                                    if selected_zones is not None:
                                        temperatures = {
                                            zone: values
                                            for zone, values in temperatures.items()
                                            if zone in selected_zones
                                        }
                                    merged["TemperatureZones"] = temperatures
                            except (TypeError, ValueError):
                                pass

                        previous_meta = obj.get("meta", "") if rtype == "data" else ""
                        if service_config_samples:
                            try:
                                absolute_timestamp = (
                                    header_start_timestamp + t_s
                                    if header_start_timestamp is not None else None
                                )
                                config_metadata = _service_config_at(
                                    service_config_samples, service_config_times, absolute_timestamp
                                )
                                if config_metadata is not None:
                                    data_row_meta = {
                                        "temperature": config_metadata
                                    }
                                else:
                                    data_row_meta = previous_meta
                            except (TypeError, ValueError):
                                data_row_meta = previous_meta
                        else:
                            data_row_meta = previous_meta
                        data_row = {
                            "type": "data",
                            "meta": data_row_meta,
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

        if same_file:
            os.replace(write_path, output_path)
    finally:
        if same_file and write_path.exists():
            try:
                write_path.unlink()
            except Exception:
                pass

    if not return_stats:
        return rows_written

    output_size = output_path.stat().st_size if output_path.exists() else 0
    reduction_pct = (1.0 - (output_size / file_size)) * 100.0 if file_size else 0.0
    return {
        "rows_written": rows_written,
        "total_rows": total_rows,
        "pressure_rows": pressure_rows,
        "input_size_bytes": file_size,
        "output_size_bytes": output_size,
        "size_reduction_pct": reduction_pct,
    }


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


def collect_temperature_by_cycle(
    path: str | Path,
    selected_zones=None,
) -> dict[int, dict[str, dict[str, list]]]:
    """
    Stream a condensed NDJSON file once and collect per-cycle, per-zone
    temperature samples already baked into each ``data`` row's
    ``TemperatureZones`` field (written by an earlier ``attach_temperature``
    pass). Returns ``{cycle: {zone: {"temps": [...], "setpoint": last_value}}}``.

    Returns an empty dict (cheaply) if no row carries ``TemperatureZones``.
    """
    selected = {str(zone) for zone in selected_zones} if selected_zones else None
    by_cycle: dict[int, dict[str, dict[str, list]]] = {}

    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            # Cheap pre-filter before the full JSON parse below. Works
            # regardless of whether "payload" is stored as a nested object or
            # (as condense_log writes it) a JSON-encoded string with escaped
            # quotes, since we deliberately don't anchor on the quote style.
            if "TemperatureZones" not in line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") != "data":
                    continue
                pl = _parse_payload(obj.get("payload", {}))
                zones = pl.get("TemperatureZones")
                if not isinstance(zones, dict) or not zones:
                    continue
                cycle = int(pl.get("CurrentCycle", ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

            cycle_bucket = by_cycle.setdefault(cycle, {})
            for zone, values in zones.items():
                if selected is not None and zone not in selected:
                    continue
                if not isinstance(values, dict):
                    continue
                zone_bucket = cycle_bucket.setdefault(zone, {"temps": [], "setpoint": None})
                temp_c = values.get("TemperatureC")
                if isinstance(temp_c, (int, float)):
                    zone_bucket["temps"].append(float(temp_c))
                set_point = values.get("SetPointC")
                if isinstance(set_point, (int, float)):
                    zone_bucket["setpoint"] = float(set_point)

    return by_cycle


def write_cycle_summaries(path: str | Path, summaries: list[dict]) -> int:
    """
    Append ``cycle_summary`` rows to the condensed NDJSON file at *path*,
    ahead of the trailing ``footer`` line if present.

    Any ``cycle_summary`` rows already present are discarded first (cheap
    prefix check, no JSON parsing), so this is safe to call repeatedly, e.g.
    after re-running Stage 6. Only reads/rewrites the (already small)
    condensed file once -- it does not touch the original raw log.
    """
    target = Path(path)
    lines = target.read_text(encoding="utf-8").splitlines()

    def _row_type(line: str) -> str | None:
        try:
            return json.loads(line).get("type")
        except (json.JSONDecodeError, AttributeError):
            return None

    footer_line = None
    if lines and '"footer"' in lines[-1] and _row_type(lines[-1]) == "footer":
        footer_line = lines.pop()

    # Cheap substring pre-filter (avoids parsing every line) before the
    # exact type check, so re-running this only strips genuine
    # cycle_summary rows.
    kept_lines = [
        line for line in lines
        if '"cycle_summary"' not in line or _row_type(line) != "cycle_summary"
    ]

    summary_lines = [
        json.dumps({"type": "cycle_summary", "payload": summary},
                    ensure_ascii=False, separators=(",", ":"))
        for summary in summaries
    ]

    all_lines = kept_lines + summary_lines
    if footer_line is not None:
        all_lines.append(footer_line)

    target.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    return len(summary_lines)

