#!/usr/bin/env python3
"""
new_to_old_jsonlog.py

Convert the *new* NDJSON log format to the *old* format.

- Drops records like type=="step" (and anything in DROP_TYPES).
- If payload is a JSON-encoded *string*, parse it back into a dict.
- Removes extra keys in payload (e.g., "CurrentStep") listed in DROP_PAYLOAD_KEYS.
- Leaves "header" and "pressure" records (or any other non-dropped types) intact.
- Preserves string types for values (e.g., "TimeElapsed":"61") if they arrive as strings.

Usage:
    python new_to_old_jsonlog.py -i new.jsonl -o old.jsonl
    # or stream:
    python new_to_old_jsonlog.py < new.jsonl > old.jsonl
"""

import sys
import json
import argparse

# Record types to drop entirely (expand if needed)
DROP_TYPES = {"step", "currentstep"}

# Extra payload keys to drop (expand if needed)
DROP_PAYLOAD_KEYS = {
    "CurrentStep",
    "CurrentSubstep",
    "CurrentAction",
    "CurrentStepID",
    "CurrentPhase",
    # add any other new-only keys here
}

def coerce_payload(payload):
    """
    Ensure payload is a dict.
    - If it's a JSON string, parse it.
    - If parsing fails, leave it as-is.
    """
    if isinstance(payload, str):
        s = payload.strip()
        # Quick check to avoid exceptions on empty or non-JSON strings
        if s and (s[0] in "{[" and s[-1] in "}]"):
            try:
                parsed = json.loads(s)
                return parsed
            except Exception:
                return payload  # leave as string if it wasn't valid JSON
    return payload

def strip_extra_keys(payload):
    """Remove new-format-only keys from the payload dict."""
    if isinstance(payload, dict):
        for k in list(payload.keys()):
            if k in DROP_PAYLOAD_KEYS:
                payload.pop(k, None)
    return payload

def convert_stream(instream, outstream):
    """
    Read NDJSON lines from instream, write converted lines to outstream.
    """
    for line in instream:
        line = line.strip()
        if not line:
            continue

        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            # If a line isn't valid JSON, just skip it (or print to stderr)
            continue

        # Drop whole records by type
        rtype = str(rec.get("type", "")).lower()
        if rtype in DROP_TYPES:
            continue

        # Normalize payload
        if "payload" in rec:
            payload = coerce_payload(rec["payload"])
            payload = strip_extra_keys(payload)
            rec["payload"] = payload

        # Write out normalized record
        outstream.write(json.dumps(rec, separators=(",", ":")) + "\n")

def main():
    ap = argparse.ArgumentParser(description="Convert new NDJSON format to old format.")
    ap.add_argument("-i", "--input", help="Input NDJSON file (default: stdin)")
    ap.add_argument("-o", "--output", help="Output NDJSON file (default: stdout)")
    args = ap.parse_args()

    if args.input:
        instream = open(args.input, "r", encoding="utf-8")
    else:
        instream = sys.stdin

    if args.output:
        outstream = open(args.output, "w", encoding="utf-8")
    else:
        outstream = sys.stdout

    try:
        convert_stream(instream, outstream)
    finally:
        if args.input:
            instream.close()
        if args.output:
            outstream.close()

if __name__ == "__main__":
    main()
