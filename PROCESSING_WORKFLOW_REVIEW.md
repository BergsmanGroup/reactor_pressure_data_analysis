# Processing Workflow Review & Proposal: Temperature Efficiency, General Efficiency, and Detailed iSE / Cycle Summary Data

This document answers the four review questions, proposes a concrete refactor, and assesses feasibility. **No code files were changed as part of this review** — this is a planning document only.

---

## 1. Making temperature attachment more efficient

**Finding: the real cost is a bug, not the meta-field write.** In [`data_parser.py`](data_parser.py), `_temperature_at()` and `_service_config_at()` each do:

```python
def _temperature_at(samples, timestamp):
    ...
    times = [sample[0] for sample in samples]   # <-- rebuilt from scratch every call
    index = bisect_left(times, timestamp)
    ...
```

These helpers are called **once per data row** inside `condense_log()`'s loop. With ~35,000 temperature samples and ~44,000 pressure rows (the `DID000141` sample set), that's ~44,000 full list rebuilds of a 35,000-element list — roughly 1.5 billion element-copies just to prepare for a `bisect_left` call that itself is O(log n). This is an accidental **O(rows × samples)** algorithm hiding behind an O(log n) bisect call, and it is almost certainly the dominant cost of Step 3 today — far more expensive than writing a small `TemperatureZones`/`meta` dict into each row (which is just a handful of dict/JSON operations).

**Proposed fix (cheap, no behavior change):**
- Precompute the `times` list **once** before the row loop in `condense_log()` (or inside `load_temperature_data()`/`load_service_config_data()` by returning a `(times, samples)` tuple, or wrapping it in a small `TemperatureIndex` helper class that stores `times` as a prebuilt list/array). Pass that precomputed list into `_temperature_at`/`_service_config_at` instead of rebuilding it per call.
- This alone should turn Step 3 from O(rows × samples) into O(rows × log(samples)), which for realistic file sizes should be a 100x–1000x speedup (seconds instead of minutes).
- This is a pure internal refactor of `data_parser.py`, fully backward compatible, and low risk.

**Secondary optimization — effective sample rate control (your idea):** Once the above bug is fixed, downsampling mainly helps:
- `load_temperature_data()` / `load_service_config_data()` parse time (fewer JSONL lines to read/parse), and
- memory footprint of the in-memory sample list.

It has only a marginal effect on the per-row bisect cost (already O(log n)), but it's still worth adding because telemetry is logged at ~2 Hz while zone setpoints/temperatures change on the order of minutes, so most samples are redundant. Proposed implementation:
- Add a helper `detect_sample_interval_s(samples) -> float` (median of consecutive timestamp deltas) to `data_parser.py`.
- Add a `ProcessingOptions.temperature_sample_interval_s: float | None` field. `None`/`0` means "use all samples" (current behavior, safe default). When set, `load_temperature_data()`/`load_service_config_data()` (or a thin wrapper in `pipeline.py`) keep only the first sample within each bucket of that interval before building the bisect index.
- GUI: show the auto-detected interval as a read-only label next to an editable "Effective sample interval (s)" field in the Temperature Data panel, defaulting to the detected value (or blank = no downsampling) so existing behavior is unchanged unless the user opts in.

**Feasibility:** High. The bug fix is a small, isolated change in `data_parser.py` with no schema/format impact — safe to do immediately. The downsampling option is additive (new optional field, defaults preserve current behavior).

---

## 2. Other workflow efficiency opportunities

Reviewed the rest of the staged pipeline (`pipeline.py`, `data_parser.py`, `plot_utils.py`). Beyond the temperature bug above:

1. **Progress-callback flood.** `progress_cb` is invoked very frequently (every ~4 MB of input, or every row inside tight loops in some paths) and each GUI-side call marshals to the Tk main thread via `self.after(0, ...)`. For very large files this can queue a large number of Tk callbacks and add UI-thread overhead. Low-risk fix: throttle `_set_progress` in `gui.py` to skip updates that are within ~0.5% of the last reported value, or rate-limit to ~10 updates/sec.
2. **`label_phases()` / `attach_temperature()` full-file rewrites.** Each staged pass that bakes data into the working file rewrites *every* line (even unaffected ones), because NDJSON lines are variable-length and can't be patched in place. This is inherent to the chosen format and already about as cheap as it can be per pass (one sequential read + one sequential write, no per-row recomputation beyond what's needed) — not worth changing unless file sizes grow by another order of magnitude. If they do, the CycleSummary design in Section 4 (append-only) is the right escape hatch, since appending new rows is far cheaper than rewriting existing ones.
3. **Redundant phase-structure recomputation.** `preview_cycle()` intentionally recomputes `phased_seq`/`cyc_seq_map` fresh every call (so shift/valve-name edits preview instantly); this is correct and cheap (pure Python, no I/O) and should stay as-is.
4. **`stream_pressure()` re-parses JSON per line twice** (`json.loads` + `_parse_payload` which may itself call `json.loads` again if payload arrives JSON-encoded as a string). This is minor compared to the temperature bug but could be worth profiling after the Section 1 fix lands, to see if it's still significant.

