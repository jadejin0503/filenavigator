import sys
import os
import ctypes

# Windows taskbar / Jump List identity (must be before QApplication)
myappid = "com.pfn.tool.app.1.0"
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

from PyQt6.QtCore import QLockFile
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget

_BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
def _lock_dir_prefer_config() -> str:
    """单实例锁文件目录：优先使用 config.json 所在目录，避免在桌面/分发目录产生 lock 文件。"""
    try:
        from config_manager import get_config_path

        cfg = str(get_config_path() or "").strip()
        d = os.path.dirname(os.path.abspath(cfg)) if cfg else ""
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    # 回退到 APPDATA\PFN
    try:
        appdata = os.environ.get("APPDATA", "") or ""
        if appdata:
            d = os.path.join(appdata, "PFN")
            os.makedirs(d, exist_ok=True)
            return d
    except Exception:
        pass
    return _BASE_DIR


_LOCK_PATH = os.path.join(_lock_dir_prefer_config(), "pfn_app.lock")
_lock = QLockFile(_LOCK_PATH)
if not _lock.tryLock(100):
    sys.exit(0)

from app_qt import PFNCore, QtMainWindow


def _root_icon_path() -> str:
    return os.path.normpath(os.path.join(_BASE_DIR, "icon.ico"))


def _resolve_icon_file_path() -> str:
    """ico 文件路径：exe 同级 icon.ico，或 PyInstaller 单文件解压目录内 assets（与 app_qt 一致）。"""
    p = _root_icon_path()
    if os.path.isfile(p):
        return p
    if getattr(sys, "frozen", False):
        meip = getattr(sys, "_MEIPASS", None)
        if meip:
            inner = os.path.normpath(os.path.join(meip, "assets", "app_icon.ico"))
            if os.path.isfile(inner):
                return inner
    return ""


def _apply_wm_seticon_from_exe_pe(window: QWidget) -> None:
    """无可用 .ico 路径时，从当前 exe 的 PE 图标取句柄设置 WM_SETICON（单文件仅拷 exe 时任务栏仍可用）。"""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        _ = window.winId()
        hwnd = int(window.winId())
    except Exception:
        return
    try:
        exe = os.path.normpath(sys.executable)
        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        h_large = ctypes.c_void_p()
        h_small = ctypes.c_void_p()
        n = int(shell32.ExtractIconExW(exe, 0, ctypes.byref(h_large), ctypes.byref(h_small), 1) or 0)
        if n <= 0:
            return
        if hwnd and h_small.value:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small.value)
        if hwnd and h_large.value:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_large.value)
    except Exception:
        pass


def _apply_wm_seticon(window: QWidget, icon_path: str) -> None:
    """Force Win32 small/big icons (taskbar / Alt+Tab / Task Manager window row)."""
    if sys.platform != "win32":
        return
    if not icon_path or not os.path.isfile(icon_path):
        _apply_wm_seticon_from_exe_pe(window)
        return
    try:
        _ = window.winId()
        hwnd = int(window.winId())
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040

        user32 = ctypes.windll.user32

        def _load(w: int, h: int) -> int:
            return int(user32.LoadImageW(0, icon_path, IMAGE_ICON, w, h, LR_LOADFROMFILE) or 0)

        h_small = _load(16, 16) or _load(24, 24) or int(
            user32.LoadImageW(0, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE) or 0
        )
        h_big = _load(32, 32) or _load(48, 48) or _load(64, 64) or int(
            user32.LoadImageW(0, icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE) or 0
        )
        if not h_small and not h_big:
            _apply_wm_seticon_from_exe_pe(window)
            return
        if hwnd and h_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
        if hwnd and h_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
    except Exception:
        try:
            _apply_wm_seticon_from_exe_pe(window)
        except Exception:
            pass


def main() -> None:
    # Avoid console flicker when launched with python.exe (not used by frozen PFN.exe)
    if sys.platform == "win32" and os.environ.get("PFN_KEEP_CONSOLE") != "1":
        try:
            if ctypes.windll.kernel32.GetConsoleWindow() == 0:
                _dn = open(os.devnull, "w", encoding="utf-8", errors="replace")
                sys.stdout = _dn
                sys.stderr = _dn
        except Exception:
            pass
        try:
            _hwnd = ctypes.windll.kernel32.GetConsoleWindow()
            if _hwnd:
                ctypes.windll.user32.ShowWindow(_hwnd, 0)
        except Exception:
            pass

    app = QApplication(sys.argv)

    icon_path = _resolve_icon_file_path()
    if os.environ.get("PFN_ICON_DEBUG") == "1":
        try:
            print("icon_path:", icon_path, "exists:", os.path.isfile(icon_path), flush=True)
        except Exception:
            pass

    ico = QIcon()
    if os.path.isfile(icon_path):
        ico = QIcon(icon_path)
    if ico.isNull() and getattr(sys, "frozen", False) and sys.platform == "win32":
        t = QIcon(sys.executable)
        if not t.isNull():
            ico = t
    if not ico.isNull():
        app.setWindowIcon(ico)

    core = PFNCore()
    window = QtMainWindow(core)
    if not ico.isNull():
        window.setWindowIcon(ico)

    _apply_wm_seticon(window, icon_path)
    window.show()
    _apply_wm_seticon(window, icon_path)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
