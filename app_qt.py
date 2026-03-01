"""
PFN - 临床试验项目导航工具 (PyQt6)
支持 Z 盘网络路径，左侧收藏项目库（projects/unblinded/users 分类 + 项目层级聚合），右侧文件树。
"""
import re
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QMenu, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QFrame, QMessageBox, QSizePolicy, QStyle, QDialog,
    QStyledItemDelegate, QGraphicsDropShadowEffect, QAbstractItemView,
    QRadioButton, QCheckBox, QButtonGroup,
)
from PyQt6.QtCore import Qt, QSize, QTimer, QEvent
from PyQt6.QtGui import QGuiApplication, QColor
import sys
import os
import subprocess
import ctypes
import time
import threading
from config_manager import ConfigManager
from zdrive_scanner import ZDriveScanner, get_source_id_from_path
from file_matcher import FileMatcher
from icons_pfn import (
    icon_folder_yellow, icon_heart_outlined, icon_product_outlined,
    icon_for_file_soft, icon_check_circle_outlined, icon_home_outlined,
)


def _strip_prefix(name):
    """移除文件名/文件夹名前的序号前缀，如 03_ -> 空, 07_logs -> logs"""
    return re.sub(r"^\d+_", "", name) if name else name


def _mtime_str(path):
    """返回修改时间 YYYY-MM-DD HH:MM，失败返回空"""
    try:
        m = os.path.getmtime(path)
        return __import__("datetime").datetime.fromtimestamp(m).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _file_display_with_mtime(path):
    """文件名 + 修改时间，时间 #86909C 风格（树节点用单色）"""
    name = _strip_prefix(os.path.basename(path))
    try:
        m = os.path.getmtime(path)
        mstr = __import__("datetime").datetime.fromtimestamp(m).strftime("%Y-%m-%d %H:%M")
        return f"{name}    {mstr}"
    except Exception:
        return name


def _add_logs_xml_children(parent_item, logs_path, style):
    """logs 节点：加载 .xml 文件作为子项，双列 [name, mtime]"""
    try:
        names = sorted(os.listdir(logs_path))
        for n in names:
            if not n.lower().endswith(".xml"):
                continue
            fp = os.path.join(logs_path, n)
            if os.path.isfile(fp):
                name = _strip_prefix(n)
                mtime = _mtime_str(fp)
                c = QTreeWidgetItem([name, mtime])
                c.setData(0, Qt.ItemDataRole.UserRole, fp)
                c.setData(1, Qt.ItemDataRole.UserRole, "file")
                c.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                c.setToolTip(0, fp)
                c.setIcon(0, icon_for_file_soft(fp, 14))
                parent_item.addChild(c)
    except Exception:
        pass


def _parse_display_name(display_name):
    """解析 display_name：'SHR6508_301 (csr_01)' -> (main='SHR6508_301', sub='csr_01')"""
    m = re.match(r"^(.+?)\s*\(([^)]+)\)\s*$", display_name or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return display_name or "", None


def _source_root_name(dir_type):
    """dir_type 对应的固定根目录名（projects / unblinded / users）。"""
    if dir_type == "projects" or (dir_type and "projects" in dir_type and "users" not in (dir_type or "")):
        return "projects"
    if dir_type == "unblinded" or (dir_type and "unblinded" in dir_type and "users" not in (dir_type or "")):
        return "unblinded"
    if dir_type == "users" or (dir_type and dir_type.startswith("users")):
        return "users"
    return None


def _path_segments_after_root(path, dir_type):
    """跳过 Z:\\projects\\ 或 Z:\\users\\userid\\projects\\ 根目录，返回后续路径段列表。"""
    path = os.path.normpath(path).replace("/", "\\")
    if path.upper().startswith("Z:\\"):
        rel = path[3:]
    else:
        rel = path
    parts = [p for p in rel.split("\\") if p]
    root_name = _source_root_name(dir_type)
    if not root_name or not parts:
        return parts
    # users/userid/projects 或 users/userid/unblinded：跳过 users、userid、projects 或 unblinded 共三段，再取 product/trial/subdir
    if root_name == "users" and dir_type and "-" in dir_type:
        if len(parts) >= 4:
            return parts[4:]  # 跳过 users, userid, projects|unblinded，得到 product, trial, subdir...
        if len(parts) >= 3:
            return parts[3:]
        return []
    # projects / unblinded：只跳过根名及重复根名
    i = 0
    while i < len(parts) and parts[i].lower() != root_name:
        i += 1
    if i >= len(parts):
        return parts
    j = i + 1
    while j < len(parts) and parts[j].lower() == root_name:
        j += 1
    return parts[j:] if j < len(parts) else []


def _product_trial_from_path(path, dir_type):
    """从路径解析：第一级=产品名，第二级=试验名（产品名_数字），第三级及以后=子目录。返回 (product, trial, subdir_label)。
    users 下仅两层时（trial/subdir）：从 trial 名解析产品前缀（如 HRS7450_201 → 产品 HRS7450），便于按产品归类。"""
    segments = _path_segments_after_root(path, dir_type)
    product = segments[0] if len(segments) >= 1 else None
    trial = segments[1] if len(segments) >= 2 else None
    subdir = segments[2] if len(segments) >= 3 else None
    if product and _source_root_name(dir_type) and product.lower() == _source_root_name(dir_type):
        product = segments[1] if len(segments) >= 2 else None
        trial = segments[2] if len(segments) >= 3 else None
        subdir = segments[3] if len(segments) >= 4 else None
    # users 下仅两层（trial 文件夹 + 子目录）：从 trial 名解析产品前缀，实现按产品归类
    root_name = _source_root_name(dir_type)
    if root_name == "users" and dir_type and "-" in dir_type and len(segments) == 2:
        trial_name, subdir_name = segments[0], segments[1]
        product = trial_name.rsplit("_", 1)[0] if "_" in trial_name else trial_name
        trial = trial_name
        subdir = subdir_name
    return (product or "unknown", trial, subdir)


# 全局样式：选中 #165DFF 文字 + #E8F3FF 背景，hover #D1E5FF
_SELECTED_STYLE = (
    "color:#165DFF; background:#E8F3FF;"
)
_HOVER_STYLE = "background:#D1E5FF;"
_NORMAL_STYLE = "color:#4E5969;"
_LEFT_TREE_STYLE = (
    "QTreeWidget{font-size:12px; color:#4E5969; background:#FFF; border:1px solid #E5E6EB; border-radius:8px; padding:4px;} "
    "QTreeWidget::item{height:24px; padding-left:6px;} "
    "QTreeWidget::item:hover{background:#D1E5FF; color:#165DFF;} "
    "QTreeWidget::item:selected{background:#E8F3FF; color:#165DFF;} "
)
_RIGHT_TREE_STYLE = (
    "QTreeWidget{font-size:12px; color:#4E5969; background:#FFF; border:1px solid #E5E6EB; border-radius:8px;} "
    "QTreeWidget::item{height:24px; padding-left:6px; padding-right:8px;} "
    "QTreeWidget::item:hover{background:#D1E5FF; color:#165DFF;} "
    "QTreeWidget::item:selected{background:#E8F3FF; color:#165DFF;} "
)


class _TimeColumnDelegate(QStyledItemDelegate):
    """右侧文件树第 2 列：时间右对齐、浅灰 11px、右侧 padding"""
    def paint(self, painter, option, index):
        if index.column() != 1:
            super().paint(painter, option, index)
            return
        from PyQt6.QtGui import QFont  # pyright: ignore[reportMissingImports]
        painter.save()
        font = option.font
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#86909C"))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = option.rect.adjusted(10, 0, -20, 0)  # 与文件名 10px 间距，右侧留白
        flags = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(rect, int(flags), text)
        painter.restore()

class PFNCore:
    def __init__(self):
        self.config = ConfigManager()
        self.scanner = ZDriveScanner()
        self.matcher = FileMatcher()
        self.fs_expanded = {}
        self._match_cache = {}
        self._sas_eg_pywin32_missing = False
    
    def get_favorites(self):
        return self.config.get_favorites()
    
    def add_favorite(self, project, overwrite=False):
        self.config.add_favorite(project, overwrite=overwrite)
        self.config.save()
        self._match_cache.clear()
    
    def remove_favorite(self, fid):
        self.config.remove_favorite(fid)
        self.config.save()
        self._match_cache.clear()
    
    def list_children(self, path=None):
        return self.scanner.list_children(path, ["projects", "unblinded", "users"])
    
    def get_fixed_paths(self):
        return self.config.get_fixed_paths()
    
    def match_files(self, project_path):
        key = os.path.normpath(project_path).replace("/", "\\")
        if key in self._match_cache:
            return self._match_cache[key]
        result = self.matcher.match(project_path, self.config.rules)
        self._match_cache[key] = result
        return result

    def open_sas_with(self, path_or_paths, choice):
        """用指定方式打开 .sas 文件（可多选同窗口）。choice 仅为 'vscode' 时由此处理；SAS EG 由主窗口 _open_with_saseg 唯一处理。"""
        paths = path_or_paths if isinstance(path_or_paths, list) else [path_or_paths]
        paths = [os.path.normpath(p).replace("/", "\\") for p in paths]
        for p in paths:
            if not os.path.exists(p):
                return False, "文件路径不存在"
        if choice != "vscode":
            return False, "SAS EG 请通过主界面打开"
        exe = self._find_vscode()
        if not exe:
            return False, "未找到 VS Code，请安装后重试"
        try:
            args = [exe, "-r"] + paths
            subprocess.Popen(args, shell=False)
            return True, None
        except Exception as e:
            return False, f"启动失败: {e}"
    
    def open_file(self, path):
        """
        使用 Windows 原生 ShellExecute 打开文件，支持 Z 盘网络路径。
        返回 (success, error_msg)：成功时 error_msg 为 None。
        .sas 若已配置默认打开方式则用 open_sas_with，否则兜底尝试 VSCode/SAS EG/ShellExecute。
        """
        path = os.path.normpath(path).replace("/", "\\")
        if not os.path.exists(path):
            return False, "文件路径不存在"
        ext = os.path.splitext(path)[1].lower()
        if ext == ".sas":
            default = self.config.get_sas_open_with()
            if default == "vscode":
                ok, err = self.open_sas_with(path, default)
                if ok:
                    return True, None
            code = self._find_vscode()
            if code:
                try:
                    subprocess.Popen([code, path], shell=False)
                    return True, None
                except Exception:
                    pass
            success, err = self._shell_open(path)
            if success:
                return True, None
            return False, err or "未找到 VSCode，请安装后重试；或双击文件在弹窗中选择 SAS EG 打开"
        if ext == ".egp":
            eg = self._find_sas_eg()
            if eg:
                try:
                    subprocess.Popen([eg, path], shell=False)
                    return True, None
                except Exception as e:
                    return False, f"启动 SAS 失败: {e}"
            return False, "未找到 SAS Enterprise Guide 程序"
        # Excel/Word/XML 等：优先 ShellExecute，由系统关联程序打开
        if ext in [".xlsx", ".xls", ".csv", ".xml"]:
            success, err = self._shell_open(path)
            if success:
                return True, None
            return False, err or "无法打开 Excel 文件，请确认已安装 Microsoft Excel"
        if ext in [".doc", ".docx"]:
            success, err = self._shell_open(path)
            if success:
                return True, None
            return False, err or "无法打开 Word 文件，请确认已安装 Microsoft Word"
        # 其他文件：ShellExecute 或 os.startfile
        success, err = self._shell_open(path)
        if success:
            return True, None
        try:
            os.startfile(path)
            return True, None
        except Exception as e:
            return False, str(e)

    def _shell_open(self, path):
        """使用 ShellExecuteW 打开文件，返回 (success, error_msg)"""
        try:
            ret = ctypes.windll.Shell32.ShellExecuteW(None, "open", path, None, None, 1)
            if ret > 32:
                return True, None
            err_map = {0: "系统内存不足", 2: "文件不存在", 3: "路径无效",
                       5: "拒绝访问", 26: "共享冲突", 27: "文件名/扩展名太长", 31: "无关联程序"}
            return False, err_map.get(ret, f"ShellExecute 返回码 {ret}")
        except Exception as e:
            return False, str(e)

    def open_xml_with_excel(self, path):
        """
        XML 文件：无弹窗，直接用 Excel 打开。
        不经过 ShellExecute，避免 .xml 未关联时弹出「选择应用」对话框。
        """
        path = os.path.normpath(path).replace("/", "\\")
        if not os.path.exists(path):
            return False, "文件路径不存在"
        excel = self._find_excel()
        if not excel:
            return False, "未找到 Microsoft Excel，请确认已安装"
        try:
            subprocess.Popen([excel, path], shell=False)
            return True, None
        except Exception as e:
            return False, str(e)
    
    def _find_excel(self):
        """查找 Excel 可执行文件：先注册表，再常见路径"""
        import shutil
        try:
            import winreg
            for hive, subkey in [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\excel.exe"),
            ]:
                try:
                    k = winreg.OpenKey(hive, subkey)
                    val, _ = winreg.QueryValueEx(k, "")
                    winreg.CloseKey(k)
                    if val and os.path.exists(val):
                        return val
                except Exception:
                    continue
        except ImportError:
            pass
        candidates = [
            r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files\Microsoft Office\root\Office15\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\root\Office15\EXCEL.EXE",
            r"C:\Program Files\Microsoft Office\Office16\EXCEL.EXE",
            r"C:\Program Files (x86)\Microsoft Office\Office16\EXCEL.EXE",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return shutil.which("excel") or None

    @staticmethod
    def _escape_explorer_path(path: str) -> str:
        """对长路径/含双引号路径做转义，供 explorer.exe 参数使用。"""
        path = os.path.normpath(path).replace("/", "\\")
        return path.replace('"', '""')

    def open_folder(self, folder_path, select_path=None):
        """打开文件夹（可选：在资源管理器中选中文件）。

        - select_path 不为空时：explorer.exe /select,"path" 打开并选中文件。
        - 否则：优先复用已打开资源管理器窗口 Navigate，失败则 explorer.exe /e,"path"。
        路径做转义处理，兼容长路径与 Z:\\ 等网络路径。
        """
        folder_path = os.path.normpath(folder_path).replace("/", "\\")
        if select_path:
            select_path = os.path.normpath(select_path).replace("/", "\\")
            if not os.path.exists(select_path):
                raise FileNotFoundError("路径无效或不可访问")
            escaped = self._escape_explorer_path(select_path)
            cmd = f'explorer.exe /select,"{escaped}"'
            try:
                subprocess.Popen(cmd, shell=True)
                return
            except Exception:
                try:
                    ctypes.windll.Shell32.ShellExecuteW(None, "open", "explorer.exe", f'/select,"{escaped}"', None, 1)
                    return
                except Exception:
                    raise RuntimeError("无法打开文件夹，请检查路径或网络")

        if not os.path.exists(folder_path):
            raise FileNotFoundError("路径无效或不可访问")

        # 网络路径（Z: 或 UNC）不用已有窗口，避免 Navigate 失败后仍停在文档目录
        is_network = (
            (len(folder_path) >= 2 and folder_path[1] == ":" and folder_path[0].upper() not in "ABC")
            or folder_path.startswith("\\\\")
        )
        if not is_network and self._navigate_existing_explorer(folder_path):
            return
        escaped = self._escape_explorer_path(folder_path)
        cmd = f'explorer.exe /e,"{escaped}"'
        try:
            subprocess.Popen(cmd, shell=True)
        except Exception:
            try:
                ctypes.windll.Shell32.ShellExecuteW(None, "open", "explorer.exe", f'/e,"{escaped}"', None, 1)
            except Exception:
                raise RuntimeError("无法打开文件夹，请检查路径或网络")

    def _navigate_existing_explorer(self, folder_path):
        """若存在已打开的资源管理器则在其中导航，返回 True"""
        try:
            import win32com.client
            sh = win32com.client.Dispatch("Shell.Application")
            for w in sh.Windows():
                try:
                    if "explorer" in (getattr(w, "FullName", "") or "").lower():
                        w.Navigate(folder_path)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _find_vscode(self):
        """查找 VSCode 可执行文件"""
        import shutil
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
        ]
        for p in candidates:
            if p and os.path.exists(p):
                return p
        return shutil.which("code") or None

    def open_pdf_with_adobe(self, path):
        path = os.path.normpath(path).replace("/", "\\")
        if not os.path.exists(path):
            return False, "文件路径不存在"
        candidates = [
            r"C:\Program Files\Adobe\Acrobat DC\Acrobat\Acrobat.exe",
            r"C:\Program Files\Adobe\Acrobat\Acrobat.exe",
            r"C:\Program Files\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
            r"C:\Program Files (x86)\Adobe\Acrobat Reader DC\Reader\AcroRd32.exe",
        ]
        for exe in candidates:
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe, path], shell=False)
                    return True, None
                except Exception as e:
                    return False, str(e)
        success, err = self._shell_open(path)
        return (True, None) if success else (False, err or "未找到 Adobe Acrobat")

    def open_pdf_in_browser(self, path):
        path = os.path.normpath(path).replace("/", "\\")
        if not os.path.exists(path):
            return False, "文件路径不存在"
        candidates = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for exe in candidates:
            if os.path.exists(exe):
                try:
                    subprocess.Popen([exe, path], shell=False)
                    return True, None
                except Exception as e:
                    return False, str(e)
        success, err = self._shell_open(path)
        return (True, None) if success else (False, err or "未找到浏览器")

    @staticmethod
    def _resolve_lnk(lnk_path):
        """使用 pywin32 解析 .lnk 快捷方式，返回目标 exe 路径；失败或未安装 pywin32 返回 None。"""
        if not lnk_path or not os.path.isfile(lnk_path):
            return None
        try:
            import win32com.client
            ws = win32com.client.Dispatch("WScript.Shell")
            scut = ws.CreateShortCut(lnk_path)
            target = getattr(scut, "TargetPath", None) or ""
            target = os.path.normpath(target).replace("/", "\\")
            if target and os.path.isfile(target) and target.lower().endswith(".exe"):
                return target
            return None
        except ImportError:
            return None
        except Exception:
            return None

    def _find_sas_eg(self):
        """优先通过开始菜单 .lnk 解析真实 exe 路径（需 pywin32），否则回退到固定路径。"""
        self._sas_eg_pywin32_missing = False
        lnk_candidates = [
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\SAS\SAS Enterprise Guide 8.3 (64-bit).lnk",
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\SAS\SAS Enterprise Guide 8.2 (64-bit).lnk",
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\SAS\SAS Enterprise Guide 8.1 (64-bit).lnk",
            r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\SAS\SAS Enterprise Guide 8.0 (64-bit).lnk",
        ]
        for lnk in lnk_candidates:
            if not os.path.isfile(lnk):
                continue
            try:
                import win32com.client
                exe = self._resolve_lnk(lnk)
                if exe:
                    return exe
            except ImportError:
                self._sas_eg_pywin32_missing = True
                break
        exe_candidates = [
            r"C:\Program Files\SASHome\SASEnterpriseGuide\8.3\SEGuide.exe",
            r"C:\Program Files\SASHome\SASEnterpriseGuide\8.2\SEGuide.exe",
            r"C:\Program Files\SASHome\SASEnterpriseGuide\8.1\SEGuide.exe",
            r"C:\Program Files\SASHome\SASEnterpriseGuide\8.0\SEGuide.exe",
        ]
        for p in exe_candidates:
            if os.path.exists(p):
                return p
        return None


