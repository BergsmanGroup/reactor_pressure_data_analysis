"""Small synthetic raw run for processing and Qt integration tests."""

from __future__ import annotations

import json
from pathlib import Path


def write_synthetic_run(path: Path) -> Path:
    header = {
        "GUID": "synthetic-run",
        "username": "Synthetic",
        "experimentalDetails": json.dumps(
            {
                "ValvePrecursor": [None, 7],
                "Name": ["Chamber", "TestValve"],
                "TempC": [25, 30],
                "WaitTime": 0,
                "SequenceNotes": [{"Seq": 1, "Cycles": 2, "Note": "Synthetic note"}],
            }
        ),
        "valveSequence": [[2, 7, 0, 2, 0, 1, 1, 0, 2]],
        "startTime": "2026-01-01T12:00:00",
    }
    records = [{"type": "header", "payload": header}, {"type": "step", "payload": {"CurrentStep": "test"}}]
    for cycle in (1, 2):
        for index in range(7):
            records.append(
                {
                    "type": "pressure",
                    "payload": {
                        "TimeElapsed": ((cycle - 1) * 7 + index) * 1000,
                        "CurrentCycle": cycle,
                        "Pressure": 10 + cycle + index * 0.5,
                        "GUID": "synthetic-run",
                    },
                }
            )
    records.append({"type": "footer", "payload": {}})
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path
