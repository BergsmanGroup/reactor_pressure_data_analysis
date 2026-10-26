"""
pipeline.py
-----------
Pure processing-pipeline orchestration for the Reactor Pressure Analyzer.

No tkinter dependency -- the staged workflow lives here so it can be driven
by the GUI, scripts, or tests alike. ``gui.py`` is a thin wrapper that builds
a :class:`ReactorPipeline`, runs its methods on a background thread, and
forwards log/progress callbacks to the on-screen widgets.

Stages
------
1. ``condense()``            -- merge the raw NDJSON into a small working
                                 file (temp file, or the conventional
                                 ``_condensed.json`` path) and cache
                                 ``cycle_points``/``cycle_start_map``. Every
                                 later stage reads the small working file
                                 instead of the large raw file.
2. ``label_phases()``        -- compute phase bins/names from the header
                                 valve sequence and, when a condensed JSON
                                 artifact is being kept, bake per-row phase
                                 labels into the working file.
3. ``attach_temperature()``  -- optional; bakes temperature + service-config
                                 metadata into the working file. Does not
                                 affect plots -- it only enriches the
                                 condensed JSON artifact. Honors
                                 ``temperature_sample_interval_s`` to
                                 downsample noisy/high-rate telemetry.
4. (detailed iSE)            -- cycle-aligned thickness data (``ise_utils.
                                 parse_ise_cycle_thickness``) is folded into
                                 the Stage 6 ``cycle_summary`` rows when the
                                 selected iSE file has ``Cycle``/``Thickness``
                                 columns; the simple single-column thickness
                                 CSV export is unaffected.
5. ``preview_cycle()``       -- render a single cycle figure for interactive
                                 use; always reflects the live shift/valve
                                 name options.
6. ``generate_outputs()``    -- batch-render cycle PNGs, the exposure CSV,
                                 the iSE thickness CSV, the animation GIF,
                                 and (when a condensed JSON artifact is kept)
                                 per-cycle ``cycle_summary`` rows appended to
                                 the working file.

``run_all()`` chains 1 -> 2 -> 3 (if enabled) -> 6 for one-click processing.
"""

from __future__ import annotations

import os
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt

from sequence_utils import (
    apply_valve_names,
    compute_phase_bins,
    make_cycle_seq_map,
    assign_phase,
    build_phase_color_map,
)
from data_parser import (
    stream_pressure, subtract_baseline,
    condense_log, condensed_path, is_condensed_file,
    load_temperature_data, load_service_config_data,
    detect_sample_interval_s, downsample_samples,
    collect_temperature_by_cycle, write_cycle_summaries,
)
from plot_utils import (
    build_segments,
    draw_cycle_figure,
    compute_leakrate_regressions,
    save_cycle_figure,
    compute_axis_limits,
    compute_exposure_table,
    save_exposure_csv,
    build_animation,
)
from ise_utils import save_ise_thickness_csv, parse_ise_cycle_thickness


@dataclass
class ProcessingOptions:
    """User-adjustable knobs that affect the pipeline stages."""
    valve_names:                dict = field(default_factory=dict)
    xlim:                       float | None = None
    ylim:                       float | None = None
    grid_x:                     bool = True
    grid_y:                     bool = True
    grid_x_spacing:             float | None = None
    grid_y_spacing:              float | None = None
    shift:                      float = 0.0
    wait_time:                  float = 0.0
    leakrate_phase_reduction:   float = 0.0
    write_condensed_json:       bool = True
    add_temperature:            bool = False
    temperature_source:         str | None = None
    selected_temperature_zones: list | None = None
    temperature_sample_interval_s: float | None = None
    ise_file_path:               str = ""
    thickness_blank_rows:        int = 0
    fps:                        float = 5.0


def _format_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(max(num_bytes, 0))
    idx = 0
    while size >= 1024.0 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    return f"{size:.2f} {units[idx]}"


def _format_phase_for_step(phase_name: str) -> str:
    parts = phase_name.split("_")
    if parts:
        parts[-1] = parts[-1].capitalize()
    return "_".join(parts)


