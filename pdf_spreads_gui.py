"""
PDF Spreads Creator — GUI Version
Combines consecutive PDF pages into 2-page spreads.
Supports multiple spread ranges via an inline editor or a JSON config file.
"""

import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from pypdf import PdfReader, PdfWriter, PageObject, Transformation


# ─────────────────────────────────────────────
#  Core processing logic (unchanged algorithm)
# ─────────────────────────────────────────────

def _visible_box(page):
    """
    Return the true visible rectangle of a page as (left, bottom, right, top) floats.

    Many manga/tankobon PDFs store a cropbox inset inside the mediabox to hide
    bleed or binding margins. Using mediabox dimensions for placement causes the
    invisible margin to appear as a gap between pages in a spread. This function
    returns the intersection of the mediabox and cropbox — the region that is
    actually rendered and visible to a reader.
    """
    mb = page.mediabox
    cb = page.cropbox
    left   = max(float(mb.left),   float(cb.left))
    bottom = max(float(mb.bottom), float(cb.bottom))
    right  = min(float(mb.right),  float(cb.right))
    top    = min(float(mb.top),    float(cb.top))
    return left, bottom, right, top


def _merge_spread(page_a, page_b, rtl=False):
    """
    Merge two pages side-by-side into a new spread PageObject.

    Sizes and positions each page using its *visible* (cropped) area rather than
    its full mediabox, so bleed margins in manga/tankobon PDFs do not create gaps
    or misalignment between the two halves of the spread.

    :param page_a: The page that will appear on the LEFT of the spread canvas.
    :param page_b: The page that will appear on the RIGHT of the spread canvas.
    :param rtl:    Informational only — caller swaps page_a/page_b for RTL order.
    :returns:      A new PageObject containing both pages placed side by side.
    """
    # Determine the visible rectangle for each page (crop-aware)
    a_left, a_bottom, a_right, a_top = _visible_box(page_a)
    b_left, b_bottom, b_right, b_top = _visible_box(page_b)

    a_width  = a_right  - a_left
    a_height = a_top    - a_bottom
    b_width  = b_right  - b_left
    b_height = b_top    - b_bottom

    spread_width  = a_width + b_width
    spread_height = max(a_height, b_height)

    spread_page = PageObject.create_blank_page(width=spread_width, height=spread_height)

    # ── Left page ──────────────────────────────────────────────────────────
    # Translate so the page's visible top-left aligns with (0, spread_height).
    # The tx cancels any cropbox left-offset; ty aligns tops when pages differ
    # in height.
    tx_a = -a_left
    ty_a = spread_height - a_top
    page_a.add_transformation(Transformation().translate(tx=tx_a, ty=ty_a))
    page_a.mediabox.lower_left  = (0,       spread_height - a_height)
    page_a.mediabox.upper_right = (a_width, spread_height)
    page_a.cropbox.lower_left   = (0,       spread_height - a_height)
    page_a.cropbox.upper_right  = (a_width, spread_height)
    spread_page.merge_page(page_a)

    # ── Right page ─────────────────────────────────────────────────────────
    # Translate so the page's visible top-left aligns with (a_width, spread_height).
    tx_b = a_width - b_left
    ty_b = spread_height - b_top
    page_b.add_transformation(Transformation().translate(tx=tx_b, ty=ty_b))
    page_b.mediabox.lower_left  = (a_width,           spread_height - b_height)
    page_b.mediabox.upper_right = (a_width + b_width, spread_height)
    page_b.cropbox.lower_left   = (a_width,           spread_height - b_height)
    page_b.cropbox.upper_right  = (a_width + b_width, spread_height)
    spread_page.merge_page(page_b)

    return spread_page


