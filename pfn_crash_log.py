"""PFN crash / uncaught exception logging to %USERPROFILE%\\PFN_Config\\pfn_crash.log"""
import faulthandler
import os
import sys
import traceback
from datetime import datetime

_CRASH_LOG_PATH = ""
_FAULT_HANDLER_FILE = None


def crash_log_path() -> str:
    global _CRASH_LOG_PATH
    if _CRASH_LOG_PATH:
        return _CRASH_LOG_PATH
    try:
        from config_manager import get_config_path

        cfg = str(get_config_path() or "").strip()
        d = os.path.dirname(os.path.abspath(cfg)) if cfg else ""
        if d and os.path.isdir(d):
            _CRASH_LOG_PATH = os.path.join(d, "pfn_crash.log")
            return _CRASH_LOG_PATH
    except Exception:
        pass
    profile = (os.environ.get("USERPROFILE") or "").strip()
    if profile:
        d = os.path.join(profile, "PFN_Config")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        _CRASH_LOG_PATH = os.path.join(d, "pfn_crash.log")
        return _CRASH_LOG_PATH
    _CRASH_LOG_PATH = os.path.join(os.path.expanduser("~"), "pfn_crash.log")
    return _CRASH_LOG_PATH


def _append_crash_log(header: str, body: str) -> None:
    line = f"\n{'=' * 72}\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {header}\n{body}\n"
    try:
        with open(crash_log_path(), "a", encoding="utf-8", errors="replace") as f:
            f.write(line)
    except Exception:
        pass
    if os.environ.get("PFN_KEEP_CONSOLE") == "1":
        try:
            print(line, flush=True)
        except Exception:
            pass


def _pfn_excepthook(exc_type, exc_value, exc_tb):
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    body = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _append_crash_log(f"Uncaught {exc_type.__name__}: {exc_value}", body)
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def install_pfn_crash_handlers() -> None:
    """Register excepthook and faulthandler before QApplication starts."""
    global _FAULT_HANDLER_FILE
    sys.excepthook = _pfn_excepthook
    try:
        path = crash_log_path()
        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, exist_ok=True)
        _FAULT_HANDLER_FILE = open(path, "a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=_FAULT_HANDLER_FILE, all_threads=True)
    except Exception:
        try:
            faulthandler.enable(all_threads=True)
        except Exception:
            pass
