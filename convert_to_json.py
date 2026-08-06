import argparse
import json
from pathlib import Path
import pandas as pd


RECIPE_COLS = 10
RECIPE_SEQUENCE_COLS = 9


HEADER_KEY_MAP = {
    "Info": "Info",
    "Wait time": "WaitTime",
    "EDR": "EDR",
    "DID": "DID",
    # Removed in new format but kept for backward compatibility with old sheets
    "SID": "SID",
    "EID": "EID",
    "PID": "PID",
    # Old valve-table row labels
    "Valve/precursor": "ValvePrecursor",
    "Name": "Name",
    "Temperature (C)": "TempC",
    "Temperature (C) ": "TempC",
    # New valve-table row labels
    "valve number": "ValvePrecursor",
    "Valve number": "ValvePrecursor",
    "valve name": "Name",
    "Valve name": "Name",
    "valve temperature": "TempC",
    "Valve temperature": "TempC",
    # Old informational fields (kept for backward compatibility)
    "Substrate": "Substrate",
    "Preexisting layer": "PreexistingLayer",
    "Preexisting layers": "PreexistingLayer",
    "Thickness": "PreexistingThickness",
    "Thicknesses": "PreexistingThickness",
    "Start time": "StartTime",
    "Process time (hr)": "ProcessTimeHr",
    "Process time (hours)": "ProcessTimeHr",
    "End time": "EndTime",
    "End time (datetime)": "EndTime",
}


def _clean_cell(value) -> str:
    return str(value).strip()


def _sanitize_filename_text(value) -> str:
    text = _clean_cell(value)
    if not text:
        return ""

    for ch in '-<>:"/\\|?*':
        text = text.replace(ch, "_")

    return text.strip()


def _coerce_token(token: str):
    token = _clean_cell(token)
    if token == "":
        return ""

    upper = token.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False

    try:
        if any(ch in token for ch in (".", "e", "E")):
            number = float(token)
            return int(number) if number.is_integer() else number
        return int(token)
    except ValueError:
        return token


def _split_embedded_values(value: str) -> list[str]:
    if "," not in value:
        return [_clean_cell(value)] if _clean_cell(value) else []
    return [_clean_cell(part) for part in value.split(",") if _clean_cell(part)]


def _parse_header_value(label: str, row_values: list[str]):
    cleaned = [_clean_cell(v) for v in row_values if _clean_cell(v)]
    if not cleaned:
        return ""

    if label in {"Info", "User/File Name Info"}:
        return cleaned[0]

    if label == "Wait time":
        return _coerce_token(cleaned[0])

    if label == "EDR":
        return bool(_coerce_token(cleaned[0]))

    if label in {"DID", "SID", "EID", "PID"}:
        tokens: list[str] = []
        for value in cleaned:
            tokens.extend(_split_embedded_values(value))
        return [_coerce_token(token) for token in tokens if token]

    return [_coerce_token(value) for value in cleaned]


def extract_header_details(df: pd.DataFrame) -> tuple[str, dict]:
    details: dict = {}
    username_base = ""

    df = df.iloc[:, :RECIPE_COLS].copy()

    norm_col0 = df.iloc[:, 0].fillna("").astype(str).map(_clean_cell)
    cycles_rows = norm_col0[norm_col0 == "Cycles"].index
    stop_idx = int(cycles_rows[0]) if len(cycles_rows) else df.shape[0]

    header_df = df.iloc[:stop_idx, :].fillna("").astype(str)
    for _, row in header_df.iterrows():
        label = _clean_cell(row.iloc[0])
        if not label:
            continue
        values = row.iloc[1:].tolist()

        if label in {"User/File Name Info", "Username"}:
            username_base = _parse_header_value(label, values)
            continue

        mapped = HEADER_KEY_MAP.get(label) or HEADER_KEY_MAP.get(label.rstrip())
        if not mapped:
            continue
        details[mapped] = _parse_header_value(label, values)

    return username_base, details


