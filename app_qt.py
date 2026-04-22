"""
PFN - 临床试验项目导航工具 (PyQt6)
支持 Z 盘网络路径，左侧项目管理栏（projects/unblinded/users 分类 + 项目层级聚合），右侧按选中状态切换待办/分析与目录浏览。
"""
import sys
import os
# Windows：在导入 PyQt 等重型模块之前脱离控制台，避免「多个 python 窗口/控制台一闪而过」
# 调试需要看控制台输出时：设置环境变量 PFN_KEEP_CONSOLE=1 后启动
if __name__ == "__main__" and sys.platform == "win32":
    try:
        if os.environ.get("PFN_KEEP_CONSOLE") != "1":
            import ctypes

            ctypes.windll.kernel32.FreeConsole()
            # 脱离控制台后，print() 仍可能触发 Windows 短暂分配新控制台窗口，重定向到 NUL
            try:
                _pfn_devnull = open(os.devnull, "w", encoding="utf-8", errors="replace")
                sys.stdout = _pfn_devnull
                sys.stderr = _pfn_devnull
            except Exception:
                pass
    except Exception:
        pass
import re
from functools import partial
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QSplitter, QListWidget, QListWidgetItem,
    QTreeWidget, QTreeWidgetItem, QMenu, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QFrame, QMessageBox, QSizePolicy, QStyle, QDialog, QFileDialog,
    QStyledItemDelegate, QGraphicsDropShadowEffect, QAbstractItemView,
    QRadioButton, QCheckBox, QButtonGroup, QLineEdit, QInputDialog, QTextEdit, QDateEdit, QToolTip,
    QTabWidget, QScrollArea, QComboBox, QDialogButtonBox, QStackedWidget, QGridLayout,
    QStyleOptionViewItem,
)
from PyQt6.QtCore import (
    Qt,
    QSize,
    QTimer,
    QEvent,
    pyqtSignal,
    QSignalBlocker,
    QDate,
    QPoint,
    QUrl,
    QMimeData,
    QRectF,
    QObject,
    QRunnable,
    QThreadPool,
)
from PyQt6.QtGui import QGuiApplication, QColor, QFont, QPen, QPainter, QIcon, QCursor, QPixmap
from PyQt6.QtCore import QPropertyAnimation
import html
import shutil
import struct
import subprocess
import ctypes
import time
import threading
import webbrowser
import tempfile
import math
from datetime import datetime
import uuid
from copy import deepcopy
from config_manager import ConfigManager
from zdrive_scanner import ZDriveScanner, get_source_id_from_path
from file_matcher import FileMatcher
from icons_pfn import (
    icon_folder_yellow, icon_heart_outlined, icon_product_outlined,
    icon_for_file_soft, icon_check_circle_outlined, icon_home_outlined, icon_pushpin_outlined, icon_bars_outlined,
)


class _PMRefreshSignals(QObject):
    finished = pyqtSignal(object)  # pm dict
    failed = pyqtSignal(str)  # err


class _PMRefreshWorker(QRunnable):
    def __init__(self, pm_snapshot):
        super().__init__()
        self.pm_snapshot = pm_snapshot
        self.signals = _PMRefreshSignals()

    @staticmethod
    def _coerce_tasks(raw):
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, (dict, str))]
        if isinstance(raw, dict):
            # 兼容异常写入为 dict（如 {"0": {...}, "1": {...}}）
            keys = list(raw.keys())
            if keys and all(str(k).isdigit() for k in keys):
                out = []
                for k in sorted(keys, key=lambda x: int(x)):
                    v = raw.get(k)
                    if isinstance(v, (dict, str)):
                        out.append(v)
                return out
            return [v for v in raw.values() if isinstance(v, (dict, str))]
        return []

    def run(self):
        try:
            pm = self.pm_snapshot if isinstance(self.pm_snapshot, dict) else {}
            root_ta = pm.get("root_ta", {})
            if not isinstance(root_ta, dict):
                root_ta = {}
            subs = pm.get("subprojects", {})
            if not isinstance(subs, dict):
                subs = {}
            clean_subs = {}
            for k, v in subs.items():
                try:
                    if not isinstance(v, dict):
                        continue
                    sk = str(k or "").strip().lower()
                    if not sk:
                        continue
                    out = {
                        "subproject_name": str(v.get("subproject_name", "") or ""),
                        "root_name": str(v.get("root_name", "") or ""),
                        "path": str(v.get("path", "") or ""),
                        "status": str(v.get("status", "未完成") or "未完成"),
                        "priority": str(v.get("priority", "中") or "中"),
                        "tasks": self._coerce_tasks(v.get("tasks", [])),
                        "milestones": v.get("milestones", {}),
                    }
                    if out["status"] not in ("未完成", "已完成"):
                        out["status"] = "未完成"
                    if out["priority"] not in ("高", "中", "低"):
                        out["priority"] = "中"
                    clean_subs[sk] = out
                except Exception:
                    continue
            self.signals.finished.emit({"root_ta": root_ta, "subprojects": clean_subs})
        except Exception as e:
            try:
                self.signals.failed.emit(str(e))
            except Exception:
                pass


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


def _pfn_normalize_milestones(val):
    """统一成用于 UI 的 [{name,date}, ...] 列表（底层存储为 dict）。"""
    try:
        d = ConfigManager._normalize_milestones(val)
        if not isinstance(d, dict):
            d = {}
        out = [{"name": str(k), "date": str(v)} for k, v in d.items() if str(k).strip() and str(v).strip()]
        out.sort(key=lambda x: (x["name"].lower(), x["date"]))
        return out
    except Exception as e:
        try:
            print(f"[PFN] _pfn_normalize_milestones 失败，已忽略: {e}", flush=True)
        except Exception:
            pass
        return []


def _parse_milestone_editor_text(text: str):
    """解析时间节点编辑区：一行一条，支持 name: date 或 name：date。"""
    out = []
    for line in (text or "").splitlines():
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
            out.append({"name": n, "date": d})
    return out


def _milestones_to_editor_text(milestones) -> str:
    rows = _pfn_normalize_milestones(milestones)
    return "\n".join(f"{m['name']}: {m['date']}" for m in rows)


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
    # users：不依赖 dir_type 格式，直接从路径段判断跳过层级
    # 支持：
    # - users/<userid>/projects|project|unblinded/<...>
    # - users/projects|project|unblinded/<...>（无 userid）
    if root_name == "users":
        lower_parts = [p.lower() for p in parts]
        # 找到 users 段位置（通常就在开头）
        i = 0
        while i < len(lower_parts) and lower_parts[i] != "users":
            i += 1
        if i >= len(lower_parts):
            return parts
        # users/<userid>/X
        if i + 2 < len(lower_parts) and lower_parts[i + 2] in ("projects", "project", "unblinded"):
            return parts[i + 3 :]
        # users/X（无 userid）
        if i + 1 < len(lower_parts) and lower_parts[i + 1] in ("projects", "project", "unblinded"):
            return parts[i + 2 :]
        # users 下其他结构：至少跳过 users 自身
        return parts[i + 1 :]
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
    # users 下仅两层：可能是 (trial/subdir) 或 (product/subdir)
    root_name = _source_root_name(dir_type)
    if root_name == "users" and len(segments) == 2:
        first, second = segments[0], segments[1]
        # 若第一段看起来像 trial（例如 HRS7450_201），则按 trial/subdir 处理并推导 product
        if "_" in first and first.rsplit("_", 1)[-1].isdigit():
            trial_name, subdir_name = first, second
            product = trial_name.rsplit("_", 1)[0]
            trial = trial_name
            subdir = subdir_name
        else:
            # 否则更像 product/subdir（例如 HRS1301/dsur），归到产品下，不生成 trial
            product = first
            trial = None
            subdir = second
    return (product or "unknown", trial, subdir)


_EXCLUDED_FAVORITE_DIR_NAMES = frozenset({".git", "utility"})


def _pfn_excluded_favorite_dir(name):
    return (name or "").strip().lower() in _EXCLUDED_FAVORITE_DIR_NAMES


def _pfn_z_rel_parts(path):
    path = os.path.normpath(path or "").replace("/", "\\")
    if path.upper().startswith("Z:\\"):
        rel = path[3:]
    else:
        rel = path
    return [p for p in rel.split("\\") if p]


def _pfn_is_min_favorite_depth(path):
    """与 zdrive_scanner 一致：projects/unblinded 下深度≥4、users 下≥6 视为最小可收藏目录。"""
    parts = _pfn_z_rel_parts(path)
    if not parts:
        return False
    if parts[0].lower() == "users":
        return len(parts) >= 6
    return len(parts) >= 4


def _pfn_enumerate_addable_paths_under(root: str):
    """深度优先枚举某 Z 盘根下所有「可单独添加收藏」的目录，规则与 _expand_node_to_min_favorite_paths 一致：
    命中 _pfn_is_min_favorite_depth 的目录作为一条结果，不再向下递归。"""
    root = os.path.normpath(root or "").replace("/", "\\")
    out = []
    if not root or not os.path.isdir(root):
        return out

    def walk(p: str):
        try:
            names = sorted(os.listdir(p))
        except OSError:
            return
        for n in names:
            if _pfn_excluded_favorite_dir(n):
                continue
            fp = os.path.join(p, n)
            try:
                if not os.path.isdir(fp):
                    continue
            except OSError:
                continue
            if _pfn_is_min_favorite_depth(fp):
                out.append(os.path.normpath(fp).replace("/", "\\"))
                continue
            walk(fp)

    walk(root)
    return out


def _pfn_safe_listdir_sorted(path: str):
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _pfn_product_search_source_meta(path: str) -> tuple[str, str, int]:
    """添加项目搜索下拉：来源徽章文案、tooltip 补充、排序分组（0 projects 1 unblinded 2 users）。"""
    parts = _pfn_z_rel_parts(path)
    if not parts:
        return "?", "", 9
    a0 = parts[0].lower()
    if a0 == "projects":
        return "projects", "", 0
    if a0 == "unblinded":
        return "unblinded", "", 1
    if a0 == "users":
        extra = ""
        if len(parts) >= 3:
            extra = f"{parts[1]} · {parts[2]}"
        return "users", extra, 2
    return a0, "", 9


def _pfn_product_search_badge_stylesheet(badge: str) -> str:
    b = (badge or "").strip().lower()
    if b == "projects":
        bg, fg = "#E8F3FF", "#165DFF"
    elif b == "unblinded":
        bg, fg = "#E8F8EF", "#00B42A"
    elif b == "users":
        bg, fg = "#FFF3E8", "#D25F00"
    else:
        bg, fg = "#F2F3F5", "#4E5969"
    return (
        f"QLabel{{background-color:{bg};color:{fg};border-radius:3px;padding:1px 5px;"
        f"font-size:9px;font-weight:600;border:none;}}"
    )


def _pfn_is_z_product_directory(path: str) -> bool:
    """是否为「产品」文件夹：projects|unblinded 下二级；users 下 .../projects|unblinded 下的产品一级。"""
    parts = _pfn_z_rel_parts(path)
    n = len(parts)
    if n < 2:
        return False
    a0 = parts[0].lower()
    if a0 in ("projects", "unblinded"):
        return n == 2
    if a0 == "users":
        if n == 4 and parts[2].lower() in ("projects", "project", "unblinded"):
            return True
        if n == 3 and parts[1].lower() in ("projects", "project", "unblinded"):
            return True
    return False


def _pfn_enumerate_z_product_directories():
    """枚举 Z:\\projects、unblinded、users 下的产品目录（一级产品文件夹），返回 [(flat, path), ...]。"""
    rows = []
    seen = set()

    def add_row(p: str):
        pn = os.path.normpath(p).replace("/", "\\")
        k = pn.lower()
        if k in seen or not os.path.isdir(pn):
            return
        seen.add(k)
        parts = _pfn_z_rel_parts(pn)
        flat = "/".join(parts) if parts else os.path.basename(pn)
        rows.append((flat, pn))

    for root_nm in ("projects", "unblinded"):
        base = os.path.normpath(f"Z:\\{root_nm}").replace("/", "\\")
        if not os.path.isdir(base):
            continue
        for n in _pfn_safe_listdir_sorted(base):
            if _pfn_excluded_favorite_dir(n):
                continue
            add_row(os.path.join(base, n))

    users_base = os.path.normpath("Z:\\users").replace("/", "\\")
    if os.path.isdir(users_base):
        for uid in _pfn_safe_listdir_sorted(users_base):
            udir = os.path.join(users_base, uid)
            if not os.path.isdir(udir):
                continue
            for sub in ("projects", "project", "unblinded"):
                sdir = os.path.join(udir, sub)
                if not os.path.isdir(sdir):
                    continue
                for n in _pfn_safe_listdir_sorted(sdir):
                    if _pfn_excluded_favorite_dir(n):
                        continue
                    add_row(os.path.join(sdir, n))
    rows.sort(key=lambda x: (x[0].lower(), x[1].lower()))
    return rows


def _pfn_derive_product_name(sub_info: dict, sub_name: str, sub_key: str) -> str:
    """由子项目信息推导产品名（与待办列表逻辑一致）。"""
    rn = ""
    if isinstance(sub_info, dict):
        rn = str(sub_info.get("root_name", "") or "").strip()
    if rn:
        return rn
    sn = (sub_name or "").strip()
    if "_" in sn and sn.rsplit("_", 1)[-1].isdigit():
        return sn.rsplit("_", 1)[0]
    sk = str(sub_key or "")
    try:
        parts = [p for p in sk.replace("/", "\\").split("\\") if p]
        for i in range(len(parts) - 1):
            a = parts[i]
            b = parts[i + 1]
            if a and b and b.lower().startswith(a.lower() + "_"):
                return a
    except Exception:
        pass
    return "（未知产品）"


# 全局样式：左侧树选中仅改背景（不改文字色）
_SELECTED_STYLE = (
    "color:#165DFF; background:#E8F3FF;"
)
_HOVER_STYLE = "background:#D1E5FF;"
_NORMAL_STYLE = "color:#4E5969;"
_LEFT_TREE_STYLE = (
    "QTreeWidget{font-size:12px; color:#4E5969; background:#FFF; border:1px solid #E5E6EB; border-radius:8px; padding:4px;} "
    "QTreeWidget::item{height:24px; padding-left:6px;} "
    "QTreeWidget::item:hover{background:#EEF5FF; color:#4E5969;} "
    "QTreeWidget::item:selected{background:#F3F8FF; color:#165DFF;} "
)
_RIGHT_TREE_STYLE = (
    "QTreeWidget{font-size:12px; color:#4E5969; background:#FFF; border:1px solid #E5E6EB; border-radius:8px;} "
    "QTreeWidget::item{height:24px; padding-left:6px; padding-right:8px;} "
    "QTreeWidget::item:hover{background:#D1E5FF; color:#165DFF;} "
    "QTreeWidget::item:selected{background:#E8F3FF; color:#165DFF;} "
)


def _pfn_font_for_delegate_paint(f: QFont) -> QFont:
    """样式表 font-size 为 px 时 QFont 常为 pointSize=-1，Qt 在 QStyledItemDelegate 内会触发 setPointSize(-1) 警告。
    输出仅含正 pointSize 的字体（px 按 96dpi 换算为 pt），避免传入仍带 -1 的 QFont。"""
    fam = (f.family() or "").strip() or "Microsoft YaHei UI"
    if f.pointSize() > 0:
        g = QFont(fam)
        g.setPointSize(f.pointSize())
        return g
    if f.pixelSize() > 0:
        g = QFont(fam)
        pts = max(8, min(16, int(round(f.pixelSize() * 72.0 / 96.0))))
        g.setPointSize(pts)
        return g
    g = QFont(fam)
    g.setPointSize(9)
    return g


def _pfn_qfont_pt(point_size: int, bold: bool = False) -> QFont:
    """待办区等：样式表里写 font-size: px 易使 Qt 内部出现 pointSize=-1 并触发 setPointSize(-1) 警告；用显式 pt 字号。"""
    f = QFont("Microsoft YaHei UI")
    f.setPointSize(max(6, min(24, int(point_size))))
    if bold:
        f.setWeight(QFont.Weight.DemiBold)
    return f


class _TimeColumnDelegate(QStyledItemDelegate):
    """右侧文件树第 2 列：时间右对齐、浅灰 11px、右侧 padding"""
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        tw = self.parent()
        if isinstance(tw, QTreeWidget):
            item = tw.itemFromIndex(index)
            if item is not None:
                option.font = _pfn_font_for_delegate_paint(item.font(0))

    def paint(self, painter, option, index):
        if index.column() != 1:
            super().paint(painter, option, index)
            return
        painter.save()
        # 勿沿用 option.font（样式表下常为 pointSize=-1），避免 QFont 警告与异常度量
        font = QFont()
        font.setPixelSize(11)
        painter.setFont(font)
        painter.setPen(QColor("#86909C"))
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        rect = option.rect.adjusted(10, 0, -20, 0)  # 与文件名 10px 间距，右侧留白
        flags = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(rect, int(flags), text)
        painter.restore()


class _FavTreeDelegate(QStyledItemDelegate):
    """左侧收藏树委托：为「置顶项目」行绘制底部分隔线。"""
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        tw = self.parent()
        if isinstance(tw, QTreeWidget):
            item = tw.itemFromIndex(index)
            if item is not None:
                option.font = _pfn_font_for_delegate_paint(item.font(0))

    def paint(self, painter, option, index):
        # 先画“卡片化”的分组头：置顶项目 / projects / unblinded / users 等“下拉框”
        try:
            tw = self.parent()
            item = tw.itemFromIndex(index) if isinstance(tw, QTreeWidget) else None
            node_type = item.data(0, Qt.ItemDataRole.UserRole + 1) if item is not None else None
            is_group_header = bool(item is not None and item.parent() is None and node_type in ("pinned_source", "source"))
        except Exception:
            item = None
            node_type = None
            is_group_header = False

        if is_group_header:
            painter.save()
            # 覆盖整行（含左侧缩进空白），避免 hover 时出现“左侧白块”
            r = option.rect.adjusted(2, 3, -6, -3)
            hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            # 背景：轻微浮起，与下面收藏区区分
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F7FAFF") if hovered else QColor("#FFFFFF"))
            painter.drawRoundedRect(r, 8, 8)
            # 底部阴影：克制的双层渐隐（更“干净”）
            # 第一层：很浅、很窄
            shadow_r1 = r.adjusted(6, r.height() - 1, -6, 2)
            painter.setBrush(QColor(0, 0, 0, 10))
            painter.drawRoundedRect(shadow_r1, 6, 6)
            # 第二层：更浅、更宽，制造柔和过渡
            shadow_r2 = r.adjusted(10, r.height(), -10, 3)
            painter.setBrush(QColor(0, 0, 0, 6))
            painter.drawRoundedRect(shadow_r2, 6, 6)
            # 顶部细描边
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#DDE6F7") if hovered else QColor("#E5E6EB"), 1))
            painter.drawRoundedRect(r, 8, 8)
            painter.restore()

        # 分组头：给文字/图标留出内边距（避免贴边）
        if is_group_header:
            opt2 = QStyleOptionViewItem(option)
            opt2.rect = option.rect.adjusted(14, 0, -8, 0)
            super().paint(painter, opt2, index)
        else:
            super().paint(painter, option, index)
        try:
            draw_sep = bool(index.data(Qt.ItemDataRole.UserRole + 6))
        except Exception:
            draw_sep = False
        # 置顶项目下方不需要额外横线分隔（已用卡片阴影区分）
        if node_type == "pinned_source":
            draw_sep = False
        if not draw_sep:
            return
        painter.save()
        painter.setPen(QPen(QColor("#E5E6EB"), 1))
        y = option.rect.bottom()
        painter.drawLine(option.rect.left(), y, option.rect.right(), y)
        painter.restore()


class FavTreeWidgetItem(QTreeWidgetItem):
    """左侧收藏树节点：按层级应用字体样式（根节点加粗，子节点常规）。"""
    def __init__(self, texts=None, level=0):
        super().__init__(texts or [])
        self._pfn_level = max(0, int(level))
        self.set_level(self._pfn_level)

    def set_level(self, level):
        self._pfn_level = max(0, int(level))


class SubprojectTasksEditorDialog(QDialog):
    """子项目：上半待办任务（多行，一行一条，空行不保存）；下半项目时间节点（与任务分存储）。"""

    # 下拉列表末尾：选择后可于输入框内填写任意节点类型名称
    _MS_CUSTOM_LABEL = "（自定义）"

    class _MilestoneRow(QWidget):
        def __init__(self, parent, preset_names, custom_label: str):
            super().__init__(parent)
            self._preset_names = preset_names or []
            self._custom_label = str(custom_label or "").strip() or "（自定义）"
            h = QHBoxLayout(self)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)

            self.combo = QComboBox()
            self.combo.setEditable(True)
            self.combo.addItems(self._preset_names)
            # InsertAtTop 会在选中/回填预设时在列表顶端再插一条，下拉中易出现重复或「| 当前项」类条目
            self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            self.combo.setMinimumWidth(140)
            self.combo.setFixedHeight(28)

            self.date_edit = QDateEdit()
            self.date_edit.setCalendarPopup(True)
            self.date_edit.setDisplayFormat("yyyy-MM-dd")
            self.date_edit.setFixedHeight(28)
            self.date_edit.setMinimumWidth(120)
            # 默认日期=当天（避免 2000-01-01）
            try:
                self.date_edit.setDate(QDate.currentDate())
            except Exception:
                pass
            try:
                self.date_edit.setKeyboardTracking(False)
            except Exception:
                pass

            # 兼容“4月底/四月底”等非标准日期：允许用户手输文本，优先保存该字段
            self.date_text = QLineEdit()
            self.date_text.setPlaceholderText("可手输：如 2026-04-30 / 四月底")
            self.date_text.setFixedHeight(28)

            self.btn_add = QPushButton("+")
            self.btn_del = QPushButton("×")
            for b in (self.btn_add, self.btn_del):
                b.setFixedSize(28, 28)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setStyleSheet(
                    "QPushButton{border:1px solid #DCDEE3; border-radius:6px; background:#FFFFFF; color:#4E5969;}"
                    "QPushButton:hover{background:#F2F3F5; color:#1F2329; border-color:#C9CDD4;}"
                )

            self.combo.setStyleSheet("QComboBox{border:1px solid #DCDEE3; border-radius:6px; padding:0 8px;}")
            self.date_edit.setStyleSheet("QDateEdit{border:1px solid #DCDEE3; border-radius:6px; padding:0 8px;}")
            self.date_text.setStyleSheet("QLineEdit{border:1px solid #DCDEE3; border-radius:6px; padding:0 8px;}")

            h.addWidget(self.combo, 0)
            h.addWidget(self.date_edit, 0)
            h.addWidget(self.date_text, 1)
            h.addWidget(self.btn_add, 0)
            h.addWidget(self.btn_del, 0)

        def set_values(self, name: str, date_str: str):
            name = str(name or "").strip()
            if name == self._custom_label:
                name = ""
            date_str = str(date_str or "").strip()
            if name:
                if self.combo.findText(name) < 0:
                    self.combo.insertItem(0, name)
                self.combo.setCurrentText(name)
            else:
                self.combo.setCurrentText(self._custom_label)

            if re.match(r"^\\d{4}-\\d{2}-\\d{2}$", date_str):
                try:
                    from PyQt6.QtCore import QDate

                    qd = QDate.fromString(date_str, "yyyy-MM-dd")
                    if qd and qd.isValid():
                        self.date_edit.setDate(qd)
                        self.date_text.setText("")
                        return
                except Exception:
                    pass
            self.date_text.setText(date_str)

        def get_pair(self):
            name = str(self.combo.currentText() or "").strip()
            if name == self._custom_label:
                name = ""
            dt = str(self.date_text.text() or "").strip()
            if not dt:
                try:
                    dt = self.date_edit.date().toString("yyyy-MM-dd")
                except Exception:
                    dt = ""
            return name, dt

    def __init__(self, parent, title, task_lines, milestones=None, milestones_only=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._milestones_only = bool(milestones_only)
        self._ms_preset_base = ["dry-run", "DBL", "FPI", "期中分析"]
        self._ms_preset = self._ms_preset_base + [self._MS_CUSTOM_LABEL]

        if self._milestones_only:
            self.setMinimumWidth(480)
            self.setMaximumWidth(560)
            self.resize(500, 400)
            self.setModal(True)
        else:
            self.resize(640, 520)
        lay = QVBoxLayout(self)
        if self._milestones_only:
            lay.setContentsMargins(20, 16, 20, 14)
            lay.setSpacing(12)
        else:
            lay.setSpacing(10)
        h1 = QLabel("待办任务（一行一条，按 Enter 换行；空行不保存）")
        h1.setStyleSheet("color:#1F2329; font-weight:600;")
        lay.addWidget(h1)
        self.edit_tasks = QTextEdit()
        self.edit_tasks.setPlaceholderText("例如：\n完成 ADAM 分析\n整理 SAE 数据\n提交统计代码")
        self.edit_tasks.setPlainText("\n".join(task_lines or []))
        self.edit_tasks.setMinimumHeight(160)
        lay.addWidget(self.edit_tasks)
        if self._milestones_only:
            h1.hide()
            self.edit_tasks.hide()

        if self._milestones_only:
            h2 = QLabel("项目时间节点")
            h2.setStyleSheet("color:#1F2329; font-size:15px; font-weight:600;")
            lay.addWidget(h2)
            ex = QLabel("选择类型或选「（自定义）」后输入名称；日期可点选或手填（如「四月底」）。")
            ex.setWordWrap(True)
            ex.setStyleSheet("color:#86909C; font-size:12px;")
            lay.addWidget(ex)
        else:
            h2 = QLabel("项目时间节点")
            h2.setStyleSheet("color:#1F2329; font-weight:600;")
            lay.addWidget(h2)
            ex = QLabel("左侧选择节点类型（可自定义输入），右侧选择日期或手动输入（如“四月底”）。")
            ex.setStyleSheet("color:#86909C; font-size:11px;")
            lay.addWidget(ex)

        self.ms_scroll = QScrollArea()
        self.ms_scroll.setWidgetResizable(True)
        self.ms_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.ms_scroll.setStyleSheet("QScrollArea{background:transparent; border:none;}")
        ms_cont = QWidget()
        if self._milestones_only:
            ms_cont.setStyleSheet("background:#F7F8FA; border-radius:10px; border:1px solid #EDEFF2;")
            self._ms_layout = QVBoxLayout(ms_cont)
            self._ms_layout.setContentsMargins(12, 12, 12, 12)
        else:
            self._ms_layout = QVBoxLayout(ms_cont)
            self._ms_layout.setContentsMargins(0, 0, 0, 0)
        self._ms_layout.setSpacing(8)
        self.ms_scroll.setWidget(ms_cont)
        if self._milestones_only:
            self.ms_scroll.setMinimumHeight(200)
            self.ms_scroll.setMaximumHeight(280)
            lay.addWidget(self.ms_scroll, 0)
        else:
            lay.addWidget(self.ms_scroll, 1)

        self._ms_rows = []
        self._build_milestone_rows(milestones)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        if self._milestones_only:
            self.setStyleSheet("QDialog{font-size:12px; color:#1F2329; background:#FFFFFF;}")
            ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)
            cancel_btn = btns.button(QDialogButtonBox.StandardButton.Cancel)
            _btn_ok = (
                "QPushButton{background:#165DFF;color:#FFFFFF;border:none;border-radius:8px;"
                "padding:6px 20px;min-width:88px;font-size:12px;}"
                "QPushButton:hover{background:#4080FF;} QPushButton:pressed{background:#0E42D2;}"
            )
            _btn_cancel = (
                "QPushButton{background:#FFFFFF;color:#4E5969;border:1px solid #DCDEE3;border-radius:8px;"
                "padding:6px 20px;min-width:88px;font-size:12px;}"
                "QPushButton:hover{background:#F7F8FA; border-color:#C9CDD4;}"
            )
            if ok_btn is not None:
                ok_btn.setStyleSheet(_btn_ok)
            if cancel_btn is not None:
                cancel_btn.setStyleSheet(_btn_cancel)
        else:
            self.setStyleSheet("QDialog{font-size:12px; color:#1F2329;}")

    def get_task_lines(self):
        text = self.edit_tasks.toPlainText()
        return [x.strip() for x in text.splitlines() if x.strip()]

    def _build_milestone_rows(self, milestones):
        d = ConfigManager._normalize_milestones(milestones)
        if not isinstance(d, dict):
            d = {}
        items = list(d.items())
        order = {n.lower(): i for i, n in enumerate(self._ms_preset)}
        items.sort(key=lambda kv: (order.get(str(kv[0]).lower(), 999), str(kv[0]).lower()))

        if not items:
            self._add_ms_row()
            return
        for n, dt in items:
            r = self._add_ms_row()
            r.set_values(n, dt)
        self._add_ms_row()

    def _add_ms_row(self):
        row = SubprojectTasksEditorDialog._MilestoneRow(self, self._ms_preset, self._MS_CUSTOM_LABEL)
        row.btn_add.clicked.connect(lambda _=False, r=row: self._on_ms_add_clicked(r))
        row.btn_del.clicked.connect(lambda _=False, r=row: self._on_ms_del_clicked(r))
        self._ms_rows.append(row)
        self._ms_layout.addWidget(row)
        self._update_ms_del_enabled()
        return row

    def _on_ms_add_clicked(self, _row):
        self._add_ms_row()

    def _on_ms_del_clicked(self, row):
        if len(self._ms_rows) <= 1:
            return
        try:
            self._ms_rows.remove(row)
        except ValueError:
            return
        row.setParent(None)
        row.deleteLater()
        self._update_ms_del_enabled()

    def _update_ms_del_enabled(self):
        can_del = len(self._ms_rows) > 1
        for r in self._ms_rows:
            r.btn_del.setEnabled(can_del)

    def get_milestones_dict(self):
        out = {}
        for r in self._ms_rows:
            n, dt = r.get_pair()
            if n and dt:
                out[n] = dt
        return out


class SingleTodoTaskEditDialog(QDialog):
    """单条待办：内容、优先级、完成状态（与项目时间节点无关）。"""

    def __init__(self, parent, title, task_dict, default_priority="中"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(440, 280)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("任务内容"))
        self.edit_content = QTextEdit()
        self.edit_content.setPlaceholderText("输入任务描述")
        if task_dict and isinstance(task_dict, dict):
            self.edit_content.setPlainText(str(task_dict.get("content", "") or ""))
        lay.addWidget(self.edit_content)

        row = QHBoxLayout()
        row.addWidget(QLabel("优先级"))
        self.combo_pri = QComboBox()
        self.combo_pri.addItems(["高", "中", "低"])
        dp = str(default_priority or "中")
        if dp not in ("高", "中", "低"):
            dp = "中"
        self.combo_pri.setCurrentText(dp)
        if task_dict and isinstance(task_dict, dict):
            tp = str(task_dict.get("priority", "") or "").strip()
            if tp in ("高", "中", "低"):
                self.combo_pri.setCurrentText(tp)
        row.addWidget(self.combo_pri, 1)
        lay.addLayout(row)

        self.chk_done = QCheckBox("标记为已完成")
        done = False
        if task_dict and isinstance(task_dict, dict):
            s = task_dict.get("status", "未完成")
            if s is True or s == 1:
                done = True
            else:
                s = str(s or "").strip()
                done = s in ("已完成", "完成", "done", "Done", "DONE")
        self.chk_done.setChecked(done)
        lay.addWidget(self.chk_done)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self.setStyleSheet("QDialog{font-size:12px; color:#1F2329;}")

    def get_content(self):
        return str(self.edit_content.toPlainText() or "").strip()

    def get_priority(self):
        p = str(self.combo_pri.currentText() or "中")
        return p if p in ("高", "中", "低") else "中"

    def is_done(self):
        return self.chk_done.isChecked()


