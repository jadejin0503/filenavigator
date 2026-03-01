import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
import os
import subprocess
import ctypes

class ProjectBrowserDialog(tk.Toplevel):
    def __init__(self, parent, app, on_add):
        super().__init__(parent)
        self.app = app
        self.title("添加项目 - 请选择要收藏的文件夹")
        self.geometry("800x600")
        self.on_add = on_add
        
        self._build_ui()
        
    def _build_ui(self):
        # Treeview
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        self.tree = ttk.Treeview(frame, selectmode="extended")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.configure(yscrollcommand=scroll.set)
        
        # Bind expansion
        self.tree.bind("<<TreeviewOpen>>", self._on_tree_open)
        
        # Populate Roots
        self._populate_roots()
        
        # Bottom Buttons
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=4)
        ttk.Button(btn_frame, text="添加选中项目", command=self._add_selected).pack(side=tk.RIGHT, padx=4)

    def _populate_roots(self):
        roots = self.app.list_children(None)
        for r in roots:
            node_id = self.tree.insert("", tk.END, text=r["name"], open=False)
            self.tree.item(node_id, values=(r["path"], "root"))
            # Add dummy child to make it expand
            self.tree.insert(node_id, tk.END, text="Loading...")

    def _on_tree_open(self, event):
        item_id = self.tree.focus()
        if not item_id:
            return
            
        # Check if already loaded
        children = self.tree.get_children(item_id)
        if children and self.tree.item(children[0], "text") == "Loading...":
            # Remove dummy
            self.tree.delete(children[0])
            
            # Load real children
            values = self.tree.item(item_id, "values")
            if not values:
                return
            path = values[0]
            
            try:
                subdirs = self.app.list_children(path)
                if not subdirs:
                    self.tree.insert(item_id, tk.END, text="(空)")
                    return
                    
                for sub in subdirs:
                    # If leaf, mark it
                    # node values: path, type, is_leaf
                    is_leaf = sub.get("is_leaf", False)
                    node = self.tree.insert(item_id, tk.END, text=sub["name"], open=False)
                    self.tree.item(node, values=(sub["path"], sub["type"], str(is_leaf)))
                    
                    if not is_leaf:
                        self.tree.insert(node, tk.END, text="Loading...")
            except Exception as e:
                print(f"Error loading {path}: {e}")

    def _add_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请选择至少一个项目")
            return
        
        added_count = 0
        for node in selection:
            values = self.tree.item(node, "values")
            if not values:
                continue
            path = values[0]
            # type = values[1]
            is_leaf = (len(values) > 2 and values[2] == "True")
            
            # Allow adding if it looks like a version folder (is_leaf) or user insists?
            # For now, trust the scanner's leaf detection (depth based)
            # Or just allow adding any folder if the user wants
            
            # Construct project object
            # We need an ID and display name
            # ID can be path hash or relative path string
            
            # Try to construct ID from path relative to Z:
            rel = ""
            if path.upper().startswith("Z:\\"):
                rel = path[3:]
            elif path.upper().startswith("Z:/"):
                rel = path[3:]
            else:
                rel = path
                
            pid = rel.replace("\\", "_").replace("/", "_")
            display = os.path.basename(path)
            # Try to get parent name for better display: Project (Version)
            parent = os.path.dirname(path)
            parent_name = os.path.basename(parent)
            if parent_name:
                display = f"{parent_name} ({display})"
            
            # dir_type is the first part
            parts = rel.replace("/", "\\").split("\\")
            dir_type = parts[0] if parts else "unknown"
            
            project = {
                "id": pid,
                "display_name": display,
                "full_path": path,
                "dir_type": dir_type
            }
            
            self.on_add(project)
            added_count += 1
        
        if added_count > 0:
            messagebox.showinfo("成功", f"已添加 {added_count} 个项目")
            self.destroy()
        else:
            messagebox.showwarning("提示", "未添加任何项目")

