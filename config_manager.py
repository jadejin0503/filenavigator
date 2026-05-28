import os
import sys
import json
import re
import shutil

# 用于记录「上次使用的 config 所在目录」，exe 复制到桌面时可回退到该目录找 config
_PFN_SAVED_CONFIG_DIR_FILE = None

def _get_saved_config_dir_path():
    """APPDATA\\PFN\\pfn_config_dir.txt 的路径（仅打包后使用）。"""
    global _PFN_SAVED_CONFIG_DIR_FILE
    if _PFN_SAVED_CONFIG_DIR_FILE is not None:
        return _PFN_SAVED_CONFIG_DIR_FILE
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return ""
    _PFN_SAVED_CONFIG_DIR_FILE = os.path.join(appdata, "PFN", "pfn_config_dir.txt")
    return _PFN_SAVED_CONFIG_DIR_FILE


def _get_user_profile_config_paths():
    """返回 (PFN_Config 目录, config.json 完整路径)。优先 %USERPROFILE%，否则回退到 C:\\Users\\<登录名>。"""
    profile = (os.environ.get("USERPROFILE") or "").strip()
    if not profile or not os.path.isdir(profile):
        try:
            import getpass

            username = getpass.getuser()
        except Exception:
            username = os.environ.get("USERNAME", "Default")
        profile = os.path.join(r"C:\Users", username)
    user_config_dir = os.path.join(profile, "PFN_Config")
    user_config_path = os.path.join(user_config_dir, "config.json")
    return user_config_dir, user_config_path


