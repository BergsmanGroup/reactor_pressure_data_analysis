"""
gui.py
------
Tkinter GUI for the Reactor Pressure Analyzer.

Imports the three pure-logic modules and wires them to the UI:
    sequence_utils  -- valve sequence / phase-bin helpers
    data_parser     -- streaming NDJSON file reader
    plot_utils      -- figure building and saving
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
import threading
import os
import re
import json
import subprocess
import hashlib
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from sequence_utils import (
    convert_sequence,
    apply_valve_names,
    compute_phase_bins,
    make_cycle_seq_map,
    assign_phase,
    build_phase_color_map,
)
from data_parser import (
    read_header, stream_pressure, subtract_baseline,
    condense_log, condensed_path, is_condensed_file,
)
from plot_utils  import (
    build_segments,
    draw_cycle_figure,
    save_cycle_figure,
    compute_axis_limits,
    compute_exposure_table,
    save_exposure_csv,
    build_animation,
)
from convert_to_json import load_table, build_payload, convert_recipe_sheet


class SaveAbortedError(Exception):
    """Raised when the user cancels a retryable save operation."""


class ReactorApp(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("Reactor Pressure Data Analyzer")
        self.geometry("980x760")
        self.resizable(True, True)
        self.minsize(760, 560)

        # -- tk variables ------------------------------------------------------
        self._file_path         = tk.StringVar()
        self._output_dir        = tk.StringVar()
        self._xlim_var          = tk.StringVar(value="auto")
        self._ylim_var          = tk.StringVar(value="auto")
        self._shift_var         = tk.StringVar(value="0")
        self._wait_var          = tk.StringVar(value="0")
        self._fps_var           = tk.StringVar(value="5")
        self._preview_cycle_var = tk.StringVar(value="1")
        self._recipe_sheet_path = tk.StringVar()
        self._recipe_output_path = tk.StringVar()
        self._recipe_status_var = tk.StringVar(value="Load a recipe sheet to preview the payload.")

        # -- state -------------------------------------------------------------
        self._header_info:     dict = {}
        self._seq_dict:        dict = {}
        self._valve_name_vars: dict = {}   # {valve_num_int: tk.StringVar}
        self._cached:          dict = {}   # populated after a processing run
        self._recipe_payload:  dict = {}
        self._settings_path = Path(__file__).with_name("gui_processing_state.json")
        self._settings_state: dict = {
            "last_processing_settings": {},
            "valve_names_by_header": {},
            "valve_names_by_set": {},
            "last_valve_names": {},
        }

        self._load_settings_state()
        self._apply_last_processing_settings()

        self._build_ui()

    # =========================================================================
    #  UI construction
    # =========================================================================

    def _build_ui(self):
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=10, pady=10)

        plot_tab = ttk.Frame(self._notebook)
        recipe_tab = ttk.Frame(self._notebook)
        self._notebook.add(plot_tab, text="Reactor Plots")
        self._notebook.add(recipe_tab, text="Convert Recipe Sheet")

        self._build_plot_tab(plot_tab)
        self._build_recipe_tab(recipe_tab)

    def _build_plot_tab(self, parent):
        pad = {"padx": 10, "pady": 4}

        # -- File selection ----------------------------------------------------
        file_frame = ttk.LabelFrame(parent, text="Raw Data File", padding=8)
        file_frame.pack(fill="x", **pad)
        ttk.Entry(file_frame, textvariable=self._file_path, width=54).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(file_frame, text="Browse...",    command=self._browse_file  ).pack(side="left", padx=(0, 4))
        ttk.Button(file_frame, text="Load Header",  command=self._load_header  ).pack(side="left", padx=(0, 4))
        ttk.Button(file_frame, text="Open File Location",
                   command=self._open_raw_file_location).pack(side="left")

        # -- Valve names (populated after header load) -------------------------
        self._valve_frame = ttk.LabelFrame(parent, text="Valve Names (from recipe)", padding=8)
        self._valve_frame.pack(fill="x", **pad)
        self._valve_placeholder = ttk.Label(
            self._valve_frame, text="Load a data file above to populate valve names.")
        self._valve_placeholder.pack()

        # -- Output directory + plot options -----------------------------------
        opt_outer = ttk.Frame(parent)
        opt_outer.pack(fill="x", **pad)

        out_frame = ttk.LabelFrame(opt_outer, text="Output Directory", padding=8)
        out_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Entry(out_frame, textvariable=self._output_dir, width=40).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(out_frame, text="Browse...", command=self._browse_output).pack(side="left")

        plot_frame = ttk.LabelFrame(opt_outer, text="Plot Options", padding=8)
        plot_frame.pack(side="left")
        _opts = [
            ("X max (s):",       0, 0, self._xlim_var),
            ("Y max (mTorr):",   0, 2, self._ylim_var),
            ("Phase shift (s):", 1, 0, self._shift_var),
            ("Wait time (s):",   2, 0, self._wait_var),
            ("Anim FPS:",        3, 0, self._fps_var),
        ]
        for label_text, row, col, var in _opts:
            ttk.Label(plot_frame, text=label_text).grid(
                row=row, column=col, sticky="w", padx=3, pady=(3, 0))
            ttk.Entry(plot_frame, textvariable=var, width=8).grid(
                row=row, column=col + 1, padx=3, pady=(3, 0))

        # -- Process button + progress bar -------------------------------------
        ctrl = ttk.Frame(parent)
        ctrl.pack(fill="x", padx=10, pady=6)
        self._process_btn = ttk.Button(
            ctrl, text="Process & Generate Plots",
            command=self._start_processing, state="disabled")
        self._process_btn.pack(side="left", padx=(0, 8))
        self._progress = ttk.Progressbar(
            ctrl, orient="horizontal", mode="determinate", length=1)
        self._progress.pack(side="left", expand=True, fill="x")
        self._pct_lbl = ttk.Label(ctrl, text="  0%", width=5)
        self._pct_lbl.pack(side="left")

        # -- Animation button -------------------------------------------------
        anim_row = ttk.Frame(parent)
        anim_row.pack(fill="x", padx=10, pady=(0, 4))
        self._anim_btn = ttk.Button(
            anim_row, text="Generate Animation",
            command=self._start_animation, state="disabled")
        self._anim_btn.pack(side="left")

        # -- Preview controls -------------------------------------------------
        prev_row = ttk.Frame(parent)
        prev_row.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(prev_row, text="Preview cycle:").pack(side="left", padx=(0, 4))
        ttk.Entry(prev_row, textvariable=self._preview_cycle_var,
                  width=6).pack(side="left", padx=(0, 8))
        self._preview_btn = ttk.Button(
            prev_row, text="Preview Plot",
            command=self._preview_plot, state="disabled")
        self._preview_btn.pack(side="left")

        # -- Log ---------------------------------------------------------------
        log_frame = ttk.LabelFrame(parent, text="Log", padding=6)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        log_toolbar = ttk.Frame(log_frame)
        log_toolbar.pack(fill="x", anchor="e")
        ttk.Button(log_toolbar, text="Clear Log",
                   command=self._clear_log).pack(side="right")
        self._log_box = scrolledtext.ScrolledText(
            log_frame, height=10, state="disabled",
            font=("Consolas", 9), wrap="word")
        self._log_box.pack(fill="both", expand=True)

    def _build_recipe_tab(self, parent):
        pad = {"padx": 10, "pady": 4}

        file_frame = ttk.LabelFrame(parent, text="Recipe Sheet", padding=8)
        file_frame.pack(fill="x", **pad)
        ttk.Entry(file_frame, textvariable=self._recipe_sheet_path, width=64).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(file_frame, text="Browse...",
                   command=self._browse_recipe_sheet).pack(side="left", padx=(0, 4))
        ttk.Button(file_frame, text="Create JSON Payload",
                   command=self._create_recipe_payload).pack(side="left", padx=(0, 4))
        ttk.Button(file_frame, text="Open File Location",
                   command=self._open_recipe_file_location).pack(side="left")

        status_frame = ttk.Frame(parent)
        status_frame.pack(fill="x", **pad)
        ttk.Label(status_frame, textvariable=self._recipe_status_var,
                  anchor="w").pack(fill="x")

        review_frame = ttk.LabelFrame(parent, text="Processed Payload Preview", padding=8)
        review_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._recipe_preview_box = scrolledtext.ScrolledText(
            review_frame,
            height=16,
            state="disabled",
            font=("Consolas", 9),
            wrap="word",
        )
        self._recipe_preview_box.pack(fill="both", expand=True)

    # =========================================================================
    #  Utility helpers
    # =========================================================================

    def _log(self, msg: str):
        """Append *msg* to the log box (thread-safe)."""
        def _do():
            self._log_box.config(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.config(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self._log_box.config(state="normal")
        self._log_box.delete("1.0", "end")
        self._log_box.config(state="disabled")

    def _set_progress(self, pct: float):
        self.after(0, lambda: (
            self._progress.configure(value=pct),
            self._pct_lbl.configure(text=f"{pct:3.0f}%"),
        ))

    def _get_float(self, var: tk.StringVar, default=None):
        try:
            return float(var.get())
        except ValueError:
            return default

    def _set_text_widget(self, widget, text: str):
        widget.config(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.config(state="disabled")

    def _prompt_retry_save(self, file_path: str, label: str) -> bool:
        """Show a GUI retry/cancel prompt for a locked output file."""
        result = {"retry": False}
        done = threading.Event()

        def _show():
            result["retry"] = messagebox.askretrycancel(
                "File In Use",
                f"Could not save the {label} because it appears to be open:\n\n"
                f"{file_path}\n\n"
                "Close the file, then click Retry to try saving again.",
                parent=self,
            )
            done.set()

        self.after(0, _show)
        done.wait()
        return result["retry"]

    def _run_save_with_retry(self, save_fn, file_path: str, label: str):
        """Run *save_fn* until it succeeds or the user cancels retry."""
        while True:
            try:
                return save_fn()
            except PermissionError:
                self._log(f"Permission denied while saving {label}: {file_path}")
            except OSError as exc:
                if getattr(exc, "errno", None) != 13:
                    raise
                self._log(f"Permission denied while saving {label}: {file_path}")

            if not self._prompt_retry_save(file_path, label):
                raise SaveAbortedError(f"User cancelled save for {file_path}")

    def _open_path_in_explorer(self, value: str, label: str):
        path_text = value.strip()
        if not path_text:
            messagebox.showerror("Open File Location", f"No {label} selected.", parent=self)
            return

        path = Path(path_text)
        if not path.exists():
            messagebox.showerror(
                "Open File Location",
                f"The selected {label} does not exist:\n\n{path}",
                parent=self,
            )
            return

        try:
            resolved = path.resolve()
            if resolved.is_file() and os.name == "nt":
                subprocess.Popen(["explorer", "/select,", str(resolved)])
            elif hasattr(os, "startfile"):
                os.startfile(str(resolved if resolved.is_dir() else resolved.parent))
            else:
                subprocess.Popen(["explorer", str(resolved if resolved.is_dir() else resolved.parent)])
        except Exception as exc:
            messagebox.showerror(
                "Open File Location",
                f"Could not open the file location:\n\n{exc}",
                parent=self,
            )

    def _format_recipe_preview(self, csv_path: str, out_path: str, payload: dict) -> str:
        details_value = payload.get("experimentalDetails", "")
        if isinstance(details_value, str):
            try:
                parsed = json.loads(details_value)
            except (TypeError, ValueError):
                details_json = details_value
            else:
                details_json = json.dumps(parsed, indent=2)
        else:
            details_json = json.dumps(details_value, indent=2)
        recipe_rows = payload.get("recipe", [])
        data_row_count = len(recipe_rows)
        return (
            f"Recipe sheet:\n{csv_path}\n\n"
            f"Output JSON:\n{out_path}\n\n"
            f"username:\n{payload.get('username', '')}\n\n"
            f"experimentalDetails:\n{details_json}\n\n"
            f"Timing rows captured: {data_row_count}"
        )

    def _load_settings_state(self):
        if not self._settings_path.exists():
            return
        try:
            with self._settings_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return

        if not isinstance(data, dict):
            return

        last = data.get("last_processing_settings", {})
        by_header = data.get("valve_names_by_header", {})
        by_set = data.get("valve_names_by_set", {})
        last_valves = data.get("last_valve_names", {})

        if isinstance(by_header, dict) and not isinstance(last_valves, dict):
            last_valves = {}
        if isinstance(by_header, dict) and not last_valves and by_header:
            # Backward-compatibility: recover a fallback mapping from older state
            # files that only persisted valve names by header hash.
            try:
                candidate = next(reversed(by_header.values()))
                if isinstance(candidate, dict):
                    last_valves = candidate
            except Exception:
                pass

        self._settings_state = {
            "last_processing_settings": last if isinstance(last, dict) else {},
            "valve_names_by_header": by_header if isinstance(by_header, dict) else {},
            "valve_names_by_set": by_set if isinstance(by_set, dict) else {},
            "last_valve_names": last_valves if isinstance(last_valves, dict) else {},
        }

    def _save_settings_state(self):
        try:
            with self._settings_path.open("w", encoding="utf-8") as fh:
                json.dump(self._settings_state, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            self._log(f"WARNING: could not save GUI settings: {exc}")

    def _apply_last_processing_settings(self):
        last = self._settings_state.get("last_processing_settings", {})
        if not isinstance(last, dict):
            return

        xlim = last.get("xlim")
        ylim = last.get("ylim")
        shift = last.get("shift")
        wait_time = last.get("wait_time")
        fps = last.get("fps")
        if xlim is not None:
            self._xlim_var.set(str(xlim))
        if ylim is not None:
            self._ylim_var.set(str(ylim))
        if shift is not None:
            self._shift_var.set(str(shift))
        if wait_time is not None:
            self._wait_var.set(str(wait_time))
        if fps is not None:
            self._fps_var.set(str(fps))

    def _header_settings_key(self) -> str:
        if not self._seq_dict:
            return ""
        canonical = json.dumps(self._seq_dict, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(canonical.encode("utf-8")).hexdigest()

    def _valve_set_key(self) -> str:
        valves = sorted(int(v) for v in self._valve_name_vars.keys())
        return "|".join(str(v) for v in valves)

    def _apply_saved_valve_names(self):
        key = self._header_settings_key()
        by_header = self._settings_state.get("valve_names_by_header", {})
        by_set = self._settings_state.get("valve_names_by_set", {})
        last_valves = self._settings_state.get("last_valve_names", {})

        saved = {}
        if key:
            saved = by_header.get(key, {})
        if not saved:
            saved = by_set.get(self._valve_set_key(), {})
        if not saved:
            saved = last_valves
        if not isinstance(saved, dict):
            return

        for vnum, var in self._valve_name_vars.items():
            val = saved.get(str(vnum))
            if val is not None:
                var.set(str(val))

    def _persist_processing_preferences(self, valve_names: dict):
        self._settings_state["last_processing_settings"] = {
            "xlim": self._xlim_var.get().strip(),
            "ylim": self._ylim_var.get().strip(),
            "shift": self._shift_var.get().strip(),
            "wait_time": self._wait_var.get().strip(),
            "fps": self._fps_var.get().strip(),
        }

        names_payload = {
            str(vnum): str(name)
            for vnum, name in valve_names.items()
        }

        key = self._header_settings_key()
        if key:
            self._settings_state.setdefault("valve_names_by_header", {})[key] = names_payload

        self._settings_state.setdefault("valve_names_by_set", {})[
            self._valve_set_key()
        ] = names_payload
        self._settings_state["last_valve_names"] = names_payload

        self._save_settings_state()

    def _default_output_dir_for_file(self, file_path: str) -> str:
        p = Path(file_path)
        m = re.match(r"^(\d{6}_\d{2}h\d{2}m)", p.stem)
        suffix = m.group(1) if m else ""
        folder = f"cycle_plots_{suffix}" if suffix else "cycle_plots"
        return str(p.parent / folder)

    # =========================================================================
    #  File browsing
    # =========================================================================

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select Reactor Data JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self._file_path.set(path)
            self._output_dir.set(self._default_output_dir_for_file(path))

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select Output Directory")
        if path:
            self._output_dir.set(path)

    def _browse_recipe_sheet(self):
        path = filedialog.askopenfilename(
            title="Select Recipe Sheet",
            filetypes=[("CSV files", "*.csv"), ("Excel files", "*.xlsx;*.xls"), ("All files", "*.*")],
        )
        if path:
            self._recipe_sheet_path.set(path)
            self._recipe_output_path.set(str(Path(path).with_name(f"{Path(path).stem}_payload.json")))
            self._load_recipe_sheet_preview()

    def _open_raw_file_location(self):
        self._open_path_in_explorer(self._file_path.get(), "raw data file")

    def _open_recipe_file_location(self):
        target = self._recipe_output_path.get() or self._recipe_sheet_path.get()
        self._open_path_in_explorer(target, "recipe sheet")

    def _load_recipe_sheet_preview(self):
        path = self._recipe_sheet_path.get().strip()
        if not path:
            self._recipe_status_var.set("Select a recipe sheet to preview the payload.")
            self._set_text_widget(self._recipe_preview_box, "")
            return
        if not os.path.isfile(path):
            self._recipe_status_var.set("Selected recipe sheet was not found.")
            self._set_text_widget(self._recipe_preview_box, "")
            return

        try:
            payload = build_payload(load_table(Path(path)))
        except Exception as exc:
            self._recipe_payload = {}
            self._recipe_status_var.set(f"ERROR: {exc}")
            self._set_text_widget(self._recipe_preview_box, f"Failed to load recipe sheet.\n\n{exc}")
            return

        out_path = self._recipe_output_path.get().strip()
        if not out_path:
            out_path = str(Path(path).with_name(f"{Path(path).stem}_payload.json"))
            self._recipe_output_path.set(out_path)

        self._recipe_payload = payload
        self._recipe_status_var.set("Recipe sheet loaded. Review the calculated payload below.")
        self._set_text_widget(self._recipe_preview_box, self._format_recipe_preview(path, out_path, payload))

    def _create_recipe_payload(self):
        path = self._recipe_sheet_path.get().strip()
        if not path or not os.path.isfile(path):
            messagebox.showerror("Create JSON Payload", "Select a valid recipe sheet first.", parent=self)
            return

        if not self._recipe_payload:
            self._load_recipe_sheet_preview()
            if not self._recipe_payload:
                return

        out_path = self._recipe_output_path.get().strip()
        if not out_path:
            out_path = str(Path(path).with_name(f"{Path(path).stem}_payload.json"))
            self._recipe_output_path.set(out_path)

        try:
            payload, saved_path = self._run_save_with_retry(
                lambda: convert_recipe_sheet(path, out_path=out_path),
                out_path,
                "recipe JSON",
            )
        except SaveAbortedError as exc:
            self._recipe_status_var.set(f"Save cancelled: {exc}")
            return
        except Exception as exc:
            self._recipe_status_var.set(f"ERROR: {exc}")
            messagebox.showerror("Create JSON Payload", str(exc), parent=self)
            return

        self._recipe_payload = payload
        self._recipe_output_path.set(str(saved_path))
        self._recipe_status_var.set(f"JSON payload saved to {saved_path.name}")
        self._set_text_widget(
            self._recipe_preview_box,
            self._format_recipe_preview(path, str(saved_path), payload),
        )

    # =========================================================================
    #  Header loading
    # =========================================================================

    def _load_header(self):
        path = self._file_path.get().strip()
        if not path or not os.path.isfile(path):
            self._log("ERROR: Select a valid file first.")
            return
        try:
            self._header_info = read_header(path)
        except Exception as e:
            self._log(f"ERROR reading header: {e}")
            return

        vs = self._header_info.get("valveSequence", [])
        self._seq_dict = convert_sequence(vs)

        self._log(f"Loaded:  {self._header_info.get('username', '')}")
        self._log(f"Details: {self._header_info.get('experimentalDetails', '')}")
        for sk, sd in self._seq_dict.items():
            valves = [k for k in sd if k.startswith("valve")]
            self._log(f"  {sk}: {sd['cycles']} cycles -- {', '.join(valves)}")

        self._populate_valve_fields()
        self._apply_saved_valve_names()
        self._apply_last_processing_settings()
        self._process_btn.config(state="normal")

    def _populate_valve_fields(self):
        for w in self._valve_frame.winfo_children():
            w.destroy()

        # Collect unique valve numbers across all sequences.
        rows: list = []
        seen: set  = set()
        for seq_key, seq_data in self._seq_dict.items():
            for k in seq_data:
                if k.startswith("valve"):
                    m = re.search(r"\d+", k)
                    if m:
                        vnum = int(m.group())
                        if vnum not in seen:
                            seen.add(vnum)
                            rows.append(vnum)

        if not rows:
            ttk.Label(self._valve_frame, text="No valves found.").pack()
            return

        # Column headers
        hdr = ttk.Frame(self._valve_frame)
        hdr.pack(fill="x", padx=4)
        for col, (text, w) in enumerate([
            ("Valve #", 10), ("Custom Name", 28)
        ]):
            ttk.Label(hdr, text=text, width=w, anchor="w",
                      font=("", 9, "bold")).grid(row=0, column=col, padx=4)
        ttk.Separator(self._valve_frame, orient="horizontal").pack(
            fill="x", padx=4, pady=(2, 4))

        self._valve_name_vars.clear()
        for vnum in sorted(rows):
            rf = ttk.Frame(self._valve_frame)
            rf.pack(fill="x", pady=1, padx=4)
            ttk.Label(rf, text=f"Valve {vnum}", width=10, anchor="w").grid(row=0, column=0, padx=4)
            var = tk.StringVar(value=str(vnum))
            ttk.Entry(rf, textvariable=var, width=28).grid(row=0, column=1, padx=4)
            self._valve_name_vars[vnum] = var

    # =========================================================================
    #  Processing
    # =========================================================================

    def _start_processing(self):
        path    = self._file_path.get().strip()
        out_dir = self._output_dir.get().strip()
        if not path or not os.path.isfile(path):
            self._log("ERROR: Invalid data file.")
            return
        if not out_dir:
            self._log("ERROR: No output directory specified.")
            return

        valve_names = {vnum: var.get() for vnum, var in self._valve_name_vars.items()}
        xlim        = self._get_float(self._xlim_var)
        ylim        = self._get_float(self._ylim_var)
        shift       = self._get_float(self._shift_var,  default=0.0)
        wait_time   = self._get_float(self._wait_var,   default=0.0)

        self._persist_processing_preferences(valve_names)

        self._process_btn.config(state="disabled")
        self._preview_btn.config(state="disabled")
        self._set_progress(0)

        threading.Thread(
            target=self._run_processing,
            args=(path, out_dir, valve_names, xlim, ylim, shift, wait_time),
            daemon=True,
        ).start()

    def _run_processing(self, path, out_dir, valve_names, xlim, ylim, shift, wait_time):
        """Worker function — runs in a background thread."""
        try:
            self._log(f"\n-- {Path(path).name}")
            if wait_time > 0:
                self._log(f"   Trimming first {wait_time:.0f} s (wait time)")
            os.makedirs(out_dir, exist_ok=True)

            # -- Build phase structure from header --------------------------------
            named_seq   = apply_valve_names(self._seq_dict, valve_names)
            phased_seq  = compute_phase_bins(named_seq, shift=shift)
            cyc_seq_map = make_cycle_seq_map(phased_seq)

            for sk, sd in phased_seq.items():
                self._log(f"  {sk} bins (s): {sd.get('phase_bins', [])}")
                self._log(f"  {sk} phases  : {sd.get('phase_names', [])}")

            # -- Stream-parse the file --------------------------------------------
            self._log("Reading data...")

            def _prog(br, fs):
                self._set_progress(br / fs * 55)

            cycle_points, cycle_start_map = stream_pressure(
                path, wait_time=wait_time, progress_cb=_prog)

            self._set_progress(55)
            self._log(f"  {len(cycle_points)} cycles, "
                      f"{sum(len(v) for v in cycle_points.values()):,} pressure points")

            # -- Write condensed log (always refresh, even for condensed input) ---
            is_input_condensed = is_condensed_file(path)
            cpath = Path(path) if is_input_condensed else condensed_path(path)
            self._log("Writing condensed log...")
            try:
                condensed_out = str(cpath)

                def _fmt_bytes(nbytes: int) -> str:
                    units = ["B", "KB", "MB", "GB", "TB"]
                    size = float(max(nbytes, 0))
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

                def _phase_lookup(cycle, time_s, raw_step, payload):
                    seq_key = cyc_seq_map.get(cycle)
                    if not seq_key:
                        return None
                    bins = phased_seq.get(seq_key, {}).get("phase_bins", [])
                    names = phased_seq.get(seq_key, {}).get("phase_names", [])
                    if not bins or not names:
                        return None
                    t0 = cycle_start_map.get(cycle)
                    if t0 is None:
                        return None
                    phase = assign_phase(time_s - t0, bins, names)
                    if not phase:
                        return None
                    return _format_phase_for_step(phase)

                stats = self._run_save_with_retry(
                    lambda: condense_log(
                        path,
                        condensed_out,
                        phase_lookup=_phase_lookup,
                        return_stats=True,
                    ),
                    condensed_out,
                    "condensed log",
                )
                self._log(
                    f"  Raw rows before condense: {stats['total_rows']:,} total, "
                    f"{stats['pressure_rows']:,} pressure"
                )
                self._log(
                    f"  File size: {_fmt_bytes(stats['input_size_bytes'])} -> "
                    f"{_fmt_bytes(stats['output_size_bytes'])} "
                    f"({stats['size_reduction_pct']:.1f}% reduction)"
                )
                self._log(
                    f"  Condensed: {Path(cpath).name}  "
                    f"({stats['rows_written']:,} data rows)"
                )
            except SaveAbortedError:
                self._log("  Condensed log save cancelled.")
            except Exception as exc:
                self._log(f"  WARNING: could not write condensed log: {exc}")

            # -- Baseline correction ----------------------------------------------
            cycle_points, baseline = subtract_baseline(cycle_points)
            self._log(f"  Baseline subtracted: {baseline:.2f} mTorr")

            # -- Axis limits -------------------------------------------------------
            max_ct, max_p = compute_axis_limits(cycle_points, cycle_start_map)
            xlim_val = xlim if xlim else max_ct
            ylim_val = ylim if ylim else max_p
            stem = Path(path).stem
            filename = stem[:-len("_condensed")] if stem.endswith("_condensed") else stem

            # -- Phase color map --------------------------------------------------
            all_phase_names: list[str] = []
            for sd in phased_seq.values():
                for pn in sd.get("phase_names", []):
                    if pn not in all_phase_names:
                        all_phase_names.append(pn)
            phase_color_map = build_phase_color_map(all_phase_names)

            # -- Batch plot generation --------------------------------------------
            self._log("Generating plots...")
            cycles_sorted = sorted(cycle_points.keys())
            total         = len(cycles_sorted)

            for i, cycle in enumerate(cycles_sorted):
                seq_key = cyc_seq_map.get(cycle)
                if seq_key is None:
                    self._set_progress(55 + (i + 1) / total * 45)
                    continue

                segs = build_segments(
                    cycle, cycle_points, cycle_start_map,
                    phased_seq, cyc_seq_map, assign_phase)

                fig = draw_cycle_figure(
                    cycle, filename, segs, phase_color_map,
                    all_phase_names, xlim_val, ylim_val)

                png_path = os.path.join(out_dir, f"cycle_{cycle:04d}.png")
                try:
                    self._run_save_with_retry(
                        lambda: save_cycle_figure(fig, cycle, out_dir),
                        png_path,
                        "PNG plot",
                    )
                finally:
                    plt.close(fig)

                self._set_progress(55 + (i + 1) / total * 45)

            self._set_progress(100)
            self._log(f"\nDone -- {total} plots saved to:\n  {out_dir}")

            # -- Exposure CSV -----------------------------------------------------
            self._log("Computing phase exposures...")
            exp_rows = compute_exposure_table(
                cycles_sorted, cycle_points, cycle_start_map,
                phased_seq, cyc_seq_map, assign_phase,
            )
            csv_path = os.path.join(out_dir, f"{filename}_exposure.csv")
            self._run_save_with_retry(
                lambda: save_exposure_csv(exp_rows, out_dir, filename),
                csv_path,
                "exposure CSV",
            )
            self._log(f"  Exposure CSV: {Path(csv_path).name}  ({len(exp_rows)} rows)")

            # Cache for interactive preview
            self._cached = dict(
                cycle_points    = cycle_points,
                cycle_start_map = cycle_start_map,
                phased_seq      = phased_seq,
                cyc_seq_map     = cyc_seq_map,
                all_phase_names = all_phase_names,
                phase_color_map = phase_color_map,
                xlim_val        = xlim_val,
                ylim_val        = ylim_val,
                filename        = filename,
                out_dir         = out_dir,
            )
        except SaveAbortedError as exc:
            self._log(f"Save cancelled: {exc}")
        except Exception as exc:
            self._log(f"Processing ERROR: {exc}")
        finally:
            def _re_enable():
                self._process_btn.config(state="normal")
                self._preview_btn.config(state="normal")
                self._anim_btn.config(state="normal")
            self.after(0, _re_enable)

    # =========================================================================
    #  Animation
    # =========================================================================

    def _start_animation(self):
        if not self._cached:
            self._log("No data cached -- run processing first.")
            return

        fps = self._get_float(self._fps_var, default=5.0)
        if fps <= 0:
            fps = 5.0

        self._process_btn.config(state="disabled")
        self._preview_btn.config(state="disabled")
        self._anim_btn.config(state="disabled")
        self._set_progress(0)

        threading.Thread(
            target=self._run_animation,
            args=(fps,),
            daemon=True,
        ).start()

    def _run_animation(self, fps: float):
        """Worker — render and save the animation GIF in a background thread."""
        c       = self._cached
        out_dir = c["out_dir"]
        n       = len(c["cycle_points"])
        self._log(f"\nGenerating animation ({n} frames @ {fps:.0f} fps)...")

        def _prog(done, total):
            self._set_progress(done / total * 100)

        try:
            out_path = os.path.join(out_dir, f"{c['filename']}_animation.gif")
            self._run_save_with_retry(
                lambda: build_animation(
                    sorted(c["cycle_points"].keys()),
                    c["cycle_points"],
                    c["cycle_start_map"],
                    c["phased_seq"],
                    c["cyc_seq_map"],
                    c["all_phase_names"],
                    c["phase_color_map"],
                    assign_phase,
                    c["xlim_val"],
                    c["ylim_val"],
                    c["filename"],
                    out_dir,
                    fps=max(1, int(fps)),
                    progress_cb=_prog,
                ),
                out_path,
                "animation GIF",
            )
            self._log(f"Animation saved: {Path(out_path).name}")
        except ImportError:
            self._log(
                "ERROR: Pillow is required for animations.\n"
                "  Run:  .venv\\Scripts\\pip install Pillow"
            )
        except SaveAbortedError as exc:
            self._log(f"Animation save cancelled: {exc}")
        except Exception as e:
            self._log(f"Animation ERROR: {e}")
        finally:
            self._set_progress(100)
            def _re_enable():
                self._process_btn.config(state="normal")
                self._preview_btn.config(state="normal")
                self._anim_btn.config(state="normal")
            self.after(0, _re_enable)

    # =========================================================================
    #  Interactive preview
    # =========================================================================

    def _preview_plot(self):
        if not self._cached:
            self._log("No data cached -- run processing first.")
            return

        try:
            cycle = int(self._preview_cycle_var.get())
        except ValueError:
            self._log("ERROR: Preview cycle must be an integer.")
            return

        c = self._cached
        if cycle not in c["cycle_points"]:
            avail = sorted(c["cycle_points"].keys())
            self._log(f"ERROR: Cycle {cycle} not found. "
                      f"Available range: {avail[0]}..{avail[-1]}")
            return

        segs = build_segments(
            cycle,
            c["cycle_points"], c["cycle_start_map"],
            c["phased_seq"],   c["cyc_seq_map"],
            assign_phase,
        )

        fig = draw_cycle_figure(
            cycle,
            c["filename"],
            segs,
            c["phase_color_map"],
            c["all_phase_names"],
            c["xlim_val"],
            c["ylim_val"],
            figsize=(10, 7),
        )

        cycles_sorted = sorted(c["cycle_points"].keys())
        self._open_preview_window(fig, cycle, cycles_sorted,
                                  c["filename"])

    def _open_preview_window(self, fig, cycle: int,
                             cycles_sorted: list, filename: str):
        """Embed *fig* in a Toplevel with a matplotlib toolbar + Prev/Next."""
        win = tk.Toplevel(self)
        win.title(f"Preview  --  {filename}  cycle {cycle}")
        win.geometry("1000x660")

        toolbar_frame = ttk.Frame(win)
        toolbar_frame.pack(side="top", fill="x")

        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        NavigationToolbar2Tk(canvas, toolbar_frame).update()
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

        # -- Prev / Next navigation ------------------------------------------
        nav = ttk.Frame(win)
        nav.pack(side="bottom", pady=6)
        idx = cycles_sorted.index(cycle) if cycle in cycles_sorted else 0

        def _go(new_cycle: int):
            self._preview_cycle_var.set(str(new_cycle))
            win.destroy()
            self._preview_plot()

        ttk.Button(
            nav, text="< Prev",
            state="normal" if idx > 0 else "disabled",
            command=lambda: _go(cycles_sorted[max(idx - 1, 0)]),
        ).pack(side="left", padx=8)

        ttk.Label(nav,
                  text=f"Cycle {cycle}  of  {cycles_sorted[-1]}"
                  ).pack(side="left", padx=12)

        ttk.Button(
            nav, text="Next >",
            state="normal" if idx < len(cycles_sorted) - 1 else "disabled",
            command=lambda: _go(cycles_sorted[min(idx + 1, len(cycles_sorted) - 1)]),
        ).pack(side="left", padx=8)


def main():
    app = ReactorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
