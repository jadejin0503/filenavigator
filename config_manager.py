import os
import sys
import json

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


def get_config_path():
    """
    按优先级定位 config.json：
    1. 程序运行目录（exe/脚本所在目录）的 config.json
    2. 上次使用过的 config 所在目录（保存于 APPDATA\\PFN\\pfn_config_dir.txt，便于 exe 复制到桌面后仍找到原配置）
    3. C:\\Users\\<当前用户>\\PFN_Config\\config.json（不存在则创建空配置）
    """
    if getattr(sys, "frozen", False):
        run_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        run_dir = os.path.dirname(os.path.abspath(__file__))

    # 优先级 1：运行目录
    run_config = os.path.join(run_dir, "config.json")
    if os.path.isfile(run_config):
        _save_config_dir_for_fallback(run_dir)
        return run_config

    # 优先级 2：上次使用过的目录（仅打包后）
    if getattr(sys, "frozen", False):
        saved_path = _get_saved_config_dir_path()
        if saved_path and os.path.isfile(saved_path):
            try:
                with open(saved_path, "r", encoding="utf-8") as f:
                    saved_dir = f.read().strip()
                if saved_dir and os.path.isdir(saved_dir):
                    original_config = os.path.join(saved_dir, "config.json")
                    if os.path.isfile(original_config):
                        return original_config
            except Exception:
                pass

    # 优先级 3：用户目录 C:\Users\<用户名>\PFN_Config\
    try:
        import getpass
        username = getpass.getuser()
    except Exception:
        username = os.environ.get("USERNAME", "Default")
    user_config_dir = os.path.join(r"C:\\Users", username, "PFN_Config")
    user_config_path = os.path.join(user_config_dir, "config.json")
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
    _save_config_dir_for_fallback(user_config_dir)
    return user_config_path


def _save_config_dir_for_fallback(dir_path):
    """打包后：把当前使用的 config 所在目录写入 APPDATA，供下次「exe 在别处运行」时作为优先级 2 回退。"""
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
    
    def get_fixed_paths(self):
        return self.data.get("fixed_paths", [])
    
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
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def _load(self):
        # 只从 config_path 读；打包后不读包内 config，这样分发给别人时对方是空项目
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {"favorite_projects": [], "match_rules": {}}

    def _ensure_defaults(self):
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
            
        self.save()