_EXPOSURE_SUFFIXES = (
    ("_nominal_duration", "NominalDuration"),
    ("_nominal_dose", "NominalDose"),
    ("_nominal_hold", "NominalHold"),
    ("_mean_pressure", "MeanPressure"),
    ("_leak_rate", "LeakRateMTorrPerMin"),
    ("_exposure", "Exposure"),
)


def _pivot_exposure_row(row: dict) -> dict:
    """
    Turn one flattened ``compute_exposure_table`` row (``{"TDIC_exposure":
    ..., "TDIC_LR_leak_rate": ...}``) into a nested per-precursor dict,
    folding any ``<name>_LR`` columns into a ``"LeakRate"`` sub-object of
    the base precursor name.
    """
    flat: dict = {}
    for key, value in row.items():
        if key in ("cycle number", "sequence"):
            continue
        for suffix, field_name in _EXPOSURE_SUFFIXES:
            if key.endswith(suffix):
                name = key[: -len(suffix)]
                flat.setdefault(name, {})[field_name] = value
                break

    precursors: dict = {}
    for name, fields in flat.items():
        if name.endswith("_LR"):
            base = name[: -len("_LR")]
            precursors.setdefault(base, {})["LeakRate"] = fields
        else:
            precursors.setdefault(name, {}).update(fields)
    return precursors


def _pct_adapter(progress_cb: Callable[[float], None] | None, lo: float = 0.0, hi: float = 100.0):
    """
    Wrap a simple ``progress_cb(percent)`` callback into the
    ``progress_cb(done, total)`` convention used by ``condense_log``,
    ``stream_pressure``, and ``build_animation``, rescaled to ``[lo, hi]``.
    """
    if progress_cb is None:
        return None
    span = hi - lo

    def _inner(done, total):
        total = max(total, 1)
        progress_cb(lo + span * (done / total))

    return _inner


def _noop_log(_msg: str) -> None:
    pass


def _default_save(save_fn, _path: str, _label: str):
    return save_fn()


