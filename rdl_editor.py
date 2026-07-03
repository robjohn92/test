#!/usr/bin/env python3
"""SSRS .rdl file editor — GUI application using tkinter."""

import copy
import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

RDL_2008_NS = "http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition"
RD_NS = "http://schemas.microsoft.com/SQLServer/reporting/reportdesigner"

RECENT_FILES_PATH = os.path.expanduser("~/.rdl_editor_recent.json")
MAX_RECENT = 8
MAX_UNDO = 100

NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._\-]*$")

COMMON_RDL_TAGS = [
    "Body", "BottomMargin", "CanGrow", "CellContents", "Color",
    "CommandText", "ConnectString", "ConnectionProperties", "DataField",
    "DataProvider", "DataSet", "DataSetName", "DataSets", "DataSource",
    "DataSourceName", "DataSourceReference", "DataSources", "DataType",
    "DefaultValue", "Field", "Fields", "FontFamily", "FontSize",
    "FontStyle", "FontWeight", "Format", "Group", "GroupExpressions",
    "Height", "Hidden", "KeepTogether", "Left", "LeftMargin", "Page",
    "PageFooter", "PageHeader", "PageHeight", "PageWidth",
    "PaddingBottom", "PaddingLeft", "PaddingRight", "PaddingTop",
    "Paragraph", "Paragraphs", "Prompt", "Query", "QueryParameter",
    "QueryParameters", "ReportItems", "ReportParameter",
    "ReportParameters", "ReportSection", "ReportSections", "RightMargin",
    "Style", "Tablix", "TablixBody", "TablixCell", "TablixCells",
    "TablixColumn", "TablixColumnHierarchy", "TablixColumns",
    "TablixCorner", "TablixHeader", "TablixMember", "TablixMembers",
    "TablixRow", "TablixRowHierarchy", "TablixRows", "TextAlign",
    "Textbox", "TextRun", "TextRuns", "Top", "TopMargin", "Value",
    "Values", "VerticalAlign", "Visibility", "Width", "ZIndex",
    "rd:TypeName",
]

SHORTCUTS_TEXT = """\
Ctrl+N          New file
Ctrl+O          Open file
Ctrl+S          Save
Ctrl+Shift+S    Save As
Ctrl+Z / Ctrl+Y Undo / Redo
Ctrl+F          Find (F3 next, Shift+F3 previous)
F2              Rename selected element
Ctrl+D          Duplicate selected element
Alt+Up / Down   Move element among siblings
Delete          Delete selected element
Right-click     Context menu on tree and attributes"""


def local_tag(tag):
    """Strip namespace URI from a tag or attribute name."""
    if isinstance(tag, str) and tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def strip_xml_declaration(text):
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text, count=1)