def validate_recipe_sheet(df: pd.DataFrame) -> list[str]:
    """
    Validate a recipe-sheet dataframe against the new workbook format requirements.

    Skips validation silently for old-format sheets that still contain SID / EID / PID
    rows (backward compatibility).

    Returns a list of human-readable error strings; an empty list means the sheet
    is valid (or is an old-format sheet that pre-dates these requirements).
    """
    errors: list[str] = []

    if df.shape[0] < 10 or df.shape[1] < 2:
        errors.append("Sheet must have at least 10 rows and 2 columns.")
        return errors

    def cell(row_0idx: int, col_0idx: int) -> str:
        try:
            return _clean_cell(str(df.iloc[row_0idx, col_0idx]))
        except IndexError:
            return ""

    # Locate the recipe header row so we can inspect only the metadata section.
    norm_col0 = df.iloc[:, 0].fillna("").astype(str).map(_clean_cell)
    cycles_rows = norm_col0[norm_col0 == "Cycles"].index
    if len(cycles_rows) == 0:
        errors.append('Could not find the recipe header row (a row starting with "Cycles").')
        return errors

    recipe_header_idx = int(cycles_rows[0])

    # Backward-compat: skip validation for old-format sheets that have SID/EID/PID rows.
    pre_recipe_labels = set(norm_col0.iloc[:recipe_header_idx].values)
    if pre_recipe_labels & {"SID", "EID", "PID"}:
        return []

    # --- structural row checks ------------------------------------------------
    # Row 6 (0-based index 5), column B (index 1): Chamber valve slot must be "nan".
    b6 = cell(5, 1)
    if b6.lower() != "nan":
        errors.append(
            f'Row 6, column B (Chamber valve slot) must be "nan"; got "{b6}".'
        )

    # Row 7 (0-based index 6), column B (index 1): Chamber name must be "Chamber".
    b7 = cell(6, 1)
    if b7 != "Chamber":
        errors.append(
            f'Row 7, column B (Chamber name) must be "Chamber"; got "{b7}".'
        )

    # Row 8 (0-based index 7), column B (index 1): Chamber temperature must be numeric.
    b8 = cell(7, 1)
    try:
        if not b8:
            raise ValueError("empty")
        float(b8)
    except ValueError:
        errors.append(
            f'Row 8, column B (Chamber temperature) must be a number; got "{b8}".'
        )

    # --- valve coverage check -------------------------------------------------
    # Declared valves: row 6, columns C–J (0-based indices 2–9).
    declared_valves: set[str] = set()
    for col_idx in range(2, min(10, df.shape[1])):
        v = cell(5, col_idx)
        if v and v.lower() != "nan":
            declared_valves.add(v)

    # Used valves: the Valve column (column B, index 1) of recipe data rows.
    recipe_start_idx = recipe_header_idx + 1
    if recipe_start_idx < df.shape[0] and df.shape[1] > 1:
        valve_col = (
            df.iloc[recipe_start_idx:, 1]
            .fillna("")
            .astype(str)
            .map(_clean_cell)
        )
        used_valves = {v for v in valve_col if v}
        missing = used_valves - declared_valves
        if missing:
            missing_str = ", ".join(
                sorted(missing, key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else x))
            )
            errors.append(
                f"Valves used in the recipe but not declared in row 6: {missing_str}."
            )

    return errors


def build_username(base_username: str, details: dict) -> str:
    username = _clean_cell(base_username)
    suffixes: list[str] = []

    edr_enabled = bool(details.get("EDR"))
    if edr_enabled:
        suffixes.append("EDR")

        for key in ("DID", "SID", "EID", "PID"):
            values = details.get(key, [])
            if isinstance(values, list) and values:
                suffixes.append(f"{key}{'-'.join(str(value) for value in values)}")

    if username and suffixes:
        return "&".join([username, *suffixes])
    if suffixes:
        return "&".join(suffixes)
    return username


def build_output_filename(df: pd.DataFrame) -> str | None:
    report = build_output_filename_report(df)
    return report["sanitized"] if report else None