class ReactorPipeline:
    """
    Stateful, re-runnable processing pipeline for one raw data file.

    Parameters
    ----------
    raw_path, out_dir : str
    seq_dict : dict
        Output of ``sequence_utils.convert_sequence`` for the file's header.
    options : ProcessingOptions
    sequence_note_fn : callable(seq_key, phased_seq) -> str | None
        Optional annotation text shown on plots; keeps this module decoupled
        from header/recipe "SequenceNotes" details.
    save_fn : callable(save_fn, path, label) -> Any
        Optional hook to add retry-on-locked-file behavior around disk
        writes. Defaults to calling ``save_fn()`` directly.
    """

    def __init__(
        self,
        raw_path:          str | Path,
        out_dir:           str,
        seq_dict:          dict,
        options:           ProcessingOptions,
        sequence_note_fn:  Callable[[str, dict], str | None] | None = None,
        save_fn:           Callable | None = None,
    ):
        self.raw_path = Path(raw_path)
        self.out_dir  = out_dir
        self.seq_dict = seq_dict
        self.options  = options
        self._sequence_note_fn = sequence_note_fn or (lambda seq_key, phased_seq: None)
        self._save = save_fn or _default_save

        self.working_path:    Path | None = None
        self.working_is_temp: bool = False

        self.cycle_points:    dict = {}
        self.cycle_start_map: dict = {}
        self.baseline:        float = 0.0

        self.phased_seq:      dict = {}
        self.cyc_seq_map:     dict = {}
        self.all_phase_names: list = []
        self.phase_color_map: dict = {}

        self.xlim_val: float | None = None
        self.ylim_val: float | None = None
        self.exposure_rows: list | None = None
        self.cycle_summaries: list | None = None

        stem = self.raw_path.stem
        self.filename = stem[:-len("_condensed")] if stem.endswith("_condensed") else stem

        self.stage = "none"   # none -> condensed -> labeled -> temperature -> generated

    # -------------------------------------------------------------------
    #  Housekeeping
    # -------------------------------------------------------------------

    def update_recipe(self, seq_dict: dict):
        """Refresh the header-derived sequence structure (e.g. after an edit)."""
        self.seq_dict = seq_dict

    def update_sequence_note_fn(self, sequence_note_fn: Callable[[str, dict], str | None]):
        """Refresh the sequence-note callback (e.g. after a header edit)."""
        self._sequence_note_fn = sequence_note_fn or (lambda seq_key, phased_seq: None)

    def cleanup(self):
        """Remove the working file if it was a throwaway temp file."""
        if self.working_is_temp and self.working_path and self.working_path.exists():
            try:
                self.working_path.unlink()
            except OSError:
                pass

    def _build_phase_structure(self, shift: float) -> tuple[dict, dict]:
        named_seq = apply_valve_names(self.seq_dict, self.options.valve_names)
        phased_seq = compute_phase_bins(named_seq, shift=shift)
        cyc_seq_map = make_cycle_seq_map(phased_seq)
        return phased_seq, cyc_seq_map

    def _phase_lookup(self, cycle, time_s, raw_step, payload):
        seq_key = self.cyc_seq_map.get(cycle)
        if not seq_key:
            return None
        bins = self.phased_seq.get(seq_key, {}).get("phase_bins", [])
        names = self.phased_seq.get(seq_key, {}).get("phase_names", [])
        if not bins or not names:
            return None
        t0 = self.cycle_start_map.get(cycle)
        if t0 is None:
            return None
        phase = assign_phase(time_s - t0, bins, names)
        return _format_phase_for_step(phase) if phase else None

    # -------------------------------------------------------------------
    #  Stage 1 -- condense
    # -------------------------------------------------------------------

    def condense(self, progress_cb: Callable[[float], None] | None = None, log_cb=None) -> dict:
        """
        Merge the raw NDJSON into a small working file and cache the parsed
        pressure data. Makes every later stage fast because they all read
        the (now small) working file instead of the original raw file.
        """
        log = log_cb or _noop_log

        is_input_condensed = is_condensed_file(self.raw_path)
        if self.options.write_condensed_json:
            target = self.raw_path if is_input_condensed else condensed_path(self.raw_path)
            self.working_is_temp = False
        else:
            fd, tmp_name = tempfile.mkstemp(prefix=f"{self.filename}_", suffix=".working.json")
            os.close(fd)
            target = Path(tmp_name)
            self.working_is_temp = True

        log("Reading & condensing data...")
        stats = self._save(
            lambda: condense_log(
                self.raw_path, target,
                progress_cb=_pct_adapter(progress_cb, 0, 60),
                return_stats=True,
            ),
            str(target),
            "condensed log",
        )
        self.working_path = target

        log(f"  Raw rows: {stats['total_rows']:,} total, {stats['pressure_rows']:,} pressure")
        log(f"  File size: {_format_bytes(stats['input_size_bytes'])} -> "
            f"{_format_bytes(stats['output_size_bytes'])} "
            f"({stats['size_reduction_pct']:.1f}% reduction)")

        self.cycle_points, self.cycle_start_map = stream_pressure(
            self.working_path,
            wait_time=self.options.wait_time,
            progress_cb=_pct_adapter(progress_cb, 60, 90),
        )
        self.cycle_points, self.baseline = subtract_baseline(self.cycle_points)
        max_ct, max_p = compute_axis_limits(self.cycle_points, self.cycle_start_map)
        self.xlim_val = self.options.xlim if self.options.xlim else max_ct
        self.ylim_val = self.options.ylim if self.options.ylim else max_p

        log(f"  {len(self.cycle_points)} cycles, "
            f"{sum(len(v) for v in self.cycle_points.values()):,} pressure points")
        log(f"  Baseline subtracted: {self.baseline:.2f} mTorr")

        if progress_cb:
            progress_cb(100)
        self.stage = "condensed"
        return stats

    # -------------------------------------------------------------------
    #  Stage 2 -- label sequences & phases
    # -------------------------------------------------------------------

    def label_phases(self, log_cb=None) -> None:
        """
        Compute phase bins/names from the header valve sequence (fast,
        in-memory) and, if a condensed JSON artifact is being kept, bake
        per-row phase labels into the working file.
        """
        log = log_cb or _noop_log

        self.phased_seq, self.cyc_seq_map = self._build_phase_structure(self.options.shift)

        all_phase_names: list = []
        for seq_data in self.phased_seq.values():
            for phase_name in seq_data.get("phase_names", []):
                if phase_name not in all_phase_names:
                    all_phase_names.append(phase_name)
        self.all_phase_names = all_phase_names
        self.phase_color_map = build_phase_color_map(all_phase_names)

        for seq_key, seq_data in self.phased_seq.items():
            log(f"  {seq_key} bins (s): {seq_data.get('phase_bins', [])}")
            log(f"  {seq_key} phases  : {seq_data.get('phase_names', [])}")

        if self.options.write_condensed_json and self.working_path is not None:
            log("Labeling phases in condensed log...")
            stats = self._save(
                lambda: condense_log(
                    self.working_path, self.working_path,
                    phase_lookup=self._phase_lookup,
                    return_stats=True,
                ),
                str(self.working_path),
                "condensed log",
            )
            log(f"  Labeled {stats['rows_written']:,} rows")

        if self.stage == "none":
            self.stage = "labeled"
        elif self.stage == "condensed":
            self.stage = "labeled"

    # -------------------------------------------------------------------
    #  Stage 3 -- attach temperature (optional)
    # -------------------------------------------------------------------

    def attach_temperature(self, progress_cb: Callable[[float], None] | None = None, log_cb=None) -> dict | None:
        """
        Bake temperature + service-config metadata into the working file.
        Optional, and only meaningful when a condensed JSON artifact is kept
        (temperature data never affects pressure plots).
        """
        log = log_cb or _noop_log

        if not self.options.write_condensed_json or self.working_path is None:
            log("Temperature attachment skipped: run Condense with "
                "'Write condensed data JSON' enabled first.")
            return None
        if not self.options.add_temperature or not self.options.temperature_source:
            log("Temperature attachment skipped: no temperature source selected.")
            return None

        temperature_samples = load_temperature_data(self.options.temperature_source)
        service_config_samples = load_service_config_data(self.options.temperature_source)
        log(f"  Loaded {len(temperature_samples):,} temperature samples")
        log(f"  Loaded {len(service_config_samples):,} service config entries")

        interval = self.options.temperature_sample_interval_s
        if interval:
            before = len(temperature_samples)
            temperature_samples = downsample_samples(temperature_samples, interval)
            log(f"  Downsampled temperature samples to {interval:.1f}s interval: "
                f"{before:,} -> {len(temperature_samples):,}")

        stats = self._save(
            lambda: condense_log(
                self.working_path, self.working_path,
                progress_cb=_pct_adapter(progress_cb, 0, 100),
                temperature_samples=temperature_samples,
                temperature_zones_to_keep=self.options.selected_temperature_zones,
                service_config_samples=service_config_samples,
                return_stats=True,
            ),
            str(self.working_path),
            "condensed log",
        )
        log(f"  Attached temperature data to {stats['rows_written']:,} rows")
        if progress_cb:
            progress_cb(100)
        self.stage = "temperature"
        return stats

    @staticmethod
    def detect_temperature_interval(temperature_source: str) -> float | None:
        """Convenience for the GUI: auto-suggest a downsampling interval."""
        samples = load_temperature_data(temperature_source)
        return detect_sample_interval_s(samples)

    # -------------------------------------------------------------------
    #  Stage 5 -- preview
    # -------------------------------------------------------------------

    def preview_cycle(
        self,
        cycle: int,
        progress_cb: Callable[[float], None] | None = None,
        log_cb=None,
    ):
        """
        Render a single cycle figure. Always recomputes the phase structure
        from the current options (shift/valve names), so tweaking those and
        re-previewing never requires re-running Condense.
        """
        log = log_cb or _noop_log

        if self.working_path is not None and cycle in self.cycle_points:
            cycle_points = {cycle: self.cycle_points[cycle]}
            cycle_start_map = (
                {cycle: self.cycle_start_map[cycle]} if cycle in self.cycle_start_map else {}
            )
        else:
            source = self.working_path or self.raw_path
            log(f"Preview: reading cycle {cycle}...")
            cycle_points, cycle_start_map = stream_pressure(
                source,
                wait_time=self.options.wait_time,
                progress_cb=_pct_adapter(progress_cb, 0, 85),
                target_cycle=cycle,
            )
        if cycle not in cycle_points:
            raise ValueError(f"Cycle {cycle} not found in the data.")

        cycle_points, baseline = subtract_baseline(cycle_points)
        max_ct, max_p = compute_axis_limits(cycle_points, cycle_start_map)
        xlim_val = self.options.xlim if self.options.xlim else max_ct
        ylim_val = self.options.ylim if self.options.ylim else max_p

        phased_seq, cyc_seq_map = self._build_phase_structure(self.options.shift)
        unshifted_seq, _ = self._build_phase_structure(0.0)

        all_phase_names: list = []
        for seq_data in phased_seq.values():
            for phase_name in seq_data.get("phase_names", []):
                if phase_name not in all_phase_names:
                    all_phase_names.append(phase_name)
        phase_color_map = build_phase_color_map(all_phase_names)

        seq_key = cyc_seq_map.get(cycle)
        segs = build_segments(
            cycle, cycle_points, cycle_start_map, phased_seq, cyc_seq_map, assign_phase,
        )
        leakrate_regressions = compute_leakrate_regressions(
            cycle, cycle_points, cycle_start_map, phased_seq, cyc_seq_map, assign_phase,
            self.options.leakrate_phase_reduction,
        )
        fig = draw_cycle_figure(
            cycle, self.filename, segs, phase_color_map, all_phase_names,
            xlim_val, ylim_val,
            grid_x=self.options.grid_x, grid_y=self.options.grid_y,
            grid_x_spacing=self.options.grid_x_spacing,
            grid_y_spacing=self.options.grid_y_spacing,
            phase_background=unshifted_seq.get(seq_key, {}),
            leakrate_regressions=leakrate_regressions,
            sequence_note=self._sequence_note_fn(seq_key, phased_seq),
            figsize=(10, 7),
        )
        if progress_cb:
            progress_cb(100)
        log(f"Preview ready: cycle {cycle} ({len(cycle_points[cycle]):,} points, "
            f"baseline {baseline:.2f} mTorr).")
        return fig

    # -------------------------------------------------------------------
    #  Stage 6 -- generate plots & animation
    # -------------------------------------------------------------------

    def generate_outputs(self, progress_cb: Callable[[float], None] | None = None, log_cb=None) -> dict:
        """
        Batch-render cycle PNGs, the exposure CSV, the iSE thickness CSV,
        and the animation GIF. Re-derives the phase structure so this always
        reflects the current shift/valve names even if step 2 was skipped.
        """
        log = log_cb or _noop_log

        if not self.cycle_points:
            raise RuntimeError("Run the Condense step before generating outputs.")

        self.label_phases(log_cb=log)

        os.makedirs(self.out_dir, exist_ok=True)
        cycles_sorted = sorted(self.cycle_points.keys())
        total = len(cycles_sorted) or 1
        log("Generating plots...")

        for i, cycle in enumerate(cycles_sorted):
            seq_key = self.cyc_seq_map.get(cycle)
            if seq_key is None:
                if progress_cb:
                    progress_cb((i + 1) / total * 50)
                continue

            segs = build_segments(
                cycle, self.cycle_points, self.cycle_start_map,
                self.phased_seq, self.cyc_seq_map, assign_phase,
            )
            fig = draw_cycle_figure(
                cycle, self.filename, segs, self.phase_color_map, self.all_phase_names,
                self.xlim_val, self.ylim_val,
                grid_x=self.options.grid_x, grid_y=self.options.grid_y,
                grid_x_spacing=self.options.grid_x_spacing,
                grid_y_spacing=self.options.grid_y_spacing,
                sequence_note=self._sequence_note_fn(seq_key, self.phased_seq),
            )
            png_path = os.path.join(self.out_dir, f"cycle_{cycle:04d}.png")
            try:
                self._save(lambda: save_cycle_figure(fig, cycle, self.out_dir), png_path, "PNG plot")
            finally:
                plt.close(fig)
            if progress_cb:
                progress_cb((i + 1) / total * 50)

        log(f"Done -- {len(cycles_sorted)} plots saved to:\n  {self.out_dir}")

        log("Computing phase exposures...")
        if self.options.leakrate_phase_reduction > 0:
            log(f"  LeakRate phase reduction: {self.options.leakrate_phase_reduction:.3f} s on each side")
        exposure_rows = compute_exposure_table(
            cycles_sorted, self.cycle_points, self.cycle_start_map,
            self.phased_seq, self.cyc_seq_map, assign_phase,
            leakrate_phase_reduction=self.options.leakrate_phase_reduction,
        )
        self.exposure_rows = exposure_rows
        csv_path = os.path.join(self.out_dir, f"{self.filename}_exposure.csv")
        self._save(
            lambda: save_exposure_csv(exposure_rows, self.out_dir, self.filename),
            csv_path, "exposure CSV",
        )
        log(f"  Exposure CSV: {Path(csv_path).name}  ({len(exposure_rows)} rows)")
        if progress_cb:
            progress_cb(65)

        thickness_path = None
        ise_path = (self.options.ise_file_path or "").strip()
        if ise_path and Path(ise_path).is_file():
            thickness_path = os.path.join(self.out_dir, f"{self.filename}_thickness.csv")
            n_thickness = self._save(
                lambda: save_ise_thickness_csv(
                    ise_path, thickness_path, blank_rows=self.options.thickness_blank_rows,
                ),
                thickness_path, "thickness CSV",
            )
            log(f"  Thickness CSV: {Path(thickness_path).name} "
                f"({n_thickness} rows from {Path(ise_path).name})")
        else:
            log("  Thickness CSV: skipped (select a valid iSE data file)")
        if progress_cb:
            progress_cb(75)

        log(f"Generating animation ({len(cycles_sorted)} frames @ {self.options.fps:.0f} fps)...")
        anim_path = os.path.join(self.out_dir, f"{self.filename}_animation.gif")
        self._save(
            lambda: build_animation(
                cycles_sorted, self.cycle_points, self.cycle_start_map,
                self.phased_seq, self.cyc_seq_map, self.all_phase_names, self.phase_color_map,
                assign_phase, self.xlim_val, self.ylim_val, self.filename, self.out_dir,
                sequence_note_fn=lambda cyc, seq_key: self._sequence_note_fn(seq_key or "", self.phased_seq),
                fps=max(1, int(self.options.fps)),
                progress_cb=_pct_adapter(progress_cb, 75, 90),
            ),
            anim_path, "animation GIF",
        )
        log(f"Animation saved: {Path(anim_path).name}")
        if progress_cb:
            progress_cb(90)

        log("Assembling cycle summaries...")
        self.generate_cycle_summaries(log_cb=log)
        if progress_cb:
            progress_cb(100)

        self.stage = "generated"
        return {
            "plots": len(cycles_sorted),
            "exposure_csv": csv_path,
            "thickness_csv": thickness_path,
            "animation": anim_path,
            "cycle_summaries": len(self.cycle_summaries or []),
        }

    def generate_cycle_summaries(self, log_cb=None) -> list[dict]:
        """
        Assemble one ``cycle_summary`` dict per cycle -- start/end time,
        sequence note, per-precursor exposure/leak-rate (from
        ``compute_exposure_table``), per-zone temperature mean/stdev (from
        the working file's baked-in ``TemperatureZones``, if Stage 3 ran),
        and cycle-aligned iSE thickness readings (if the selected iSE file
        has ``Cycle``/``Thickness`` columns). When a condensed JSON artifact
        is being kept, the rows are also appended to the working file.
        """
        log = log_cb or _noop_log

        cycles_sorted = sorted(self.cycle_points.keys())
        cycle_zero = min(cycles_sorted) if cycles_sorted else 0
        exposure_rows = self.exposure_rows or []
        exposure_by_cycle = {
            row["cycle number"] + cycle_zero: row for row in exposure_rows
        }

        temperature_by_cycle: dict = {}
        zone_names: dict = {}
        if self.options.write_condensed_json and self.working_path is not None:
            try:
                temperature_by_cycle = collect_temperature_by_cycle(
                    self.working_path, self.options.selected_temperature_zones,
                )
            except Exception as exc:
                log(f"  WARNING: could not read temperature data for cycle summaries: {exc}")
            if self.options.temperature_source:
                try:
                    config_samples = load_service_config_data(self.options.temperature_source)
                    if config_samples:
                        zone_names = config_samples[-1][1].get("zone_names", {}) or {}
                except Exception:
                    pass

        thickness_by_cycle: dict = {}
        ise_path = (self.options.ise_file_path or "").strip()
        if ise_path and Path(ise_path).is_file():
            try:
                thickness_by_cycle = parse_ise_cycle_thickness(ise_path)
            except Exception as exc:
                log(f"  WARNING: could not parse cycle-aligned iSE data: {exc}")

        summaries = []
        for cycle in cycles_sorted:
            pts = self.cycle_points.get(cycle, [])
            if not pts:
                continue
            seq_key = self.cyc_seq_map.get(cycle)
            start_time = self.cycle_start_map.get(cycle, pts[0][0])
            end_time = max(t for t, _ in pts)

            summary = {
                "Cycle": cycle,
                "Sequence": seq_key,
                "SequenceNote": self._sequence_note_fn(seq_key, self.phased_seq),
                "StartTime": start_time,
                "EndTime": end_time,
            }

            exposure_row = exposure_by_cycle.get(cycle)
            if exposure_row is not None:
                summary["Precursors"] = _pivot_exposure_row(exposure_row)

            cycle_temps = temperature_by_cycle.get(cycle)
            if cycle_temps:
                summary["Temperature"] = {
                    zone: {
                        "Name": zone_names.get(zone, ""),
                        "SetPointC": bucket["setpoint"],
                        "MeanC": (
                            round(statistics.fmean(bucket["temps"]), 3)
                            if bucket["temps"] else None
                        ),
                        "StdDevC": (
                            round(statistics.pstdev(bucket["temps"]), 3)
                            if len(bucket["temps"]) > 1 else 0.0
                        ),
                    }
                    for zone, bucket in cycle_temps.items()
                }

            cycle_thickness = thickness_by_cycle.get(cycle)
            if cycle_thickness:
                summary["Thickness"] = cycle_thickness

            summaries.append(summary)

        if self.options.write_condensed_json and self.working_path is not None:
            n_written = write_cycle_summaries(self.working_path, summaries)
            log(f"  Wrote {n_written} cycle_summary rows to {self.working_path.name}")
        else:
            log("  Cycle summaries computed in memory only "
                "(enable 'Write condensed data JSON' to persist them)")

        self.cycle_summaries = summaries
        return summaries

    # -------------------------------------------------------------------
    #  Convenience -- run everything in one call
    # -------------------------------------------------------------------

    def run_all(self, progress_cb: Callable[[float], None] | None = None, log_cb=None) -> dict:
        """Condense -> label phases -> (optional) attach temperature -> generate outputs."""
        log = log_cb or _noop_log

        def _sub(lo, hi):
            if progress_cb is None:
                return None
            return lambda pct: progress_cb(lo + (hi - lo) * (pct / 100.0))

        self.condense(progress_cb=_sub(0, 20), log_cb=log)
        self.label_phases(log_cb=log)
        if progress_cb:
            progress_cb(25)

        if self.options.add_temperature and self.options.temperature_source:
            self.attach_temperature(progress_cb=_sub(25, 35), log_cb=log)
        elif progress_cb:
            progress_cb(35)

        return self.generate_outputs(progress_cb=_sub(35, 100), log_cb=log)
