"""Shared helpers for the test suite (paths, hashing, payload normalization)."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EXAMPLE_CSV = REPO_ROOT / "Example recipe sheet.csv"
EXAMPLE_PAYLOAD = REPO_ROOT / "Example recipe sheet_payload.json"
WORKBOOK_CURRENT = REPO_ROOT / "Recipe sheet workbook format.xlsx"
WORKBOOK_OLD = REPO_ROOT / "Recipe sheet workbook format (old).xlsx"
DID141_DIR = REPO_ROOT / "DID000141"
DID141_WORKBOOK = DID141_DIR / "260819 TDIC & DAMDPA high dose purge testing recipe sheet(1).xlsx"

# Owner-supplied example (2026-11-01): four sequences, the third repeating
# six valve rows for 40 cycles. Blank Cycles cells continue the sequence above.
OWNER_EXAMPLE_CSV = """Username,Jay,,,,,,,,
Info,Owner example with four sequences,,,,,,,,
Wait time,0,,,,,,,,
EDR,TRUE,,,,,,,,
DID,168,,,,,,,,
Valve/precursor,nan,7,5,8,6,12,,,
Name,Chamber,GV,TDIC,DAMDPA,MeI,LeakRate,,,
Temperature (C),80,50,30,30,25,nan,,,
,,,,,,,,,
Cycles,Valve,PrePump,N2Dose,PumpDose,Dose,Hold,PrePurge,Purge,Notes
1,12,10,0,0,0,120,0,10,
1,7,0,15,0,0,0,0,10,
40,5,10,0,0,300,0,0,600,
,5,10,0,0,0,60,0,10,
,7,0,15,0,0,0,0,10,
,8,10,0,0,300,0,0,600,
,8,10,0,0,0,60,0,10,
,7,0,15,0,0,0,0,10,
1,12,10,0,0,0,120,0,10,
"""

# Hand calculation for OWNER_EXAMPLE_CSV (seconds, serial slots, per-sequence cycles):
#   seq1 = 1  x (10+120+10)                         = 140
#   seq2 = 1  x (15+10)                             = 25
#   seq3 = 40 x (910 + 80 + 25 + 910 + 80 + 25)     = 40 x 2030 = 81200
#   seq4 = 1  x (10+120+10)                         = 140
OWNER_EXAMPLE_TOTAL_SECONDS = 140 + 25 + 81200 + 140


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_payload(payload: dict) -> dict:
    """Return a payload copy with the time-dependent EndTime removed.

    ``experimentalDetails`` is re-serialized with sorted keys so NaN values
    (which the converter currently emits) compare as equal text.
    """
    out = dict(payload)
    details = payload.get("experimentalDetails")
    if isinstance(details, str):
        try:
            parsed = json.loads(details)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            parsed.pop("EndTime", None)
            out["experimentalDetails"] = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
    return out


def load_golden(name: str):
    with open(GOLDEN_DIR / name, "r", encoding="utf-8") as fh:
        return json.load(fh)
