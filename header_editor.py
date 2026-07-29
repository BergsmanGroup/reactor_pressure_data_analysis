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

DETAIL_SCALAR_FIELDS = [
    ("Info", "Info", "text"),
    ("Wait time", "WaitTime", "entry"),
    ("EDR", "EDR", "checkbox"),
    ("DID", "DID", "entry"),
    ("SID", "SID", "entry"),
    ("EID", "EID", "entry"),
    ("PID", "PID", "entry"),
]

DETAIL_TABLE_FIELDS = [
    ("Valve #", "ValvePrecursor"),
    ("Name", "Name"),
    ("Temperature (C)", "TempC"),
]

LIST_FIELDS = {"DID", "SID", "EID", "PID", "ValvePrecursor", "Name", "TempC"}

NUMERIC_FIELDS = {"WaitTime", "ProcessTimeHr"}
TIMING_COLUMNS = [
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


def _parse_list_text(text: str) -> list:
    text = _clean_text(text)
    if not text:
        return []
    return [_coerce_token(part) for part in (_clean_text(chunk) for chunk in text.split(",")) if part]


def _list_to_text(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


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


def _normalize_list_value(value) -> list[str]:
    if isinstance(value, list):
        return ["" if cell is None else str(cell) for cell in value]
    if value in (None, ""):
        return []
    return [str(value)]


def _list_item(value, index: int) -> str:
    items = _normalize_list_value(value)
    if 0 <= index < len(items):
        return items[index]
    return ""


def _pad_list(values: list[str], size: int) -> list[str]:
    padded = list(values)
    if len(padded) < size:
        padded.extend([""] * (size - len(padded)))
    return padded[:size]


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
        self._win_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win_id, width=e.width))
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
        if isinstance(self._details_value, dict):
            self._details_original = copy.deepcopy(self._details_value)
        elif isinstance(self._details_value, str):
            _text = self._details_value.strip()
            try:
                _parsed = json.loads(_text) if _text else {}
                self._details_original = _parsed if isinstance(_parsed, dict) else {"Info": _text}
            except (json.JSONDecodeError, ValueError):
                self._details_original = {"Info": _text}
        else:
            self._details_original = {}

        self._field_vars: dict[str, tk.StringVar] = {}
        self._field_widgets: dict[str, tk.Widget] = {}
        self._detail_table_vars: list[dict[str, tk.StringVar]] = []
        self._table_rows: list[dict] = []
        self._selected_table_row: int | None = None

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

        self._build_experimental_details(details_frame)

        table_frame = ttk.LabelFrame(outer, text="Timing Table", padding=8)
        table_frame.pack(fill="both", expand=True)
        self._build_timing_table(table_frame)

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(8, 0))
        ttk.Button(button_row, text="Save", command=self._on_save).pack(side="right", padx=(6, 0))
        ttk.Button(button_row, text="Cancel", command=self._on_cancel).pack(side="right")

    def _build_experimental_details(self, parent):
        form = ttk.Frame(parent)
        form.pack(fill="x")

        ttk.Label(form, text="Info").grid(row=0, column=0, sticky="nw", padx=(0, 6), pady=3)
        self._field_widgets["Info"] = tk.Text(form, height=5, width=72, wrap="word")
        self._field_widgets["Info"].grid(row=0, column=1, columnspan=3, sticky="ew", pady=3)

        row = 1
        for left_label, left_key, left_kind, right_label, right_key, right_kind in [
            ("Wait time", "WaitTime", "entry", "EDR", "EDR", "checkbox"),
            ("DID", "DID", "entry", "SID", "SID", "entry"),
            ("EID", "EID", "entry", "PID", "PID", "entry"),
        ]:
            ttk.Label(form, text=left_label).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=3)
            self._field_vars[left_key] = tk.BooleanVar(value=False) if left_kind == "checkbox" else tk.StringVar()
            if left_kind == "checkbox":
                ttk.Checkbutton(form, variable=self._field_vars[left_key]).grid(row=row, column=1, sticky="w", pady=3)
            else:
                ttk.Entry(form, textvariable=self._field_vars[left_key], width=28).grid(
                    row=row, column=1, sticky="ew", pady=3
                )

            ttk.Label(form, text=right_label).grid(row=row, column=2, sticky="w", padx=(16, 6), pady=3)
            self._field_vars[right_key] = tk.BooleanVar(value=False) if right_kind == "checkbox" else tk.StringVar()
            if right_kind == "checkbox":
                ttk.Checkbutton(form, variable=self._field_vars[right_key]).grid(row=row, column=3, sticky="w", pady=3)
            else:
                ttk.Entry(form, textvariable=self._field_vars[right_key], width=28).grid(
                    row=row, column=3, sticky="ew", pady=3
                )
            row += 1

        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        table_frame = ttk.LabelFrame(parent, text="Valve Metadata", padding=8)
        table_frame.pack(fill="x", pady=(8, 0))
        valve_toolbar = ttk.Frame(table_frame)
        valve_toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(valve_toolbar, text="Add Column", command=self._insert_detail_column).pack(side="left")
        self._detail_table_frame = ttk.Frame(table_frame)
        self._detail_table_frame.pack(fill="x")

    def _build_timing_table(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(toolbar, text="Add Row", command=self._add_table_row).pack(side="left")
        ttk.Button(toolbar, text="Reset Rows", command=self._reset_table_rows).pack(side="left", padx=(6, 0))

        self._table_scroll = _ScrollableFrame(parent)
        self._table_scroll.pack(fill="both", expand=True)

        # Header labels live in the same grid as data entries — guarantees alignment.
        for col_idx, title in enumerate(TIMING_COLUMNS):
            ttk.Label(
                self._table_scroll.inner,
                text=title,
                font=("Segoe UI", 9, "bold"),
                anchor="center",
            ).grid(row=0, column=col_idx, padx=2, pady=(2, 4), sticky="ew")

        for col_idx in range(len(TIMING_COLUMNS)):
            self._table_scroll.inner.columnconfigure(col_idx, weight=1, uniform="timing")

    def _initial_detail_table_values(self) -> list[dict[str, tk.StringVar]]:
        details = self._details_original if isinstance(self._details_original, dict) else {}
        column_count = 3
        for _label, key in DETAIL_TABLE_FIELDS:
            column_count = max(column_count, len(_normalize_list_value(details.get(key, []))))

        columns: list[dict[str, tk.StringVar]] = []
        for index in range(column_count):
            column: dict[str, tk.StringVar] = {}
            for _label, key in DETAIL_TABLE_FIELDS:
                column[key] = tk.StringVar(value=_list_item(details.get(key, []), index))
            columns.append(column)
        return columns

    def _render_detail_table(self):
        for child in self._detail_table_frame.winfo_children():
            child.destroy()

        if not self._detail_table_vars:
            self._detail_table_vars = self._initial_detail_table_values()

        ttk.Label(self._detail_table_frame, text="").grid(row=0, column=0, padx=3, pady=2, sticky="w")
        for col_idx, column_vars in enumerate(self._detail_table_vars):
            tk.Button(
                self._detail_table_frame,
                text="\u2715",
                fg="red",
                relief="flat",
                bd=0,
                padx=2,
                cursor="hand2",
                command=lambda idx=col_idx: self._delete_detail_column(idx),
            ).grid(row=0, column=col_idx + 1, padx=3, pady=2)

        for row_idx, (label, key) in enumerate(DETAIL_TABLE_FIELDS, start=1):
            ttk.Label(self._detail_table_frame, text=label).grid(row=row_idx, column=0, sticky="w", padx=(0, 6), pady=3)
            for col_idx, column_vars in enumerate(self._detail_table_vars):
                entry = ttk.Entry(self._detail_table_frame, textvariable=column_vars[key], width=9)
                entry.grid(row=row_idx, column=col_idx + 1, sticky="ew", padx=3, pady=3)

        for col_idx in range(len(self._detail_table_vars) + 1):
            self._detail_table_frame.columnconfigure(col_idx, weight=1 if col_idx > 0 else 0, uniform="detail_table")

    def _insert_detail_column(self, index: int | None = None, values: dict | None = None):
        index = len(self._detail_table_vars) if index is None else max(0, min(index, len(self._detail_table_vars)))
        values = values if isinstance(values, dict) else {}
        column: dict[str, tk.StringVar] = {}
        for _label, key in DETAIL_TABLE_FIELDS:
            column[key] = tk.StringVar(value=_clean_text(values.get(key, "")))
        self._detail_table_vars.insert(index, column)
        self._render_detail_table()

    def _delete_detail_column(self, index: int):
        if not (0 <= index < len(self._detail_table_vars)):
            return
        if len(self._detail_table_vars) <= 1:
            for column in self._detail_table_vars:
                for var in column.values():
                    var.set("")
            self._render_detail_table()
            return
        del self._detail_table_vars[index]
        self._render_detail_table()

    def _populate_details_fields(self):
        details = self._details_original if isinstance(self._details_original, dict) else {}

        self._field_widgets["Info"].delete("1.0", "end")
        self._field_widgets["Info"].insert("1.0", _clean_text(details.get("Info", "")))

        self._field_vars["WaitTime"].set(_list_to_text(details.get("WaitTime", "")))
        self._field_vars["EDR"].set(bool(details.get("EDR", False)))
        for key in ("DID", "SID", "EID", "PID"):
            self._field_vars[key].set(_list_to_text(details.get(key, [])))

        self._detail_table_vars = self._initial_detail_table_values()
        self._render_detail_table()

    def _populate_from_payload(self):
        self._username_var.set(self._username_original)
        self._populate_details_fields()
        self._reset_table_rows()

    def _select_timing_row(self, index: int):
        self._selected_table_row = index

    def _rebuild_timing_rows(self, rows: list[list[str]]):
        for row in self._table_rows:
            for widget in row["widgets"]:
                widget.destroy()
        self._table_rows = []

        for index, values in enumerate(rows):
            self._add_table_row(values, insert_index=index, rebuild=False)
        if not self._table_rows:
            self._add_table_row(rebuild=False)

    def _add_table_row(self, values: list[str] | None = None, insert_index: int | None = None, rebuild: bool = True):
        current_rows = [
            [var.get() for var in row["vars"]]
            for row in self._table_rows
        ] if rebuild else []

        if rebuild:
            if insert_index is None:
                insert_at = (
                    self._selected_table_row + 1
                    if self._selected_table_row is not None
                    else len(current_rows)
                )
            else:
                insert_at = max(0, min(insert_index, len(current_rows)))
            row_values = ["" for _ in range(len(TIMING_COLUMNS))] if values is None else list(values)
            row_values.extend([""] * (len(TIMING_COLUMNS) - len(row_values)))
            current_rows.insert(insert_at, row_values[:len(TIMING_COLUMNS)])
            self._rebuild_timing_rows(current_rows)
            self._selected_table_row = insert_at
            return

        row_index = len(self._table_rows) if insert_index is None else insert_index
        grid_row = row_index + 1  # row 0 is the header
        row_values = ["" for _ in range(len(TIMING_COLUMNS))] if values is None else list(values)
        row_values.extend([""] * (len(TIMING_COLUMNS) - len(row_values)))

        row_vars: list[tk.StringVar] = []
        row_widgets: list = []

        for col_idx in range(len(TIMING_COLUMNS)):
            var = tk.StringVar(value=row_values[col_idx])
            entry = ttk.Entry(self._table_scroll.inner, textvariable=var, width=12)
            entry.grid(row=grid_row, column=col_idx, padx=2, pady=1, sticky="ew")
            entry.bind("<FocusIn>", lambda _event, idx=row_index: self._select_timing_row(idx))
            entry.bind("<Button-1>", lambda _event, idx=row_index: self._select_timing_row(idx))
            row_vars.append(var)
            row_widgets.append(entry)

        del_btn = tk.Button(
            self._table_scroll.inner,
            text="\u2715",
            fg="red",
            relief="flat",
            bd=0,
            padx=2,
            cursor="hand2",
            command=lambda idx=row_index: self._delete_table_row(idx),
        )
        del_btn.grid(row=grid_row, column=len(TIMING_COLUMNS), padx=(4, 2), pady=1)
        row_widgets.append(del_btn)

        self._table_rows.append({"vars": row_vars, "widgets": row_widgets})
        self._reflow_table_rows()

    def _delete_table_row(self, index: int):
        if not (0 <= index < len(self._table_rows)):
            return
        current_rows = [
            [var.get() for var in row["vars"]]
            for row in self._table_rows
        ]
        del current_rows[index]
        self._rebuild_timing_rows(current_rows)
        self._selected_table_row = min(index, len(self._table_rows) - 1) if self._table_rows else None

    def _reflow_table_rows(self):
        for idx, row in enumerate(self._table_rows):
            grid_row = idx + 1
            for widget in row["widgets"]:
                widget.grid_configure(row=grid_row)

    def _reset_table_rows(self):
        rows = self._table_original if self._table_original else []
        self._selected_table_row = None
        self._rebuild_timing_rows(rows)

    def _collect_table_rows(self) -> list[list]:
        rows: list[list] = []
        for row in self._table_rows:
            values = [var.get().strip() for var in row["vars"]]
            if not any(values):
                continue
            rows.append([_parse_cell_value(value) for value in values])
        return rows

    def _detail_table_payload(self) -> dict:
        payload: dict[str, list] = {}
        for _label, key in DETAIL_TABLE_FIELDS:
            values = [column[key].get().strip() for column in self._detail_table_vars]
            if any(values):
                payload[key] = [_parse_cell_value(value) for value in values]
            else:
                payload[key] = []
        return payload

    def _build_details_payload(self):
        details = copy.deepcopy(self._details_original) if isinstance(self._details_original, dict) else {}
        details["Info"] = self._field_widgets["Info"].get("1.0", "end").strip()
        wait_time = self._field_vars["WaitTime"].get().strip()
        details["WaitTime"] = _parse_cell_value(wait_time) if wait_time else ""
        details["EDR"] = bool(self._field_vars["EDR"].get())
        for key in ("DID", "SID", "EID", "PID"):
            details[key] = _parse_list_text(self._field_vars[key].get())
        details.update(self._detail_table_payload())
        return details

    def _on_save(self):
        payload = copy.deepcopy(self._payload)
        payload["username"] = self._username_var.get().strip()
        payload["experimentalDetails"] = self._build_details_payload()
        payload["valveSequence"] = self._collect_table_rows()
        self.result = payload
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


def open_header_editor(parent, payload: dict):
    dialog = HeaderEditorDialog(parent, payload)
    parent.wait_window(dialog)
    return dialog.result