def build_output_filename_report(df: pd.DataFrame) -> dict | None:
    """
    Build a filename stem from the new-format workbook header.

    Pattern (mirrors the workbook CONCAT formula):
        {B1}_{A4}{B4}_{A5}{B5}_{B7}{B8}[_{name}{temp} for each active valve column]

    Valve columns C onwards are only appended when:
      - row 6 has a non-nan valve number in that column,
      - row 7 has a non-empty name,
      - row 8 has a numeric temperature, and
      - that valve number appears in the recipe's Valve column.

    Returns *None* for old-format sheets (those containing SID/EID/PID rows)
    or when there is insufficient data to form a useful name.
    """
    if df.shape[0] < 10 or df.shape[1] < 2:
        return None

    def cell(row_0idx: int, col_0idx: int) -> str:
        try:
            return _clean_cell(str(df.iloc[row_0idx, col_0idx]))
        except IndexError:
            return ""

    def fmt_num(text: str) -> str:
        """'25.0' → '25'; non-numeric strings pass through unchanged."""
        try:
            f = float(text)
            return str(int(f)) if f == int(f) else str(f)
        except (ValueError, TypeError):
            return text

    def sanitize(text: str) -> str:
        """Strip characters that are illegal in Windows file names."""
        for ch in r'-\/:*?"<>|':
            text = text.replace(ch, "_")
        return text.strip("_ ")

    # Detect old-format sheets — skip validation-style filename building.
    norm_col0 = df.iloc[:, 0].fillna("").astype(str).map(_clean_cell)
    cycles_rows = norm_col0[norm_col0 == "Cycles"].index
    recipe_header_idx = int(cycles_rows[0]) if len(cycles_rows) else df.shape[0]
    pre_labels = set(norm_col0.iloc[:recipe_header_idx].values)
    if pre_labels & {"SID", "EID", "PID"}:
        return None

    # --- fixed header cells --------------------------------------------------
    b1 = sanitize(cell(0, 1))            # Username value (B1)
    a4 = sanitize(cell(3, 0))            # "EDR" label  (A4)
    b4 = sanitize(cell(3, 1))            # EDR value    (B4)
    a5 = sanitize(cell(4, 0))            # "DID" label  (A5)
    b5_raw = cell(4, 1)                  # DID raw value (B5), may be comma-list
    b7 = sanitize(cell(6, 1))            # Chamber name (B7)
    b8 = fmt_num(cell(7, 1))            # Chamber temp (B8)

    # Format DID: "117, 119" → "117-119"
    if b5_raw:
        did_parts = [fmt_num(_clean_cell(p)) for p in b5_raw.split(",") if _clean_cell(p)]
        b5 = sanitize("-".join(did_parts))
    else:
        b5 = ""

    # Collect valve numbers used in the recipe (Valve column = index 1).
    used_valves: set[str] = set()
    recipe_start_idx = recipe_header_idx + 1
    if recipe_start_idx < df.shape[0] and df.shape[1] > 1:
        valve_col = (
            df.iloc[recipe_start_idx:, 1]
            .fillna("")
            .astype(str)
            .map(_clean_cell)
        )
        used_valves = {v for v in valve_col if v}

    # --- assemble parts -------------------------------------------------------
    parts: list[str] = []
    raw_parts: list[str] = []
    if cell(0, 1):
        raw_parts.append(cell(0, 1))
    if cell(3, 0) and cell(3, 1):
        raw_parts.append(cell(3, 0) + cell(3, 1))
    if cell(4, 0) and b5_raw:
        raw_parts.append(cell(4, 0) + b5_raw)
    chamber_raw = cell(6, 1) + fmt_num(cell(7, 1))
    if chamber_raw:
        raw_parts.append(chamber_raw)

    if b1:
        parts.append(b1)
    if a4 and b4:
        parts.append(a4 + b4)
    if a5 and b5:
        parts.append(a5 + b5)
    # Chamber (B7+B8) — always included.
    chamber_seg = b7 + b8
    if chamber_seg:
        parts.append(chamber_seg)

    # Additional valve columns C–J (0-based column indices 2–9).
    for col_idx in range(2, min(10, df.shape[1])):
        valve_num = cell(5, col_idx)   # row 6: declared valve number
        name     = cell(6, col_idx)    # row 7: valve name
        temp_raw = cell(7, col_idx)    # row 8: valve temperature

        if not valve_num or valve_num.lower() == "nan":
            continue
        if not name:
            continue
        try:
            if not temp_raw:
                raise ValueError
            float(temp_raw)
        except ValueError:
            continue
        if valve_num not in used_valves:
            continue

        raw_parts.append(name + fmt_num(temp_raw))
        parts.append(sanitize(name) + fmt_num(temp_raw))

    if not parts:
        return None

    raw_name = "_".join(raw_parts) if raw_parts else ""
    safe_name = "_".join(parts)
    return {
        "raw": raw_name,
        "sanitized": safe_name,
        "changed": raw_name != safe_name,
    }