class SasOpenWithDialog(QDialog):
    """双击 .sas 时「选择打开方式」弹窗：SAS EG / VS Code，可勾选「下次默认使用」。default_app 用于预选已保存的默认。"""

    def __init__(self, parent, file_name, default_app=None):
        super().__init__(parent)
        self.setWindowTitle("选择打开方式")
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addWidget(QLabel(file_name))
        layout.addWidget(QLabel("请选择打开方式："))
        self.radio_eg = QRadioButton("SAS Enterprise Guide")
        self.radio_vscode = QRadioButton("VS Code")
        if default_app == "vscode":
            self.radio_vscode.setChecked(True)
        else:
            self.radio_eg.setChecked(True)
        bg = QButtonGroup(self)
        bg.addButton(self.radio_eg)
        bg.addButton(self.radio_vscode)
        layout.addWidget(self.radio_eg)
        layout.addWidget(self.radio_vscode)
        self.cb_default = QCheckBox("下次默认使用")
        self.cb_default.setChecked(True)
        layout.addWidget(self.cb_default)
        btns = QHBoxLayout()
        btns.addStretch()
        ok_btn = QPushButton("确定")
        cancel_btn = QPushButton("取消")
        ok_btn.setStyleSheet("background-color:#165DFF; color:white; border:none; border-radius:4px; padding:6px 16px;")
        cancel_btn.setStyleSheet("border:1px solid #DCDEE3; border-radius:4px; padding:6px 16px;")
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(cancel_btn)
        btns.addWidget(ok_btn)
        layout.addLayout(btns)
        self.setStyleSheet("QDialog{font-size:12px; color:#1F2329;} QLabel{color:#1F2329;}")

    def get_choice(self):
        return "vscode" if self.radio_vscode.isChecked() else "sas_eg"

    def get_use_default(self):
        return self.cb_default.isChecked()