def create_pdf_spreads(input_path, output_path, spread_ranges, log_fn=print):
    """
    Combines consecutive pages of a PDF into 2-page spreads for each range.

    :param input_path:    Path to the original PDF.
    :param output_path:   Path to save the new spread PDF.
    :param spread_ranges: List of dicts with keys:
                            'start_page' (int, 1-based, inclusive)
                            'end_page'   (int, 1-based, inclusive)
                            'rtl'        (bool, optional) — if True, each pair
                                         is placed with the HIGHER-numbered page
                                         on the left (manga / right-to-left order)
                          e.g.: [{"start_page": 3, "end_page": 10, "rtl": true}]
    :param log_fn:        Callable for status messages.
    """
    reader = PdfReader(input_path)
    total_pages = len(reader.pages)
    writer = PdfWriter()

    # Build a map: page_index (0-based) → range_index
    spread_map = {}
    for ri, r in enumerate(spread_ranges):
        start = max(0, r["start_page"] - 1)
        end   = min(total_pages, r["end_page"])   # exclusive upper bound
        for pi in range(start, end):
            spread_map[pi] = ri

    i = 0
    while i < total_pages:
        if i in spread_map:
            ri        = spread_map[i]
            range_end = spread_ranges[ri]["end_page"]   # exclusive
            rtl       = bool(spread_ranges[ri].get("rtl", False))

            first_page = reader.pages[i]

            if i + 1 < range_end and (i + 1) in spread_map:
                second_page = reader.pages[i + 1]

                if rtl:
                    # Right-to-left: higher page number goes on the LEFT
                    spread_page = _merge_spread(second_page, first_page, rtl=True)
                    log_fn(f"  Spread (RTL/manga): page {i+2} ← | → {i+1}")
                else:
                    # Standard left-to-right
                    spread_page = _merge_spread(first_page, second_page, rtl=False)
                    log_fn(f"  Spread (LTR): pages {i+1} + {i+2}")

                writer.add_page(spread_page)
                i += 2
            else:
                # Odd page at the end of a range — pass through unchanged
                writer.add_page(first_page)
                log_fn(f"  Single page (end of range): {i+1}")
                i += 1
        else:
            writer.add_page(reader.pages[i])
            log_fn(f"  Pass-through: page {i+1}")
            i += 1

    with open(output_path, "wb") as f:
        writer.write(f)

    log_fn(f"\n✓ Done! Output saved to:\n  {output_path}")


# ─────────────────────────────────────────────
#  GUI
# ─────────────────────────────────────────────

DARK_BG   = "#1e1e2e"
PANEL_BG  = "#2a2a3e"
ACCENT    = "#7c6af7"       # violet
ACCENT2   = "#a78bfa"
TEXT_MAIN = "#e2e0f0"
TEXT_DIM  = "#8882b0"
SUCCESS   = "#4ade80"
ERROR     = "#f87171"
MONO_FONT = ("Courier New", 10)
SANS_FONT = ("Segoe UI", 10)
HEAD_FONT = ("Segoe UI", 13, "bold")


class PDFSpreadsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF Spreads Creator")
        self.configure(bg=DARK_BG)
        self.resizable(True, True)
        self.minsize(780, 600)

        self._build_ui()
        self._center_window(900, 680)

    # ── Layout ──────────────────────────────

    def _build_ui(self):
        # ── Header bar
        hdr = tk.Frame(self, bg=ACCENT, pady=10)
        hdr.pack(fill="x")
        tk.Label(
            hdr, text="PDF Spreads Creator",
            bg=ACCENT, fg="white",
            font=("Segoe UI", 16, "bold"), padx=18
        ).pack(side="left")
        tk.Label(
            hdr, text="Combine pages into side-by-side spreads",
            bg=ACCENT, fg="#d0c8ff",
            font=("Segoe UI", 10), padx=4
        ).pack(side="left")

        # ── Two-column body
        body = tk.Frame(self, bg=DARK_BG)
        body.pack(fill="both", expand=True, padx=16, pady=12)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(1, weight=1)

        # Left column — file paths + ranges table
        left = tk.Frame(body, bg=DARK_BG)
        left.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 8))
        left.rowconfigure(3, weight=1)
        left.columnconfigure(0, weight=1)

        self._build_file_section(left)
        self._build_ranges_section(left)

        # Right column — JSON editor + log
        right = tk.Frame(body, bg=DARK_BG)
        right.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(8, 0))
        right.rowconfigure(1, weight=1)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_json_section(right)
        self._build_log_section(right)

        # ── Bottom bar
        bar = tk.Frame(self, bg=PANEL_BG, pady=10)
        bar.pack(fill="x", side="bottom")
        self._btn(bar, "▶  Process PDF", self._run, bg=ACCENT, fg="white", padx=24).pack(side="right", padx=16)
        self._btn(bar, "Clear log", self._clear_log, bg=PANEL_BG, fg=TEXT_DIM).pack(side="right", padx=4)

    def _build_file_section(self, parent):
        self._section_label(parent, "Files").grid(row=0, column=0, sticky="w", pady=(0, 4))

        grid = tk.Frame(parent, bg=DARK_BG)
        grid.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        grid.columnconfigure(1, weight=1)

        # Input PDF
        tk.Label(grid, text="Input PDF", bg=DARK_BG, fg=TEXT_DIM, font=SANS_FONT).grid(row=0, column=0, sticky="w", pady=3, padx=(0, 8))
        self.input_var = tk.StringVar()
        self._entry(grid, self.input_var).grid(row=0, column=1, sticky="ew")
        self._btn(grid, "Browse…", self._browse_input).grid(row=0, column=2, padx=(6, 0))

        # Output PDF
        tk.Label(grid, text="Output PDF", bg=DARK_BG, fg=TEXT_DIM, font=SANS_FONT).grid(row=1, column=0, sticky="w", pady=3, padx=(0, 8))
        self.output_var = tk.StringVar()
        self._entry(grid, self.output_var).grid(row=1, column=1, sticky="ew")
        self._btn(grid, "Browse…", self._browse_output).grid(row=1, column=2, padx=(6, 0))

        # JSON config
        tk.Label(grid, text="JSON Config", bg=DARK_BG, fg=TEXT_DIM, font=SANS_FONT).grid(row=2, column=0, sticky="w", pady=3, padx=(0, 8))
        self.json_path_var = tk.StringVar()
        self._entry(grid, self.json_path_var).grid(row=2, column=1, sticky="ew")
        self._btn(grid, "Load…", self._load_json_file).grid(row=2, column=2, padx=(6, 0))

    def _build_ranges_section(self, parent):
        lbl_row = tk.Frame(parent, bg=DARK_BG)
        lbl_row.grid(row=2, column=0, sticky="ew", pady=(4, 4))
        self._section_label(lbl_row, "Spread Ranges").pack(side="left")
        tk.Label(lbl_row, text="(1-based page numbers, end inclusive)",
                 bg=DARK_BG, fg=TEXT_DIM, font=("Segoe UI", 8)).pack(side="left", padx=8)

        # Treeview table
        frame = tk.Frame(parent, bg=PANEL_BG, bd=0, relief="flat")
        frame.grid(row=3, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Dark.Treeview",
                        background=PANEL_BG, foreground=TEXT_MAIN,
                        fieldbackground=PANEL_BG, rowheight=26,
                        font=SANS_FONT)
        style.configure("Dark.Treeview.Heading",
                        background=DARK_BG, foreground=ACCENT2,
                        font=("Segoe UI", 9, "bold"), relief="flat")
        style.map("Dark.Treeview", background=[("selected", ACCENT)])

        self.tree = ttk.Treeview(
            frame, style="Dark.Treeview",
            columns=("start", "end", "dir"), show="headings", height=8
        )
        self.tree.heading("start", text="Start Page")
        self.tree.heading("end",   text="End Page")
        self.tree.heading("dir",   text="Direction")
        self.tree.column("start", width=90,  anchor="center")
        self.tree.column("end",   width=90,  anchor="center")
        self.tree.column("dir",   width=110, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

        # Row edit/add controls
        ctrl = tk.Frame(parent, bg=DARK_BG)
        ctrl.grid(row=4, column=0, sticky="ew", pady=(6, 0))

        tk.Label(ctrl, text="Start:", bg=DARK_BG, fg=TEXT_DIM, font=SANS_FONT).pack(side="left")
        self.start_entry = self._small_entry(ctrl, width=6)
        self.start_entry.pack(side="left", padx=(2, 8))

        tk.Label(ctrl, text="End:", bg=DARK_BG, fg=TEXT_DIM, font=SANS_FONT).pack(side="left")
        self.end_entry = self._small_entry(ctrl, width=6)
        self.end_entry.pack(side="left", padx=(2, 8))

        # RTL (manga) toggle
        self.rtl_var = tk.BooleanVar(value=False)
        rtl_cb = tk.Checkbutton(
            ctrl, text="RTL (manga)", variable=self.rtl_var,
            bg=DARK_BG, fg=TEXT_MAIN, selectcolor=PANEL_BG,
            activebackground=DARK_BG, activeforeground=ACCENT2,
            font=SANS_FONT, cursor="hand2", bd=0, relief="flat"
        )
        rtl_cb.pack(side="left", padx=(0, 8))

        self._btn(ctrl, "Add",    self._add_range,    bg=ACCENT, fg="white").pack(side="left", padx=2)
        self._btn(ctrl, "Update", self._update_range, bg=PANEL_BG, fg=ACCENT2).pack(side="left", padx=2)
        self._btn(ctrl, "Delete", self._delete_range, bg=PANEL_BG, fg=ERROR).pack(side="left", padx=2)

        self.tree.bind("<<TreeviewSelect>>", self._on_row_select)

    def _build_json_section(self, parent):
        lbl_row = tk.Frame(parent, bg=DARK_BG)
        lbl_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._section_label(lbl_row, "JSON Editor").pack(side="left")
        self._btn(lbl_row, "↑ Table → JSON", self._table_to_json, bg=PANEL_BG, fg=ACCENT2).pack(side="right")
        self._btn(lbl_row, "↓ JSON → Table", self._json_to_table, bg=PANEL_BG, fg=ACCENT2).pack(side="right", padx=4)
        self._btn(lbl_row, "Save JSON…",     self._save_json_file, bg=PANEL_BG, fg=TEXT_DIM).pack(side="right", padx=4)

        txt_frame = tk.Frame(parent, bg=PANEL_BG)
        txt_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        txt_frame.rowconfigure(0, weight=1)
        txt_frame.columnconfigure(0, weight=1)

        self.json_text = tk.Text(
            txt_frame, bg=PANEL_BG, fg=TEXT_MAIN,
            insertbackground=ACCENT2, selectbackground=ACCENT,
            font=MONO_FONT, wrap="none", bd=0,
            relief="flat", padx=8, pady=6
        )
        self.json_text.grid(row=0, column=0, sticky="nsew")

        json_sb = ttk.Scrollbar(txt_frame, orient="vertical", command=self.json_text.yview)
        self.json_text.configure(yscrollcommand=json_sb.set)
        json_sb.grid(row=0, column=1, sticky="ns")

        # Default template
        self.json_text.insert("1.0", json.dumps(
            [{"start_page": 1, "end_page": 4, "rtl": False}], indent=2
        ))

    def _build_log_section(self, parent):
        self._section_label(parent, "Log").grid(row=2, column=0, sticky="w", pady=(0, 4))

        log_frame = tk.Frame(parent, bg=PANEL_BG)
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            log_frame, bg="#12121e", fg=TEXT_MAIN,
            insertbackground=ACCENT2, selectbackground=ACCENT,
            font=MONO_FONT, wrap="word", state="disabled",
            bd=0, relief="flat", padx=8, pady=6
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.tag_config("success", foreground=SUCCESS)
        self.log_text.tag_config("error",   foreground=ERROR)
        self.log_text.tag_config("dim",     foreground=TEXT_DIM)

        log_sb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        log_sb.grid(row=0, column=1, sticky="ns")

    # ── Helpers ──────────────────────────────

    def _section_label(self, parent, text):
        return tk.Label(parent, text=text.upper(),
                        bg=DARK_BG, fg=ACCENT2,
                        font=("Segoe UI", 8, "bold"), pady=0)

    def _entry(self, parent, var):
        return tk.Entry(parent, textvariable=var,
                        bg=PANEL_BG, fg=TEXT_MAIN,
                        insertbackground=ACCENT2,
                        relief="flat", font=SANS_FONT, bd=4)

    def _small_entry(self, parent, width=8):
        e = tk.Entry(parent, width=width,
                     bg=PANEL_BG, fg=TEXT_MAIN,
                     insertbackground=ACCENT2,
                     relief="flat", font=SANS_FONT, bd=4)
        return e

    def _btn(self, parent, text, cmd, bg=PANEL_BG, fg=TEXT_MAIN, padx=10, pady=5):
        return tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=fg, activebackground=ACCENT, activeforeground="white",
            relief="flat", font=SANS_FONT, cursor="hand2",
            padx=padx, pady=pady, bd=0
        )

    def _center_window(self, w, h):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── File browsing ─────────────────────────

    def _browse_input(self):
        path = filedialog.askopenfilename(
            title="Select input PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if path:
            self.input_var.set(path)
            # Auto-suggest output path
            if not self.output_var.get():
                base, _ = os.path.splitext(path)
                self.output_var.set(base + "_spreads.pdf")

    def _browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Save output PDF as",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if path:
            self.output_var.set(path)

    def _load_json_file(self):
        path = filedialog.askopenfilename(
            title="Load JSON config",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.json_path_var.set(path)
            try:
                with open(path) as f:
                    data = json.load(f)
                self.json_text.delete("1.0", "end")
                self.json_text.insert("1.0", json.dumps(data, indent=2))
                self._json_to_table()
                self._log(f"Loaded config: {path}", tag="dim")
            except Exception as e:
                self._log(f"Error loading JSON: {e}", tag="error")

    def _save_json_file(self):
        path = filedialog.asksaveasfilename(
            title="Save JSON config",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            try:
                raw = self.json_text.get("1.0", "end").strip()
                data = json.loads(raw)
                with open(path, "w") as f:
                    json.dump(data, f, indent=2)
                self.json_path_var.set(path)
                self._log(f"Saved config: {path}", tag="dim")
            except Exception as e:
                self._log(f"Error saving JSON: {e}", tag="error")

    # ── Range table operations ────────────────

    def _add_range(self):
        try:
            start = int(self.start_entry.get())
            end   = int(self.end_entry.get())
            if start < 1 or end < start:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid input", "Start and End must be positive integers with Start ≤ End.")
            return
        direction = "RTL ←" if self.rtl_var.get() else "LTR →"
        self.tree.insert("", "end", values=(start, end, direction))
        self._table_to_json()

    def _update_range(self):
        sel = self.tree.selection()
        if not sel:
            return
        try:
            start = int(self.start_entry.get())
            end   = int(self.end_entry.get())
            if start < 1 or end < start:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid input", "Start and End must be positive integers with Start ≤ End.")
            return
        direction = "RTL ←" if self.rtl_var.get() else "LTR →"
        self.tree.item(sel[0], values=(start, end, direction))
        self._table_to_json()

    def _delete_range(self):
        sel = self.tree.selection()
        if sel:
            self.tree.delete(*sel)
            self._table_to_json()

    def _on_row_select(self, _event=None):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            self.start_entry.delete(0, "end")
            self.start_entry.insert(0, vals[0])
            self.end_entry.delete(0, "end")
            self.end_entry.insert(0, vals[1])
            # Restore the RTL checkbox to match the selected row
            self.rtl_var.set(len(vals) > 2 and vals[2].startswith("RTL"))

    # ── JSON ↔ Table sync ────────────────────

    def _table_to_json(self):
        rows = [self.tree.item(iid, "values") for iid in self.tree.get_children()]
        data = []
        for r in rows:
            entry = {"start_page": int(r[0]), "end_page": int(r[1])}
            if len(r) > 2 and str(r[2]).startswith("RTL"):
                entry["rtl"] = True
            data.append(entry)
        self.json_text.delete("1.0", "end")
        self.json_text.insert("1.0", json.dumps(data, indent=2))

    def _json_to_table(self):
        try:
            raw  = self.json_text.get("1.0", "end").strip()
            data = json.loads(raw)
            if not isinstance(data, list):
                raise ValueError("JSON must be a list of objects.")
            self.tree.delete(*self.tree.get_children())
            for item in data:
                direction = "RTL ←" if item.get("rtl", False) else "LTR →"
                self.tree.insert("", "end", values=(item["start_page"], item["end_page"], direction))
        except Exception as e:
            self._log(f"JSON parse error: {e}", tag="error")

    # ── Processing ───────────────────────────

    def _run(self):
        input_path  = self.input_var.get().strip()
        output_path = self.output_var.get().strip()

        if not input_path or not os.path.isfile(input_path):
            messagebox.showerror("Missing input", "Please select a valid input PDF.")
            return
        if not output_path:
            messagebox.showerror("Missing output", "Please specify an output file path.")
            return

        try:
            raw  = self.json_text.get("1.0", "end").strip()
            ranges = json.loads(raw)
            if not isinstance(ranges, list) or not ranges:
                raise ValueError("Ranges list is empty or invalid.")
        except Exception as e:
            messagebox.showerror("Invalid ranges", f"Could not parse spread ranges:\n{e}")
            return

        self._log(f"\n── Processing ──────────────────────")
        self._log(f"Input:  {input_path}", tag="dim")
        self._log(f"Output: {output_path}", tag="dim")
        self._log(f"Ranges: {ranges}", tag="dim")

        # Run in a thread so the UI stays responsive
        threading.Thread(target=self._worker, args=(input_path, output_path, ranges), daemon=True).start()

    def _worker(self, input_path, output_path, ranges):
        try:
            create_pdf_spreads(input_path, output_path, ranges, log_fn=lambda m: self._log(m))
            self._log("✓ Completed successfully!", tag="success")
        except Exception as e:
            self._log(f"✗ Error: {e}", tag="error")

    # ── Log ──────────────────────────────────

    def _log(self, message, tag=None):
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n", tag or "")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _append)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


# ─────────────────────────────────────────────

if __name__ == "__main__":
    app = PDFSpreadsApp()
    app.mainloop()
