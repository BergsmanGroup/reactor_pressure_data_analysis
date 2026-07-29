"""
plot_utils.py
-------------
Figure-building utilities for the Reactor Pressure Analyzer.

All functions work with plain matplotlib Figure objects so they can be used
both for headless batch-saving (Agg backend) and for embedding in the tkinter
preview window (FigureCanvasTkAgg).

Public API
----------
build_segments(cycle, cycle_points, cycle_start_map, phased_seq, cyc_seq_map,
               assign_phase_fn) -> dict
    Segment raw pressure points for one cycle into per-phase lists.

draw_cycle_figure(cycle, filename, segments, phase_color_map,
                  all_phase_names, xlim, ylim) -> matplotlib.figure.Figure
    Render a cycle plot and return the Figure (caller decides what to do with it).

save_cycle_figure(fig, cycle, out_dir)
    Save *fig* to ``out_dir/cycle_NNNN.png`` and close it.

compute_axis_limits(cycle_points, cycle_start_map) -> (max_cycle_time, max_pressure)
    Scan all cycles and return sensible default axis limits.
"""

import os
import textwrap
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
#  Segment builder
# ---------------------------------------------------------------------------

def build_segments(
    cycle:           int,
    cycle_points:    dict,
    cycle_start_map: dict,
    phased_seq:      dict,
    cyc_seq_map:     dict,
    assign_phase_fn,
) -> dict:
    """
    Partition the raw ``(t_s, pressure)`` pairs for *cycle* into per-phase
    line segments, bridging adjacent segments at phase transitions so lines
    connect without gaps.

    Parameters
    ----------
    assign_phase_fn : callable(cycle_time_s, phase_bins, phase_names) -> str|None
        The ``assign_phase`` function from ``sequence_utils``.

    Returns
    -------
    segments : dict[str, tuple[list, list]]
        ``{phase_name: ([times], [pressures])}``
        Includes an ``"unassigned"`` entry for points outside all phase bins.
    """
    pts_sorted = sorted(cycle_points.get(cycle, []))
    if not pts_sorted:
        return {}

    t0 = cycle_start_map.get(cycle, pts_sorted[0][0])
    seq_key = cyc_seq_map.get(cycle)
    phase_bins = phased_seq[seq_key].get("phase_bins", []) if seq_key else []
    phase_names = phased_seq[seq_key].get("phase_names", []) if seq_key else []

    segments: dict = {}
    prev_label = None
    seg_t: list = []
    seg_p: list = []

    for t_s, pval in pts_sorted:
        ct = t_s - t0
        phase = assign_phase_fn(ct, phase_bins, phase_names)
        label = phase if phase else "unassigned"

        if label != prev_label:
            if prev_label is not None and seg_t:
                seg_t.append(ct)
                seg_p.append(pval)
                buf = segments.setdefault(prev_label, ([], []))
                buf[0].extend(seg_t)
                buf[1].extend(seg_p)
            seg_t, seg_p, prev_label = [ct], [pval], label
        else:
            seg_t.append(ct)
            seg_p.append(pval)

    if prev_label and seg_t:
        buf = segments.setdefault(prev_label, ([], []))
        buf[0].extend(seg_t)
        buf[1].extend(seg_p)

    return segments


# ---------------------------------------------------------------------------
#  Figure builder  (backend-agnostic — caller embeds or saves)
# ---------------------------------------------------------------------------

def draw_cycle_figure(
    cycle:           int,
    filename:        str,
    segments:        dict,
    phase_color_map: dict,
    all_phase_names: list,
    xlim:            float,
    ylim:            float,
    sequence_note:   str | None = None,
    figsize:         tuple = (10, 8),
) -> plt.Figure:
    """
    Build and return a ``matplotlib.figure.Figure`` for *cycle*.

    Uses ``plt.Figure()`` directly (not ``plt.subplots``) so the caller
    controls which backend canvas it is drawn on.
    """
    fig = plt.Figure(figsize=figsize)
    ax = fig.add_subplot(111)

    for pname in all_phase_names:
        if pname not in segments:
            continue
        ts, ps = segments[pname]
        ax.plot(ts, ps, linestyle="-", linewidth=1.4,
                color=phase_color_map.get(pname, "gray"), label=pname)

    if "unassigned" in segments:
        ts, ps = segments["unassigned"]
        ax.plot(ts, ps, linestyle="-", linewidth=0.8,
                color="#cccccc", label="unassigned")

    ax.set_xlabel("Time (s)", fontsize=11)
    ax.set_ylabel("Pressure (mTorr)", fontsize=11)
    ax.set_title(f"{filename} cycle {cycle}", fontsize=12)
    ax.set_xlim(0, xlim)
    ax.set_ylim(0, ylim)
    ax.grid(True, alpha=0.35, linewidth=0.6)

    handles, labels = ax.get_legend_handles_labels()
    if handles:
        ax.legend(handles, labels,
                  loc="center left", bbox_to_anchor=(1.0, 0.5),
                  fontsize=9, framealpha=0.9)

    if sequence_note:
        wrapped_note = textwrap.fill(sequence_note, width=52)
        ax.text(
            0.02,
            0.98,
            wrapped_note,
            transform=ax.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            bbox={
                "boxstyle": "round,pad=0.35",
                "facecolor": "white",
                "edgecolor": "#666666",
                "alpha": 0.93,
            },
        )

    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