def get_config_path():
    """
    固定使用当前 Windows 登录用户下的 PFN_Config（与用户名对应）：
    %USERPROFILE%\\PFN_Config\\config.json
    （在默认用户目录布局下等价于 C:\\Users\\<当前用户名>\\PFN_Config\\config.json）

    不再从 exe 旁或「上次目录」抢优先级，避免版本/拷贝位置变化导致读写另一份空配置。
    若目录或 config.json 不存在则创建；打包后仍将 config 所在目录写入 %APPDATA%\\PFN\\pfn_config_dir.txt。
    """
    user_config_dir, user_config_path = _get_user_profile_config_paths()
    if not os.path.isdir(user_config_dir):
        try:
            os.makedirs(user_config_dir, exist_ok=True)
        except Exception:
            pass
    if not os.path.isfile(user_config_path):
        try:
            with open(user_config_path, "w", encoding="utf-8") as f:
                json.dump({"favorite_projects": [], "match_rules": {}}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    if getattr(sys, "frozen", False):
        _save_config_dir_for_fallback(user_config_dir)
    return user_config_path


def _save_config_dir_for_fallback(dir_path):
    """打包后：把当前 config 所在目录写入 APPDATA（记录 PFN_Config 等路径，供排查或其它组件参考）。"""
    if not getattr(sys, "frozen", False) or not dir_path:
        return
    saved_file = _get_saved_config_dir_path()
    if not saved_file:
        return
    try:
        parent = os.path.dirname(saved_file)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        with open(saved_file, "w", encoding="utf-8") as f:
            f.write(dir_path)
    except Exception:
        pass


class ConfigManager:
    def __init__(self):
        self.config_path = get_config_path()
        self.data = {"favorite_projects": [], "match_rules": {}}
        self._load()
        self._ensure_defaults()

    @property
    def rules(self):
        return self.data["match_rules"]

    def get_favorites(self):
        return self.data["favorite_projects"]

    def get_todo_product_expanded(self):
        """「我的待办」产品卡片展开状态：{ 产品名: True 展开 / False 收起 }。"""
        st = self.data.get("ui_state")
        if not isinstance(st, dict):
            return {}
        d = st.get("todo_product_expanded")
        if not isinstance(d, dict):
            return {}
        return {str(k): bool(v) for k, v in d.items()}

    def get_todo_subproject_expanded(self):
        """「项目待办」子项目折叠状态：{ sub_key.lower(): True 展开 / False 收起 }。"""
        st = self.data.get("ui_state")
        if not isinstance(st, dict):
            return {}
        d = st.get("todo_subproject_expanded")
        if not isinstance(d, dict):
            return {}
        return {str(k or "").strip().lower(): bool(v) for k, v in d.items() if str(k or "").strip()}

    @staticmethod
    def _normalize_personal_task_attachments_list(raw_list, task_id):
        tid = str(task_id or "").strip()
        if not tid or ".." in tid or "/" in tid or "\\" in tid:
            return []
        out = []
        seen = set()
        if not isinstance(raw_list, list):
            return []
        for x in raw_list:
            s = str(x or "").strip().replace("\\", "/")
            if not s or ".." in s or s.startswith("/"):
                continue
            parts = [p for p in s.split("/") if p and p != ".."]
            if len(parts) == 1:
                rel = f"{tid}/{parts[0]}"
            elif len(parts) == 2 and parts[0] == tid:
                rel = f"{tid}/{parts[1]}"
            else:
                continue
            if ".." in rel or rel in seen:
                continue
            seen.add(rel)
            out.append(rel)
        return out

    @staticmethod
    def _normalize_personal_task_item(raw):
        if not isinstance(raw, dict):
            return None
        tid = str(raw.get("id", "") or "").strip()
        content = str(raw.get("content", "") or "").strip()
        if not tid or not content:
            return None
        status = str(raw.get("status", "未完成") or "未完成").strip()
        if status in ("已完成", "完成", "done", "Done", "DONE"):
            status = "已完成"
        else:
            status = "未完成"
        pri = str(raw.get("priority", "中") or "中").strip()
        if pri not in ("高", "中", "低"):
            pri = "中"
        created_at = str(raw.get("created_at", "") or "").strip()
        completed_at = str(raw.get("completed_at", "") or "").strip()
        due_date = str(raw.get("due_date", "") or "").strip()
        if due_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", due_date):
            due_date = ""
        if status != "已完成":
            completed_at = ""
        attachments = ConfigManager._normalize_personal_task_attachments_list(raw.get("attachments"), tid)
        return {
            "id": tid,
            "content": content,
            "created_at": created_at,
            "status": status,
            "completed_at": completed_at,
            "priority": pri,
            "due_date": due_date,
            "attachments": attachments,
        }

    def get_personal_tasks(self):
        raw = self.data.get("personal_tasks", [])
        if not isinstance(raw, list):
            return []
        out = []
        seen = set()
        for x in raw:
            item = self._normalize_personal_task_item(x)
            if not item:
                continue
            tid = item["id"]
            if tid in seen:
                continue
            seen.add(tid)
            out.append(item)
        return out

    def personal_tasks_attachments_root(self):
        """与 config.json 同目录下：PFN_Data/personal_task_attachments/"""
        base = os.path.dirname(os.path.abspath(self.config_path))
        root = os.path.join(base, "PFN_Data", "personal_task_attachments")
        try:
            os.makedirs(root, exist_ok=True)
        except Exception:
            pass
        return root

    def ensure_personal_task_attachment_dir(self, task_id):
        tid = str(task_id or "").strip()
        if not tid or ".." in tid or "/" in tid or "\\" in tid:
            return ""
        d = os.path.join(self.personal_tasks_attachments_root(), tid)
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return ""
        return d

    def abs_path_personal_task_attachment(self, rel_path):
        rel = str(rel_path or "").strip().replace("\\", "/")
        if not rel or ".." in rel or rel.startswith("/"):
            return ""
        root = os.path.normpath(self.personal_tasks_attachments_root())
        full = os.path.normpath(os.path.join(root, rel))
        try:
            if os.path.commonpath([root, full]) != root:
                return ""
        except ValueError:
            return ""
        return full

    def remove_personal_task_attachments_dir(self, task_id):
        tid = str(task_id or "").strip()
        if not tid or ".." in tid or "/" in tid or "\\" in tid:
            return
        d = os.path.join(self.personal_tasks_attachments_root(), tid)
        if os.path.isdir(d):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _safe_attachment_path_segment(s, max_len=100):
        t = str(s or "").strip().lower()
        t = re.sub(r"[^a-z0-9_.-]+", "_", t).strip("._-")
        if not t:
            t = "sub"
        return t[:max_len]

    @staticmethod
    def _normalize_project_task_attachments_list(raw_list, sub_key, task_id):
        """项目子任务附件相对路径：{safe_sub}/{task_id}/文件名（相对于 project_task_attachments 根）。"""
        sk = ConfigManager._safe_attachment_path_segment(sub_key)
        tid = str(task_id or "").strip()
        if not sk or not tid or ".." in tid or "/" in tid or "\\" in tid:
            return []
        out = []
        seen = set()
        if not isinstance(raw_list, list):
            return []
        for x in raw_list:
            s = str(x or "").strip().replace("\\", "/")
            if not s or ".." in s or s.startswith("/"):
                continue
            parts = [p for p in s.split("/") if p and p != ".."]
            rel = None
            if len(parts) == 1:
                rel = f"{sk}/{tid}/{parts[0]}"
            elif len(parts) == 2:
                if parts[0] == sk:
                    rel = f"{sk}/{tid}/{parts[1]}"
                elif parts[0] == tid:
                    rel = f"{sk}/{tid}/{parts[1]}"
                else:
                    continue
            elif len(parts) == 3 and parts[0] == sk and parts[1] == tid:
                rel = f"{sk}/{tid}/{parts[2]}"
            else:
                continue
            if ".." in rel or rel in seen:
                continue
            seen.add(rel)
            out.append(rel)
        return out

    def project_tasks_attachments_root(self):
        """与 config.json 同目录：PFN_Data/project_task_attachments/"""
        base = os.path.dirname(os.path.abspath(self.config_path))
        root = os.path.join(base, "PFN_Data", "project_task_attachments")
        try:
            os.makedirs(root, exist_ok=True)
        except Exception:
            pass
        return root

    def ensure_project_task_attachment_dir(self, sub_key, task_id):
        sk = self._safe_attachment_path_segment(sub_key)
        tid = str(task_id or "").strip()
        if not sk or not tid or ".." in tid or "/" in tid or "\\" in tid:
            return ""
        d = os.path.join(self.project_tasks_attachments_root(), sk, tid)
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            return ""
        return d

    def abs_path_project_task_attachment(self, rel_path):
        rel = str(rel_path or "").strip().replace("\\", "/")
        if not rel or ".." in rel or rel.startswith("/"):
            return ""
        root = os.path.normpath(self.project_tasks_attachments_root())
        full = os.path.normpath(os.path.join(root, rel))
        try:
            if os.path.commonpath([root, full]) != root:
                return ""
        except ValueError:
            return ""
        return full

    def remove_project_task_attachments_dir(self, sub_key, task_id):
        sk = self._safe_attachment_path_segment(sub_key)
        tid = str(task_id or "").strip()
        if not sk or not tid:
            return
        d = os.path.join(self.project_tasks_attachments_root(), sk, tid)
        if os.path.isdir(d):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass

    def add_personal_task(self, task):
        item = self._normalize_personal_task_item(task)
        if not item:
            return False
        tasks = self.get_personal_tasks()
        for t in tasks:
            if str(t.get("id", "")) == item["id"]:
                return False
        tasks.append(item)
        self.data["personal_tasks"] = tasks
        self.save()
        return True

    def update_personal_task(self, task_id, patch):
        tid = str(task_id or "").strip()
        if not tid or not isinstance(patch, dict):
            return False
        tasks = self.get_personal_tasks()
        changed = False
        for i, t in enumerate(tasks):
            if str(t.get("id", "")) != tid:
                continue
            merged = dict(t)
            for k in ("content", "priority", "status", "completed_at", "due_date", "attachments"):
                if k in patch:
                    merged[k] = patch.get(k)
            item = self._normalize_personal_task_item(merged)
            if not item:
                return False
            tasks[i] = item
            changed = True
            break
        if not changed:
            return False
        self.data["personal_tasks"] = tasks
        self.save()
        return True

    def delete_personal_task(self, task_id):
        tid = str(task_id or "").strip()
        if not tid:
            return False
        tasks = self.get_personal_tasks()
        new_tasks = [t for t in tasks if str(t.get("id", "")) != tid]
        if len(new_tasks) == len(tasks):
            return False
        self.data["personal_tasks"] = new_tasks
        self.save()
        try:
            self.remove_personal_task_attachments_dir(tid)
        except Exception:
            pass
        return True

    def get_personal_due_alert_date(self):
        st = self.data.get("ui_state")
        if not isinstance(st, dict):
            return ""
        pt = st.get("personal_todo")
        if not isinstance(pt, dict):
            return ""
        v = str(pt.get("last_due_alert_date", "") or "").strip()
        return v if re.match(r"^\d{4}-\d{2}-\d{2}$", v) else ""

    def set_personal_due_alert_date(self, date_str):
        v = str(date_str or "").strip()
        if v and not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            return False
        if "ui_state" not in self.data or not isinstance(self.data.get("ui_state"), dict):
            self.data["ui_state"] = {}
        if "personal_todo" not in self.data["ui_state"] or not isinstance(self.data["ui_state"].get("personal_todo"), dict):
            self.data["ui_state"]["personal_todo"] = {}
        self.data["ui_state"]["personal_todo"]["last_due_alert_date"] = v
        self.save()
        return True

    def save_todo_product_expanded_snapshot(self, expanded_map):
        """一次性写入当前内存中的展开状态（收起/展开后立即或关闭窗口时调用）。"""
        if "ui_state" not in self.data or not isinstance(self.data.get("ui_state"), dict):
            self.data["ui_state"] = {}
        clean = {str(k): bool(v) for k, v in (expanded_map or {}).items() if str(k).strip()}
        self.data["ui_state"]["todo_product_expanded"] = clean
        self.save()

    def save_todo_subproject_expanded_snapshot(self, expanded_map):
        """写入子项目折叠状态（收起/展开后或关闭窗口时调用）。"""
        if "ui_state" not in self.data or not isinstance(self.data.get("ui_state"), dict):
            self.data["ui_state"] = {}
        clean = {
            str(k or "").strip().lower(): bool(v)
            for k, v in (expanded_map or {}).items()
            if str(k or "").strip()
        }
        self.data["ui_state"]["todo_subproject_expanded"] = clean
        self.save()

    @staticmethod
    def _todo_hidden_list_to_set(raw) -> set:
        if not isinstance(raw, list):
            return set()
        out = set()
        for x in raw:
            s = str(x or "").strip().lower()
            if s:
                out.add(s)
        return out

    def get_todo_hidden_products(self) -> set:
        """待办列表已隐藏的产品名（小写）。"""
        st = self.data.get("ui_state")
        if not isinstance(st, dict):
            return set()
        return self._todo_hidden_list_to_set(st.get("todo_hidden_products"))

    def get_todo_hidden_subprojects(self) -> set:
        """待办列表已隐藏的子项目 sub_key（小写）。"""
        st = self.data.get("ui_state")
        if not isinstance(st, dict):
            return set()
        return self._todo_hidden_list_to_set(st.get("todo_hidden_subprojects"))

    def hide_todo_product(self, product_name) -> bool:
        """仅从项目待办隐藏产品卡片；不删除 project_management 数据。"""
        try:
            key = str(product_name or "").strip().lower()
            if not key:
                return False
            if "ui_state" not in self.data or not isinstance(self.data.get("ui_state"), dict):
                self.data["ui_state"] = {}
            lst = self.data["ui_state"].get("todo_hidden_products")
            if not isinstance(lst, list):
                lst = []
            if key not in {str(x or "").strip().lower() for x in lst}:
                lst.append(key)
            self.data["ui_state"]["todo_hidden_products"] = lst
            self.save()
            return True
        except Exception as e:
            try:
                print(f"[PFN config] hide_todo_product 失败: {e}", flush=True)
            except Exception:
                pass
            return False

    def hide_todo_subproject(self, sub_key) -> bool:
        """仅从项目待办隐藏子项目；不删除 project_management 数据。"""
        try:
            key = str(sub_key or "").strip().lower()
            if not key:
                return False
            if "ui_state" not in self.data or not isinstance(self.data.get("ui_state"), dict):
                self.data["ui_state"] = {}
            lst = self.data["ui_state"].get("todo_hidden_subprojects")
            if not isinstance(lst, list):
                lst = []
            if key not in {str(x or "").strip().lower() for x in lst}:
                lst.append(key)
            self.data["ui_state"]["todo_hidden_subprojects"] = lst
            self.save()
            return True
        except Exception as e:
            try:
                print(f"[PFN config] hide_todo_subproject 失败: {e}", flush=True)
            except Exception:
                pass
            return False

    def get_todo_filters(self):
        """返回待办筛选状态：{'project': 0-2, 'personal': 0-2}。"""
        st = self.data.get("ui_state")
        if not isinstance(st, dict):
            return {"project": 0, "personal": 0}
        tf = st.get("todo_filters")
        if not isinstance(tf, dict):
            return {"project": 0, "personal": 0}
        out = {"project": 0, "personal": 0}
        for k in ("project", "personal"):
            try:
                v = int(tf.get(k, 0))
            except Exception:
                v = 0
            if v < 0 or v > 2:
                v = 0
            out[k] = v
        return out

    def save_todo_filter(self, tab_key: str, filter_index: int):
        k = str(tab_key or "").strip().lower()
        if k not in ("project", "personal"):
            return False
        try:
            idx = int(filter_index)
        except Exception:
            idx = 0
        if idx < 0 or idx > 2:
            idx = 0
        if "ui_state" not in self.data or not isinstance(self.data.get("ui_state"), dict):
            self.data["ui_state"] = {}
        if "todo_filters" not in self.data["ui_state"] or not isinstance(self.data["ui_state"].get("todo_filters"), dict):
            self.data["ui_state"]["todo_filters"] = {"project": 0, "personal": 0}
        self.data["ui_state"]["todo_filters"][k] = idx
        self.save()
        return True

    def get_pinned_projects(self):
        v = self.data.get("pinned_projects", [])
        return v if isinstance(v, list) else []

    def add_pinned_project(self, name, path):
        name = str(name or "").strip()
        path = os.path.normpath(str(path or "")).replace("/", "\\")
        if not name or not path:
            return False
        pins = self.get_pinned_projects()
        key = (name.lower(), path.lower())
        for p in pins:
            if not isinstance(p, dict):
                continue
            pn = str(p.get("name", "")).strip().lower()
            pp = os.path.normpath(str(p.get("path", ""))).replace("/", "\\").lower()
            if (pn, pp) == key:
                return False
        pins.insert(0, {"name": name, "path": path})
        self.data["pinned_projects"] = pins
        self.save()
        return True

    def remove_pinned_project(self, name, path):
        name = str(name or "").strip().lower()
        path = os.path.normpath(str(path or "")).replace("/", "\\").lower()
        pins = self.get_pinned_projects()
        new_pins = []
        removed = False
        for p in pins:
            if not isinstance(p, dict):
                continue
            pn = str(p.get("name", "")).strip().lower()
            pp = os.path.normpath(str(p.get("path", ""))).replace("/", "\\").lower()
            if not removed and pn == name and pp == path:
                removed = True
                continue
            new_pins.append(p)
        if removed:
            self.data["pinned_projects"] = new_pins
            self.save()
        return removed
    
    def get_fixed_paths(self):
        return self.data.get("fixed_paths", [])

    def get_documentation_paths(self):
        """返回 documentation_paths 配置：common 常用项列表，scan_root、documentation_scan_path 扫描路径。"""
        d = self.data.get("documentation_paths") or {}
        if not isinstance(d, dict):
            return {"common": [], "scan_root": "", "documentation_scan_path": ""}
        return {
            "common": d.get("common") or [],
            "scan_root": (d.get("scan_root") or "").strip(),
            "documentation_scan_path": (d.get("documentation_scan_path") or self.data.get("documentation_scan_path") or "").strip(),
        }

    def set_documentation_paths(self, common=None, scan_root=None, documentation_scan_path=None):
        if "documentation_paths" not in self.data or not isinstance(self.data["documentation_paths"], dict):
            self.data["documentation_paths"] = {"common": [], "scan_root": "", "documentation_scan_path": ""}
        if common is not None:
            self.data["documentation_paths"]["common"] = common
        if scan_root is not None:
            self.data["documentation_paths"]["scan_root"] = str(scan_root).strip()
        if documentation_scan_path is not None:
            self.data["documentation_paths"]["documentation_scan_path"] = str(documentation_scan_path).strip()
        self.save()
    
    def set_fixed_paths(self, paths):
        self.data["fixed_paths"] = paths
        self.save()

    def get_sas_open(self):
        """返回 .sas 打开配置：{"default_app": "sas_eg"|"vscode"|None, "encoding": "utf-8"|"gbk"|"gb2312"}。兼容旧 key sas_open_with。"""
        out = {"default_app": None, "encoding": "utf-8"}
        obj = self.data.get("sas_open")
        if isinstance(obj, dict):
            if obj.get("default_app") in ("sas_eg", "vscode"):
                out["default_app"] = obj["default_app"]
            enc = obj.get("encoding", "utf-8")
            if enc in ("utf-8", "gbk", "gb2312"):
                out["encoding"] = enc
        else:
            v = self.data.get("sas_open_with")
            if v in ("sas_eg", "vscode"):
                out["default_app"] = v
        return out

    def get_sas_open_with(self):
        """兼容旧接口：返回 default_app 或 None"""
        return self.get_sas_open()["default_app"]

    def set_sas_open_with(self, choice):
        """设置 .sas 默认打开方式并写入 sas_open 结构"""
        if choice in ("sas_eg", "vscode"):
            self.set_sas_open(default_app=choice)

    def set_sas_open(self, default_app=None, encoding=None):
        """更新 sas_open 配置（仅更新传入的字段，未传则保留原值）"""
        obj = dict(self.get_sas_open())
        if default_app is not None and default_app in ("sas_eg", "vscode"):
            obj["default_app"] = default_app
        if encoding is not None and encoding in ("utf-8", "gbk", "gb2312"):
            obj["encoding"] = encoding
        self.data["sas_open"] = {"default_app": obj["default_app"], "encoding": obj["encoding"]}
        self.save()

    def get_project_management(self):
        """
        读取 project_management 并做强健清洗，确保 UI 遍历时不会因格式错误/字段缺失崩溃：
        - 任何异常：返回空结构，不抛出
        - 子项目字段缺失：提供默认值（priority/status/tasks/milestones 等）
        - 数据类型不符合：跳过该子项目
        """
        try:
            obj = self.data.get("project_management", {})
            if not isinstance(obj, dict):
                obj = {}
            root_ta = obj.get("root_ta", {})
            subprojects = obj.get("subprojects", {})
            if not isinstance(root_ta, dict):
                root_ta = {}
            if not isinstance(subprojects, dict):
                subprojects = {}

            clean_subs = {}

            def _coerce_tasks(raw):
                if isinstance(raw, list):
                    return raw
                if isinstance(raw, dict):
                    keys = list(raw.keys())
                    if keys and all(str(k).isdigit() for k in keys):
                        out = []
                        for k in sorted(keys, key=lambda x: int(x)):
                            out.append(raw.get(k))
                        return out
                    return list(raw.values()) if raw else []
                return []

            for k, v in subprojects.items():
                if not isinstance(v, dict):
                    try:
                        print(f"[PFN config] 跳过非字典子项目项 key={k!r}", flush=True)
                    except Exception:
                        pass
                    continue
                try:
                    sk = str(k or "").strip().lower()
                    if not sk:
                        continue
                    out = {
                        "subproject_name": str(v.get("subproject_name", "") or ""),
                        "root_name": str(v.get("root_name", "") or ""),
                        "path": str(v.get("path", "") or ""),
                        "status": str(v.get("status", "未完成") or "未完成"),
                        "priority": str(v.get("priority", "中") or "中"),
                        "tasks": _coerce_tasks(v.get("tasks", [])),
                        "milestones": self._normalize_milestones(v.get("milestones")),
                    }
                    if out["status"] not in ("未完成", "已完成"):
                        out["status"] = "未完成"
                    if out["priority"] not in ("高", "中", "低"):
                        out["priority"] = "中"
                    if not isinstance(out["tasks"], list):
                        out["tasks"] = []
                    clean_subs[sk] = out
                except Exception as e:
                    try:
                        print(f"[PFN config] 子项目清洗失败，已跳过 key={k!r}: {e}", flush=True)
                    except Exception:
                        pass
                    continue

            return {"root_ta": root_ta, "subprojects": clean_subs}
        except Exception as e:
            try:
                print(f"[PFN config] get_project_management 失败，已降级为空: {e}", flush=True)
            except Exception:
                pass
            return {"root_ta": {}, "subprojects": {}}

    def get_product_order(self):
        """产品卡片自定义排序：["HRS8427","SHR2004", ...]"""
        v = self.data.get("product_order", [])
        return v if isinstance(v, list) else []

    def set_product_order(self, order_list):
        if not isinstance(order_list, list):
            return False
        out = []
        seen = set()
        for x in order_list:
            s = str(x or "").strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            seen.add(k)
            out.append(s)
        self.data["product_order"] = out
        self.save()
        return True

    def set_root_project_ta(self, root_name, ta):
        root_name = str(root_name or "").strip()
        ta = str(ta or "").strip()
        if not root_name:
            return False
        pm = self.get_project_management()
        if ta:
            pm["root_ta"][root_name] = ta
        else:
            pm["root_ta"].pop(root_name, None)
        self.data["project_management"] = pm
        self.save()
        return True

    def get_root_project_ta(self, root_name):
        root_name = str(root_name or "").strip()
        if not root_name:
            return ""
        pm = self.get_project_management()
        return str(pm["root_ta"].get(root_name, "") or "")

    @staticmethod
    def _normalize_milestones(val):
        """项目时间节点：最终统一为 dict 形式写入 config.json：{ 节点名: 日期字符串 }。
        兼容历史格式：
        - dict: {name: date}
        - list: [{"name":..., "date":...}, ...]
        - str: 多行文本，支持 name: date 或 name：date
        """
        try:
            if val is None:
                return {}
            # 已是目标格式
            if isinstance(val, dict):
                out = {}
                for k, v in val.items():
                    try:
                        n = str(k or "").strip()
                        d = str(v or "").strip()
                        if n and d:
                            out[n] = d
                    except Exception:
                        continue
                return out
            # 旧 list 格式
            if isinstance(val, list):
                out = {}
                for x in val:
                    if not isinstance(x, dict):
                        continue
                    try:
                        n = str(x.get("name", "") or "").strip()
                        d = str(x.get("date", "") or "").strip()
                        if n and d:
                            out[n] = d
                    except Exception:
                        continue
                return out
            # 旧文本格式
            if isinstance(val, str):
                out = {}
                for line in (val or "").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if "：" in line:
                        a, _, b = line.partition("：")
                    elif ":" in line:
                        a, _, b = line.partition(":")
                    else:
                        continue
                    n, d = a.strip(), b.strip()
                    if n and d:
                        out[n] = d
                return out
            return {}
        except Exception as e:
            try:
                print(f"[PFN config] _normalize_milestones 失败，已忽略: {e}", flush=True)
            except Exception:
                pass
            return {}

    def upsert_subproject(self, sub_key, **kwargs):
        try:
            sub_key = str(sub_key or "").strip().lower()
            if not sub_key:
                return False
            pm = self.get_project_management()
            subs = pm["subprojects"]
            cur = subs.get(sub_key, {})
            if not isinstance(cur, dict):
                cur = {}
            raw_ms = cur.get("milestones", [])
            out = {
                "subproject_name": str(cur.get("subproject_name", "") or ""),
                "root_name": str(cur.get("root_name", "") or ""),
                "path": str(cur.get("path", "") or ""),
                "status": str(cur.get("status", "未完成") or "未完成"),
                "priority": str(cur.get("priority", "中") or "中"),
                "tasks": cur.get("tasks", []),
                "milestones": self._normalize_milestones(raw_ms),
            }
            for k in ("subproject_name", "root_name", "path", "status", "priority", "tasks", "milestones"):
                if k in kwargs and kwargs[k] is not None:
                    out[k] = kwargs[k]
            if out["status"] not in ("未完成", "已完成"):
                out["status"] = "未完成"
            if out["priority"] not in ("高", "中", "低"):
                out["priority"] = "中"
            if not isinstance(out["tasks"], list):
                out["tasks"] = []
            out["milestones"] = self._normalize_milestones(out.get("milestones"))
            subs[sub_key] = out
            self.data["project_management"] = pm
            self._sync_project_tasks_from_subprojects(sub_key=sub_key)
            self.save()
            return True
        except Exception as e:
            try:
                print(f"[PFN config] upsert_subproject 失败: {e}", flush=True)
            except Exception:
                pass
            return False

    def remove_subproject(self, sub_key):
        """从 project_management 移除子项目（任务、时间节点）；清理附件；不删除收藏树。"""
        try:
            sub_key = str(sub_key or "").strip().lower()
            if not sub_key:
                return False
            pm = self.get_project_management()
            subs = pm.get("subprojects", {})
            if not isinstance(subs, dict):
                return False
            if sub_key not in subs:
                return False
            info = subs.pop(sub_key)
            tasks = info.get("tasks", []) if isinstance(info, dict) else []
            if isinstance(tasks, list):
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    tid = str(t.get("id", "") or "").strip()
                    if tid:
                        self.remove_project_task_attachments_dir(sub_key, tid)
            sk_safe = self._safe_attachment_path_segment(sub_key)
            if sk_safe:
                sub_dir = os.path.join(self.project_tasks_attachments_root(), sk_safe)
                if os.path.isdir(sub_dir):
                    try:
                        shutil.rmtree(sub_dir, ignore_errors=True)
                    except Exception:
                        pass
            self.data["project_management"] = pm
            pt = self.data.get("project_tasks")
            if isinstance(pt, dict):
                pt.pop(sub_key, None)
            self._sync_project_tasks_from_subprojects()
            self.save()
            return True
        except Exception as e:
            try:
                print(f"[PFN config] remove_subproject 失败: {e}", flush=True)
            except Exception:
                pass
            return False

    def add_favorite(self, project, overwrite=False):
        existing = {p["id"] for p in self.data["favorite_projects"]}
        if overwrite and project["id"] in existing:
            self.data["favorite_projects"] = [
                p for p in self.data["favorite_projects"] if p["id"] != project["id"]
            ]
        if project["id"] not in existing or overwrite:
            self.data["favorite_projects"].append(project)

    def remove_favorite(self, favorite_id):
        self.data["favorite_projects"] = [
            p for p in self.data["favorite_projects"] if p["id"] != favorite_id
        ]

    def save(self):
        try:
            parent = os.path.dirname(os.path.abspath(self.config_path))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            try:
                print(f"[PFN config] 保存 config 失败: {e}", flush=True)
            except Exception:
                pass
            return False

    def reload_config(self):
        """从磁盘重新读取 config.json，使内存中的 project_management 等与文件一致（不写回磁盘）。"""
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        except Exception as e:
            try:
                print(f"[PFN config] reload_config 读取失败，保留内存数据: {e}", flush=True)
            except Exception:
                pass
            return
        # 兼容迁移：若缺少 project_tasks，则由 project_management.subprojects.tasks 派生
        try:
            self._ensure_defaults(save=False)
            self._sync_project_tasks_from_subprojects()
        except Exception as e:
            try:
                print(f"[PFN config] reload_config 迁移/同步失败（已忽略）: {e}", flush=True)
            except Exception:
                pass

    def _load(self):
        # 只从 config_path 读；打包后不读包内 config，这样分发给别人时对方是空项目
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception as e:
                try:
                    print(f"[PFN config] 初次加载 config 失败，使用空默认: {e}", flush=True)
                except Exception:
                    pass
                self.data = {"favorite_projects": [], "match_rules": {}}

    def _ensure_defaults(self, save=True):
        defaults = {
            "aCRF": {
                "path": os.path.join("utility", "documentation", "06_crt_preparation", "062_acrf", "final"),
                "pattern": "aCRF*.pdf",
                "select": "latest",
            },
            "Annotated CRF": {
                "path": os.path.join("utility", "documentation", "02_data_management"),
                "pattern": "*.pdf",
                "contains": ["Annotated CRF", "注释病例报告表", "注释CRF", "aUnique"],
                "select": "latest",
            },
            "protocol": {
                "path": os.path.join("utility", "documentation", "01_protocol"),
                "pattern": "*.doc*",
                "select": "protocol_versions",
            },
            "sap": {
                "path": os.path.join("utility", "documentation", "03_statistics"),
                "pattern": "*.docx",
                "exclude_contains": ["TFL", "shell", "topline", "Topline", "顶线"],
                "select": "latest",
            },
            "shell": {
                "path": os.path.join("utility", "documentation", "03_statistics"),
                "pattern": "*.docx",
                "contains": ["TFL", "shell"],
                "select": "latest",
            },
            "顶线": {
                "path": os.path.join("utility", "documentation", "03_statistics"),
                "pattern": "*.docx",
                "contains": ["topline", "Topline", "顶线"],
                "select": "latest",
            },
            "setup": {
                "path": os.path.join("utility", "documentation"),
                "pattern": "setup.xlsx",
                "select": "exact",
            },
            "SDTM_PDS": {
                "path": os.path.join("utility", "documentation"),
                "pattern": "*SDTM_PDS*.xlsx",
                "select": "latest",
            },
            "ADAM_PDS": {
                "path": os.path.join("utility", "documentation"),
                "pattern": "*ADAM_PDS*.xlsx",
                "select": "latest",
            },
            "PDT": {
                "path": os.path.join("utility", "documentation"),
                "pattern": "*PDT*.xlsx",
                "select": "latest",
            },
            "QCT": {
                "path": os.path.join("utility", "documentation"),
                "pattern": "*QCT*.xlsx",
                "select": "latest",
            },
            "PIT": {
                "path": os.path.join("utility", "documentation"),
                "pattern": "*PIT*.xlsx",
                "select": "latest",
            },
        }
        
        if "match_rules" not in self.data:
            self.data["match_rules"] = {}
            
        # Merge/Overwrite built-in rules
        for k, v in defaults.items():
            self.data["match_rules"][k] = v
            
        # Cleanup old keys if any
        if "注释CRF" in self.data["match_rules"]:
            del self.data["match_rules"]["注释CRF"]
        
        default_paths = [
            "03_reports", "utility/documentation/01_protocol", "utility/documentation/02_data_management",
            "utility/documentation/03_statistics", "utility/documentation/04_review_comments", "07_logs",
        ]
        if "fixed_paths" not in self.data or not self.data["fixed_paths"]:
            self.data["fixed_paths"] = [p.replace("/", os.sep) for p in default_paths]
        else:
            fps = self.data["fixed_paths"]
            if not any("07_logs" in p or "logs" in p for p in fps):
                fps.append("07_logs")
                self.data["fixed_paths"] = fps

        if "documentation_paths" not in self.data:
            self.data["documentation_paths"] = {
                "common": ["setup.xlsx", "SDTM_PDS", "ADAM_PDS", "PDT", "QCT", "PIT"],
                "scan_root": "",
                "documentation_scan_path": "",
            }
        elif isinstance(self.data["documentation_paths"], dict):
            if "common" not in self.data["documentation_paths"]:
                self.data["documentation_paths"]["common"] = ["setup.xlsx", "SDTM_PDS", "ADAM_PDS", "PDT", "QCT", "PIT"]
            if "scan_root" not in self.data["documentation_paths"]:
                self.data["documentation_paths"]["scan_root"] = ""
            if "documentation_scan_path" not in self.data["documentation_paths"]:
                self.data["documentation_paths"]["documentation_scan_path"] = ""

        if "pinned_projects" not in self.data or not isinstance(self.data["pinned_projects"], list):
            self.data["pinned_projects"] = []

        if "product_order" not in self.data or not isinstance(self.data.get("product_order"), list):
            self.data["product_order"] = []

        if "project_management" not in self.data or not isinstance(self.data["project_management"], dict):
            self.data["project_management"] = {"root_ta": {}, "subprojects": {}}
        else:
            pm = self.data["project_management"]
            if "root_ta" not in pm or not isinstance(pm.get("root_ta"), dict):
                pm["root_ta"] = {}
            if "subprojects" not in pm or not isinstance(pm.get("subprojects"), dict):
                pm["subprojects"] = {}

        if "project_tasks" not in self.data or not isinstance(self.data.get("project_tasks"), dict):
            self.data["project_tasks"] = {}

        if "personal_tasks" not in self.data or not isinstance(self.data.get("personal_tasks"), list):
            self.data["personal_tasks"] = []
        else:
            self.data["personal_tasks"] = self.get_personal_tasks()

        if "ui_state" not in self.data or not isinstance(self.data.get("ui_state"), dict):
            self.data["ui_state"] = {}
        else:
            us = self.data["ui_state"]
            if "todo_product_expanded" in us and not isinstance(us.get("todo_product_expanded"), dict):
                us["todo_product_expanded"] = {}
            if "todo_subproject_expanded" in us and not isinstance(us.get("todo_subproject_expanded"), dict):
                us["todo_subproject_expanded"] = {}
            if "todo_hidden_products" in us and not isinstance(us.get("todo_hidden_products"), list):
                us["todo_hidden_products"] = []
            if "todo_hidden_subprojects" in us and not isinstance(us.get("todo_hidden_subprojects"), list):
                us["todo_hidden_subprojects"] = []
            if "todo_filters" in us and not isinstance(us.get("todo_filters"), dict):
                us["todo_filters"] = {"project": 0, "personal": 0}
            if "personal_todo" in us and not isinstance(us.get("personal_todo"), dict):
                us["personal_todo"] = {}
        if "todo_filters" not in self.data["ui_state"] or not isinstance(self.data["ui_state"].get("todo_filters"), dict):
            self.data["ui_state"]["todo_filters"] = {"project": 0, "personal": 0}
        if "todo_hidden_products" not in self.data["ui_state"]:
            self.data["ui_state"]["todo_hidden_products"] = []
        if "todo_hidden_subprojects" not in self.data["ui_state"]:
            self.data["ui_state"]["todo_hidden_subprojects"] = []
        for _k in ("project", "personal"):
            try:
                _v = int(self.data["ui_state"]["todo_filters"].get(_k, 0))
            except Exception:
                _v = 0
            if _v < 0 or _v > 2:
                _v = 0
            self.data["ui_state"]["todo_filters"][_k] = _v
        if "personal_todo" not in self.data["ui_state"] or not isinstance(self.data["ui_state"].get("personal_todo"), dict):
            self.data["ui_state"]["personal_todo"] = {}
        lad = str(self.data["ui_state"]["personal_todo"].get("last_due_alert_date", "") or "").strip()
        if lad and not re.match(r"^\d{4}-\d{2}-\d{2}$", lad):
            self.data["ui_state"]["personal_todo"]["last_due_alert_date"] = ""

        if save:
            self.save()

    def _sync_project_tasks_from_subprojects(self, sub_key: str = None):
        """
        同步生成/更新标准化 project_tasks 字段，避免 UI/外部逻辑读取 project_tasks 时为空。
        project_tasks 结构：
          { "<sub_key>": [ {content, create_time, complete_time, is_completed, priority, project_path, project_name} ] }
        """
        try:
            pm = self.get_project_management()
            subs = pm.get("subprojects", {})
            if not isinstance(subs, dict):
                return
            if "project_tasks" not in self.data or not isinstance(self.data.get("project_tasks"), dict):
                self.data["project_tasks"] = {}

            keys = [sub_key] if sub_key else list(subs.keys())
            for k in keys:
                try:
                    info = subs.get(k, {})
                    if not isinstance(info, dict):
                        continue
                    pri = str(info.get("priority", "中") or "中")
                    if pri not in ("高", "中", "低"):
                        pri = "中"
                    proj_path = str(info.get("path", "") or "")
                    proj_name = str(info.get("subproject_name", "") or "")
                    tasks = info.get("tasks", []) or []
                    if not isinstance(tasks, list):
                        tasks = []
                    out_list = []
                    for t in tasks:
                        if not isinstance(t, dict):
                            continue
                        try:
                            content = str(t.get("content", "") or "").strip()
                            if not content:
                                continue
                            status = str(t.get("status", "未完成") or "未完成").strip()
                            is_completed = status in ("已完成", "完成", "done", "Done", "DONE") or status is True or status == 1
                            created_at = str(t.get("created_at", "") or "").strip()
                            completed_at = str(t.get("completed_at", "") or "").strip()
                            tpri = str(t.get("priority", "") or "").strip()
                            if tpri not in ("高", "中", "低"):
                                tpri = pri
                            out_list.append(
                                {
                                    "content": content,
                                    "create_time": created_at,
                                    "complete_time": completed_at if is_completed and completed_at else (completed_at or None),
                                    "is_completed": bool(is_completed),
                                    "priority": tpri,
                                    "project_path": proj_path,
                                    "project_name": proj_name,
                                }
                            )
                        except Exception:
                            continue
                    self.data["project_tasks"][str(k).strip().lower()] = out_list
                except Exception:
                    continue
        except Exception as e:
            try:
                print(f"[PFN config] _sync_project_tasks_from_subprojects 失败（已忽略）: {e}", flush=True)
            except Exception:
                pass
