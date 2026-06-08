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
    pts_sorted  = sorted(cycle_points.get(cycle, []))
    if not pts_sorted:
        return {}

    t0          = cycle_start_map.get(cycle, pts_sorted[0][0])
    seq_key     = cyc_seq_map.get(cycle)
    phase_bins  = phased_seq[seq_key].get("phase_bins",  []) if seq_key else []
    phase_names = phased_seq[seq_key].get("phase_names", []) if seq_key else []

    segments: dict  = {}
    prev_label      = None
    seg_t: list     = []
    seg_p: list     = []

    for t_s, pval in pts_sorted:
        ct    = t_s - t0
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
    figsize:         tuple = (10, 8),
) -> plt.Figure:
    """
    Build and return a ``matplotlib.figure.Figure`` for *cycle*.

    Uses ``plt.Figure()`` directly (not ``plt.subplots``) so the caller
    controls which backend canvas it is drawn on.
    """
    fig = plt.Figure(figsize=figsize)
    ax  = fig.add_subplot(111)

    # Phases in canonical order so the legend is always consistent
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

    ax.set_xlabel("Time (s)",          fontsize=11)
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
    max_p  = 0.0

    for cyc, pts in cycle_points.items():
        t0 = cycle_start_map.get(cyc, 0.0)
        for t_s, pval in pts:
            ct = t_s - t0
            if ct  > max_ct: max_ct = ct
            if pval > max_p:  max_p  = pval

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
) -> list:
    """
    For every cycle, compute trapezoidal exposure over only the ``dose`` and
    ``hold`` phases, combined into one integration per sequence/valve label.

    Returns a list of dicts with keys:
        cycle, phase, exposure_mTorr_s, duration_s, mean_pressure_mTorr
    """
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

        for phase_head, vals in grouped.items():
            total_exposure = vals["exposure"]
            total_duration = vals["duration"]
            if total_duration <= 0:
                continue
            mean_p = total_exposure / total_duration
            rows.append({
                "cycle":               cycle,
                "phase":               f"{phase_head}_dose_hold",
                "exposure_mTorr_s":    round(total_exposure, 4),
                "duration_s":          round(total_duration, 4),
                "mean_pressure_mTorr": round(mean_p, 4),
            })
    return rows


def save_exposure_csv(rows: list, out_dir: str, stem: str) -> str:
    """
    Write *rows* to ``<out_dir>/<stem>_exposure.csv`` and return the path.
    """
    import csv
    out_path = os.path.join(out_dir, f"{stem}_exposure.csv")
    fieldnames = [
        "cycle", "phase",
        "exposure_mTorr_s", "duration_s", "mean_pressure_mTorr",
    ]
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
    fps:             int   = 5,
    dpi:             int   = 100,
    progress_cb             = None,
) -> str:
    """
    Render each cycle as a PNG frame and stitch into an animated GIF.

    Requires Pillow (``pip install Pillow``).  Each frame is rendered with
    ``matplotlib.figure.Figure`` + ``FigureCanvasAgg`` so no pyplot state is
    touched (safe to call from a background thread).

    Returns the output file path.
    """
    from PIL import Image
    import io
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    frames   = []
    n_frames = len(cycles_sorted)
    last     = cycles_sorted[-1] if cycles_sorted else 1

    for i, cycle in enumerate(cycles_sorted):
        segs = build_segments(
            cycle, cycle_points, cycle_start_map,
            phased_seq, cyc_seq_map, assign_phase_fn,
        )

        fig = Figure(figsize=(12, 7))
        FigureCanvasAgg(fig)                             # attach Agg renderer
        fig.subplots_adjust(right=0.76, left=0.09, bottom=0.10, top=0.92)
        ax = fig.add_subplot(111)

        for pname in all_phase_names:
            if pname not in segs:
                continue
            ts, ps = segs[pname]
            ax.plot(ts, ps, linestyle="-", linewidth=1.4,
                    color=phase_color_map.get(pname, "gray"), label=pname)

        if "unassigned" in segs:
            ts, ps = segs["unassigned"]
            ax.plot(ts, ps, linestyle="-", linewidth=0.8,
                    color="#cccccc", label="unassigned")

        ax.set_xlabel("Time (s)",           fontsize=11)
        ax.set_ylabel("Pressure (mTorr)",   fontsize=11)
        ax.set_title(f"{filename}  —  Cycle {cycle} / {last}", fontsize=12)
        ax.set_xlim(0, xlim_val)
        ax.set_ylim(0, ylim_val)
        ax.grid(True, alpha=0.35, linewidth=0.6)

        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(handles, labels,
                      loc="center left", bbox_to_anchor=(1.0, 0.5),
                      fontsize=9, framealpha=0.9)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi)
        buf.seek(0)
        frames.append(Image.open(buf).copy())
        buf.close()

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