class MainWindow:
    def __init__(self, app):
        self.app = app
        self.root = app.root
        self.root.title("PFN - 临床试验项目导航")
        self.current_favorite = None
        self.fs_expanded = {}
        self.current_source = "projects"
        self.category_frames = {}
        self.category_lists = {}
        self._build_ui()
        self._render_favorites_groups()

    def _build_ui(self):
        self.root.geometry("1000x700")
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Treeview", font=("微软雅黑", 10))
        style.configure("TLabel", font=("微软雅黑", 10))
        self.root.configure(bg="#F7F8FA")
        
        # Main Layout
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        # Left Sidebar
        left_frame = ttk.Frame(main_paned, width=250)
        main_paned.add(left_frame, weight=1)
        
        title_bar = ttk.Frame(left_frame)
        title_bar.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(title_bar, text="收藏项目库", font=("微软雅黑", 11, "bold")).pack(side=tk.LEFT, anchor=tk.W)
        add_btn = ttk.Button(title_bar, text="+ 添加项目", command=self._add_project)
        add_btn.pack(side=tk.RIGHT)
        
        self.categories_container = ttk.Frame(left_frame)
        self.categories_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        # Right Content
        right_frame = ttk.Frame(main_paned)
        main_paned.add(right_frame, weight=3)
        
        breadcrumb_frame = ttk.Frame(right_frame)
        breadcrumb_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Label(breadcrumb_frame, text="当前项目路径：").pack(side=tk.LEFT)
        self.breadcrumb_label = ttk.Label(breadcrumb_frame, text="-", foreground="#165DFF")
        self.breadcrumb_label.pack(side=tk.LEFT)
        
        self.fs_frame = ttk.Frame(right_frame)
        self.fs_frame.pack(fill=tk.BOTH, expand=True)
        self.fs_tree = ttk.Treeview(self.fs_frame, show="tree", selectmode="extended")
        self.fs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.fs_scroll = ttk.Scrollbar(self.fs_frame, orient="vertical", command=self.fs_tree.yview)
        self.fs_tree.configure(yscrollcommand=self.fs_scroll.set)
        self.fs_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.fs_tree.bind("<<TreeviewOpen>>", self._on_fs_open)
        self.fs_tree.bind("<<TreeviewClose>>", self._on_fs_close)
        self.fs_tree.bind("<<TreeviewSelect>>", self._on_fs_select)
        self.fs_tree.bind("<Double-1>", self._on_fs_double)
        self.fs_tree.bind("<Button-3>", self._on_fs_right_click)
        self.fs_tree.tag_configure("unavailable", foreground="red")
        self.loading_label = ttk.Label(self.fs_frame, text="加载中...", anchor="center")
        
        self.info_frame = ttk.Frame(right_frame)
        self.info_frame.pack(fill=tk.X, pady=(5, 0))
        self.info_type = ttk.Label(self.info_frame, text="请选择文件查看详情")
        self.info_mtime = ttk.Label(self.info_frame, text="")
        self.info_path = ttk.Label(self.info_frame, text="", foreground="blue", cursor="hand2")
        self.info_type.pack(side=tk.LEFT, padx=10)
        self.info_mtime.pack(side=tk.LEFT, padx=10)
        self.info_path.pack(side=tk.RIGHT, padx=10)
        self.info_path.bind("<Button-1>", self._copy_path)
        self.status_label = ttk.Label(right_frame, text="", foreground="#86909C")
        self.status_label.pack(fill=tk.X, padx=10, pady=(2, 0))

    def _convert_path_for_saseg(self, file_path):
        """将 Z 盘等网络路径转为 SAS EG 可识别的映射路径，兼容中文。"""
        path = os.path.normpath(file_path).replace("/", "\\")
        if len(path) >= 2 and path[1] == ":" and path[0].upper() == "Z":
            try:
                mpr = ctypes.windll.mpr
                buf = ctypes.create_unicode_buffer(1024)
                if mpr.WNetGetConnectionW(path[:2] + ":", buf, 1024) == 0:
                    unc = buf.value
                    if unc:
                        return unc.rstrip("\\") + path[2:]
            except Exception:
                pass
        return path

    def update_status(self, msg):
        """更新底部状态栏文本。"""
        self.status_label.configure(text=msg)
        if msg:
            self.root.after(3000, lambda: self.status_label.configure(text=""))

    def show_error(self, msg):
        """弹出错误提示。"""
        messagebox.showerror("打开失败", msg)

    def _open_with_saseg(self, file_path):
        """使用 SAS EG 打开 .sas/.sas7bdat 文件，核心逻辑。支持单路径或路径列表（多选同窗口）。"""
        try:
            seguide_path = r"C:\Program Files\SaS\SASHome\SASEnterpriseGuide\8\SEGuide.exe"
            if not os.path.isfile(seguide_path):
                eg = self.app._find_sas_eg()
                if eg:
                    seguide_path = eg
            paths = [file_path] if isinstance(file_path, str) else file_path
            mapped_paths = [self._convert_path_for_saseg(p) for p in paths]
            subprocess.Popen([seguide_path] + mapped_paths, shell=False)
            if len(mapped_paths) > 1:
                self.update_status(f"正在使用 SAS EG 打开: {len(mapped_paths)} 个文件")
            else:
                self.update_status(f"正在使用 SAS EG 打开: {os.path.basename(paths[0])}")
        except Exception as e:
            error_msg = f"使用 SAS EG 打开文件时出错: {str(e)}"
            self.show_error(error_msg)
            self.update_status(error_msg)

    def _choose_sas_open(self, path_or_paths):
        """选择用 SAS EG 或 VS Code 打开 .sas；若已设默认 SAS EG 则直接打开。"""
        paths = path_or_paths if isinstance(path_or_paths, list) else [path_or_paths]
        paths = [os.path.normpath(p).replace("/", "\\") for p in paths]
        default = self.app.config.get_sas_open_with() if hasattr(self.app.config, "get_sas_open_with") else None
        if default == "sas_eg":
            self._open_with_saseg(paths)
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("选择打开方式")
        dlg.geometry("320x160")
        dlg.transient(self.root)
        dlg.grab_set()
        ttk.Label(dlg, text=os.path.basename(paths[0]) + (" 等 %d 个文件" % len(paths) if len(paths) > 1 else "")).pack(pady=(12, 4))
        ttk.Label(dlg, text="请选择打开方式：").pack(pady=4)
        choice_var = tk.StringVar(value="sas_eg")
        f = ttk.Frame(dlg)
        f.pack(pady=4)
        ttk.Radiobutton(f, text="SAS Enterprise Guide", variable=choice_var, value="sas_eg").pack(anchor=tk.W)
        ttk.Radiobutton(f, text="VS Code", variable=choice_var, value="vscode").pack(anchor=tk.W)
        use_default_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dlg, text="下次默认使用", variable=use_default_var).pack(anchor=tk.W, pady=4)
        def on_ok():
            ch = choice_var.get()
            if use_default_var.get() and hasattr(self.app.config, "set_sas_open_with"):
                self.app.config.set_sas_open_with(ch)
                self.app.config.save()
            dlg.destroy()
            if ch == "sas_eg":
                self._open_with_saseg(paths)
            else:
                try:
                    code_exe = getattr(self.app, "_find_vscode", lambda: None)()
                    if code_exe:
                        subprocess.Popen([code_exe, "-r"] + paths, shell=False)
                    else:
                        for p in paths:
                            self.app.open_file(p)
                    self.update_status("正在用 VS Code 打开: %s" % (os.path.basename(paths[0]) if len(paths) == 1 else "%d 个文件" % len(paths)))
                except Exception as e:
                    self.show_error(str(e))
        def on_cancel():
            dlg.destroy()
        btn_f = ttk.Frame(dlg)
        btn_f.pack(pady=12)
        ttk.Button(btn_f, text="确定", command=on_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_f, text="取消", command=on_cancel).pack(side=tk.LEFT)
        dlg.wait_window()

    def _open_with_vscode(self, paths):
        """用 VS Code 打开路径列表。"""
        code_exe = getattr(self.app, "_find_vscode", lambda: None)()
        if code_exe:
            try:
                subprocess.Popen([code_exe, "-r"] + paths, shell=False)
                self.update_status("正在用 VS Code 打开: %s" % (os.path.basename(paths[0]) if len(paths) == 1 else "%d 个文件" % len(paths)))
            except Exception as e:
                self.show_error(str(e))
        else:
            for p in paths:
                try:
                    self.app.open_file(p)
                except Exception as e:
                    self.show_error(str(e))
                    return
            self.update_status("正在打开: %s" % (os.path.basename(paths[0]) if len(paths) == 1 else "%d 个文件" % len(paths)))

    def _set_default_sas_open(self, choice):
        """设置 .sas 默认打开方式并更新状态。"""
        if hasattr(self.app.config, "set_sas_open_with"):
            self.app.config.set_sas_open_with(choice)
            self.app.config.save()
        self.update_status("已设为默认用 %s 打开 .sas 文件" % ("SAS EG" if choice == "sas_eg" else "VS Code"))

    def _render_favorites_groups(self):
        for w in self.categories_container.winfo_children():
            w.destroy()
        self.category_frames.clear()
        self.category_lists.clear()
        self.favorites = self.app.get_favorites()
        sources = ["projects", "unblinded", "users"]
        for src in sources:
            items = [f for f in self.favorites if f.get("dir_type") == src]
            if not items:
                continue
            frame = ttk.Frame(self.categories_container)
            frame.pack(fill=tk.X, pady=(0, 6))
            header = ttk.Frame(frame)
            header.pack(fill=tk.X)
            title = ttk.Label(header, text=src, foreground="#165DFF")
            title.pack(side=tk.LEFT)
            toggle_btn = ttk.Button(header, text="▾", width=2)
            toggle_btn.pack(side=tk.RIGHT)
            listbox = tk.Listbox(frame, selectmode=tk.SINGLE)
            listbox.pack(fill=tk.X)
            try:
                listbox.configure(font=("微软雅黑", 10), bg="#1F2329", fg="#FFFFFF", selectbackground="#165DFF", selectforeground="#FFFFFF", activestyle="none")
            except Exception:
                pass
            sorted_items = sorted(items, key=lambda x: x.get("display_name", ""))
            for it in sorted_items:
                listbox.insert(tk.END, it.get("display_name", ""))
            listbox.bind("<<ListboxSelect>>", lambda e, s=src: self._on_favorite_select(e, s))
            listbox.bind("<Button-3>", lambda e, s=src: self._on_favorite_right_click(e, s))
            def _toggle():
                if listbox.winfo_ismapped():
                    listbox.pack_forget()
                    toggle_btn.configure(text="▸")
                else:
                    listbox.pack(fill=tk.X)
                    toggle_btn.configure(text="▾")
            toggle_btn.configure(command=_toggle)
            self.category_frames[src] = frame
            self.category_lists[src] = (listbox, sorted_items)
        if self.current_favorite:
            for src, (lb, items) in self.category_lists.items():
                for i, f in enumerate(items):
                    if f.get("id") == self.current_favorite.get("id"):
                        lb.selection_clear(0, tk.END)
                        lb.selection_set(i)
                        break

    def _get_current_favorite(self):
        return self.current_favorite

    def _set_current_favorite(self, fav):
        self.current_favorite = fav
        try:
            self.breadcrumb_label.configure(text=fav.get("full_path", "-"))
        except Exception:
            pass
        self._refresh_views(fav)

    def _refresh_views(self, fav):
        self._refresh_fs(fav)
        self._clear_info()

    def _add_project(self):
        # Scan roots
        # projects = self.app.scan_projects() # Deprecated
        # Pass app to dialog to let it load lazily
        
        def add_callback(project):
            self.app.add_favorite(project)
            self.app.config.save()
            
        dialog = ProjectBrowserDialog(self.root, self.app, add_callback)
        self.root.wait_window(dialog)
        self._render_favorites_groups()

    def _delete_current_favorite(self):
        messagebox.showinfo("提示", "请在列表中右键选中项目进行删除")

    def _delete_favorite_by_id(self, fid):
        self.app.remove_favorite(fid)
        self.app.config.save()
        if self.current_favorite and self.current_favorite.get("id") == fid:
            self.current_favorite = None
        self._render_favorites_groups()

    def _clean_name(self, name):
        import re
        return re.sub(r'^\d+[_-]\s*', '', name)

    def _refresh_fs(self, fav):
        self._show_loading()
        for i in self.fs_tree.get_children():
            self.fs_tree.delete(i)
        base = fav["full_path"]
        logs_path = os.path.join(base, "07_logs")
        logs_unavailable = not os.path.exists(logs_path)
        logs_root = self.fs_tree.insert("", tk.END, text="  🗎 logs", open=False, tags=("unavailable",) if logs_unavailable else ())
        self.fs_tree.item(logs_root, values=(logs_path, "unavailable" if logs_unavailable else "ok"))
        if not logs_unavailable:
            try:
                names = sorted(os.listdir(logs_path))
            except Exception:
                names = []
            for n in names:
                p = os.path.join(logs_path, n)
                if os.path.isfile(p) and p.lower().endswith(".xml"):
                    nid = self.fs_tree.insert(logs_root, tk.END, text=f"  📄 {self._clean_name(os.path.basename(p))}")
                    self.fs_tree.item(nid, values=(p, "file"))
        docs_root = self.fs_tree.insert("", tk.END, text="  📚 Documents", open=False)
        files = self.app.match_files(base)
        keys = ["setup", "SDTM_PDS", "ADAM_PDS", "PDT", "QCT", "PIT"]
        items = []
        for k in keys:
            v = files.get(k)
            if not v:
                continue
            paths = v if isinstance(v, list) else [v]
            for p in paths:
                try:
                    m = os.path.getmtime(p)
                except:
                    m = 0
                items.append((k, p, m))
        items.sort(key=lambda x: (0 if os.path.basename(x[1]).lower() == "setup.xlsx" else 1, -x[2]))
        for k, p, _m in items:
            label = f"  📄 {os.path.basename(p)}"
            nid = self.fs_tree.insert(docs_root, tk.END, text=label)
            self.fs_tree.item(nid, values=(p, "file"))
        for rel in self.app.get_fixed_paths():
            p = os.path.join(base, rel)
            name = self._clean_name(os.path.basename(rel))
            unavailable = not os.path.exists(p)
            label = f"  📁 {name}" if not unavailable else name
            nid = self.fs_tree.insert("", tk.END, text=label, open=False, tags=("unavailable",) if unavailable else ())
            self.fs_tree.item(nid, values=(p, "unavailable" if unavailable else "ok"))
            if not unavailable:
                self.fs_tree.insert(nid, tk.END, text="...")
        pid = fav["id"]
        if pid in self.fs_expanded:
            expanded = self.fs_expanded[pid]
            self._restore_fs_expanded(expanded)
        self._hide_loading()

    def _on_fs_open(self, _e=None):
        item_id = self.fs_tree.focus()
        if not item_id:
            return
        children = self.fs_tree.get_children(item_id)
        if children and self.fs_tree.item(children[0], "text") == "...":
            self.fs_tree.delete(children[0])
            vals = self.fs_tree.item(item_id, "values")
            if not vals:
                return
            path = vals[0]
            try:
                names = sorted(os.listdir(path))
            except Exception:
                names = []
            for n in names:
                p = os.path.join(path, n)
                if os.path.isdir(p):
                    nid = self.fs_tree.insert(item_id, tk.END, text=f"  📁 {self._clean_name(n)}", open=False)
                    self.fs_tree.item(nid, values=(p, "dir"))
                    self.fs_tree.insert(nid, tk.END, text="...")
                else:
                    nid = self.fs_tree.insert(item_id, tk.END, text=f"  📄 {self._clean_name(n)}", open=False)
                    self.fs_tree.item(nid, values=(p, "file"))
        fav = self._get_current_favorite()
        if fav:
            pid = fav["id"]
            s = self.fs_expanded.get(pid, set())
            vals = self.fs_tree.item(item_id, "values")
            if vals:
                s.add(vals[0])
            self.fs_expanded[pid] = s
    
    def _on_fs_close(self, _e=None):
        item_id = self.fs_tree.focus()
        if not item_id:
            return
        fav = self._get_current_favorite()
        if fav:
            pid = fav["id"]
            s = self.fs_expanded.get(pid, set())
            vals = self.fs_tree.item(item_id, "values")
            if vals and vals[0] in s:
                s.discard(vals[0])
            self.fs_expanded[pid] = s

    def _on_fs_select(self, _e=None):
        sel = self.fs_tree.selection()
        if not sel:
            return
        item = self.fs_tree.item(sel[0])
        vals = item.get("values", [])
        if not vals:
            return
        path = vals[0]
        typ = vals[1] if len(vals) > 1 else ""
        if typ == "unavailable":
            return
        self._show_info(path)

    def _on_fs_double(self, _e=None):
        sel = self.fs_tree.selection()
        if not sel:
            return
        item = self.fs_tree.item(sel[0])
        vals = item.get("values", [])
        if not vals:
            return
        path = vals[0]
        typ = vals[1] if len(vals) > 1 else ""
        if typ == "dir":
            try:
                self.app.open_folder(path)
            except Exception as e:
                messagebox.showerror("错误", str(e))
            return
        if typ == "unavailable":
            return
        if path.lower().endswith(".sas") or path.lower().endswith(".sas7bdat"):
            sas_paths = [os.path.normpath(path).replace("/", "\\")]
            for item_id in sel[1:]:
                it = self.fs_tree.item(item_id)
                v = it.get("values", [])
                if v and len(v) > 1 and v[1] != "dir" and v[1] != "unavailable":
                    p = os.path.normpath(v[0]).replace("/", "\\")
                    if (p.lower().endswith(".sas") or p.lower().endswith(".sas7bdat")) and p not in sas_paths and os.path.exists(p):
                        sas_paths.append(p)
            try:
                self._choose_sas_open(sas_paths[0] if len(sas_paths) == 1 else sas_paths)
            except Exception as e:
                messagebox.showerror("错误", str(e))
            return
        try:
            self.loading_label.configure(text="正在打开文件...")
            self._show_loading()
            self._open_path(path)
        except Exception as e:
            ext = os.path.splitext(path)[1].lower()
            if ext in [".xlsx", ".xls", ".csv", ".xml"]:
                messagebox.showerror("错误", "未检测到 Excel 程序，请检查是否安装 Microsoft Office")
                try:
                    self.app.open_folder(os.path.dirname(path))
                except Exception as ee:
                    messagebox.showerror("错误", str(ee))
            elif ext in [".doc", ".docx"]:
                messagebox.showerror("错误", "未检测到 Word 程序，请检查是否安装 Microsoft Office")
                try:
                    self.app.open_folder(os.path.dirname(path))
                except Exception as ee:
                    messagebox.showerror("错误", str(ee))
            else:
                messagebox.showerror("错误", str(e))
        finally:
            self.root.after(1200, self._hide_loading)
    
    def _on_fs_right_click(self, event):
        item_id = self.fs_tree.identify_row(event.y)
        if not item_id:
            return
        self.fs_tree.selection_set(item_id)
        item = self.fs_tree.item(item_id)
        vals = item.get("values", [])
        if not vals:
            return
        path = vals[0]
        menu = tk.Menu(self.root, tearoff=0)
        def open_folder():
            try:
                self.app.open_folder(os.path.dirname(path))
            except Exception as e:
                messagebox.showerror("错误", str(e))
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            open_menu = tk.Menu(menu, tearoff=0)
            open_menu.add_command(label="用 Adobe Acrobat 打开", command=lambda p=path: self.app.open_pdf_with_adobe(p))
            open_menu.add_command(label="用浏览器打开", command=lambda p=path: self.app.open_pdf_in_browser(p))
            menu.add_cascade(label="选择打开方式", menu=open_menu)
        if ext in (".sas", ".sas7bdat"):
            def collect_sas_paths():
                out = []
                for item_id in self.fs_tree.selection():
                    v = self.fs_tree.item(item_id, "values")
                    if not v or (len(v) > 1 and v[1] in ("dir", "unavailable")):
                        continue
                    p = os.path.normpath(v[0]).replace("/", "\\")
                    if (p.lower().endswith(".sas") or p.lower().endswith(".sas7bdat")) and os.path.exists(p) and p not in out:
                        out.append(p)
                return out or [path]
            menu.add_command(label="用 SAS EG 打开", command=lambda: self._open_with_saseg(collect_sas_paths()))
            menu.add_command(label="用 VS Code 打开", command=lambda: self._open_with_vscode(collect_sas_paths()))
            default_menu = tk.Menu(menu, tearoff=0)
            default_menu.add_command(label="SAS EG", command=lambda: self._set_default_sas_open("sas_eg"))
            default_menu.add_command(label="VS Code", command=lambda: self._set_default_sas_open("vscode"))
            menu.add_cascade(label="设置默认打开方式", menu=default_menu)
            menu.add_separator()
        def copy_path():
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(path)
                messagebox.showinfo("提示", "路径已复制")
            except Exception as e:
                messagebox.showerror("错误", str(e))
        menu.add_command(label="打开所在文件夹", command=open_folder)
        menu.add_command(label="复制路径", command=copy_path)
        menu.post(event.x_root, event.y_root)

    def _open_path(self, path):
        try:
            self.app.open_file(path)
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _clear_info(self):
        self.info_type.configure(text="请选择文件查看详情")
        self.info_mtime.configure(text="")
        self.info_path.configure(text="")

    def _show_info(self, path):
        ext = os.path.splitext(path)[1].lower()
        if os.path.isdir(path):
            t = "文件夹"
        elif ext in [".xlsx", ".xls", ".csv", ".xml"]:
            t = "Excel"
        elif ext in [".pdf"]:
            t = "PDF"
        elif ext in [".doc", ".docx"]:
            t = "Word"
        else:
            t = "文件"
        try:
            from datetime import datetime
            m = os.path.getmtime(path)
            mstr = datetime.fromtimestamp(m).strftime('%Y-%m-%d %H:%M')
        except:
            mstr = "-"
        self.info_type.configure(text=t)
        self.info_mtime.configure(text=mstr)
        self.info_path.configure(text=path)

    def _copy_path(self, _e=None):
        text = self.info_path.cget("text")
        if not text:
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("提示", "路径已复制")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _restore_fs_expanded(self, expanded):
        def expand_matching(parent):
            for nid in self.fs_tree.get_children(parent):
                vals = self.fs_tree.item(nid, "values")
                if vals and vals[0] in expanded:
                    self.fs_tree.item(nid, open=True)
                    self._on_fs_open()
                    expand_matching(nid)
        expand_matching("")
    
    def _show_loading(self):
        try:
            self.loading_label.place(relx=0.5, rely=0.5, anchor="center")
        except Exception:
            pass
    
    def _hide_loading(self):
        try:
            self.loading_label.place_forget()
        except Exception:
            pass
    
    def _on_favorite_select(self, event=None, source=None):
        if not source or source not in self.category_lists:
            return
        lb, items = self.category_lists[source]
        sel = lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(items):
            self._set_current_favorite(items[idx])
    
    def _on_favorite_right_click(self, event, source=None):
        if not source or source not in self.category_lists:
            return
        lb, items = self.category_lists[source]
        index = lb.nearest(event.y)
        if index < 0:
            return
        lb.selection_clear(0, tk.END)
        lb.selection_set(index)
        menu = tk.Menu(self.root, tearoff=0)
        def _delete_selected():
            if index < len(items):
                fav = items[index]
                if messagebox.askyesno("确认", f"确定要移除 {fav['display_name']} 吗？"):
                    self.app.remove_favorite(fav["id"])
                    self.app.config.save()
                    self.current_favorite = None
                    self._render_favorites_groups()
        menu.add_command(label="删除", command=_delete_selected)
        menu.post(event.x_root, event.y_root)
    
    def _switch_source(self, source):
        self.current_source = source
        self._update_tab_styles()
        self._render_favorites_list()
        # reset selection on tab change
        self.current_favorite = None
        for i in self.fs_tree.get_children():
            self.fs_tree.delete(i)
        self._clear_info()
    
    def _update_tab_styles(self):
        for name, btn in self.tab_buttons.items():
            if name == self.current_source:
                try:
                    btn.configure(style="")
                    btn.configure(text=name + " ︳")
                except Exception:
                    pass
            else:
                try:
                    btn.configure(style="")
                except Exception:
                    pass
