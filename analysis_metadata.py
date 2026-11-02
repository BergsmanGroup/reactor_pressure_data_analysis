"""Shared header-derived names, annotations, and processing path helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def parse_experimental_details(value):
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            return text
        if isinstance(parsed, dict):
            return parsed
    return value if value is not None else {}


def details_valve_names(details) -> dict[int, str]:
    if not isinstance(details, dict):
        return {}
    names = details.get("Name", [])
    precursors = details.get("ValvePrecursor", [])
    if not isinstance(names, list) or not isinstance(precursors, list):
        return {}
    mapping: dict[int, str] = {}
    for precursor, name in zip(precursors, names):
        try:
            number = int(precursor)
        except (TypeError, ValueError, OverflowError):
            continue
        label = str(name).strip()
        if label and label.lower() != "stage":
            mapping[number] = label
    return mapping


def effective_valve_names(manual: dict[int, str], details) -> dict[int, str]:
    names = {number: str(name).strip() for number, name in manual.items() if str(name).strip()}
    names.update(details_valve_names(details))
    return names


def sequence_notes_by_seq(details) -> tuple[dict[int, str], dict[int, str]]:
    by_sequence: dict[int, str] = {}
    by_cycles: dict[int, str] = {}
    if not isinstance(details, dict) or not isinstance(details.get("SequenceNotes", []), list):
        return by_sequence, by_cycles
    for entry in details.get("SequenceNotes", []):
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("Note", "")).strip()
        if not text:
            continue
        sequence = entry.get("Seq", entry.get("Sequence"))
        has_sequence = False
        if sequence not in (None, ""):
            try:
                by_sequence[int(sequence)] = text
                has_sequence = True
            except (TypeError, ValueError, OverflowError):
                pass
        cycles = entry.get("Cycles")
        if not has_sequence and cycles not in (None, ""):
            try:
                by_cycles[int(cycles)] = text
            except (TypeError, ValueError, OverflowError):
                pass
    return by_sequence, by_cycles


def sequence_note_text(seq_key: str, phased_seq: dict, details) -> str | None:
    by_sequence, by_cycles = sequence_notes_by_seq(details)
    match = re.search(r"\d+", seq_key or "")
    if match is None:
        return None
    index = int(match.group())
    text = by_sequence.get(index)
    if not text:
        cycles = phased_seq.get(seq_key, {}).get("cycles") if isinstance(phased_seq, dict) else None
        if cycles not in (None, ""):
            try:
                text = by_cycles.get(int(cycles))
            except (TypeError, ValueError, OverflowError):
                text = None
    return f"Seq {index}: {text}" if text else None


def reactor_type_from_filename(file_path: str | Path, reactors: list[str]) -> str | None:
    pattern = "|".join(re.escape(name) for name in sorted(reactors, key=len, reverse=True) if name)
    if not pattern:
        return None
    match = re.fullmatch(
        rf"\d{{6}}_\d{{2}}h\d{{2}}m_{{1,2}}(?P<reactor>{pattern})"
        rf".*_Reactor\d+_Data(?:_condensed)?\.json",
        Path(file_path).name,
    )
    return match.group("reactor") if match else None


def default_output_directory(file_path: str | Path) -> Path:
    path = Path(file_path)
    match = re.match(r"^(\d{6}_\d{2}h\d{2}m)", path.stem)
    suffix = match.group(1) if match else ""
    return path.parent / (f"cycle_plots_{suffix}" if suffix else "cycle_plots")


def predicted_header_text_path(file_path: str | Path) -> Path | None:
    path = Path(file_path)
    reactor_data_dir = path.parent.parent
    if path.parent.name.casefold() != "json files" or reactor_data_dir.name.casefold() != "reactor data":
        return None
    match = re.match(r"^(?P<date>\d{6})_", path.name)
    if not match:
        return None
    try:
        month_dir = datetime.strptime(match.group("date"), "%y%m%d").strftime("%B %Y")
    except ValueError:
        return None
    name = re.sub(r"_Data(?:_condensed)?\.json$", "_Header.txt", path.name, flags=re.IGNORECASE)
    return reactor_data_dir / "Text Files" / month_dir / name if name != path.name else None


def processed_datetime_from_filename(file_path: str | Path) -> str | None:
    match = re.match(r"^(?P<date>\d{6})_(?P<time>\d{2}h\d{2}m)_", Path(file_path).name)
    if not match:
        return None
    try:
        value = datetime.strptime(f"{match.group('date')}_{match.group('time')}", "%y%m%d_%Hh%Mm")
    except ValueError:
        return None
    return value.replace(tzinfo=ZoneInfo("America/Los_Angeles")).isoformat()


def append_valve_name_log(
    log_path: str | Path,
    file_path: str | Path,
    guid: object,
    reactor_type: str | None,
    valve_names: dict[int, str],
) -> bool:
    processed_at = processed_datetime_from_filename(file_path)
    if processed_at is None:
        raise ValueError(f"Could not parse timestamp for valve name log: {Path(file_path).name}")
    path = Path(log_path)
    record = {
        "data_file": Path(file_path).name,
        "GUID": str(guid),
        "valve_names": {reactor_type: {str(number): str(name) for number, name in valve_names.items()}},
        "process_datetime": processed_at,
        "log_datetime": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
    }
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    existing = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(existing, dict):
                    existing.pop("log_datetime", None)
                    comparable = dict(record)
                    comparable.pop("log_datetime", None)
                    if existing == comparable:
                        return False
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True