class QtMainWindow(QMainWindow):
    # SAS EG 自动化等待时间（精准等待 + 缩短启动到展开间隔）
    SHORT_WAIT = 0.2   # 短等待（控件就绪）
    MEDIUM_WAIT = 0.6  # 中等等待（节点展开/界面刷新）
    LONG_WAIT = 2.5    # 长等待（文件加载）
    MAX_EG_START_WAIT = 25   # EG 启动后等待服务器树就绪的最大秒数（兜底）
    TREE_CHECK_INTERVAL = 0.5  # 服务器树就绪检测间隔（秒）

    def __init__(self, core: PFNCore):
        super().__init__()
        self.core = core
        self.current_fav = None
        self._showing_utility = False
        self._tree_cache = {}  # fav_id -> 已加载标记，切换回时可直接用缓存避免重复构建
        self.setWindowTitle("PFN - 临床试验项目导航 (PyQt6)")
        self.resize(1100, 720)
        self._build_ui()
        self._load_favorites()
        QTimer.singleShot(800, self._check_pywin32_at_startup)

    def _check_pywin32_at_startup(self):
        """启动时校验 pywin32，缺失则提示安装（解析 .lnk、SAS EG 等依赖）。"""
        try:
            import win32com.client
            return
        except ImportError:
            pass
        self.statusBar().showMessage("建议安装 pywin32 以支持快捷方式解析、SAS EG 路径识别等：pip install pywin32", 8000)
    
    def _build_ui(self):
        container = QWidget()
        self.setCentralWidget(container)
        root_layout = QHBoxLayout(container)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)
        
        left = QWidget()
        left.setMinimumWidth(280)
        left.setMaximumWidth(280)
        left.setStyleSheet("background:#FAFBFC; border-right:1px solid #E5E6EB;")
        left_layout = QVBoxLayout(left)
        self.utility_path = os.path.normpath("Z:\\projects\\utility").replace("/", "\\")
        utility_frame = QFrame()
        utility_frame.setStyleSheet(
            "QFrame#utilityFrame { background:#F5F7FA; border-radius:8px; padding:6px 12px; min-height:24px; } "
            "QFrame#utilityFrame:hover { background:#EBEDF0; } "
            "QLabel#utilityLabel { color:#1F2329; font-family:'Microsoft YaHei'; font-size:12px; background:transparent; } "
        )
        utility_frame.setObjectName("utilityFrame")
        utility_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        util_shadow = QGraphicsDropShadowEffect()
        util_shadow.setBlurRadius(4)
        util_shadow.setXOffset(0)
        util_shadow.setYOffset(2)
        util_shadow.setColor(QColor(0, 0, 0, 13))
        utility_frame.setGraphicsEffect(util_shadow)
        utility_layout = QHBoxLayout(utility_frame)
        utility_layout.setContentsMargins(12, 6, 12, 6)
        utility_label = QLabel("Utility 公共目录")
        utility_label.setObjectName("utilityLabel")
        utility_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        utility_label.setStyleSheet("color:#1F2329; font-family:'Microsoft YaHei'; font-size:12px; background:transparent;")
        utility_label.setToolTip("点击在右侧展示该目录")
        utility_layout.addWidget(utility_label, 1)
        utility_frame.mousePressEvent = lambda e: self._on_utility_clicked()
        left_layout.addWidget(utility_frame)
        header = QHBoxLayout()
        header.setSpacing(0)
        header.setContentsMargins(0, 0, 0, 0)
        fav_card = QFrame()
        fav_card.setStyleSheet(
            "QFrame#favCard { background:#F0F2F5; border-radius:6px; padding:6px 10px; } "
            "QFrame#favCard:hover { background:#E5E6EB; } "
        )
        fav_card.setObjectName("favCard")
        fav_shadow = QGraphicsDropShadowEffect()
        fav_shadow.setBlurRadius(6)
        fav_shadow.setXOffset(0)
        fav_shadow.setYOffset(1)
        fav_shadow.setColor(QColor(0, 0, 0, 20))
        fav_card.setGraphicsEffect(fav_shadow)
        fav_layout = QHBoxLayout(fav_card)
        fav_layout.setContentsMargins(10, 6, 12, 6)
        fav_layout.setSpacing(4)
        heart_icon_lbl = QLabel()
        heart_icon_lbl.setFixedSize(16, 16)
        heart_icon_lbl.setPixmap(icon_heart_outlined(16).pixmap(16, 16))
        fav_layout.addWidget(heart_icon_lbl)
        title = QLabel("收藏项目库")
        title.setObjectName("favTitle")
        title.setStyleSheet(
            "QLabel#favTitle{ font-family:'Microsoft YaHei'; font-size:14px; font-weight:500; color:#4E5969; background:transparent; } "
            "QLabel#favTitle:hover{ color:#165DFF; } "
        )
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        fav_layout.addWidget(title)
        header.addWidget(fav_card)
        header.addStretch()
        add_btn = QPushButton("+ 添加项目")
        add_btn.setFixedHeight(32)
        add_btn.setStyleSheet(
            "QPushButton{background:#165DFF; color:white; border:none; border-radius:8px; font-size:12px; padding:8px 14px;} "
            "QPushButton:hover{background:#4080FF;} QPushButton:pressed{background:#0E42D2;}"
        )
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(4)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(0, 0, 0, 26))
        add_btn.setGraphicsEffect(shadow)
        add_btn.clicked.connect(self._add_project)
        header.addWidget(add_btn)
        left_layout.addLayout(header)
        self.fav_tree = QTreeWidget()
        self.fav_tree.setHeaderHidden(True)
        self.fav_tree.setIndentation(16)
        self.fav_tree.setIconSize(QSize(16, 16))
        self.fav_tree.setStyleSheet(_LEFT_TREE_STYLE)
        self.fav_tree.itemSelectionChanged.connect(self._on_fav_selected)
        self.fav_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fav_tree.customContextMenuRequested.connect(self._on_fav_context)
        left_layout.addWidget(self.fav_tree)
        
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setColumnCount(2)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._update_right_tree_columns()
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)  # 优先保留文件名前缀，超长用...缩略
        self.tree.setStyleSheet(_RIGHT_TREE_STYLE)
        self.tree.installEventFilter(self)
        QTimer.singleShot(0, self._update_right_tree_columns)
        self.tree.setItemDelegateForColumn(1, _TimeColumnDelegate(self.tree))
        self.tree.itemExpanded.connect(self._on_tree_expanded)
        self.tree.itemCollapsed.connect(self._on_tree_collapsed)
        self.tree.itemSelectionChanged.connect(self._on_tree_selected)
        self.tree.itemDoubleClicked.connect(self._on_tree_double)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_context)
        right_layout.addWidget(self.tree)
        
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([280, 820])
        self.loading = QLabel("加载中...")
        self.loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading.setStyleSheet("color:#4E5969;")
        self.loading.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout.addWidget(self.loading)
        self.loading.hide()
    
    def _update_right_tree_columns(self):
        """右侧文件树：文件名列占宽 50%，时间列固定右侧，与文件名 10px 间距。"""
        w = self.tree.viewport().width() if self.tree.viewport() else self.tree.width()
        if w <= 0:
            return
        c0 = int(w * 0.5)
        c1 = w - c0
        if c1 < 100:
            c1 = 100
            c0 = w - 100
        self.tree.setColumnWidth(0, c0)
        self.tree.setColumnWidth(1, c1)

    def eventFilter(self, obj, event):
        if obj is self.tree and event.type() == QEvent.Type.Resize:
            self._update_right_tree_columns()
        return super().eventFilter(obj, event)

    def _add_folder_node(self, display_name, p, parent=None):
        """添加单个文件夹节点。parent 为 None 时作为根节点（普通图标）；否则作为子节点（icon_folder_sub）。"""
        unavailable = not os.path.exists(p)
        item = QTreeWidgetItem([display_name, ""])
        item.setData(0, Qt.ItemDataRole.UserRole, p)
        item.setData(1, Qt.ItemDataRole.UserRole, "unavailable" if unavailable else "ok")
        item.setToolTip(0, p)
        if unavailable:
            item.setForeground(0, Qt.GlobalColor.red)
        else:
            if "logs" in p or "07_logs" in p:
                _add_logs_xml_children(item, p, self.style())
            else:
                child = QTreeWidgetItem(["...", ""])
                child.setData(0, Qt.ItemDataRole.UserRole, None)
                item.addChild(child)
        item.setIcon(0, icon_folder_yellow())
        if parent is not None:
            parent.addChild(item)
        else:
            self.tree.addTopLevelItem(item)

    def _add_aggregate_node(self, display_name, rel_list, base):
        """添加聚合根节点（M5/program/util）：根用 FolderFilled #165DFF，子项为多个路径，子项用普通文件夹图标。"""
        root = QTreeWidgetItem([display_name, ""])
        root.setData(0, Qt.ItemDataRole.UserRole, None)
        root.setData(1, Qt.ItemDataRole.UserRole, "folder_aggregate")
        root.setIcon(0, icon_folder_yellow())
        for rel in rel_list:
            p = os.path.normpath(os.path.join(base, rel)).replace("/", "\\")
            sub_display = _strip_prefix(os.path.basename(rel))
            self._add_folder_node(sub_display, p, parent=root)
        self.tree.addTopLevelItem(root)

    def _build_documents_node(self, base):
        docs_root = QTreeWidgetItem(["Documents", ""])
        docs_root.setData(0, Qt.ItemDataRole.UserRole, None)
        docs_root.setData(1, Qt.ItemDataRole.UserRole, "docs_root")
        docs_root.setIcon(0, icon_product_outlined(14))
        files = self.core.match_files(base)
        doc_order = ["setup", "PDT", "SDTM_PDS", "ADAM_PDS", "PIT", "QCT"]
        file_items = []
        for k in doc_order:
            v = files.get(k)
            if not v:
                continue
            paths = v if isinstance(v, list) else [v]
            for fp in paths:
                try:
                    m = os.path.getmtime(fp)
                except Exception:
                    m = 0
                file_items.append((doc_order.index(k), k, fp, m))
        file_items.sort(key=lambda x: (x[0], -x[3]))
        for _idx, k, fp, _m in file_items:
            name = _strip_prefix(os.path.basename(fp))
            mtime = _mtime_str(fp)
            leaf = QTreeWidgetItem([name, mtime])
            leaf.setData(0, Qt.ItemDataRole.UserRole, fp)
            leaf.setData(1, Qt.ItemDataRole.UserRole, "file")
            leaf.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            leaf.setToolTip(0, fp)
            leaf.setIcon(0, icon_for_file_soft(fp, 14))
            docs_root.addChild(leaf)
        return docs_root

    def _show_loading(self):
        self.loading.show()
    
    def _hide_loading(self):
        self.loading.hide()
    
    def _load_favorites(self):
        self.fav_tree.clear()
        favs = self.core.get_favorites()
        dir_order = ["projects", "unblinded"]
        if any(f.get("dir_type", "").startswith("users") for f in favs):
            dir_order.append("users")
        root_name = _source_root_name("projects")
        by_pt = {}
        by_dir_legacy = {}
        for f in favs:
            dt = f.get("dir_type", "unknown")
            dt_key = "users" if dt and dt.startswith("users") else dt
            if dt in ("projects", "unblinded"):
                product, trial, subdir = _product_trial_from_path(f.get("full_path", ""), dt)
                if product and product.lower() != root_name and product != "unknown" and (dt != "unblinded" or product.lower() != "unblinded"):
                    if dt_key not in by_pt:
                        by_pt[dt_key] = {}
                    if product not in by_pt[dt_key]:
                        by_pt[dt_key][product] = {}
                    trial_key = trial or ""
                    if trial_key not in by_pt[dt_key][product]:
                        by_pt[dt_key][product][trial_key] = []
                    by_pt[dt_key][product][trial_key].append(f)
                else:
                    if dt_key not in by_dir_legacy:
                        by_dir_legacy[dt_key] = {}
                    main, sub = _parse_display_name(f.get("display_name", ""))
                    key = main or f.get("display_name", str(id(f)))
                    if key not in by_dir_legacy[dt_key]:
                        by_dir_legacy[dt_key][key] = []
                    by_dir_legacy[dt_key][key].append(f)
            elif dt_key == "users" and dt and str(dt).startswith("users"):
                product, trial, subdir = _product_trial_from_path(f.get("full_path", ""), dt)
                sub_root = "unblinded" if "unblinded" in (dt or "").lower() else "projects"
                if product and product != "unknown":
                    if dt_key not in by_pt:
                        by_pt[dt_key] = {}
                    if sub_root not in by_pt[dt_key]:
                        by_pt[dt_key][sub_root] = {}
                    if product not in by_pt[dt_key][sub_root]:
                        by_pt[dt_key][sub_root][product] = {}
                    trial_key = trial or ""
                    if trial_key not in by_pt[dt_key][sub_root][product]:
                        by_pt[dt_key][sub_root][product][trial_key] = []
                    fpath = os.path.normpath(f.get("full_path", "") or "").replace("/", "\\")
                    if fpath and not any(os.path.normpath(x.get("full_path", "") or "").replace("/", "\\") == fpath for x in by_pt[dt_key][sub_root][product][trial_key]):
                        by_pt[dt_key][sub_root][product][trial_key].append(f)
                else:
                    if dt_key not in by_dir_legacy:
                        by_dir_legacy[dt_key] = {}
                    main, sub = _parse_display_name(f.get("display_name", ""))
                    key = main or f.get("display_name", str(id(f)))
                    if key not in by_dir_legacy[dt_key]:
                        by_dir_legacy[dt_key][key] = []
                    by_dir_legacy[dt_key][key].append(f)
            else:
                if dt_key not in by_dir_legacy:
                    by_dir_legacy[dt_key] = {}
                main, sub = _parse_display_name(f.get("display_name", ""))
                key = main or f.get("display_name", str(id(f)))
                if key not in by_dir_legacy[dt_key]:
                    by_dir_legacy[dt_key][key] = []
                by_dir_legacy[dt_key][key].append(f)
        for dt in dir_order:
            root = QTreeWidgetItem([dt])
            root.setData(0, Qt.ItemDataRole.UserRole + 1, "source")
            root.setExpanded(True)
            root.setIcon(0, icon_folder_yellow())
            if dt in by_pt:
                if dt == "users":
                    for sub_root in ["unblinded", "projects"]:
                        if sub_root not in by_pt[dt]:
                            continue
                        sub_root_node = QTreeWidgetItem([sub_root])
                        sub_root_node.setData(0, Qt.ItemDataRole.UserRole + 1, "source")
                        sub_root_node.setIcon(0, icon_folder_yellow())
                        sub_root_node.setExpanded(True)
                        root.addChild(sub_root_node)
                        for product in sorted(by_pt[dt][sub_root].keys()):
                            product_node = QTreeWidgetItem([product])
                            product_node.setData(0, Qt.ItemDataRole.UserRole + 1, "product")
                            all_favs = []
                            for trial_key, flist in by_pt[dt][sub_root][product].items():
                                all_favs.extend(flist)
                            product_root_path = ""
                            if all_favs:
                                fp = os.path.normpath(all_favs[0].get("full_path", "")).replace("/", "\\")
                                parts = [p for p in fp.split("\\") if p]
                                idx = next((i for i, p in enumerate(parts) if p == product), None)
                                if idx is not None:
                                    product_root_path = "\\".join(parts[: idx + 1])
                                    if not product_root_path.upper().startswith("Z:"):
                                        product_root_path = "Z:\\" + product_root_path
                                if not product_root_path:
                                    product_root_path = os.path.normpath(os.path.dirname(all_favs[0]["full_path"])).replace("/", "\\")
                            product_node.setData(0, Qt.ItemDataRole.UserRole, {
                                "full_path": product_root_path or (all_favs[0]["full_path"] if all_favs else ""),
                                "display_name": product,
                                "id": f"product_{dt}_{sub_root}_{product}",
                                "is_product_node": True,
                                "dir_type": dt,
                            })
                            product_node.setIcon(0, icon_home_outlined(14))
                            product_node.setExpanded(True)
                            for trial_key in sorted(by_pt[dt][sub_root][product].keys(), key=lambda x: x or "\0"):
                                flist = by_pt[dt][sub_root][product][trial_key]
                                if trial_key:
                                    trial_node = QTreeWidgetItem([trial_key])
                                    trial_node.setData(0, Qt.ItemDataRole.UserRole + 1, "trial")
                                    trial_node.setData(0, Qt.ItemDataRole.UserRole + 2, flist)
                                    trial_node.setIcon(0, icon_folder_yellow())
                                    seen_paths = set()
                                    for fav in sorted(flist, key=lambda x: x.get("display_name", "")):
                                        norm_path = os.path.normpath(fav.get("full_path", "") or "").replace("/", "\\")
                                        if norm_path and norm_path in seen_paths:
                                            continue
                                        seen_paths.add(norm_path)
                                        _, sub = _parse_display_name(fav.get("display_name", ""))
                                        label = sub or os.path.basename(fav.get("full_path", "").rstrip("\\")) or fav.get("display_name", "")
                                        leaf = QTreeWidgetItem([label])
                                        leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                        leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                        leaf.setIcon(0, icon_check_circle_outlined(12) if re.match(r"^csr_?\\d*$", label, re.I) or (label and "csr" in label.lower()) else icon_folder_yellow())
                                        trial_node.addChild(leaf)
                                    product_node.addChild(trial_node)
                                else:
                                    seen_paths = set()
                                    for fav in flist:
                                        norm_path = os.path.normpath(fav.get("full_path", "") or "").replace("/", "\\")
                                        if norm_path and norm_path in seen_paths:
                                            continue
                                        seen_paths.add(norm_path)
                                        label = fav.get("display_name", os.path.basename(fav.get("full_path", "").rstrip("\\")) or "")
                                        leaf = QTreeWidgetItem([label])
                                        leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                        leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                        leaf.setIcon(0, icon_folder_yellow())
                                        product_node.addChild(leaf)
                            sub_root_node.addChild(product_node)
                else:
                    for product in sorted(by_pt[dt].keys()):
                        product_node = QTreeWidgetItem([product])
                        product_node.setData(0, Qt.ItemDataRole.UserRole + 1, "product")
                        all_favs = []
                        for trial_key, flist in by_pt[dt][product].items():
                            all_favs.extend(flist)
                        product_root_path = ""
                        if all_favs:
                            fp = os.path.normpath(all_favs[0].get("full_path", "")).replace("/", "\\")
                            parts = [p for p in fp.split("\\") if p]
                            rn = _source_root_name(dt)
                            for i, p in enumerate(parts):
                                if p.lower() == rn:
                                    product_root_path = "\\".join(parts[: i + 1] + [product])
                                    break
                            if not product_root_path and all_favs:
                                product_root_path = os.path.normpath(os.path.join(os.path.dirname(all_favs[0]["full_path"]), "..", product)).replace("/", "\\")
                        product_node.setData(0, Qt.ItemDataRole.UserRole, {
                            "full_path": product_root_path or (all_favs[0]["full_path"] if all_favs else ""),
                            "display_name": product,
                            "id": f"product_{dt}_{product}",
                            "is_product_node": True,
                            "dir_type": dt,
                        })
                        product_node.setIcon(0, icon_home_outlined(14))
                        product_node.setExpanded(True)
                        for trial_key in sorted(by_pt[dt][product].keys(), key=lambda x: x or "\0"):
                            flist = by_pt[dt][product][trial_key]
                            if trial_key:
                                trial_node = QTreeWidgetItem([trial_key])
                                trial_node.setData(0, Qt.ItemDataRole.UserRole + 1, "trial")
                                trial_node.setData(0, Qt.ItemDataRole.UserRole + 2, flist)
                                trial_node.setIcon(0, icon_folder_yellow())
                                seen_paths = set()
                                for fav in sorted(flist, key=lambda x: x.get("display_name", "")):
                                    norm_path = os.path.normpath(fav.get("full_path", "") or "").replace("/", "\\")
                                    if norm_path and norm_path in seen_paths:
                                        continue
                                    seen_paths.add(norm_path)
                                    _, sub = _parse_display_name(fav.get("display_name", ""))
                                    label = sub or os.path.basename(fav.get("full_path", "").rstrip("\\")) or fav.get("display_name", "")
                                    leaf = QTreeWidgetItem([label])
                                    leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                    leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                    leaf.setIcon(0, icon_check_circle_outlined(12) if re.match(r"^csr_?\\d*$", label, re.I) or (label and "csr" in label.lower()) else icon_folder_yellow())
                                    trial_node.addChild(leaf)
                                product_node.addChild(trial_node)
                            else:
                                seen_paths = set()
                                for fav in flist:
                                    norm_path = os.path.normpath(fav.get("full_path", "") or "").replace("/", "\\")
                                    if norm_path and norm_path in seen_paths:
                                        continue
                                    seen_paths.add(norm_path)
                                    label = fav.get("display_name", os.path.basename(fav.get("full_path", "").rstrip("\\")) or "")
                                    leaf = QTreeWidgetItem([label])
                                    leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                    leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                    leaf.setIcon(0, icon_folder_yellow())
                                    product_node.addChild(leaf)
                        root.addChild(product_node)
            if dt in by_dir_legacy and by_dir_legacy[dt]:
                for main_name, items in sorted(by_dir_legacy[dt].items(), key=lambda x: x[0]):
                    if len(items) == 1 and not _parse_display_name(items[0].get("display_name", ""))[1]:
                        leaf = QTreeWidgetItem([items[0].get("display_name", main_name)])
                        leaf.setData(0, Qt.ItemDataRole.UserRole, items[0])
                        leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                        leaf.setIcon(0, icon_folder_yellow())
                        root.addChild(leaf)
                    else:
                        parent = QTreeWidgetItem([main_name])
                        parent.setData(0, Qt.ItemDataRole.UserRole + 1, "parent")
                        parent.setData(0, Qt.ItemDataRole.UserRole + 2, items)
                        parent.setIcon(0, icon_folder_yellow())
                        for f in sorted(items, key=lambda x: x.get("display_name", "")):
                            _, sub = _parse_display_name(f.get("display_name", ""))
                            label = sub or f.get("display_name", "")
                            child = QTreeWidgetItem([label])
                            child.setData(0, Qt.ItemDataRole.UserRole, f)
                            child.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                            child.setIcon(0, icon_check_circle_outlined(12) if re.match(r"^csr_\\d+$", label, re.I) else icon_folder_yellow())
                            parent.addChild(child)
                        root.addChild(parent)
            self.fav_tree.addTopLevelItem(root)
        if self.current_fav:
            self._select_fav_in_tree(self.current_fav.get("id"))

    def _open_folder_with_feedback(self, folder_path, select_path=None):
        """打开文件夹：路径校验、执行、状态栏提示及操作反馈。

        - select_path 不为空：打开资源管理器并选中该文件
        - 否则：打开 folder_path（本地路径优先复用已有资源管理器窗口）
        """
        if not folder_path or not str(folder_path).strip():
            QMessageBox.warning(self, "路径无效", "未获取到文件夹路径，请重试。")
            return
        if select_path:
            select_path = os.path.normpath(select_path).replace("/", "\\")
            if not os.path.exists(select_path):
                QMessageBox.warning(self, "路径无效", "路径无效或不可访问，请检查后重试。")
                return
            folder_path = os.path.dirname(select_path)
        folder_path = os.path.normpath(folder_path).replace("/", "\\")
        if not os.path.isabs(folder_path):
            folder_path = os.path.abspath(folder_path)
        if not os.path.exists(folder_path):
            QMessageBox.warning(self, "路径无效", "路径无效或不可访问，请检查后重试。")
            return
        try:
            self.core.open_folder(folder_path, select_path=select_path)
            short = os.path.basename(folder_path.rstrip("\\")) or folder_path
            self.statusBar().showMessage(f"已打开：{short}", 3000)
            QTimer.singleShot(3000, lambda: self.statusBar().showMessage("若未打开请检查路径或网络", 2000))
        except Exception as e:
            QMessageBox.critical(self, "打开失败", str(e))

    def _select_fav_in_tree(self, fav_id):
        def find(item):
            f = item.data(0, Qt.ItemDataRole.UserRole)
            if f and f.get("id") == fav_id:
                return item
            for i in range(item.childCount()):
                r = find(item.child(i))
                if r:
                    return r
            return None
        for i in range(self.fav_tree.topLevelItemCount()):
            root = self.fav_tree.topLevelItem(i)
            for j in range(root.childCount()):
                node = root.child(j)
                target = find(node)
                if target:
                    self.fav_tree.setCurrentItem(target)
                    return

    def _on_utility_clicked(self):
        """点击固定区域：右侧展示 Z:\\projects\\utility 目录"""
        self._showing_utility = True
        self.current_fav = None
        self.fav_tree.clearSelection()
        QTimer.singleShot(0, self._do_refresh_tree)
    
    def _on_fav_selected(self):
        item = self.fav_tree.currentItem()
        if not item:
            return
        self._showing_utility = False
        fav = item.data(0, Qt.ItemDataRole.UserRole)
        if fav:
            self.current_fav = fav
        else:
            items = item.data(0, Qt.ItemDataRole.UserRole + 2)
            if items:
                self.current_fav = items[0]
            else:
                return
        QTimer.singleShot(0, self._do_refresh_tree)
    
    def _on_fav_context(self, pos):
        item = self.fav_tree.itemAt(pos)
        if not item:
            return
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        fav = item.data(0, Qt.ItemDataRole.UserRole)
        items = item.data(0, Qt.ItemDataRole.UserRole + 2)
        menu = QMenu(self)
        if node_type == "product" and fav and fav.get("is_product_node"):
            act_open = menu.addAction("打开所在文件夹")
            act_del = menu.addAction("删除产品类目")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            if act == act_open:
                self._open_folder_with_feedback(fav.get("full_path", ""))
            elif act == act_del:
                all_favs = []
                for i in range(item.childCount()):
                    child = item.child(i)
                    flist = child.data(0, Qt.ItemDataRole.UserRole + 2)
                    if flist:
                        all_favs.extend(flist)
                    else:
                        f = child.data(0, Qt.ItemDataRole.UserRole)
                        if f and f.get("id"):
                            all_favs.append(f)
                if not all_favs:
                    return
                r = QMessageBox.question(
                    self, "确认删除",
                    f"确定要删除产品「{item.text(0)}」及其下全部 {len(all_favs)} 个收藏吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r == QMessageBox.StandardButton.Yes:
                    for f in all_favs:
                        self.core.remove_favorite(f["id"])
                    self.current_fav = None
                    self._load_favorites()
        elif node_type == "trial" and items:
            act_open = menu.addAction("打开所在文件夹")
            act_del = menu.addAction("删除试验")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            if act == act_open:
                self._open_folder_with_feedback(items[0]["full_path"])
            elif act == act_del:
                r = QMessageBox.question(
                    self, "确认删除",
                    f"确定要删除试验「{item.text(0)}」及其下全部 {len(items)} 个收藏吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r == QMessageBox.StandardButton.Yes:
                    for f in items:
                        self.core.remove_favorite(f["id"])
                    self.current_fav = None
                    self._load_favorites()
        elif node_type == "leaf" and fav:
            act_open = menu.addAction("打开所在文件夹")
            act_del = menu.addAction("删除子项目")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            if act == act_open:
                self._open_folder_with_feedback(fav["full_path"])
            elif act == act_del:
                self.core.remove_favorite(fav["id"])
                self.current_fav = None
                self._load_favorites()
        elif node_type == "parent" and items:
            act_open = menu.addAction("打开所在文件夹")
            act_del = menu.addAction("删除整个项目")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            if act == act_open:
                self._open_folder_with_feedback(items[0]["full_path"])
            elif act == act_del:
                r = QMessageBox.question(
                    self, "确认删除",
                    f"确定要删除 {item.text(0)} 及其下全部 {len(items)} 个子项目吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r == QMessageBox.StandardButton.Yes:
                    for f in items:
                        self.core.remove_favorite(f["id"])
                self.current_fav = None
                self._load_favorites()
    
    def _refresh_tree(self):
        """入口：显示 loading 后异步加载文件树"""
        self._show_loading()
        QTimer.singleShot(0, self._do_refresh_tree)

    def _build_utility_tree(self):
        """右侧展示 Z:\\projects\\utility 目录（简单目录树）"""
        path = self.utility_path
        if not os.path.isdir(path):
            root = QTreeWidgetItem(["utility (路径不可用)", ""])
            root.setData(0, Qt.ItemDataRole.UserRole, None)
            self.tree.addTopLevelItem(root)
            return
        root = QTreeWidgetItem([os.path.basename(path) or "utility", ""])
        root.setData(0, Qt.ItemDataRole.UserRole, path)
        root.setData(1, Qt.ItemDataRole.UserRole, "ok")
        root.setIcon(0, icon_folder_yellow())
        
        ph = QTreeWidgetItem(["...", ""])
        ph.setData(0, Qt.ItemDataRole.UserRole, None)
        root.addChild(ph)
        self.tree.addTopLevelItem(root)
        self.tree.expandItem(root)

    def _do_refresh_tree(self):
        """异步执行：构建右侧文件树"""
        self.tree.setUpdatesEnabled(False)
        try:
            self.tree.clear()
            if self._showing_utility:
                self._build_utility_tree()
                return
            if not self.current_fav:
                return
            base = os.path.normpath(self.current_fav["full_path"]).replace("/", "\\")
            dir_type = self.current_fav.get("dir_type", "")
            is_users = dir_type and dir_type.startswith("users")
            # projects/unblinded: 完整节点；users: M5 / program / util 聚合
            if is_users:
                # user 下与 projects 对齐：仅 product→trial→子目录，不再展示 M5 分类
                path_order = [
                    ("program", ["06_programs", "09_validation"]),
                    ("util", ["utility/macros", "utility/metadata", "utility/tools"]),
                ]
            else:
                path_order = [
                    ("data", None),
                    ("M5", ["04_crt", "utility/documentation/06_crt_preparation"]),
                    ("program", ["06_programs", "09_validation"]),
                    ("reports", "03_reports"),
                    ("protocol", "utility/documentation/01_protocol"),
                    ("data_management", "utility/documentation/02_data_management"),
                    ("statistics", "utility/documentation/03_statistics"),
                    ("review_comments", "utility/documentation/04_review_comments"),
                    ("logs", "07_logs"),
                    ("util", ["utility/macros", "utility/metadata", "utility/tools"]),
                ]
            for disp, rel in path_order:
                if rel is None:
                    data_item = QTreeWidgetItem([disp, ""])
                    data_item.setData(0, Qt.ItemDataRole.UserRole, None)
                    data_item.setData(1, Qt.ItemDataRole.UserRole, "folder_group")
                    data_item.setIcon(0, icon_folder_yellow())
                    for sub in ["00_source_data", "01_sdtm", "02_adam"]:
                        sp = os.path.normpath(os.path.join(base, sub)).replace("/", "\\")
                        sub_item = QTreeWidgetItem([_strip_prefix(sub), ""])
                        sub_item.setData(0, Qt.ItemDataRole.UserRole, sp)
                        sub_item.setData(1, Qt.ItemDataRole.UserRole, "ok" if os.path.exists(sp) else "unavailable")
                        sub_item.setToolTip(0, sp)
                        if os.path.exists(sp):
                            placeholder = QTreeWidgetItem(["...", ""])
                            placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
                            sub_item.addChild(placeholder)
                            sub_item.setIcon(0, icon_folder_yellow())
                        else:
                            sub_item.setForeground(0, Qt.GlobalColor.red)
                            sub_item.setIcon(0, icon_folder_yellow())
                        data_item.addChild(sub_item)
                    self.tree.addTopLevelItem(data_item)
                elif isinstance(rel, list):
                    self._add_aggregate_node(disp, rel, base)
                else:
                    p = os.path.normpath(os.path.join(base, rel)).replace("/", "\\")
                    self._add_folder_node(disp, p)
            if not is_users:
                docs_root = self._build_documents_node(base)
                self.tree.addTopLevelItem(docs_root)
            pid = self.current_fav["id"]
            expanded = self.core.fs_expanded.get(pid, set())
            if expanded:
                self._restore_expanded(expanded)
        finally:
            self.tree.setUpdatesEnabled(True)
        self._hide_loading()
    
    def _on_tree_expanded(self, item):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        typ = item.data(1, Qt.ItemDataRole.UserRole)
        if path and typ and typ != "file":
            children = [item.child(i) for i in range(item.childCount())]
            if children and children[0].data(0, Qt.ItemDataRole.UserRole) is None:
                item.removeChild(children[0])
                try:
                    names = sorted(os.listdir(path))
                except Exception:
                    names = []
                for n in names:
                    p = os.path.join(path, n)
                    display = _strip_prefix(n)
                    if os.path.isdir(p):
                        c = QTreeWidgetItem([display, ""])
                        c.setData(0, Qt.ItemDataRole.UserRole, p)
                        c.setData(1, Qt.ItemDataRole.UserRole, "dir")
                        c.setToolTip(0, p)
                        c.setIcon(0, icon_folder_yellow())
                        placeholder = QTreeWidgetItem(["...", ""])
                        placeholder.setData(0, Qt.ItemDataRole.UserRole, None)
                        c.addChild(placeholder)
                        item.addChild(c)
                    else:
                        mtime = _mtime_str(p)
                        c = QTreeWidgetItem([display, mtime])
                        c.setData(0, Qt.ItemDataRole.UserRole, p)
                        c.setData(1, Qt.ItemDataRole.UserRole, "file")
                        c.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                        c.setToolTip(0, p)
                        c.setIcon(0, icon_for_file_soft(p, 14))
                        item.addChild(c)
        if self.current_fav:
            pid = self.current_fav["id"]
            s = self.core.fs_expanded.get(pid, set())
            if path:
                s.add(path)
            self.core.fs_expanded[pid] = s
    
    def _on_tree_collapsed(self, item):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if self.current_fav:
            pid = self.current_fav["id"]
            s = self.core.fs_expanded.get(pid, set())
            if path and path in s:
                s.discard(path)
            self.core.fs_expanded[pid] = s
    
    def _on_tree_selected(self):
        pass
    
    def _on_tree_double(self, item, _col):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        typ = item.data(1, Qt.ItemDataRole.UserRole)
        if not path or typ in ["dir_placeholder", "unavailable"]:
            return
        if typ == "dir":
            return
        path = os.path.normpath(path).replace("/", "\\")
        if path.lower().endswith(".pdf"):
            self._choose_pdf_open(path)
            return
        if path.lower().endswith(".sas") or path.lower().endswith(".sas7bdat"):
            selected = self.tree.selectedItems()
            sas_paths = []
            for it in selected:
                p = it.data(0, Qt.ItemDataRole.UserRole)
                t = it.data(1, Qt.ItemDataRole.UserRole)
                if p and t == "file" and (str(p).lower().endswith(".sas") or str(p).lower().endswith(".sas7bdat")):
                    p = os.path.normpath(p).replace("/", "\\")
                    if p not in sas_paths and os.path.exists(p):
                        sas_paths.append(p)
            if not sas_paths:
                sas_paths = [path]
            if len(sas_paths) > 1:
                self._choose_sas_open(sas_paths)
                return
            self._choose_sas_open(sas_paths[0])
            return
        if path.lower().endswith(".xml"):
            success, err = self.core.open_xml_with_excel(path)
            if success:
                self.statusBar().showMessage(f"正在打开 {os.path.basename(path)}", 3000)
            else:
                self._show_xml_open_error(path, err)
            return
        success, err = self.core.open_file(path)
        if success:
            name = os.path.basename(path)
            self.statusBar().showMessage(f"正在打开 {name}", 3000)
        else:
            QMessageBox.critical(self, "打开失败", err)

    def _show_xml_open_error(self, path, err):
        """XML 打开失败：弹窗提示，附带「打开所在文件夹」兜底按钮"""
        dlg = QMessageBox(self)
        dlg.setWindowTitle("打开失败")
        dlg.setText(err)
        dlg.setInformativeText("可尝试打开所在文件夹后手动双击文件。")
        btn_folder = dlg.addButton("打开所在文件夹", QMessageBox.ButtonRole.ActionRole)
        dlg.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        if dlg.clickedButton() == btn_folder:
            self._open_folder_with_feedback(os.path.dirname(path), select_path=path)

    def _convert_path_for_saseg(self, file_path):
        """将路径转换为 SAS EG 可用的形式：Z 盘 → /u01/app/sas/sas9.4/DocumentRepository/DDT/...；非 Z 盘仅反斜杠转正斜杠。"""
        path = os.path.normpath(file_path).replace("/", "\\")
        upper = path.upper()
        if upper.startswith("Z:\\") or upper.startswith("Z:/"):
            remaining = path[3:].strip("\\/").replace("\\", "/")
            return f"/u01/app/sas/sas9.4/DocumentRepository/DDT/{remaining}"
        return path.replace("\\", "/")

    def update_status(self, msg):
        """供 _open_with_saseg 等调用的状态栏更新。"""
        self.statusBar().showMessage(msg, 3000)

    def show_error(self, msg):
        """供 _open_with_saseg 等调用的错误弹窗。"""
        QMessageBox.critical(self, "打开失败", msg)

    def _open_with_saseg(self, file_path):
        """用 SAS EG 打开 .sas / .sas7bdat：每次强制新开 SAS EG 窗口，在新窗口左侧「服务器」树中展开到目标路径并双击文件打开（不弹「文件→打开」对话框）。失败时降级为传参打开。"""
        seguide_path = r"C:\Program Files\SaS\SASHome\SASEnterpriseGuide\8\SEGuide.exe"
        if not os.path.isfile(seguide_path):
            self.show_error("未找到 SAS Enterprise Guide，请确认已安装：\n" + seguide_path)
            self.update_status("打开失败：未找到 SEGuide.exe")
            return
        paths = [file_path] if isinstance(file_path, str) else list(file_path)
        for p in paths:
            if not os.path.exists(p):
                self.show_error(f"文件不存在: {p}")
                self.update_status("打开失败：文件不存在")
                return
        self.update_status("正在通过 SAS EG 自动化打开文件…")
        thread = threading.Thread(target=self._open_sas_eg_automation, args=(seguide_path, paths))
        thread.daemon = True
        thread.start()

    def _open_sas_eg_automation(self, seguide_path, paths):
        """后台线程：每次均强制新开 SAS EG 进程（不复用已有窗口）→ 在新窗口左侧树展开 SASApp→文件→…→目标文件夹 →
        依次双击每个选中文件（.sas/.sas7bdat），支持 Ctrl 多选在同一新窗口中批量打开；单个文件未找到不中断其余，最后显示成功数/总数。"""
        try:
            from pywinauto import Application
        except ImportError:
            QTimer.singleShot(0, lambda: self._open_with_saseg_fallback(seguide_path, paths))
            QTimer.singleShot(0, lambda: self.show_error("请安装 pywinauto 以使用自动化打开：pip install pywinauto"))
            QTimer.singleShot(0, lambda: self.update_status("已改为直接传参打开，若乱码请安装 pywinauto"))
            return
        try:
            common_dir, folder_parts, file_names = self._common_folder_and_files(paths)
        except ValueError as e:
            QTimer.singleShot(0, lambda: self.show_error(str(e)))
            QTimer.singleShot(0, lambda: self.update_status("多选文件须位于同一文件夹下"))
            return
        app = None
        main_win = None
        try:
            # 强制新开 SAS EG 窗口，不复用已有窗口；精准等待服务器树就绪，缩短启动到展开间隔
            QTimer.singleShot(0, lambda: self.update_status("正在启动新的 SAS EG 窗口…"))
            app = Application(backend="uia").start(seguide_path)
            app.Dialog.wait("exists ready", timeout=15, retry_interval=2)
            main_win = app.window(title_re=".*SAS Enterprise Guide.*")
            main_win.wait("visible", timeout=15)
            main_win.set_focus()
            main_win.maximize()
            time.sleep(self.SHORT_WAIT)
            self._wait_for_saseg_tree_control(main_win)
            QTimer.singleShot(0, lambda: self.update_status("新 SAS EG 窗口已就绪，开始展开节点…"))
            self._close_obstructing_popups(app, main_win)
            path_type, path_levels = self._saseg_path_type_and_levels(folder_parts)
            current = None
            try:
                current = self._expand_sasapp_tree_main(main_win, path_type, path_levels)
            except Exception as e:
                QTimer.singleShot(0, lambda: self.update_status(f"主界面树展开失败，改用面板方式：{str(e)}"))
                current = None
            if current is None:
                QTimer.singleShot(0, lambda: self.update_status("正在展开服务器树…"))
                server_pane = main_win.child_window(title="服务器", control_type="Pane")
                if not server_pane.exists():
                    server_pane = main_win.child_window(title_re=".*服务器.*", control_type="Pane")
                if not server_pane.exists():
                    for c in main_win.descendants(control_type="Pane"):
                        try:
                            if "服务器" in (c.window_text() or ""):
                                server_pane = c
                                break
                        except Exception:
                            continue
                if not server_pane.exists():
                    QTimer.singleShot(0, lambda: self.show_error("未找到「服务器」面板，请确认 SAS EG 主界面已加载。"))
                    self._open_with_saseg_fallback(seguide_path, paths)
                    return
                server_item = server_pane.child_window(title="服务器", control_type="TreeItem")
                if not server_item.exists():
                    server_item = server_pane.child_window(title_re=".*服务器.*", control_type="TreeItem")
                if not server_item.exists():
                    for c in server_pane.descendants(control_type="TreeItem"):
                        try:
                            if (c.window_text() or "").strip() in ("服务器", "Servers"):
                                server_item = c
                                break
                        except Exception:
                            continue
                if not server_item.exists():
                    QTimer.singleShot(0, lambda: self.show_error("未找到「服务器」树节点。"))
                    self._open_with_saseg_fallback(seguide_path, paths)
                    return
                self._expand_single_node(server_item, "服务器")
                time.sleep(self.MEDIUM_WAIT)
                sasapp = server_item.child_window(title="SASApp", control_type="TreeItem")
                if not sasapp.exists():
                    sasapp = server_item.child_window(title_re=".*SASApp.*", control_type="TreeItem")
                if not sasapp.exists():
                    QTimer.singleShot(0, lambda: self.show_error("未找到 SASApp 节点。"))
                    self._open_with_saseg_fallback(seguide_path, paths)
                    return
                self._expand_single_node(sasapp, "SASApp")
                time.sleep(self.MEDIUM_WAIT)
                file_node = None
                for name in ["文件", "Files", "文件系统", "File System"]:
                    try:
                        fn = sasapp.child_window(title=name, control_type="TreeItem")
                        if fn.exists():
                            file_node = fn
                            break
                    except Exception:
                        continue
                if file_node is None:
                    file_node = self._find_file_node(sasapp)
                if file_node is None:
                    for child in sasapp.children():
                        try:
                            t = (child.window_text() or "").lower()
                            if any(kw in t for kw in ["文件", "file", "system"]):
                                file_node = child
                                break
                        except Exception:
                            continue
                if file_node is None:
                    file_node = self._find_file_node_in_pane(server_pane)
                if file_node is None:
                    QTimer.singleShot(0, lambda: self.update_status("无法找到「文件」节点，已改为直接传参打开"))
                    self._open_with_saseg_fallback(seguide_path, paths)
                    return
                self._expand_single_node(file_node, file_node.window_text() or "文件")
                time.sleep(self.MEDIUM_WAIT)
                current = file_node
                # 按 path_type 展开根节点（projects 或 users→project / users→unblinded）
                if path_type == "projects":
                    for child in current.children():
                        try:
                            if "projects" in (child.window_text() or "").lower():
                                current = child
                                self._expand_single_node(current, "projects")
                                break
                        except Exception:
                            continue
                elif path_type == "users_project":
                    for child in current.children():
                        try:
                            if "users" in (child.window_text() or "").lower():
                                current = child
                                self._expand_single_node(current, "users")
                                break
                        except Exception:
                            continue
                    for child in current.children():
                        try:
                            if "project" in (child.window_text() or "").lower():
                                current = child
                                self._expand_single_node(current, "project")
                                break
                        except Exception:
                            continue
                elif path_type == "users_unblinded":
                    for child in current.children():
                        try:
                            if "users" in (child.window_text() or "").lower():
                                current = child
                                self._expand_single_node(current, "users")
                                break
                        except Exception:
                            continue
                    for child in current.children():
                        try:
                            if "unblinded" in (child.window_text() or "").lower():
                                current = child
                                self._expand_single_node(current, "unblinded")
                                break
                        except Exception:
                            continue
                time.sleep(self.MEDIUM_WAIT)
                for part in path_levels:
                    try:
                        current.click_input()
                        time.sleep(self.SHORT_WAIT)
                    except Exception:
                        pass
                    if not current.is_expanded():
                        current.expand()
                        time.sleep(self.MEDIUM_WAIT)
                    else:
                        time.sleep(self.SHORT_WAIT)
                    found = False
                    for child in current.children():
                        try:
                            t = (child.window_text() or "").strip()
                            if t == part or t.lower() == part.lower():
                                current = child
                                current.ensure_visible()
                                time.sleep(self.SHORT_WAIT)
                                try:
                                    current.click_input()
                                    time.sleep(self.SHORT_WAIT)
                                except Exception:
                                    pass
                                if not current.is_expanded():
                                    current.expand()
                                    time.sleep(self.MEDIUM_WAIT)
                                else:
                                    time.sleep(self.SHORT_WAIT)
                                found = True
                                break
                        except Exception:
                            continue
                    if not found:
                        QTimer.singleShot(0, lambda: self.update_status(f"无法找到文件夹节点: {part}，已改为直接传参打开"))
                        self._open_with_saseg_fallback(seguide_path, paths)
                        return
                current.click_input()
                time.sleep(self.MEDIUM_WAIT)
            # 批量打开：依次双击每个选中文件（.sas/.sas7bdat），单个失败不中断其余
            success_count = 0
            for idx, target_name in enumerate(file_names):
                if idx > 0:
                    current.click_input()
                    time.sleep(self.SHORT_WAIT)
                found = False
                try:
                    for child in current.children():
                        try:
                            t = (child.window_text() or "").strip()
                            if t == target_name or t.lower() == target_name.lower():
                                child.ensure_visible()
                                time.sleep(self.SHORT_WAIT)
                                try:
                                    child.click_input(double=True, coords=(10, 10))
                                except Exception:
                                    child.click_input(double=True)
                                time.sleep(self.MEDIUM_WAIT)
                                main_win.set_focus()
                                self._close_obstructing_popups(app, main_win)
                                found = True
                                success_count += 1
                                break
                        except Exception:
                            continue
                except Exception:
                    pass
                if not found:
                    QTimer.singleShot(0, lambda n=target_name: self.show_error(f"在文件列表中未找到: {n}"))
            main_win.set_focus()
            total = len(file_names)
            if total == 1:
                QTimer.singleShot(0, lambda f=file_names[0], s=success_count: self.update_status("已用 SAS EG 打开: " + f if s else "打开失败"))
            else:
                QTimer.singleShot(0, lambda s=success_count, t=total: self.update_status(f"批量打开完成：成功 {s} / 共 {t} 个文件"))
        except Exception as e:
            QTimer.singleShot(0, lambda: self._open_with_saseg_fallback(seguide_path, paths))
            QTimer.singleShot(0, lambda msg=str(e): self.update_status(f"自动化打开失败: {msg}"))
            return

    def _common_folder_and_files(self, paths):
        """计算所有选中文件的共同父文件夹、导航用 folder_parts、以及文件名列表。若不在同一文件夹则抛出 ValueError。"""
        paths = [os.path.normpath(p).replace("/", "\\") for p in paths]
        if not paths:
            raise ValueError("未选中任何文件")
        common_dir = os.path.dirname(paths[0])
        file_names = [os.path.basename(paths[0])]
        if len(paths) > 1:
            try:
                common_dir = os.path.commonpath(paths)
            except ValueError:
                raise ValueError("选中的文件不在同一文件夹下，请仅选择同一目录下的多个 .sas 文件。")
            first_dir = os.path.dirname(paths[0])
            for p in paths:
                if os.path.dirname(p) != first_dir:
                    raise ValueError("选中的文件不在同一文件夹下，请仅选择同一目录下的多个 .sas 文件。")
            file_names = [os.path.basename(p) for p in paths]
            common_dir = first_dir
        upper = common_dir.upper().replace("/", "\\")
        if upper.startswith("Z:\\") or upper.startswith("Z:/"):
            remaining = common_dir[3:].strip("\\/").replace("\\", "/")
            folder_parts = [p for p in remaining.split("/") if p]
        else:
            folder_parts = [p for p in common_dir.replace("\\", "/").split("/") if p]
        return common_dir, folder_parts, file_names

    def _saseg_path_type_and_levels(self, folder_parts):
        """根据 Z 盘路径段识别 path_type（projects / users_project / users_unblinded）及展开用的 path_levels（根节点之后的层级）。"""
        if not folder_parts:
            return "projects", []
        lower_parts = [p.lower() for p in folder_parts]
        if lower_parts[0] == "projects":
            return "projects", folder_parts[1:]
        for i in range(len(folder_parts) - 1):
            if lower_parts[i] == "users" and lower_parts[i + 1] in ("project", "unblinded"):
                path_type = "users_project" if lower_parts[i + 1] == "project" else "users_unblinded"
                return path_type, folder_parts[i + 2 :]
        return "projects", folder_parts

    def _group_paths_by_folder(self, paths):
        """将路径按所在文件夹分组，返回 [(folder_parts, [file_name, ...]), ...]。"""
        from collections import OrderedDict
        groups = OrderedDict()
        for p in paths:
            dir_path = os.path.dirname(p)
            file_name = os.path.basename(p)
            upper = dir_path.upper().replace("/", "\\")
            if upper.startswith("Z:\\") or upper.startswith("Z:/"):
                remaining = dir_path[3:].strip("\\/").replace("\\", "/")
                folder_parts = tuple(p for p in remaining.split("/") if p)
            else:
                folder_parts = tuple(p for p in dir_path.replace("\\", "/").split("/") if p)
            if folder_parts not in groups:
                groups[folder_parts] = []
            groups[folder_parts].append(file_name)
        return list(groups.items())

    def _find_file_node(self, sasapp_node):
        """在 SASApp 下查找「文件」或 Files 节点。"""
        try:
            n = sasapp_node.child_window(title="文件", control_type="TreeItem")
            if n.exists():
                return n
        except Exception:
            pass
        try:
            n = sasapp_node.child_window(title_re=".*文件.*", control_type="TreeItem")
            if n.exists():
                return n
        except Exception:
            pass
        try:
            n = sasapp_node.child_window(title="Files", control_type="TreeItem")
            if n.exists():
                return n
        except Exception:
            pass
        for child in sasapp_node.children():
            try:
                t = (child.window_text() or "").lower()
                if "文件" in t or "file" in t:
                    return child
            except Exception:
                continue
        try:
            ch = sasapp_node.children()
            if ch:
                return ch[0]
        except Exception:
            pass
        return None

    def _find_file_node_in_pane(self, server_pane):
        """在「服务器」面板内按标题查找「文件」/「Files」树节点（用于主窗口树结构可能与对话框不一致时）。"""
        for node in server_pane.descendants(control_type="TreeItem"):
            try:
                t = (node.window_text() or "").strip().lower()
                if t in ("文件", "files"):
                    return node
                if "文件" in t or (len(t) == 5 and t == "files"):
                    return node
            except Exception:
                continue
        return None

    def _wait_for_saseg_tree_control(self, main_eg_win):
        """精准等待服务器树控件就绪后再展开，避免固定长等待；超时 MAX_EG_START_WAIT 秒则抛错。从后台线程调用。"""
        start_time = time.time()
        QTimer.singleShot(0, lambda: self.update_status("检测服务器树控件…"))
        while time.time() - start_time < self.MAX_EG_START_WAIT:
            try:
                tree_ctrl = main_eg_win.child_window(control_type="Tree")
                if tree_ctrl.exists() and tree_ctrl.is_visible():
                    elapsed = round(time.time() - start_time, 1)
                    QTimer.singleShot(0, lambda e=elapsed: self.update_status(f"服务器树就绪（耗时 {e} 秒）"))
                    return
            except Exception:
                pass
            time.sleep(self.TREE_CHECK_INTERVAL)
            elapsed = round(time.time() - start_time, 1)
            QTimer.singleShot(0, lambda e=elapsed, m=self.MAX_EG_START_WAIT: self.update_status(f"等待控件就绪… ({e}/{m} 秒)"))
        raise RuntimeError(f"超时 {self.MAX_EG_START_WAIT} 秒，服务器树控件仍未就绪")

    def _expand_single_node(self, node, node_name):
        """展开单个树节点；对「文件/Files」节点略增加等待以适配 SAS 加载延迟，其余极快。"""
        try:
            node.ensure_visible()
            if "文件" in node_name or "Files" in node_name:
                time.sleep(self.SHORT_WAIT * 2)
            else:
                time.sleep(self.SHORT_WAIT)

            if not node.is_expanded():
                node.expand()
                if "文件" in node_name or "Files" in node_name:
                    time.sleep(0.5)
                else:
                    time.sleep(0.3)
            return True
        except Exception:
            raise Exception(f"节点「{node_name}」展开失败")

    def _expand_sasapp_tree_main(self, main_eg_win, path_type, path_levels):
        """在 SAS EG 主界面左侧服务器树中逐级展开到目标文件夹。
        支持 path_type：projects（文件→projects→…）、users_project（文件→users→project→…）、users_unblinded（文件→users→unblinded→…）。"""
        QTimer.singleShot(0, lambda: self.update_status("开始在主界面展开 SASApp 节点…"))
        path_levels = [level.strip() for level in path_levels if level and str(level).strip()]
        tree_ctrl = None
        try:
            tree_ctrl = main_eg_win.child_window(control_type="Tree")
            tree_ctrl.wait("visible", timeout=10)
        except Exception:
            raise RuntimeError("无法定位 SAS EG 主界面的服务器树控件，请检查界面布局。")
        tree_ctrl.set_focus()
        time.sleep(self.SHORT_WAIT)
        server_node = None
        try:
            server_node = tree_ctrl.child_window(title="服务器", control_type="TreeItem")
            if not server_node.exists():
                server_node = None
        except Exception:
            server_node = None
        if server_node is None:
            try:
                server_node = tree_ctrl.child_window(title="Servers", control_type="TreeItem")
                if not server_node.exists():
                    server_node = None
            except Exception:
                server_node = None
        if server_node is None:
            for child in tree_ctrl.children():
                try:
                    t = (child.window_text() or "") or ""
                    if "服务器" in t or "Servers" in t:
                        server_node = child
                        break
                except Exception:
                    continue
        if server_node is None:
            raise RuntimeError("无法定位「服务器」根节点。")
        self._expand_single_node(server_node, "服务器")
        sasapp_node = None
        try:
            sasapp_node = server_node.child_window(title="SASApp", control_type="TreeItem")
            if not sasapp_node.exists():
                sasapp_node = None
        except Exception:
            sasapp_node = None
        if sasapp_node is None:
            raise RuntimeError("无法定位「SASApp」节点。")
        self._expand_single_node(sasapp_node, "SASApp")
        time.sleep(self.MEDIUM_WAIT)
        files_node = None
        possible_names = ["文件", "Files", "文件系统", "File System", "My Computer", "This PC", "此电脑"]
        for name in possible_names:
            try:
                fn = sasapp_node.child_window(title=name, control_type="TreeItem")
                if fn.exists():
                    files_node = fn
                    break
            except Exception:
                continue
        if files_node is None or not getattr(files_node, "exists", lambda: True)():
            QTimer.singleShot(0, lambda: self.update_status("按名称查找「文件」节点失败，尝试遍历子节点…"))
            for child in sasapp_node.children():
                try:
                    t = (child.window_text() or "").lower()
                    if any(kw in t for kw in ["文件", "file", "system", "computer", "电脑"]):
                        files_node = child
                        break
                except Exception:
                    continue
        if files_node is None or not getattr(files_node, "exists", lambda: True)():
            raise RuntimeError(
                "展开 SASApp 后无法找到「文件」/「Files」节点。请确认 SAS EG 中该节点名称，并可将名称加入 possible_names 列表。"
            )
        self._expand_single_node(files_node, files_node.window_text() or "文件")
        time.sleep(self.MEDIUM_WAIT)
        current_node = files_node

        if path_type == "projects":
            proj_node = None
            for c in current_node.children():
                try:
                    if "projects" in (c.window_text() or "").lower():
                        proj_node = c
                        break
                except Exception:
                    continue
            if proj_node is None or not getattr(proj_node, "exists", lambda: True)():
                raise RuntimeError("无法定位「projects」节点。")
            self._expand_single_node(proj_node, "projects")
            current_node = proj_node
        elif path_type == "users_project":
            users_node = None
            for c in current_node.children():
                try:
                    if "users" in (c.window_text() or "").lower():
                        users_node = c
                        break
                except Exception:
                    continue
            if users_node is None or not getattr(users_node, "exists", lambda: True)():
                raise RuntimeError("无法定位「users」节点。")
            self._expand_single_node(users_node, "users")
            current_node = users_node
            project_node = None
            for c in current_node.children():
                try:
                    if "project" in (c.window_text() or "").lower():
                        project_node = c
                        break
                except Exception:
                    continue
            if project_node is None or not getattr(project_node, "exists", lambda: True)():
                raise RuntimeError("无法定位「project」节点（users 下）。")
            self._expand_single_node(project_node, "project")
            current_node = project_node
        elif path_type == "users_unblinded":
            users_node = None
            for c in current_node.children():
                try:
                    if "users" in (c.window_text() or "").lower():
                        users_node = c
                        break
                except Exception:
                    continue
            if users_node is None or not getattr(users_node, "exists", lambda: True)():
                raise RuntimeError("无法定位「users」节点。")
            self._expand_single_node(users_node, "users")
            current_node = users_node
            unblinded_node = None
            for c in current_node.children():
                try:
                    if "unblinded" in (c.window_text() or "").lower():
                        unblinded_node = c
                        break
                except Exception:
                    continue
            if unblinded_node is None or not getattr(unblinded_node, "exists", lambda: True)():
                raise RuntimeError("无法定位「unblinded」节点（users 下）。")
            self._expand_single_node(unblinded_node, "unblinded")
            current_node = unblinded_node
        time.sleep(self.MEDIUM_WAIT)

        for level in path_levels:
            child_node = None
            try:
                child_node = current_node.child_window(title=level, control_type="TreeItem")
                if not child_node.exists():
                    child_node = None
            except Exception:
                child_node = None
            if child_node is None:
                for child in current_node.children():
                    try:
                        if (child.window_text() or "").strip().lower() == level.lower():
                            child_node = child
                            break
                    except Exception:
                        continue
            if child_node is None or not getattr(child_node, "exists", lambda: True)():
                raise RuntimeError(f"在节点「{current_node.window_text()}」下无法找到子节点「{level}」。")
            self._expand_single_node(child_node, level)
            current_node = child_node
            time.sleep(self.MEDIUM_WAIT)
        current_node.click_input()
        time.sleep(self.MEDIUM_WAIT)
        QTimer.singleShot(0, lambda: self.update_status("主界面服务器树展开完成。"))
        return current_node

    def _saseg_click_server_tab(self, app):
        """在「打开」对话框中查找并点击「服务器」/「Servers」标签，确保左侧树可见。返回是否成功。"""
        dlg = app.Dialog
        for title in ("服务器", "Servers", "服务器(", "Servers ("):
            try:
                tab = dlg.child_window(title=title, control_type="TabItem")
                if tab.exists():
                    tab.set_focus()
                    time.sleep(0.3)
                    tab.click_input()
                    print("[SAS EG] 已切换到服务器标签")
                    return True
            except Exception:
                pass
        for ctrl in dlg.descendants():
            try:
                t = (ctrl.window_text() or "").strip()
                if t in ("服务器", "Servers"):
                    ctrl.set_focus()
                    time.sleep(0.3)
                    ctrl.click_input()
                    print("[SAS EG] 已切换到服务器标签")
                    return True
            except Exception:
                continue
        return False

    def _select_file_in_list(self, app, file_name, send_keys, folder_node=None):
        """在打开对话框右侧文件列表中按文件名（忽略大小写）定位并选中目标文件，然后点击「打开」。
        步骤：1) 激活对话框 set_focus；2) 若传入 folder_node，先在其子节点（树节点）中按文件名匹配；
        3) 再在 ListView/List/DataGrid 的 ListItem/DataItem 中匹配；4) 找到后 click_input 选中，等待 5s 后点击「打开」。
        若未找到则弹窗提示并建议使用 inspect.exe 查看控件类型。"""
        dlg = app.Dialog
        dlg.set_focus()
        time.sleep(0.5)
        want = (file_name or "").strip()
        if not want:
            return False
        want_lower = want.lower()

        # 步骤1：若已导航到目标文件夹，优先在文件夹树节点的子项中查找（右侧可能为同一树的子节点）
        if folder_node is not None:
            try:
                for child in folder_node.children():
                    try:
                        t = (child.window_text() or "").strip()
                        if t.lower() == want_lower or (want in t):
                            child.set_focus()
                            time.sleep(0.3)
                            child.ensure_visible()
                            child.click_input()
                            time.sleep(5)
                            print("[SAS EG] 已在文件列表中选中目标文件:", want)
                            self._click_open_button_then_enter(app, send_keys)
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

        # 步骤2：在 ListView / List / DataGrid 中查找 ListItem、DataItem
        for list_ctype in ("ListView", "List", "DataGrid"):
            try:
                lists = dlg.descendants(control_type=list_ctype)
                for lv in lists:
                    try:
                        items = list(lv.descendants(control_type="ListItem")) + list(lv.descendants(control_type="DataItem"))
                        if not items:
                            for child in lv.children():
                                try:
                                    t = (child.window_text() or "").strip()
                                    if t.lower() == want_lower or (want in t):
                                        child.set_focus()
                                        time.sleep(0.3)
                                        child.click_input()
                                        time.sleep(5)
                                        print("[SAS EG] 已在文件列表中选中目标文件:", want)
                                        self._click_open_button_then_enter(app, send_keys)
                                        return True
                                except Exception:
                                    continue
                        for item in items:
                            try:
                                t = (item.window_text() or "").strip()
                                if t.lower() == want_lower or (want in t):
                                    item.set_focus()
                                    time.sleep(0.3)
                                    item.ensure_visible()
                                    item.click_input()
                                    time.sleep(5)
                                    print("[SAS EG] 已在文件列表中选中目标文件:", want)
                                    self._click_open_button_then_enter(app, send_keys)
                                    return True
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                continue
        # 兜底：在整个对话框中按 ListItem/DataItem/TreeItem 匹配（兼容不同控件实现）
        for ctype in ("ListItem", "DataItem", "TreeItem"):
            try:
                for item in dlg.descendants(control_type=ctype):
                    try:
                        t = (item.window_text() or "").strip()
                        if t.lower() == want_lower or (want in t):
                            item.set_focus()
                            time.sleep(0.3)
                            item.ensure_visible()
                            item.click_input()
                            time.sleep(5)
                            print("[SAS EG] 已在文件列表中选中目标文件:", want)
                            self._click_open_button_then_enter(app, send_keys)
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        QTimer.singleShot(0, lambda: self.show_error("文件列表中未找到目标文件，请检查路径或文件名。\n\n若仍失败，可使用 pywinauto 的 inspect.exe 或 Windows SDK 的 inspect.exe 查看「打开」对话框右侧文件列表的 ControlType（如 ListView、List、TreeItem）。"))
        QTimer.singleShot(0, lambda: self.update_status("文件列表中未找到目标文件"))
        return False

    def _select_and_open_file_in_dialog(self, app, file_name):
        """在打开对话框中查找并双击/打开指定文件名。返回是否找到并操作。"""
        try:
            dlg = app.Dialog
            for ctype in ("ListItem", "DataItem", "TreeItem", "List"):
                try:
                    items = dlg.descendants(control_type=ctype)
                    for item in items:
                        try:
                            if (item.window_text() or "").strip() == file_name:
                                item.ensure_visible()
                                item.click_input(double=True)
                                time.sleep(0.5)
                                return True
                        except Exception:
                            continue
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _batch_select_and_open_in_dialog(self, app, file_names, send_keys, folder_node=None):
        """在目标文件夹下批量选中多个文件（模拟 Ctrl+点击），最后点击「打开」或回车。优先从树节点 folder_node 的子节点找文件。"""
        if not file_names:
            return False
        want = set(f.strip() for f in file_names)
        matched = []
        dlg = app.Dialog
        if folder_node is not None:
            try:
                for child in folder_node.children():
                    try:
                        t = (child.window_text() or "").strip()
                        if t in want:
                            matched.append((t, child))
                    except Exception:
                        continue
            except Exception:
                pass
        if not matched:
            for ctype in ("ListItem", "DataItem", "TreeItem", "List", "ListView", "DataItem"):
                try:
                    items = dlg.descendants(control_type=ctype)
                    for item in items:
                        try:
                            t = (item.window_text() or "").strip()
                            if t in want:
                                matched.append((t, item))
                        except Exception:
                            continue
                    if matched:
                        break
                except Exception:
                    continue
        if not matched:
            time.sleep(1.5)
            if folder_node is not None:
                try:
                    for child in folder_node.children():
                        try:
                            t = (child.window_text() or "").strip()
                            if t in want:
                                matched.append((t, child))
                        except Exception:
                            continue
                except Exception:
                    pass
            if not matched:
                for ctype in ("ListItem", "DataItem", "TreeItem"):
                    try:
                        for item in dlg.descendants(control_type=ctype):
                            try:
                                t = (item.window_text() or "").strip()
                                if t in want:
                                    matched.append((t, item))
                            except Exception:
                                continue
                        if matched:
                            break
                    except Exception:
                        continue
        by_name = {}
        for t, item in matched:
            if t not in by_name:
                by_name[t] = (t, item)
        matched = list(by_name.values())
        order = {f: i for i, f in enumerate(file_names)}
        matched.sort(key=lambda x: order.get(x[0], 999))
        if not matched:
            self._click_open_button_then_enter(app, send_keys)
            return True
        try:
            if len(matched) == 1:
                try:
                    matched[0][1].ensure_visible()
                    time.sleep(0.2)
                    matched[0][1].click_input(double=True)
                    time.sleep(1.0)
                    return True
                except Exception:
                    pass
            ctrl_click = self._ctrl_click_item
            for i, (_, item) in enumerate(matched):
                try:
                    item.ensure_visible()
                    time.sleep(0.15)
                    if i == 0:
                        item.click_input()
                    else:
                        ctrl_click(item)
                    time.sleep(0.5 if i > 0 else 0.25)
                except Exception:
                    continue
            time.sleep(0.4)
            self._click_open_button_then_enter(app, send_keys)
            return True
        except Exception:
            self._click_open_button_then_enter(app, send_keys)
            return False

    def _single_file_open_by_path(self, app, mapped_path, send_keys):
        """单文件场景：在打开对话框中向「文件名」输入框输入完整路径（含文件名），回车确认打开。
        路径格式为 DDT：Z:\\xxx -> /u01/app/sas/sas9.4/DocumentRepository/DDT/xxx。关键步骤后等待 5s 以适配 SAS EG 慢响应。"""
        dlg = app.Dialog
        edit = None
        for control_type in ("Edit", "ComboBox"):
            try:
                for item in dlg.descendants(control_type=control_type):
                    try:
                        name = (item.window_text() or "").strip()
                        aid = (item.element_info.automation_id or "").strip()
                        if "文件名" in name or "file name" in name.lower() or "文件名:" in name or "1148" in aid:
                            edit = item
                            break
                    except Exception:
                        continue
                if edit is not None:
                    break
            except Exception:
                continue
        if edit is None:
            for item in dlg.descendants(control_type="Edit"):
                try:
                    if item.is_enabled() and item.is_visible():
                        edit = item
                        break
                except Exception:
                    continue
        try:
            if edit is not None:
                edit.set_focus()
                time.sleep(0.5)
                try:
                    edit.set_edit_text("")
                except Exception:
                    pass
                time.sleep(0.2)
                try:
                    edit.set_edit_text(mapped_path)
                except Exception:
                    edit.type_keys(mapped_path, with_spaces=True)
                time.sleep(5.0)
            send_keys("{VK_RETURN}")
            time.sleep(2.0)
            self._click_open_button_then_enter(app, send_keys)
            return True
        except Exception:
            try:
                send_keys("{VK_RETURN}")
                return True
            except Exception:
                return False

    def _close_obstructing_popups(self, app, main_eg_win):
        """精简弹窗关闭：仅对小弹窗发 ESC，绝不点击「关闭」按钮，避免误关主窗口。"""
        try:
            main_handle = main_eg_win.handle if hasattr(main_eg_win, "handle") else None
            for win in app.windows():
                try:
                    if not win.is_visible():
                        continue
                    if main_handle is not None and getattr(win, "handle", None) == main_handle:
                        continue
                    try:
                        r = win.rectangle()
                        if r.width() >= 500 or r.height() >= 300:
                            continue
                    except Exception:
                        continue
                    title = (win.window_text() or "").strip()
                    if title and any(k in title for k in ["提示", "加载", "Processing", "Info"]):
                        try:
                            from pywinauto.keyboard import send_keys
                            send_keys("{ESC}", pause=0.1)
                            time.sleep(self.SHORT_WAIT)
                        except Exception:
                            pass
                except Exception:
                    continue
        except Exception:
            pass

    def _click_open_button_then_enter(self, app, send_keys):
        """尝试点击「打开」/「Open」按钮，再发送回车兜底，最后尝试关闭右下角提示弹框。"""
        try:
            dlg = app.Dialog
            for title in ("打开", "Open", "确定", "OK", "&Open"):
                try:
                    btn = dlg.child_window(title=title, control_type="Button")
                    if btn.exists():
                        btn.click()
                        time.sleep(self.MEDIUM_WAIT)
                        try:
                            mw = app.window(title_re=".*SAS Enterprise Guide.*")
                            self._close_obstructing_popups(app, mw)
                        except Exception:
                            pass
                        return
                except Exception:
                    continue
            for btn in dlg.descendants(control_type="Button"):
                try:
                    t = (btn.window_text() or "").strip()
                    if "打开" in t or "open" in t.lower() or "确定" in t or "ok" in t.lower():
                        btn.click()
                        time.sleep(self.MEDIUM_WAIT)
                        try:
                            mw = app.window(title_re=".*SAS Enterprise Guide.*")
                            self._close_obstructing_popups(app, mw)
                        except Exception:
                            pass
                        return
                except Exception:
                    continue
        except Exception:
            pass
        try:
            send_keys("{VK_RETURN}")
            time.sleep(self.MEDIUM_WAIT)
            try:
                mw = app.window(title_re=".*SAS Enterprise Guide.*")
                self._close_obstructing_popups(app, mw)
            except Exception:
                pass
        except Exception:
            pass

    def _ctrl_click_item(self, item):
        """对 item 模拟 Ctrl+左键点击（按住 Ctrl 再点击）。"""
        try:
            rect = item.rectangle()
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
        except Exception:
            item.click_input()
            return
        try:
            import ctypes
            VK_CONTROL = 0x11
            KEYEVENTF_KEYUP = 0x2
            ctypes.windll.user32.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.05)
            try:
                item.click_input()
            finally:
                ctypes.windll.user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            item.click_input()

    def _open_with_saseg_fallback(self, seguide_path, paths):
        """降级：复用路径转换后直接传参启动 SEGuide，可能乱码。"""
        try:
            for p in paths:
                mapped = self._convert_path_for_saseg(p)
                creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                subprocess.Popen([seguide_path, mapped], shell=False, creationflags=creationflags)
            QTimer.singleShot(0, lambda: self.update_status(f"正在使用 SAS EG 打开: {os.path.basename(paths[0])}" + (f" 等 {len(paths)} 个文件" if len(paths) > 1 else "")))
        except Exception as e:
            QTimer.singleShot(0, lambda: self.show_error(f"使用 SAS EG 打开文件时出错: {str(e)}"))
            QTimer.singleShot(0, lambda: self.update_status(str(e)))

    def _choose_sas_open(self, path_or_paths):
        """双击 .sas：始终弹出选择框（SAS EG / VS Code）；右键可设置默认打开方式。SAS EG 仅通过 _open_with_saseg 打开。"""
        paths = path_or_paths if isinstance(path_or_paths, list) else [path_or_paths]
        paths = [os.path.normpath(p).replace("/", "\\") for p in paths]
        if not paths:
            return
        name = os.path.basename(paths[0]) if paths else ""
        if len(paths) > 1:
            name = f"{name} 等 {len(paths)} 个文件"
        default_app = self.core.config.get_sas_open_with()
        dlg = SasOpenWithDialog(self, name, default_app=default_app)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        choice, use_default = dlg.get_choice(), dlg.get_use_default()
        if use_default:
            self.core.config.set_sas_open(default_app=choice)
        if choice == "sas_eg":
            self._open_with_saseg(paths)
            return
        ok, err = self.core.open_sas_with(paths, choice)
        if ok:
            self.statusBar().showMessage(f"正在打开 {len(paths)} 个文件", 3000)
            return
        QMessageBox.critical(self, "打开失败", err or "未找到 VS Code，请安装后重试。")

    def _choose_pdf_open(self, path):
        """PDF 双击：选择打开方式"""
        dlg = QMessageBox(self)
        dlg.setWindowTitle("选择打开方式")
        dlg.setText(os.path.basename(path))
        dlg.setInformativeText("请选择打开方式：")
        btn_adobe = dlg.addButton("用 Adobe Acrobat 打开", QMessageBox.ButtonRole.ActionRole)
        btn_browser = dlg.addButton("用浏览器打开", QMessageBox.ButtonRole.ActionRole)
        dlg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        dlg.exec()
        clicked = dlg.clickedButton()
        if clicked == btn_adobe:
            ok, err = self.core.open_pdf_with_adobe(path)
            if ok:
                self.statusBar().showMessage(f"正在打开 {os.path.basename(path)}", 3000)
            else:
                QMessageBox.critical(self, "打开失败", err)
        elif clicked == btn_browser:
            ok, err = self.core.open_pdf_in_browser(path)
            if ok:
                self.statusBar().showMessage(f"正在打开 {os.path.basename(path)}", 3000)
            else:
                QMessageBox.critical(self, "打开失败", err)
    
    def _on_tree_context(self, pos):
        # 必须从点击位置取节点，得到该行的真实路径（避免误用选中项或默认文档目录）
        item = self.tree.itemAt(pos)
        if not item:
            item = self.tree.currentItem()
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        typ = item.data(1, Qt.ItemDataRole.UserRole)
        if not path or not isinstance(path, str):
            return
        path = os.path.normpath(path).replace("/", "\\")
        if not os.path.isabs(path):
            path = os.path.abspath(path)
        menu = QMenu(self)
        is_pdf = path.lower().endswith(".pdf")
        is_sas = path.lower().endswith(".sas") or path.lower().endswith(".sas7bdat")
        act_adobe = act_browser = None
        act_sas_eg = act_sas_vscode = act_default_eg = act_default_vscode = None
        if is_pdf:
            act_adobe = menu.addAction("用 Adobe Acrobat 打开")
            act_browser = menu.addAction("用浏览器打开")
        if is_sas:
            act_sas_eg = menu.addAction("用 SAS EG 打开")
            act_sas_vscode = menu.addAction("用 VS Code 打开")
            menu.addSeparator()
            sub_default = menu.addMenu("设置默认打开方式")
            act_default_eg = sub_default.addAction("SAS EG")
            act_default_vscode = sub_default.addAction("VS Code")
        act_open_folder = menu.addAction("打开所在文件夹")
        act_open_folder.setData((path, typ))
        act_copy_path = menu.addAction("复制路径")
        act = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if act == act_open_folder:
            path_typ = act_open_folder.data()
            if path_typ:
                path, typ = path_typ
                if typ == "file":
                    self._open_folder_with_feedback(os.path.dirname(path), select_path=path)
                else:
                    self._open_folder_with_feedback(path)
        elif act == act_copy_path:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(path)
        elif is_pdf and act == act_adobe:
            ok, err = self.core.open_pdf_with_adobe(path)
            if ok:
                self.statusBar().showMessage(f"正在打开 {os.path.basename(path)}", 3000)
            else:
                QMessageBox.critical(self, "打开失败", err)
        elif is_pdf and act == act_browser:
            ok, err = self.core.open_pdf_in_browser(path)
            if ok:
                self.statusBar().showMessage(f"正在打开 {os.path.basename(path)}", 3000)
            else:
                QMessageBox.critical(self, "打开失败", err)
        elif is_sas and act in (act_sas_eg, act_sas_vscode):
            selected = self.tree.selectedItems()
            sas_paths = [path]
            for it in selected:
                p = it.data(0, Qt.ItemDataRole.UserRole)
                t = it.data(1, Qt.ItemDataRole.UserRole)
                if p and t == "file" and (str(p).lower().endswith(".sas") or str(p).lower().endswith(".sas7bdat")):
                    p = os.path.normpath(p).replace("/", "\\")
                    if p not in sas_paths and os.path.exists(p):
                        sas_paths.append(p)
            if act == act_sas_eg:
                self._open_with_saseg(sas_paths)
            else:
                ok, err = self.core.open_sas_with(sas_paths, "vscode")
                if ok:
                    self.statusBar().showMessage(f"正在打开 {len(sas_paths)} 个文件", 3000)
                else:
                    QMessageBox.critical(self, "打开失败", err)
        elif is_sas and act == act_default_eg:
            self.core.config.set_sas_open(default_app="sas_eg")
            self.statusBar().showMessage("默认打开方式已设为 SAS EG，生效于本次及之后打开", 3000)
        elif is_sas and act == act_default_vscode:
            self.core.config.set_sas_open(default_app="vscode")
            self.statusBar().showMessage("默认打开方式已设为 VS Code，生效于本次及之后打开", 3000)
    
    def _show_pywin32_hint_if_needed(self):
        """若因未安装 pywin32 未能解析 .lnk，则提示用户安装（仅提示一次）。"""
        if getattr(self.core, "_sas_eg_pywin32_missing", False):
            self.core._sas_eg_pywin32_missing = False
            QMessageBox.information(
                self,
                "依赖建议",
                "为通过开始菜单快捷方式准确识别 SAS EG 路径，建议安装 pywin32：\n\npip install pywin32",
            )
    
    def _restore_expanded(self, expanded: set):
        def expand_children(item: QTreeWidgetItem):
            for i in range(item.childCount()):
                child = item.child(i)
                p = child.data(0, Qt.ItemDataRole.UserRole)
                if p in expanded:
                    self.tree.expandItem(child)
                    self._on_tree_expanded(child)
                    expand_children(child)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            p = top.data(0, Qt.ItemDataRole.UserRole)
            if p in expanded:
                self.tree.expandItem(top)
                self._on_tree_expanded(top)
                expand_children(top)
    
    def _add_project(self):
        dlg = ProjectSelector(self, self.core)
        if dlg.exec():
            self._load_favorites()

class ProjectSelector(QDialog):
    """添加项目对话框：支持多选子目录，自动归类为 产品→试验→子目录；默认定位到 Z:\\projects"""

    def __init__(self, parent, core: PFNCore):
        super().__init__(parent)
        self.core = core
        self.setWindowTitle("选择要添加的项目/子目录")
        self.resize(800, 600)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setStyleSheet(
            "QTreeWidget{font-size:12px; color:#1F2329; background:#FFF;} "
            "QTreeWidget::item{color:#1F2329; background:#FFF;} "
            "QTreeWidget::item:hover{background:#D1E5FF;} "
            "QTreeWidget::item:selected{color:#165DFF; background:#E8F3FF;}"
        )
        layout.addWidget(self.tree)
        btns = QHBoxLayout()
        add_btn = QPushButton("添加选中项目")
        cancel_btn = QPushButton("取消")
        add_btn.setStyleSheet("background-color:#165DFF; color:white; border:none; border-radius:4px; padding:6px 16px;")
        cancel_btn.setStyleSheet("border:1px solid #DCDEE3; border-radius:4px; padding:6px 16px;")
        add_btn.clicked.connect(self._add_selected)
        cancel_btn.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(cancel_btn)
        btns.addWidget(add_btn)
        layout.addLayout(btns)
        roots = self.core.list_children(None)
        projects_item = None
        for r in roots:
            node = QTreeWidgetItem([r["name"]])
            node.setData(0, Qt.ItemDataRole.UserRole, r["path"])
            self.tree.addTopLevelItem(node)
            if r["name"].lower() == "projects":
                projects_item = node
            child = QTreeWidgetItem(["Loading..."])
            child.setData(0, Qt.ItemDataRole.UserRole, None)
            node.addChild(child)
        self.tree.itemExpanded.connect(self._on_expand)
        if projects_item:
            self.tree.expandItem(projects_item)
            self._on_expand(projects_item)
    
    def _on_expand(self, item):
        children = [item.child(i) for i in range(item.childCount())]
        if children and children[0].data(0, Qt.ItemDataRole.UserRole) is None:
            item.removeChild(children[0])
            path = item.data(0, Qt.ItemDataRole.UserRole)
            subs = self.core.list_children(path)
            for sub in subs:
                n = QTreeWidgetItem([sub["name"]])
                n.setData(0, Qt.ItemDataRole.UserRole, sub["path"])
                item.addChild(n)
                if not sub.get("is_leaf", False):
                    ph = QTreeWidgetItem(["Loading..."])
                    ph.setData(0, Qt.ItemDataRole.UserRole, None)
                    n.addChild(ph)
    
    def _project_from_path(self, path):
        """从路径构建 project 字典；projects/unblinded 按 产品→试验→子目录 解析以便正确归类。"""
        path = os.path.normpath(path).replace("/", "\\")
        dir_type = get_source_id_from_path(path)
        rel = path[3:] if path.upper().startswith("Z:\\") else path
        pid = rel.replace("\\", "_").replace("/", "_")
        if dir_type in ("projects", "unblinded") or (dir_type and str(dir_type).startswith("users")):
            product, trial, subdir = _product_trial_from_path(path, dir_type)
            if product and product != "unknown" and trial and subdir:
                display = f"{trial} ({subdir})"
            elif product and product != "unknown" and trial:
                display = trial
            elif product and product != "unknown":
                display = product
            else:
                display = os.path.basename(path)
                parent_name = os.path.basename(os.path.dirname(path))
                if parent_name:
                    display = f"{parent_name} ({display})"
        else:
            display = os.path.basename(path)
            parent_name = os.path.basename(os.path.dirname(path))
            if parent_name:
                display = f"{parent_name} ({display})"
        return {
            "id": pid,
            "display_name": display,
            "full_path": path,
            "dir_type": dir_type,
        }
    
    def _add_selected(self):
        sel = self.tree.selectedItems()
        if not sel:
            QMessageBox.information(self, "提示", "请选择至少一个项目或子目录（可按住 Ctrl 多选）")
            return
        existing = {os.path.normpath(f["full_path"]).replace("/", "\\") for f in self.core.get_favorites()}
        projects = []
        seen_paths = set()
        for node in sel:
            path = node.data(0, Qt.ItemDataRole.UserRole)
            if not path:
                continue
            path = os.path.normpath(path).replace("/", "\\")
            if path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                proj = self._project_from_path(path)
                projects.append(proj)
            except Exception:
                continue
        if not projects:
            QMessageBox.warning(self, "提示", "未添加任何项目")
            return
        dup_paths = [p["full_path"] for p in projects if p["full_path"] in existing]
        overwrite_dup = False
        if dup_paths:
            msg = QMessageBox(self)
            msg.setWindowTitle("路径已存在")
            msg.setText("以下路径已在收藏中，是否覆盖？")
            detail = "\n".join(dup_paths[:30])
            if len(dup_paths) > 30:
                detail += f"\n... 共 {len(dup_paths)} 条"
            msg.setDetailedText(detail)
            overwrite_btn = msg.addButton("全部覆盖", QMessageBox.ButtonRole.AcceptRole)
            skip_btn = msg.addButton("全部跳过", QMessageBox.ButtonRole.RejectRole)
            cancel_btn = msg.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            msg.exec()
            if msg.clickedButton() == cancel_btn:
                return
            overwrite_dup = msg.clickedButton() == overwrite_btn
        added_names = []
        success = 0
        fail = 0
        for proj in projects:
            if proj["full_path"] in existing and not overwrite_dup:
                fail += 1
                continue
            try:
                self.core.add_favorite(proj, overwrite=proj["full_path"] in existing)
                success += 1
                added_names.append(os.path.basename(proj["full_path"].rstrip("\\")))
            except Exception:
                fail += 1
        if success > 0:
            summary = f"添加完成：成功 {success} 个，失败 {fail} 个。"
            if added_names:
                names_str = "、".join(added_names[:15])
                if len(added_names) > 15:
                    names_str += f" 等共 {len(added_names)} 项"
                summary += f"\n已添加子目录：{names_str}"
            QMessageBox.information(self, "完成", summary)
            self.accept()
        else:
            QMessageBox.warning(self, "提示", f"未添加任何项目（跳过或失败 {fail} 个）")

def main():
    app = QApplication(sys.argv)
    core = PFNCore()
    win = QtMainWindow(core)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
