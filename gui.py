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
import difflib
import threading
from concurrent.futures import ThreadPoolExecutor
import os
import re
import json
import subprocess
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
    compute_leakrate_regressions,
    save_cycle_figure,
    compute_axis_limits,
    compute_exposure_table,
    save_exposure_csv,
    build_animation,
)
from ise_utils import save_ise_thickness_csv
from convert_to_json import load_table, build_payload, save_payload, validate_recipe_sheet, build_output_filename_report
from header_editor import open_header_editor
from header_text import (
    compare_header_payloads,
    normalized_header_text,
    parse_header_text,
    save_converted_header,
)


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
        self._header_txt_path    = tk.StringVar()
        self._header_comparison_warning_var = tk.StringVar()
        self._output_dir        = tk.StringVar()
        self._xlim_var          = tk.StringVar()
        self._ylim_var          = tk.StringVar()
        self._grid_x_var        = tk.BooleanVar(value=True)
        self._grid_y_var        = tk.BooleanVar(value=True)
        self._grid_x_spacing_var = tk.StringVar()
        self._grid_y_spacing_var = tk.StringVar()
        self._shift_var         = tk.StringVar()
        self._wait_var          = tk.StringVar()
        self._fps_var           = tk.StringVar()
        self._leakrate_phase_reduction_var = tk.StringVar()
        self._thickness_blank_rows_var = tk.StringVar()
        self._preview_cycle_var = tk.StringVar(value="1")
        self._write_condensed_json_var = tk.BooleanVar(value=True)
        self._exclude_falsey_edr_tags_var = tk.BooleanVar(value=False)
        self._ise_file_path     = tk.StringVar()
        self._recipe_sheet_path = tk.StringVar()
        self._recipe_output_path = tk.StringVar()
        self._recipe_status_var = tk.StringVar(value="Load a recipe sheet to preview the payload.")
        self._recipe_validation_var = tk.StringVar(value="")
        self._recipe_username_warning_var = tk.StringVar(value="")
        self._file_path.trace_add("write", self._on_raw_file_path_changed)

        # -- state -------------------------------------------------------------
        self._header_info:     dict = {}
        self._seq_dict:        dict = {}
        self._valve_name_vars: dict = {}   # {valve_num_int: tk.StringVar}
        self._valve_name_entries: dict = {} # {valve_num_int: ttk.Entry}
        self._wait_entry = None
        self._cached:          dict = {}   # populated after a processing run
        self._recipe_payload:  dict = {}
        self._reactor_type: str | None = None
        settings_dir = Path(__file__).parent
        self._settings_path = settings_dir / "config_local.json"
        self._default_settings_path = settings_dir / "config_default.json"
        self._valve_name_log_path = settings_dir / "valve_name_log.jsonl"
        self._settings_state: dict = {
            "last_processing_settings": {},
            "last_valve_names": {},
            "reactors": [],
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
        self._edit_header_btn = ttk.Button(
            file_frame, text="Edit Header...", command=self._edit_header, state="disabled"
        )
        self._edit_header_btn.pack(side="left", padx=(0, 4))
        ttk.Button(file_frame, text="Open File Location",
                   command=self._open_raw_file_location).pack(side="left")

        self._header_txt_frame = ttk.LabelFrame(parent, text="Header Text File", padding=8)
        self._header_txt_frame.pack(fill="x", padx=10, pady=4)
        self._header_txt_entry = ttk.Entry(
            self._header_txt_frame,
            textvariable=self._header_txt_path,
        )
        self._header_txt_entry.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self._header_txt_browse_btn = ttk.Button(
            self._header_txt_frame,
            text="Browse...",
            command=self._browse_header_txt,
        )
        self._header_txt_browse_btn.pack(side="left", padx=(0, 4))
        ttk.Button(
            self._header_txt_frame,
            text="Open File Location",
            command=self._open_header_txt_location,
        ).pack(side="left")
        ttk.Button(
            self._header_txt_frame,
            text="Compare Headers",
            command=self._compare_header_text_file,
        ).pack(side="left", padx=(6, 0))
        ttk.Button(
            self._header_txt_frame,
            text="Use Header JSON",
            command=self._use_header_text_as_raw_header,
        ).pack(side="left", padx=(6, 0))
        tk.Label(
            self._header_txt_frame,
            textvariable=self._header_comparison_warning_var,
            foreground="red",
            anchor="w",
            justify="left",
        ).pack(side="left", padx=(8, 0))

        # -- iSE thickness source file ----------------------------------------
        ise_frame = ttk.LabelFrame(parent, text="iSE Data File", padding=8)
        ise_frame.pack(fill="x", **pad)
        ttk.Entry(ise_frame, textvariable=self._ise_file_path, width=54).pack(
            side="left", expand=True, fill="x", padx=(0, 4))
        ttk.Button(ise_frame, text="Browse...", command=self._browse_ise_file).pack(
            side="left", padx=(0, 4))
        ttk.Button(ise_frame, text="Open File Location",
                   command=self._open_ise_file_location).pack(side="left")

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
        ttk.Button(
            out_frame,
            text="Open Output Directory",
            command=self._open_output_directory,
        ).pack(side="left", padx=(4, 0))

        plot_frame = ttk.LabelFrame(opt_outer, text="Plot Options", padding=8)
        plot_frame.pack(side="left")
        _opts = [
            ("X max (s):",       0, 0, self._xlim_var),
            ("Y max (mTorr):",   0, 2, self._ylim_var),
            ("Phase shift (s):", 1, 0, self._shift_var),
            ("Wait time (s):",   2, 0, self._wait_var),
            ("Anim FPS:",        3, 0, self._fps_var),
            ("LeakRate phase reduction:", 4, 0, self._leakrate_phase_reduction_var),
            ("Thickness blank rows:", 5, 0, self._thickness_blank_rows_var),
        ]
        for label_text, row, col, var in _opts:
            ttk.Label(plot_frame, text=label_text).grid(
                row=row, column=col, sticky="w", padx=3, pady=(3, 0))
            entry = ttk.Entry(plot_frame, textvariable=var, width=8)
            entry.grid(
                row=row, column=col + 1, padx=3, pady=(3, 0))
            if label_text == "Wait time (s):":
                self._wait_entry = entry
        ttk.Checkbutton(
            plot_frame,
            text="X gridlines",
            variable=self._grid_x_var,
        ).grid(row=6, column=0, sticky="w", padx=3, pady=(6, 0))
        ttk.Checkbutton(
            plot_frame,
            text="Y gridlines",
            variable=self._grid_y_var,
        ).grid(row=6, column=2, sticky="w", padx=3, pady=(6, 0))
        ttk.Label(plot_frame, text="X grid spacing:").grid(
            row=7, column=0, sticky="w", padx=3, pady=(3, 0))
        ttk.Entry(plot_frame, textvariable=self._grid_x_spacing_var, width=8).grid(
            row=7, column=1, padx=3, pady=(3, 0))
        ttk.Label(plot_frame, text="Y grid spacing:").grid(
            row=8, column=0, sticky="w", padx=3, pady=(3, 0))
        ttk.Entry(plot_frame, textvariable=self._grid_y_spacing_var, width=8).grid(
            row=8, column=1, padx=3, pady=(3, 0))
        ttk.Checkbutton(
            plot_frame,
            text="Write condensed data JSON",
            variable=self._write_condensed_json_var,
        ).grid(row=9, column=0, columnspan=3, sticky="w", padx=3, pady=(6, 0))

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
        self._create_payload_btn = ttk.Button(file_frame, text="Create JSON Payload",
                   command=self._create_recipe_payload)
        self._create_payload_btn.pack(side="left", padx=(0, 4))
        ttk.Button(file_frame, text="Open Blank Sheet",
               command=self._open_blank_recipe_sheet).pack(side="left", padx=(0, 4))
        ttk.Button(file_frame, text="Open File Location",
                   command=self._open_recipe_file_location).pack(side="left")

        ttk.Checkbutton(
            parent,
            text="Exclude falsey EDR tags from the username and filename",
            variable=self._exclude_falsey_edr_tags_var,
            command=self._load_recipe_sheet_preview,
        ).pack(anchor="w", padx=12, pady=(0, 2))

        validation_frame = ttk.Frame(parent)
        validation_frame.pack(fill="x", padx=10, pady=(2, 0))
        self._recipe_validation_label = tk.Label(
            validation_frame,
            textvariable=self._recipe_validation_var,
            anchor="w",
            justify="left",
            foreground="red",
            wraplength=900,
        )
        self._recipe_validation_label.pack(fill="x")

        warning_frame = ttk.Frame(parent)
        warning_frame.pack(fill="x", padx=10, pady=(2, 0))
        self._recipe_username_warning_label = tk.Label(
            warning_frame,
            textvariable=self._recipe_username_warning_var,
            anchor="w",
            justify="left",
            foreground="red",
            wraplength=900,
        )
        self._recipe_username_warning_label.pack(fill="x")

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
            wrap="none",
        )
        self._recipe_preview_box.pack(fill="both", expand=True)
        preview_xscroll = ttk.Scrollbar(review_frame, orient="horizontal", command=self._recipe_preview_box.xview)
        preview_xscroll.pack(fill="x")
        self._recipe_preview_box.configure(xscrollcommand=preview_xscroll.set)

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
        if threading.current_thread() is threading.main_thread():
            return messagebox.askretrycancel(
                "File In Use",
                f"Could not save the {label} because it appears to be open:\n\n"
                f"{file_path}\n\n"
                "Close the file, then click Retry to try saving again.",
                parent=self,
            )

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
        details_payload = None
        if isinstance(details_value, str):
            try:
                parsed = json.loads(details_value)
            except (TypeError, ValueError):
                details_json = details_value
            else:
                details_payload = parsed if isinstance(parsed, dict) else None
                details_json = self._format_header_details(parsed)
        else:
            details_payload = details_value if isinstance(details_value, dict) else None
            details_json = self._format_header_details(details_value)
        recipe_rows = payload.get("recipe", [])
        sequence_notes = details_payload.get("SequenceNotes", []) if isinstance(details_payload, dict) else []
        timing_rows_text = self._format_timing_rows(recipe_rows, sequence_notes)
        return (
            f"Recipe sheet:\n{csv_path}\n\n"
            f"Output JSON:\n{out_path}\n\n"
            f"username:\n{payload.get('username', '')}\n\n"
            f"experimentalDetails:\n{details_json}\n\n"
            f"Timing rows:\n{timing_rows_text}"
        )

    def _format_timing_rows(self, recipe_rows: list, sequence_notes: list | None = None) -> str:
        if not recipe_rows:
            return "(none)"

        normalized_rows = [["" if value is None else str(value) for value in row] for row in recipe_rows]
        note_rows = ["" for _ in normalized_rows]
        notes_by_seq: dict[int, list[str]] = {}
        notes_by_cycles: dict[int, list[str]] = {}
        if isinstance(sequence_notes, list):
            for entry in sequence_notes:
                if not isinstance(entry, dict):
                    continue
                note_text = str(entry.get("Note", "")).strip()
                if not note_text:
                    continue
                seq_value = entry.get("Seq", entry.get("Sequence"))
                has_sequence = False
                if seq_value not in (None, ""):
                    try:
                        notes_by_seq.setdefault(int(seq_value), []).append(note_text)
                        has_sequence = True
                    except (TypeError, ValueError):
                        pass
                cycle_value = entry.get("Cycles")
                if not has_sequence and cycle_value not in (None, ""):
                    try:
                        notes_by_cycles.setdefault(int(cycle_value), []).append(note_text)
                    except (TypeError, ValueError):
                        pass

        seq_index = 0
        current_cycles = None
        for row_index, row in enumerate(normalized_rows):
            cycle_cell = row[0].strip() if row else ""
            if cycle_cell:
                seq_index += 1
                current_cycles = None
                try:
                    current_cycles = int(float(cycle_cell))
                except (TypeError, ValueError):
                    current_cycles = None
                notes = notes_by_seq.get(seq_index, [])
                if not notes and current_cycles is not None:
                    notes = notes_by_cycles.get(current_cycles, [])
                if notes:
                    note_rows[row_index] = " | ".join(notes)

        base_headers = [
            "Cycles",
            "Valve #",
            "Pre-dose Pump (s)",
            "N2 Dose (s)",
            "Pump Dose (s)",
            "Dose (s)",
            "Hold (s)",
            "Pre-Purge (s)",
            "Purge (s)",
        ]
        column_count = max((len(row) for row in normalized_rows), default=0)
        if column_count == 0:
            return "(none)"

        headers = base_headers[:column_count] + ["Sequence Notes"]
        output_column_count = column_count + 1

        widths = [0] * output_column_count
        for row in normalized_rows:
            for index in range(column_count):
                cell_text = row[index] if index < len(row) else ""
                widths[index] = max(widths[index], len(cell_text))
        for index, header in enumerate(headers):
            widths[index] = max(widths[index], len(header))
        for note_text in note_rows:
            widths[column_count] = max(widths[column_count], len(note_text))

        lines = []
        lines.append("  ".join(headers[index].ljust(widths[index]) for index in range(output_column_count)).rstrip())
        for row_index, row in enumerate(normalized_rows):
            cells = []
            for index in range(column_count):
                cell_text = row[index] if index < len(row) else ""
                cells.append(cell_text.rjust(widths[index]))
            cells.append(note_rows[row_index].ljust(widths[column_count]))
            lines.append("  ".join(cells).rstrip())

        return "\n".join(lines)

    def _format_header_details(self, details_value) -> str:
        def _format_value(value, level: int = 0) -> str:
            indent = "  " * level
            next_indent = "  " * (level + 1)

            if isinstance(value, dict):
                if not value:
                    return "{}"
                lines = ["{"]
                items = list(value.items())
                for index, (key, child) in enumerate(items):
                    rendered = _format_value(child, level + 1)
                    if "\n" in rendered:
                        rendered = "\n".join(
                            f"{next_indent}{line}" if line else line
                            for line in rendered.splitlines()
                        )
                    comma = "," if index < len(items) - 1 else ""
                    lines.append(f"{next_indent}{json.dumps(key, ensure_ascii=False)}: {rendered}{comma}")
                lines.append(f"{indent}}}")
                return "\n".join(lines)

            if isinstance(value, list):
                return json.dumps(value, ensure_ascii=False)

            return json.dumps(value, ensure_ascii=False)

        if isinstance(details_value, str):
            text = details_value.strip()
            if not text:
                return ""
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                return text
            return _format_value(parsed)

        if isinstance(details_value, dict):
            return _format_value(details_value)

        return str(details_value)

    def _parse_experimental_details_payload(self, details_value):
        if isinstance(details_value, dict):
            return dict(details_value)
        if isinstance(details_value, str):
            text = details_value.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                return text
            if isinstance(parsed, dict):
                return parsed
        return details_value if details_value is not None else {}

    def _recipe_valve_name_payload(self, valve_names: dict) -> dict:
        used_valves: set[int] = set()
        for seq_data in self._seq_dict.values():
            for vnum, _ in seq_data.get("valve_rows", []):
                used_valves.add(vnum)

        payload = {}
        for vnum in sorted(used_valves):
            name = str(valve_names.get(vnum, "")).strip()
            if name:
                payload[str(vnum)] = name
        return payload

    def _details_valve_name_mapping(self, details_payload) -> dict[int, str]:
        if not isinstance(details_payload, dict):
            return {}

        names = details_payload.get("Name", [])
        precursors = details_payload.get("ValvePrecursor", [])
        if not isinstance(names, list) or not isinstance(precursors, list):
            return {}

        mapping: dict[int, str] = {}
        for precursor, name in zip(precursors, names):
            try:
                vnum = int(precursor)
            except (TypeError, ValueError):
                continue

            label = str(name).strip()
            if label and label.lower() != "stage":
                mapping[vnum] = label

        return mapping

    def _effective_valve_names(self, manual_valve_names: dict, details_payload) -> dict[int, str]:
        effective = {
            vnum: str(name).strip()
            for vnum, name in manual_valve_names.items()
            if str(name).strip()
        }
        effective.update(self._details_valve_name_mapping(details_payload))
        return effective

    def _apply_detail_valve_names(self, details_payload):
        details_payload = self._parse_experimental_details_payload(details_payload)
        details_mapping = self._details_valve_name_mapping(details_payload)
        if not details_mapping:
            for entry in self._valve_name_entries.values():
                entry.configure(state="normal")
            return

        for vnum, var in self._valve_name_vars.items():
            name = details_mapping.get(vnum)
            if name:
                var.set(name)
                entry = self._valve_name_entries.get(vnum)
                if entry is not None:
                    entry.configure(state="disabled")
            else:
                entry = self._valve_name_entries.get(vnum)
                if entry is not None:
                    entry.configure(state="normal")

    def _apply_detail_wait_time(self, details_payload):
        details_payload = self._parse_experimental_details_payload(details_payload)
        if not isinstance(details_payload, dict):
            if self._wait_entry is not None:
                self._wait_entry.configure(state="normal")
            return

        if "WaitTime" not in details_payload:
            if self._wait_entry is not None:
                self._wait_entry.configure(state="normal")
            return

        wait_time = details_payload.get("WaitTime", "")
        self._wait_var.set(str(wait_time))
        if self._wait_entry is not None:
            self._wait_entry.configure(state="disabled")

    def _sequence_notes_by_seq(self, details_payload) -> tuple[dict[int, str], dict[int, str]]:
        notes_by_seq: dict[int, str] = {}
        notes_by_cycles: dict[int, str] = {}
        if not isinstance(details_payload, dict):
            return notes_by_seq, notes_by_cycles

        entries = details_payload.get("SequenceNotes", [])
        if not isinstance(entries, list):
            return notes_by_seq, notes_by_cycles

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            note_text = str(entry.get("Note", "")).strip()
            if not note_text:
                continue

            seq_value = entry.get("Seq", entry.get("Sequence"))
            has_sequence = False
            if seq_value not in (None, ""):
                try:
                    notes_by_seq[int(seq_value)] = note_text
                    has_sequence = True
                except (TypeError, ValueError):
                    pass

            cycle_value = entry.get("Cycles")
            if not has_sequence and cycle_value not in (None, ""):
                try:
                    notes_by_cycles[int(cycle_value)] = note_text
                except (TypeError, ValueError):
                    pass

        return notes_by_seq, notes_by_cycles

    def _sequence_note_text(self, seq_key: str, phased_seq: dict, details_payload) -> str | None:
        notes_by_seq, notes_by_cycles = self._sequence_notes_by_seq(details_payload)
        match = re.search(r"\d+", seq_key or "")
        seq_index = int(match.group()) if match else None
        if seq_index is None:
            return None

        note_text = notes_by_seq.get(seq_index)
        if not note_text:
            cycles = phased_seq.get(seq_key, {}).get("cycles") if isinstance(phased_seq, dict) else None
            if cycles not in (None, ""):
                try:
                    note_text = notes_by_cycles.get(int(cycles))
                except (TypeError, ValueError):
                    note_text = None
        if not note_text:
            return None
        return f"Seq {seq_index}: {note_text}"

    def _format_timing_table(self, seq_dict: dict) -> str:
        lines = ["Timing table:"]
        for seq_key, seq_data in seq_dict.items():
            cycles = seq_data.get("cycles", "")
            lines.append(f"  {seq_key} (cycles: {cycles})")
            for vnum, timing in seq_data.get("valve_rows", []):
                value_text = json.dumps(list(timing), ensure_ascii=False)
                lines.append(f"    valve{vnum}: {value_text}")
        return "\n".join(lines)

    def _load_settings_state(self):
        if not self._settings_path.exists() and self._default_settings_path.exists():
            try:
                shutil.copyfile(self._default_settings_path, self._settings_path)
            except Exception:
                pass

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
        last_valves = data.get("last_valve_names", {})
        reactors = data.get("reactors", [])

        self._settings_state = {
            "last_processing_settings": last if isinstance(last, dict) else {},
            "last_valve_names": last_valves if isinstance(last_valves, dict) else {},
            "reactors": [str(reactor) for reactor in reactors if str(reactor).strip()]
            if isinstance(reactors, list) else [],
        }

    def _reactor_type_from_filename(self, file_path: str) -> str | None:
        filename = Path(file_path).name
        reactors = self._settings_state.get("reactors", [])
        if not isinstance(reactors, list) or not reactors:
            return None

        reactor_pattern = "|".join(
            re.escape(reactor)
            for reactor in sorted(reactors, key=len, reverse=True)
            if isinstance(reactor, str) and reactor
        )
        if not reactor_pattern:
            return None

        match = re.fullmatch(
            rf"\d{{6}}_\d{{2}}h\d{{2}}m_{{1,2}}(?P<reactor>{reactor_pattern})"
            rf".*_Reactor\d+_Data(?:_condensed)?\.json",
            filename,
        )
        return match.group("reactor") if match else None

    def _processed_datetime_from_filename(self, file_path: str) -> str | None:
        match = re.match(
            r"^(?P<date>\d{6})_(?P<time>\d{2}h\d{2}m)_",
            Path(file_path).name,
        )
        if not match:
            return None

        try:
            processed_at = datetime.strptime(
                f"{match.group('date')}_{match.group('time')}",
                "%y%m%d_%Hh%Mm",
            ).replace(tzinfo=ZoneInfo("America/Los_Angeles"))
        except ValueError:
            return None
        return processed_at.isoformat()

    def _append_valve_name_log(self, file_path: str, valve_names: dict):
        processed_datetime = self._processed_datetime_from_filename(file_path)
        if processed_datetime is None:
            self._log(f"WARNING: could not parse timestamp for valve name log: {Path(file_path).name}")
            return

        record = {
            "data_file": Path(file_path).name,
            "GUID": str(self._header_info.get("GUID", "")),
            "valve_names": {
                self._reactor_type: {
                    str(vnum): str(name)
                    for vnum, name in valve_names.items()
                }
            },
            "process_datetime": processed_datetime,
            "log_datetime": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
        }
        try:
            if self._valve_name_log_path.exists():
                with self._valve_name_log_path.open("r", encoding="utf-8") as fh:
                    for line in fh:
                        try:
                            existing = json.loads(line)
                            if not isinstance(existing, dict):
                                continue
                            existing.pop("log_datetime", None)
                            comparable = dict(record)
                            comparable.pop("log_datetime", None)
                            if existing == comparable:
                                return
                        except (json.JSONDecodeError, TypeError):
                            continue

            with self._valve_name_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        except Exception as exc:
            self._log(f"WARNING: could not append valve name log: {exc}")

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
        grid_x = last.get("grid_x")
        grid_y = last.get("grid_y")
        legacy_grid_spacing = last.get("grid_spacing")
        grid_x_spacing = last.get("grid_x_spacing", legacy_grid_spacing)
        grid_y_spacing = last.get("grid_y_spacing", legacy_grid_spacing)
        shift = last.get("shift")
        wait_time = last.get("wait_time")
        fps = last.get("fps")
        leakrate_phase_reduction = last.get("leakrate_phase_reduction")
        thickness_blank_rows = last.get("thickness_blank_rows")
        write_condensed_json = last.get("write_condensed_json")
        leakrate_phase_reduction = last.get("leakrate_phase_reduction")
        if xlim is not None:
            self._xlim_var.set(str(xlim))
        if ylim is not None:
            self._ylim_var.set(str(ylim))
        if grid_x is not None:
            self._grid_x_var.set(bool(grid_x))
        if grid_y is not None:
            self._grid_y_var.set(bool(grid_y))
        if grid_x_spacing is not None:
            self._grid_x_spacing_var.set(str(grid_x_spacing))
        if grid_y_spacing is not None:
            self._grid_y_spacing_var.set(str(grid_y_spacing))
        if shift is not None:
            self._shift_var.set(str(shift))
        if wait_time is not None:
            self._wait_var.set(str(wait_time))
        if fps is not None:
            self._fps_var.set(str(fps))
        if leakrate_phase_reduction is not None:
            self._leakrate_phase_reduction_var.set(str(leakrate_phase_reduction))
        if thickness_blank_rows is not None:
            self._thickness_blank_rows_var.set(str(thickness_blank_rows))
        if write_condensed_json is not None:
            self._write_condensed_json_var.set(bool(write_condensed_json))
        if leakrate_phase_reduction is not None:
            self._leakrate_phase_reduction_var.set(str(leakrate_phase_reduction))

    def _apply_saved_valve_names(self):
        saved_by_reactor = self._settings_state.get("last_valve_names", {})
        if not isinstance(saved_by_reactor, dict):
            return

        saved = saved_by_reactor.get(self._reactor_type)
        if not isinstance(saved, dict):
            saved = saved_by_reactor if all(
                not isinstance(value, dict) for value in saved_by_reactor.values()
            ) else {}
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
            "grid_x": self._grid_x_var.get(),
            "grid_y": self._grid_y_var.get(),
            "grid_x_spacing": self._grid_x_spacing_var.get().strip(),
            "grid_y_spacing": self._grid_y_spacing_var.get().strip(),
            "shift": self._shift_var.get().strip(),
            "wait_time": self._wait_var.get().strip(),
            "fps": self._fps_var.get().strip(),
            "leakrate_phase_reduction": self._leakrate_phase_reduction_var.get().strip(),
            "thickness_blank_rows": self._thickness_blank_rows_var.get().strip(),
            "write_condensed_json": self._write_condensed_json_var.get(),
            "leakrate_phase_reduction": self._leakrate_phase_reduction_var.get().strip(),
        }

        names_payload = {
            str(vnum): str(name)
            for vnum, name in valve_names.items()
        }

        last_valve_names = self._settings_state.get("last_valve_names", {})
        if not isinstance(last_valve_names, dict):
            last_valve_names = {}
        if all(not isinstance(value, dict) for value in last_valve_names.values()):
            last_valve_names = {self._reactor_type: dict(last_valve_names)}

        reactor_names = last_valve_names.setdefault(self._reactor_type, {})
        if not isinstance(reactor_names, dict):
            reactor_names = {}
            last_valve_names[self._reactor_type] = reactor_names
        reactor_names.update(names_payload)
        self._settings_state["last_valve_names"] = last_valve_names

        self._save_settings_state()

    def _default_output_dir_for_file(self, file_path: str) -> str:
        p = Path(file_path)
        m = re.match(r"^(\d{6}_\d{2}h\d{2}m)", p.stem)
        suffix = m.group(1) if m else ""
        folder = f"cycle_plots_{suffix}" if suffix else "cycle_plots"
        return str(p.parent / folder)

    def _predicted_header_txt_path(self, file_path: str) -> str:
        path = Path(file_path)
        parent_name = path.parent.name.casefold()
        reactor_data_dir = path.parent.parent
        if parent_name != "json files" or reactor_data_dir.name.casefold() != "reactor data":
            return ""

        match = re.match(r"^(?P<date>\d{6})_", path.name)
        if not match:
            return ""
        try:
            month_dir = datetime.strptime(match.group("date"), "%y%m%d").strftime("%B %Y")
        except ValueError:
            return ""

        header_name = re.sub(r"_Data(?:_condensed)?\.json$", "_Header.txt", path.name, flags=re.IGNORECASE)
        if header_name == path.name:
            return ""
        return str(reactor_data_dir / "Text Files" / month_dir / header_name)

    def _update_header_txt_path(self, file_path: str):
        self._header_txt_path.set(self._predicted_header_txt_path(file_path))

    def _on_raw_file_path_changed(self, *_args):
        self._update_header_txt_path(self._file_path.get().strip())
        self._header_comparison_warning_var.set("")

    def _compare_header_text_file(self):
        self._header_comparison_warning_var.set("")
        raw_path = self._file_path.get().strip()
        header_path = self._header_txt_path.get().strip()
        if not raw_path or not os.path.isfile(raw_path) or not os.path.isfile(header_path):
            self._header_comparison_warning_var.set("Warning: select existing raw and header text files first.")
            return
        try:
            text_payload = parse_header_text(header_path)
            converted_path = save_converted_header(header_path, text_payload)
            raw_payload = read_header(raw_path)
            differences = compare_header_payloads(raw_payload, text_payload)
        except Exception as exc:
            self._header_comparison_warning_var.set(f"Header comparison warning: {exc}")
            return

        if differences:
            fields = ", ".join(differences)
            self._header_comparison_warning_var.set(
                f"Warning: header.txt differs from raw header ({fields}). Converted: {converted_path.name}"
            )
            self._show_header_diff_popup(raw_payload, text_payload, fields)
        else:
            self._header_comparison_warning_var.set(f"Headers match. Saved {converted_path.name}.")

    def _show_header_diff_popup(self, raw_payload: dict, text_payload: dict, fields: str):
        popup = tk.Toplevel(self)
        popup.title(f"Header Differences: {fields}")
        popup.geometry("1200x720")
        popup.transient(self)

        ttk.Label(
            popup,
            text="Different field: valveSequence",
            foreground="red",
        ).pack(anchor="w", padx=10, pady=(8, 4))

        panes = ttk.Frame(popup)
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(1, weight=1)
        ttk.Label(panes, text="Raw data JSON valve sequence").grid(row=0, column=0, sticky="w", padx=(0, 4))
        ttk.Label(panes, text="Header text valve sequence").grid(row=0, column=1, sticky="w", padx=(4, 0))

        left = scrolledtext.ScrolledText(panes, wrap="none", font=("Consolas", 9))
        right = scrolledtext.ScrolledText(panes, wrap="none", font=("Consolas", 9))
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 4))
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 0))
        left.tag_configure("changed", background="#ffd6d6")
        right.tag_configure("changed", background="#fff0b3")

        left_lines = normalized_header_text(raw_payload).splitlines()
        right_lines = normalized_header_text(text_payload).splitlines()
        matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
        left_row = 1
        right_row = 1

        def insert_line(widget, line, row, changed):
            start = f"{row}.0"
            widget.insert("end", line + "\n")
            if changed:
                widget.tag_add("changed", start, f"{row}.end")

        for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes():
            if operation == "equal":
                for left_line, right_line in zip(left_lines[left_start:left_end], right_lines[right_start:right_end]):
                    insert_line(left, left_line, left_row, False)
                    insert_line(right, right_line, right_row, False)
                    left_row += 1
                    right_row += 1
            else:
                left_chunk = left_lines[left_start:left_end]
                right_chunk = right_lines[right_start:right_end]
                for index in range(max(len(left_chunk), len(right_chunk))):
                    left_line = left_chunk[index] if index < len(left_chunk) else ""
                    right_line = right_chunk[index] if index < len(right_chunk) else ""
                    insert_line(left, left_line, left_row, bool(left_line))
                    insert_line(right, right_line, right_row, bool(right_line))
                    left_row += 1
                    right_row += 1

        left.configure(state="disabled")
        right.configure(state="disabled")
        ttk.Button(popup, text="Close", command=popup.destroy).pack(anchor="e", padx=10, pady=(0, 8))

    def _use_header_text_as_raw_header(self):
        raw_path = self._file_path.get().strip()
        header_path = self._header_txt_path.get().strip()
        if not raw_path or not os.path.isfile(raw_path) or not os.path.isfile(header_path):
            self._header_comparison_warning_var.set("Warning: select existing raw and header text files first.")
            return
        try:
            text_payload = parse_header_text(header_path)
            self._rewrite_header_payload(raw_path, text_payload)
        except Exception as exc:
            self._header_comparison_warning_var.set(f"Warning: could not replace raw header: {exc}")
            return

        self._header_comparison_warning_var.set("Raw data header replaced from header.txt.")
        self._load_header()

    def _browse_header_txt(self):
        path = filedialog.askopenfilename(
            title="Select Header Text File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self._header_txt_path.set(path)

    def _open_header_txt_location(self):
        self._open_path_in_explorer(self._header_txt_path.get(), "header text file")

    def _open_output_directory(self):
        self._open_path_in_explorer(self._output_dir.get(), "output directory")

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
            self._update_header_txt_path(path)
            self._load_header()

    def _browse_output(self):
        path = filedialog.askdirectory(title="Select Output Directory")
        if path:
            self._output_dir.set(path)

    def _browse_ise_file(self):
        path = filedialog.askopenfilename(
            title="Select iSE Data CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self._ise_file_path.set(path)

    def _browse_recipe_sheet(self):
        path = filedialog.askopenfilename(
            title="Select Recipe Sheet",
            filetypes=[("Excel files", "*.xlsx;*.xls"), ("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if path:
            self._recipe_sheet_path.set(path)
            self._recipe_output_path.set(str(Path(path).with_name(f"{Path(path).stem}_payload.json")))
            self._load_recipe_sheet_preview()

    def _open_raw_file_location(self):
        self._open_path_in_explorer(self._file_path.get(), "raw data file")

    def _open_ise_file_location(self):
        self._open_path_in_explorer(self._ise_file_path.get(), "iSE data file")

    def _open_recipe_file_location(self):
        target = self._recipe_output_path.get() or self._recipe_sheet_path.get()
        self._open_path_in_explorer(target, "recipe sheet")

    def _create_blank_recipe_sheet(self) -> Path:
        template_path = Path(__file__).with_name("Recipe sheet workbook format.xlsx")
        if not template_path.is_file():
            raise FileNotFoundError(f"Template workbook not found: {template_path.name}")

        tmp_file = tempfile.NamedTemporaryFile(
            prefix="reactor_blank_recipe_sheet_",
            suffix=".xlsx",
            delete=False,
        )
        tmp_file.close()

        shutil.copyfile(template_path, tmp_file.name)

        return Path(tmp_file.name)

    def _open_blank_recipe_sheet(self):
        try:
            template_path = self._create_blank_recipe_sheet()
        except Exception as exc:
            messagebox.showerror(
                "Open Blank Sheet",
                f"Could not create the blank recipe sheet:\n\n{exc}",
                parent=self,
            )
            return

        try:
            if hasattr(os, "startfile"):
                os.startfile(str(template_path))
            else:
                subprocess.Popen(["explorer", str(template_path)])
        except Exception as exc:
            messagebox.showerror(
                "Open Blank Sheet",
                f"Could not open the blank recipe sheet:\n\n{exc}",
                parent=self,
            )

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
            df = load_table(Path(path))
            exclude_falsey_edr_tags = self._exclude_falsey_edr_tags_var.get()
            calculated_name_report = build_output_filename_report(
                df,
                exclude_falsey_edr_tags=exclude_falsey_edr_tags,
            )
            calculated_username = calculated_name_report["sanitized"] if calculated_name_report else None
            payload = build_payload(
                df,
                username=calculated_username,
                exclude_falsey_edr_tags=exclude_falsey_edr_tags,
            )
        except PermissionError:
            self._recipe_payload = {}
            self._recipe_status_var.set("ERROR: The selected recipe sheet is open in another program.")
            self._recipe_validation_var.set("")
            self._recipe_username_warning_var.set("")
            self._create_payload_btn.configure(state="disabled")
            self._set_text_widget(
                self._recipe_preview_box,
                "Failed to load recipe sheet.\n\nThe file is open in another program. Close it and try again.",
            )
            return
        except Exception as exc:
            self._recipe_payload = {}
            self._recipe_status_var.set(f"ERROR: {exc}")
            self._recipe_validation_var.set("")
            self._recipe_username_warning_var.set("")
            self._create_payload_btn.configure(state="disabled")
            self._set_text_widget(self._recipe_preview_box, f"Failed to load recipe sheet.\n\n{exc}")
            return

        validation_errors = validate_recipe_sheet(df)
        if validation_errors:
            self._recipe_validation_var.set("\u26a0 " + "  \u2022  ".join(validation_errors))
            self._create_payload_btn.configure(state="disabled")
        else:
            self._recipe_validation_var.set("")
            self._create_payload_btn.configure(state="normal")

        if calculated_name_report and calculated_name_report.get("changed"):
            self._recipe_username_warning_var.set(
                "Warning: the payload username was sanitized for filename safety. "
                f"Saved value: {calculated_name_report['sanitized']}"
            )
        else:
            self._recipe_username_warning_var.set("")

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

        try:
            df = load_table(Path(path))
            exclude_falsey_edr_tags = self._exclude_falsey_edr_tags_var.get()
            report = build_output_filename_report(
                df,
                exclude_falsey_edr_tags=exclude_falsey_edr_tags,
            )
            payload = build_payload(
                df,
                username=report["sanitized"] if report else None,
                exclude_falsey_edr_tags=exclude_falsey_edr_tags,
            )
        except PermissionError:
            self._recipe_payload = {}
            self._recipe_status_var.set("ERROR: The selected recipe sheet is open in another program.")
            messagebox.showerror(
                "Create JSON Payload",
                "Failed to load recipe sheet.\n\nThe file is open in another program. Close it and try again.",
                parent=self,
            )
            return
        except Exception as exc:
            self._recipe_payload = {}
            self._recipe_status_var.set(f"ERROR: {exc}")
            messagebox.showerror("Create JSON Payload", f"Failed to load recipe sheet.\n\n{exc}", parent=self)
            return

        out_path = self._recipe_output_path.get().strip()
        if not out_path:
            out_path = str(Path(path).with_name(f"{Path(path).stem}_payload.json"))
            self._recipe_output_path.set(out_path)

        try:
            payload, saved_path = self._run_save_with_retry(
                lambda: (payload, save_payload(payload, out_path)),
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
        self._reactor_type = self._reactor_type_from_filename(path)
        if self._reactor_type is None:
            self._log(
                "ERROR: Filename must match "
                "YYMMDD_HHhMMm_ReactorType<tags>_ReactorN_Data.json "
                "or _Data_condensed.json "
                "with a configured ReactorType."
            )
            return
        self._clear_log()
        try:
            self._header_info = read_header(path)
        except Exception as e:
            self._log(f"ERROR reading header: {e}")
            return

        vs = self._header_info.get("valveSequence", [])
        self._seq_dict = convert_sequence(vs)

        self._log(f"Loading:  {path}")
        self._log(self._format_timing_table(self._seq_dict))
        for sk, sd in self._seq_dict.items():
            seen_v: list[str] = []
            seen_set: set[int] = set()
            for vnum, _ in sd.get("valve_rows", []):
                if vnum not in seen_set:
                    seen_set.add(vnum)
                    seen_v.append(f"valve{vnum}")
            self._log(f"  {sk}: {sd['cycles']} cycles -- {', '.join(seen_v)}")
        details_text = self._format_header_details(self._header_info.get("experimentalDetails", ""))
        if details_text:
            self._log(f"Details:\n{details_text}")
        self._log(f"Loaded:  {self._header_info.get('username', '')}")

        self._populate_valve_fields()
        self._apply_last_processing_settings()
        self._apply_saved_valve_names()
        self._apply_detail_valve_names(self._header_info.get("experimentalDetails", ""))
        self._apply_detail_wait_time(self._header_info.get("experimentalDetails", ""))
        self._process_btn.config(state="normal")
        self._preview_btn.config(state="normal")
        self._edit_header_btn.config(state="normal")

    def _rewrite_header_payload(self, file_path: str, payload: dict):
        path = Path(file_path)
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
        if not lines:
            raise ValueError("Raw data file is empty.")

        first = json.loads(lines[0])
        first["payload"] = payload
        updated_lines = [json.dumps(first, ensure_ascii=False) + "\n"]
        updated_lines.extend(lines[1:])

        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.writelines(updated_lines)

    def _edit_header(self):
        path = self._file_path.get().strip()
        if not path or not os.path.isfile(path):
            self._log("ERROR: Select a valid file first.")
            return
        if not self._header_info:
            try:
                self._header_info = read_header(path)
            except Exception as exc:
                messagebox.showerror("Edit Header", f"Could not load header:\n\n{exc}", parent=self)
                return

        edited = open_header_editor(self, self._header_info)
        if edited is None:
            return

        try:
            self._rewrite_header_payload(path, edited)
        except Exception as exc:
            messagebox.showerror("Edit Header", f"Could not save header:\n\n{exc}", parent=self)
            return

        self._log("Header updated.")
        self._load_header()

    def _populate_valve_fields(self):
        for w in self._valve_frame.winfo_children():
            w.destroy()

        # Collect unique valve numbers across all sequences.
        rows: list = []
        seen: set  = set()
        for seq_data in self._seq_dict.values():
            for vnum, _ in seq_data.get("valve_rows", []):
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
        self._valve_name_entries.clear()
        for vnum in sorted(rows):
            rf = ttk.Frame(self._valve_frame)
            rf.pack(fill="x", pady=1, padx=4)
            ttk.Label(rf, text=f"Valve {vnum}", width=10, anchor="w").grid(row=0, column=0, padx=4)
            var = tk.StringVar(value=str(vnum))
            entry = ttk.Entry(rf, textvariable=var, width=28)
            entry.grid(row=0, column=1, padx=4)
            self._valve_name_vars[vnum] = var
            self._valve_name_entries[vnum] = entry

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
        grid_x_spacing = self._get_float(self._grid_x_spacing_var)
        grid_y_spacing = self._get_float(self._grid_y_spacing_var)
        if grid_x_spacing is not None and grid_x_spacing <= 0:
            self._log("ERROR: X grid spacing must be greater than zero.")
            return
        if grid_y_spacing is not None and grid_y_spacing <= 0:
            self._log("ERROR: Y grid spacing must be greater than zero.")
            return
        shift       = self._get_float(self._shift_var)
        wait_time   = self._get_float(self._wait_var)
        leakrate_phase_reduction = max(
            0.0,
            self._get_float(self._leakrate_phase_reduction_var),
        )
        write_condensed_json = self._write_condensed_json_var.get()

        self._persist_processing_preferences(valve_names)

        self._process_btn.config(state="disabled")
        self._preview_btn.config(state="disabled")
        self._set_progress(0)

        threading.Thread(
            target=self._run_processing,
            args=(
                path,
                out_dir,
                valve_names,
                xlim,
                ylim,
                self._grid_x_var.get(),
                self._grid_y_var.get(),
                grid_x_spacing,
                grid_y_spacing,
                shift,
                wait_time,
                leakrate_phase_reduction,
                write_condensed_json,
            ),
            daemon=True,
        ).start()

    def _run_processing(
        self,
        path,
        out_dir,
        valve_names,
        xlim,
        ylim,
        grid_x,
        grid_y,
        grid_x_spacing,
        grid_y_spacing,
        shift,
        wait_time,
        leakrate_phase_reduction,
        write_condensed_json,
    ):
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
            details_payload = self._parse_experimental_details_payload(
                self._header_info.get("experimentalDetails", "")
            )
            if isinstance(details_payload, dict):
                valve_names = self._effective_valve_names(valve_names, details_payload)
                named_seq = apply_valve_names(self._seq_dict, valve_names)
                phased_seq = compute_phase_bins(named_seq, shift=shift)
                cyc_seq_map = make_cycle_seq_map(phased_seq)
                valve_name_payload = self._recipe_valve_name_payload(valve_names)
                if valve_name_payload:
                    details_payload = dict(details_payload)
                    details_payload["ValveNames"] = valve_name_payload

            self._append_valve_name_log(path, valve_names)

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

            condensed_future = None
            if write_condensed_json:
                # -- Write condensed log -----------------------------------------
                is_input_condensed = is_condensed_file(path)
                cpath = Path(path) if is_input_condensed else condensed_path(path)
                self._log("Writing condensed log...")
                condensed_executor = ThreadPoolExecutor(max_workers=1)
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

                    condensed_future = condensed_executor.submit(
                        lambda: self._run_save_with_retry(
                            lambda: condense_log(
                                path,
                                condensed_out,
                                phase_lookup=_phase_lookup,
                                return_stats=True,
                            ),
                            condensed_out,
                            "condensed log",
                        )
                    )
                except Exception:
                    condensed_executor.shutdown(wait=False, cancel_futures=True)
                    raise

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
                    all_phase_names, xlim_val, ylim_val,
                    grid_x=grid_x, grid_y=grid_y,
                    grid_x_spacing=grid_x_spacing,
                    grid_y_spacing=grid_y_spacing,
                    sequence_note=self._sequence_note_text(seq_key, phased_seq, details_payload),
                )

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

            try:
                stats = condensed_future.result() if condensed_future is not None else None
                if stats is not None:
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

            # -- Exposure CSV -----------------------------------------------------
            self._log("Computing phase exposures...")
            if leakrate_phase_reduction > 0:
                self._log(
                    f"  LeakRate phase reduction: {leakrate_phase_reduction:.3f} s on each side"
                )
            exp_rows = compute_exposure_table(
                cycles_sorted, cycle_points, cycle_start_map,
                phased_seq, cyc_seq_map, assign_phase,
                leakrate_phase_reduction=leakrate_phase_reduction,
            )
            csv_path = os.path.join(out_dir, f"{filename}_exposure.csv")
            self._run_save_with_retry(
                lambda: save_exposure_csv(exp_rows, out_dir, filename),
                csv_path,
                "exposure CSV",
            )
            self._log(f"  Exposure CSV: {Path(csv_path).name}  ({len(exp_rows)} rows)")

            # -- iSE thickness CSV -----------------------------------------------
            try:
                ise_path = self._ise_file_path.get().strip()
                if ise_path and Path(ise_path).is_file():
                    ise_src = Path(ise_path)
                    try:
                        thickness_blank_rows = max(0, int(self._thickness_blank_rows_var.get().strip() or "0"))
                    except ValueError:
                        thickness_blank_rows = 0
                    thickness_path = os.path.join(out_dir, f"{filename}_thickness.csv")
                    n_thickness = self._run_save_with_retry(
                        lambda: save_ise_thickness_csv(
                            ise_src,
                            thickness_path,
                            blank_rows=thickness_blank_rows,
                        ),
                        thickness_path,
                        "thickness CSV",
                    )
                    self._log(
                        f"  Thickness CSV: {Path(thickness_path).name} "
                        f"({n_thickness} rows from {ise_src.name})"
                    )
                else:
                    self._log("  Thickness CSV: skipped (select a valid iSE data file)")
            except SaveAbortedError:
                self._log("  Thickness CSV save cancelled.")
            except Exception as exc:
                self._log(f"  WARNING: could not extract iSE thickness CSV: {exc}")

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
                grid_x           = grid_x,
                grid_y           = grid_y,
                grid_x_spacing   = grid_x_spacing,
                grid_y_spacing   = grid_y_spacing,
                filename        = filename,
                out_dir         = out_dir,
                experimental_details = details_payload,
            )
        except SaveAbortedError as exc:
            self._log(f"Save cancelled: {exc}")
        except Exception as exc:
            self._log(f"Processing ERROR: {exc}")
        finally:
            try:
                if 'condensed_executor' in locals():
                    condensed_executor.shutdown(wait=True, cancel_futures=False)
            except Exception:
                pass
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

        fps = self._get_float(self._fps_var)
        if fps is None or fps <= 0:
            self._log("ERROR: Animation FPS must be greater than zero.")
            return

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
                    sequence_note_fn=lambda cycle, seq_key: self._sequence_note_text(seq_key or "", c["phased_seq"], c.get("experimental_details", {})),
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
        path = self._file_path.get().strip()
        if not path or not os.path.isfile(path) or not self._header_info:
            self._log("Load a valid data file and header before previewing.")
            return

        try:
            cycle = int(self._preview_cycle_var.get())
        except ValueError:
            self._log("ERROR: Preview cycle must be an integer.")
            return

        wait_time = self._get_float(self._wait_var) or 0.0
        xlim = self._get_float(self._xlim_var)
        ylim = self._get_float(self._ylim_var)
        grid_x_spacing = self._get_float(self._grid_x_spacing_var)
        grid_y_spacing = self._get_float(self._grid_y_spacing_var)
        leakrate_phase_reduction = max(
            0.0,
            self._get_float(self._leakrate_phase_reduction_var),
        )
        if grid_x_spacing is not None and grid_x_spacing <= 0:
            self._log("ERROR: X grid spacing must be greater than zero.")
            return
        if grid_y_spacing is not None and grid_y_spacing <= 0:
            self._log("ERROR: Y grid spacing must be greater than zero.")
            return

        self._process_btn.config(state="disabled")
        self._preview_btn.config(state="disabled")
        self._set_progress(0)
        threading.Thread(
            target=self._run_preview,
            args=(
                path, cycle, xlim, ylim,
                self._grid_x_var.get(), self._grid_y_var.get(),
                grid_x_spacing, grid_y_spacing, wait_time,
                leakrate_phase_reduction,
            ),
            daemon=True,
        ).start()

    def _run_preview(
        self, path, cycle, xlim, ylim, grid_x, grid_y,
        grid_x_spacing, grid_y_spacing, wait_time, leakrate_phase_reduction,
    ):
        try:
            valve_names = {vnum: var.get() for vnum, var in self._valve_name_vars.items()}
            named_seq = apply_valve_names(self._seq_dict, valve_names)
            shift = self._get_float(self._shift_var) or 0.0
            unshifted_seq = compute_phase_bins(named_seq, shift=0.0)
            phased_seq = compute_phase_bins(named_seq, shift=shift)
            cyc_seq_map = make_cycle_seq_map(phased_seq)
            details_payload = self._parse_experimental_details_payload(
                self._header_info.get("experimentalDetails", "")
            )
            if isinstance(details_payload, dict):
                valve_names = self._effective_valve_names(valve_names, details_payload)
                named_seq = apply_valve_names(self._seq_dict, valve_names)
                unshifted_seq = compute_phase_bins(named_seq, shift=0.0)
                phased_seq = compute_phase_bins(named_seq, shift=shift)
                cyc_seq_map = make_cycle_seq_map(phased_seq)

            self._log(f"Preview: reading cycle {cycle}...")

            def _prog(bytes_read, file_size):
                self._set_progress(bytes_read / file_size * 85)

            cycle_points, cycle_start_map = stream_pressure(
                path,
                wait_time=wait_time,
                progress_cb=_prog,
                target_cycle=cycle,
            )
            if cycle not in cycle_points:
                self._log(f"ERROR: Cycle {cycle} not found in the raw data.")
                return

            cycle_points, baseline = subtract_baseline(cycle_points)
            max_ct, max_p = compute_axis_limits(cycle_points, cycle_start_map)
            xlim_val = xlim if xlim else max_ct
            ylim_val = ylim if ylim else max_p
            all_phase_names = []
            for sequence_data in phased_seq.values():
                for phase_name in sequence_data.get("phase_names", []):
                    if phase_name not in all_phase_names:
                        all_phase_names.append(phase_name)
            phase_color_map = build_phase_color_map(all_phase_names)
            filename = Path(path).stem
            if filename.endswith("_condensed"):
                filename = filename[:-len("_condensed")]

            segs = build_segments(
                cycle, cycle_points, cycle_start_map,
                phased_seq, cyc_seq_map, assign_phase,
            )
            leakrate_regressions = compute_leakrate_regressions(
                cycle, cycle_points, cycle_start_map,
                phased_seq, cyc_seq_map, assign_phase,
                leakrate_phase_reduction,
            )
            fig = draw_cycle_figure(
                cycle, filename, segs, phase_color_map, all_phase_names,
                xlim_val, ylim_val,
                grid_x=grid_x, grid_y=grid_y,
                grid_x_spacing=grid_x_spacing,
                grid_y_spacing=grid_y_spacing,
                phase_background=unshifted_seq.get(
                    cyc_seq_map.get(cycle), {}
                ),
                leakrate_regressions=leakrate_regressions,
                sequence_note=self._sequence_note_text(
                    cyc_seq_map.get(cycle, ""), phased_seq, details_payload,
                ),
                figsize=(10, 7),
            )
            self._set_progress(100)
            self.after(0, lambda: self._open_preview_window(fig, cycle, [cycle], filename))
            self._log(f"Preview ready: cycle {cycle} ({len(cycle_points[cycle]):,} points, baseline {baseline:.2f} mTorr).")
        except Exception as exc:
            self._log(f"Preview ERROR: {exc}")
        finally:
            def _re_enable():
                self._process_btn.config(state="normal")
                self._preview_btn.config(state="normal")
            self.after(0, _re_enable)

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
