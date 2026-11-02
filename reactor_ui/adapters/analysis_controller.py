"""Validated, immutable form snapshots for the existing processing pipeline."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass

from analysis_metadata import effective_valve_names, parse_experimental_details
from pipeline import ProcessingOptions


@dataclass(frozen=True)
class AnalysisInputs:
    valve_names: tuple[tuple[int, str], ...] = ()
    xlim: str = "auto"
    ylim: str = "auto"
    grid_x: bool = True
    grid_y: bool = True
    grid_x_spacing: str = ""
    grid_y_spacing: str = ""
    shift: str = "0"
    wait_time: str = "0"
    leakrate_phase_reduction: str = "0"
    write_condensed_json: bool = True
    add_temperature: bool = False
    add_ise: bool = False
    temperature_source: str | tuple[str, ...] | None = None
    temperature_directory: str = ""
    temperature_files: tuple[str, ...] = ()
    temperature_source_mode: str = "directory"
    selected_temperature_zones: tuple[str, ...] = ()
    temperature_sample_interval_s: str = ""
    plot_temperature_zones: tuple[str, ...] | None = None
    ise_file_path: str = ""
    ise_valve: str = "Valve7"
    ise_first_cycle: str = "1"
    thickness_blank_rows: str = "0"
    fps: str = "5"


@dataclass(frozen=True)
class ProcessingSnapshot:
    valve_names: tuple[tuple[int, str], ...]
    xlim: float | None
    ylim: float | None
    grid_x: bool
    grid_y: bool
    grid_x_spacing: float | None
    grid_y_spacing: float | None
    shift: float
    wait_time: float
    leakrate_phase_reduction: float
    write_condensed_json: bool
    add_temperature: bool
    add_ise: bool
    temperature_source: str | tuple[str, ...] | None
    selected_temperature_zones: tuple[str, ...]
    temperature_sample_interval_s: float | None
    plot_temperature_zones: tuple[str, ...] | None
    ise_file_path: str
    ise_valve: str
    ise_first_cycle: float
    thickness_blank_rows: int
    fps: float

    def to_options(self) -> ProcessingOptions:
        source = list(self.temperature_source) if isinstance(self.temperature_source, tuple) else self.temperature_source
        return ProcessingOptions(
            valve_names=dict(self.valve_names),
            xlim=self.xlim,
            ylim=self.ylim,
            grid_x=self.grid_x,
            grid_y=self.grid_y,
            grid_x_spacing=self.grid_x_spacing,
            grid_y_spacing=self.grid_y_spacing,
            shift=self.shift,
            wait_time=self.wait_time,
            leakrate_phase_reduction=self.leakrate_phase_reduction,
            write_condensed_json=self.write_condensed_json,
            add_temperature=self.add_temperature,
            add_ise=self.add_ise,
            temperature_source=source,
            selected_temperature_zones=list(self.selected_temperature_zones),
            temperature_sample_interval_s=self.temperature_sample_interval_s,
            plot_temperature_zones=(
                list(self.plot_temperature_zones) if self.plot_temperature_zones is not None else None
            ),
            ise_file_path=self.ise_file_path,
            ise_valve=self.ise_valve,
            ise_first_cycle=self.ise_first_cycle,
            thickness_blank_rows=self.thickness_blank_rows,
            fps=self.fps,
        )


def _number(text: str, label: str, *, default: float | None, minimum: float | None = None) -> float | None:
    value = text.strip()
    if not value or (value.lower() == "auto" and default is None):
        return default
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number.") from exc
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise ValueError(f"{label} must be finite and at least {minimum:g}." if minimum is not None else f"{label} must be finite.")
    return number


def _positive_optional(text: str, label: str) -> float | None:
    value = _number(text, label, default=None)
    if value is not None and value <= 0:
        raise ValueError(f"{label} must be greater than zero.")
    return value


def build_processing_snapshot(inputs: AnalysisInputs, details_value: object) -> ProcessingSnapshot:
    details = parse_experimental_details(details_value)
    names = effective_valve_names(dict(inputs.valve_names), details)
    try:
        blank_rows = int(inputs.thickness_blank_rows.strip() or "0")
    except ValueError as exc:
        raise ValueError("Thickness blank rows must be a non-negative integer.") from exc
    if blank_rows < 0:
        raise ValueError("Thickness blank rows must be a non-negative integer.")
    shift = _number(inputs.shift, "Phase shift", default=0.0)
    wait = _number(inputs.wait_time, "Wait time", default=0.0, minimum=0.0)
    reduction = _number(inputs.leakrate_phase_reduction, "LeakRate phase reduction", default=0.0, minimum=0.0)
    first_cycle = _number(inputs.ise_first_cycle, "iSE first cycle", default=None, minimum=0.0)
    fps = _number(inputs.fps, "Animation FPS", default=5.0)
    if first_cycle is None:
        raise ValueError("iSE first cycle must be a non-negative number.")
    if fps is None or fps <= 0:
        raise ValueError("Animation FPS must be greater than zero.")
    assert shift is not None and wait is not None and reduction is not None
    return ProcessingSnapshot(
        valve_names=tuple(sorted(names.items())),
        xlim=_positive_optional(inputs.xlim, "X maximum"),
        ylim=_positive_optional(inputs.ylim, "Y maximum"),
        grid_x=inputs.grid_x,
        grid_y=inputs.grid_y,
        grid_x_spacing=_positive_optional(inputs.grid_x_spacing, "X grid spacing"),
        grid_y_spacing=_positive_optional(inputs.grid_y_spacing, "Y grid spacing"),
        shift=shift,
        wait_time=wait,
        leakrate_phase_reduction=reduction,
        write_condensed_json=inputs.write_condensed_json,
        add_temperature=inputs.add_temperature,
        add_ise=inputs.add_ise,
        temperature_source=inputs.temperature_source,
        selected_temperature_zones=inputs.selected_temperature_zones,
        temperature_sample_interval_s=_positive_optional(
            inputs.temperature_sample_interval_s, "Temperature sample interval"
        ),
        plot_temperature_zones=inputs.plot_temperature_zones,
        ise_file_path=inputs.ise_file_path.strip(),
        ise_valve=inputs.ise_valve.strip() or "Valve7",
        ise_first_cycle=first_cycle,
        thickness_blank_rows=blank_rows,
        fps=fps,
    )


def settings_after_processing(state: dict, inputs: AnalysisInputs, reactor: str, snapshot: ProcessingSnapshot) -> dict:
    updated = copy.deepcopy(state)
    updated["last_processing_settings"] = {
        "xlim": inputs.xlim.strip(),
        "ylim": inputs.ylim.strip(),
        "grid_x": inputs.grid_x,
        "grid_y": inputs.grid_y,
        "grid_x_spacing": inputs.grid_x_spacing.strip(),
        "grid_y_spacing": inputs.grid_y_spacing.strip(),
        "shift": inputs.shift.strip(),
        "wait_time": inputs.wait_time.strip(),
        "fps": inputs.fps.strip(),
        "leakrate_phase_reduction": inputs.leakrate_phase_reduction.strip(),
        "thickness_blank_rows": inputs.thickness_blank_rows.strip(),
        "write_condensed_json": inputs.write_condensed_json,
        "add_temperature": inputs.add_temperature,
        "temperature_directory": inputs.temperature_directory.strip(),
        "temperature_file": list(inputs.temperature_files),
        "temperature_source_mode": inputs.temperature_source_mode,
        "ise_valve": snapshot.ise_valve,
    }
    saved = updated.get("last_valve_names", {})
    if not isinstance(saved, dict):
        raise ValueError("Saved valve names must be an object.")
    if all(not isinstance(value, dict) for value in saved.values()):
        saved = {reactor: dict(saved)}
    by_reactor = saved.setdefault(reactor, {})
    if not isinstance(by_reactor, dict):
        raise ValueError(f"Saved valve names for {reactor} must be an object.")
    by_reactor.update({str(number): name for number, name in snapshot.valve_names})
    updated["last_valve_names"] = saved
    return updated