#  Batch save helper
# ---------------------------------------------------------------------------

def save_cycle_figure(fig: plt.Figure, cycle: int, out_dir: str, dpi: int = 130):
    """Save *fig* as ``cycle_NNNN.png`` inside *out_dir* and close it."""
    out_path = os.path.join(out_dir, f"cycle_{cycle:04d}.png")
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
#  Axis-limit helper
# ---------------------------------------------------------------------------

def compute_axis_limits(
    cycle_points:    dict,
    cycle_start_map: dict,
) -> tuple[float, float]:
    """
    Scan all cycles and return ``(max_cycle_time_s, max_pressure_mTorr)``
    that can be used as default axis limits.

    Falls back to ``(600.0, 2500.0)`` if there is no data.
    """
    max_ct = 0.0
    max_p = 0.0

    for cyc, pts in cycle_points.items():
        t0 = cycle_start_map.get(cyc, 0.0)
        for t_s, pval in pts:
            ct = t_s - t0
            if ct > max_ct:
                max_ct = ct
            if pval > max_p:
                max_p = pval

    return (max_ct or 600.0), (max_p or 2500.0)


# ---------------------------------------------------------------------------
#  Exposure table  (pressure × time integral for dose+hold per cycle)
# ---------------------------------------------------------------------------

def compute_exposure_table(
    cycles_sorted:   list,
    cycle_points:    dict,
    cycle_start_map: dict,
    phased_seq:      dict,
    cyc_seq_map:     dict,
    assign_phase_fn,
    leakrate_phase_reduction: float = 0.0,
) -> list:
    """
    For every cycle, compute trapezoidal exposure over only the ``dose`` and
    ``hold`` phases, combined into one integration per sequence/valve label.

    If a sequence contains a valve named ``LeakRate``, the row also includes
    ``LeakRate_leak_rate`` computed as the least-squares slope dP/dt over all
    dose+hold points for that cycle after trimming the first and last
    ``leakrate_phase_reduction`` seconds from the exposure window.

    Returns a list of dicts, one row per sequence index (zero-based).
    Each row contains dynamic columns per valve label:
        <valve>_nominal_dose, <valve>_nominal_hold, <valve>_nominal_duration,
        <valve>_exposure, <valve>_mean_pressure, <valve>_leak_rate
    """
    if not cycles_sorted:
        return []

    cycle_zero = min(cycles_sorted)

    nominal_map: dict = {}
    for seq_key, seq_data in phased_seq.items():
        for key, timing in seq_data.items():
            if not str(key).startswith("valve"):
                continue
            vals = list(timing) if isinstance(timing, (list, tuple)) else []
            dose = float(vals[3]) if len(vals) > 3 else 0.0
            hold = float(vals[4]) if len(vals) > 4 else 0.0
            label = str(key)[len("valve"):]
            nominal_map[f"{seq_key}_{label}"] = {
                "nominal_dose": dose,
                "nominal_hold": hold,
                "nominal_duration": dose + hold,
            }

    phase_reduction = max(0.0, float(leakrate_phase_reduction or 0.0))

    def _least_squares_slope(times, pressures):
        n = len(times)
        if n < 2:
            return None
        mean_t = sum(times) / n
        mean_p = sum(pressures) / n
        ss_tt = sum((t - mean_t) ** 2 for t in times)
        if ss_tt <= 0:
            return None
        ss_tp = sum((times[i] - mean_t) * (pressures[i] - mean_p) for i in range(n))
        return ss_tp / ss_tt

    rows = []
    for cycle in cycles_sorted:
        segs = build_segments(
            cycle, cycle_points, cycle_start_map,
            phased_seq, cyc_seq_map, assign_phase_fn,
        )
        grouped: dict = {}

        for phase_name, (times, pressures) in segs.items():
            if phase_name == "unassigned":
                continue
            parts = str(phase_name).rsplit("_", 1)
            if len(parts) != 2:
                continue
            phase_head, phase_tail = parts
            if phase_tail not in {"dose", "hold"}:
                continue
            if len(times) < 2:
                continue
            exposure = sum(
                (pressures[j] + pressures[j - 1]) * 0.5 * (times[j] - times[j - 1])
                for j in range(1, len(times))
            )
            duration = times[-1] - times[0]
            if duration <= 0:
                continue
            bucket = grouped.setdefault(
                phase_head,
                {"exposure": 0.0, "duration": 0.0},
            )
            bucket["exposure"] += exposure
            bucket["duration"] += duration

        row = {"sequence": int(cycle - cycle_zero)}
        has_nonzero_exposure = False

        for phase_head, vals in sorted(grouped.items()):
            total_exposure = vals["exposure"]
            total_duration = vals["duration"]
            if total_duration <= 0:
                continue
            mean_p = total_exposure / total_duration
            if total_exposure == 0:
                continue
            nominal = nominal_map.get(
                phase_head,
                {"nominal_dose": 0.0, "nominal_hold": 0.0, "nominal_duration": 0.0},
            )
            valve_label = phase_head.split("_", 1)[1] if "_" in phase_head else phase_head
            col = valve_label.replace(" ", "_")

            row[f"{col}_nominal_dose"] = round(nominal["nominal_dose"], 6)
            row[f"{col}_nominal_hold"] = round(nominal["nominal_hold"], 6)
            row[f"{col}_nominal_duration"] = round(nominal["nominal_duration"], 6)
            row[f"{col}_exposure"] = round(total_exposure, 4)
            row[f"{col}_mean_pressure"] = round(mean_p, 4)

            if valve_label == "LeakRate":
                exposure_points = []
                for tail in ("dose", "hold"):
                    seg = segs.get(f"{phase_head}_{tail}")
                    if not seg:
                        continue
                    times_part, pressures_part = seg
                    exposure_points.extend(zip(times_part, pressures_part))

                if len(exposure_points) >= 2:
                    exposure_points.sort(key=lambda tp: tp[0])
                    t_start = exposure_points[0][0] + phase_reduction
                    t_end = exposure_points[-1][0] - phase_reduction
                    trimmed = [tp for tp in exposure_points if t_start <= tp[0] <= t_end]

                    if len(trimmed) >= 2:
                        times = [t for t, _ in trimmed]
                        pressures = [p for _, p in trimmed]
                        leak_slope = _least_squares_slope(times, pressures)
                        if leak_slope is not None:
                            row[f"{col}_leak_rate"] = round(leak_slope, 6)

            has_nonzero_exposure = True

        if has_nonzero_exposure:
            rows.append(row)

    rows.sort(key=lambda r: r["sequence"])
    return rows


