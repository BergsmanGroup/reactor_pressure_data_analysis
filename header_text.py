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


def format_human_json(value, level: int = 0) -> str:
    """Format header JSON with expanded objects and compact list values."""
    indent = "  " * level
    child_indent = "  " * (level + 1)

    if isinstance(value, dict):
        if not value:
            return "{}"
        items = list(value.items())
        lines = ["{"]
        for index, (key, child) in enumerate(items):
            rendered = format_human_json(child, level + 1)
            child_lines = rendered.splitlines()
            lines.append(
                f"{child_indent}{json.dumps(key, ensure_ascii=False)}: "
                + child_lines[0]
            )
            lines.extend(child_lines[1:])
            if index < len(items) - 1:
                lines[-1] += ","
        lines.append(f"{indent}}}")
        return "\n".join(lines)

    if isinstance(value, list):
        if not value:
            return "[]"
        if all(isinstance(item, list) for item in value):
            lines = ["["]
            for index, item in enumerate(value):
                item_text = json.dumps(
                    item,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=True,
                )
                suffix = "," if index < len(value) - 1 else ""
                lines.append(f"{child_indent}{item_text}{suffix}")
            lines.append(f"{indent}]")
            return "\n".join(lines)
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=True,
        )

    return json.dumps(value, ensure_ascii=False, allow_nan=True)


def save_converted_header(path: str | Path, payload: dict) -> Path:
    """Save a parsed header payload beside its source text file."""
    output_path = converted_json_path(path)
    output_path.write_text(
        format_human_json(payload) + "\n",
        encoding="utf-8",
    )
    return output_path


def save_header_text(path: str | Path, payload: dict) -> Path:
    """Write a payload in the legacy human-readable header text structure."""
    output_path = Path(path)
    elapsed_line = ""
    if output_path.exists():
        for line in output_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            if line.startswith("Time Elapsed:"):
                elapsed_line = line
                break
    details = payload.get("experimentalDetails", "")
    if isinstance(details, (dict, list)):
        details_text = json.dumps(details, ensure_ascii=False, separators=(",", ":"), allow_nan=True)
    else:
        details_text = str(details or "")

    lines = [
        f"GUID: {payload.get('GUID', '')}",
        str(payload.get("username", "")),
        details_text,
        "Valve Sequence:",
    ]
    for row in payload.get("valveSequence", []):
        values = list(row[:9]) if isinstance(row, (list, tuple)) else []
        values.extend([0] * (9 - len(values)))
        lines.append("\t".join(str(value) for value in values[:9]))
    lines.extend([
        "",
        f"Start Date/Time{payload.get('startTime', '')}",
    ])
    if elapsed_line:
        lines.append(elapsed_line)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
    return format_human_json(payload.get("valveSequence"))


def compare_header_payloads(raw_payload: dict, text_payload: dict) -> list[str]:
    """Return a difference only when the valve sequences differ or are missing."""
    if "valveSequence" not in raw_payload or "valveSequence" not in text_payload:
        return ["valveSequence"]
    if _comparison_value(raw_payload["valveSequence"]) != _comparison_value(text_payload["valveSequence"]):
        return ["valveSequence"]
    return []
