#!/usr/bin/env python3
"""SSRS .rdl file editor — GUI application using tkinter."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import xml.etree.ElementTree as ET
import xml.dom.minidom
import os


def prettify_xml(element):
    rough = ET.tostring(element, encoding="unicode")
    reparsed = xml.dom.minidom.parseString(rough)
    return reparsed.toprettyxml(indent="  ", encoding=None)


class RDLEditor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RDL Editor")
        self.geometry("1100x700")
        self.minsize(800, 500)

        self._tree_xml = None  # ET.ElementTree
        self._file_path = None
        self._modified = False
        self._node_map = {}  # iid -> ET.Element

        self._build_menu()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ menu
    def _build_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self._new_file)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self._open_file)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self._save_file)
        file_menu.add_command(label="Save As…", command=self._save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        edit_menu = tk.Menu(menubar, tearoff=False)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Add Child Element", command=self._add_child)
        edit_menu.add_command(label="Add Attribute", command=self._add_attribute)
        edit_menu.add_command(label="Delete Selected", accelerator="Del", command=self._delete_selected)

        self.bind_all("<Control-n>", lambda e: self._new_file())
        self.bind_all("<Control-o>", lambda e: self._open_file())
        self.bind_all("<Control-s>", lambda e: self._save_file())
        self.bind_all("<Delete>", lambda e: self._delete_selected())

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        # Status bar
        self._status_var = tk.StringVar(value="No file open")
        status_bar = tk.Label(self, textvariable=self._status_var, anchor="w",
                              relief=tk.SUNKEN, padx=4)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Main paned window
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # ---- Left: XML tree ----
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
        self._tree.heading("#0", text="Element / Attribute")
        self._tree.heading("value", text="Value")
        self._tree.column("#0", width=280, minwidth=150)
        self._tree.column("value", width=220, minwidth=100)

        self._tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self._tree.bind("<Double-1>", self._on_tree_double_click)

        # ---- Right: detail panel ----
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)

        ttk.Label(right_frame, text="Properties").pack(anchor="w", padx=4, pady=2)

        # Attributes table
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
        self._attr_tree.bind("<Double-1>", self._on_attr_double_click)

        # Text content editor
        text_frame = ttk.LabelFrame(right_frame, text="Text Content")
        text_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._text_edit = tk.Text(text_frame, height=6, wrap=tk.WORD, undo=True)
        text_scroll = ttk.Scrollbar(text_frame, command=self._text_edit.yview)
        self._text_edit.config(yscrollcommand=text_scroll.set)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._text_edit.pack(fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(right_frame)
        btn_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(btn_frame, text="Apply Text", command=self._apply_text).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Add Child", command=self._add_child).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Add Attr", command=self._add_attribute).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Delete", command=self._delete_selected).pack(side=tk.LEFT, padx=2)

    # ------------------------------------------------------------------ file ops
    def _new_file(self):
        if not self._confirm_discard():
            return
        root_el = ET.Element("Report", attrib={
            "xmlns": "http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition"
        })
        self._tree_xml = ET.ElementTree(root_el)
        self._file_path = None
        self._modified = False
        self._populate_tree()
        self._set_status("New report created")

    def _open_file(self):
        if not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open RDL File",
            filetypes=[("RDL Files", "*.rdl"), ("XML Files", "*.xml"), ("All Files", "*.*")]
        )
        if not path:
            return
        try:
            self._tree_xml = ET.parse(path)
            self._file_path = path
            self._modified = False
            self._populate_tree()
            self._set_status(f"Opened: {os.path.basename(path)}")
            self.title(f"RDL Editor — {os.path.basename(path)}")
        except ET.ParseError as e:
            messagebox.showerror("Parse Error", f"Could not parse file:\n{e}")

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
            pretty = prettify_xml(self._tree_xml.getroot())
            # Remove the extra xml declaration added by minidom (ET will write its own)
            lines = pretty.splitlines()
            if lines and lines[0].startswith("<?xml"):
                lines = lines[1:]
            content = "\n".join(lines)
            with open(path, "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="utf-8"?>\n')
                f.write(content)
            self._modified = False
            self._set_status(f"Saved: {os.path.basename(path)}")
            self.title(f"RDL Editor — {os.path.basename(path)}")
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

    # ------------------------------------------------------------------ tree population
    def _populate_tree(self):
        self._tree.delete(*self._tree.get_children())
        self._node_map.clear()
        self._attr_tree.delete(*self._attr_tree.get_children())
        self._text_edit.delete("1.0", tk.END)

        if not self._tree_xml:
            return

        root = self._tree_xml.getroot()
        self._insert_element("", root)

    def _local_tag(self, tag):
        """Strip namespace URI from tag."""
        if tag.startswith("{"):
            return tag.split("}", 1)[1]
        return tag

    def _insert_element(self, parent_iid, element):
        tag = self._local_tag(element.tag)
        text_preview = (element.text or "").strip()[:40]
        iid = self._tree.insert(parent_iid, tk.END, text=tag, values=(text_preview,), open=False)
        self._node_map[iid] = element

        for child in element:
            self._insert_element(iid, child)

        return iid

    # ------------------------------------------------------------------ tree selection
    def _on_tree_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        element = self._node_map.get(iid)
        if element is None:
            return

        # Populate attributes panel
        self._attr_tree.delete(*self._attr_tree.get_children())
        for name, value in element.attrib.items():
            self._attr_tree.insert("", tk.END, text=self._local_tag(name), values=(value,))

        # Populate text editor
        self._text_edit.delete("1.0", tk.END)
        if element.text:
            self._text_edit.insert("1.0", element.text)

    def _on_tree_double_click(self, event):
        """Inline rename of element tag."""
        iid = self._tree.identify_row(event.y)
        if not iid:
            return
        element = self._node_map.get(iid)
        if element is None:
            return
        current = self._local_tag(element.tag)
        new_tag = simpledialog.askstring("Rename Element", "New tag name:", initialvalue=current)
        if new_tag and new_tag != current:
            # Preserve namespace if present
            if element.tag.startswith("{"):
                ns = element.tag.split("}", 1)[0] + "}"
                element.tag = ns + new_tag
            else:
                element.tag = new_tag
            self._tree.item(iid, text=new_tag)
            self._mark_modified()

    def _on_attr_double_click(self, event):
        """Edit attribute value inline."""
        iid = self._attr_tree.identify_row(event.y)
        if not iid:
            return
        attr_name = self._attr_tree.item(iid, "text")
        old_value = self._attr_tree.item(iid, "values")[0]

        new_value = simpledialog.askstring("Edit Attribute",
                                            f"Value for '{attr_name}':", initialvalue=old_value)
        if new_value is None:
            return

        sel = self._tree.selection()
        if not sel:
            return
        element = self._node_map.get(sel[0])
        if element is None:
            return

        # Find full attribute key (may have namespace)
        for key in list(element.attrib.keys()):
            if self._local_tag(key) == attr_name:
                element.attrib[key] = new_value
                break
        else:
            element.attrib[attr_name] = new_value

        self._attr_tree.item(iid, values=(new_value,))
        self._mark_modified()

    # ------------------------------------------------------------------ editing actions
    def _apply_text(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Select an element first.")
            return
        element = self._node_map.get(sel[0])
        if element is None:
            return
        element.text = self._text_edit.get("1.0", tk.END).rstrip("\n") or None
        # Refresh preview
        preview = (element.text or "").strip()[:40]
        self._tree.item(sel[0], values=(preview,))
        self._mark_modified()

    def _add_child(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Select a parent element first.")
            return
        parent_iid = sel[0]
        parent_el = self._node_map.get(parent_iid)
        if parent_el is None:
            return

        tag = simpledialog.askstring("Add Child Element", "Tag name for new child:")
        if not tag:
            return

        child = ET.SubElement(parent_el, tag)
        iid = self._insert_element(parent_iid, child)
        self._tree.item(parent_iid, open=True)
        self._tree.selection_set(iid)
        self._mark_modified()

    def _add_attribute(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Select an element first.")
            return
        element = self._node_map.get(sel[0])
        if element is None:
            return

        name = simpledialog.askstring("Add Attribute", "Attribute name:")
        if not name:
            return
        value = simpledialog.askstring("Add Attribute", f"Value for '{name}':", initialvalue="")
        if value is None:
            return

        element.attrib[name] = value
        self._attr_tree.insert("", tk.END, text=name, values=(value,))
        self._mark_modified()

    def _delete_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        element = self._node_map.get(iid)
        if element is None:
            return

        # Find parent element in the XML tree
        parent_iid = self._tree.parent(iid)
        if not parent_iid:
            messagebox.showwarning("Cannot Delete", "Cannot delete the root element.")
            return

        parent_el = self._node_map.get(parent_iid)
        if parent_el is None:
            return

        if not messagebox.askyesno("Confirm Delete",
                                    f"Delete element '{self._local_tag(element.tag)}' and all its children?"):
            return

        parent_el.remove(element)
        # Remove from node_map recursively
        self._remove_iid_recursive(iid)
        self._tree.delete(iid)
        self._attr_tree.delete(*self._attr_tree.get_children())
        self._text_edit.delete("1.0", tk.END)
        self._mark_modified()

    def _remove_iid_recursive(self, iid):
        for child_iid in self._tree.get_children(iid):
            self._remove_iid_recursive(child_iid)
        self._node_map.pop(iid, None)

    # ------------------------------------------------------------------ helpers
    def _mark_modified(self):
        self._modified = True
        fname = os.path.basename(self._file_path) if self._file_path else "untitled.rdl"
        self.title(f"RDL Editor — *{fname}")

    def _set_status(self, msg):
        self._status_var.set(msg)


if __name__ == "__main__":
    app = RDLEditor()
    app.mainloop()