def save_exposure_csv(rows: list, out_dir: str, stem: str) -> str:
    """
    Write *rows* to ``<out_dir>/<stem>_exposure.csv`` and return the path.
    """
    import csv

    out_path = os.path.join(out_dir, f"{stem}_exposure.csv")

    valve_prefixes = set()
    suffixes = [
        "_nominal_dose",
        "_nominal_hold",
        "_nominal_duration",
        "_exposure",
        "_mean_pressure",
        "_leak_rate",
    ]
    for row in rows:
        for key in row.keys():
            if key == "sequence":
                continue
            for suffix in suffixes:
                if key.endswith(suffix):
                    valve_prefixes.add(key[: -len(suffix)])
                    break

    fieldnames = ["sequence"]
    for prefix in sorted(valve_prefixes):
        fieldnames.extend([
            f"{prefix}_nominal_dose",
            f"{prefix}_nominal_hold",
            f"{prefix}_nominal_duration",
            f"{prefix}_exposure",
            f"{prefix}_mean_pressure",
            f"{prefix}_leak_rate",
        ])

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return out_path


# ---------------------------------------------------------------------------
#  Animation builder
# ---------------------------------------------------------------------------

def build_animation(
    cycles_sorted:   list,
    cycle_points:    dict,
    cycle_start_map: dict,
    phased_seq:      dict,
    cyc_seq_map:     dict,
    all_phase_names: list,
    phase_color_map: dict,
    assign_phase_fn,
    xlim_val:        float,
    ylim_val:        float,
    filename:        str,
    out_dir:         str,
    sequence_note_fn = None,
    fps:             int   = 5,
    dpi:             int   = 100,
    progress_cb             = None,
) -> str:
    """
    Stitch the already-saved cycle PNGs into an animated GIF.

    Requires Pillow (``pip install Pillow``).  This reuses the exported cycle
    plots directly, so the GIF matches the saved images exactly.

    Returns the output file path.
    """
    from PIL import Image

    frames = []
    n_frames = len(cycles_sorted)
    for i, cycle in enumerate(cycles_sorted):
        frame_path = os.path.join(out_dir, f"cycle_{cycle:04d}.png")
        if not os.path.isfile(frame_path):
            raise FileNotFoundError(f"Missing cycle plot image: {frame_path}")

        with Image.open(frame_path) as img:
            frames.append(img.convert("P", palette=Image.ADAPTIVE).copy())

        if progress_cb:
            progress_cb(i + 1, n_frames)

    out_path = os.path.join(out_dir, f"{filename}_animation.gif")
    if frames:
        frames[0].save(
            out_path,
            save_all=True,
            append_images=frames[1:],
            optimize=False,
            duration=int(1000 / fps),
            loop=0,
        )
    return out_path
