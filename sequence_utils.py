"""
sequence_utils.py
-----------------
Pure data-processing helpers for reactor valve sequences and phase bins.
No GUI or I/O dependencies — safe to import anywhere.
"""

import re
import copy
from colorsys import hsv_to_rgb
import numpy as np

# Phase slot order is fixed and must match the controller firmware convention.
PHASE_TYPES = ["prepump", "dosepump", "dosen2", "dose", "hold", "prepurge", "purge"]


# =============================================================================
#  Sequence structure helpers
# =============================================================================

def convert_sequence(valve_sequence: list) -> dict:
    """
    Convert the raw list-of-lists ``valveSequence`` from the JSON header into
    a structured dict.  Multiple rows with the same valve number within one
    sequence are preserved in insertion order via ``valve_rows``.

    Output
    ------
    {
        "seq1": {"cycles": N, "valve_rows": [(valve_num_int, [t0..t6]), ...]},
        ...
    }
    """
    result: dict = {}
    seq_count = 1
    current_seq: dict | None = None

    for row in valve_sequence:
        if not any(row):
            continue
        cycle_count = int(row[0])
        valve_num   = int(row[1])
        timing_vals = list(row[2:2 + len(PHASE_TYPES)])
        timing      = timing_vals + [0] * (len(PHASE_TYPES) - len(timing_vals))

        if cycle_count == 0:
            if current_seq is not None:
                current_seq["valve_rows"].append((valve_num, timing))
        else:
            if current_seq is not None:
                result[f"seq{seq_count}"] = current_seq
                seq_count += 1
            current_seq = {"cycles": cycle_count, "valve_rows": [(valve_num, timing)]}

    if current_seq is not None:
        result[f"seq{seq_count}"] = current_seq

    return result


def apply_valve_names(seq_dict: dict, valve_names: dict) -> dict:
    """
    Return a deep copy of *seq_dict* with valve numbers in ``valve_rows``
    replaced by display strings from *valve_names*.
    """
    renamed = {}
    for seq_key, seq_data in seq_dict.items():
        new_rows = [
            (valve_names.get(vnum, str(vnum)), copy.copy(timing))
            for vnum, timing in seq_data.get("valve_rows", [])
        ]
        renamed[seq_key] = {"cycles": seq_data["cycles"], "valve_rows": new_rows}
    return renamed


def compute_phase_bins(seq_dict: dict, shift: float = 0.0) -> dict:
    """
    For each sequence, compute ``phase_bins`` (cumulative seconds, N+1 floats)
    and ``phase_names`` (N strings) and store them back in a deep copy.

    Phase names use the form ``"seqN_ValveName_phasetype"``,
    e.g. ``"seq2_TDIC_dose"``.

    Zero-valued timing slots produce no bin (matching ``cut_by_phases`` in the
    legacy ``data_processing.py``).
    """
    result = copy.deepcopy(seq_dict)

    for seq_key, seq_data in result.items():
        compact_vals: list = []
        all_names:    list = []

        for display, timing in seq_data.get("valve_rows", []):
            display = str(display)
            # A row with no dosing phases but a nonzero hold is a leak-rate step;
            # rename its hold slot so it gets a distinct phase label.
            vals = [float(v) for v in timing]
            is_lr = (
                len(vals) >= 5
                and abs(vals[1]) <= 1e-12   # dosepump
                and abs(vals[2]) <= 1e-12   # dosen2
                and abs(vals[3]) <= 1e-12   # dose
                and abs(vals[4]) > 1e-12    # hold
            )
            lr_display = f"{display}_LR" if is_lr else display
            for i, phase_type in enumerate(PHASE_TYPES):
                if is_lr and phase_type == "hold":
                    all_names.append(f"{seq_key}_{lr_display}_LeakRate")
                else:
                    all_names.append(f"{seq_key}_{lr_display}_{phase_type}")
            compact_vals.extend(timing)

        phase_bins:  list = [0.0]
        phase_names: list = []
        cumtime = 0.0

        for idx, val in enumerate(compact_vals):
            if val != 0:
                cumtime += float(val) + shift
                phase_bins.append(cumtime)
                if idx < len(all_names):
                    phase_names.append(all_names[idx])

        seq_data["phase_bins"]  = phase_bins
        seq_data["phase_names"] = phase_names

    return result


def make_cycle_seq_map(seq_dict: dict) -> dict:
    """
    Build ``{global_cycle_int: "seqN"}`` from the per-sequence cycle counts.
    Global cycle numbering starts at 1.
    """
    mapping: dict = {}
    global_cycle = 1
    def _seq_sort_key(name: str):
        m = re.fullmatch(r"seq(\d+)", str(name))
        return int(m.group(1)) if m else float("inf")

    for seq_key in sorted(seq_dict.keys(), key=_seq_sort_key):
        n = seq_dict[seq_key].get("cycles", 0)
        for _ in range(n):
            mapping[global_cycle] = seq_key
            global_cycle += 1
    return mapping


def assign_phase(cycle_time_s: float, phase_bins: list, phase_names: list):
    """
    Return the phase name for a cycle-relative time (seconds), or ``None``
    if *cycle_time_s* falls before the first bin or *phase_bins* is empty.
    """
    if not phase_bins or cycle_time_s < phase_bins[0]:
        return None
    idx = int(np.searchsorted(phase_bins, cycle_time_s, side="right")) - 1
    if 0 <= idx < len(phase_names):
        return phase_names[idx]
    return None


def _canonical_phase_name(phase_name: str) -> str:
    """
    Drop the leading ``seqN_`` prefix so the same phase in different sequences
    shares a single color identity.
    """
    parts = phase_name.split("_", 1)
    if len(parts) == 2 and re.fullmatch(r"seq\d+", parts[0]):
        return parts[1]
    return phase_name


_PHASE_COLORS = (
    "#0072B2",  # blue
    "#D55E00",  # vermillion
    "#009E73",  # green
    "#CC79A7",  # purple
    "#E69F00",  # orange
    "#56B4E9",  # sky blue
    "#A65628",  # brown
    "#F0E442",  # yellow
    "#332288",  # indigo
    "#117733",  # dark green
    "#AA4499",  # magenta
    "#44AA99",  # teal
    "#999933",  # olive
    "#88CCEE",  # light cyan
    "#CC6677",  # rose
    "#DDCC77",  # sand
)


def build_phase_color_map(all_phase_names: list, cmap_name: str = "tab20") -> dict:
    """
    Return ``{phase_name: color}`` using an ordered, high-contrast palette.

    Example: ``seq1_6_dose`` and ``seq20_6_dose`` will receive the same color.
    Colors are assigned to canonical phase identities in first-seen order so
    neighboring phases are visually distinct.  ``cmap_name`` is retained for
    API compatibility with older callers.
    """
    canonical_colors: dict = {}
    phase_color_map: dict = {}

    for phase_name in all_phase_names:
        canonical_name = _canonical_phase_name(phase_name)
        if canonical_name not in canonical_colors:
            color_index = len(canonical_colors)
            if color_index < len(_PHASE_COLORS):
                color = _PHASE_COLORS[color_index]
            else:
                hue = (color_index * 0.61803398875) % 1.0
                red, green, blue = hsv_to_rgb(hue, 0.72, 0.85)
                color = (red, green, blue, 1.0)
            canonical_colors[canonical_name] = color
        color = canonical_colors[canonical_name]
        phase_color_map[phase_name] = color

    return phase_color_map