**Recommended priority:** fix the temperature bisect bug first (biggest, clearest win), then progress-callback throttling (cheap, improves perceived responsiveness), and treat the rest as "revisit if profiling shows it matters."

---

## 3. Where to put "detailed iSE" (thickness) data today

Your instinct against overloading `meta` is correct. Looking at the current condensed-row shape:

```json
{"type": "data", "meta": {"temperature": {...}}, "payload": "{...pressure fields...}"}
```

`meta` currently holds **connection/service metadata** (COM port, TCP host, zone names) — essentially "how the data was collected," not measurement data. Thickness is a **measurement**, like pressure or temperature, and it:
- doesn't arrive at pressure-sample frequency (it's sparse — a few measurements per cycle, sometimes at half-cycle granularity, per the example `Example experiment\261025(1) iSE data.xlsx`: columns `Cycle, Time (min.), Thickness`, with rows at `Cycle = 0, 0.5, 1, 1.5, 2, ...`),
- is naturally keyed by **cycle** (fractional cycle number), not by elapsed time within a single pressure row.

Forcing it onto individual `data` rows (even via `meta`) would mean picking one arbitrary pressure row per cycle to "own" each thickness value, which is awkward and fragile. This observation is what leads directly to Section 4: thickness data is a strong motivating example for a **new, cycle-scoped row type**, rather than another field squeezed into the per-sample `data` row.

---

## 4. Proposed `CycleSummary` row type

### 4.1 Schema (proposed)

One `CycleSummary` record appended **after all `data` rows for that cycle** (or simply appended at the very end of the file in cycle order — see 4.3 on performance):

```json
{
  "type": "cycle_summary",
  "payload": {
    "Cycle": 3,
    "Sequence": "seq2",
    "SequenceNote": "Saturation curve, step 2",
    "StartTime": 1234.5,
    "EndTime": 1594.5,
    "Precursors": {
      "TDIC": {
        "NominalDose": 300.0, "NominalHold": 60.0, "NominalDuration": 360.0,
        "Exposure": 91586.4, "MeanPressure": 254.4,
        "LeakRate": { "NominalDose": 0.0, "NominalHold": 60.0, "Exposure": 2561.8,
                      "MeanPressure": 42.7, "LeakRateMTorrPerMin": -225.1 }
      },
      "DAMDPA": { "...": "..." }
    },
    "Temperature": {
      "1": {"Name": "TDIC", "SetPointC": 30.0, "MeanC": 30.03, "StdDevC": 0.05 },
      "2": {"Name": "DAMDPA","SetPointC": 30.0, "MeanC": 29.99, "StdDevC": 0.04 }
    },
    "Thickness": {
      "Cycle": [3.0, 3.5],
      "ThicknessNm": [91.2, 94.4]
    }
  }
}
```

This mirrors the existing `header`/`footer`/`data` envelope convention (`{"type": ..., "payload": ...}`), so existing parsers that already switch on `type` only need one more `elif` branch, and nothing about the `data` row schema changes — directly satisfying your goal of avoiding further churn to the `data` row shape.

### 4.2 Where each field comes from (and when it's computable)

| Field | Source | Available after stage |
|---|---|---|
| `StartTime`/`EndTime`, `Sequence`, `SequenceNote` | `cycle_start_map`, `cyc_seq_map`, header sequence notes | Stage 2 (label phases) |
| `Precursors.*` (dose/hold/exposure/mean pressure/leak rate) | `plot_utils.compute_exposure_table()` + `compute_leakrate_regressions()` — **already computed today**, just per-cycle rows in the exposure CSV instead of embedded here | Stage 6 (generate outputs), since it needs the fully parsed per-cycle pressure series |
| `Temperature.*` (name, set point, mean, stdev) | New aggregation over the `TemperatureZones` already baked into `data` rows during Stage 3 | After Stage 3, but only if Stage 3 ran (optional, same as today) |
| `Thickness.*` | New "Stage 4" iSE loader (Section 4.4) | Stage 4 (whenever the user supplies an iSE file) |