class SimplePieChartWidget(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = [("未完成", 0), ("已完成", 0)]
        self._segments = []
        self._hover_label = ""
        self._hover_range = None  # (start_deg, end_deg)
        self.setMinimumHeight(160)
        self.setMouseTracking(True)

    def set_data(self, rows):
        self._data = [(str(k), max(0, int(v))) for k, v in (rows or [])]
        self._hover_label = ""
        self._hover_range = None
        self.update()

    def _pie_pointer_cw_degrees(self, pt):
        """与 drawPie(-start*16, -span*16) 一致：从 3 点方向顺时针 [0,360)。"""
        cx = self.width() * 0.38
        cy = self.height() * 0.52
        radius = min(self.width(), self.height()) * 0.34
        dx = float(pt.x() - cx)
        dy = float(pt.y() - cy)
        d2 = dx * dx + dy * dy
        r_out = radius * 1.05
        r_in = radius * 0.08
        if d2 > r_out * r_out or d2 < r_in * r_in:
            return None
        return (360.0 - math.degrees(math.atan2(-dy, dx))) % 360.0

    def mouseMoveEvent(self, event):
        if not self._segments:
            QToolTip.hideText()
            if self._hover_label:
                self._hover_label = ""
                self._hover_range = None
                self.update()
            return
        pt = event.position()
        cw = self._pie_pointer_cw_degrees(pt)
        if cw is None:
            QToolTip.hideText()
            if self._hover_label:
                self._hover_label = ""
                self._hover_range = None
                self.update()
            return
        total = sum(v for _, v in self._data) or 0
        found = None
        n = len(self._segments)
        for i, (label, start_deg, end_deg, value) in enumerate(self._segments):
            if i < n - 1:
                hit = start_deg <= cw < end_deg
            else:
                hit = cw >= start_deg - 1e-6
            if hit:
                found = (label, start_deg, end_deg, value)
                break
        if not found:
            QToolTip.hideText()
            if self._hover_label:
                self._hover_label = ""
                self._hover_range = None
                self.update()
            return
        label, s, e, value = found
        if label != self._hover_label:
            self._hover_label = label
            self._hover_range = (s, e)
            self.update()
        pct = (value / total * 100.0) if total > 0 else 0.0
        QToolTip.showText(
            QCursor.pos(),
            f"{label}\n数量：{value}\n占比：{pct:.1f}%",
            self,
        )

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._segments:
            return
        pt = event.position()
        cw = self._pie_pointer_cw_degrees(pt)
        if cw is None:
            return
        n = len(self._segments)
        for i, (label, start_deg, end_deg, _value) in enumerate(self._segments):
            if i < n - 1:
                hit = start_deg <= cw < end_deg
            else:
                hit = cw >= start_deg - 1e-6
            if hit:
                self.clicked.emit(label)
                return

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        total = sum(v for _, v in self._data)
        # 左饼右图例
        cx = self.width() * 0.38
        cy = self.height() * 0.52
        radius = min(self.width(), self.height()) * 0.34
        rect = (cx - radius, cy - radius, radius * 2, radius * 2)
        # ongoing=rosepink, complete=soft green
        colors = {
            "未完成": QColor("#F5A3B7"),
            "已完成": QColor("#86D58B"),
        }
        self._segments = []
        if total <= 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#E5E6EB"))
            painter.drawEllipse(int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3]))
            painter.setPen(QColor("#86909C"))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "暂无数据")
            return
        start = 0.0
        # 先计算 segments，再绘制（hover 时单独放大）
        segs = []
        for (label, value) in self._data:
            if value <= 0:
                continue
            span = value / total * 360.0
            segs.append((label, start, start + span, value))
            start += span
        self._segments = segs

        for label, s, e, value in segs:
            span = e - s
            mid = (s + e) / 2.0
            is_hover = label == self._hover_label and self._hover_range is not None
            # hover 轻微放大并沿扇区方向偏移一点
            rr = radius * (1.06 if is_hover else 1.0)
            ox = 0.0
            oy = 0.0
            if is_hover:
                rad = math.radians(mid)
                ox = math.cos(rad) * (radius * 0.03)
                oy = -math.sin(rad) * (radius * 0.03)
            r2 = (cx + ox - rr, cy + oy - rr, rr * 2, rr * 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(colors.get(label, QColor("#AAB2BD")))
            painter.drawPie(int(r2[0]), int(r2[1]), int(r2[2]), int(r2[3]), int(-s * 16), int(-span * 16))

        # 图例（右侧）
        legend_x = int(self.width() * 0.70)
        legend_y = int(self.height() * 0.30)
        painter.setPen(QColor("#1F2329"))
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)
        box = 10
        line_h = 18
        i = 0
        for label in ("未完成", "已完成"):
            value = next((v for k, v in self._data if k == label), 0)
            pct = (value / total * 100.0) if total > 0 else 0.0
            painter.setBrush(colors.get(label, QColor("#AAB2BD")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(legend_x, legend_y + i * line_h, box, box, 2, 2)
            painter.setPen(QColor("#4E5969"))
            painter.drawText(
                legend_x + box + 8,
                legend_y + i * line_h + box,
                f"{label}  {value}（{pct:.0f}%）",
            )
            i += 1


class SimpleBarChartWidget(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self._bar_regions = []  # [(label, QRectF)]
        self._hover_label = ""
        self.setMinimumHeight(160)
        self.setMouseTracking(True)

    def set_data(self, rows):
        self._data = [(str(k), max(0, int(v))) for k, v in (rows or [])]
        self._hover_label = ""
        self.update()

    def mouseMoveEvent(self, event):
        pt = event.position()
        found = ""
        val = 0
        for label, rect, v in (self._bar_regions or []):
            try:
                if rect.contains(pt):
                    found = str(label)
                    val = int(v)
                    break
            except Exception:
                continue
        if found:
            if found != self._hover_label:
                self._hover_label = found
                self.update()
            QToolTip.showText(QCursor.pos(), f"{found}\n项目数：{val}", self)
        else:
            QToolTip.hideText()
            if self._hover_label:
                self._hover_label = ""
                self.update()

    def mousePressEvent(self, event):
        try:
            pt = event.position()
        except Exception:
            return
        for label, rect, _v in (self._bar_regions or []):
            try:
                if rect.contains(pt):
                    self.clicked.emit(str(label))
                    return
            except Exception:
                continue

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._bar_regions = []
        if not self._data:
            painter.setPen(QColor("#86909C"))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "暂无数据")
            return
        l, t, r, b = 28, 14, 14, 34
        chart_w = max(1, self.width() - l - r)
        chart_h = max(1, self.height() - t - b)
        max_v = max(v for _, v in self._data) or 1
        bar_w = max(16, int(chart_w / max(1, len(self._data) * 2)))
        gap = max(8, int((chart_w - bar_w * len(self._data)) / max(1, len(self._data) + 1)))
        x = l + gap
        base_c = QColor("#A7D8FF")  # lightblue
        hover_c = QColor("#6CB7FF")

        # 网格线
        painter.setPen(QPen(QColor("#EDEFF2"), 1, Qt.PenStyle.DashLine))
        for i in range(1, 4):
            yy = t + int(chart_h * i / 4)
            painter.drawLine(l, yy, l + chart_w, yy)
        painter.setPen(QPen(QColor("#E5E6EB"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(l, t, chart_w, chart_h), 10.0, 10.0)

        for i, (name, val) in enumerate(self._data):
            h = int((val / max_v) * (chart_h - 8))
            y = t + chart_h - h
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(hover_c if str(name) == self._hover_label else base_c)
            painter.drawRoundedRect(x, y, bar_w, h, 6, 6)
            try:
                self._bar_regions.append((name, QRectF(x, y, bar_w, h if h > 6 else 10), val))
            except Exception:
                pass
            painter.setPen(QColor("#4E5969"))
            painter.drawText(x - 12, t + chart_h + 18, bar_w + 24, 14, int(Qt.AlignmentFlag.AlignCenter), name)
            # 顶部数值
            painter.setPen(QColor("#1F2329"))
            painter.drawText(x - 12, max(t, y - 16), bar_w + 24, 14, int(Qt.AlignmentFlag.AlignCenter), str(val))
            x += bar_w + gap


class SimpleLineChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []
        self._points = []  # [(label, x, y, v)]
        self._hover_idx = -1
        self.setMinimumHeight(170)
        self.setMouseTracking(True)

    def set_data(self, rows):
        self._data = [(str(k), max(0, int(v))) for k, v in (rows or [])]
        self._hover_idx = -1
        self.update()

    def mouseMoveEvent(self, event):
        if not self._points:
            return
        pt = event.position()
        best = -1
        best_d2 = 10_000_000
        for i, (_k, x, y, v) in enumerate(self._points):
            dx = pt.x() - x
            dy = pt.y() - y
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2 = d2
                best = i
        if best >= 0 and best_d2 <= 13 * 13:
            if best != self._hover_idx:
                self._hover_idx = best
                self.update()
            k, _x, _y, v = self._points[best]
            QToolTip.showText(QCursor.pos(), f"{k}\n当月完成：{v}", self)
        else:
            QToolTip.hideText()
            if self._hover_idx != -1:
                self._hover_idx = -1
                self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._data:
            painter.setPen(QColor("#86909C"))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "暂无数据")
            return
        l, t, r, b = 40, 16, 18, 36
        chart_w = max(1, self.width() - l - r)
        chart_h = max(1, self.height() - t - b)
        max_v = max(v for _, v in self._data) or 1
        # 网格线
        painter.setPen(QPen(QColor("#EDEFF2"), 1, Qt.PenStyle.DashLine))
        for i in range(1, 4):
            yy = t + int(chart_h * i / 4)
            painter.drawLine(l, yy, l + chart_w, yy)
        painter.setPen(QPen(QColor("#E5E6EB"), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(l, t, chart_w, chart_h), 10.0, 10.0)
        step = chart_w / max(1, len(self._data) - 1)
        points = []
        for i, (_k, v) in enumerate(self._data):
            x = l + i * step
            y = t + chart_h - (v / max_v) * chart_h
            points.append((x, y, v))
        # 主蓝色 #1677ff
        painter.setPen(QPen(QColor("#1677ff"), 2))
        for i in range(len(points) - 1):
            painter.drawLine(int(points[i][0]), int(points[i][1]), int(points[i + 1][0]), int(points[i + 1][1]))
        painter.setBrush(QColor("#1677ff"))
        painter.setPen(Qt.PenStyle.NoPen)
        self._points = []
        for i, (x, y, v) in enumerate(points):
            rr = 4 if i == self._hover_idx else 3
            painter.drawEllipse(int(x - rr), int(y - rr), rr * 2, rr * 2)
            try:
                k = str(self._data[i][0])
            except Exception:
                k = ""
            self._points.append((k, float(x), float(y), int(v)))
        painter.setPen(QColor("#4E5969"))
        # 强制显示完整 12 个月标签：避免最后一个月份被裁剪
        label_w = 64
        label_h = 14
        for i, (k, _v) in enumerate(self._data):
            x = l + i * step
            rx = int(x - label_w / 2)
            # clamp: 确保不越界导致 12 月缺失
            rx = max(0, min(rx, self.width() - label_w))
            painter.drawText(rx, t + chart_h + 16, label_w, label_h, int(Qt.AlignmentFlag.AlignCenter), k)


class PFNCore:
    def __init__(self):
        self.config = ConfigManager()
        self.scanner = ZDriveScanner()
        self.matcher = FileMatcher()
        self.fs_expanded = {}
        self._match_cache = {}
        self._doc_scan_cache = {}
        self._sas_eg_pywin32_missing = False
        # setup.xlsx：每次点击根据「Excel 是否已打开该原文件」决定编辑版/参考版（不缓存“第几次点击”状态）
        self._setup_ref_dir = os.path.join(tempfile.gettempdir(), "PFN_Reference")
        try:
            os.makedirs(self._setup_ref_dir, exist_ok=True)
        except Exception:
            pass
        self._cleanup_stale_setup_references()
    
    def _sanitize_filename_part(self, s: str, max_len: int = 60) -> str:
        """用于拼接到文件名中的安全片段：去除 Windows 非法字符并截断。"""
        try:
            s = str(s or "").strip()
        except Exception:
            return ""
        if not s:
            return ""
        # Windows 文件名非法字符：\ / : * ? " < > |
        s = re.sub(r'[\\/:*?"<>|]+', "_", s)
        s = re.sub(r"\s+", " ", s).strip()
        # 去掉末尾句点/空格（Windows 不允许）
        s = s.rstrip(" .")
        if max_len and len(s) > max_len:
            s = s[:max_len].rstrip(" ._")
        return s

    def _guess_dir_type_from_path(self, p: str) -> str:
        p = os.path.normpath(str(p or "")).replace("/", "\\").lower()
        # 粗略判断即可：仅用于解析 sub_key
        if "\\unblinded\\" in p or p.endswith("\\unblinded") or p.endswith("\\unblinded\\"):
            return "unblinded"
        if "\\users\\" in p or p.endswith("\\users") or p.endswith("\\users\\"):
            return "users"
        return "projects"

    def _derive_subproject_name_from_config(self, setup_path: str, project_tag: str) -> str:
        """
        从配置的 project_management.subprojects 中，按路径推导 sub_key，取用户维护的 subproject_name。
        取不到则返回空字符串。
        """
        try:
            pm = self.config.get_project_management()
            subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
            if not isinstance(subs, dict) or not subs:
                return ""
        except Exception:
            return ""

        dir_type = self._guess_dir_type_from_path(setup_path)
        # 尽量使用 trial 名（如 SHR2004_101）作为定位锚点
        trial = None
        try:
            _product, trial, _subdir = _product_trial_from_path(setup_path, dir_type)
        except Exception:
            trial = None
        if not trial:
            trial = project_tag or ""
        if not trial:
            return ""

        try:
            parts = [x for x in os.path.normpath(str(setup_path or "")).replace("/", "\\").split("\\") if x]
            idx = next((i for i, seg in enumerate(parts) if seg == trial), -1)
            if idx >= 0:
                trial_path = "\\".join(parts[: idx + 1])
                if not trial_path.upper().startswith("Z:") and ":" not in trial_path:
                    trial_path = "Z:\\" + trial_path
            else:
                trial_path = os.path.dirname(os.path.dirname(setup_path))  # 退化：setup.xlsx 的上一级
        except Exception:
            trial_path = ""

        sub_key = os.path.normpath(str(trial_path or "")).replace("/", "\\").lower()
        info = subs.get(sub_key)
        if not isinstance(info, dict):
            return ""
        name = str(info.get("subproject_name", "") or "").strip()
        return name

    def _norm_path_key(self, p: str) -> str:
        try:
            return os.path.normpath(os.path.abspath(os.fspath(p))).replace("/", "\\").lower()
        except Exception:
            return os.path.normpath(str(p or "")).replace("/", "\\").lower()

    def _is_file_locked_win(self, p: str) -> bool:
        """Windows: 判断文件是否被其他进程占用（Excel 独占打开时通常为 True）。非 Windows 返回 False。"""
        if sys.platform != "win32":
            return False
        try:
            p = os.fspath(p)
        except Exception:
            return True
        GENERIC_READ = 0x80000000
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
        try:
            h = ctypes.windll.kernel32.CreateFileW(
                p, GENERIC_READ, 0, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None
            )
            if h == INVALID_HANDLE_VALUE:
                return True
            ctypes.windll.kernel32.CloseHandle(h)
            return False
        except Exception:
            return True

    def _fallback_should_use_setup_reference_copy(self, path: str) -> bool:
        """
        无 pywin32 或 COM 失败时兜底：仅当「本路径」被独占占用时，认为可能已在本机 Excel 中打开。
        无法检测「已打开项目 A 的 setup，再点项目 B 的 setup」这种跨路径同名（需安装 pywin32）。
        """
        if not os.path.isfile(path):
            return False
        return self._is_file_locked_win(path)

    def _excel_should_use_setup_reference_copy(self, path: str) -> bool:
        """
        是否应打开临时参考版而非原文件。

        Excel 限制：**不能同时打开两个同名工作簿**（即使路径不同）。因此只要当前已运行的
        Excel 里存在任意文件名为 setup.xlsx 的工作簿，再打开任意路径下的 setup.xlsx 都必须
        走临时目录中的副本，否则会弹出「无法同时打开两个同名的工作簿」。
        """
        if os.path.basename(path).lower() != "setup.xlsx":
            return False
        try:
            import pythoncom

            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            import win32com.client

            xl = win32com.client.GetActiveObject("Excel.Application")
            wbs = xl.Workbooks
            n = int(wbs.Count)
            for i in range(1, n + 1):
                try:
                    wb = wbs.Item(i)
                    fn = str(getattr(wb, "FullName", "") or "")
                    if not fn:
                        continue
                    if os.path.basename(fn).lower() == "setup.xlsx":
                        return True
                except Exception:
                    continue
            return False
        except Exception:
            return self._fallback_should_use_setup_reference_copy(path)

    def _cleanup_stale_setup_references(self):
        """启动时尽量清理历史残留的参考版副本（若仍被占用则忽略）。"""
        try:
            if not os.path.isdir(self._setup_ref_dir):
                return
            for n in os.listdir(self._setup_ref_dir):
                nl = n.lower()
                legacy = nl.startswith("setup_") and "参考版" in n and nl.endswith(".xlsx")
                current = nl.endswith("_setup_参考版.xlsx")
                if not (legacy or current):
                    continue
                p = os.path.join(self._setup_ref_dir, n)
                try:
                    os.remove(p)
                except Exception:
                    continue
        except Exception:
            pass

    def _setup_reference_dest_path(self, setup_path: str) -> str:
        """参考版固定名：{项目名称}_Setup_参考版.xlsx，位于 temp\\PFN_Reference。"""
        tag = self._derive_project_tag_from_path(setup_path)
        cfg_name = self._derive_subproject_name_from_config(setup_path, tag)
        display = (cfg_name or "").strip() or (tag or "").strip() or "Project"
        safe = self._sanitize_filename_part(display, max_len=80) or "Project"
        fname = f"{safe}_Setup_参考版.xlsx"
        return os.path.join(self._setup_ref_dir, fname)

    def _copy_setup_overwrite(self, src: str, dst: str):
        parent = os.path.dirname(dst)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception:
                pass
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except Exception:
                pass
        shutil.copy2(src, dst)

    def _derive_project_tag_from_path(self, file_path: str) -> str:
        """从路径中提取项目名（如 SHR2004_101 / HRS2183_101），用于参考版文件名。"""
        try:
            parts = [p for p in os.path.normpath(file_path).replace("/", "\\").split("\\") if p]
        except Exception:
            parts = []
        # 优先匹配类似 SHR2004_101 / HRS2183_101
        for p in parts:
            if re.match(r"^[A-Z]{3}\d+_\d+$", p):
                return p
        # 退化：用父目录名
        try:
            return os.path.basename(os.path.dirname(file_path)) or "Project"
        except Exception:
            return "Project"

    def _open_setup_xlsx(self, path: str):
        """setup.xlsx：按 Excel 中是否已有「同名 setup.xlsx」工作簿区分编辑版/参考版。返回 (success, msg_or_err)。"""
        path = os.path.normpath(path).replace("/", "\\")
        if not os.path.isfile(path):
            return False, "文件路径不存在"
        try:
            os.makedirs(self._setup_ref_dir, exist_ok=True)
        except Exception:
            pass

        if self._excel_should_use_setup_reference_copy(path):
            ref_path = self._setup_reference_dest_path(path)
            try:
                self._copy_setup_overwrite(path, ref_path)
            except Exception as e:
                return False, f"复制参考版失败：{e}"
            excel = None
            try:
                excel = self._find_excel()
            except Exception:
                excel = None
            try:
                if excel and os.path.isfile(excel):
                    subprocess.Popen([excel, ref_path], shell=False)
                else:
                    ok, err = self._shell_open(ref_path)
                    if not ok:
                        raise RuntimeError(err or "Shell 打开失败")
            except Exception as e:
                return False, f"打开参考版失败：{e}"
            return True, None

        ok, err = self._shell_open(path)
        return (ok, None) if ok else (False, err or "无法打开 setup.xlsx")
    
    def get_favorites(self):
        return self.config.get_favorites()
    
    def add_favorite(self, project, overwrite=False, autosave=True):
        self.config.add_favorite(project, overwrite=overwrite)
        if autosave:
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

    def _scan_documentation_extra_files(self, scan_path):
        """扫描指定路径下所有 .xlsx 文件，按文件名升序；结果缓存，避免重复扫描。返回 [(display, path), ...]。"""
        if not scan_path:
            return []
        scan_path = os.path.normpath(scan_path).replace("/", "\\")
        if scan_path in self._doc_scan_cache:
            return self._doc_scan_cache[scan_path]
        result = []
        try:
            if os.path.isdir(scan_path):
                for n in sorted(os.listdir(scan_path)):
                    if n.lower().endswith(".xlsx"):
                        p = os.path.join(scan_path, n)
                        if os.path.isfile(p):
                            result.append((n, p))
        except Exception:
            pass
        self._doc_scan_cache[scan_path] = result
        return result

    def get_documentation_xlsx_list(self, base_path):
        """返回 Documentation 下拉框数据：[(display, path), ...]，中间用 (None, None) 表示分隔线。顶部常用项来自配置+match_files，分隔线下方来自 documentation_scan_path/scan_root 下其他 .xlsx。"""
        doc_cfg = self.config.get_documentation_paths()
        common_keys = doc_cfg.get("common") or []
        scan_path_cfg = (doc_cfg.get("documentation_scan_path") or doc_cfg.get("scan_root") or "").strip()
        out = []
        common_paths = set()
        if base_path:
            base_path = os.path.normpath(base_path).replace("/", "\\")
            files = self.match_files(base_path)
            for k in common_keys:
                key = k.replace(".xlsx", "").strip()
                v = files.get(key)
                if not v:
                    continue
                paths = v if isinstance(v, list) else [v]
                for fp in paths:
                    if isinstance(fp, str) and fp.lower().endswith(".xlsx") and os.path.isfile(fp):
                        out.append((os.path.basename(fp), fp))
                        common_paths.add(os.path.normpath(fp))
                        break
        need_sep = bool(out)
        other = []
        if scan_path_cfg:
            root = os.path.normpath(scan_path_cfg).replace("/", "\\")
            if not os.path.isabs(root) and base_path:
                root = os.path.normpath(os.path.join(base_path, root))
            extra = self._scan_documentation_extra_files(root)
            for n, p in extra:
                pnorm = os.path.normpath(p)
                if pnorm not in common_paths:
                    other.append((n, p))
        if need_sep and other:
            out.append((None, None))
        out.extend(other)
        return out

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
        # setup.xlsx：差异化打开（编辑版/参考版）
        if os.path.basename(path).lower() == "setup.xlsx":
            return self._open_setup_xlsx(path)
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
        # XML：define 类文件优先用浏览器打开（避免 Excel 打开导致乱码/显示异常）
        if ext == ".xml":
            base = os.path.basename(path).lower()
            if base == "define.xml" or "define" in base:
                try:
                    webbrowser.open("file:///" + path.replace("\\", "/"))
                    return True, None
                except Exception:
                    # 失败则走系统关联兜底
                    pass

        # Excel/Word 等：优先 ShellExecute，由系统关联程序打开
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
    refresh_folder_done = pyqtSignal(object, object, object)  # item, err(str|None), result(list)
    # SAS EG 自动化等待时间（精准等待 + 缩短启动到展开间隔）
    SHORT_WAIT = 0.2   # 短等待（控件就绪）
    MEDIUM_WAIT = 0.6  # 中等等待（节点展开/界面刷新）
    LONG_WAIT = 2.5    # 长等待（文件加载）
    MAX_EG_START_WAIT = 10   # EG 启动后等待服务器树就绪的最大秒数（需求≤10s）
    TREE_CHECK_INTERVAL = 0.25  # 服务器树就绪检测间隔（秒）
    NODE_EXPAND_TIMEOUT = 1.0   # 单节点展开检测超时（秒），需求≤1s
    # 本机 SAS EG 左侧「SASApp」在屏幕上的点击位置（用于 .sas 程序自动化展开前先点一次）
    SASEG_SASAPP_SCREEN_X = 65
    SASEG_SASAPP_SCREEN_Y = 954

    def __init__(self, core: PFNCore):
        super().__init__()
        self.core = core
        self.current_fav = None
        self._current_selected_sub_key = ""
        self._subproject_item_index = {}
        self._pinned_projects = []
        self._showing_utility = False
        self._tree_cache = {}  # fav_id -> 已加载标记，切换回时可直接用缓存避免重复构建
        self._fs_view_state_by_pid = {}  # fav_id / __utility__ -> {v,h,split} 右侧资源管理器滚动与分割条
        self._restoring_fav_expand_state = False
        self._fav_tree_rebuilding = False  # clear() 时勿把空树写入展开状态
        self._page_pm = None
        self._page_explorer = None
        self._right_stack = None
        self._pm_stack = None
        self._pm_loading = None
        self._pm_loaded_once = False
        self._pm_refresh_inflight = False
        self._pm_refresh_pending = False
        self._pm_dirty = True
        try:
            self._pm_thread_pool = QThreadPool.globalInstance()
        except Exception:
            self._pm_thread_pool = None
        self._todo_product_expanded = {}
        try:
            getter = getattr(self.core.config, "get_todo_product_expanded", None)
            d = getter() if callable(getter) else {}
            if isinstance(d, dict) and d:
                self._todo_product_expanded = {str(k): bool(v) for k, v in d.items()}
        except Exception:
            pass
        self.setWindowTitle("PFN - 临床试验项目导航")
        # 主窗口图标：
        # 1) 优先从 exe 同级根目录 icon.ico 读取（满足 Windows 任务栏“固定/不固定”一致取图标）
        # 2) 兜底：从包内 assets/app_icon.ico 读取（PyInstaller: sys._MEIPASS）
        try:
            icon_path = ""
            try:
                _exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                _root_ico = os.path.join(_exe_dir, "icon.ico")
                if os.path.exists(_root_ico):
                    icon_path = _root_ico
            except Exception:
                icon_path = ""
            if not icon_path:
                _base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))  # type: ignore[attr-defined]
                icon_path = os.path.join(_base, "assets", "app_icon.ico")
            if os.environ.get("PFN_ICON_DEBUG") == "1":
                try:
                    print("图标路径:", icon_path, "存在:", os.path.exists(icon_path), flush=True)
                except Exception:
                    pass
            if os.path.exists(icon_path):
                ico = QIcon(icon_path)
                if not ico.isNull():
                    self.setWindowIcon(ico)
                    # 记录路径：用于 Windows 任务栏“强制刷新”图标
                    try:
                        self._pfn_icon_path = str(icon_path)
                    except Exception:
                        self._pfn_icon_path = ""
        except Exception:
            pass
        self.resize(1100, 720)
        self._build_ui()
        self._load_favorites()
        # _load_favorites 末尾已调用 _refresh_project_management_panel，无需再定时全量刷新，避免启动重复刷新与连带弹窗
        self.refresh_folder_done.connect(self._apply_refresh_folder_result)
        QTimer.singleShot(800, self._check_pywin32_at_startup)
        # 若以控制台模式启动，提示使用 pythonw/.pyw 根治“一闪而过”的 python 弹框
        if sys.platform == "win32":
            try:
                if ctypes.windll.kernel32.GetConsoleWindow():
                    QTimer.singleShot(
                        1200,
                        lambda: self.statusBar().showMessage(
                            "提示：若启动时出现 python 弹框闪一下，请用 PFN_silent.pyw 或命令行 pythonw PFN_silent.pyw 启动（可根治闪烁）。",
                            9000,
                        ),
                    )
            except Exception:
                pass

    def showEvent(self, event):
        super().showEvent(event)
        # Win11/部分 Qt 组合下，任务栏图标可能不从 setWindowIcon 及时同步；
        # 这里在窗口首次显示后用 Win32 WM_SETICON 强制刷新（不影响其它平台）。
        if sys.platform == "win32" and not getattr(self, "_pfn_taskbar_icon_forced", False):
            self._pfn_taskbar_icon_forced = True
            QTimer.singleShot(0, self._force_taskbar_icon_win32)
        # 窗口首次显示后再刷一次待办：QScrollArea 在首帧前常把内容高度算成 0，导致列表空白
        if not getattr(self, "_pfn_todo_after_show_done", False):
            self._pfn_todo_after_show_done = True
            # 仅一次：避免与 _load_favorites 末尾刷新叠加导致重复重建与弹窗链
            QTimer.singleShot(0, self._rebuild_todo_panel)

    def _force_taskbar_icon_win32(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())  # WId -> HWND
        except Exception:
            return
        icon_path = str(getattr(self, "_pfn_icon_path", "") or "").strip()
        try:
            user32 = ctypes.windll.user32
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            # 注意：不得在此处 DestroyIcon(hicon)。WM_SETICON 后窗口仍引用该句柄；
            # 立即销毁会导致任务栏/任务管理器“窗口”行变成默认空白图标（进程行仍显示 exe 图标）。
            hicon = 0
            if icon_path and os.path.exists(icon_path):
                hicon = int(
                    user32.LoadImageW(0, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE) or 0
                )
            if hicon:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
                return
            if getattr(sys, "frozen", False):
                shell32 = ctypes.windll.shell32
                h_large = ctypes.c_void_p()
                h_small = ctypes.c_void_p()
                exe = os.path.normpath(sys.executable)
                n = int(shell32.ExtractIconExW(exe, 0, ctypes.byref(h_large), ctypes.byref(h_small), 1) or 0)
                if n > 0:
                    if h_small.value:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small.value)
                    if h_large.value:
                        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_large.value)
        except Exception:
            return

    def closeEvent(self, event):
        try:
            saver = getattr(self.core.config, "save_todo_product_expanded_snapshot", None)
            if callable(saver) and isinstance(getattr(self, "_todo_product_expanded", None), dict):
                saver(self._todo_product_expanded)
        except Exception:
            pass
        super().closeEvent(event)

    def _apply_refresh_folder_result(self, item, err, result):
        """主线程：应用文件夹刷新结果到右侧树节点。"""
        if item is None:
            return
        while item.childCount():
            item.removeChild(item.child(0))
        if err:
            try:
                print(f"[PFN] 文件夹刷新失败: {err}", flush=True)
            except Exception:
                pass
            ph = QTreeWidgetItem(["...", ""])
            ph.setData(0, Qt.ItemDataRole.UserRole, None)
            item.addChild(ph)
            return
        for n, p, is_dir in (result or []):
            display = _strip_prefix(n)
            if is_dir:
                c = QTreeWidgetItem([display, ""])
                c.setData(0, Qt.ItemDataRole.UserRole, p)
                c.setData(1, Qt.ItemDataRole.UserRole, "dir")
                c.setToolTip(0, p)
                c.setIcon(0, icon_folder_yellow())
                ph = QTreeWidgetItem(["...", ""])
                ph.setData(0, Qt.ItemDataRole.UserRole, None)
                c.addChild(ph)
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
        self.statusBar().showMessage("刷新完成", 2000)

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
        self._main_splitter = splitter
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
        logo_lbl = QLabel()
        logo_lbl.setObjectName("pmHeaderLogo")
        _logo_sz = 24
        logo_lbl.setFixedSize(_logo_sz, _logo_sz)
        logo_lbl.setPixmap(icon_heart_outlined(_logo_sz).pixmap(_logo_sz, _logo_sz))
        logo_lbl.setStyleSheet("QLabel#pmHeaderLogo{background:transparent;border:none;padding:0;}")
        logo_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        logo_lbl.setScaledContents(False)
        logo_lbl.mousePressEvent = lambda e: self._on_left_pm_header_clicked()
        fav_layout.addWidget(logo_lbl)
        title = QLabel("项目管理栏")
        title.setObjectName("favTitle")
        title.setStyleSheet(
            "QLabel#favTitle{ font-family:'Microsoft YaHei'; font-size:14px; font-weight:500; color:#4E5969; background:transparent; } "
            "QLabel#favTitle:hover{ color:#165DFF; } "
        )
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        title.mousePressEvent = lambda e: self._on_left_pm_header_clicked()
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
        fav_card.mousePressEvent = lambda e: self._on_left_pm_header_clicked()
        left_layout.addLayout(header)

        # 搜索栏 + 扁平下拉列表
        self.fav_search_edit = QLineEdit()
        self.fav_search_edit.setPlaceholderText("搜索项目")
        self.fav_search_edit.setClearButtonEnabled(True)
        self.fav_search_edit.setFixedHeight(26)
        self.fav_search_edit.setStyleSheet(
            "QLineEdit{border:1px solid #D0D3D8; border-radius:4px; padding:2px 8px; font-size:11px;}"
            "QLineEdit:focus{border-color:#165DFF;}"
        )
        left_layout.addWidget(self.fav_search_edit)

        # 下拉层：半透明 QListWidget，扁平单行路径
        self.fav_search_list = QListWidget(left)
        self.fav_search_list.setWindowFlags(Qt.WindowType.SubWindow)
        self.fav_search_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.fav_search_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.fav_search_list.setMaximumHeight(8 * 25)
        self.fav_search_list.setSpacing(0)
        self.fav_search_list.setUniformItemSizes(True)
        self.fav_search_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.fav_search_list.setStyleSheet(
            "QListWidget{background:rgba(255,255,255,217); border:1px solid #D0D3D8; font-size:9px; outline:none;}"
            "QListWidget::item{padding:2px 6px; border:none; outline:none;}"
            "QListWidget::item:focus, QListWidget::item:hover{outline:none; border:none;}"
            "QListWidget::item:selected{background:#E8F3FF; color:#165DFF; outline:none; border:none;}"
            "QScrollBar:vertical{width:8px;}"
        )
        self.fav_search_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 用状态栏替代 tooltip，避免悬停黑框
        self.fav_search_list.setMouseTracking(True)
        if self.fav_search_list.viewport():
            self.fav_search_list.viewport().setMouseTracking(True)
        self.fav_search_list.itemEntered.connect(self._on_fav_search_item_hover)
        if self.fav_search_list.viewport():
            self.fav_search_list.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fav_search_list.hide()

        self.fav_search_edit.textChanged.connect(self._on_fav_search_changed)
        self.fav_search_edit.installEventFilter(self)
        self.fav_search_list.itemClicked.connect(self._on_fav_search_item_clicked)

        self.fav_tree = QTreeWidget()
        self.fav_tree.setHeaderHidden(True)
        self.fav_tree.setIndentation(16)
        self.fav_tree.setIconSize(QSize(16, 16))
        self.fav_tree.setAnimated(True)
        self.fav_tree.setStyleSheet(_LEFT_TREE_STYLE)
        self.fav_tree.setItemDelegate(_FavTreeDelegate(self.fav_tree))
        self.fav_tree.itemSelectionChanged.connect(self._on_fav_selected)
        self.fav_tree.itemExpanded.connect(self._on_fav_tree_expand_changed)
        self.fav_tree.itemCollapsed.connect(self._on_fav_tree_expand_changed)
        self.fav_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.fav_tree.customContextMenuRequested.connect(self._on_fav_context)
        left_layout.addWidget(self.fav_tree)
        
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.pm_tabs = QTabWidget()
        self.pm_tabs.setDocumentMode(True)
        self.pm_tabs.setStyleSheet(
            # 容器：浅灰底 + 白色内容卡片
            "QTabWidget{background:#F6F7FB;}"
            "QTabWidget::pane{border:1px solid #E5E6EB; border-radius:12px; background:#FFFFFF; top:-1px;}"
            "QTabBar{background:transparent;}"
            # Tab：胶囊风格
            "QTabBar::tab{min-width:120px; padding:8px 14px; margin:8px 6px 0 6px; "
            "border:1px solid transparent; border-top-left-radius:10px; border-top-right-radius:10px; "
            "color:#4E5969; background:transparent;}"
            "QTabBar::tab:hover{color:#1F2329; background:rgba(22,93,255,0.08);}"
            "QTabBar::tab:selected{color:#165DFF; background:#FFFFFF; border:1px solid #E5E6EB; border-bottom-color:#FFFFFF; font-weight:600;}"
            # 下拉控件统一一点质感（只影响 tabs 内部，避免影响全局）
            "QComboBox{border:1px solid #D0D3D8; border-radius:8px; padding:4px 10px; background:#FFFFFF;}"
            "QComboBox:focus{border-color:#165DFF;}"
        )
        self._build_todo_tab()
        self._build_analysis_tab()
        self._build_workbench_tab()
        self.pm_tabs.currentChanged.connect(self._on_pm_tab_changed)

        self._page_pm = QWidget()
        pm_outer = QVBoxLayout(self._page_pm)
        pm_outer.setContentsMargins(0, 0, 0, 0)
        self._pm_loading = QLabel("加载中…")
        self._pm_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pm_loading.setStyleSheet("color:#4E5969; background:rgba(255,255,255,0.96);")
        self._pm_loading.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._pm_stack = QStackedWidget()
        self._pm_stack.addWidget(self.pm_tabs)
        self._pm_stack.addWidget(self._pm_loading)
        self._pm_stack.setCurrentWidget(self.pm_tabs)
        pm_outer.addWidget(self._pm_stack)

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

        self.loading = QLabel("加载中...")
        self.loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading.setStyleSheet("color:#4E5969; background:rgba(255,255,255,0.92);")
        self.loading.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._page_explorer = QWidget()
        ex_layout = QVBoxLayout(self._page_explorer)
        ex_layout.setContentsMargins(0, 0, 0, 0)
        ex_layout.addWidget(self.tree, 1)
        ex_layout.addWidget(self.loading)
        self.loading.hide()

        self._right_stack = QStackedWidget()
        self._right_stack.addWidget(self._page_pm)
        self._right_stack.addWidget(self._page_explorer)
        self._right_stack.setCurrentWidget(self._page_pm)
        right_layout.addWidget(self._right_stack, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([280, 820])
    
    def _update_right_tree_columns(self):
        """右侧文件树：文件名列加长（约 70%），时间列固定右侧至少 100px。"""
        w = self.tree.viewport().width() if self.tree.viewport() else self.tree.width()
        if w <= 0:
            return
        # 让“文件名”更长：提高列0最小值，并降低时间列的默认占比
        # 目标：列0 ~ 72%，列1 ~ 28%（但列1 下限 110，列0 下限 260）
        c0 = max(260, int(w * 0.72))
        c1 = w - c0
        if c1 < 110:
            c1 = 110
            c0 = w - c1
        if c0 < 220:
            c0 = 220
            c1 = max(90, w - c0)
        self.tree.setColumnWidth(0, c0)
        self.tree.setColumnWidth(1, c1)

    def eventFilter(self, obj, event):
        if self._todo_product_drag_handle_event(obj, event):
            return True
        if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            sk = obj.property("_pfn_todo_sub_key")
            tid = obj.property("_pfn_todo_task_id")
            if sk is not None and str(sk).strip() != "" and tid is not None and str(tid).strip() != "":
                self._open_single_todo_task_editor(str(sk), str(tid))
                return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            sk = obj.property("_pfn_todo_sub_key")
            if sk is not None and str(sk).strip() != "":
                if not isinstance(obj, QCheckBox):
                    self._focus_tree_subproject(str(sk))
                return False
        if obj is self.tree and event.type() == QEvent.Type.Resize:
            self._update_right_tree_columns()
        # 收藏搜索下拉：输入框按键 & 失焦隐藏
        if obj is getattr(self, "fav_search_edit", None):
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    if self.fav_search_list.isVisible() and self.fav_search_list.count() > 0:
                        row = self.fav_search_list.currentRow()
                        if event.key() == Qt.Key.Key_Down:
                            row = 0 if row < 0 else min(row + 1, self.fav_search_list.count() - 1)
                        else:
                            row = self.fav_search_list.count() - 1 if row < 0 else max(row - 1, 0)
                        self.fav_search_list.setCurrentRow(row)
                        return True
                if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                    item = self.fav_search_list.currentItem()
                    if item:
                        self._on_fav_search_item_clicked(item)
                        return True
                if event.key() == Qt.Key.Key_Escape:
                    self.fav_search_edit.clear()
                    self._hide_fav_search_list()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                # 点击列表本身时不要立刻隐藏，由列表点击回调来隐藏
                QTimer.singleShot(150, self._hide_fav_search_list)
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
        base = os.path.normpath(base).replace("/", "\\")
        files = self.core.match_files(base)
        doc_order = ["setup", "PDT", "SDTM_PDS", "ADAM_PDS", "PIT", "QCT"]
        file_items = []
        common_paths = set()
        for k in doc_order:
            v = files.get(k)
            if not v:
                continue
            paths = v if isinstance(v, list) else [v]
            for fp in paths:
                if not (isinstance(fp, str) and fp.lower().endswith(".xlsx") and os.path.isfile(fp)):
                    continue
                try:
                    m = os.path.getmtime(fp)
                except Exception:
                    m = 0
                file_items.append((doc_order.index(k), k, fp, m))
                common_paths.add(os.path.normpath(fp))
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
        # 追加 documentation 目录下的其它 xlsx：优先用配置的 documentation_scan_path / scan_root；
        # 若未配置，则默认使用 base\\utility\\documentation。
        doc_cfg = self.core.config.get_documentation_paths()
        scan_path_cfg = (doc_cfg.get("documentation_scan_path") or doc_cfg.get("scan_root") or "").strip()
        root = None
        if scan_path_cfg:
            root = os.path.normpath(scan_path_cfg).replace("/", "\\")
            if not os.path.isabs(root):
                root = os.path.normpath(os.path.join(base, root))
        else:
            root = os.path.normpath(os.path.join(base, "utility", "documentation")).replace("/", "\\")
        # 让 Documents 节点可右键“打开所在文件夹”
        if root:
            docs_root.setData(0, Qt.ItemDataRole.UserRole, root)
        if root and os.path.isdir(root):
            # 只展示指定关键字的额外文件，避免 documentation 太多文件干扰
            allow_keywords_lower = [
                "test_testcd_mapping",
                "randomization_ratio",
                "demo_shell",
                "pkpd_mapping",
            ]
            for name, fp in self.core._scan_documentation_extra_files(root):
                pnorm = os.path.normpath(fp)
                if pnorm in common_paths:
                    continue
                name_lower = (name or "").lower()
                if not any(k in name_lower for k in allow_keywords_lower):
                    continue
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

    def _fs_view_state_pid(self):
        """当前右侧资源管理器视图对应的快照键（Utility 与收藏 id 区分）。"""
        if self._showing_utility:
            return "__utility__"
        if self.current_fav and self.current_fav.get("id"):
            return self.current_fav["id"]
        return None

    def _snapshot_fs_view_state_if_explorer(self):
        """切换项目/Utility 前保存右侧文件树滚动与主分割条宽度，便于切回时保持观感。"""
        if self._right_stack is None or self._page_explorer is None:
            return
        if self._right_stack.currentWidget() != self._page_explorer:
            return
        pid = self._fs_view_state_pid()
        if not pid:
            return
        sb = self.tree.verticalScrollBar()
        hb = self.tree.horizontalScrollBar()
        state = {"v": sb.value(), "h": hb.value() if hb else 0}
        if getattr(self, "_main_splitter", None) is not None:
            try:
                state["split"] = list(self._main_splitter.sizes())
            except Exception:
                pass
        self._fs_view_state_by_pid[pid] = state

    def _apply_fs_view_state(self, state):
        if not state:
            return
        sb = self.tree.verticalScrollBar()
        hb = self.tree.horizontalScrollBar()
        try:
            sb.setValue(min(int(state.get("v", 0)), max(0, sb.maximum())))
            if hb:
                hb.setValue(min(int(state.get("h", 0)), max(0, hb.maximum())))
        except Exception:
            pass
        sp = state.get("split")
        if sp and getattr(self, "_main_splitter", None) is not None:
            try:
                if len(sp) == len(self._main_splitter.sizes()):
                    self._main_splitter.setSizes(sp)
            except Exception:
                pass

    def _schedule_restore_fs_view_state(self):
        pid = self._fs_view_state_pid()
        if not pid:
            return
        state = self._fs_view_state_by_pid.get(pid)
        if not state:
            return

        def apply():
            self._apply_fs_view_state(state)

        QTimer.singleShot(0, apply)
        QTimer.singleShot(120, apply)

    def _on_left_pm_header_clicked(self, _event=None):
        """点击左侧「项目管理栏」标题区域：取消树选中，右侧回到待办/分析页。"""
        try:
            self._snapshot_fs_view_state_if_explorer()
            self._showing_utility = False
            # Utility 模式下左树本就无选中，clearSelection 不会触发 selectionChanged；
            # 因此这里需要显式切回右侧「项目管理」页，避免无法跳转。
            try:
                self.fav_tree.clearSelection()
            except Exception:
                pass
            self.current_fav = None
            self._show_right_pm_view()
            # 点击标题：只在首次进入或数据被标记为 dirty 时才触发加载/刷新
            self._request_pm_refresh(allow_repeat=False, reason="pm_header_click")
        except Exception as e:
            try:
                print(f"[PFN] 点击项目管理栏失败: {e}", flush=True)
            except Exception:
                pass

    def _to_explorer_fav(self, folder_path: str):
        """将任意文件夹路径包装为「资源管理器式」浏览用的 current_fav。"""
        p = os.path.normpath(str(folder_path or "")).replace("/", "\\")
        key = p.replace("\\", "/").lower()
        return {
            "id": f"explorer:{key}",
            "full_path": p,
            "display_name": os.path.basename(p.rstrip("\\")) or p,
            "dir_type": "explorer",
        }

    def _build_explorer_folder_tree(self, root_path: str):
        """单根目录 + 懒加载子项（与 Utility 一致，可展开/折叠）。"""
        root_path = os.path.normpath(str(root_path or "")).replace("/", "\\")
        if not os.path.isdir(root_path):
            label = os.path.basename(root_path.rstrip("\\")) or root_path or "(路径不可用)"
            root = QTreeWidgetItem([label, ""])
            root.setData(0, Qt.ItemDataRole.UserRole, None)
            root.setForeground(0, Qt.GlobalColor.red)
            self.tree.addTopLevelItem(root)
            return
        label = os.path.basename(root_path.rstrip("\\")) or root_path
        root = QTreeWidgetItem([label, ""])
        root.setData(0, Qt.ItemDataRole.UserRole, root_path)
        root.setData(1, Qt.ItemDataRole.UserRole, "ok")
        root.setIcon(0, icon_folder_yellow())
        root.setToolTip(0, root_path)
        ph = QTreeWidgetItem(["...", ""])
        ph.setData(0, Qt.ItemDataRole.UserRole, None)
        root.addChild(ph)
        self.tree.addTopLevelItem(root)
        self.tree.expandItem(root)

    def _show_right_pm_view(self):
        try:
            if self._right_stack is not None and self._page_pm is not None:
                self._right_stack.setCurrentWidget(self._page_pm)
        except Exception as e:
            try:
                print(f"[PFN] 切换项目管理页失败: {e}", flush=True)
            except Exception:
                pass
        # 进入项目管理页：避免重复全量刷新；交由 _request_pm_refresh 决定是否需要加载
        self._request_pm_refresh(allow_repeat=False, reason="show_pm_view")

    def _show_right_explorer_view(self):
        if self._right_stack is not None:
            self._right_stack.setCurrentWidget(self._page_explorer)

    def _z_path_for_source_root(self, label: str):
        label = (label or "").strip().lower()
        mapping = {
            "projects": r"Z:\projects",
            "unblinded": r"Z:\unblinded",
            "users": r"Z:\users",
        }
        p = mapping.get(label)
        if p and os.path.isdir(p):
            return os.path.normpath(p).replace("/", "\\")
        return ""

    def _resolve_left_tree_directory(self, item: QTreeWidgetItem):
        """解析左侧树当前节点应对应的文件夹路径（用于右侧资源管理器视图）。"""
        if item is None:
            return ""
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        fav = item.data(0, Qt.ItemDataRole.UserRole)
        items = item.data(0, Qt.ItemDataRole.UserRole + 2) or []

        if node_type in ("pinned_empty", "pinned_source"):
            return ""

        if node_type == "source":
            if item.parent() is None:
                return self._z_path_for_source_root(item.text(0))
            return ""

        if node_type == "pinned_leaf":
            pin = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
            real = self._resolve_fav_from_name_path(pin.get("name", ""), pin.get("path", ""))
            if not isinstance(real, dict):
                return ""
            fp = os.path.normpath(str(real.get("full_path", "") or "")).replace("/", "\\")
            return fp if os.path.isdir(fp) else ""

        if node_type == "product" and isinstance(fav, dict) and fav.get("is_product_node"):
            fp = os.path.normpath(str(fav.get("full_path", "") or "")).replace("/", "\\")
            return fp if fp and os.path.isdir(fp) else ""

        if node_type == "trial" and items and isinstance(items[0], dict):
            meta = self._extract_project_meta_from_path(
                items[0].get("full_path", ""), items[0].get("dir_type", "projects")
            )
            fp = os.path.normpath(str(meta.get("path", "") or "")).replace("/", "\\")
            return fp if fp and os.path.isdir(fp) else ""

        if node_type == "leaf" and isinstance(fav, dict):
            fp = os.path.normpath(str(fav.get("full_path", "") or "")).replace("/", "\\")
            return fp if fp and os.path.isdir(fp) else ""

        if items and isinstance(items[0], dict):
            fp = os.path.normpath(str(items[0].get("full_path", "") or "")).replace("/", "\\")
            return fp if fp and os.path.isdir(fp) else ""

        return ""

    def _favorite_dict_for_selection(self, item: QTreeWidgetItem):
        """解析左侧树节点对应的收藏项 dict（若有），用于 users 等需走定制目录结构的场景。"""
        if item is None:
            return None
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        fav = item.data(0, Qt.ItemDataRole.UserRole)
        items = item.data(0, Qt.ItemDataRole.UserRole + 2) or []

        if node_type == "leaf" and isinstance(fav, dict) and fav.get("id"):
            return fav
        if node_type in ("trial", "parent") and items and isinstance(items[0], dict) and items[0].get("id"):
            return items[0]
        if node_type == "pinned_leaf":
            pin = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
            real = self._resolve_fav_from_name_path(pin.get("name", ""), pin.get("path", ""))
            return real if isinstance(real, dict) else None
        return None

    def _build_todo_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        # 待办页更紧凑：一屏显示更多内容
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)

        todo_title = QLabel("我的待办")
        todo_title.setStyleSheet("color:#1F2329;")
        todo_title.setFont(_pfn_qfont_pt(12, True))
        lay.addWidget(todo_title)

        self.todo_filter_combo = QComboBox()
        self.todo_filter_combo.addItems(["显示全部", "仅显示未完成", "仅显示已完成"])
        self.todo_filter_combo.setCurrentIndex(0)
        self.todo_filter_combo.setFixedHeight(28)
        self.todo_filter_combo.setMinimumWidth(240)
        self.todo_filter_combo.setFont(_pfn_qfont_pt(8))
        self.todo_filter_combo.currentIndexChanged.connect(self._on_todo_filter_changed)
        lay.addWidget(self.todo_filter_combo)

        self.todo_scroll = QScrollArea()
        self.todo_scroll.setWidgetResizable(True)
        self.todo_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.todo_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.todo_scroll.setMinimumHeight(200)
        self.todo_scroll.setStyleSheet(
            "QScrollArea{background:transparent; border:none;}"
            "QScrollBar:vertical{width:10px; background:transparent; margin:4px 2px 4px 2px;}"
            "QScrollBar::handle:vertical{background:rgba(0,0,0,0.18); border-radius:5px; min-height:26px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(0,0,0,0.26);}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0px;}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}"
        )

        self.todo_cont = QWidget()
        self.todo_cont.setStyleSheet("background:transparent;")
        self.todo_cont.setFont(_pfn_qfont_pt(8))
        self.todo_cont.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.todo_layout = QVBoxLayout(self.todo_cont)
        self.todo_layout.setContentsMargins(2, 4, 4, 10)
        self.todo_layout.setSpacing(10)

        # 产品拖拽排序：插入位置指示线（避免 QListWidget 内部拖拽产生异常空白）
        self._todo_insert_line = QFrame(self.todo_cont)
        self._todo_insert_line.setFixedHeight(3)
        self._todo_insert_line.setStyleSheet("background:#165DFF;border:none;border-radius:2px;")
        self._todo_insert_line.hide()
        self._todo_insert_line.raise_()

        self.todo_scroll.setWidget(self.todo_cont)
        lay.addWidget(self.todo_scroll, 1)

        # 待办产品拖拽状态（自定义重排，不用 QDrag）
        self._todo_dnd_press_frame = None
        self._todo_dnd_press_global = None
        self._todo_dnd_origin_btn = None
        self._todo_dnd_dragging = False
        self._todo_dnd_insert_at = 0

        self._todo_group_frames = {}
        self.pm_tabs.addTab(tab, "我的待办")

    def _on_todo_filter_changed(self, _i: int):
        try:
            name = str(self.todo_filter_combo.currentText() or "")
            # 统计展示数量在 _rebuild_todo_panel 内统一打印
            print(f"[Filter Changed] 当前筛选: {name}", flush=True)
        except Exception:
            pass
        self._rebuild_todo_panel()

    def _on_todo_product_order_changed(self, order_list):
        """拖拽排序后持久化到 config.json（product_order）。"""
        try:
            setter = getattr(self.core.config, "set_product_order", None)
            if callable(setter):
                setter(list(order_list or []))
        except Exception:
            pass

    @staticmethod
    def _todo_drag_product_frame(w):
        cur = w
        while cur is not None:
            if getattr(cur, "_pfn_product_name", None):
                return cur
            cur = cur.parentWidget()
        return None

    @staticmethod
    def _todo_drag_skip_widget(w):
        if isinstance(w, QCheckBox):
            return True
        if isinstance(w, QPushButton):
            t = str(w.text() or "")
            if "添加任务" in t:
                return True
        return False

    def _todo_product_frames_ordered(self):
        lay = getattr(self, "todo_layout", None)
        if lay is None:
            return []
        out = []
        for i in range(lay.count()):
            it = lay.itemAt(i)
            w = it.widget() if it is not None else None
            if w is not None and getattr(w, "_pfn_product_name", None):
                out.append(w)
        return out

    def _todo_register_product_drag_targets(self, prod_frame: QFrame):
        try:
            for ww in [prod_frame] + prod_frame.findChildren(QWidget):
                ww.installEventFilter(self)
        except Exception:
            pass

    def _todo_reset_product_drag_ui(self):
        """重建列表或异常中断时，强制收起插入线与拖拽状态，避免蓝线残留。"""
        try:
            if getattr(self, "_todo_insert_line", None) is not None:
                self._todo_insert_line.hide()
        except Exception:
            pass
        fr = getattr(self, "_todo_dnd_press_frame", None)
        if getattr(self, "_todo_dnd_dragging", False) and fr is not None:
            try:
                fr.releaseMouse()
            except Exception:
                pass
        try:
            QApplication.restoreOverrideCursor()
        except Exception:
            pass
        self._todo_dnd_dragging = False
        self._todo_dnd_press_frame = None
        self._todo_dnd_press_global = None
        self._todo_dnd_origin_btn = None

    def _todo_update_product_insert_line(self, global_pt: QPoint, show_line: bool = True):
        line = getattr(self, "_todo_insert_line", None)
        cont = getattr(self, "todo_cont", None)
        drag = getattr(self, "_todo_dnd_press_frame", None)
        if cont is None or drag is None:
            return
        frames = self._todo_product_frames_ordered()
        others = [f for f in frames if f is not drag]
        try:
            yc = cont.mapFromGlobal(global_pt).y()
        except Exception:
            yc = 0
        insert_at = len(others)
        for i, w in enumerate(others):
            try:
                wy = w.mapTo(cont, QPoint(0, 0)).y()
                mid = wy + max(8, w.height() // 2)
            except Exception:
                continue
            if yc < mid:
                insert_at = i
                break
        self._todo_dnd_insert_at = insert_at
        if not show_line or line is None:
            return
        if not others:
            try:
                m = self.todo_layout.contentsMargins()
                y_top = m.top()
            except Exception:
                y_top = 4
        elif insert_at < len(others):
            try:
                y_top = others[insert_at].mapTo(cont, QPoint(0, 0)).y()
            except Exception:
                y_top = 0
        else:
            w = others[-1]
            try:
                y_top = w.mapTo(cont, QPoint(0, w.height())).y()
            except Exception:
                y_top = 0
        try:
            m = self.todo_layout.contentsMargins()
            x = m.left()
            ww = max(24, cont.width() - m.left() - m.right())
            line.setGeometry(x, max(0, y_top - 1), ww, 3)
            line.show()
            line.raise_()
        except Exception:
            pass

    def _todo_begin_product_drag(self, frame: QFrame):
        if self._todo_dnd_dragging:
            return
        self._todo_dnd_dragging = True
        # 不再用 QGraphicsOpacityEffect：会整卡发灰且松手后偶发残留阴影/半透明状态
        try:
            frame.grabMouse()
        except Exception:
            pass
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.SizeAllCursor)
        except Exception:
            pass
        try:
            self._todo_update_product_insert_line(QCursor.pos())
        except Exception:
            pass

    def _todo_finish_product_drag(self, global_pt: QPoint):
        frame = getattr(self, "_todo_dnd_press_frame", None)
        try:
            if frame is not None:
                frame.releaseMouse()
        except Exception:
            pass
        try:
            QApplication.restoreOverrideCursor()
        except Exception:
            pass
        try:
            if getattr(self, "_todo_insert_line", None) is not None:
                self._todo_insert_line.hide()
        except Exception:
            pass
        try:
            ob = getattr(self, "_todo_dnd_origin_btn", None)
            if ob is not None and hasattr(ob, "setDown"):
                ob.setDown(False)
        except Exception:
            pass
        if frame is not None:
            # 仅用松手位置刷新插入下标，禁止再 show 指示线（否则会“先 hide 再 show”残留蓝条）
            try:
                self._todo_update_product_insert_line(global_pt, show_line=False)
            except Exception:
                pass
            others = [f for f in self._todo_product_frames_ordered() if f is not frame]
            ins = int(getattr(self, "_todo_dnd_insert_at", 0) or 0)
            ins = max(0, min(ins, len(others)))
            new_order = others[:ins] + [frame] + others[ins:]
            self._todo_reflow_product_frames(new_order)
            names = [str(getattr(f, "_pfn_product_name", "") or "") for f in new_order]
            names = [n for n in names if n]
            self._on_todo_product_order_changed(names)
        self._todo_dnd_dragging = False
        self._todo_dnd_press_frame = None
        self._todo_dnd_press_global = None
        self._todo_dnd_origin_btn = None

    def _todo_reflow_product_frames(self, frames_ordered):
        lay = getattr(self, "todo_layout", None)
        if lay is None:
            return
        for f in frames_ordered:
            try:
                lay.removeWidget(f)
            except Exception:
                pass
        stretch_i = lay.count()
        for i in range(lay.count()):
            if lay.itemAt(i).spacerItem():
                stretch_i = i
                break
        for j, f in enumerate(frames_ordered):
            try:
                lay.insertWidget(stretch_i + j, f)
            except Exception:
                pass
        try:
            self.todo_cont.adjustSize()
            sc = getattr(self, "todo_scroll", None)
            if sc is not None:
                sc.updateGeometry()
        except Exception:
            pass

    def _todo_product_drag_handle_event(self, obj, event) -> bool:
        tc = getattr(self, "todo_cont", None)
        if tc is None:
            return False
        et = event.type()
        if not self._todo_dnd_dragging and self._todo_dnd_press_frame is None:
            if not isinstance(obj, QWidget):
                return False
            if self._todo_drag_product_frame(obj) is None:
                return False
        if et == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            if not isinstance(obj, QWidget):
                return False
            if self._todo_drag_skip_widget(obj):
                return False
            fr = self._todo_drag_product_frame(obj)
            if fr is None:
                return False
            self._todo_dnd_press_frame = fr
            try:
                self._todo_dnd_press_global = event.globalPosition().toPoint()
            except Exception:
                self._todo_dnd_press_global = None
            self._todo_dnd_origin_btn = obj if isinstance(obj, QPushButton) else None
            return False
        if et == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
            if self._todo_dnd_dragging:
                try:
                    self._todo_update_product_insert_line(event.globalPosition().toPoint())
                except Exception:
                    pass
                return False
            if self._todo_dnd_press_frame is None or self._todo_dnd_press_global is None:
                return False
            fr = self._todo_drag_product_frame(obj)
            if fr is not self._todo_dnd_press_frame:
                return False
            try:
                dist = (event.globalPosition().toPoint() - self._todo_dnd_press_global).manhattanLength()
            except Exception:
                dist = 0
            # 比系统默认略敏感，拖拽更跟手
            start_dist = max(5, int(QApplication.startDragDistance() * 0.55))
            if dist <= start_dist:
                return False
            self._todo_begin_product_drag(fr)
            return False
        if et == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._todo_dnd_dragging:
                try:
                    self._todo_finish_product_drag(event.globalPosition().toPoint())
                except Exception:
                    self._todo_dnd_dragging = False
                return True
            self._todo_dnd_press_frame = None
            self._todo_dnd_press_global = None
            self._todo_dnd_origin_btn = None
            return False
        return False

    def _build_analysis_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(16, 12, 16, 16)
        lay.setSpacing(10)

        # 顶部工具栏：月份筛选（驱动全页面联动）+ 年份（折线图年份）
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(10)

        m_lbl = QLabel("月份：")
        m_lbl.setFont(_pfn_qfont_pt(9))
        m_lbl.setStyleSheet("color:#4E5969;")
        top.addWidget(m_lbl)
        self.month_filter_combo = QComboBox()
        self.month_filter_combo.setFixedHeight(30)
        self.month_filter_combo.setMinimumWidth(175)
        self.month_filter_combo.setFont(_pfn_qfont_pt(9))
        self.month_filter_combo.currentTextChanged.connect(lambda _t: self._refresh_project_management_panel())
        top.addWidget(self.month_filter_combo)

        y_lbl = QLabel("年份：")
        y_lbl.setFont(_pfn_qfont_pt(9))
        y_lbl.setStyleSheet("color:#4E5969;")
        top.addWidget(y_lbl)
        self.year_filter_combo = QComboBox()
        self.year_filter_combo.setFixedHeight(30)
        self.year_filter_combo.setMinimumWidth(125)
        self.year_filter_combo.currentTextChanged.connect(lambda _t: self._refresh_project_management_panel())
        top.addWidget(self.year_filter_combo)
        top.addStretch()
        lay.addLayout(top)

        # 第一行：饼图 + 柱状图（并排，无滚动）
        row1 = QHBoxLayout()
        row1.setSpacing(12)

        def _mk_chart_card(title: str):
            card = QFrame()
            card.setObjectName("pmChartCard")
            card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            card.setStyleSheet(
                "QFrame#pmChartCard{background:#FFFFFF; border:1px solid #E5E6EB; border-radius:18px;}"
            )
            sh = QGraphicsDropShadowEffect()
            sh.setBlurRadius(12)
            sh.setXOffset(0)
            sh.setYOffset(3)
            sh.setColor(QColor(0, 0, 0, 16))
            card.setGraphicsEffect(sh)
            v = QVBoxLayout(card)
            v.setContentsMargins(12, 10, 12, 10)
            v.setSpacing(8)
            t = QLabel(title)
            t.setFont(_pfn_qfont_pt(10, True))
            t.setStyleSheet("color:#1F2329;")
            v.addWidget(t)
            return card, v

        pie_card, pie_v = _mk_chart_card("项目状态分布")
        self.pie_status = SimplePieChartWidget()
        self.pie_status.clicked.connect(self._show_status_subprojects_dialog)
        self.pie_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pie_status.setMinimumHeight(150)
        pie_v.addWidget(self.pie_status, 1)
        row1.addWidget(pie_card, 1)

        bar_card, bar_v = _mk_chart_card("项目 TA 分布")
        self.bar_ta = SimpleBarChartWidget()
        self.bar_ta.clicked.connect(self._on_ta_bar_clicked)
        self.bar_ta.setMinimumHeight(150)
        bar_v.addWidget(self.bar_ta, 1)
        row1.addWidget(bar_card, 1)

        lay.addLayout(row1, 1)

        # 第二行：折线图（紧凑高度）
        line_card, line_v = _mk_chart_card("已完成任务趋势（按月）")
        self.line_trend = SimpleLineChartWidget()
        self.line_trend.setMinimumHeight(160)
        line_v.addWidget(self.line_trend, 1)
        lay.addWidget(line_card, 1)
        self.pm_tabs.addTab(tab, "项目数据分析")

    # ----------------------------
    # 工作台（固定工具快捷启动）
    # ----------------------------
    @staticmethod
    def _workbench_tool_specs():
        """固定工具顺序与匹配规则（点击时实时扫描，不做路径缓存）。"""
        return [
            {
                "name": "PDTManager",
                "dir": r"Z:\projects\Z_PYTHON\PDT",
                "contains": "PDTManager",
            },
            {
                "name": "QCT_Tools",
                "dir": r"Z:\projects\Z_PYTHON\QCT_Tools",
                "contains": "QCT",
            },
            {
                "name": "RTFtoPDF",
                "dir": r"Z:\projects\Z_PYTHON\rtf_to_pdf",
                "contains": "RTFtoPDF",
            },
        ]

    @staticmethod
    def _find_latest_exe_in_dir(folder: str, name_contains: str) -> str:
        """在指定目录下查找最新 exe（文件名包含关键字，按 mtime 最大）。找不到返回空串。"""
        folder = os.path.normpath(str(folder or "")).replace("/", "\\")
        if not folder or not os.path.isdir(folder):
            return ""
        key = str(name_contains or "").strip().lower()
        best_path = ""
        best_mtime = -1
        try:
            # os.scandir 在网络盘上通常比 listdir + stat 更快
            with os.scandir(folder) as it:
                for entry in it:
                    try:
                        if not entry.is_file():
                            continue
                        fn = entry.name or ""
                        fn_lower = fn.lower()
                        if not fn_lower.endswith(".exe"):
                            continue
                        if key and key not in fn_lower:
                            continue
                        try:
                            mt = entry.stat().st_mtime
                        except Exception:
                            mt = -1
                        if mt > best_mtime:
                            best_mtime = mt
                            best_path = entry.path
                    except Exception:
                        continue
        except Exception:
            return ""
        return best_path

    def _workbench_launch_tool_async(self, tool_spec: dict):
        """点击卡片：后台线程实时扫描最新版 exe 并启动，避免 UI 被网络盘/图标解析阻塞。"""
        name = str((tool_spec or {}).get("name", "") or "").strip()
        folder = str((tool_spec or {}).get("dir", "") or "").strip()
        contains = str((tool_spec or {}).get("contains", "") or "").strip()

        try:
            self.statusBar().showMessage(f"正在启动：{name or '工具'} …", 2500)
        except Exception:
            pass

        def ui_info(msg: str):
            def _show():
                try:
                    QMessageBox.information(self, "提示", msg)
                except Exception:
                    pass
            QTimer.singleShot(0, _show)

        def worker():
            try:
                exe_path = self._find_latest_exe_in_dir(folder, contains)
                if not exe_path:
                    ui_info("未找到工具exe文件")
                    return
                # 优先用 ShellExecute 启动（通常更快返回）
                try:
                    os.startfile(exe_path)  # type: ignore[attr-defined]
                    return
                except Exception:
                    pass
                try:
                    subprocess.Popen([exe_path], shell=False)
                except Exception:
                    ui_info("未找到工具exe文件" if not os.path.isfile(exe_path) else f"无法启动：{name or '工具'}")
            except Exception:
                ui_info("未找到工具exe文件")

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            # 线程启动失败时退化为同步，但仍兜底
            try:
                worker()
            except Exception:
                ui_info("未找到工具exe文件")

    def _build_workbench_tab(self):
        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(10)

        title = QLabel("工作台")
        title.setStyleSheet("color:#1F2329;")
        title.setFont(_pfn_qfont_pt(12, True))
        lay.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent; border:none;}"
            "QScrollBar:vertical{width:10px; background:transparent; margin:4px 2px 4px 2px;}"
            "QScrollBar::handle:vertical{background:rgba(0,0,0,0.18); border-radius:5px; min-height:26px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(0,0,0,0.26);}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical{height:0px;}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical{background:transparent;}"
        )

        cont = QWidget()
        cont.setStyleSheet("background:transparent;")
        grid = QGridLayout(cont)
        grid.setContentsMargins(2, 2, 2, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        def _mk_card(tool_spec: dict):
            card = QFrame()
            card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setFixedSize(180, 110)

            card._pfn_wb_hovered = False  # type: ignore[attr-defined]
            card._pfn_wb_spec = dict(tool_spec or {})  # type: ignore[attr-defined]

            sh = QGraphicsDropShadowEffect()
            sh.setBlurRadius(12)
            sh.setXOffset(0)
            sh.setYOffset(3)
            sh.setColor(QColor(0, 0, 0, 16))
            card.setGraphicsEffect(sh)

            def apply_style(hover: bool):
                if hover:
                    card.setStyleSheet(
                        "QFrame{background:#FFFFFF; border:1px solid rgba(22,93,255,0.55); border-radius:18px;}"
                    )
                    try:
                        eff = card.graphicsEffect()
                        if isinstance(eff, QGraphicsDropShadowEffect):
                            eff.setBlurRadius(16)
                            eff.setYOffset(6)
                            eff.setColor(QColor(22, 93, 255, 28))
                    except Exception:
                        pass
                else:
                    card.setStyleSheet(
                        "QFrame{background:#FFFFFF; border:1px solid #E5E6EB; border-radius:18px;}"
                    )
                    try:
                        eff = card.graphicsEffect()
                        if isinstance(eff, QGraphicsDropShadowEffect):
                            eff.setBlurRadius(12)
                            eff.setYOffset(3)
                            eff.setColor(QColor(0, 0, 0, 16))
                    except Exception:
                        pass

            apply_style(False)

            v = QVBoxLayout(card)
            v.setContentsMargins(14, 12, 14, 12)
            v.setSpacing(8)
            v.addStretch()

            icon_lbl = QLabel()
            icon_lbl.setFixedSize(44, 44)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card._pfn_wb_icon_label = icon_lbl  # type: ignore[attr-defined]
            v.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignHCenter)

            name = str((tool_spec or {}).get("name", "") or "")
            name_lbl = QLabel(name)
            name_lbl.setFont(_pfn_qfont_pt(10, True))
            name_lbl.setStyleSheet("color:#1F2329;")
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            v.addWidget(name_lbl)

            v.addStretch()

            # 展示：随机使用系统内置图标（避免从网络盘 exe 解析图标导致卡顿）
            try:
                std_icons = [
                    QStyle.StandardPixmap.SP_ComputerIcon,
                    QStyle.StandardPixmap.SP_DriveHDIcon,
                    QStyle.StandardPixmap.SP_DriveNetIcon,
                    QStyle.StandardPixmap.SP_DirOpenIcon,
                    QStyle.StandardPixmap.SP_FileIcon,
                    QStyle.StandardPixmap.SP_DesktopIcon,
                    QStyle.StandardPixmap.SP_DialogOpenButton,
                    QStyle.StandardPixmap.SP_CommandLink,
                ]
                name = str((tool_spec or {}).get("name", "") or "")
                idx = abs(hash(name + str(time.time_ns()))) % len(std_icons) if std_icons else 0
                icon_lbl.setPixmap(self.style().standardIcon(std_icons[idx]).pixmap(38, 38))
            except Exception:
                icon_lbl.setPixmap(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon).pixmap(36, 36))

            # hover / click
            def enterEvent(_e):
                card._pfn_wb_hovered = True  # type: ignore[attr-defined]
                apply_style(True)

            def leaveEvent(_e):
                card._pfn_wb_hovered = False  # type: ignore[attr-defined]
                apply_style(False)

            def mousePressEvent(e):
                if e.button() == Qt.MouseButton.LeftButton:
                    self._workbench_launch_tool_async(card._pfn_wb_spec)  # type: ignore[attr-defined]

            card.enterEvent = enterEvent  # type: ignore[assignment]
            card.leaveEvent = leaveEvent  # type: ignore[assignment]
            card.mousePressEvent = mousePressEvent  # type: ignore[assignment]
            return card

        specs = self._workbench_tool_specs()
        cols = 3
        for i, spec in enumerate(specs):
            r = i // cols
            c = i % cols
            grid.addWidget(_mk_card(spec), r, c)
        # 占位拉伸，保证左对齐的网格观感
        grid.setRowStretch(grid.rowCount(), 1)
        grid.setColumnStretch(cols, 1)

        scroll.setWidget(cont)
        lay.addWidget(scroll, 1)
        self.pm_tabs.addTab(tab, "工作台")

    def _normalize_path_key(self, path):
        return os.path.normpath(str(path or "")).replace("/", "\\").lower()

    def _extract_project_meta_from_path(self, path, dir_type):
        product, trial, _subdir = _product_trial_from_path(path, dir_type)
        path = os.path.normpath(str(path or "")).replace("/", "\\")
        if trial:
            parts = [x for x in path.split("\\") if x]
            idx = next((i for i, seg in enumerate(parts) if seg == trial), -1)
            if idx >= 0:
                trial_path = "\\".join(parts[: idx + 1])
                if not trial_path.upper().startswith("Z:"):
                    trial_path = "Z:\\" + trial_path
            else:
                trial_path = os.path.dirname(path)
        else:
            trial = os.path.basename(path.rstrip("\\"))
            trial_path = path
        return {
            "root_name": product or "",
            "subproject_name": trial or "",
            "sub_key": self._normalize_path_key(trial_path),
            "path": trial_path,
        }

    def _rebuild_subproject_index(self):
        self._subproject_item_index = {}
        for i in range(self.fav_tree.topLevelItemCount()):
            root = self.fav_tree.topLevelItem(i)
            stack = [root]
            while stack:
                cur = stack.pop()
                node_type = cur.data(0, Qt.ItemDataRole.UserRole + 1)
                if node_type == "trial":
                    items = cur.data(0, Qt.ItemDataRole.UserRole + 2) or []
                    if items and isinstance(items[0], dict):
                        meta = self._extract_project_meta_from_path(items[0].get("full_path", ""), items[0].get("dir_type", "projects"))
                        if meta["sub_key"]:
                            self._subproject_item_index[meta["sub_key"]] = cur
                for ci in range(cur.childCount()):
                    stack.append(cur.child(ci))

    def _project_management_data(self):
        getter = getattr(self.core.config, "get_project_management", None)
        if callable(getter):
            return getter()
        return {"root_ta": {}, "subprojects": {}}

    def _coerce_raw_tasks_list(self, raw):
        """config 中 tasks 应为 list；若被写成 JSON 对象或异常结构，尽量转成列表。"""
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            keys = list(raw.keys())
            if keys and all(str(k).isdigit() for k in keys):
                return [raw[k] for k in sorted(keys, key=lambda x: int(x))]
            return list(raw.values()) if raw else []
        return []

    def _on_pm_tab_changed(self, idx: int):
        """切换到「我的待办」时强制重建列表，避免非当前标签页时布局未就绪导致空白。"""
        if idx == 0:
            try:
                self._rebuild_todo_panel()
            except Exception as e:
                try:
                    print(f"[PFN] 待办标签页重建失败: {e}", flush=True)
                except Exception:
                    pass

    def _normalize_task_status(self, task) -> str:
        """统一任务完成状态，兼容历史或异常值。"""
        if not isinstance(task, dict):
            return "未完成"
        s = task.get("status", "未完成")
        if s is True or s == 1:
            return "已完成"
        s = str(s or "").strip()
        if s in ("已完成", "完成", "done", "Done", "DONE"):
            return "已完成"
        return "未完成"

    def _coerce_task_entry(self, t, sub_key: str):
        """将 config 中的任务项规范为 dict（兼容纯字符串等旧数据）。"""
        if isinstance(t, str):
            line = t.strip()
            if not line:
                return None
            return {
                "id": str(uuid.uuid4()),
                "content": line,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": "未完成",
                "completed_at": "",
            }
        if not isinstance(t, dict):
            return None
        out = dict(t)
        if not str(out.get("id", "") or "").strip():
            out["id"] = str(uuid.uuid4())
        if not str(out.get("content", "") or "").strip():
            return None
        tp = str(out.get("priority", "") or "").strip()
        if tp not in ("高", "中", "低"):
            out.pop("priority", None)
        if str(out.get("priority", "") or "").strip() not in ("高", "中", "低"):
            out["priority"] = "中"
        st = self._normalize_task_status(out)
        out["status"] = "已完成" if st == "已完成" else "未完成"
        return out

    def _todo_effective_priority(self, task: dict, info: dict) -> str:
        p = str((task or {}).get("priority", "") or "").strip()
        if p in ("高", "中", "低"):
            return p
        return str((info or {}).get("priority", "中") or "中")

    def _persist_normalized_tasks_if_needed(self):
        """若 tasks 含纯字符串或缺 id 的 dict，写回规范化列表，避免界面不显示或每次刷新生成新 id。"""
        pm = self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        if not isinstance(subs, dict):
            return
        setter = getattr(self.core.config, "upsert_subproject", None)
        if not callable(setter):
            return
        for sub_key, info in subs.items():
            if not isinstance(info, dict):
                continue
            raw_tasks = self._coerce_raw_tasks_list(info.get("tasks", []) or [])
            need = bool(info.get("tasks")) and not isinstance(info.get("tasks"), list)
            for t in raw_tasks:
                if isinstance(t, str):
                    need = True
                    break
                if isinstance(t, dict) and not str(t.get("id", "") or "").strip():
                    need = True
                    break
            if not need:
                continue
            out_list = []
            for t in raw_tasks:
                c = self._coerce_task_entry(t, sub_key)
                if c is not None:
                    out_list.append(c)
            try:
                setter(sub_key, tasks=out_list)
            except Exception:
                pass

    def _todo_filter_passes_task(self, task: dict, filter_index: int) -> bool:
        """filter_index: 0 全部 / 1 仅未完成 / 2 仅显示已完成"""
        st = self._normalize_task_status(task)
        if filter_index == 0:
            return True
        if filter_index == 1:
            return st != "已完成"
        if filter_index == 2:
            return st == "已完成"
        return True

    def _clear_todo_layout(self):
        # 注意：PyQt 的 QLayout 在空布局时可能 bool(layout)==False，不能用 truthy 判断是否存在
        if getattr(self, "todo_layout", None) is None:
            return
        while self.todo_layout.count():
            item = self.todo_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _toggle_todo_product(self, product_name: str, content_widget: QWidget):
        """点击产品标题：展开/收起该产品下的子项目与任务（带高度动画）。"""
        name = str(product_name or "").strip()
        if not name or content_widget is None:
            return
        if not hasattr(self, "_todo_product_expanded") or not isinstance(getattr(self, "_todo_product_expanded", None), dict):
            self._todo_product_expanded = {}
        expanded = bool(self._todo_product_expanded.get(name, True))
        target_expand = not expanded
        self._todo_product_expanded[name] = target_expand
        try:
            saver = getattr(self.core.config, "save_todo_product_expanded_snapshot", None)
            if callable(saver):
                saver(self._todo_product_expanded)
        except Exception:
            pass

        try:
            content_widget.setVisible(True)
            content_widget.layout().activate() if content_widget.layout() else None
        except Exception:
            pass

        start_h = content_widget.maximumHeight()
        if start_h <= 0:
            try:
                start_h = max(0, int(content_widget.sizeHint().height()))
            except Exception:
                start_h = 0
        end_h = 0
        if target_expand:
            try:
                end_h = max(0, int(content_widget.sizeHint().height()))
            except Exception:
                end_h = 0
            if end_h <= 0:
                end_h = 1

        anim = QPropertyAnimation(content_widget, b"maximumHeight", self)
        anim.setDuration(260)
        anim.setStartValue(start_h)
        anim.setEndValue(end_h)

        def _on_finished():
            try:
                if not target_expand:
                    content_widget.setVisible(False)
                    content_widget.setMaximumHeight(0)
                else:
                    content_widget.setVisible(True)
                    content_widget.setMaximumHeight(16777215)
            except Exception:
                pass
            # 展开/收起后刷新卡片高度（垂直布局下由 sizeHint 自然收缩）
            try:
                prod_frame = content_widget.parentWidget()
                if prod_frame is not None and prod_frame.layout():
                    prod_frame.layout().activate()
                    prod_frame.adjustSize()
                if getattr(self, "todo_cont", None) is not None:
                    self.todo_cont.adjustSize()
                sc = getattr(self, "todo_scroll", None)
                if sc is not None:
                    sc.updateGeometry()
            except Exception:
                pass

        anim.finished.connect(_on_finished)
        # 防止被 GC
        content_widget._pfn_anim = anim
        anim.start()

    def _rebuild_todo_panel(self):
        """根据筛选重建「我的待办」列表（产品-项目-任务三级：产品卡片 -> 子项目分组 -> 任务行）。"""
        if getattr(self, "todo_layout", None) is None:
            return
        self._todo_reset_product_drag_ui()
        # 保存滚动位置（按比例恢复）：避免新增/编辑任务后跳回顶部
        sc = getattr(self, "todo_scroll", None)
        sb = None
        try:
            sb = sc.verticalScrollBar() if sc is not None else None
        except Exception:
            sb = None
        try:
            sb_max = int(sb.maximum()) if sb is not None else 0
            sb_val = int(sb.value()) if sb is not None else 0
            _todo_scroll_ratio = (sb_val / sb_max) if sb_max > 0 else 0.0
        except Exception:
            _todo_scroll_ratio = 0.0
        try:
            cfg_path = str(getattr(self.core.config, "config_path", "") or "")
            print(f"[Todo Rebuild] start, config={cfg_path}", flush=True)
        except Exception:
            pass
        # 不在此处 reload_config：避免进入项目管理页时反复读盘、重复同步与连带异常；内存即权威，除非进程外改配置需重启
        try:
            self._persist_normalized_tasks_if_needed()
        except Exception:
            pass
        self._clear_todo_layout()
        self._todo_group_frames = {}
        if not hasattr(self, "_todo_product_expanded") or not isinstance(getattr(self, "_todo_product_expanded", None), dict):
            self._todo_product_expanded = {}

        pm = self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        if not isinstance(subs, dict):
            subs = {}
        try:
            print(f"[Todo Rebuild] subprojects={len(subs)}", flush=True)
        except Exception:
            pass

        filter_index = 0
        if getattr(self, "todo_filter_combo", None) is not None:
            filter_index = int(self.todo_filter_combo.currentIndex())
            if filter_index < 0 or filter_index > 2:
                filter_index = 0

        priority_rank = {"高": 0, "中": 1, "低": 2}

        # 每个子项目都展示（便于「+ 添加任务」）；任务行按筛选显示
        products = {}
        for sub_key, info in subs.items():
            if not isinstance(info, dict):
                continue
            sub_name = str(info.get("subproject_name", "") or "")
            sk_low = str(sub_key or "").lower()
            product_name = _pfn_derive_product_name(info, sub_name, sub_key)
            prod = products.setdefault(product_name, {})
            bucket = {
                "sub_name": sub_name,
                "priority": str(info.get("priority", "中") or "中"),
                "info": info,
                "rows": [],
            }
            raw_tasks = self._coerce_raw_tasks_list(info.get("tasks", []) or [])
            for t in raw_tasks:
                t = self._coerce_task_entry(t, sub_key)
                if t is None:
                    continue
                if not self._todo_filter_passes_task(t, filter_index):
                    continue
                eff_pri = self._todo_effective_priority(t, info)
                rk = priority_rank.get(eff_pri, 1)
                bucket["rows"].append((rk, sub_name, sk_low, info, t))
            prod[sk_low] = bucket

        try:
            n_filtered = sum(len((b or {}).get("rows") or []) for pmap in products.values() for b in pmap.values())
            print(f"[Task Loaded] 产品分组 {len(products)}，当前筛选下 {n_filtered} 条任务", flush=True)
        except Exception:
            pass

        def _pri_rank(p: str) -> int:
            return {"高": 0, "中": 1, "低": 2}.get(str(p or "中"), 1)

        for prod_name, proj_map in products.items():
            for sk, bucket in proj_map.items():
                def _row_sort_key(x):
                    rk, _sn, _sk, _info, t = x
                    done = 1 if self._normalize_task_status(t) == "已完成" else 0
                    return (done, rk, str((t or {}).get("created_at", "")))

                bucket["rows"].sort(key=_row_sort_key)

        # 显式区分 unchecked/checked：圆圈更小、更“淡”，减少视觉存在感（同时避免系统主题覆盖）
        chk_style = (
            "QCheckBox { spacing: 5px; background: transparent; color: #1F2329; }"
            "QCheckBox::indicator { width: 10px; height: 10px; border-radius: 5px; border: 1px solid rgba(31,35,41,130); background: rgba(255,255,255,200); }"
            "QCheckBox::indicator:unchecked { border-radius: 5px; border: 1px solid rgba(31,35,41,130); background: rgba(255,255,255,200); image: none; }"
            "QCheckBox::indicator:checked { border-radius: 5px; border: 1px solid rgba(31,35,41,160); background: rgba(31,35,41,170); image: none; }"
            "QCheckBox::indicator:hover { border-color: rgba(31,35,41,180); }"
        )

        any_visible = bool(products) and any(
            bool((b or {}).get("rows")) for pmap in products.values() for b in pmap.values()
        )

        if not products:
            hint = "暂无符合条件的任务"
            if filter_index == 0:
                n_sub = len(subs)
                n_task = sum(
                    len(self._coerce_raw_tasks_list((inf or {}).get("tasks") or []))
                    for inf in subs.values()
                    if isinstance(inf, dict)
                )
                cfg_path = str(getattr(self.core.config, "config_path", "") or "")
                if n_sub == 0:
                    hint = (
                        "未读取到子项目数据。请确认正在使用的 config.json 中含 project_management.subprojects。\n"
                        f"当前配置文件：{cfg_path}"
                    )
                elif n_task == 0:
                    hint = (
                        f"配置中已有 {n_sub} 个子项目，但尚无任务。"
                        "请在左侧收藏树展开子项目后右键「编辑项目任务」添加；添加后即在此显示。"
                    )
            empty = QLabel(hint)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            empty.setMinimumHeight(120)
            empty.setStyleSheet("color:#86909C; padding:24px;")
            empty.setFont(_pfn_qfont_pt(10))
            self.todo_layout.addWidget(empty)
        elif not any_visible:
            hint = (
                "暂无符合当前筛选的任务，可将上方下拉框切换为「显示全部」。"
                if filter_index != 0
                else "暂无待办任务。请先在左侧树为子项目添加任务（右键「编辑项目任务」）。"
            )
            empty = QLabel(hint)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            empty.setMinimumHeight(120)
            empty.setStyleSheet("color:#86909C; padding:24px;")
            empty.setFont(_pfn_qfont_pt(10))
            self.todo_layout.addWidget(empty)

        # 三层展示：产品卡片 -> 子项目分组 -> 任务（无任务或未通过筛选的子项目不显示）
        # 产品顺序：优先使用 config.json.product_order；其余按字母追加
        try:
            saved_order = list(getattr(self.core.config, "get_product_order", lambda: [])() or [])
        except Exception:
            saved_order = []
        saved_l = [str(x or "").strip() for x in saved_order if str(x or "").strip()]
        prod_keys = list(products.keys())
        prod_map = {str(p).lower(): p for p in prod_keys}
        ordered = []
        seen = set()
        for x in saved_l:
            k = x.lower()
            if k in prod_map and k not in seen:
                ordered.append(prod_map[k])
                seen.add(k)
        for p in sorted(prod_keys, key=lambda x: str(x or "")):
            k = str(p).lower()
            if k not in seen:
                ordered.append(p)
                seen.add(k)

        for prod_name in ordered:
            proj_items = list(products.get(prod_name, {}).items())
            proj_items.sort(key=lambda kv: (_pri_rank((kv[1] or {}).get("priority", "中")), str((kv[1] or {}).get("sub_name", ""))))
            visible_proj = [(sk, b) for sk, b in proj_items if (b or {}).get("rows")]
            if not visible_proj:
                continue

            prod_frame = QFrame()
            prod_frame.setObjectName("todoProductFrame")
            # 在拖拽列表里必须“贴内容”而不是撑满可视区域
            prod_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            prod_frame.setStyleSheet(
                "#todoProductFrame { background:#FFFFFF; border:1px solid #E5E6EB; border-radius:12px; }"
            )
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(14)
            shadow.setXOffset(0)
            shadow.setYOffset(4)
            shadow.setColor(QColor(0, 0, 0, 18))
            prod_frame.setGraphicsEffect(shadow)
            pv = QVBoxLayout(prod_frame)
            pv.setContentsMargins(12, 10, 10, 10)
            pv.setSpacing(8)

            # 产品标题：整行 hover 高亮 + 点击展开/收起（无箭头）
            prod_title_btn = QPushButton(str(prod_name or "（未命名产品）"))
            prod_title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            prod_title_btn.setFlat(True)
            prod_title_btn.setFont(_pfn_qfont_pt(10, True))
            prod_title_btn.setStyleSheet(
                "QPushButton{color:#1F2329;text-align:left;border:none;padding:6px 6px;border-radius:8px;background:transparent;}"
                "QPushButton:hover{background:rgba(22,93,255,0.06);}"
                "QPushButton:pressed{background:rgba(22,93,255,0.10);}"
            )
            pv.addWidget(prod_title_btn)

            # 产品内容区（子项目 + 任务）：用于折叠/展开动画
            prod_content = QWidget()
            prod_content.setStyleSheet("background:transparent;")
            prod_content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            pcv = QVBoxLayout(prod_content)
            pcv.setContentsMargins(0, 0, 0, 0)
            pcv.setSpacing(8)

            for sk_l, bucket in visible_proj:
                sub_name = str((bucket or {}).get("sub_name", "") or "")
                rows = (bucket or {}).get("rows", []) or []
                info_b = (bucket or {}).get("info") or {}

                sub_frame = QFrame()
                sub_frame.setObjectName("todoSubprojectFrame")
                sub_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
                sub_frame.setStyleSheet(
                    "#todoSubprojectFrame { background:#F7F8FA; border:1px solid #EDEFF2; border-radius:10px; }"
                )
                sv = QVBoxLayout(sub_frame)
                sv.setContentsMargins(8, 8, 8, 8)
                sv.setSpacing(6)

                head_row = QWidget()
                head_row.setStyleSheet("background:transparent;")
                head_h = QHBoxLayout(head_row)
                head_h.setContentsMargins(0, 0, 0, 0)
                head_h.setSpacing(6)
                st_lbl = QLabel(sub_name or "（未命名项目）")
                st_lbl.setStyleSheet("color:#1F2329;")
                st_lbl.setFont(_pfn_qfont_pt(9, True))
                st_lbl.setToolTip("右键 → 编辑时间节点")
                head_h.addWidget(st_lbl, 0)
                for m in _pfn_normalize_milestones(info_b.get("milestones")):
                    try:
                        chip = QLabel(f"[{m['name']}：{m['date']}]")
                        chip.setStyleSheet(
                            "color:#86909C; background:#E8EAED; padding:1px 6px; border-radius:5px;"
                        )
                        chip.setFont(_pfn_qfont_pt(7))
                        chip.setToolTip("")
                        chip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                        head_h.addWidget(chip, 0)
                    except Exception:
                        continue
                head_h.addStretch(1)
                head_row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                head_row.customContextMenuRequested.connect(
                    partial(self._on_todo_subproject_header_context, sk_l, sub_name)
                )
                sv.addWidget(head_row)

                add_btn = QPushButton("+ 添加任务")
                add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                add_btn.setStyleSheet(
                    "QPushButton{border:none;color:#165DFF;background:transparent;text-align:left;padding:0 0 2px 2px;font-size:10px;}"
                    "QPushButton:hover{color:#0E42D2;text-decoration:underline;}"
                )
                add_btn.clicked.connect(partial(self._on_todo_add_task_clicked, sk_l))
                sv.addWidget(add_btn)

                for _rk, _sn, sub_key, info, task in rows:
                    task_id = str((task or {}).get("id", "") or "")
                    content = str((task or {}).get("content", "") or "").strip() or "（无内容）"
                    created = str((task or {}).get("created_at", "") or "")
                    pri = self._todo_effective_priority(task, info)
                    is_done = self._normalize_task_status(task) == "已完成"

                    row_w = QWidget()
                    row_w.setStyleSheet("background: transparent;")
                    row_h = QHBoxLayout(row_w)
                    # 任务列表相对子项目标题再缩进 20px
                    row_h.setContentsMargins(16, 2, 2, 2)
                    row_h.setSpacing(6)

                    chk = QCheckBox()
                    chk.setStyleSheet(chk_style)
                    chk.setFont(_pfn_qfont_pt(9))
                    chk.setCursor(Qt.CursorShape.PointingHandCursor)
                    chk.blockSignals(True)
                    chk.setChecked(is_done)
                    chk.blockSignals(False)
                    chk.toggled.connect(partial(self._on_todo_checkbox_toggled, sub_key, task_id))
                    chk.setProperty("_pfn_todo_sub_key", sub_key)
                    chk.setProperty("_pfn_todo_task_id", task_id)
                    chk.installEventFilter(self)

                    text_col = QWidget()
                    text_col.setStyleSheet("background: transparent;")
                    text_col.setProperty("_pfn_todo_sub_key", sub_key)
                    text_col.setProperty("_pfn_todo_task_id", task_id)
                    text_col.installEventFilter(self)
                    tv = QVBoxLayout(text_col)
                    tv.setContentsMargins(0, 0, 0, 0)
                    tv.setSpacing(1)

                    body = QLabel(content)
                    body.setWordWrap(True)
                    body.setFont(_pfn_qfont_pt(9))
                    body.setStyleSheet("color:#86909C;" if is_done else "color:#1F2329;")
                    body.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

                    meta = QLabel(f"创建：{created}  ·  优先级：{pri}")
                    meta.setStyleSheet("color:#C9CDD4;" if is_done else "color:#86909C;")
                    meta.setFont(_pfn_qfont_pt(8))
                    meta.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

                    tv.addWidget(body)
                    tv.addWidget(meta)

                    row_h.addWidget(chk, 0, Qt.AlignmentFlag.AlignTop)
                    row_h.addWidget(text_col, 1)

                    row_w.setProperty("_pfn_todo_sub_key", sub_key)
                    row_w.setProperty("_pfn_todo_task_id", task_id)
                    row_w.installEventFilter(self)
                    row_w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                    row_w.customContextMenuRequested.connect(
                        partial(self._on_todo_row_context_menu, row_w, sub_key, task_id)
                    )

                    sv.addWidget(row_w)

                # 子项目标题相对产品标题缩进 20px（外层缩进，不靠 padding）
                sub_wrap = QWidget()
                sub_wrap.setStyleSheet("background:transparent;")
                sub_h = QHBoxLayout(sub_wrap)
                sub_h.setContentsMargins(0, 0, 0, 0)
                sub_h.setSpacing(0)
                sub_h.addSpacing(20)
                sub_h.addWidget(sub_frame, 1)
                pcv.addWidget(sub_wrap)

                # 用于左侧点击联动定位到对应“子项目分组”
                if sk_l and sk_l not in self._todo_group_frames:
                    self._todo_group_frames[sk_l] = sub_frame

            pv.addWidget(prod_content)

            # 默认全部展开；点击标题整行折叠/展开（带动画）
            pname = str(prod_name or "").strip() or "（未命名产品）"
            is_expanded = bool(self._todo_product_expanded.get(pname, True))
            if not is_expanded:
                prod_content.setVisible(False)
                prod_content.setMaximumHeight(0)
            else:
                prod_content.setVisible(True)
                prod_content.setMaximumHeight(16777215)
            prod_title_btn.clicked.connect(partial(self._toggle_todo_product, pname, prod_content))
            prod_frame._pfn_product_name = str(pname)
            self.todo_layout.addWidget(prod_frame)
            self._todo_register_product_drag_targets(prod_frame)

        # 关键：吸收滚动区剩余高度，避免最后一个卡片被拉伸“变形”
        self.todo_layout.addStretch(1)
        try:
            self.todo_layout.activate()
            sh = self.todo_layout.sizeHint()
            mh = max(200, sh.height() + 16)
            self.todo_cont.setMinimumHeight(mh)
            self.todo_cont.adjustSize()
            sc = getattr(self, "todo_scroll", None)
            if sc is not None:
                sc.updateGeometry()
                sc.viewport().update()
                # 重建后恢复滚动位置（需要等布局完成）
                try:
                    sb2 = sc.verticalScrollBar()
                except Exception:
                    sb2 = None
                if sb2 is not None:
                    def _restore():
                        try:
                            m = int(sb2.maximum())
                            v = int(round(max(0.0, min(1.0, _todo_scroll_ratio)) * m))
                            sb2.setValue(v)
                        except Exception:
                            pass
                    QTimer.singleShot(0, _restore)
        except Exception:
            pass
        try:
            if getattr(self, "_todo_insert_line", None) is not None:
                self._todo_insert_line.hide()
        except Exception:
            pass

    def _on_todo_checkbox_toggled(self, sub_key: str, task_id: str, checked: bool):
        pm = self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        info = subs.get(sub_key, {}) if isinstance(subs, dict) else {}
        if not isinstance(info, dict):
            return
        tasks = self._coerce_raw_tasks_list(info.get("tasks", []) or [])
        changed = False
        task_content = ""
        for t in tasks:
            if not isinstance(t, dict) or str(t.get("id", "")) != task_id:
                continue
            task_content = str(t.get("content", "") or "").strip()
            if checked:
                t["status"] = "已完成"
                t["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            else:
                t["status"] = "未完成"
                t["completed_at"] = ""
            changed = True
            break
        if not changed:
            return
        setter = getattr(self.core.config, "upsert_subproject", None)
        if callable(setter):
            setter(sub_key, tasks=tasks)
        try:
            print(
                f"[Task Saved] 项目: {str(info.get('subproject_name','') or sub_key)}, 任务: {task_content or task_id}",
                flush=True,
            )
        except Exception:
            pass
        self._refresh_project_management_panel()

    def _on_todo_row_context_menu(self, source_widget, sub_key: str, task_id: str, pos):
        menu = QMenu(self)
        act_edit = menu.addAction("编辑任务")
        act_del = menu.addAction("删除任务")
        action = menu.exec(source_widget.mapToGlobal(pos))
        if action is None:
            return
        if action == act_edit:
            self._update_single_task(sub_key, task_id, "编辑任务")
        elif action == act_del:
            self._update_single_task(sub_key, task_id, "删除任务")

    def _set_pm_loading_visible(self, visible: bool):
        st = getattr(self, "_pm_stack", None)
        if st is None:
            return
        try:
            if visible:
                st.setCurrentWidget(self._pm_loading)
            else:
                st.setCurrentWidget(self.pm_tabs)
        except Exception:
            pass

    def _request_pm_refresh(self, allow_repeat: bool = True, reason: str = ""):
        """
        项目管理页刷新入口（去重 + 异步加载）：
        - allow_repeat=False：用于“点击项目管理栏”/“切回项目管理页”，仅在首次或 dirty 时刷新
        - allow_repeat=True：用于编辑任务/新增/删除等明确需要刷新时
        """
        try:
            if not allow_repeat:
                if self._pm_loaded_once and not getattr(self, "_pm_dirty", False):
                    return
            else:
                self._pm_dirty = True
        except Exception:
            pass

        if getattr(self, "_pm_refresh_inflight", False):
            self._pm_refresh_pending = True
            return

        self._pm_refresh_inflight = True
        self._pm_refresh_pending = False
        self._set_pm_loading_visible(True)

        try:
            pm_snapshot = deepcopy(self._project_management_data())
        except Exception as e:
            pm_snapshot = {"root_ta": {}, "subprojects": {}}
            try:
                print(f"[PFN] 项目管理数据快照失败（已降级为空）：{reason} {e}", flush=True)
            except Exception:
                pass

        worker = _PMRefreshWorker(pm_snapshot)

        def _on_failed(err: str):
            try:
                print(f"[PFN] 项目管理后台加载失败: {reason} {err}", flush=True)
            except Exception:
                pass
            self._pm_refresh_inflight = False
            self._set_pm_loading_visible(False)

        def _on_finished(pm_clean):
            self._pm_refresh_inflight = False
            self._pm_loaded_once = True
            self._pm_dirty = False
            try:
                self._do_refresh_project_management_panel(pm=pm_clean)
            except Exception as e:
                try:
                    print(f"[PFN] 项目管理面板刷新失败: {e}", flush=True)
                except Exception:
                    pass
            self._set_pm_loading_visible(False)
            if getattr(self, "_pm_refresh_pending", False):
                self._pm_refresh_pending = False
                self._request_pm_refresh(allow_repeat=True, reason="pm_refresh_pending")

        worker.signals.failed.connect(_on_failed)
        worker.signals.finished.connect(_on_finished)

        pool = getattr(self, "_pm_thread_pool", None)
        if pool is None:
            # 兜底：不使用线程池也不要阻塞在点击事件里，先让“加载中”渲染出来
            QTimer.singleShot(0, lambda: _on_finished(pm_snapshot))
            return
        try:
            pool.start(worker)
        except Exception as e:
            try:
                print(f"[PFN] 启动项目管理后台任务失败（降级主线程刷新）：{e}", flush=True)
            except Exception:
                pass
            QTimer.singleShot(0, lambda: _on_finished(pm_snapshot))

    def _refresh_project_management_panel(self):
        # 保持原接口：明确请求刷新（编辑任务等会调用这里）
        self._request_pm_refresh(allow_repeat=True, reason="explicit_refresh")

    def _do_refresh_project_management_panel(self, pm=None):
        pm = pm if isinstance(pm, dict) else self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        if not isinstance(subs, dict):
            subs = {}

        try:
            self._rebuild_todo_panel()
        except Exception as e:
            try:
                print(f"[PFN] 待办列表重建失败: {e}", flush=True)
            except Exception:
                pass

        def _month_of(s: str) -> str:
            s = str(s or "").strip()
            return s[:7] if len(s) >= 7 else ""

        def _task_in_period(t: dict, year: str, month: str) -> bool:
            """year=全部/month=全部：不做时间过滤；year=全部+month=YYYY-MM：按月过滤；year=YYYY+month=全部：按年过滤。"""
            if not isinstance(t, dict):
                return False
            cm = _month_of(t.get("created_at", ""))
            dm = _month_of(t.get("completed_at", ""))
            if month and month != "全部":
                return cm == month or dm == month
            y = str(year or "").strip()
            if not y or y == "全部":
                return True
            return (cm.startswith(y + "-") if cm else False) or (dm.startswith(y + "-") if dm else False)

        # 先根据“已完成任务”的 completed_at 推导可选年份
        months_done_counter = {}
        years = set()
        for info in subs.values():
            if not isinstance(info, dict):
                continue
            for t in info.get("tasks", []) or []:
                if not isinstance(t, dict):
                    continue
                if t.get("status") != "已完成":
                    continue
                m = _month_of(t.get("completed_at", ""))
                if m:
                    months_done_counter[m] = months_done_counter.get(m, 0) + 1
                    years.add(m[:4])

        years = sorted(years) or [datetime.now().strftime("%Y")]
        if datetime.now().strftime("%Y") not in years:
            years.append(datetime.now().strftime("%Y"))
            years = sorted(set(years))
        years = ["全部"] + years
        selected_year = years[0]
        cur_month = "全部"
        try:
            with QSignalBlocker(self.year_filter_combo), QSignalBlocker(self.month_filter_combo):
                cur_year = self.year_filter_combo.currentText().strip()
                if cur_year not in years:
                    cur_year = years[0]
                self.year_filter_combo.clear()
                self.year_filter_combo.addItems(years)
                self.year_filter_combo.setCurrentText(cur_year)
                selected_year = self.year_filter_combo.currentText().strip() if self.year_filter_combo.count() else cur_year

                month_items = ["全部"] if selected_year == "全部" else (["全部"] + [f"{selected_year}-{m:02d}" for m in range(1, 13)])
                cm = self.month_filter_combo.currentText().strip()
                if cm not in month_items:
                    cm = "全部"
                self.month_filter_combo.clear()
                self.month_filter_combo.addItems(month_items)
                self.month_filter_combo.setCurrentText(cm)
                cur_month = self.month_filter_combo.currentText().strip() if self.month_filter_combo.count() else "全部"
        except Exception:
            pass

        def _task_is_done_dict(t: dict) -> bool:
            if not isinstance(t, dict):
                return False
            s = t.get("status", "未完成")
            if s is True or s == 1:
                return True
            s = str(s or "").strip()
            return s in ("已完成", "完成", "done", "Done", "DONE")

        # 饼图：按“任务数量”统计（未完成任务数 / 已完成任务数），严格按筛选周期过滤
        n_ongoing = 0  # 未完成任务数
        n_complete = 0  # 已完成任务数
        subs_in_period = set()
        self._analysis_period_cache = {}  # sub_key -> {"info":info,"todo":[task], "done":[task]}
        for sub_key, info in subs.items():
            if not isinstance(info, dict):
                continue
            tasks = [t for t in (info.get("tasks", []) or []) if isinstance(t, dict)]
            if not tasks:
                continue
            subs_in_period.add(str(sub_key or "").lower())
            p_tasks = [t for t in tasks if _task_in_period(t, selected_year, cur_month)]
            if not p_tasks:
                # 无周期内任务活动：不计入当前周期
                subs_in_period.discard(str(sub_key or "").lower())
                continue
            done = [t for t in p_tasks if _task_is_done_dict(t)]
            todo = [t for t in p_tasks if not _task_is_done_dict(t)]
            self._analysis_period_cache[str(sub_key or "").lower()] = {"info": info, "todo": todo, "done": done}
            n_complete += len(done)
            n_ongoing += len(todo)
        self.pie_status.set_data([("未完成", n_ongoing), ("已完成", n_complete)])

        # TA 柱状图：不随时间筛选变化，始终按已设置 TA 的产品统计
        ta_labels = ["心血管", "肾病", "感染", "神经", "呼吸", "自免"]
        ta_counter = {k: 0 for k in ta_labels}
        root_ta = pm.get("root_ta", {}) if isinstance(pm, dict) else {}
        if isinstance(root_ta, dict):
            for root_name, ta in root_ta.items():
                if ta in ta_counter:
                    ta_counter[ta] += 1
        self.bar_ta.set_data([(k, ta_counter[k]) for k in ta_labels])

        # 折线图：只随“年份”变化；月份筛选不影响折线图展示（与你的预期一致）
        trend_rows = []
        if selected_year == "全部":
            # 全部年份：显示近 12 个“有完成任务”的月份趋势
            all_done_months = set()
            for info in subs.values():
                if not isinstance(info, dict):
                    continue
                for t in info.get("tasks", []) or []:
                    if not isinstance(t, dict):
                        continue
                    if not _task_is_done_dict(t):
                        continue
                    dm = _month_of(t.get("completed_at", ""))
                    if dm:
                        all_done_months.add(dm)
            months_sorted = sorted(all_done_months)
            months_last = months_sorted[-12:] if len(months_sorted) > 12 else months_sorted
            if not months_last:
                months_last = [datetime.now().strftime("%Y-%m")]
            for key in months_last:
                v = 0
                for info in subs.values():
                    if not isinstance(info, dict):
                        continue
                    for t in info.get("tasks", []) or []:
                        if not isinstance(t, dict):
                            continue
                        if not _task_is_done_dict(t):
                            continue
                        if _month_of(t.get("completed_at", "")) != key:
                            continue
                        v += 1
                trend_rows.append((key, v))
        else:
            # 指定年份：展示该年 12 个月完成趋势
            for m in range(1, 13):
                key = f"{selected_year}-{m:02d}"
                v = 0
                for info in subs.values():
                    if not isinstance(info, dict):
                        continue
                    for t in info.get("tasks", []) or []:
                        if not isinstance(t, dict):
                            continue
                        if not _task_is_done_dict(t):
                            continue
                        if _month_of(t.get("completed_at", "")) != key:
                            continue
                        v += 1
                trend_rows.append((key, v))
        self.line_trend.set_data(trend_rows)
        # 避免筛选器变更时跳回“我的待办”
        try:
            if getattr(self, "pm_tabs", None) is not None and int(self.pm_tabs.currentIndex()) == 0:
                self._highlight_todo_for_subproject(self._current_selected_sub_key)
        except Exception:
            pass

    def _show_status_subprojects_dialog(self, status_label):
        pm = self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        if not isinstance(subs, dict):
            subs = {}
        # 读取当前筛选（年月联动）
        try:
            cur_month = self.month_filter_combo.currentText().strip()
        except Exception:
            cur_month = "全部"
        try:
            cur_year = self.year_filter_combo.currentText().strip()
        except Exception:
            cur_year = datetime.now().strftime("%Y")

        def _month_of(s: str) -> str:
            s = str(s or "").strip()
            return s[:7] if len(s) >= 7 else ""

        def _task_in_period(t: dict) -> bool:
            if not isinstance(t, dict):
                return False
            cm = _month_of(t.get("created_at", ""))
            dm = _month_of(t.get("completed_at", ""))
            if cur_month != "全部":
                return cm == cur_month or dm == cur_month
            y = str(cur_year or "").strip()
            if not y:
                return True
            return (cm.startswith(y + "-") if cm else False) or (dm.startswith(y + "-") if dm else False)

        def _task_done(t: dict) -> bool:
            if not isinstance(t, dict):
                return False
            s = t.get("status", "未完成")
            if s is True or s == 1:
                return True
            s = str(s or "").strip()
            return s in ("已完成", "完成", "done", "Done", "DONE")

        want_done = str(status_label or "").strip() == "已完成"

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{status_label}（按产品→项目→任务）")
        dlg.resize(520, 520)
        v = QVBoxLayout(dlg)
        hint = QLabel(f"筛选：{cur_year} / {cur_month}    双击产品或项目可定位左侧树。")
        hint.setStyleSheet("color:#4E5969;")
        v.addWidget(hint)

        tree = QTreeWidget()
        tree.setHeaderLabels(["产品 / 项目 / 任务", "时间"])
        tree.setStyleSheet("QTreeWidget{border:1px solid #E5E6EB; border-radius:10px; padding:6px;}")
        tree.setUniformRowHeights(True)
        try:
            tree.setColumnWidth(0, 360)
            tree.setColumnWidth(1, 140)
        except Exception:
            pass
        v.addWidget(tree, 1)

        from collections import defaultdict

        n_prod = 0
        n_proj = 0
        n_task = 0
        grouped = defaultdict(list)
        cache = getattr(self, "_analysis_period_cache", {}) or {}
        for sub_key_l, payload in cache.items():
            info = (payload or {}).get("info") or {}
            tasks = (payload or {}).get("done" if want_done else "todo") or []
            if not tasks:
                continue
            sub_name = str(info.get("subproject_name", "") or "")
            prod = _pfn_derive_product_name(info, sub_name, str(sub_key_l or ""))
            grouped[prod].append((str(sub_key_l or ""), info, tasks))

        f_bold = QFont()
        f_bold.setBold(True)
        for prod_name in sorted(grouped.keys()):
            rows = grouped[prod_name]
            rows.sort(
                key=lambda x: str((x[1] or {}).get("subproject_name", "") or "").lower(),
            )
            pitem = QTreeWidgetItem([prod_name, ""])
            pitem.setData(0, Qt.ItemDataRole.UserRole + 1, "product")
            pitem.setData(0, Qt.ItemDataRole.UserRole + 2, prod_name)
            pitem.setFont(0, f_bold)
            tree.addTopLevelItem(pitem)
            n_prod += 1
            for sub_key_l, info, tasks in rows:
                proj = str(info.get("subproject_name", "") or "（未命名项目）")
                sitem = QTreeWidgetItem([proj, ""])
                sitem.setData(0, Qt.ItemDataRole.UserRole, sub_key_l)
                sitem.setData(0, Qt.ItemDataRole.UserRole + 1, "subproject")
                pitem.addChild(sitem)
                n_proj += 1
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    content = str(t.get("content", "") or "").strip() or "（无内容）"
                    when = str(t.get("completed_at" if want_done else "created_at", "") or "")
                    c = QTreeWidgetItem([content, when])
                    c.setData(0, Qt.ItemDataRole.UserRole, sub_key_l)
                    c.setData(0, Qt.ItemDataRole.UserRole + 1, "task")
                    sitem.addChild(c)
                    n_task += 1
        tree.expandAll()

        if n_proj == 0:
            try:
                print("[PFN] 状态详情：暂无符合条件的产品/项目/任务", flush=True)
            except Exception:
                pass
            return

        hint.setText(
            f"筛选：{cur_year} / {cur_month}    共 {n_prod} 个产品，{n_proj} 个项目，{n_task} 条任务。双击产品或项目可定位左侧树。"
        )

        def _jump(it: QTreeWidgetItem, _col: int):
            kind = it.data(0, Qt.ItemDataRole.UserRole + 1)
            if kind == "product":
                pn = it.data(0, Qt.ItemDataRole.UserRole + 2)
                if pn:
                    self._focus_tree_product(str(pn))
                return
            sk = it.data(0, Qt.ItemDataRole.UserRole)
            if sk:
                self._focus_tree_subproject(str(sk))

        tree.itemDoubleClicked.connect(_jump)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)
        dlg.exec()

    def _on_ta_bar_clicked(self, ta_label: str):
        pm = self._project_management_data()
        root_ta = pm.get("root_ta", {}) if isinstance(pm, dict) else {}
        if not isinstance(root_ta, dict):
            root_ta = {}

        products = []
        for root_name, ta in root_ta.items():
            if str(ta or "") != str(ta_label or ""):
                continue
            rn = str(root_name or "").strip()
            if rn and rn not in products:
                products.append(rn)

        products = sorted(products)
        if not products:
            try:
                print(f"[PFN] TA 产品列表：{ta_label} 暂无产品", flush=True)
            except Exception:
                pass
            return

        # 简单列表弹窗：点选后定位左侧树产品节点
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{ta_label}（产品列表）")
        dlg.resize(360, 420)
        v = QVBoxLayout(dlg)
        hint = QLabel(f"共 {len(products)} 个产品\n点击产品可定位左侧树。")
        hint.setStyleSheet("color:#4E5969;")
        v.addWidget(hint)
        lw = QListWidget()
        lw.addItems(products)
        lw.setStyleSheet("QListWidget{border:1px solid #E5E6EB; border-radius:10px; padding:6px;}")
        v.addWidget(lw, 1)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)

        def _go():
            it = lw.currentItem()
            if not it:
                return
            self._focus_tree_product(str(it.text() or "").strip())

        lw.itemDoubleClicked.connect(lambda _it: (_go(), dlg.accept()))
        lw.itemClicked.connect(lambda _it: _go())
        dlg.exec()

    def _focus_tree_product(self, product_name: str):
        """定位左侧树的产品节点（文本匹配 product_name）。"""
        target = (product_name or "").strip()
        if not target:
            return
        best = None
        # 优先在 projects/unblinded/users 下的 product 节点中找
        for i in range(self.fav_tree.topLevelItemCount()):
            top = self.fav_tree.topLevelItem(i)
            stack = [top]
            while stack:
                cur = stack.pop()
                try:
                    node_type = cur.data(0, Qt.ItemDataRole.UserRole + 1)
                except Exception:
                    node_type = None
                txt = (cur.text(0) or "").strip()
                if node_type == "product" and txt.lower() == target.lower():
                    best = cur
                    stack = []
                    break
                for ci in range(cur.childCount() - 1, -1, -1):
                    stack.append(cur.child(ci))
            if best is not None:
                break
        if best is None:
            return
        cur = best
        while cur:
            cur.setExpanded(True)
            cur = cur.parent()
        self.fav_tree.setCurrentItem(best)

    def _open_single_todo_task_editor(self, sub_key: str, task_id: str):
        pm = self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        info = subs.get(sub_key, {}) if isinstance(subs, dict) else {}
        if not isinstance(info, dict):
            return
        tasks = self._coerce_raw_tasks_list(info.get("tasks", []) or [])
        target = None
        for t in tasks:
            if isinstance(t, dict) and str(t.get("id", "")) == task_id:
                target = dict(t)
                break
        if target is None:
            return
        sub_name = str(info.get("subproject_name", "") or sub_key)
        dlg = SingleTodoTaskEditDialog(
            self,
            f"编辑任务 - {sub_name}",
            target,
            default_priority=str(info.get("priority", "中") or "中"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        content = dlg.get_content()
        if not content:
            try:
                print("[PFN] 编辑任务：内容为空，已取消保存", flush=True)
            except Exception:
                pass
            return
        pri = dlg.get_priority()
        done = dlg.is_done()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        changed = False
        for t in tasks:
            if not isinstance(t, dict) or str(t.get("id", "")) != task_id:
                continue
            t["content"] = content
            t["priority"] = pri
            if done:
                t["status"] = "已完成"
                if not str(t.get("completed_at", "") or "").strip():
                    t["completed_at"] = now
            else:
                t["status"] = "未完成"
                t["completed_at"] = ""
            changed = True
            break
        if not changed:
            return
        setter = getattr(self.core.config, "upsert_subproject", None)
        if callable(setter):
            setter(sub_key, tasks=tasks)
        self._refresh_project_management_panel()

    def _apply_subproject_tasks_editor_result(self, sub_key: str, sub_info: dict, dlg: SubprojectTasksEditorDialog, log_name: str = ""):
        """将 SubprojectTasksEditorDialog 的结果写回配置（任务行 + 里程碑）。"""
        setter = getattr(self.core.config, "upsert_subproject", None)
        if not callable(setter) or not isinstance(sub_info, dict):
            return False
        lines = dlg.get_task_lines()
        milestones = dlg.get_milestones_dict()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old_tasks = sub_info.get("tasks", []) or []
        new_tasks = []
        sub_pri = str(sub_info.get("priority", "中") or "中")
        for idx, line in enumerate(lines):
            if idx < len(old_tasks) and isinstance(old_tasks[idx], dict):
                old = old_tasks[idx]
                op = str(old.get("priority", "") or "").strip()
                if op not in ("高", "中", "低"):
                    op = sub_pri
                new_tasks.append({
                    "id": old.get("id", str(uuid.uuid4())),
                    "content": line,
                    "created_at": old.get("created_at", now),
                    "status": old.get("status", "未完成"),
                    "completed_at": old.get("completed_at", ""),
                    "priority": op,
                })
            else:
                new_tasks.append({
                    "id": str(uuid.uuid4()),
                    "content": line,
                    "created_at": now,
                    "status": "未完成",
                    "completed_at": "",
                    "priority": sub_pri,
                })
        setter(sub_key, tasks=new_tasks, milestones=milestones)
        try:
            pnm = str(log_name or sub_key)
            for ln in lines:
                if str(ln or "").strip():
                    print(f"[Task Saved] 项目: {pnm}, 任务: {str(ln).strip()}", flush=True)
        except Exception:
            pass
        return True

    def _on_todo_subproject_header_context(self, sub_key: str, sub_name: str, pos: QPoint):
        """待办区子项目标题行右键：仅「编辑时间节点」。"""
        w = self.sender()
        if not isinstance(w, QWidget):
            return
        sk = str(sub_key or "").strip().lower()
        if not sk:
            return
        menu = QMenu(self)
        act_ms = menu.addAction("编辑时间节点…")
        act = menu.exec(w.mapToGlobal(pos))
        if act != act_ms:
            return
        pm = self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        sub_info = subs.get(sk, {}) if isinstance(subs, dict) else {}
        if not isinstance(sub_info, dict):
            return
        disp = str(sub_name or sub_info.get("subproject_name", "") or sk)
        old_tasks = sub_info.get("tasks", []) or []
        old_lines = [str(t.get("content", "")).strip() for t in old_tasks if isinstance(t, dict) and str(t.get("content", "")).strip()]
        ms = sub_info.get("milestones") if isinstance(sub_info, dict) else None
        dlg = SubprojectTasksEditorDialog(
            self,
            f"编辑时间节点 — {disp}",
            old_lines,
            ms,
            milestones_only=True,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._apply_subproject_tasks_editor_result(sk, sub_info, dlg, disp)
        self._refresh_project_management_panel()

    def _on_todo_add_task_clicked(self, sub_key: str):
        sk = str(sub_key or "").strip().lower()
        if not sk:
            return
        pm = self._project_management_data()
        info = (pm.get("subprojects", {}) or {}).get(sk, {}) if isinstance(pm, dict) else {}
        if not isinstance(info, dict):
            return
        sub_name = str(info.get("subproject_name", "") or sk)
        dlg = SingleTodoTaskEditDialog(
            self,
            f"添加任务 - {sub_name}",
            None,
            default_priority=str(info.get("priority", "中") or "中"),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        content = dlg.get_content()
        if not content:
            return
        pri = dlg.get_priority()
        done = dlg.is_done()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tasks = list(info.get("tasks", []) or [])
        nt = {
            "id": str(uuid.uuid4()),
            "content": content,
            "created_at": now,
            "status": "已完成" if done else "未完成",
            "completed_at": now if done else "",
            "priority": pri,
        }
        tasks.append(nt)
        setter = getattr(self.core.config, "upsert_subproject", None)
        if callable(setter):
            setter(sk, tasks=tasks)
        self._refresh_project_management_panel()

    def _update_single_task(self, sub_key, task_id, action_text):
        pm = self._project_management_data()
        subs = pm.get("subprojects", {}) if isinstance(pm, dict) else {}
        info = subs.get(sub_key, {}) if isinstance(subs, dict) else {}
        if not isinstance(info, dict):
            return
        tasks = self._coerce_raw_tasks_list(info.get("tasks", []) or [])
        changed = False
        for t in tasks:
            if not isinstance(t, dict) or str(t.get("id", "")) != task_id:
                continue
            if action_text == "编辑任务":
                self._open_single_todo_task_editor(sub_key, task_id)
                return
            elif action_text == "标记完成":
                t["status"] = "已完成"
                t["completed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                changed = True
            elif action_text == "取消完成":
                t["status"] = "未完成"
                t["completed_at"] = ""
                changed = True
            elif action_text == "删除任务":
                tasks.remove(t)
                changed = True
            break
        if not changed:
            return
        setter = getattr(self.core.config, "upsert_subproject", None)
        if callable(setter):
            setter(sub_key, tasks=tasks)
        self._refresh_project_management_panel()

    def _focus_tree_subproject(self, sub_key):
        item = self._subproject_item_index.get(str(sub_key or "").lower())
        if item is None:
            return
        cur = item
        while cur:
            cur.setExpanded(True)
            cur = cur.parent()
        self.fav_tree.setCurrentItem(item)

    def _update_current_subproject_from_item(self, item):
        self._current_selected_sub_key = ""
        if item is None:
            return
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        target = item
        if node_type == "leaf" and item.parent() and item.parent().data(0, Qt.ItemDataRole.UserRole + 1) == "trial":
            target = item.parent()
            node_type = "trial"
        if node_type != "trial":
            return
        items = target.data(0, Qt.ItemDataRole.UserRole + 2) or []
        if not items or not isinstance(items[0], dict):
            return
        meta = self._extract_project_meta_from_path(items[0].get("full_path", ""), items[0].get("dir_type", "projects"))
        self._current_selected_sub_key = meta.get("sub_key", "")
        self._highlight_todo_for_subproject(self._current_selected_sub_key)

    def _highlight_todo_for_subproject(self, sub_key):
        key = str(sub_key or "").lower()
        if not key:
            return
        if getattr(self, "pm_tabs", None) is not None:
            self.pm_tabs.setCurrentIndex(0)
        frame = getattr(self, "_todo_group_frames", {}).get(key)
        if frame is None:
            return
        try:
            sc = getattr(self, "todo_scroll", None)
            if sc is not None:
                sc.ensureWidgetVisible(frame)
        except Exception:
            pass

    def _normalize_search_text(self, s: str) -> str:
        s = (s or "").strip().lower()
        # 忽略分隔符：csr01 匹配 csr_01 / csr-01 / csr 01
        return re.sub(r"[\s_\-\\/]+", "", s)

    def _flatten_fav_tree_index(self):
        """把当前收藏树中“可定位”的节点扁平化成 [(flat_text, full_path, fav_id)]"""
        out = []

        def _flat_path_for_item(item: QTreeWidgetItem) -> str:
            parts = []
            cur = item
            while cur is not None:
                t = (cur.text(0) or "").strip()
                if t:
                    parts.insert(0, t)
                cur = cur.parent()
            return "/".join(parts)

        def _direct_full_path_and_id(item: QTreeWidgetItem):
            fav = item.data(0, Qt.ItemDataRole.UserRole)
            items = item.data(0, Qt.ItemDataRole.UserRole + 2)
            if isinstance(fav, dict) and fav.get("full_path"):
                return fav.get("full_path", "") or "", fav.get("id", "") or ""
            if isinstance(items, list) and items and isinstance(items[0], dict) and items[0].get("full_path"):
                return items[0].get("full_path", "") or "", items[0].get("id", "") or ""
            return "", ""

        def walk(item: QTreeWidgetItem):
            node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
            if node_type in ("pinned_source", "pinned_empty") or bool(item.data(0, Qt.ItemDataRole.UserRole + 4)):
                # 搜索不包含置顶分组
                return []
            flat = _flat_path_for_item(item)
            direct_fp, fid = _direct_full_path_and_id(item)
            collected = []
            if direct_fp:
                collected.append(os.path.normpath(direct_fp).replace("/", "\\"))

            # 递归收集子路径
            child_paths = []
            for i in range(item.childCount()):
                child_paths.extend(walk(item.child(i)))

            collected.extend(child_paths)

            # 当前节点若没有直绑 full_path，则用子孙路径的 commonpath 来补齐（用于 csr_01 这种中间层级）
            node_fp = ""
            if collected:
                try:
                    node_fp = os.path.commonpath(collected)
                except Exception:
                    node_fp = collected[0]
            if node_fp:
                # 只保留“最小节点”的路径：同一个 full_path 后面会用去重策略选择更深层的 flat
                out.append((flat, node_fp, fid))

            return collected

        for i in range(self.fav_tree.topLevelItemCount()):
            walk(self.fav_tree.topLevelItem(i))

        # 去重：同一 (full_path, flat) 只保留一次；同一 full_path 取更深层 flat（更长）优先
        best_by_fp = {}
        seen_pair = set()
        for flat, fp, fid in out:
            fp = os.path.normpath(fp).replace("/", "\\")
            pair = (fp.lower(), flat.lower())
            if pair in seen_pair:
                continue
            seen_pair.add(pair)
            k = fp.lower()
            if k not in best_by_fp or len(flat) > len(best_by_fp[k][0]):
                best_by_fp[k] = (flat, fp, fid)
        self._fav_flat_paths = list(best_by_fp.values())

    def _hide_fav_search_list(self):
        if getattr(self, "fav_search_list", None) is None:
            return
        if self.fav_search_list.isVisible():
            self.fav_search_list.hide()

    def _position_fav_search_list(self):
        """把下拉层贴到搜索框下方，宽度对齐，最多 8 行"""
        if not self.fav_search_list or not self.fav_search_edit:
            return
        # 位置：相对 left 容器
        x = self.fav_search_edit.x()
        y = self.fav_search_edit.y() + self.fav_search_edit.height()
        w = self.fav_search_edit.width()
        rows = min(self.fav_search_list.count(), 8)
        h = max(1, rows) * 25 + 2
        self.fav_search_list.setGeometry(x, y, w, h)
        self.fav_search_list.raise_()

    def _on_fav_search_changed(self, text: str):
        """收藏库搜索：扁平单行路径下拉"""
        q = self._normalize_search_text(text)
        if not q:
            self.fav_search_list.clear()
            self._hide_fav_search_list()
            return
        # 确保索引存在
        if not hasattr(self, "_fav_flat_paths") or not getattr(self, "_fav_flat_paths", None):
            self._flatten_fav_tree_index()

        matches = []
        for flat, fp, fid in getattr(self, "_fav_flat_paths", []):
            if q in self._normalize_search_text(flat):
                matches.append((flat, fp, fid))

        self.fav_search_list.clear()
        if not matches:
            self._hide_fav_search_list()
            return

        # 最多显示 200 条（下拉层只显示 8 行，滚动可看更多）
        matches = matches[:200]
        def _leaf_label_from_flat(s: str) -> str:
            return (s.split("/")[-1] if s else "").strip()

        def _is_csr_like(label: str) -> bool:
            lab = (label or "").strip()
            if not lab:
                return False
            # csr_01 / adar_01 / scs_01 都用同一“对勾”图标
            return bool(re.match(r"^(csr|adar|scs|dsur)_?\d+$", lab, flags=re.I)) or any(
                k in lab.lower() for k in ("csr", "adar", "scs", "dsur")
            )

        for flat, fp, fid in matches:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, {"flat": flat, "full_path": fp, "id": fid})

            leaf = _leaf_label_from_flat(flat)
            if _is_csr_like(leaf):
                pix = icon_check_circle_outlined(12).pixmap(12, 12)
            else:
                pix = icon_folder_yellow().pixmap(14, 14)

            # 高亮匹配（保持你现在看到的红色高亮效果）
            safe = html.escape(flat)
            raw_lower = flat.lower()
            q_raw = (text or "").strip().lower()
            idx = raw_lower.find(q_raw) if q_raw else -1
            if idx >= 0 and q_raw:
                before = html.escape(flat[:idx])
                mid = html.escape(flat[idx: idx + len(q_raw)])
                after = html.escape(flat[idx + len(q_raw):])
                rich = f"{before}<span style='color:#FF4444;'>{mid}</span>{after}"
            else:
                rich = safe

            row = QWidget()
            row.setStyleSheet("background:transparent; border:none; outline:none;")
            row.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(4, 0, 4, 0)
            lay.setSpacing(6)
            icon_lbl = QLabel()
            icon_lbl.setFixedSize(14, 14)
            icon_lbl.setStyleSheet("background:transparent; border:none; outline:none;")
            icon_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            icon_lbl.setPixmap(pix)
            txt_lbl = QLabel()
            txt_lbl.setTextFormat(Qt.TextFormat.RichText)
            txt_lbl.setStyleSheet("background:transparent; border:none; outline:none; font-size:9px;")
            txt_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            txt_lbl.setText(rich)
            lay.addWidget(icon_lbl, 0)
            lay.addWidget(txt_lbl, 1)

            self.fav_search_list.addItem(it)
            it.setSizeHint(QSize(10, 23))
            self.fav_search_list.setItemWidget(it, row)

            # 路径失效标红（文本本身）
            try:
                if not os.path.exists(fp):
                    it.setForeground(QColor("#FF4444"))
            except Exception:
                pass

        self._position_fav_search_list()
        self.fav_search_list.setCurrentRow(0)
        self.fav_search_list.show()

    def _on_fav_search_item_clicked(self, item):
        """点击搜索结果：隐藏下拉层 -> 高亮收藏树 -> 右侧定位"""
        self._snapshot_fs_view_state_if_explorer()
        try:
            payload = item.data(Qt.ItemDataRole.UserRole) or {}
        except Exception:
            payload = {}
        fp = (payload.get("full_path") or "").strip()
        fid = (payload.get("id") or "").strip()
        self._hide_fav_search_list()
        self.fav_search_edit.clearFocus()

        if fp:
            self._showing_utility = False
            p = os.path.normpath(fp).replace("/", "\\")
            if os.path.isfile(p):
                p = os.path.dirname(p)
            fav_hit = None
            if fid:
                for f in self.core.get_favorites():
                    if isinstance(f, dict) and f.get("id") == fid:
                        fav_hit = f
                        break
            if fav_hit:
                fpath = os.path.normpath(str(fav_hit.get("full_path", "") or "")).replace("/", "\\")
                if fpath and os.path.isdir(fpath):
                    self.current_fav = fav_hit
                else:
                    self.current_fav = self._to_explorer_fav(p)
            else:
                self.current_fav = self._to_explorer_fav(p)
            self._show_right_explorer_view()
            QTimer.singleShot(0, self._refresh_tree)
        if fid:
            # 高亮收藏树时避免触发 _on_fav_selected 覆盖/清空右侧
            try:
                self.fav_tree.blockSignals(True)
                self._select_fav_in_tree(fid)
            finally:
                self.fav_tree.blockSignals(False)

    def _on_fav_search_item_hover(self, item):
        """悬停搜索结果：在状态栏显示完整路径（替代 tooltip，避免黑框）。"""
        try:
            payload = item.data(Qt.ItemDataRole.UserRole) or {}
        except Exception:
            payload = {}
        fp = (payload.get("full_path") or "").strip()
        if fp:
            self.statusBar().showMessage(fp, 2000)

    def _set_node_font(self, item: QTreeWidgetItem, level: int):
        """左侧树节点字体分层：source/product 同样式，trial/leaf 更小。"""
        if isinstance(item, FavTreeWidgetItem):
            item.set_level(level)
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        # 根目录节点保持“纯文字 + 展开箭头”，强制移除前导图标/圆圈标记
        try:
            label = (item.text(0) or "").strip().lower()
            if node_type == "source" and label in ("projects", "unblinded", "users"):
                item.setIcon(0, QIcon())
        except Exception:
            pass
        # 勿直接沿用 item.font(0)：未显式设置时常为 pointSize=-1，会触发 QFont::setPointSize 警告
        font = QFont()
        fam = item.font(0).family()
        if fam and fam.strip():
            font.setFamily(fam)
        # projects/unblinded/users 与产品节点保持一致：不加粗
        if node_type in ("source",) or level == 0:
            font.setPointSize(10)
            font.setBold(False)
        elif node_type == "product":
            font.setPointSize(9)
            font.setBold(False)
        # 项目节点（如 HRS1301_101）
        elif node_type in ("trial", "parent"):
            font.setPointSize(8)
            font.setBold(False)
        # 最小叶子节点（如 csr_01）
        elif node_type == "leaf":
            font.setPointSize(8)
            font.setBold(False)
        else:
            font.setPointSize(8)
            font.setBold(False)
        item.setFont(0, font)

    def _apply_fav_tree_node_styles(self):
        """刷新后重新应用左侧树节点样式。"""
        def walk(node, level):
            self._set_node_font(node, level)
            for i in range(node.childCount()):
                walk(node.child(i), level + 1)
        for i in range(self.fav_tree.topLevelItemCount()):
            walk(self.fav_tree.topLevelItem(i), 0)

    def _fav_item_key(self, item: QTreeWidgetItem):
        """按父子文本拼接唯一路径键。"""
        parts = []
        cur = item
        while cur is not None:
            txt = (cur.text(0) or "").strip()
            if txt:
                parts.append(txt)
            cur = cur.parent()
        return "/".join(reversed(parts))

    def _on_fav_tree_expand_changed(self, _item):
        if self._restoring_fav_expand_state:
            return
        QTimer.singleShot(0, self.save_tree_expand_state)

    def save_tree_expand_state(self):
        """保存左侧收藏树展开状态到配置。"""
        if getattr(self, "_fav_tree_rebuilding", False):
            return
        if getattr(self, "_restoring_fav_expand_state", False):
            return
        states = {}
        for i in range(self.fav_tree.topLevelItemCount()):
            top = self.fav_tree.topLevelItem(i)
            stack = [top]
            while stack:
                cur = stack.pop()
                key = self._fav_item_key(cur)
                if key:
                    states[key] = bool(cur.isExpanded())
                for j in range(cur.childCount() - 1, -1, -1):
                    stack.append(cur.child(j))
        try:
            setter = getattr(self.core.config, "set_fav_tree_expand_states", None)
            if callable(setter):
                setter(states)
        except Exception:
            pass

    def restore_tree_expand_state(self):
        """恢复左侧收藏树展开状态；无记录默认折叠，并清理无效记录。"""
        try:
            getter = getattr(self.core.config, "get_fav_tree_expand_states", None)
            saved = getter() if callable(getter) else {}
        except Exception:
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        valid_keys = set()
        self._restoring_fav_expand_state = True
        try:
            for i in range(self.fav_tree.topLevelItemCount()):
                top = self.fav_tree.topLevelItem(i)
                stack = [top]
                while stack:
                    cur = stack.pop()
                    key = self._fav_item_key(cur)
                    if key:
                        valid_keys.add(key)
                        cur.setExpanded(bool(saved.get(key, False)))
                    else:
                        cur.setExpanded(False)
                    for j in range(cur.childCount() - 1, -1, -1):
                        stack.append(cur.child(j))
        finally:
            self._restoring_fav_expand_state = False
        cleaned = {k: bool(v) for k, v in saved.items() if k in valid_keys}
        if cleaned != saved:
            try:
                setter = getattr(self.core.config, "set_fav_tree_expand_states", None)
                if callable(setter):
                    setter(cleaned)
            except Exception:
                pass
    
    def _load_favorites(self):
        self._fav_tree_rebuilding = True
        try:
            self.fav_tree.blockSignals(True)
            try:
                self.fav_tree.clear()
            finally:
                self.fav_tree.blockSignals(False)
            def mk_item(text, level):
                return FavTreeWidgetItem([text], level)
            self._reload_pinned_projects()
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
            # 置顶分组（在 projects 上方，展示层级与 projects 一致）
            pinned_root = mk_item("置顶项目", 0)
            pinned_root.setData(0, Qt.ItemDataRole.UserRole + 1, "pinned_source")
            pinned_root.setIcon(0, icon_bars_outlined(14, color="#F53F3F", alpha=0.98))
            pinned_root.setData(0, Qt.ItemDataRole.UserRole + 6, True)
            if self._pinned_projects:
                projects_map = by_pt.get("projects", {})
    
                def build_pinned_product(product_name, trial_only=None, pin_meta=None):
                    if product_name not in projects_map:
                        return None
                    product_node = mk_item(product_name, 1)
                    product_node.setData(0, Qt.ItemDataRole.UserRole + 1, "product")
                    product_node.setData(0, Qt.ItemDataRole.UserRole + 3, pin_meta or {})
                    product_node.setData(0, Qt.ItemDataRole.UserRole + 4, True)
                    all_favs = []
                    for tk, fl in projects_map[product_name].items():
                        if trial_only and tk != trial_only:
                            continue
                        all_favs.extend(fl)
                    product_root_path = ""
                    if all_favs:
                        fp = os.path.normpath(all_favs[0].get("full_path", "")).replace("/", "\\")
                        parts = [x for x in fp.split("\\") if x]
                        rn = _source_root_name("projects")
                        for i, x in enumerate(parts):
                            if x.lower() == rn:
                                product_root_path = "\\".join(parts[: i + 1] + [product_name])
                                break
                    product_node.setData(0, Qt.ItemDataRole.UserRole, {
                        "full_path": product_root_path or (all_favs[0]["full_path"] if all_favs else ""),
                        "display_name": product_name,
                        "id": f"pinned_product_projects_{product_name}",
                        "is_product_node": True,
                        "dir_type": "projects",
                    })
                    product_node.setData(0, Qt.ItemDataRole.UserRole + 2, list(all_favs))
                    product_node.setIcon(0, icon_home_outlined(14))
                    for trial_key in sorted(projects_map[product_name].keys(), key=lambda x: x or "\0"):
                        if trial_only and trial_key != trial_only:
                            continue
                        flist = projects_map[product_name][trial_key]
                        if not trial_key:
                            continue
                        trial_node = mk_item(trial_key, 2)
                        trial_node.setData(0, Qt.ItemDataRole.UserRole + 1, "trial")
                        trial_node.setData(0, Qt.ItemDataRole.UserRole + 2, flist)
                        trial_node.setData(0, Qt.ItemDataRole.UserRole + 3, pin_meta or {})
                        trial_node.setData(0, Qt.ItemDataRole.UserRole + 4, True)
                        trial_node.setIcon(0, icon_folder_yellow())
                        seen_paths = set()
                        for fav in sorted(flist, key=lambda x: x.get("display_name", "")):
                            norm_path = os.path.normpath(fav.get("full_path", "") or "").replace("/", "\\")
                            if norm_path and norm_path in seen_paths:
                                continue
                            seen_paths.add(norm_path)
                            _, sub = _parse_display_name(fav.get("display_name", ""))
                            label = sub or os.path.basename(fav.get("full_path", "").rstrip("\\")) or fav.get("display_name", "")
                            leaf = mk_item(label, 3)
                            leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                            leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                            leaf.setData(0, Qt.ItemDataRole.UserRole + 3, pin_meta or {})
                            leaf.setData(0, Qt.ItemDataRole.UserRole + 4, True)
                            leaf.setIcon(
                                0,
                                icon_check_circle_outlined(12)
                                if re.match(r"^(csr|adar|scs|dsur)_?\d*$", label, re.I)
                                or (label and any(k in label.lower() for k in ("csr", "adar", "scs", "dsur")))
                                else icon_folder_yellow(),
                            )
                            trial_node.addChild(leaf)
                        product_node.addChild(trial_node)
                    return product_node
    
                # 按产品合并置顶范围，避免同一产品重复出现
                pinned_scope = {}  # product -> {"full": bool, "trials": set[str], "meta": {"name","path"}}
                fallback_pins = []  # 无法归并到 projects_map 的置顶项，按叶子展示
                for p in self._pinned_projects:
                    name = str(p.get("name", "")).strip()
                    path = os.path.normpath(str(p.get("path", "") or "")).replace("/", "\\")
                    if not name or not path:
                        continue
                    pin_meta = {"name": name, "path": path}
                    product, trial, subdir = _product_trial_from_path(path, "projects")
                    if product in projects_map:
                        sc = pinned_scope.setdefault(product, {"full": False, "trials": set(), "meta": pin_meta})
                        if not sc.get("meta"):
                            sc["meta"] = pin_meta
                        if not trial and not subdir:
                            sc["full"] = True
                        elif trial:
                            sc["trials"].add(trial)
                    else:
                        fallback_pins.append(pin_meta)
    
                for product, sc in pinned_scope.items():
                    meta = sc.get("meta") or {}
                    if sc.get("full") or not sc.get("trials"):
                        node = build_pinned_product(product, trial_only=None, pin_meta=meta)
                        if node:
                            pinned_root.addChild(node)
                    else:
                        # 仅展示被置顶的试验集合（每个试验及其全部子项目）
                        for t in sorted(sc.get("trials", set())):
                            node = build_pinned_product(product, trial_only=t, pin_meta=meta)
                            if node:
                                pinned_root.addChild(node)
    
                for pin_meta in fallback_pins:
                    name = pin_meta.get("name", "")
                    path = pin_meta.get("path", "")
                    fav = self._resolve_fav_from_name_path(name, path)
                    leaf = mk_item(name, 1)
                    leaf.setData(0, Qt.ItemDataRole.UserRole, fav if fav else {"display_name": name, "full_path": path, "dir_type": "projects"})
                    leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                    leaf.setData(0, Qt.ItemDataRole.UserRole + 3, pin_meta)
                    leaf.setData(0, Qt.ItemDataRole.UserRole + 4, True)
                    leaf.setToolTip(0, path)
                    leaf.setIcon(0, icon_folder_yellow())
                    pinned_root.addChild(leaf)
            else:
                empty = mk_item("暂无置顶项目", 1)
                empty.setData(0, Qt.ItemDataRole.UserRole + 1, "pinned_empty")
                empty.setIcon(0, icon_folder_yellow())
                pinned_root.addChild(empty)
            self.fav_tree.addTopLevelItem(pinned_root)
    
            for dt in dir_order:
                root = mk_item(dt, 0)
                root.setData(0, Qt.ItemDataRole.UserRole + 1, "source")
                root.setIcon(0, icon_folder_yellow())
                if dt in by_pt:
                    if dt == "users":
                        for sub_root in ["unblinded", "projects"]:
                            if sub_root not in by_pt[dt]:
                                continue
                            sub_root_node = mk_item(sub_root, 1)
                            sub_root_node.setData(0, Qt.ItemDataRole.UserRole + 1, "source")
                            sub_root_node.setIcon(0, icon_folder_yellow())
                            root.addChild(sub_root_node)
                            for product in sorted(by_pt[dt][sub_root].keys()):
                                product_node = mk_item(product, 2)
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
                                product_node.setData(0, Qt.ItemDataRole.UserRole + 2, list(all_favs))
                                product_node.setIcon(0, icon_home_outlined(14))
                                for trial_key in sorted(by_pt[dt][sub_root][product].keys(), key=lambda x: x or "\0"):
                                    flist = by_pt[dt][sub_root][product][trial_key]
                                    if trial_key:
                                        trial_node = mk_item(trial_key, 3)
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
                                            leaf = mk_item(label, 4)
                                            leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                            leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                            leaf.setIcon(
                                                0,
                                                icon_check_circle_outlined(12)
                                                if re.match(r"^(csr|adar|scs|dsur)_?\\d*$", label, re.I)
                                                or (label and any(k in label.lower() for k in ("csr", "adar", "scs", "dsur")))
                                                else icon_folder_yellow(),
                                            )
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
                                            leaf = mk_item(label, 4)
                                            leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                            leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                            leaf.setIcon(0, icon_folder_yellow())
                                            product_node.addChild(leaf)
                                sub_root_node.addChild(product_node)
                    else:
                        for product in sorted(by_pt[dt].keys()):
                            product_node = mk_item(product, 1)
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
                                product_root_path = os.path.normpath(
                                    os.path.join(os.path.dirname(all_favs[0]["full_path"]), "..", product)
                                ).replace("/", "\\")
                            product_node.setData(0, Qt.ItemDataRole.UserRole, {
                                "full_path": product_root_path or (all_favs[0]["full_path"] if all_favs else ""),
                                "display_name": product,
                                "id": f"product_{dt}_{product}",
                                "is_product_node": True,
                                "dir_type": dt,
                            })
                            product_node.setData(0, Qt.ItemDataRole.UserRole + 2, list(all_favs))
                            product_node.setIcon(0, icon_home_outlined(14))
                            for trial_key in sorted(by_pt[dt][product].keys(), key=lambda x: x or "\0"):
                                flist = by_pt[dt][product][trial_key]
                                if trial_key:
                                    trial_node = mk_item(trial_key, 2)
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
                                        leaf = mk_item(label, 3)
                                        leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                        leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                        leaf.setIcon(
                                            0,
                                            icon_check_circle_outlined(12)
                                            if re.match(r"^(csr|adar|scs|dsur)_?\\d*$", label, re.I)
                                            or (label and any(k in label.lower() for k in ("csr", "adar", "scs", "dsur")))
                                            else icon_folder_yellow(),
                                        )
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
                                        leaf = mk_item(label, 3)
                                        leaf.setData(0, Qt.ItemDataRole.UserRole, fav)
                                        leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                        leaf.setIcon(0, icon_folder_yellow())
                                        product_node.addChild(leaf)
                            root.addChild(product_node)
                if dt in by_dir_legacy and by_dir_legacy[dt]:
                    for main_name, items in sorted(by_dir_legacy[dt].items(), key=lambda x: x[0]):
                        if len(items) == 1 and not _parse_display_name(items[0].get("display_name", ""))[1]:
                            leaf = mk_item(items[0].get("display_name", main_name), 1)
                            leaf.setData(0, Qt.ItemDataRole.UserRole, items[0])
                            leaf.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                            leaf.setIcon(0, icon_folder_yellow())
                            root.addChild(leaf)
                        else:
                            parent = mk_item(main_name, 1)
                            parent.setData(0, Qt.ItemDataRole.UserRole + 1, "parent")
                            parent.setData(0, Qt.ItemDataRole.UserRole + 2, items)
                            parent.setIcon(0, icon_folder_yellow())
                            for f in sorted(items, key=lambda x: x.get("display_name", "")):
                                _, sub = _parse_display_name(f.get("display_name", ""))
                                label = sub or f.get("display_name", "")
                                child = mk_item(label, 2)
                                child.setData(0, Qt.ItemDataRole.UserRole, f)
                                child.setData(0, Qt.ItemDataRole.UserRole + 1, "leaf")
                                child.setIcon(
                                    0,
                                    icon_check_circle_outlined(12)
                                    if re.match(r"^(csr|adar|scs|dsur)_?\\d+$", label, re.I)
                                    else icon_folder_yellow(),
                                )
                                parent.addChild(child)
                            root.addChild(parent)
                self.fav_tree.addTopLevelItem(root)
            if self.current_fav:
                self._select_fav_in_tree(self.current_fav.get("id"))
            # 左侧树刷新后重新应用层级字体 + 恢复展开状态
            self._apply_fav_tree_node_styles()
    
            def _after_fav_restore():
                try:
                    self.restore_tree_expand_state()
                finally:
                    self._fav_tree_rebuilding = False
    
            QTimer.singleShot(0, _after_fav_restore)
            # 刷新扁平搜索索引
            try:
                self._flatten_fav_tree_index()
            except Exception:
                self._fav_flat_paths = []
            self._rebuild_subproject_index()
            self._refresh_project_management_panel()
        except Exception:
            self._fav_tree_rebuilding = False
            raise

    def _open_folder_with_feedback(self, folder_path, select_path=None):
        """打开文件夹：路径校验、执行、状态栏提示及操作反馈。

        - select_path 不为空：打开资源管理器并选中该文件
        - 否则：打开 folder_path（本地路径优先复用已有资源管理器窗口）
        """
        if not folder_path or not str(folder_path).strip():
            try:
                print("[PFN] 打开文件夹：未获取到路径", flush=True)
                self.statusBar().showMessage("未获取到文件夹路径", 4000)
            except Exception:
                pass
            return
        if select_path:
            select_path = os.path.normpath(select_path).replace("/", "\\")
            if not os.path.exists(select_path):
                try:
                    print(f"[PFN] 打开文件夹：选中路径不存在 {select_path}", flush=True)
                    self.statusBar().showMessage("路径无效或不可访问", 4000)
                except Exception:
                    pass
                return
            folder_path = os.path.dirname(select_path)
        folder_path = os.path.normpath(folder_path).replace("/", "\\")
        if not os.path.isabs(folder_path):
            folder_path = os.path.abspath(folder_path)
        if not os.path.exists(folder_path):
            try:
                print(f"[PFN] 打开文件夹：路径不存在 {folder_path}", flush=True)
                self.statusBar().showMessage("路径无效或不可访问", 4000)
            except Exception:
                pass
            return
        try:
            self.core.open_folder(folder_path, select_path=select_path)
            short = os.path.basename(folder_path.rstrip("\\")) or folder_path
            self.statusBar().showMessage(f"已打开：{short}", 3000)
            QTimer.singleShot(3000, lambda: self.statusBar().showMessage("若未打开请检查路径或网络", 2000))
        except Exception as e:
            try:
                print(f"[PFN] 打开文件夹失败: {e}", flush=True)
                self.statusBar().showMessage(f"打开失败：{e}", 6000)
            except Exception:
                pass

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

    def _get_item_ref_for_pin(self, item):
        """提取可置顶节点引用：返回 (name, path) 或 None。
        支持产品根、试验目录（非必须点到 csr_01 等叶子）、聚合 parent、叶子。"""
        if item is None:
            return None
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        fav = item.data(0, Qt.ItemDataRole.UserRole)
        items = item.data(0, Qt.ItemDataRole.UserRole + 2) or []
        name = (item.text(0) or "").strip()
        path = ""

        if node_type == "product" and isinstance(fav, dict) and fav.get("is_product_node"):
            name = (item.text(0) or fav.get("display_name") or "").strip()
            path = str(fav.get("full_path", "") or "")

        elif node_type == "trial" and isinstance(items, list) and items and isinstance(items[0], dict):
            meta = self._extract_project_meta_from_path(
                items[0].get("full_path", ""), items[0].get("dir_type", "projects")
            )
            name = (meta.get("subproject_name") or name).strip()
            path = str(meta.get("path", "") or "")

        elif node_type == "parent" and isinstance(items, list) and items and isinstance(items[0], dict):
            path = str(items[0].get("full_path", "") or "")
            name = (item.text(0) or "").strip()

        elif isinstance(fav, dict) and fav.get("full_path"):
            path = str(fav.get("full_path", "") or "")

        path = os.path.normpath(str(path or "")).replace("/", "\\")
        if not name or not path:
            return None
        return name, path

    def _is_pinned(self, name, path):
        name = str(name or "").strip().lower()
        path = os.path.normpath(str(path or "")).replace("/", "\\").lower()
        for p in self._pinned_projects:
            if not isinstance(p, dict):
                continue
            if str(p.get("name", "")).strip().lower() == name and os.path.normpath(str(p.get("path", ""))).replace("/", "\\").lower() == path:
                return True
        return False

    def _reload_pinned_projects(self):
        getter = getattr(self.core.config, "get_pinned_projects", None)
        pins = getter() if callable(getter) else []
        if not isinstance(pins, list):
            pins = []
        cleaned = []
        seen = set()
        for p in pins:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "")).strip()
            path = os.path.normpath(str(p.get("path", "") or "")).replace("/", "\\")
            if not name or not path:
                continue
            key = (name.lower(), path.lower())
            if key in seen:
                continue
            seen.add(key)
            cleaned.append({"name": name, "path": path})
        self._pinned_projects = cleaned
    
    def _resolve_fav_from_name_path(self, name, path):
        """根据 name/path 解析为真实 favorite(dict)。"""
        name = str(name or "").strip().lower()
        path = os.path.normpath(str(path or "")).replace("/", "\\").lower()
        for f in self.core.get_favorites():
            if not isinstance(f, dict):
                continue
            fp = os.path.normpath(str(f.get("full_path", "") or "")).replace("/", "\\").lower()
            dn = str(f.get("display_name", "") or "").strip().lower()
            if fp == path and (not name or dn == name or dn.endswith("/" + name)):
                return f
        return None

    def _find_fav_item_by_name_path(self, name, path):
        name = str(name or "").strip().lower()
        path = os.path.normpath(str(path or "")).replace("/", "\\").lower()
        if not name or not path:
            return None

        def walk(node):
            ref = self._get_item_ref_for_pin(node)
            if ref:
                n, p = ref
                if n.strip().lower() == name and os.path.normpath(p).replace("/", "\\").lower() == path:
                    return node
            for i in range(node.childCount()):
                r = walk(node.child(i))
                if r:
                    return r
            return None

        for i in range(self.fav_tree.topLevelItemCount()):
            top = self.fav_tree.topLevelItem(i)
            r = walk(top)
            if r:
                return r
        return None

    # 置顶下拉框改为左树「置顶项目」分组，保留解析/增删方法供树节点复用。

    def _on_utility_clicked(self):
        """点击固定区域：右侧展示 Z:\\projects\\utility 目录"""
        self._snapshot_fs_view_state_if_explorer()
        self._showing_utility = True
        self.current_fav = None
        try:
            self.fav_tree.blockSignals(True)
            self.fav_tree.clearSelection()
        finally:
            self.fav_tree.blockSignals(False)
        self._show_right_explorer_view()
        QTimer.singleShot(0, self._refresh_tree)
    
    def _on_fav_selected(self):
        self._snapshot_fs_view_state_if_explorer()
        sel = self.fav_tree.selectedItems()
        if not sel:
            self._showing_utility = False
            self.current_fav = None
            self._show_right_pm_view()
            return

        item = sel[0]
        self._showing_utility = False
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)

        if node_type == "pinned_empty":
            self._show_right_pm_view()
            return

        if node_type == "pinned_leaf":
            pin = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
            real = self._resolve_fav_from_name_path(pin.get("name", ""), pin.get("path", ""))
            if not isinstance(real, dict):
                self.statusBar().showMessage("置顶项已失效（原项目可能已删除）", 3000)
                self._show_right_pm_view()
                return

        fav_sel = self._favorite_dict_for_selection(item)
        if fav_sel:
            fp = os.path.normpath(str(fav_sel.get("full_path", "") or "")).replace("/", "\\")
            if fp and os.path.isdir(fp):
                # 使用收藏原 dict，走 _do_refresh_tree 归类布局（projects / unblinded / users 等）
                self.current_fav = fav_sel
                self._update_current_subproject_from_item(item)
                self._show_right_explorer_view()
                QTimer.singleShot(0, self._refresh_tree)
                return
            self.current_fav = None
            self._update_current_subproject_from_item(item)
            self._show_right_pm_view()
            self.update_status("收藏路径不可用，请检查网络或 Z 盘映射")
            return

        folder = self._resolve_left_tree_directory(item)
        if not folder:
            self.current_fav = None
            self._update_current_subproject_from_item(item)
            self._show_right_pm_view()
            if node_type == "source" and item.parent() is not None:
                self.update_status("该分类下请展开后选择具体项目节点浏览目录")
            elif node_type in ("trial", "product"):
                self.update_status("路径不可用，请检查网络或 Z 盘映射")
            return

        self.current_fav = self._to_explorer_fav(folder)
        self._update_current_subproject_from_item(item)
        self._show_right_explorer_view()
        QTimer.singleShot(0, self._refresh_tree)
    
    def _on_fav_context(self, pos):
        # 右键仅用于弹出菜单：如果用户未选择任何菜单项（exec 返回 None），
        # 不应改变左树选中/右侧视图，否则会触发刷新造成“整栏全部收起”的观感。
        item = self.fav_tree.itemAt(pos)
        if not item:
            return
        prev_selected = []
        prev_current_item = None
        prev_current_fav = None
        prev_showing_utility = bool(getattr(self, "_showing_utility", False))
        prev_right_widget = None
        prev_expand_states = {}
        try:
            prev_selected = list(self.fav_tree.selectedItems() or [])
        except Exception:
            prev_selected = []
        try:
            prev_current_item = self.fav_tree.currentItem()
        except Exception:
            prev_current_item = None
        prev_current_fav = getattr(self, "current_fav", None) if isinstance(getattr(self, "current_fav", None), dict) else None
        try:
            rs = getattr(self, "_right_stack", None)
            prev_right_widget = rs.currentWidget() if rs is not None else None
        except Exception:
            prev_right_widget = None

        # 快照左侧树展开状态：用于“右键菜单未选择项就关闭”时恢复，避免整棵树被意外折叠
        try:
            for i in range(self.fav_tree.topLevelItemCount()):
                top = self.fav_tree.topLevelItem(i)
                stack = [top]
                while stack:
                    cur = stack.pop()
                    try:
                        key = self._fav_item_key(cur)
                        if key:
                            prev_expand_states[key] = bool(cur.isExpanded())
                    except Exception:
                        pass
                    for j in range(cur.childCount() - 1, -1, -1):
                        stack.append(cur.child(j))
        except Exception:
            prev_expand_states = {}

        def _restore_prev_state_if_no_action(chosen_action):
            if chosen_action is not None:
                return
            # 先恢复展开状态（最重要：避免“全部下拉框收起”）
            if isinstance(prev_expand_states, dict) and prev_expand_states:
                self._restoring_fav_expand_state = True
                try:
                    for i in range(self.fav_tree.topLevelItemCount()):
                        top = self.fav_tree.topLevelItem(i)
                        stack = [top]
                        while stack:
                            cur = stack.pop()
                            try:
                                key = self._fav_item_key(cur)
                                if key:
                                    cur.setExpanded(bool(prev_expand_states.get(key, cur.isExpanded())))
                            except Exception:
                                pass
                            for j in range(cur.childCount() - 1, -1, -1):
                                stack.append(cur.child(j))
                finally:
                    self._restoring_fav_expand_state = False
            try:
                self.fav_tree.blockSignals(True)
                try:
                    self.fav_tree.clearSelection()
                except Exception:
                    pass
                # 恢复此前选中（通常 0 或 1 个），避免触发 _on_fav_selected 导致右侧刷新/折叠
                for it in prev_selected:
                    try:
                        it.setSelected(True)
                    except Exception:
                        continue
                if prev_current_item is not None:
                    try:
                        self.fav_tree.setCurrentItem(prev_current_item)
                    except Exception:
                        pass
            finally:
                try:
                    self.fav_tree.blockSignals(False)
                except Exception:
                    pass
            # 恢复右侧与 current_fav（不触发刷新）
            try:
                self._showing_utility = bool(prev_showing_utility)
            except Exception:
                pass
            try:
                self.current_fav = prev_current_fav
            except Exception:
                pass
            try:
                rs = getattr(self, "_right_stack", None)
                if prev_right_widget is not None and rs is not None:
                    rs.setCurrentWidget(prev_right_widget)
            except Exception:
                pass
        node_type = item.data(0, Qt.ItemDataRole.UserRole + 1)
        fav = item.data(0, Qt.ItemDataRole.UserRole)
        items = item.data(0, Qt.ItemDataRole.UserRole + 2)
        pin_meta = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
        is_pinned_tree_item = bool(item.data(0, Qt.ItemDataRole.UserRole + 4))
        menu = QMenu(self)
        if node_type == "product" and fav and fav.get("is_product_node"):
            ref = self._get_item_ref_for_pin(item)
            product_favs = item.data(0, Qt.ItemDataRole.UserRole + 2) or []
            product_favs = [f for f in product_favs if isinstance(f, dict) and f.get("id")]
            act_pin = None
            act_unpin = None
            if is_pinned_tree_item and pin_meta:
                act_unpin = menu.addAction("取消置顶")
            else:
                act_pin = menu.addAction("添加到置顶（整个产品）")
                if ref and self._is_pinned(ref[0], ref[1]):
                    act_pin.setEnabled(False)
            ta_menu = menu.addMenu("设置 TA")
            ta_items = ["心血管", "肾病", "感染", "神经", "呼吸", "自免"]
            ta_actions = {}
            for ta in ta_items:
                ta_actions[ta] = ta_menu.addAction(ta)
            act_del = None
            if product_favs:
                act_del = menu.addAction("删除产品下全部子项目")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            _restore_prev_state_if_no_action(act)
            if act == act_unpin:
                p_name = str(pin_meta.get("name", item.text(0))).strip()
                p_path = os.path.normpath(str(pin_meta.get("path", ""))).replace("/", "\\")
                remover = getattr(self.core.config, "remove_pinned_project", None)
                if callable(remover) and p_name and p_path:
                    remover(p_name, p_path)
                self._load_favorites()
                self.statusBar().showMessage(f"已取消置顶：{p_name or item.text(0)}", 2000)
            elif act == act_pin and ref:
                adder = getattr(self.core.config, "add_pinned_project", None)
                if callable(adder) and adder(ref[0], ref[1]):
                    self._load_favorites()
                    self.statusBar().showMessage(f"已置顶产品：{ref[0]}", 2000)
            elif act == act_del and product_favs:
                r = QMessageBox.question(
                    self, "确认删除",
                    f"确定要删除产品「{item.text(0)}」下的全部 {len(product_favs)} 个收藏子项目吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r == QMessageBox.StandardButton.Yes:
                    for f in product_favs:
                        self.core.remove_favorite(f["id"])
                    self.current_fav = None
                    self._load_favorites()
                    self._refresh_project_management_panel()
            elif act in ta_actions.values():
                selected_ta = next((k for k, v in ta_actions.items() if v == act), "")
                setter = getattr(self.core.config, "set_root_project_ta", None)
                if callable(setter):
                    setter(item.text(0).strip(), selected_ta)
                self._refresh_project_management_panel()
                self.statusBar().showMessage(f"{item.text(0)} 已设置 TA：{selected_ta}", 2500)
        elif node_type == "trial" and items:
            meta = self._extract_project_meta_from_path(items[0].get("full_path", ""), items[0].get("dir_type", "projects"))
            sub_key = meta.get("sub_key", "")
            ref = self._get_item_ref_for_pin(item)
            act_pin = None
            act_unpin = None
            if is_pinned_tree_item and pin_meta:
                act_unpin = menu.addAction("取消置顶")
            else:
                act_pin = menu.addAction("添加到置顶（本试验目录）")
                if ref and self._is_pinned(ref[0], ref[1]):
                    act_pin.setEnabled(False)
            status_menu = menu.addMenu("项目状态")
            act_status_todo = status_menu.addAction("未完成")
            act_status_done = status_menu.addAction("已完成")
            priority_menu = menu.addMenu("优先级")
            act_p_h = priority_menu.addAction("高")
            act_p_m = priority_menu.addAction("中")
            act_p_l = priority_menu.addAction("低")
            act_edit_task = menu.addAction("编辑项目任务")
            act_del = menu.addAction("删除本试验下全部子项目")
            action = menu.exec(self.fav_tree.mapToGlobal(pos))
            _restore_prev_state_if_no_action(action)
            # 关键：未选择任何菜单项（点空白/ESC）时，必须直接退出。
            # 否则下面的 upsert_subproject + 刷新会重建左树，导致“全部收起”。
            if action is None:
                return
            if action == act_unpin:
                p_name = str(pin_meta.get("name", item.text(0))).strip()
                p_path = os.path.normpath(str(pin_meta.get("path", ""))).replace("/", "\\")
                remover = getattr(self.core.config, "remove_pinned_project", None)
                if callable(remover) and p_name and p_path:
                    remover(p_name, p_path)
                self._load_favorites()
                self.statusBar().showMessage(f"已取消置顶：{p_name or item.text(0)}", 2000)
                return
            if action == act_pin and ref:
                adder = getattr(self.core.config, "add_pinned_project", None)
                if callable(adder) and adder(ref[0], ref[1]):
                    self._load_favorites()
                    self.statusBar().showMessage(f"已置顶：{ref[0]}", 2000)
                return
            if action == act_del:
                r = QMessageBox.question(
                    self, "确认删除",
                    f"确定要删除试验「{item.text(0)}」下的全部 {len(items)} 个子项目吗？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if r == QMessageBox.StandardButton.Yes:
                    for f in items:
                        self.core.remove_favorite(f["id"])
                    self.current_fav = None
                    self._load_favorites()
                self._refresh_project_management_panel()
                return
            setter = getattr(self.core.config, "upsert_subproject", None)
            if not callable(setter):
                return
            setter(
                sub_key,
                root_name=meta.get("root_name", ""),
                subproject_name=meta.get("subproject_name", ""),
                path=meta.get("path", ""),
            )
            if action == act_status_todo:
                setter(sub_key, status="未完成")
            elif action == act_status_done:
                setter(sub_key, status="已完成")
            elif action == act_p_h:
                setter(sub_key, priority="高")
            elif action == act_p_m:
                setter(sub_key, priority="中")
            elif action == act_p_l:
                setter(sub_key, priority="低")
            elif action == act_edit_task:
                pm = self._project_management_data()
                sub_info = (pm.get("subprojects", {}) or {}).get(sub_key, {}) if isinstance(pm, dict) else {}
                old_tasks = sub_info.get("tasks", []) if isinstance(sub_info, dict) else []
                old_lines = [str(t.get("content", "")).strip() for t in old_tasks if isinstance(t, dict) and str(t.get("content", "")).strip()]
                dlg = SubprojectTasksEditorDialog(
                    self,
                    f"编辑任务 - {meta.get('subproject_name','')}",
                    old_lines,
                    (sub_info.get("milestones") if isinstance(sub_info, dict) else None),
                )
                if dlg.exec() == QDialog.DialogCode.Accepted:
                    self._apply_subproject_tasks_editor_result(
                        sub_key,
                        sub_info,
                        dlg,
                        str(meta.get("subproject_name", "") or sub_key),
                    )
            self._refresh_project_management_panel()
        elif node_type == "leaf" and fav:
            act_open = menu.addAction("打开所在文件夹")
            ref = self._get_item_ref_for_pin(item)
            act_pin = None
            act_unpin = None
            act_del = None
            if is_pinned_tree_item and pin_meta:
                act_unpin = menu.addAction("取消置顶")
            else:
                act_pin = menu.addAction("添加到置顶（本子目录）")
                if ref and self._is_pinned(ref[0], ref[1]):
                    act_pin.setEnabled(False)
                act_del = menu.addAction("删除子项目")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            _restore_prev_state_if_no_action(act)
            if act == act_open:
                self._open_folder_with_feedback(fav["full_path"])
            elif act == act_pin and ref:
                adder = getattr(self.core.config, "add_pinned_project", None)
                if callable(adder) and adder(ref[0], ref[1]):
                    self._load_favorites()
                    self.statusBar().showMessage(f"已置顶：{ref[0]}", 2000)
            elif act == act_unpin:
                target_name = ""
                target_path = ""
                if ref and self._is_pinned(ref[0], ref[1]):
                    target_name, target_path = ref[0], ref[1]
                if not target_name or not target_path:
                    self.statusBar().showMessage("该子类目未单独置顶，未执行取消", 2500)
                    return
                msg_name = str(target_name)
                remover = getattr(self.core.config, "remove_pinned_project", None)
                if callable(remover):
                    remover(target_name, target_path)
                self._load_favorites()
                self.statusBar().showMessage(f"已取消置顶：{msg_name}", 2000)
            elif act == act_del:
                self.core.remove_favorite(fav["id"])
                self.current_fav = None
                self._load_favorites()
        elif node_type == "pinned_leaf":
            pin = item.data(0, Qt.ItemDataRole.UserRole + 3) or {}
            p_name = str(pin.get("name", item.text(0))).strip()
            p_path = os.path.normpath(str(pin.get("path", ""))).replace("/", "\\")
            act_open = menu.addAction("打开所在文件夹")
            act_unpin = menu.addAction("取消置顶")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            _restore_prev_state_if_no_action(act)
            if act == act_open and p_path:
                self._open_folder_with_feedback(p_path)
            elif act == act_unpin:
                remover = getattr(self.core.config, "remove_pinned_project", None)
                if callable(remover):
                    remover(p_name, p_path)
                self._load_favorites()
                self.statusBar().showMessage(f"已取消置顶：{p_name}", 2000)
        elif node_type == "parent" and items:
            act_open = menu.addAction("打开所在文件夹")
            ref = self._get_item_ref_for_pin(item)
            act_pin = menu.addAction("添加到置顶（本组）")
            if ref and self._is_pinned(ref[0], ref[1]):
                act_pin.setEnabled(False)
            act_del = menu.addAction("删除整个项目")
            act = menu.exec(self.fav_tree.mapToGlobal(pos))
            _restore_prev_state_if_no_action(act)
            if act == act_open:
                self._open_folder_with_feedback(items[0]["full_path"])
            elif act == act_pin and ref:
                adder = getattr(self.core.config, "add_pinned_project", None)
                if callable(adder) and adder(ref[0], ref[1]):
                    self._load_favorites()
                    self.statusBar().showMessage(f"已置顶：{ref[0]}", 2000)
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
            if self.current_fav and self.current_fav.get("dir_type") == "explorer":
                base = os.path.normpath(self.current_fav["full_path"]).replace("/", "\\")
                self._build_explorer_folder_tree(base)
                pid = self.current_fav["id"]
                expanded = self.core.fs_expanded.get(pid, set())
                if expanded:
                    self._restore_expanded(expanded)
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
            self._schedule_restore_fs_view_state()

    def _is_under_program_aggregate(self, folder_path: str) -> bool:
        """路径是否位于当前收藏下「program」聚合的 06_programs / 09_validation 目录树内。"""
        if not self.current_fav or not folder_path:
            return False
        base = os.path.normpath(self.current_fav.get("full_path", "")).replace("/", "\\")
        if not base:
            return False
        fp = os.path.normpath(folder_path).replace("/", "\\")
        try:
            if not os.path.normcase(fp).startswith(os.path.normcase(base)):
                return False
        except Exception:
            return False
        for rel in ("06_programs", "09_validation"):
            prefix = os.path.normpath(os.path.join(base, rel)).replace("/", "\\")
            pfx = os.path.normcase(prefix)
            fpc = os.path.normcase(fp)
            if fpc == pfx or fpc.startswith(pfx + "\\"):
                return True
        return False

    def _is_under_validation_aggregate(self, folder_path: str) -> bool:
        """路径是否位于当前收藏下「program/validation」聚合目录树内（09_validation）。"""
        if not self.current_fav or not folder_path:
            return False
        base = os.path.normpath(self.current_fav.get("full_path", "")).replace("/", "\\")
        if not base:
            return False
        fp = os.path.normpath(folder_path).replace("/", "\\")
        try:
            if not os.path.normcase(fp).startswith(os.path.normcase(base)):
                return False
        except Exception:
            return False
        prefix = os.path.normpath(os.path.join(base, "09_validation")).replace("/", "\\")
        pfx = os.path.normcase(prefix)
        fpc = os.path.normcase(fp)
        return fpc == pfx or fpc.startswith(pfx + "\\")

    def _include_file_in_program_listing(self, parent_dir: str, file_path: str) -> bool:
        """program 聚合内过滤文件：
        - 06_programs：仅展示 .sas
        - 09_validation：展示 .sas + .xml
        其它目录保持原样。
        """
        if not self._is_under_program_aggregate(parent_dir):
            return True
        lower = str(file_path or "").lower()
        if self._is_under_validation_aggregate(parent_dir):
            return lower.endswith(".sas") or lower.endswith(".xml")
        return lower.endswith(".sas")

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
                        if not self._include_file_in_program_listing(path, p):
                            continue
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
        if path.lower().endswith(".sas") or self._saseg_is_dataset_file(path):
            selected = self.tree.selectedItems()
            sas_paths = []
            for it in selected:
                p = it.data(0, Qt.ItemDataRole.UserRole)
                t = it.data(1, Qt.ItemDataRole.UserRole)
                if p and t == "file" and (str(p).lower().endswith(".sas") or self._saseg_is_dataset_file(str(p))):
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
            base = os.path.basename(path).lower()
            if base == "define.xml" or "define" in base:
                success, err = self.core.open_file(path)
            else:
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

    @staticmethod
    def _saseg_is_dataset_file(path):
        """SAS 数据集文件类型。"""
        ext = os.path.splitext(path or "")[1].lower()
        return ext in (".sas7bdat", ".sas7bndx", ".sas7bcat", ".sd2", ".ssd01", ".sd7")

    def _saseg_move_click_sasapp_screen_fixed(self):
        """将鼠标移到固定屏幕坐标并左键单击一次，用于点开 SASApp（配合后续 UIA 展开）。"""
        try:
            x = int(self.SASEG_SASAPP_SCREEN_X)
            y = int(self.SASEG_SASAPP_SCREEN_Y)
            u32 = ctypes.windll.user32
            u32.SetCursorPos(x, y)
            time.sleep(0.08)
            u32.mouse_event(0x0002, 0, 0, 0, 0)
            u32.mouse_event(0x0004, 0, 0, 0, 0)
            time.sleep(0.12)
        except Exception:
            pass

    def _open_with_saseg(self, file_path):
        """.sas 程序：新开 EG → 固定坐标点击 SASApp → 树展开到路径并双击打开。
        数据集（.sas7bdat/.sas7bndx/.sas7bcat/.sd2）：直接调用 SEGuide 打开，不跑自动化。"""
        seguide_path = self.core._find_sas_eg() if hasattr(self, "core") else None
        if not seguide_path or not os.path.isfile(seguide_path):
            self.show_error("未找到 SAS Enterprise Guide，请确认已安装。")
            self.update_status("打开失败：未找到 SEGuide.exe")
            return
        paths = [file_path] if isinstance(file_path, str) else list(file_path)
        paths = [os.path.normpath(p).replace("/", "\\") for p in paths]
        for p in paths:
            if not os.path.exists(p):
                self.show_error(f"文件不存在: {p}")
                self.update_status("打开失败：文件不存在")
                return
        has_prog = any(str(p).lower().endswith(".sas") for p in paths)
        has_data = any(self._saseg_is_dataset_file(p) for p in paths)
        if has_data and has_prog:
            QMessageBox.warning(
                self,
                "打开方式",
                "请勿同时选中 SAS 程序（.sas）与数据集（.sas7bdat 等）。\n请分开选择后再用 SAS EG 打开。",
            )
            self.update_status("已取消：程序与数据集请分开打开")
            return
        if has_data and not has_prog:
            self.update_status("数据集：正在使用 SAS EG 打开…")
            def _open_data():
                try:
                    data_paths = [p for p in paths if self._saseg_is_dataset_file(p)]
                    if not data_paths:
                        QTimer.singleShot(0, lambda: self.show_error("未检测到可打开的数据集文件。"))
                        return
                    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                    # 一次启动并传入全部数据集，尽量让 SAS EG 在同一实例中加载。
                    subprocess.Popen([seguide_path] + data_paths, shell=False, creationflags=creationflags)
                    QTimer.singleShot(0, lambda: self.update_status(f"数据集：已提交 {len(data_paths)} 个文件到 SAS EG"))
                except Exception as e:
                    QTimer.singleShot(0, lambda: self.show_error(f"使用 SAS EG 打开数据集失败：{e}"))
            threading.Thread(target=_open_data, daemon=True).start()
            return
        if not any(str(p).lower().endswith(".sas") for p in paths):
            self.update_status("使用 SAS EG 直接打开…")
            self._open_with_saseg_fallback(seguide_path, paths)
            return
        self.update_status("正在通过 SAS EG 自动化打开 SAS 程序…")
        thread = threading.Thread(target=self._open_sas_eg_automation, args=(seguide_path, paths))
        thread.daemon = True
        thread.start()

    def _open_sas_eg_automation(self, seguide_path, paths):
        """后台线程：仅用于 .sas 程序 — 新开 EG → 屏幕固定点点击 SASApp → 树展开到路径 → 双击打开。
        数据集请在主线程走 _open_with_saseg_fallback，不会进入此函数。"""
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
            QTimer.singleShot(
                0,
                lambda: self.update_status(
                    f"点击 SASApp 位置 ({self.SASEG_SASAPP_SCREEN_X}, {self.SASEG_SASAPP_SCREEN_Y})…"
                ),
            )
            self._saseg_move_click_sasapp_screen_fixed()
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
                time.sleep(0.15)
                sasapp = server_item.child_window(title="SASApp", control_type="TreeItem")
                if not sasapp.exists():
                    sasapp = server_item.child_window(title_re=".*SASApp.*", control_type="TreeItem")
                if not sasapp.exists():
                    QTimer.singleShot(0, lambda: self.show_error("未找到 SASApp 节点。"))
                    self._open_with_saseg_fallback(seguide_path, paths)
                    return
                self._expand_single_node(sasapp, "SASApp")
                time.sleep(0.15)
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
                time.sleep(0.08)
                current = file_node
                if path_type == "projects":
                    for child in current.children():
                        try:
                            if "projects" in (child.window_text() or "").lower():
                                current = child
                                self._expand_single_node(current, "projects")
                                break
                        except Exception:
                            continue
                elif path_type in ("users_project", "users_unblinded", "users_projects"):
                    for child in current.children():
                        try:
                            if "users" in (child.window_text() or "").lower():
                                current = child
                                self._expand_single_node(current, "users")
                                break
                        except Exception:
                            continue
                time.sleep(0.06)
                # path_levels 已含 userid、projects/project/unblinded 及后续，统一由下方循环逐级展开
                for part in path_levels:
                    try:
                        current.click_input()
                        time.sleep(0.05)
                    except Exception:
                        pass
                    if not self._is_node_expanded(current):
                        self._expand_single_node(current, (current.window_text() or "当前节点"))
                    else:
                        time.sleep(0.05)
                    found = False
                    for child in current.children():
                        try:
                            t = (child.window_text() or "").strip()
                            if t == part or t.lower() == part.lower():
                                current = child
                                current.ensure_visible()
                                time.sleep(0.05)
                                if not self._is_node_expanded(current):
                                    self._expand_single_node(current, part)
                                else:
                                    time.sleep(0.05)
                                found = True
                                break
                        except Exception:
                            continue
                    if not found:
                        QTimer.singleShot(0, lambda: self.update_status(f"无法找到文件夹节点: {part}，已改为直接传参打开"))
                        self._open_with_saseg_fallback(seguide_path, paths)
                        return
                current.click_input()
                time.sleep(0.12)
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
        """根据 Z 盘路径段识别 path_type 及展开用的 path_levels。
        支持：projects；users/project、users/unblinded、users/projects；
        users/<userid>/project、users/<userid>/unblinded、users/<userid>/projects。"""
        if not folder_parts:
            return "projects", []
        lower_parts = [p.lower() for p in folder_parts]
        if lower_parts[0] == "projects":
            return "projects", folder_parts[1:]
        if lower_parts[0] != "users":
            return "projects", folder_parts
        # users 下：users/<userid>/projects 或 users/projects（path_levels 含 userid+projects 或 projects+后续）
        if len(lower_parts) >= 3 and lower_parts[2] == "projects":
            path_levels = [folder_parts[1], folder_parts[2]] + folder_parts[3:]
            print(f"[SAS EG] 路径类型: users_projects, 展开层级: {path_levels}")
            return "users_projects", path_levels
        if len(lower_parts) >= 2 and lower_parts[1] == "projects":
            path_levels = [folder_parts[1]] + folder_parts[2:]
            print(f"[SAS EG] 路径类型: users_projects, 展开层级: {path_levels}")
            return "users_projects", path_levels
        # users/<userid>/project、users/<userid>/unblinded（树结构为 users→userid→project|unblinded→…）
        if len(lower_parts) >= 3 and lower_parts[2] in ("project", "unblinded"):
            path_type = "users_project" if lower_parts[2] == "project" else "users_unblinded"
            path_levels = [folder_parts[1], folder_parts[2]] + folder_parts[3:]
            print(f"[SAS EG] 路径类型: {path_type}, 展开层级: {path_levels}")
            return path_type, path_levels
        if len(lower_parts) >= 2 and lower_parts[1] in ("project", "unblinded"):
            path_type = "users_project" if lower_parts[1] == "project" else "users_unblinded"
            path_levels = [folder_parts[1]] + folder_parts[2:]
            print(f"[SAS EG] 路径类型: {path_type}, 展开层级: {path_levels}")
            return path_type, path_levels
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

    def _is_node_expanded(self, node):
        """检测树节点是否已展开，避免重复等待/展开。"""
        try:
            props = getattr(node, "get_properties", None)
            if props and callable(props):
                d = props()
                if isinstance(d, dict) and d.get("ExpandState") == 1:
                    return True
        except Exception:
            pass
        try:
            if getattr(node, "is_expanded", None) and callable(node.is_expanded):
                return node.is_expanded()
        except Exception:
            pass
        try:
            ch = node.children()
            return len(ch) > 0
        except Exception:
            pass
        return False

    def _expand_single_node(self, node, node_name):
        """展开单个树节点：已展开则跳过；仅控件检测+最短超时（≤1s），无固定 sleep；失败重试 1 次。"""
        if not getattr(node, "exists", lambda: True)():
            raise RuntimeError(f"节点「{node_name}」不存在")
        try:
            node.ensure_visible()
        except Exception:
            pass
        if self._is_node_expanded(node):
            return
        poll_interval = 0.04
        timeout = self.NODE_EXPAND_TIMEOUT

        def _do_expand():
            try:
                if getattr(node, "expand", None) and callable(node.expand):
                    node.expand()
            except Exception:
                pass
            start = time.time()
            while time.time() - start < timeout:
                if self._is_node_expanded(node):
                    return True
                time.sleep(poll_interval)
            if self._is_node_expanded(node):
                return True
            try:
                node.click_input(button="left")
                if getattr(node, "expand", None) and callable(node.expand):
                    node.expand()
            except Exception:
                pass
            start = time.time()
            while time.time() - start < timeout:
                if self._is_node_expanded(node):
                    return True
                time.sleep(poll_interval)
            if self._is_node_expanded(node):
                return True
            try:
                node.double_click_input()
            except Exception:
                pass
            time.sleep(poll_interval * 2)
            return bool(self._is_node_expanded(node))

        if _do_expand():
            return
        # 重试 1 次
        if _do_expand():
            return
        raise RuntimeError(f"节点「{node_name}」展开超时（已重试），可改为手动在 SAS EG 中展开。")

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
        time.sleep(0.02)
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
        time.sleep(0.02)
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
        time.sleep(0.02)
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
        elif path_type in ("users_project", "users_unblinded", "users_projects"):
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
        time.sleep(0.02)

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
            time.sleep(0.02)
        current_node.click_input()
        time.sleep(0.05)
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
        # 选中项（用于“打开选中文件”）
        selected_items = self.tree.selectedItems()
        selected_files = []
        for it in selected_items:
            p = it.data(0, Qt.ItemDataRole.UserRole)
            t = it.data(1, Qt.ItemDataRole.UserRole)
            if p and t == "file" and isinstance(p, str) and os.path.isfile(p):
                p = os.path.normpath(p).replace("/", "\\")
                if p not in selected_files:
                    selected_files.append(p)

        is_file = (typ == "file" and os.path.isfile(path))
        # 只要节点绑定的是可访问目录（且非 file），都视为文件夹节点，包含 docs_root/folder_aggregate 等聚合节点
        is_folder = (typ != "file" and path and os.path.isdir(path))
        lower_path = path.lower()
        is_pdf = lower_path.endswith(".pdf")
        is_sas_code = lower_path.endswith(".sas")
        is_sas_dataset = self._saseg_is_dataset_file(lower_path)
        is_sas = is_sas_code or is_sas_dataset
        is_ps1 = lower_path.endswith(".ps1")
        code_exts = {
            ".py", ".r", ".sas", ".sql", ".js", ".jsx", ".ts", ".tsx",
            ".java", ".cpp", ".c", ".h", ".hpp", ".cs", ".go", ".rs", ".php",
            ".rb", ".swift", ".kt", ".scala", ".json", ".yaml", ".yml", ".xml",
            ".toml", ".ini", ".cfg", ".bat", ".cmd", ".ps1", ".sh", ".md",
        }
        file_ext = os.path.splitext(lower_path)[1]
        is_code_file = is_file and file_ext in code_exts

        act_open_selected = act_sas_eg = act_open_vscode = act_ps1_run = None
        act_adobe = act_browser = None
        act_default_eg = act_default_vscode = None
        act_open_folder = act_copy_path = act_copy_names = act_copy_files = None
        act_paste = act_rename_file = act_delete_files = None
        act_refresh_folder = act_sort_by_time = None

        # 第 1 组：打开操作类
        group1_has_item = False
        if len(selected_files) >= 2:
            act_open_selected = menu.addAction("打开选中文件")
            group1_has_item = True
        elif is_file:
            act_open_selected = menu.addAction("打开文件")
            group1_has_item = True
        if is_sas:
            act_sas_eg = menu.addAction("用 SAS EG 打开")
            group1_has_item = True
        if is_code_file and not is_sas_dataset:
            act_open_vscode = menu.addAction("用 VS Code 打开")
            group1_has_item = True
        if is_ps1:
            act_ps1_run = menu.addAction("用 PowerShell 运行")
            group1_has_item = True
        if is_pdf:
            act_adobe = menu.addAction("用 Adobe Acrobat 打开")
            act_browser = menu.addAction("用浏览器打开")
            group1_has_item = True
        if is_folder:
            act_open_folder = menu.addAction("打开所在文件夹")
            act_open_folder.setData((path, typ))
            group1_has_item = True
        if is_sas_code or (is_code_file and not is_sas_dataset):
            sub_default = menu.addMenu("设置默认打开方式")
            act_default_eg = sub_default.addAction("SAS EG")
            act_default_vscode = sub_default.addAction("VS Code")
            group1_has_item = True

        # 第 2 组：复制/路径类
        act_copy_path = menu.addAction("复制路径")
        act_copy_names = menu.addAction("复制文件名")
        act_copy_files = menu.addAction("复制选中文件")
        group2_has_item = True

        # 第 3 组：删除/修改类（末尾）
        target_dir = path if os.path.isdir(path) else os.path.dirname(path)
        if target_dir and os.path.isdir(target_dir) and self._check_clipboard_has_files():
            act_paste = menu.addAction("粘贴")
            act_paste.setData(target_dir)
        if is_file:
            act_rename_file = menu.addAction("重命名")
            act_delete_files = menu.addAction("删除选中文件")
        if is_folder:
            act_refresh_folder = menu.addAction("刷新")
            act_refresh_folder.setData(path)
            act_sort_by_time = menu.addAction("按时间排序查看文件")
            act_sort_by_time.setData(path)
        group3_has_item = any([act_paste, act_rename_file, act_delete_files, act_refresh_folder, act_sort_by_time])

        # 分组分隔线（仅在相邻分组均有项时显示）
        if group1_has_item and group2_has_item:
            menu.insertSeparator(act_copy_path)
        if group2_has_item and group3_has_item:
            first_group3 = next((a for a in [act_paste, act_rename_file, act_delete_files, act_refresh_folder, act_sort_by_time] if a), None)
            if first_group3:
                menu.insertSeparator(first_group3)

        act = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if act_open_selected and act == act_open_selected:
            # 若是多选：逐个按系统默认方式打开；若是单选：按双击逻辑打开
            if len(selected_files) >= 2:
                ok_count = 0
                fail = []
                for p in selected_files:
                    ok, err = self.core.open_file(p)
                    if ok:
                        ok_count += 1
                    else:
                        fail.append(f"{os.path.basename(p)}: {err}")
                if ok_count:
                    self.statusBar().showMessage(f"已打开 {ok_count} 个文件", 3000)
                if fail:
                    QMessageBox.warning(
                        self,
                        "部分文件打开失败",
                        "\n".join(fail[:20]) + (f"\n... 共 {len(fail)} 条" if len(fail) > 20 else ""),
                    )
            else:
                # 单文件：复用双击处理（包含 sas/pdf/xml 的特殊逻辑）
                self._on_tree_double(item, 0)
        elif act_open_folder and act == act_open_folder:
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
        elif act == act_copy_names:
            sel = self.tree.selectedItems()
            names = []
            for it in sel:
                p = it.data(0, Qt.ItemDataRole.UserRole)
                if not p or not isinstance(p, str):
                    continue
                p = os.path.normpath(p).replace("/", "\\")
                name = os.path.basename(p.rstrip("\\"))
                if name and name not in names:
                    names.append(name)
            if not names and path:
                names = [os.path.basename(path.rstrip("\\"))] if os.path.basename(path.rstrip("\\")) else []
            if not names:
                QMessageBox.information(self, "提示", "未找到可复制的文件名。")
            else:
                clipboard = QGuiApplication.clipboard()
                clipboard.setText("\n".join(names))
                self.statusBar().showMessage(f"已复制 {len(names)} 个文件名", 2000)
        elif act == act_copy_files:
            self._copy_selected_files()
        elif act_rename_file and act == act_rename_file:
            self._rename_file(path)
        elif act_delete_files and act == act_delete_files:
            self._delete_selected_files()
        elif act_paste and act == act_paste:
            self._paste_files_to_folder(act_paste.data())
        elif act_refresh_folder and act == act_refresh_folder:
            self._refresh_folder_node(act_refresh_folder.data(), item)
        elif act_sort_by_time and act == act_sort_by_time:
            folder = act_sort_by_time.data()
            if folder and os.path.isdir(folder):
                self._sort_folder_files_by_mtime(folder, item)
        elif is_ps1 and act == act_ps1_run:
            self._run_ps1_file(path)
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
        elif act_open_vscode and act == act_open_vscode:
            if is_sas_code:
                selected = self.tree.selectedItems()
                sas_paths = [path]
                for it in selected:
                    p = it.data(0, Qt.ItemDataRole.UserRole)
                    t = it.data(1, Qt.ItemDataRole.UserRole)
                    if p and t == "file" and str(p).lower().endswith(".sas"):
                        p = os.path.normpath(p).replace("/", "\\")
                        if p not in sas_paths and os.path.exists(p):
                            sas_paths.append(p)
                ok, err = self.core.open_sas_with(sas_paths, "vscode")
                if ok:
                    self.statusBar().showMessage(f"正在打开 {len(sas_paths)} 个文件", 3000)
                else:
                    QMessageBox.critical(self, "打开失败", err)
            else:
                ok, err = self.core.open_sas_with([path], "vscode")
                if ok:
                    self.statusBar().showMessage(f"正在用 VS Code 打开 {os.path.basename(path)}", 3000)
                else:
                    QMessageBox.critical(self, "打开失败", err)
        elif is_sas and act == act_sas_eg:
            selected = self.tree.selectedItems()
            sas_paths = [path]
            for it in selected:
                p = it.data(0, Qt.ItemDataRole.UserRole)
                t = it.data(1, Qt.ItemDataRole.UserRole)
                if p and t == "file" and (str(p).lower().endswith(".sas") or self._saseg_is_dataset_file(str(p))):
                    p = os.path.normpath(p).replace("/", "\\")
                    if p not in sas_paths and os.path.exists(p):
                        sas_paths.append(p)
            self._open_with_saseg(sas_paths)
        elif is_sas and act == act_default_eg:
            self.core.config.set_sas_open(default_app="sas_eg")
            self.statusBar().showMessage("默认打开方式已设为 SAS EG，生效于本次及之后打开", 3000)
        elif act_default_eg and act == act_default_eg and not is_sas:
            QMessageBox.information(self, "提示", "当前默认打开方式仅支持 .sas/.sas7bdat 文件。")
        elif act_default_vscode and act == act_default_vscode:
            self.core.config.set_sas_open(default_app="vscode")
            self.statusBar().showMessage("默认打开方式已设为 VS Code，生效于本次及之后打开", 3000)

    def _set_clipboard_files_win(self, file_paths):
        """将文件路径以 CF_HDROP 格式写入系统剪贴板，使资源管理器或本工具中「粘贴」可复制文件。仅 Windows。"""
        if sys.platform != "win32" or not file_paths:
            return False
        # DROPFILES: pFiles(4) pt(8) fNC(4) fWide(4)=20 字节，其后为以双字节 null 结尾的 UTF-16LE 路径列表
        CF_HDROP = 15
        GMEM_MOVEABLE = 0x0002
        paths_utf16 = []
        for p in file_paths:
            p = os.path.normpath(p).replace("/", "\\")
            paths_utf16.append(p.encode("utf-16-le") + b"\x00\x00")
        block = b"".join(paths_utf16) + b"\x00\x00"
        drop_offset = 20
        size = drop_offset + len(block)
        header = struct.pack("IllII", drop_offset, 0, 0, 0, 1)
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            return False
        try:
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                return False
            buf = (ctypes.c_char * size).from_address(ptr)
            ctypes.memmove(buf, header, drop_offset)
            ctypes.memmove(ctypes.byref(buf, drop_offset), block, len(block))
            kernel32.GlobalUnlock(h)
            if not user32.OpenClipboard(None):
                return False
            try:
                user32.EmptyClipboard()
                user32.SetClipboardData(CF_HDROP, h)
                return True
            finally:
                user32.CloseClipboard()
        except Exception:
            try:
                kernel32.GlobalFree(h)
            except Exception:
                pass
            return False

    def _copy_selected_files(self):
        """将选中的文件写入系统剪贴板，可在本工具选中文件夹后粘贴或资源管理器中粘贴以复制文件。"""
        selected = self.tree.selectedItems()
        file_paths = []
        for it in selected:
            p = it.data(0, Qt.ItemDataRole.UserRole)
            t = it.data(1, Qt.ItemDataRole.UserRole)
            if p and t == "file" and isinstance(p, str) and os.path.isfile(p):
                p = os.path.normpath(p).replace("/", "\\")
                if p not in file_paths:
                    file_paths.append(p)
        if not file_paths:
            QMessageBox.warning(self, "提示", "请先选中要复制的文件（可按住 Ctrl 多选）。")
            return
        if sys.platform == "win32":
            ok = False
            try:
                md = QMimeData()
                md.setUrls([QUrl.fromLocalFile(p) for p in file_paths])
                QGuiApplication.clipboard().setMimeData(md)
                ok = True
            except Exception:
                ok = False
            if not ok and self._set_clipboard_files_win(file_paths):
                ok = True
            if ok:
                self.statusBar().showMessage(
                    f"已复制 {len(file_paths)} 个文件到剪贴板，可在资源管理器/桌面等位置粘贴（Ctrl+V）",
                    4000,
                )
            else:
                clipboard = QGuiApplication.clipboard()
                clipboard.setText("\n".join(file_paths))
                self.statusBar().showMessage(f"已将 {len(file_paths)} 个文件路径写入剪贴板（文本）", 4000)
        else:
            clipboard = QGuiApplication.clipboard()
            clipboard.setText("\n".join(file_paths))
            self.statusBar().showMessage(f"已将 {len(file_paths)} 个文件路径写入剪贴板", 4000)

    def _check_clipboard_has_files(self):
        """仅当剪贴板中解析出至少 1 个有效文件路径时返回 True；决定是否显示「粘贴」。
        支持两种来源：CF_HDROP（优先）或文本中的文件路径。"""
        paths = self._get_clipboard_file_paths()
        return len(paths) > 0

    def _get_clipboard_file_paths(self):
        """从系统剪贴板读取待粘贴的文件路径列表。Windows 下优先解析 CF_HDROP，否则用剪贴板文本。"""
        paths = []
        if sys.platform == "win32":
            paths = self._get_clipboard_file_paths_win()
        if not paths:
            clipboard = QGuiApplication.clipboard()
            md = clipboard.mimeData()
            if md and md.hasUrls():
                for u in md.urls():
                    if u.isLocalFile():
                        p = os.path.normpath(u.toLocalFile()).replace("/", "\\")
                        if os.path.isfile(p) and p not in paths:
                            paths.append(p)
        if not paths:
            clipboard = QGuiApplication.clipboard()
            text = (clipboard.text() or "").strip()
            for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
                p = line.strip().strip('"')
                if p and os.path.isfile(p):
                    p = os.path.normpath(p).replace("/", "\\")
                    if p not in paths:
                        paths.append(p)
        return paths

    def _get_clipboard_file_paths_win(self):
        """从 Windows 剪贴板 CF_HDROP 读取文件路径列表。"""
        if sys.platform != "win32":
            return []
        CF_HDROP = 15
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(None):
            return []
        try:
            h = user32.GetClipboardData(CF_HDROP)
            if not h:
                return []
            ptr = kernel32.GlobalLock(h)
            if not ptr:
                return []
            try:
                drop_offset = struct.unpack_from("I", ctypes.string_at(ptr, 4), 0)[0]
                f_wide = struct.unpack_from("I", ctypes.string_at(ptr, 24), 16)[0]
                data = ctypes.string_at(ptr + drop_offset)
                kernel32.GlobalUnlock(h)
            except Exception:
                kernel32.GlobalUnlock(h)
                return []
            if not data:
                return []
            paths = []
            if f_wide:
                pos = 0
                while pos < len(data) - 1:
                    end = data.find(b"\x00\x00", pos)
                    if end == -1:
                        break
                    chunk = data[pos:end]
                    pos = end + 2
                    if chunk:
                        try:
                            s = chunk.decode("utf-16-le")
                            if s and os.path.isfile(s):
                                s = os.path.normpath(s).replace("/", "\\")
                                if s not in paths:
                                    paths.append(s)
                        except Exception:
                            pass
            return paths
        finally:
            user32.CloseClipboard()

    def _paste_files_to_folder(self, target_dir):
        """将剪贴板中的文件粘贴（复制）到 target_dir，同名自动加数字后缀，完成后刷新右侧树。"""
        target_dir = os.path.normpath(target_dir).replace("/", "\\")
        if not os.path.isdir(target_dir):
            QMessageBox.warning(self, "提示", "目标不是有效文件夹。")
            return
        paths = self._get_clipboard_file_paths()
        if not paths:
            QMessageBox.information(self, "提示", "剪贴板中没有可粘贴的文件。请先用「复制选中文件」复制文件。")
            return
        success = 0
        fail_list = []
        for src in paths:
            try:
                name = os.path.basename(src)
                dest = os.path.join(target_dir, name)
                if os.path.exists(dest):
                    base, ext = os.path.splitext(name)
                    n = 1
                    while os.path.exists(os.path.join(target_dir, f"{base}_{n}{ext}")):
                        n += 1
                    dest = os.path.join(target_dir, f"{base}_{n}{ext}")
                shutil.copy2(src, dest)
                success += 1
            except Exception as e:
                fail_list.append(f"{os.path.basename(src)}: {e}")
        msg = f"粘贴完成。成功：{success} 个" + (f"，失败：{len(fail_list)} 个" if fail_list else "。")
        if fail_list:
            msg += "\n失败：\n" + "\n".join(fail_list[:15])
            if len(fail_list) > 15:
                msg += f"\n…共 {len(fail_list)} 个"
        self.statusBar().showMessage(msg, 5000)
        QMessageBox.information(self, "粘贴结果", msg)
        if success > 0 and self.current_fav:
            self._refresh_tree()

    def _delete_selected_files(self):
        """删除右侧文件树中选中的文件（仅 file 类型），操作前确认，删除后刷新当前项目。"""
        selected = self.tree.selectedItems()
        file_paths = []
        for it in selected:
            p = it.data(0, Qt.ItemDataRole.UserRole)
            t = it.data(1, Qt.ItemDataRole.UserRole)
            if p and t == "file" and isinstance(p, str):
                p = os.path.normpath(p).replace("/", "\\")
                if p not in file_paths and os.path.isfile(p):
                    file_paths.append(p)
        if not file_paths:
            QMessageBox.information(self, "提示", "请选择要删除的文件（仅支持删除文件，不删除文件夹）。")
            return
        names_preview = "\n".join(os.path.basename(p) for p in file_paths[:10])
        if len(file_paths) > 10:
            names_preview += f"\n… 共 {len(file_paths)} 个文件"
        r = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除以下文件吗？\n\n{names_preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        success = 0
        failed = []
        for p in file_paths:
            try:
                os.remove(p)
                success += 1
            except Exception as e:
                failed.append(f"{os.path.basename(p)}: {e}")
        msg = f"删除完成。成功：{success} 个" + (f"，失败：{len(failed)} 个" if failed else "。")
        if failed:
            msg += "\n失败：\n" + "\n".join(failed[:15])
        self.statusBar().showMessage(msg, 5000)
        QMessageBox.information(self, "删除结果", msg)
        if self.current_fav:
            self._refresh_tree()

    def _rename_file(self, file_path):
        """重命名单个文件并刷新当前项目树。"""
        file_path = os.path.normpath(file_path).replace("/", "\\")
        if not os.path.isfile(file_path):
            QMessageBox.information(self, "提示", "仅支持重命名文件。")
            return
        old_name = os.path.basename(file_path)
        new_name, ok = QInputDialog.getText(self, "重命名文件", "请输入新文件名：", text=old_name)
        if not ok:
            return
        new_name = (new_name or "").strip()
        if not new_name:
            QMessageBox.warning(self, "提示", "文件名不能为空。")
            return
        if new_name == old_name:
            return
        invalid_chars = set('<>:"/\\|?*')
        if any(ch in invalid_chars for ch in new_name):
            QMessageBox.warning(self, "提示", "文件名包含非法字符：<>:\"/\\|?*")
            return
        new_path = os.path.join(os.path.dirname(file_path), new_name)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "提示", "目标文件名已存在，请更换名称。")
            return
        try:
            os.rename(file_path, new_path)
            self.statusBar().showMessage(f"已重命名为：{new_name}", 3000)
            if self.current_fav:
                self._refresh_tree()
        except Exception as e:
            QMessageBox.critical(self, "重命名失败", str(e))

    def _run_ps1_file(self, path):
        """用 PowerShell 执行 .ps1 文件：弹出控制台窗口，执行后窗口保持打开（-NoExit），便于查看结果与错误。"""
        path = os.path.normpath(path).replace("/", "\\")
        if not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "脚本文件不存在或无法访问。")
            return
        name = os.path.basename(path)
        try:
            subprocess.Popen(
                [
                    "powershell.exe",
                    "-NoExit",
                    "-File", path,
                ],
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0,
                cwd=os.path.dirname(path),
            )
            self.statusBar().showMessage(f"已启动 PowerShell 窗口运行：{name}", 3000)
        except FileNotFoundError:
            QMessageBox.warning(self, "PowerShell 运行", "未找到 PowerShell，请确认系统已安装 PowerShell。")
        except PermissionError:
            QMessageBox.warning(self, "PowerShell 运行", "权限不足，请尝试以管理员身份运行本程序或 PowerShell。")
        except Exception as e:
            QMessageBox.warning(self, "PowerShell 运行", f"启动失败：{e}")

    def _refresh_folder_node(self, folder_path, item):
        """刷新文件夹节点：清空子节点、显示加载中、后台扫描后更新树。"""
        folder_path = os.path.normpath(folder_path).replace("/", "\\")
        if not os.path.isdir(folder_path):
            QMessageBox.warning(self, "提示", "目标不是有效文件夹或无法访问。")
            return
        is_docs_root = (item.data(1, Qt.ItemDataRole.UserRole) == "docs_root")
        while item.childCount():
            item.removeChild(item.child(0))
        loading = QTreeWidgetItem(["加载中…", ""])
        loading.setData(0, Qt.ItemDataRole.UserRole, None)
        item.addChild(loading)
        item.setExpanded(True)

        def scan():
            try:
                names = sorted(os.listdir(folder_path))
                err = None
            except Exception as e:
                names = []
                err = str(e)
            result = []
            for n in names:
                p = os.path.join(folder_path, n)
                try:
                    is_dir = os.path.isdir(p)
                except Exception:
                    continue
                # Documents 节点刷新：仅展示全部 xlsx 文件（不展示其它后缀与子目录）。
                if is_docs_root:
                    if is_dir or not n.lower().endswith(".xlsx"):
                        continue
                    result.append((n, p, False))
                    continue
                if not is_dir and not self._include_file_in_program_listing(folder_path, p):
                    continue
                result.append((n, p, is_dir))
            # 后台线程不能用 QTimer.singleShot(0, ...) 更新 UI（线程无事件循环），用 signal 回主线程
            try:
                self.refresh_folder_done.emit(item, err, result)
            except Exception:
                pass

        threading.Thread(target=scan, daemon=True).start()

    def _sort_folder_files_by_mtime(self, folder_path, item):
        """将文件夹下的文件按修改时间倒序重新展示，并保留原有子文件夹节点位置不变。"""
        folder_path = os.path.normpath(folder_path).replace("/", "\\")
        if not os.path.isdir(folder_path):
            QMessageBox.warning(self, "提示", "目标不是有效文件夹或无法访问。")
            return
        # 先保留当前节点下的子文件夹节点（保持原始顺序/展开状态）
        preserved_dirs = []
        try:
            for i in range(item.childCount()):
                ch = item.child(i)
                p = ch.data(0, Qt.ItemDataRole.UserRole)
                t = ch.data(1, Qt.ItemDataRole.UserRole)
                if p and isinstance(p, str) and (t in ("dir", "ok", "unavailable")) and os.path.isdir(p):
                    preserved_dirs.append(ch.clone())
        except Exception:
            preserved_dirs = []
        # 扫描文件
        try:
            entries = []
            for n in os.listdir(folder_path):
                p = os.path.join(folder_path, n)
                if os.path.isfile(p):
                    if not self._include_file_in_program_listing(folder_path, p):
                        continue
                    try:
                        m = os.path.getmtime(p)
                    except Exception:
                        m = 0
                    entries.append((m, n, p))
        except Exception as e:
            QMessageBox.warning(self, "按时间排序", f"读取失败：{e}")
            return
        # 按时间倒序
        entries.sort(key=lambda x: x[0], reverse=True)
        # 重建子项：先恢复子文件夹，再追加排序后的文件
        while item.childCount():
            item.removeChild(item.child(0))
        for d in preserved_dirs:
            item.addChild(d)
        for m, n, p in entries:
            name = _strip_prefix(n)
            mtime = _mtime_str(p)
            c = QTreeWidgetItem([name, mtime])
            c.setData(0, Qt.ItemDataRole.UserRole, p)
            c.setData(1, Qt.ItemDataRole.UserRole, "file")
            c.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            c.setToolTip(0, p)
            c.setIcon(0, icon_for_file_soft(p, 14))
            item.addChild(c)
        item.setExpanded(True)
        self.statusBar().showMessage("已按时间排序（最新在前）", 2000)

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


class _ProductDirIndexRunnable(QRunnable):
    """后台枚举 Z 盘产品级目录，避免阻塞「添加项目」对话框打开。"""

    def __init__(self, dlg: "ProjectSelector"):
        super().__init__()
        self._dlg = dlg

    def run(self):
        try:
            rows = _pfn_enumerate_z_product_directories()
        except Exception:
            rows = []
        try:
            self._dlg.product_index_ready.emit(rows)
        except Exception:
            pass


class ProjectSelector(QDialog):
    """添加项目对话框：支持多选子目录，自动归类为 产品→试验→子目录。
    搜索下拉仅展示产品目录；索引在首次输入搜索时于后台构建；回车/点击定位到树中对应产品节点。"""

    product_index_ready = pyqtSignal(object)

    def __init__(self, parent, core: PFNCore):
        super().__init__(parent)
        self.core = core
        self._disk_search_built = False
        self._disk_search_rows = []
        self._disk_index_worker_running = False
        self.product_index_ready.connect(self._on_product_disk_index_ready)
        self.setWindowTitle("选择要添加的项目/子目录")
        self.resize(800, 600)
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        # 顶部搜索栏 + 扁平下拉（与左侧收藏库一致）
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("按产品名搜索（projects/users/unblinded）；首次搜索后台建索引，回车定位")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setFixedHeight(26)
        self.search_edit.setStyleSheet(
            "QLineEdit{border:1px solid #D0D3D8; border-radius:4px; padding:2px 8px; font-size:11px;}"
            "QLineEdit:focus{border-color:#165DFF;}"
        )
        layout.addWidget(self.search_edit)

        self.search_list = QListWidget(self)
        self.search_list.setWindowFlags(Qt.WindowType.SubWindow)
        self.search_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.search_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.search_list.setMaximumHeight(8 * 25)
        self.search_list.setUniformItemSizes(True)
        self.search_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.search_list.setStyleSheet(
            "QListWidget{background:rgba(255,255,255,217); border:1px solid #D0D3D8; font-size:9px; outline:none;}"
            "QListWidget::item{padding:2px 6px; border:none; outline:none;}"
            "QListWidget::item:focus, QListWidget::item:hover{outline:none; border:none;}"
            "QListWidget::item:selected{background:#E8F3FF; color:#165DFF; outline:none; border:none;}"
            "QScrollBar:vertical{width:8px;}"
        )
        self.search_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if self.search_list.viewport():
            self.search_list.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.search_list.hide()

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

        self._search_index = []
        self.search_edit.textChanged.connect(self._on_search_changed)
        self.search_edit.installEventFilter(self)
        self.search_list.itemClicked.connect(self._on_search_item_clicked)
        self._rebuild_search_index()

    def _normalize_search_text(self, s: str) -> str:
        s = (s or "").strip().lower()
        return re.sub(r"[\s_\-\\/]+", "", s)

    def _maybe_start_product_index_async(self):
        """首次需要全盘产品列表时在后台线程枚举，避免卡 UI。"""
        if self._disk_search_built or self._disk_index_worker_running:
            return
        self._disk_index_worker_running = True
        QThreadPool.globalInstance().start(_ProductDirIndexRunnable(self))

    def _on_product_disk_index_ready(self, rows):
        self._disk_index_worker_running = False
        try:
            self._disk_search_rows = list(rows or [])
            self._disk_search_built = True
            self._rebuild_search_index()
            txt = self.search_edit.text().strip()
            if txt:
                self._on_search_changed(txt)
        except RuntimeError:
            return

    def _rebuild_search_index(self):
        """仅索引「产品」级目录：已就绪的磁盘枚举结果 + 当前树中路径为产品层的节点。"""
        by_path = {}
        if getattr(self, "_disk_search_built", False):
            for flat, p in getattr(self, "_disk_search_rows", []):
                pn = os.path.normpath(str(p)).replace("/", "\\")
                by_path[pn.lower()] = (flat, pn, None)

        out = []

        def flat_path_for_item(it: QTreeWidgetItem) -> str:
            parts = []
            cur = it
            while cur is not None:
                t = (cur.text(0) or "").strip()
                if t:
                    parts.insert(0, t)
                cur = cur.parent()
            return "/".join(parts)

        def walk(it: QTreeWidgetItem):
            p = it.data(0, Qt.ItemDataRole.UserRole)
            if p:
                pn = os.path.normpath(str(p)).replace("/", "\\")
                if _pfn_is_z_product_directory(pn):
                    out.append((flat_path_for_item(it), pn, it))
            for i in range(it.childCount()):
                walk(it.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        for flat, pn, it in out:
            by_path[pn.lower()] = (flat, pn, it)
        self._search_index = sorted(by_path.values(), key=lambda x: (x[0].lower(), x[1].lower()))

    def _scroll_tree_to_path(self, target_path: str):
        """按路径逐级展开懒加载树并选中目标节点（用于仅来自磁盘索引的搜索结果）。"""
        target_path = os.path.normpath(target_path or "").replace("/", "\\")
        parts = _pfn_z_rel_parts(target_path)
        if not parts:
            return None
        item = None
        root_want = parts[0].lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if (top.text(0) or "").strip().lower() == root_want:
                item = top
                break
        if item is None:
            return None
        for seg in parts[1:]:
            self.tree.expandItem(item)
            self._on_expand(item)
            found = None
            seg_l = (seg or "").strip().lower()
            for j in range(item.childCount()):
                ch = item.child(j)
                if (ch.text(0) or "").strip().lower() == seg_l:
                    found = ch
                    break
            if found is None:
                return None
            item = found
        self.tree.setCurrentItem(item)
        self.tree.scrollToItem(item)
        return item

    def _position_search_list(self):
        x = self.search_edit.x()
        y = self.search_edit.y() + self.search_edit.height()
        w = self.search_edit.width()
        rows = min(self.search_list.count(), 8)
        h = max(1, rows) * 25 + 2
        self.search_list.setGeometry(x, y, w, h)
        self.search_list.raise_()

    def _hide_search_list(self):
        if self.search_list.isVisible():
            self.search_list.hide()

    def _search_match_rank(self, q_norm: str, q_raw: str, path: str, flat: str) -> tuple:
        """下拉仅含产品目录：0=产品文件夹名命中，1=整条相对路径规范化命中，2=弱命中（仅规范化串、原文无子串）。"""
        display = os.path.basename((path or "").rstrip("\\"))
        nb = self._normalize_search_text(display)
        nf = self._normalize_search_text(flat or "")
        tier = 2
        if q_norm and q_norm in nb:
            tier = 0
        elif q_norm in nf:
            tier = 1
        if tier >= 1 and q_raw:
            pl = (path or "").lower()
            fl = (flat or "").lower()
            dl = display.lower()
            if q_raw not in pl and q_raw not in fl and q_raw not in dl:
                tier = 2
        return (tier, display.lower())

    def _on_search_changed(self, text: str):
        q = self._normalize_search_text(text)
        if not q:
            self.search_list.clear()
            self._hide_search_list()
            return
        self._maybe_start_product_index_async()
        if not self._search_index:
            self._rebuild_search_index()
        matches = []
        for flat, p, it in self._search_index:
            base = os.path.basename((p or "").rstrip("\\"))
            nflat = self._normalize_search_text(flat)
            nbase = self._normalize_search_text(base)
            if q not in nflat and q not in nbase:
                continue
            matches.append((flat, p, it))
        self.search_list.clear()
        if not matches:
            self._hide_search_list()
            return
        q_raw = (text or "").strip().lower()

        def _sort_key(row):
            tier_t = self._search_match_rank(q, q_raw, row[1], row[0])
            _, _, sk = _pfn_product_search_source_meta(row[1])
            return (tier_t[0], sk, tier_t[1])

        matches.sort(key=_sort_key)
        matches = matches[:200]
        for flat, p, it_ref in matches:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, {"path": p, "tree_item": it_ref})
            display = os.path.basename((p or "").rstrip("\\"))
            badge, src_extra, _ = _pfn_product_search_source_meta(p)
            src = display
            idx = src.lower().find(q_raw) if q_raw else -1
            if idx < 0 and q_raw:
                src = flat
                idx = src.lower().find(q_raw) if q_raw else -1
            if idx >= 0 and q_raw:
                before = html.escape(src[:idx])
                mid = html.escape(src[idx : idx + len(q_raw)])
                after = html.escape(src[idx + len(q_raw) :])
                rich = f"{before}<span style='color:#FF4444;'>{mid}</span>{after}"
            else:
                rich = html.escape(display)
            tip_lines = [f"[{badge}]" + (f"  {src_extra}" if src_extra else ""), flat, p]
            tip = "\n".join(tip_lines)
            row_w = QWidget()
            row_w.setStyleSheet("background:transparent; border:none; outline:none;")
            row_w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            h = QHBoxLayout(row_w)
            h.setContentsMargins(4, 0, 4, 0)
            h.setSpacing(6)
            badge_lbl = QLabel(badge)
            badge_lbl.setStyleSheet(_pfn_product_search_badge_stylesheet(badge))
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge_lbl.setFixedWidth(76)
            badge_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            name_lbl = QLabel()
            name_lbl.setTextFormat(Qt.TextFormat.RichText)
            name_lbl.setStyleSheet("background:transparent; border:none; outline:none; font-size:9px;")
            name_lbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            name_lbl.setText(rich)
            name_lbl.setToolTip(tip)
            badge_lbl.setToolTip(tip)
            row_w.setToolTip(tip)
            h.addWidget(badge_lbl, 0)
            h.addWidget(name_lbl, 1)
            self.search_list.addItem(it)
            it.setSizeHint(QSize(10, 24))
            self.search_list.setItemWidget(it, row_w)
        self._position_search_list()
        self.search_list.setCurrentRow(0)
        self.search_list.show()

    def _on_search_item_clicked(self, item):
        payload = item.data(Qt.ItemDataRole.UserRole) or {}
        tree_item = payload.get("tree_item")
        path = (payload.get("path") or "").strip()
        self._hide_search_list()
        if tree_item:
            # 展开所有父节点并定位
            cur = tree_item.parent()
            while cur is not None:
                cur.setExpanded(True)
                cur = cur.parent()
            self.tree.setCurrentItem(tree_item)
            self.tree.scrollToItem(tree_item)
        elif path:
            self._scroll_tree_to_path(path)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "search_edit", None):
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                    if self.search_list.isVisible() and self.search_list.count() > 0:
                        row = self.search_list.currentRow()
                        if event.key() == Qt.Key.Key_Down:
                            row = 0 if row < 0 else min(row + 1, self.search_list.count() - 1)
                        else:
                            row = self.search_list.count() - 1 if row < 0 else max(row - 1, 0)
                        self.search_list.setCurrentRow(row)
                        return True
                if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                    it = self.search_list.currentItem()
                    if it:
                        self._on_search_item_clicked(it)
                        return True
                if event.key() == Qt.Key.Key_Escape:
                    self.search_edit.clear()
                    self._hide_search_list()
                    return True
            elif event.type() == QEvent.Type.FocusOut:
                QTimer.singleShot(150, self._hide_search_list)
        return super().eventFilter(obj, event)
    
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
        # 节点变化后刷新索引，保证搜索结果实时
        QTimer.singleShot(0, self._rebuild_search_index)
    
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

    def _expand_node_to_min_favorite_paths(self, path):
        """将选中节点展开为若干「最小收藏」路径（产品/试验会递归到叶子层），跳过 .git 与 utility 子树。"""
        path = os.path.normpath(path).replace("/", "\\")
        if not path or not os.path.isdir(path):
            return []
        if _pfn_is_min_favorite_depth(path):
            return [path]
        try:
            subs = self.core.list_children(path) or []
        except Exception:
            return []
        subs = [s for s in subs if not _pfn_excluded_favorite_dir(s.get("name", ""))]
        if not subs:
            return []
        out = []
        for s in subs:
            out.extend(self._expand_node_to_min_favorite_paths(s["path"]))
        return out
    
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
            try:
                leaf_paths = self._expand_node_to_min_favorite_paths(path)
            except Exception:
                leaf_paths = []
            for lp in leaf_paths:
                if lp in seen_paths:
                    continue
                seen_paths.add(lp)
                try:
                    proj = self._project_from_path(lp)
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
                self.core.add_favorite(
                    proj,
                    overwrite=proj["full_path"] in existing,
                    autosave=False,
                )
                success += 1
                added_names.append(os.path.basename(proj["full_path"].rstrip("\\")))
            except Exception:
                fail += 1
        if success > 0:
            self.core.config.save()
            self.core._match_cache.clear()
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

if __name__ == "__main__":
    # Single entry point is main.py (frozen + dev). Keep app_qt.py as a library module.
    import runpy

    _main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
    runpy.run_path(_main_py, run_name="__main__")