def load_table(path: Path) -> pd.DataFrame:
    ext = path.suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path, header=None, dtype=str, keep_default_na=False)
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(path, header=None, dtype=str, keep_default_na=False)
    raise ValueError(f"Unsupported file type: {ext}")


def normalize_recipe(df: pd.DataFrame, rows: int | None = None, cols: int | None = None):
    if rows is not None or cols is not None:
        max_rows = rows if rows is not None else df.shape[0]
        max_cols = cols if cols is not None else df.shape[1]
        df = df.iloc[:max_rows, :max_cols].copy()
        df = df.reindex(index=range(max_rows), columns=range(max_cols), fill_value="")

    df = df.fillna("").astype(str)
    return df.values.tolist()


def extract_timing_table(
    df: pd.DataFrame,
    rows: int | None = None,
    cols: int | None = None,
) -> list[list[str]]:
    timing_df = df.iloc[:, :RECIPE_COLS].fillna("").astype(str).copy()
    timing_df = timing_df.reindex(columns=range(RECIPE_COLS), fill_value="")
    header_rows = timing_df.index[timing_df.iloc[:, 0].map(_clean_cell) == "Cycles"]
    if len(header_rows) == 0:
        raise ValueError("Could not find the timing table header row starting with 'Cycles'.")

    start_idx = int(header_rows[0])
    # Exclude the header row itself; payload should contain only timing data rows.
    timing_df = timing_df.iloc[start_idx + 1 :, :].copy()
    timing_df = timing_df.loc[
        timing_df.apply(lambda row: any(_clean_cell(value) for value in row), axis=1)
    ]

    if rows is not None or cols is not None:
        max_rows = rows if rows is not None else timing_df.shape[0]
        max_cols = cols if cols is not None else timing_df.shape[1]
        timing_df = timing_df.iloc[:max_rows, :max_cols].copy()
        timing_df = timing_df.reset_index(drop=True)

    return timing_df.values.tolist()


def _to_float(value) -> float:
    try:
        token = _clean_cell(value)
        return float(token) if token else 0.0
    except ValueError:
        return 0.0


def _estimate_process_times(df: pd.DataFrame, details: dict) -> dict:
    """
    Compute total process time from timing rows and estimate end time.

    Sequence duration is the sum of phase columns (index 2..8) across all
    valve rows in the sequence, multiplied by the sequence cycle count.
    """
    recipe_rows = extract_timing_table(df)

    total_seconds = 0.0
    current_cycles = 0.0
    current_seq_seconds = 0.0

    def _commit_sequence():
        nonlocal total_seconds, current_cycles, current_seq_seconds
        if current_cycles > 0:
            total_seconds += current_cycles * current_seq_seconds
        current_cycles = 0.0
        current_seq_seconds = 0.0

    for row in recipe_rows:
        cycle_cell = _clean_cell(row[0]) if len(row) > 0 else ""
        if cycle_cell:
            _commit_sequence()
            current_cycles = _to_float(cycle_cell)

        phase_vals = row[2:9] if len(row) >= 9 else row[2:]
        current_seq_seconds += sum(_to_float(v) for v in phase_vals)

    _commit_sequence()

    wait_seconds = _to_float(details.get("WaitTime", 0)) if isinstance(details, dict) else 0.0
    process_hours = round(total_seconds / 3600.0, 6)
    total_duration_seconds = wait_seconds + total_seconds
    end_dt = pd.Timestamp.now() + pd.to_timedelta(total_duration_seconds, unit="s")

    out = {
        "ProcessTimeHr": process_hours,
        "EndTime": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }

    return out