**Key implication:** `CycleSummary` can only be fully assembled once exposure/leak-rate math has run — i.e., at Stage 6 time, not interleaved mid-stream during Stage 1/2/3. So in practice it's not "a row written as each cycle is condensed" but "a batch of rows computed once per-cycle data and exposure numbers are known, then appended."

### 4.3 Writing strategy: append-only, not interleaved

Interleaving `cycle_summary` rows between each cycle's `data` rows (true streaming order) would require buffering an entire cycle's rows before deciding whether a cycle boundary has passed, and would force a full file rewrite to insert the summary in the exact position — costly and fragile for marginal benefit.

**Proposal:** append `cycle_summary` rows **after the footer line's position (or before it, if a footer line must remain last)** at the end of Stage 6, in ascending cycle order, in a single `open(path, "a")` append — no need to rewrite existing `data` rows at all. Downstream consumers that care about the per-cycle rollups can simply filter `type == "cycle_summary"`; consumers that only care about raw samples are unaffected (they already skip unknown `type` values, per `condense_log()`'s existing `continue`-on-unknown-type behavior... though this should be double-checked/hardened — see 4.5 risks). This keeps the cost of adding `CycleSummary` at **O(number of cycles)**, independent of file size — cheap even for very large files.

### 4.4 New "Stage 4" iSE loader

Add `ise_utils.parse_ise_cycle_thickness(path) -> dict[float, list[float]]` (or `list[tuple[cycle, thickness]]`) that reads the `Cycle, Time (min.), Thickness` columns (xlsx via `openpyxl`/pandas, or CSV) and groups rows by `floor(cycle)` so cycle `3` collects every thickness row with `3 <= Cycle < 4` (e.g. `3` and `3.5`), matching your `Cycle [1, 1.5], thickness [6.20, 9.38]` example. This is additive — it does not touch the existing simple `parse_ise_thickness()`/`save_ise_thickness_csv()` used by the current thickness CSV export, which can remain for users who don't need cycle alignment.

### 4.5 Feasibility & risks

- **Feasible, moderate effort.** No changes to the `data` row schema; one new `type` value, one new `pipeline.py` method (`write_cycle_summaries()`, called at the end of `generate_outputs()`/`run_all()`, gated behind `write_condensed_json` same as today's other bake-in steps), one new small `ise_utils` function, and a new "Stage 4" UI section (file picker, same pattern as the current iSE panel) that's wired into `generate_outputs()` instead of being a no-op placeholder.
- **Must verify `condense_log()`'s re-entrant passes tolerate an unknown row type.** Currently `condense_log()` only special-cases `header`/`footer`/`step`/`pressure`/`data`; everything else is silently dropped (`continue`d). If `cycle_summary` rows are appended *before* a later Stage 2/3 pass re-runs `condense_log()` on the same working file, those summary rows would currently be **silently deleted** by the next pass. Two options: (a) always write `cycle_summary` rows **last**, after Stages 1–3 are finalized (natural, since the data depends on Stage 6 anyway, and matches "append once, don't touch again"), or (b) teach `condense_log()` to pass `cycle_summary` rows through unchanged. Recommend (a) as the primary safeguard and (b) as a defensive follow-up.
- **Footer placement.** Need to decide whether `cycle_summary` rows go before or after the existing `footer` line; before is likely safer for any strict "footer is last line" assumption elsewhere in the codebase (not currently verified) — this should be checked during implementation.
- **Temperature aggregation granularity.** Mean/stdev per zone per cycle is a new computation (simple, just needs a pass over the cycle's `TemperatureZones` already present in the condensed rows) — cheap, no new data source needed.
- **Half-cycle keys.** `Cycle` values like `3.5` don't map to an existing integer pressure cycle; confirm with domain knowledge whether a half-cycle thickness reading should attach to the *preceding* integer cycle's summary (as proposed) or be split across both neighbors — this is a product decision, not a technical blocker.

---

## Suggested implementation order

1. Fix the `_temperature_at`/`_service_config_at` O(n²) bug (Section 1) — quick, high-value, no schema impact.
2. Add the optional temperature sample-interval control (Section 1) — small, additive.
3. Add the `ise_utils.parse_ise_cycle_thickness()` loader and wire a real Stage 4 UI section (Section 4.4).
4. Add `CycleSummary` generation as an append-only step at the end of `generate_outputs()`/`run_all()` (Section 4.3), including the temperature-aggregation and precursor/leak-rate fields already computed by `compute_exposure_table()`/`compute_leakrate_regressions()`.
5. Harden `condense_log()` to pass through unknown row types (defensive, Section 4.5) so future row types are safe by default even if write order assumptions change later.
