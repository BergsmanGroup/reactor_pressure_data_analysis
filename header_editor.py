"""
header_editor.py
----------------
Modal popup for editing the raw file header payload.
"""

from __future__ import annotations

import copy
import json
import tkinter as tk
from tkinter import ttk

DETAIL_FIELDS = [
    ("Info", "Info"),
    ("Wait time", "WaitTime"),
    ("EDR", "EDR"),
    ("DID", "DID"),
    ("SID", "SID"),
    ("EID", "EID"),
    ("PID", "PID"),
    ("Valve/precursor", "ValvePrecursor"),
    ("Name", "Name"),
    ("Temperature (C)", "TempC"),
    ("Substrate", "Substrate"),
    ("Preexisting layer", "PreexistingLayer"),
    ("Preexisting thickness", "PreexistingThickness"),
    ("Start time", "StartTime"),
    ("Process time (hr)", "ProcessTimeHr"),
    ("End time", "EndTime"),
]

LIST_FIELDS = {
    "DID",
    "SID",
    "EID",
    "PID",
    "ValvePrecursor",
    "Name",
    "TempC",
    "Substrate",
    "PreexistingLayer",
    "PreexistingThickness",
    "StartTime",
}

NUMERIC_FIELDS = {"WaitTime", "ProcessTimeHr"}
TABLE_COLUMNS = [
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


def _clean_text(value) -> str:
    return "" if value is None else str(value).strip()


def _coerce_token(token: str):
    token = _clean_text(token)
    if token == "":
        return ""
    upper = token.upper()
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False
    try:
        if any(ch in token for ch in (".", "e", "E")):
            number = float(token)
            return int(number) if number.is_integer() else number
        return int(token)
    except ValueError:
        return token


def _format_cell_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _parse_cell_value(text: str):
    text = _clean_text(text)
    if not text:
        return ""
    if "," in text:
        parts = [_clean_text(part) for part in text.split(",")]
        return [_coerce_token(part) for part in parts if part]
    return _coerce_token(text)


def _normalize_table(table_value) -> list[list[str]]:
    rows: list[list[str]] = []
    if not isinstance(table_value, list):
        return rows
    for row in table_value:
        if not isinstance(row, (list, tuple)):
            continue
        row_values = ["" if cell is None else str(cell) for cell in row[:9]]
        row_values.extend([""] * (9 - len(row_values)))
        if any(_clean_text(cell) for cell in row_values):
            rows.append(row_values)
    return rows


def _table_compare_value(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _normalize_table_for_compare(rows: list[list]) -> list[list[str]]:
    return [[_table_compare_value(cell) for cell in row] for row in rows]


def _extract_details(payload: dict):
    details = payload.get("experimentalDetails", "")
    if isinstance(details, dict):
        return True, copy.deepcopy(details)
    if isinstance(details, str):
        text = details.strip()
        if not text:
            return False, ""
        return False, text
    return False, details


class _ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")


class HeaderEditorDialog(tk.Toplevel):
    def __init__(self, parent, payload: dict):
        super().__init__(parent)
        self.title("Edit Header")
        self.transient(parent)
        self.grab_set()
        self.resizable(True, True)
        self.minsize(1020, 720)

        self.result: dict | None = None
        self._payload = copy.deepcopy(payload) if isinstance(payload, dict) else {}
        self._details_structured, self._details_value = _extract_details(self._payload)
        self._username_original = _clean_text(self._payload.get("username", ""))
        self._table_original = _normalize_table(self._payload.get("valveSequence", []))

        self._field_vars: dict[str, tk.StringVar] = {}
        self._field_widgets: dict[str, tk.Widget] = {}
        self._table_rows: list[dict] = []

        self._build_ui()
        self._populate_from_payload()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.bind("<Escape>", lambda _event: self._on_cancel())
        self.bind("<Control-s>", lambda _event: self._on_save())
        self.bind("<Command-s>", lambda _event: self._on_save())

        self.update_idletasks()
        self._center_over_parent(parent)

    def _center_over_parent(self, parent):
        try:
            self.update_idletasks()
            parent_x = parent.winfo_rootx()
            parent_y = parent.winfo_rooty()
            parent_w = parent.winfo_width()
            parent_h = parent.winfo_height()
            width = self.winfo_width()
            height = self.winfo_height()
            x = parent_x + max((parent_w - width) // 2, 0)
            y = parent_y + max((parent_h - height) // 2, 0)
            self.geometry(f"+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Header Editor", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="Edit header fields and timing rows. Save writes the updated header back to the raw file.",
        ).pack(anchor="w", pady=(0, 8))

        top_frame = ttk.LabelFrame(outer, text="Top-Level Header", padding=8)
        top_frame.pack(fill="x", pady=(0, 8))
        ttk.Label(top_frame, text="Username").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=3)
        self._username_var = tk.StringVar()
        ttk.Entry(top_frame, textvariable=self._username_var, width=80).grid(
            row=0, column=1, sticky="ew", pady=3
        )
        top_frame.columnconfigure(1, weight=1)

        details_frame = ttk.LabelFrame(outer, text="Experimental Details", padding=8)
        details_frame.pack(fill="x", pady=(0, 8))

        for idx, (label, key) in enumerate(DETAIL_FIELDS):
            row = idx // 2
            col = (idx % 2) * 2
            ttk.Label(details_frame, text=label).grid(row=row, column=col, sticky="w", padx=(0, 6), pady=3)
            if key == "Info":
                text = tk.Text(details_frame, height=5, width=52, wrap="word")
                text.grid(row=row, column=col + 1, sticky="ew", padx=(0, 10), pady=3)
                self._field_widgets[key] = text
            elif key == "EDR":
                var = tk.BooleanVar(value=False)
                self._field_vars[key] = var
                ttk.Checkbutton(details_frame, variable=var).grid(
                    row=row, column=col + 1, sticky="w", padx=(0, 10), pady=3
                )
            else:
                var = tk.StringVar()
                self._field_vars[key] = var
                ttk.Entry(details_frame, textvariable=var, width=40).grid(
                    row=row, column=col + 1, sticky="ew", padx=(0, 10), pady=3
                )
        details_frame.columnconfigure(1, weight=1)
        details_frame.columnconfigure(3, weight=1)

        table_frame = ttk.LabelFrame(outer, text="Timing Table", padding=8)
        table_frame.pack(fill="both", expand=True)

        toolbar = ttk.Frame(table_frame)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="Add Row", command=self._add_table_row).pack(side="left")
        ttk.Button(toolbar, text="Reset Rows", command=self._reset_table_rows).pack(side="left", padx=(6, 0))

        header_row = ttk.Frame(table_frame)
        header_row.pack(fill="x")
        for col_idx, title in enumerate(TABLE_COLUMNS + ["Action"]):
            ttk.Label(header_row, text=title, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=col_idx, padx=3, pady=2, sticky="w"
            )

        self._table_scroll = _ScrollableFrame(table_frame)
        self._table_scroll.pack(fill="both", expand=True)

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(8, 0))
        ttk.Button(button_row, text="Save", command=self._on_save).pack(side="right", padx=(6, 0))
        ttk.Button(button_row, text="Cancel", command=self._on_cancel).pack(side="right")

    def _populate_from_payload(self):
        self._username_var.set(self._username_original)

        info_widget = self._field_widgets["Info"]
        info_widget.delete("1.0", "end")
        if self._details_structured:
            info_widget.insert("1.0", _format_cell_value(self._details_value.get("Info", "")))
        else:
            info_widget.insert("1.0", _clean_text(self._details_value))

        details_dict = self._details_value if self._details_structured else {}
        for _label, key in DETAIL_FIELDS:
            if key == "Info":
                continue
            if key == "EDR":
                self._field_vars[key].set(bool(details_dict.get(key, False)) if self._details_structured else False)
                continue
            value = details_dict.get(key, "") if self._details_structured else ""
            self._field_vars[key].set(_format_cell_value(value))

        self._reset_table_rows()

    def _add_table_row(self, values: list[str] | None = None):
        values = list(values) if values else [""] * 9
        values.extend([""] * (9 - len(values)))
        row_frame = ttk.Frame(self._table_scroll.inner)
        row_frame.grid(row=len(self._table_rows), column=0, sticky="ew", pady=1)

        row_vars: list[tk.StringVar] = []
        for col_idx in range(9):
            var = tk.StringVar(value=values[col_idx])
            ttk.Entry(row_frame, textvariable=var, width=12).grid(row=0, column=col_idx, padx=2, sticky="ew")
            row_vars.append(var)
        ttk.Button(row_frame, text="Delete", command=lambda frame=row_frame: self._delete_table_row(frame)).grid(
            row=0, column=9, padx=(6, 2)
        )

        self._table_rows.append({"frame": row_frame, "vars": row_vars})
        self._reflow_table_rows()

    def _delete_table_row(self, frame):
        self._table_rows = [row for row in self._table_rows if row["frame"] is not frame]
        frame.destroy()
        self._reflow_table_rows()

    def _reflow_table_rows(self):
        for idx, row in enumerate(self._table_rows):
            row["frame"].grid_configure(row=idx)

    def _reset_table_rows(self):
        for row in self._table_rows:
            row["frame"].destroy()
        self._table_rows = []
        rows = self._table_original if self._table_original else []
        if not rows:
            self._add_table_row()
            return
        for row in rows:
            self._add_table_row(row)

    def _collect_table_rows(self) -> list[list]:
        rows: list[list] = []
        for row in self._table_rows:
            values = [var.get().strip() for var in row["vars"]]
            if not any(values):
                continue
            rows.append([_parse_cell_value(value) for value in values])
        return rows

    def _has_structured_edits(self) -> bool:
        if self._username_var.get().strip() != self._username_original:
            return True

        for _label, key in DETAIL_FIELDS:
            if key == "Info":
                continue
            if key == "EDR":
                current = bool(self._field_vars[key].get())
                original = bool(self._details_value.get(key, False)) if self._details_structured else False
                if current != original:
                    return True
                continue

            current_text = self._field_vars[key].get().strip()
            original_value = self._details_value.get(key, "") if self._details_structured else ""
            if current_text != _format_cell_value(original_value).strip():
                return True

        return False

    def _build_details_payload(self, structured: bool):
        info_text = self._field_widgets["Info"].get("1.0", "end").strip()
        if not structured:
            return info_text

        details: dict = {"Info": info_text}
        for _label, key in DETAIL_FIELDS:
            if key == "Info":
                continue
            if key == "EDR":
                details[key] = bool(self._field_vars[key].get())
                continue
            raw = self._field_vars[key].get().strip()
            if not raw:
                details[key] = [] if key in LIST_FIELDS else ""
            elif key in LIST_FIELDS:
                details[key] = [_coerce_token(part) for part in (_clean_text(chunk) for chunk in raw.split(",")) if part]
            else:
                details[key] = _parse_cell_value(raw)
        return details

    def _on_save(self):
        table_rows = self._collect_table_rows()
        structured = (
            self._details_structured
            or self._has_structured_edits()
            or _normalize_table_for_compare(table_rows) != self._table_original
        )
        payload = copy.deepcopy(self._payload)
        payload["username"] = self._username_var.get().strip()
        payload["experimentalDetails"] = self._build_details_payload(structured)
        payload["valveSequence"] = table_rows
        self.result = payload
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


def open_header_editor(parent, payload: dict):
    dialog = HeaderEditorDialog(parent, payload)
    parent.wait_window(dialog)
    return dialog.result
