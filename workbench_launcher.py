import json
import os
import subprocess
from typing import Dict, Optional


def load_workbench_cache(cache_path: str) -> Dict[str, str]:
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                if isinstance(k, str) and isinstance(v, str):
                    out[k] = v
            return out
    except Exception:
        pass
    return {}


def save_workbench_cache(cache_path: str, cache: Dict[str, str]) -> None:
    folder = os.path.dirname(os.path.abspath(cache_path))
    os.makedirs(folder, exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache or {}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, cache_path)


def choose_exe_to_launch(
    *,
    cached_exe: str,
    scanned_exe: str,
    cached_exists: bool,
    scanned_exists: bool,
) -> str:
    # B 策略：点击时优先“秒开”——只要缓存路径存在就先启动它；
    # 扫描到的最新版用于更新缓存，不在本次点击上阻塞等待。
    if cached_exe and cached_exists:
        return cached_exe
    if scanned_exe and scanned_exists:
        return scanned_exe
    return ""


def build_windows_silent_popen_kwargs() -> dict:
    kw = {"close_fds": False}
    try:
        creationflags = 0
        # 不弹控制台窗口 + 与当前进程分离（更“秒返”）
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        kw["creationflags"] = creationflags
    except Exception:
        kw["creationflags"] = 0
    return kw


def default_workbench_cache_path(app_name: str = "PFN") -> str:
    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        return os.path.join(appdata, app_name, "workbench_cache.json")
    # 兜底：放当前目录（通常不会走到）
    return os.path.join(os.getcwd(), "workbench_cache.json")