def read_text_any(path):
    for enc in ("utf-8-sig", "utf-16"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def collect_namespaces(text):
    """Return (prefix, uri) pairs declared anywhere in the document."""
    pairs = []
    try:
        stream = io.StringIO(strip_xml_declaration(text))
        for _event, ns in ET.iterparse(stream, events=("start-ns",)):
            if ns not in pairs:
                pairs.append(ns)
    except ET.ParseError:
        pass
    return pairs


def register_namespaces(pairs):
    for prefix, uri in pairs:
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass  # reserved prefixes like "xml"


def strip_whitespace_nodes(element):
    """Drop indentation-only text/tails so the tree edits and re-indents cleanly."""
    if element.text is not None and not element.text.strip():
        element.text = None
    if element.tail is not None and not element.tail.strip():
        element.tail = None
    for child in element:
        strip_whitespace_nodes(child)


def serialize_pretty(root):
    clone = copy.deepcopy(root)
    strip_whitespace_nodes(clone)
    if hasattr(ET, "indent"):
        ET.indent(clone, space="  ")
    body = ET.tostring(clone, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def parse_rdl_text(text):
    """Parse RDL text, returning (root, namespace_pairs). Raises ET.ParseError."""
    stripped = strip_xml_declaration(text)
    pairs = collect_namespaces(text)
    register_namespaces(pairs)
    root = ET.fromstring(stripped)
    strip_whitespace_nodes(root)
    return root, pairs


class TagDialog(simpledialog.Dialog):
    """Modal prompt with an editable combobox of suggested tag names."""

    def __init__(self, parent, title, prompt, suggestions, initialvalue=""):
        self._prompt = prompt
        self._suggestions = suggestions
        self._initial = initialvalue
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        ttk.Label(master, text=self._prompt).grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self._combo = ttk.Combobox(master, values=self._suggestions, width=36)
        self._combo.set(self._initial)
        self._combo.grid(row=1, column=0, padx=4, pady=4)
        return self._combo

    def apply(self):
        self.result = self._combo.get().strip()


class RDLEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RDL Editor")
        self.geometry("1150x720")
        self.minsize(800, 500)

        style = ttk.Style(self)
        if self.tk.call("tk", "windowingsystem") == "x11" and "clam" in style.theme_names():
            style.theme_use("clam")

        self._tree_xml = None  # ET.ElementTree
        self._file_path = None
        self._modified = False
        self._node_map = {}   # tree iid -> ET.Element
        self._attr_keys = {}  # attr row iid -> full attribute key
        self._ns_map = {"": RDL_2008_NS, "rd": RD_NS}
        self._undo_stack = []
        self._redo_stack = []
        self._recent = self._load_recent()
        self._tab_guard = False
        self._find_query = ""
        self._find_matches = []
        self._find_index = -1
        self._matches_dirty = True

        register_namespaces(self._ns_map.items())

        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ menu
    def _build_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self._new_file)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self._open_file)
        self._recent_menu = tk.Menu(file_menu, tearoff=False)
        file_menu.add_cascade(label="Open Recent", menu=self._recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self._save_file)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self._save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        self._rebuild_recent_menu()

        edit_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Undo", accelerator="Ctrl+Z", command=self._undo)
        edit_menu.add_command(label="Redo", accelerator="Ctrl+Y", command=self._redo)
        edit_menu.add_separator()
        edit_menu.add_command(label="Find…", accelerator="Ctrl+F", command=self._show_find)
        edit_menu.add_separator()
        edit_menu.add_command(label="Add Child Element", command=self._add_child)
        edit_menu.add_command(label="Add Attribute", command=self._add_attribute)
        edit_menu.add_command(label="Rename Element", accelerator="F2", command=self._rename_selected)
        edit_menu.add_command(label="Duplicate Element", accelerator="Ctrl+D", command=self._duplicate_selected)
        edit_menu.add_command(label="Move Up", accelerator="Alt+Up", command=lambda: self._move_selected(-1))
        edit_menu.add_command(label="Move Down", accelerator="Alt+Down", command=lambda: self._move_selected(1))
        edit_menu.add_separator()
        edit_menu.add_command(label="Delete Selected", accelerator="Del", command=self._delete_selected)
        edit_menu.add_separator()
        edit_menu.add_command(label="Expand All", command=lambda: self._set_open_all(True))
        edit_menu.add_command(label="Collapse All", command=lambda: self._set_open_all(False))

        tools_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        tools_menu.add_command(label="Validate Report", command=self._validate)

        help_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="Keyboard Shortcuts",
                              command=lambda: messagebox.showinfo("Keyboard Shortcuts", SHORTCUTS_TEXT))

    def _rebuild_recent_menu(self):
        self._recent_menu.delete(0, tk.END)
        if not self._recent:
            self._recent_menu.add_command(label="(empty)", state=tk.DISABLED)
            return
        for path in self._recent:
            self._recent_menu.add_command(
                label=path, command=lambda p=path: self._open_recent(p))

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self._status_var = tk.StringVar(value="No file open")
        status_bar = tk.Label(self, textvariable=self._status_var, anchor="w",
                              relief=tk.SUNKEN, padx=4)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True)
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # ---- Find bar (hidden until Ctrl+F) ----
        self._find_frame = ttk.Frame(self)
        ttk.Label(self._find_frame, text="Find:").pack(side=tk.LEFT, padx=4)
        self._find_entry = ttk.Entry(self._find_frame, width=30)
        self._find_entry.pack(side=tk.LEFT, padx=2)
        self._find_entry.bind("<Return>", lambda e: self._find_next(1))
        ttk.Button(self._find_frame, text="Next", command=lambda: self._find_next(1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(self._find_frame, text="Prev", command=lambda: self._find_next(-1)).pack(side=tk.LEFT, padx=2)
        self._find_label = ttk.Label(self._find_frame, text="")
        self._find_label.pack(side=tk.LEFT, padx=8)
        ttk.Button(self._find_frame, text="Close", command=self._hide_find).pack(side=tk.RIGHT, padx=4)

        # ---- Tab 1: tree view ----
        self._tree_tab = ttk.Frame(self._notebook)
        self._notebook.add(self._tree_tab, text="Tree View")

        paned = ttk.PanedWindow(self._tree_tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=2)

        ttk.Label(left_frame, text="Document Tree").pack(anchor="w", padx=4, pady=2)

        tree_scroll_y = ttk.Scrollbar(left_frame, orient=tk.VERTICAL)
        tree_scroll_x = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL)
        self._tree = ttk.Treeview(left_frame, yscrollcommand=tree_scroll_y.set,
                                  xscrollcommand=tree_scroll_x.set, selectmode="browse")
        tree_scroll_y.config(command=self._tree.yview)
        tree_scroll_x.config(command=self._tree.xview)

        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._tree.pack(fill=tk.BOTH, expand=True)

        self._tree["columns"] = ("value",)
        self._tree.heading("#0", text="Element")
        self._tree.heading("value", text="Value")
        self._tree.column("#0", width=300, minwidth=150)
        self._tree.column("value", width=240, minwidth=100)
        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # ---- Right: detail panel ----
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        self._props_label = ttk.Label(right_frame, text="Properties")
        self._props_label.pack(anchor="w", padx=4, pady=2)

        attr_frame = ttk.LabelFrame(right_frame, text="Attributes")
        attr_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        attr_scroll = ttk.Scrollbar(attr_frame, orient=tk.VERTICAL)
        self._attr_tree = ttk.Treeview(attr_frame, yscrollcommand=attr_scroll.set,
                                       selectmode="browse", height=8)
        attr_scroll.config(command=self._attr_tree.yview)
        attr_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._attr_tree.pack(fill=tk.BOTH, expand=True)

        self._attr_tree["columns"] = ("value",)
        self._attr_tree.heading("#0", text="Attribute")
        self._attr_tree.heading("value", text="Value")
        self._attr_tree.column("#0", width=130)
        self._attr_tree.column("value", width=160)
        self._attr_tree.bind("<Double-1>", lambda e: self._edit_attr_value())

        text_frame = ttk.LabelFrame(right_frame, text="Text Content")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._text_edit = tk.Text(text_frame, height=6, wrap=tk.WORD, undo=True)
        text_scroll = ttk.Scrollbar(text_frame, command=self._text_edit.yview)
        self._text_edit.config(yscrollcommand=text_scroll.set)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._text_edit.pack(fill=tk.BOTH, expand=True)
        self._text_edit.bind("<Control-Return>", lambda e: (self._apply_text(), "break")[1])

        btn_row1 = ttk.Frame(right_frame)
        btn_row1.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(btn_row1, text="Apply Text", command=self._apply_text).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row1, text="Add Child", command=self._add_child).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row1, text="Add Attr", command=self._add_attribute).pack(side=tk.LEFT, padx=2)

        btn_row2 = ttk.Frame(right_frame)
        btn_row2.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(btn_row2, text="Duplicate", command=self._duplicate_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row2, text="Move Up", command=lambda: self._move_selected(-1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row2, text="Move Down", command=lambda: self._move_selected(1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row2, text="Delete", command=self._delete_selected).pack(side=tk.LEFT, padx=2)

        # ---- Tab 2: XML source ----
        self._source_tab = ttk.Frame(self._notebook)
        self._notebook.add(self._source_tab, text="XML Source")

        source_bar = ttk.Frame(self._source_tab)
        source_bar.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(source_bar, text="Apply Source", command=self._apply_source).pack(side=tk.LEFT)
        ttk.Label(source_bar, text="Edit raw XML, then Apply Source to update the tree (Ctrl+Enter)."
                  ).pack(side=tk.LEFT, padx=8)

        self._source_text = tk.Text(self._source_tab, wrap=tk.NONE, undo=True)
        src_scroll_y = ttk.Scrollbar(self._source_tab, command=self._source_text.yview)
        src_scroll_x = ttk.Scrollbar(self._source_tab, orient=tk.HORIZONTAL,
                                     command=self._source_text.xview)
        self._source_text.config(yscrollcommand=src_scroll_y.set, xscrollcommand=src_scroll_x.set)
        src_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        src_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self._source_text.pack(fill=tk.BOTH, expand=True)
        self._source_text.bind("<Control-Return>", lambda e: (self._apply_source(), "break")[1])

        # ---- Context menus ----
        self._tree_menu = tk.Menu(self, tearoff=False)
        self._tree_menu.add_command(label="Add Child Element", command=self._add_child)
        self._tree_menu.add_command(label="Add Attribute", command=self._add_attribute)
        self._tree_menu.add_command(label="Rename", command=self._rename_selected)
        self._tree_menu.add_command(label="Duplicate", command=self._duplicate_selected)
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="Move Up", command=lambda: self._move_selected(-1))
        self._tree_menu.add_command(label="Move Down", command=lambda: self._move_selected(1))
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="Expand All", command=lambda: self._set_open_all(True))
        self._tree_menu.add_command(label="Collapse All", command=lambda: self._set_open_all(False))
        self._tree_menu.add_separator()
        self._tree_menu.add_command(label="Delete", command=self._delete_selected)

        self._attr_menu = tk.Menu(self, tearoff=False)
        self._attr_menu.add_command(label="Edit Value", command=self._edit_attr_value)
        self._attr_menu.add_command(label="Rename Attribute", command=self._rename_attr)
        self._attr_menu.add_command(label="Delete Attribute", command=self._delete_attr)

        if self.tk.call("tk", "windowingsystem") == "aqua":
            self._tree.bind("<Button-2>", self._show_tree_menu)
            self._tree.bind("<Control-Button-1>", self._show_tree_menu)
            self._attr_tree.bind("<Button-2>", self._show_attr_menu)
            self._attr_tree.bind("<Control-Button-1>", self._show_attr_menu)
        else:
            self._tree.bind("<Button-3>", self._show_tree_menu)
            self._attr_tree.bind("<Button-3>", self._show_attr_menu)

    def _bind_keys(self):
        self.bind_all("<Control-n>", lambda e: self._new_file())
        self.bind_all("<Control-o>", lambda e: self._open_file())
        self.bind_all("<Control-s>", lambda e: self._save_file())
        self.bind_all("<Control-S>", lambda e: self._save_as())
        self.bind_all("<Control-z>", self._on_undo_key)
        self.bind_all("<Control-y>", self._on_redo_key)
        self.bind_all("<Control-f>", self._on_find_key)
        self.bind_all("<F3>", lambda e: self._find_next(1))
        self.bind_all("<Shift-F3>", lambda e: self._find_next(-1))
        self.bind_all("<Escape>", lambda e: self._hide_find())

        self._tree.bind("<Delete>", lambda e: self._delete_selected())
        self._tree.bind("<F2>", lambda e: self._rename_selected())
        self._tree.bind("<Control-d>", lambda e: self._duplicate_selected())
        self._tree.bind("<Alt-Up>", lambda e: (self._move_selected(-1), "break")[1])
        self._tree.bind("<Alt-Down>", lambda e: (self._move_selected(1), "break")[1])

    @staticmethod
    def _focus_in_text_widget(event):
        widget = event.widget
        if isinstance(widget, tk.Text):
            return True
        try:
            return widget.winfo_class() in ("Entry", "TEntry", "TCombobox", "Spinbox")
        except Exception:
            return False

    def _on_undo_key(self, event):
        if self._focus_in_text_widget(event):
            return  # let the text widget handle its own undo
        self._undo()
        return "break"

    def _on_redo_key(self, event):
        if self._focus_in_text_widget(event):
            return
        self._redo()
        return "break"

    def _on_find_key(self, event):
        if isinstance(event.widget, tk.Text):
            return
        self._show_find()
        return "break"

    # ------------------------------------------------------------------ file ops
    def _new_file(self):
        if not self._confirm_discard():
            return
        register_namespaces(self._ns_map.items())
        root_el = ET.Element("{%s}Report" % RDL_2008_NS)
        self._tree_xml = ET.ElementTree(root_el)
        self._file_path = None
        self._modified = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._populate_tree()
        self._update_title()
        self._set_status("New report created")

    def _open_file(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open RDL File",
            filetypes=[("RDL Files", "*.rdl"), ("XML Files", "*.xml"), ("All Files", "*.*")]
        )
        if path:
            self._open_path(path)

    def _open_recent(self, path):
        if not os.path.exists(path):
            messagebox.showerror("Not Found", f"File no longer exists:\n{path}")
            self._recent.remove(path)
            self._save_recent()
            self._rebuild_recent_menu()
            return
        if self._confirm_discard():
            self._open_path(path)

    def _open_path(self, path):
        try:
            text = read_text_any(path)
            root, pairs = parse_rdl_text(text)
        except (ET.ParseError, OSError) as e:
            messagebox.showerror("Open Error", f"Could not open file:\n{e}")
            return
        self._ns_map.update(dict(pairs))
        self._tree_xml = ET.ElementTree(root)
        self._file_path = path
        self._modified = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self._populate_tree()
        self._add_recent(path)
        self._update_title()
        self._set_status(f"Opened: {os.path.basename(path)}")

    def _save_file(self):
        if not self._tree_xml:
            return
        if not self._file_path:
            self._save_as()
            return
        self._write_file(self._file_path)

    def _save_as(self):
        if not self._tree_xml:
            return
        path = filedialog.asksaveasfilename(
            title="Save RDL File",
            defaultextension=".rdl",
            filetypes=[("RDL Files", "*.rdl"), ("XML Files", "*.xml"), ("All Files", "*.*")]
        )
        if not path:
            return
        self._file_path = path
        self._write_file(path)

    def _write_file(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(serialize_pretty(self._tree_xml.getroot()))
            self._modified = False
            self._add_recent(path)
            self._update_title()
            self._set_status(f"Saved: {os.path.basename(path)}")
        except OSError as e:
            messagebox.showerror("Save Error", f"Could not save file:\n{e}")

    def _confirm_discard(self):
        if self._modified:
            return messagebox.askyesno("Unsaved Changes",
                                       "You have unsaved changes. Discard and continue?")
        return True

    def _on_close(self):
        if self._confirm_discard():
            self.destroy()

    # ------------------------------------------------------------------ recent files
    def _load_recent(self):
        try:
            with open(RECENT_FILES_PATH) as f:
                data = json.load(f)
            return [p for p in data if isinstance(p, str)][:MAX_RECENT]
        except (OSError, ValueError):
            return []

    def _save_recent(self):
        try:
            with open(RECENT_FILES_PATH, "w") as f:
                json.dump(self._recent, f)
        except OSError:
            pass

    def _add_recent(self, path):
        path = os.path.abspath(path)
        if path in self._recent:
            self._recent.remove(path)
        self._recent.insert(0, path)
        del self._recent[MAX_RECENT:]
        self._save_recent()
        self._rebuild_recent_menu()

    # ------------------------------------------------------------------ tree population
    def _populate_tree(self):
        self._tree.delete(*self._tree.get_children())
        self._node_map.clear()
        self._attr_tree.delete(*self._attr_tree.get_children())
        self._attr_keys.clear()
        self._text_edit.delete("1.0", tk.END)
        self._props_label.config(text="Properties")
        self._matches_dirty = True

        if not self._tree_xml:
            return

        root_iid = self._insert_element("", self._tree_xml.getroot())
        self._tree.item(root_iid, open=True)

        if not self._tab_guard and self._notebook.select() == str(self._source_tab):
            self._render_source()

    def _tree_label(self, element):
        """Element tag, annotated with its Name attribute when present —
        RDL uses Name as the human identifier (Tablix1, DataSet1, …)."""
        tag = local_tag(element.tag)
        name = element.get("Name")
        return f"{tag}  ({name})" if name else tag

    def _insert_element(self, parent_iid, element, index=tk.END):
        preview = " ".join((element.text or "").split())[:60]
        iid = self._tree.insert(parent_iid, index, text=self._tree_label(element),
                                values=(preview,), open=False)
        self._node_map[iid] = element
        for child in element:
            self._insert_element(iid, child)
        return iid

    def _iter_tree_items(self, iid=""):
        for child in self._tree.get_children(iid):
            yield child
            yield from self._iter_tree_items(child)

    def _set_open_all(self, open_):
        for iid in self._iter_tree_items():
            self._tree.item(iid, open=open_)

    # ------------------------------------------------------------------ selection
    def _selected_iid(self):
        sel = self._tree.selection()
        return sel[0] if sel else None

    def _current_element(self):
        iid = self._selected_iid()
        return self._node_map.get(iid) if iid else None

    def _element_path(self, iid):
        parts = []
        while iid:
            el = self._node_map.get(iid)
            if el is not None:
                parts.append(local_tag(el.tag))
            iid = self._tree.parent(iid)
        return " / ".join(reversed(parts))

    def _on_tree_select(self, _event=None):
        iid = self._selected_iid()
        if not iid:
            return
        element = self._node_map.get(iid)
        if element is None:
            return

        self._props_label.config(text=f"Properties — {local_tag(element.tag)}")
        self._refresh_attrs(element)

        self._text_edit.delete("1.0", tk.END)
        if element.text:
            self._text_edit.insert("1.0", element.text)
        self._text_edit.edit_reset()

        self._set_status(self._element_path(iid))

    def _refresh_attrs(self, element):
        self._attr_tree.delete(*self._attr_tree.get_children())
        self._attr_keys.clear()
        for key, value in element.attrib.items():
            iid = self._attr_tree.insert("", tk.END, text=local_tag(key), values=(value,))
            self._attr_keys[iid] = key

    # ------------------------------------------------------------------ context menus
    def _show_tree_menu(self, event):
        iid = self._tree.identify_row(event.y)
        if iid:
            self._tree.selection_set(iid)
            self._tree.focus(iid)
        try:
            self._tree_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._tree_menu.grab_release()

    def _show_attr_menu(self, event):
        iid = self._attr_tree.identify_row(event.y)
        if iid:
            self._attr_tree.selection_set(iid)
        try:
            self._attr_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._attr_menu.grab_release()

    # ------------------------------------------------------------------ name handling
    def _expand_name(self, name, inherit_from=None):
        """Turn a user-typed name into an ElementTree tag, resolving prefixes
        and inheriting the parent namespace for unprefixed element names."""
        name = name.strip()
        if ":" in name:
            prefix, local = name.split(":", 1)
            if not NAME_RE.match(prefix) or not NAME_RE.match(local):
                raise ValueError(f"Invalid name: {name!r}")
            uri = self._ns_map.get(prefix)
            if not uri:
                raise ValueError(f"Unknown namespace prefix: {prefix!r}")
            return "{%s}%s" % (uri, local)
        if not NAME_RE.match(name):
            raise ValueError(f"Invalid name: {name!r}")
        if inherit_from and inherit_from.startswith("{"):
            uri = inherit_from[1:].split("}", 1)[0]
            return "{%s}%s" % (uri, name)
        return name

    # ------------------------------------------------------------------ editing actions
    def _apply_text(self):
        iid = self._selected_iid()
        if not iid:
            messagebox.showinfo("No Selection", "Select an element first.")
            return
        element = self._node_map.get(iid)
        if element is None:
            return
        new_text = self._text_edit.get("1.0", "end-1c")
        if new_text == (element.text or ""):
            self._set_status("Text unchanged")
            return
        self._push_undo()
        element.text = new_text or None
        preview = " ".join((element.text or "").split())[:60]
        self._tree.item(iid, values=(preview,))
        self._mark_modified()
        self._set_status("Text applied")

    def _add_child(self):
        iid = self._selected_iid()
        if not iid:
            messagebox.showinfo("No Selection", "Select a parent element first.")
            return
        parent_el = self._node_map.get(iid)
        if parent_el is None:
            return

        dlg = TagDialog(self, "Add Child Element", "Tag name for new child:", COMMON_RDL_TAGS)
        if not dlg.result:
            return
        try:
            tag = self._expand_name(dlg.result, inherit_from=parent_el.tag)
        except ValueError as e:
            messagebox.showerror("Invalid Name", str(e))
            return

        self._push_undo()
        child = ET.SubElement(parent_el, tag)
        new_iid = self._insert_element(iid, child)
        self._tree.item(iid, open=True)
        self._tree.selection_set(new_iid)
        self._mark_modified()

    def _rename_selected(self):
        iid = self._selected_iid()
        if not iid:
            return
        element = self._node_map.get(iid)
        if element is None:
            return
        current = local_tag(element.tag)
        dlg = TagDialog(self, "Rename Element", "New tag name:", COMMON_RDL_TAGS,
                        initialvalue=current)
        if not dlg.result or dlg.result == current:
            return
        try:
            new_tag = self._expand_name(dlg.result, inherit_from=element.tag)
        except ValueError as e:
            messagebox.showerror("Invalid Name", str(e))
            return
        self._push_undo()
        element.tag = new_tag
        self._tree.item(iid, text=self._tree_label(element))
        self._props_label.config(text=f"Properties — {local_tag(new_tag)}")
        self._mark_modified()

    def _duplicate_selected(self):
        iid = self._selected_iid()
        if not iid:
            return
        parent_iid = self._tree.parent(iid)
        if not parent_iid:
            messagebox.showwarning("Cannot Duplicate", "Cannot duplicate the root element.")
            return
        parent_el = self._node_map[parent_iid]
        element = self._node_map[iid]

        self._push_undo()
        clone = copy.deepcopy(element)
        index = list(parent_el).index(element) + 1
        parent_el.insert(index, clone)
        new_iid = self._insert_element(parent_iid, clone, index=index)
        self._tree.selection_set(new_iid)
        self._tree.see(new_iid)
        self._mark_modified()

    def _move_selected(self, delta):
        iid = self._selected_iid()
        if not iid:
            return
        parent_iid = self._tree.parent(iid)
        if not parent_iid:
            return
        parent_el = self._node_map[parent_iid]
        element = self._node_map[iid]
        index = list(parent_el).index(element)
        new_index = index + delta
        if not 0 <= new_index < len(parent_el):
            return
        self._push_undo()
        parent_el.remove(element)
        parent_el.insert(new_index, element)
        self._tree.move(iid, parent_iid, new_index)
        self._tree.see(iid)
        self._mark_modified()

    def _delete_selected(self):
        iid = self._selected_iid()
        if not iid:
            return
        element = self._node_map.get(iid)
        if element is None:
            return
        parent_iid = self._tree.parent(iid)
        if not parent_iid:
            messagebox.showwarning("Cannot Delete", "Cannot delete the root element.")
            return
        parent_el = self._node_map.get(parent_iid)
        if parent_el is None:
            return
        if not messagebox.askyesno(
                "Confirm Delete",
                f"Delete element '{local_tag(element.tag)}' and all its children?\n"
                "(Ctrl+Z will undo this.)"):
            return

        self._push_undo()
        parent_el.remove(element)
        self._remove_iid_recursive(iid)
        self._tree.delete(iid)
        self._attr_tree.delete(*self._attr_tree.get_children())
        self._attr_keys.clear()
        self._text_edit.delete("1.0", tk.END)
        self._mark_modified()

    def _remove_iid_recursive(self, iid):
        for child_iid in self._tree.get_children(iid):
            self._remove_iid_recursive(child_iid)
        self._node_map.pop(iid, None)

    # ------------------------------------------------------------------ attribute actions
    def _add_attribute(self):
        element = self._current_element()
        if element is None:
            messagebox.showinfo("No Selection", "Select an element first.")
            return
        name = simpledialog.askstring("Add Attribute", "Attribute name:", parent=self)
        if not name:
            return
        try:
            key = self._expand_name(name)
        except ValueError as e:
            messagebox.showerror("Invalid Name", str(e))
            return
        value = simpledialog.askstring("Add Attribute", f"Value for '{name}':",
                                       initialvalue="", parent=self)
        if value is None:
            return
        self._push_undo()
        element.attrib[key] = value
        self._refresh_attrs(element)
        if local_tag(key) == "Name":
            self._refresh_label(self._selected_iid(), element)
        self._mark_modified()

    def _selected_attr(self):
        element = self._current_element()
        sel = self._attr_tree.selection()
        if element is None or not sel:
            return None, None, None
        iid = sel[0]
        return element, iid, self._attr_keys.get(iid)

    def _edit_attr_value(self):
        element, iid, key = self._selected_attr()
        if key is None:
            return
        old = element.attrib.get(key, "")
        new = simpledialog.askstring("Edit Attribute", f"Value for '{local_tag(key)}':",
                                     initialvalue=old, parent=self)
        if new is None or new == old:
            return
        self._push_undo()
        element.attrib[key] = new
        self._attr_tree.item(iid, values=(new,))
        if local_tag(key) == "Name":
            self._refresh_label(self._selected_iid(), element)
        self._mark_modified()

    def _rename_attr(self):
        element, _iid, key = self._selected_attr()
        if key is None:
            return
        new_name = simpledialog.askstring("Rename Attribute", "New attribute name:",
                                          initialvalue=local_tag(key), parent=self)
        if not new_name or new_name == local_tag(key):
            return
        try:
            new_key = self._expand_name(new_name)
        except ValueError as e:
            messagebox.showerror("Invalid Name", str(e))
            return
        self._push_undo()
        element.attrib[new_key] = element.attrib.pop(key)
        self._refresh_attrs(element)
        self._refresh_label(self._selected_iid(), element)
        self._mark_modified()

    def _delete_attr(self):
        element, iid, key = self._selected_attr()
        if key is None:
            return
        self._push_undo()
        was_name = local_tag(key) == "Name"
        element.attrib.pop(key, None)
        self._attr_tree.delete(iid)
        self._attr_keys.pop(iid, None)
        if was_name:
            self._refresh_label(self._selected_iid(), element)
        self._mark_modified()

    # ------------------------------------------------------------------ undo/redo
    def _push_undo(self):
        if self._tree_xml is None:
            return
        self._undo_stack.append(ET.tostring(self._tree_xml.getroot(), encoding="unicode"))
        if len(self._undo_stack) > MAX_UNDO:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            self._set_status("Nothing to undo")
            return
        self._redo_stack.append(ET.tostring(self._tree_xml.getroot(), encoding="unicode"))
        self._restore_snapshot(self._undo_stack.pop(), "Undo")

    def _redo(self):
        if not self._redo_stack:
            self._set_status("Nothing to redo")
            return
        self._undo_stack.append(ET.tostring(self._tree_xml.getroot(), encoding="unicode"))
        self._restore_snapshot(self._redo_stack.pop(), "Redo")

    def _restore_snapshot(self, snapshot, label):
        root = ET.fromstring(snapshot)
        strip_whitespace_nodes(root)
        self._tree_xml = ET.ElementTree(root)
        self._modified = True
        self._populate_tree()
        self._update_title()
        self._set_status(label)

    # ------------------------------------------------------------------ find
    def _show_find(self):
        if self._notebook.select() != str(self._tree_tab):
            self._notebook.select(self._tree_tab)
        self._find_frame.pack(side=tk.TOP, fill=tk.X, before=self._notebook)
        self._find_entry.focus_set()
        self._find_entry.select_range(0, tk.END)

    def _hide_find(self):
        self._find_frame.pack_forget()
        self._tree.focus_set()

    def _compute_matches(self, query):
        q = query.lower()
        matches = []
        for iid in self._iter_tree_items():
            el = self._node_map.get(iid)
            if el is None:
                continue
            if q in local_tag(el.tag).lower():
                matches.append(iid)
                continue
            if el.text and q in el.text.lower():
                matches.append(iid)
                continue
            for key, value in el.attrib.items():
                if q in local_tag(key).lower() or q in str(value).lower():
                    matches.append(iid)
                    break
        return matches

    def _find_next(self, direction):
        query = self._find_entry.get().strip()
        if not query:
            return
        if query != self._find_query or self._matches_dirty:
            self._find_query = query
            self._find_matches = self._compute_matches(query)
            self._find_index = -1 if direction > 0 else 0
            self._matches_dirty = False
        if not self._find_matches:
            self._find_label.config(text="No matches")
            return
        self._find_index = (self._find_index + direction) % len(self._find_matches)
        iid = self._find_matches[self._find_index]
        self._reveal(iid)
        self._find_label.config(text=f"{self._find_index + 1} of {len(self._find_matches)}")

    def _reveal(self, iid):
        parent = self._tree.parent(iid)
        while parent:
            self._tree.item(parent, open=True)
            parent = self._tree.parent(parent)
        self._tree.selection_set(iid)
        self._tree.focus(iid)
        self._tree.see(iid)

    # ------------------------------------------------------------------ source view
    def _on_tab_changed(self, _event=None):
        if self._tab_guard:
            return
        current = self._notebook.select()
        if current == str(self._source_tab):
            self._render_source()
        elif self._source_text.edit_modified():
            if messagebox.askyesno("Unapplied Changes",
                                   "The source view has unapplied edits. Discard them?"):
                self._source_text.edit_modified(False)
            else:
                self._tab_guard = True
                self._notebook.select(self._source_tab)
                self._tab_guard = False

    def _render_source(self):
        self._source_text.delete("1.0", tk.END)
        if self._tree_xml is not None:
            self._source_text.insert("1.0", serialize_pretty(self._tree_xml.getroot()))
        self._source_text.edit_modified(False)
        self._source_text.edit_reset()

    def _apply_source(self):
        text = self._source_text.get("1.0", "end-1c")
        try:
            root, pairs = parse_rdl_text(text)
        except ET.ParseError as e:
            messagebox.showerror("Parse Error", f"Could not parse source:\n{e}")
            return
        self._ns_map.update(dict(pairs))
        self._push_undo()
        self._tree_xml = ET.ElementTree(root)
        self._populate_tree()
        self._mark_modified()
        self._set_status("Source applied")

    # ------------------------------------------------------------------ validation
    def _validate(self):
        if not self._tree_xml:
            messagebox.showinfo("Validate", "No file open.")
            return
        root = self._tree_xml.getroot()

        def find_local(parent, name):
            return [el for el in parent.iter() if local_tag(el.tag) == name]

        problems = []
        if local_tag(root.tag) != "Report":
            problems.append(f"Root element is '{local_tag(root.tag)}', expected 'Report'.")

        source_names = [el.get("Name", "?") for el in find_local(root, "DataSource")]
        datasets = find_local(root, "DataSet")
        for dataset in datasets:
            for ref in find_local(dataset, "DataSourceName"):
                name = (ref.text or "").strip()
                if name and name not in source_names:
                    problems.append(
                        f"Dataset '{dataset.get('Name', '?')}' references "
                        f"unknown data source '{name}'.")

        summary = [
            f"Data sources: {len(source_names)}",
            f"Datasets: {len(datasets)}",
            f"Report parameters: {len(find_local(root, 'ReportParameter'))}",
            f"Report items: {sum(len(el) for el in find_local(root, 'ReportItems'))}",
        ]
        if problems:
            messagebox.showwarning(
                "Validation Issues",
                "\n".join(problems) + "\n\n" + "\n".join(summary))
        else:
            messagebox.showinfo(
                "Validation Passed",
                "No issues found.\n\n" + "\n".join(summary))

    # ------------------------------------------------------------------ helpers
    def _refresh_label(self, iid, element):
        """Keep the tree row label in sync after a Name attribute change."""
        self._tree.item(iid, text=self._tree_label(element))

    def _mark_modified(self):
        self._modified = True
        self._matches_dirty = True  # element set changed; find cache is stale
        self._update_title()

    def _update_title(self):
        name = os.path.basename(self._file_path) if self._file_path else "untitled.rdl"
        star = "*" if self._modified else ""
        self.title(f"RDL Editor — {star}{name}")

    def _set_status(self, msg):
        self._status_var.set(msg)


if __name__ == "__main__":
    app = RDLEditor()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        app._open_path(sys.argv[1])
    app.mainloop()
