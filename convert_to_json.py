import argparse
import json
from pathlib import Path
import pandas as pd


HEADER_KEY_MAP = {
    "Info": "Info",
    "Wait time": "WaitTime",
    "EDR": "EDR",
    "DID": "DID",
    "SID": "SID",
    "EID": "EID",
    "PID": "PID",
    "Valve/precursor": "ValvePrecursor",
    "Name": "Name",
    "Temperature (C)": "TempC",
    "Temperature (C) ": "TempC",
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

    norm_col0 = df.iloc[:, 0].fillna("").astype(str).map(_clean_cell)
    cycles_rows = norm_col0[norm_col0 == "Cycles"].index
    stop_idx = int(cycles_rows[0]) if len(cycles_rows) else df.shape[0]

    header_df = df.iloc[:stop_idx, :].fillna("").astype(str)
    for _, row in header_df.iterrows():
        label = _clean_cell(row.iloc[0])
        if not label:
            continue
        values = row.iloc[1:].tolist()

        if label == "User/File Name Info":
            username_base = _parse_header_value(label, values)
            continue

        mapped = HEADER_KEY_MAP.get(label) or HEADER_KEY_MAP.get(label.rstrip())
        if not mapped:
            continue
        details[mapped] = _parse_header_value(label, values)

    return username_base, details


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
    timing_df = df.fillna("").astype(str).iloc[:, :9].copy()
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
        timing_df = timing_df.reindex(index=range(max_rows), columns=range(max_cols), fill_value="")

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

    process_hours = round(total_seconds / 3600.0, 6)
    out = {"ProcessTimeHr": process_hours}

    start_raw = details.get("StartTime", "") if isinstance(details, dict) else ""
    if isinstance(start_raw, list):
        start_raw = next((x for x in start_raw if _clean_cell(x)), "")
    start_text = _clean_cell(start_raw)
    if start_text:
        start_dt = pd.to_datetime(start_text, errors="coerce")
        if pd.notna(start_dt):
            end_dt = start_dt + pd.to_timedelta(total_seconds, unit="s")
            out["EndTime"] = end_dt.strftime("%Y-%m-%d %H:%M:%S")

    return out


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

    payload_username = username if username is not None else build_username(base_username, payload_details)
    if isinstance(payload_details, str):
        details_text = payload_details
    else:
        # LabVIEW expects this field to be text, so encode non-string values.
        details_text = json.dumps(payload_details, ensure_ascii=False, separators=(",", ":"))

    return {
        "recipe": extract_timing_table(df, rows=rows, cols=cols),
        "username": payload_username,
        "experimentalDetails": details_text,
    }


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
    payload = build_payload(df, username=username, details=details, rows=rows, cols=cols)

    output_path = Path(out_path) if out_path else path.with_name(f"{path.stem}_payload.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

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