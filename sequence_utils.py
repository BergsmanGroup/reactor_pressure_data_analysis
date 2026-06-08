"""
sequence_utils.py
-----------------
Pure data-processing helpers for reactor valve sequences and phase bins.
No GUI or I/O dependencies — safe to import anywhere.
"""

import re
import copy
import hashlib
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
    a structured dict.

    Input
    -----
    [[cycles, valve_num, t0, t1, t2, t3, t4, t5, t6],
     [0,      valve_num2, t0, ...],   # 0 in position 0 = additional valve
     ...]

    Output
    ------
    {
        "seq1": {"cycles": N, "valve7": [t0..t6]},
        "seq2": {"cycles": M, "valve5": [t0..t6], "valve6": [t0..t6]},
        ...
    }
    """
    result: dict = {}
    seq_count = 1
    current_seq: dict = {}

    for row in valve_sequence:
        if not any(row):
            continue
        cycle_count = int(row[0])
        valve_num   = int(row[1])
        timing_vals = list(row[2:2 + len(PHASE_TYPES)])
        timing      = timing_vals + [0] * (len(PHASE_TYPES) - len(timing_vals))

        if cycle_count == 0:
            # Additional valve appended to the current sequence
            current_seq[f"valve{valve_num}"] = timing
        else:
            # New sequence begins
            if current_seq:
                result[f"seq{seq_count}"] = current_seq
                seq_count += 1
            current_seq = {"cycles": cycle_count, f"valve{valve_num}": timing}

    if current_seq:
        result[f"seq{seq_count}"] = current_seq

    return result


def apply_valve_names(seq_dict: dict, valve_names: dict) -> dict:
    """
    Return a deep copy of *seq_dict* with valve keys renamed using
    *valve_names* = ``{valve_number_int: display_string}``.

    Example: ``"valve7"`` -> ``"valveTDIC"``  when  ``valve_names = {7: "TDIC"}``
    """
    renamed = {}
    for seq_key, seq_data in seq_dict.items():
        new_seq = {}
        for k, v in seq_data.items():
            if k.startswith("valve"):
                m = re.search(r"\d+", k)
                if m:
                    vnum  = int(m.group())
                    label = valve_names.get(vnum, str(vnum))
                    new_seq[f"valve{label}"] = copy.copy(v)
                else:
                    new_seq[k] = copy.copy(v)
            else:
                new_seq[k] = v
        renamed[seq_key] = new_seq
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

        for k, v in seq_data.items():
            if k == "cycles":
                continue
            display = k[len("valve"):]    # strip "valve" prefix -> "TDIC", "7", …
            for phase_type in PHASE_TYPES:
                all_names.append(f"{seq_key}_{display}_{phase_type}")
            compact_vals.extend(v)

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


def _stable_phase_color(phase_name: str) -> tuple[float, float, float, float]:
    """
    Generate a deterministic RGBA color from *phase_name*.

    This keeps color assignment stable even when new phases appear, because the
    color depends only on the canonical phase name and not on list order.
    """
    digest = hashlib.sha1(phase_name.encode("utf-8")).digest()
    hue = int.from_bytes(digest[:4], "big") / 2**32
    sat = 0.55 + (digest[4] / 255.0) * 0.25
    val = 0.70 + (digest[5] / 255.0) * 0.20
    red, green, blue = hsv_to_rgb(hue, sat, val)
    return (red, green, blue, 1.0)


def build_phase_color_map(all_phase_names: list, cmap_name: str = "tab20") -> dict:
    """
    Return ``{phase_name: rgba_color}`` using a deterministic, sequence-
    independent phase identity.

    Example: ``seq1_6_dose`` and ``seq20_6_dose`` will receive the same color.
    Adding new phases does not change any existing assignments.
    """
    canonical_colors: dict = {}
    phase_color_map: dict = {}

    for phase_name in all_phase_names:
        canonical_name = _canonical_phase_name(phase_name)
        color = canonical_colors.setdefault(
            canonical_name,
            _stable_phase_color(canonical_name),
        )
        phase_color_map[phase_name] = color

    return phase_color_map
