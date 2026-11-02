"""Shared persistence for the existing GUI configuration format."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path


def load_settings_state(
    local_path: str | Path, default_path: str | Path, *, create_local: bool = True
) -> dict:
    local = Path(local_path)
    default = Path(default_path)
    if not local.exists() and default.exists() and create_local:
        shutil.copyfile(default, local)
    source = local if local.exists() else default
    with source.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Settings must be a JSON object: {source}")
    last = data.get("last_processing_settings", {})
    valves = data.get("last_valve_names", {})
    reactors = data.get("reactors", [])
    if not isinstance(last, dict) or not isinstance(valves, dict) or not isinstance(reactors, list):
        raise ValueError(f"Invalid processing settings, valve names, or reactor list in {source}")
    return {
        "last_processing_settings": last,
        "last_valve_names": valves,
        "reactors": [str(reactor) for reactor in reactors if str(reactor).strip()],
    }


def save_settings_state(local_path: str | Path, state: dict) -> None:
    target = Path(local_path).resolve()
    fd, temporary_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
