"""Parse reactor header text files into raw-data header payloads."""

from __future__ import annotations

import json
import re
from pathlib import Path


def _parse_value(value: str):
    text = value.strip()
    if not text:
        return 0
    try:
        return int(text)
    except ValueError:
        try:
            number = float(text)
            return int(number) if number.is_integer() else number
        except ValueError:
            return text


def parse_header_text(path: str | Path) -> dict:
    """Parse a reactor ``_Header.txt`` file into a raw header payload dict."""
    source = Path(path)
    text = source.read_text(encoding="utf-8-sig", errors="replace")
    if text.lstrip().startswith("{"):
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("JSON header text must contain an object.")
        if "valveSequence" not in payload:
            raise ValueError("JSON header text does not contain 'valveSequence'.")
        return payload

    lines = text.splitlines()
    if len(lines) < 4:
        raise ValueError("Header text file is too short.")

    guid_line = lines[0].strip()
    if not guid_line.startswith("GUID:"):
        raise ValueError("Header text file does not start with a GUID line.")
    payload = {"GUID": guid_line.split(":", 1)[1].strip()}
    payload["username"] = lines[1].strip()
    payload["experimentalDetails"] = _parse_details(lines[2])

    try:
        sequence_start = next(index for index, line in enumerate(lines) if line.strip() == "Valve Sequence:")
    except StopIteration as exc:
        raise ValueError("Header text file does not contain 'Valve Sequence:'.") from exc

    valve_sequence = []
    index = sequence_start + 1
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("Start Date/Time"):
            payload["startTime"] = line[len("Start Date/Time"):].strip()
            break
        if line:
            parts = lines[index].split("\t")
            if len(parts) == 1:
                parts = lines[index].split()
            values = [_parse_value(part) for part in parts[:9]]
            values.extend([0] * (9 - len(values)))
            if any(value != 0 for value in values):
                valve_sequence.append(values)
        index += 1

    if "startTime" not in payload:
        raise ValueError("Header text file does not contain 'Start Date/Time'.")
    payload["valveSequence"] = valve_sequence
    return payload


def _parse_details(value: str):
    text = value.strip()
    if not text:
        return ""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def converted_json_path(path: str | Path) -> Path:
    """Return the JSON path beside a header text file."""
    source = Path(path)
    return source.with_suffix(".json")


def save_converted_header(path: str | Path, payload: dict) -> Path:
    """Save a parsed header payload beside its source text file."""
    output_path = converted_json_path(path)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _comparison_value(value):
    if isinstance(value, dict):
        return {key: _comparison_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_comparison_value(item) for item in value]
    if isinstance(value, float) and value != value:
        return "NaN"
    return value


def normalized_header_text(payload: dict) -> str:
    """Return stable, readable JSON text for valve-sequence comparison display."""
    return json.dumps(
        _comparison_value(payload.get("valveSequence")),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def compare_header_payloads(raw_payload: dict, text_payload: dict) -> list[str]:
    """Return a difference only when the valve sequences differ or are missing."""
    if "valveSequence" not in raw_payload or "valveSequence" not in text_payload:
        return ["valveSequence"]
    if _comparison_value(raw_payload["valveSequence"]) != _comparison_value(text_payload["valveSequence"]):
        return ["valveSequence"]
    return []