def _extract_sequence_notes(df: pd.DataFrame) -> list[dict]:
    notes: list[dict] = []
    timing_rows = extract_timing_table(df)

    current_cycles = ""
    seq_index = 0
    for row in timing_rows:
        if not row:
            continue

        cycle_cell = _clean_cell(row[0]) if len(row) > 0 else ""
        if cycle_cell:
            seq_index += 1
            current_cycles = cycle_cell
            note_text = _clean_cell(row[9]) if len(row) > 9 else ""
            if note_text:
                notes.append(
                    {
                        "Seq": seq_index,
                        "Cycles": _coerce_token(current_cycles),
                        "Note": note_text,
                    }
                )

    return notes


def build_payload(
    df: pd.DataFrame,
    username: str | None = None,
    details=None,
    rows: int | None = None,
    cols: int | None = None,
) -> dict:
    base_username, header_details = extract_header_details(df)
    if details is None:
        payload_details = dict(header_details)
    elif isinstance(details, dict):
        payload_details = dict(details)
    else:
        payload_details = details

    if isinstance(payload_details, dict):
        payload_details.update(_estimate_process_times(df, payload_details))
        sequence_notes = _extract_sequence_notes(df)
        if sequence_notes:
            payload_details["SequenceNotes"] = sequence_notes

    payload_username = username if username is not None else build_username(base_username, payload_details)
    payload_username = _sanitize_filename_text(payload_username)
    if isinstance(payload_details, str):
        details_text = payload_details
    else:
        # LabVIEW expects this field to be text, so encode non-string values.
        details_text = json.dumps(payload_details, ensure_ascii=False, separators=(",", ":"))

    return {
        "recipe": extract_timing_table(
            df,
            rows=rows,
            cols=min(cols, RECIPE_SEQUENCE_COLS) if cols is not None else RECIPE_SEQUENCE_COLS,
        ),
        "username": payload_username,
        "experimentalDetails": details_text,
    }


def extract_sequence_notes(df: pd.DataFrame) -> list[dict]:
    return _extract_sequence_notes(df)


def save_payload(payload: dict, out_path: str | Path) -> Path:
    output_path = Path(out_path)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output_path


def convert_recipe_sheet(
    input_path: str | Path,
    out_path: str | Path | None = None,
    username: str | None = None,
    details=None,
    rows: int | None = None,
    cols: int | None = None,
) -> tuple[dict, Path]:
    path = Path(input_path)
    df = load_table(path)
    if username is None:
        username = build_output_filename(df)
    payload = build_payload(df, username=username, details=details, rows=rows, cols=cols)

    output_path = Path(out_path) if out_path else path.with_name(f"{path.stem}_payload.json")
    save_payload(payload, output_path)
    return payload, output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_file", help="Path to .csv or .xlsx")
    parser.add_argument("--username")
    parser.add_argument("--details", help="experimentalDetails JSON string")
    parser.add_argument("--out")
    parser.add_argument("--rows", type=int, default=None, help="Optional max rows")
    parser.add_argument("--cols", type=int, default=None, help="Optional max columns")
    args = parser.parse_args()

    details = json.loads(args.details) if args.details else None
    payload, output_path = convert_recipe_sheet(
        args.input_file,
        out_path=args.out,
        username=args.username,
        details=details,
        rows=args.rows,
        cols=args.cols,
    )
    print(f"Wrote {output_path}")
    print(json.dumps({
        "username": payload["username"],
        "experimentalDetails": payload["experimentalDetails"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()