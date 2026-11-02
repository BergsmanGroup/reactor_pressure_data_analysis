"""Build and (re)capture regression baselines.

The golden files in ``tests/golden`` pin the behavior of the current backend
before the Qt migration. Regenerate them only when an output change is
intentional and reviewed:

    .\\.venv\\Scripts\\python.exe tests\\_baseline.py
"""

from __future__ import annotations

import csv
import json
import math
import shutil
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

from _helpers import (  # noqa: E402
    DID141_DIR,
    DID141_WORKBOOK,
    EXAMPLE_CSV,
    GOLDEN_DIR,
    WORKBOOK_CURRENT,
    WORKBOOK_OLD,
    normalize_payload,
)

import convert_to_json  # noqa: E402

PAYLOAD_FIXTURES = {
    "payload_example_csv.json": EXAMPLE_CSV,
    "payload_workbook_current.json": WORKBOOK_CURRENT,
    "payload_workbook_old.json": WORKBOOK_OLD,
    "payload_did141_workbook.json": DID141_WORKBOOK,
}

PIPELINE_GOLDEN = "pipeline_did141.json"


def build_normalized_payload(path: Path) -> dict:
    df = convert_to_json.load_table(path)
    return normalize_payload(convert_to_json.build_payload(df))


def _jsonable(value):
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        return round(value, 6)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    try:
        return _jsonable(float(value))
    except (TypeError, ValueError):
        return str(value)


def did141_condensed_source() -> Path:
    return next(DID141_DIR.glob("*_condensed.json"))


def run_did141_pipeline(work_dir: Path) -> dict:
    """Run the full pipeline on a temporary copy of the DID000141 condensed run.

    Returns a structured, JSON-friendly summary for baseline comparison.
    The tracked source file is never opened for writing.
    """
    from PIL import Image

    from data_parser import read_header
    from pipeline import ProcessingOptions, ReactorPipeline
    from sequence_utils import convert_sequence

    src = did141_condensed_source()
    input_path = work_dir / src.name
    shutil.copy2(src, input_path)
    out_dir = work_dir / "out"

    header = read_header(input_path)
    seq = convert_sequence(header["valveSequence"])
    pipe = ReactorPipeline(input_path, str(out_dir), seq, ProcessingOptions(write_condensed_json=False))
    try:
        result = pipe.run_all()
    finally:
        pipe.cleanup()

    exposure_rows = []
    if result.get("exposure_csv"):
        with open(result["exposure_csv"], newline="", encoding="utf-8") as fh:
            exposure_rows = list(csv.DictReader(fh))

    png_sizes = {}
    for png in sorted(out_dir.glob("*.png")):
        with Image.open(png) as img:
            png_sizes[png.name] = list(img.size)

    gif_frames = None
    if result.get("animation"):
        with Image.open(result["animation"]) as gif:
            gif_frames = getattr(gif, "n_frames", 1)

    return _jsonable(
        {
            "sequence": {k: {"cycles": v["cycles"], "valve_rows": v["valve_rows"]} for k, v in seq.items()},
            "cycle_count": len(pipe.cycle_points),
            "points_per_cycle": {str(k): len(v) for k, v in sorted(pipe.cycle_points.items())},
            "baseline": pipe.baseline,
            "xlim": pipe.xlim_val,
            "ylim": pipe.ylim_val,
            "cycle_seq_map": pipe.cyc_seq_map,
            "phase_bins": {k: v["phase_bins"] for k, v in pipe.phased_seq.items()},
            "phase_names": {k: v["phase_names"] for k, v in pipe.phased_seq.items()},
            "result_counts": {"plots": result.get("plots"), "cycle_summaries": result.get("cycle_summaries")},
            "output_files": sorted(p.name for p in out_dir.iterdir()),
            "png_sizes": png_sizes,
            "gif_frames": gif_frames,
            "exposure_rows": exposure_rows,
        }
    )


def capture() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in PAYLOAD_FIXTURES.items():
        with open(GOLDEN_DIR / name, "w", encoding="utf-8") as fh:
            json.dump(build_normalized_payload(path), fh, ensure_ascii=False, indent=2)
        print(f"wrote {name}")

    work = Path(tempfile.mkdtemp(prefix="reactor_baseline_"))
    try:
        summary = run_did141_pipeline(work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with open(GOLDEN_DIR / PIPELINE_GOLDEN, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print(f"wrote {PIPELINE_GOLDEN}")


if __name__ == "__main__":
    capture()
