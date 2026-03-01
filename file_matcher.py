import os
import glob
from datetime import datetime
import re
 
EXCLUDED_DIRS = {"archive", "归档", "备份", "backup", "old"}

class FileMatcher:
    def match(self, project_path, rules):
        out = {}
        for file_type, rule in rules.items():
            search_path = os.path.join(project_path, rule["path"])
            if rule.get("select") == "protocol_versions":
                if not os.path.isdir(search_path):
                    continue
                try:
                    subdirs = [d for d in os.listdir(search_path) if os.path.isdir(os.path.join(search_path, d))]
                except Exception:
                    subdirs = []
                version_re = re.compile(r'^(v)?\d+(\.\d+)*$', re.IGNORECASE)
                found_any = False
                for d in sorted(subdirs):
                    if d.lower() in EXCLUDED_DIRS:
                        continue
                    if not version_re.match(d.strip()):
                        continue
                    base = os.path.join(search_path, d)
                    # Prefer doc/docx; fallback to pdf
                    files = []
                    for pat in ["*.doc*", "*.pdf"]:
                        pattern = os.path.join(base, pat)
                        candidates = glob.glob(pattern, recursive=True)
                        if rule.get("contains"):
                            inc = rule["contains"]
                            candidates = [f for f in candidates if any(s in os.path.basename(f) for s in inc)]
                        if rule.get("exclude_contains"):
                            excl = rule["exclude_contains"]
                            candidates = [f for f in candidates if all(s not in os.path.basename(f) for s in excl)]
                        if candidates:
                            files = candidates
                            break
                    if rule.get("contains"):
                        inc = rule["contains"]
                        files = [f for f in files if any(s in os.path.basename(f) for s in inc)]
                    if rule.get("exclude_contains"):
                        excl = rule["exclude_contains"]
                        files = [f for f in files if all(s not in os.path.basename(f) for s in excl)]
                    if not files:
                        continue
                    selected = self._select(files, "latest")
                    if selected:
                        out[f"{file_type}-{d}"] = selected
                        found_any = True
                if found_any:
                    continue
                # Fallback at top-level: prefer doc/docx, else pdf
                files = []
                for pat in ["*.doc*", "*.pdf"]:
                    pattern = os.path.join(search_path, pat)
                    candidates = glob.glob(pattern)
                    if rule.get("contains"):
                        inc = rule["contains"]
                        candidates = [f for f in candidates if any(s in os.path.basename(f) for s in inc)]
                    if rule.get("exclude_contains"):
                        excl = rule["exclude_contains"]
                        candidates = [f for f in candidates if all(s not in os.path.basename(f) for s in excl)]
                    if candidates:
                        files = candidates
                        break
                if rule.get("contains"):
                    inc = rule["contains"]
                    files = [f for f in files if any(s in os.path.basename(f) for s in inc)]
                if rule.get("exclude_contains"):
                    excl = rule["exclude_contains"]
                    files = [f for f in files if all(s not in os.path.basename(f) for s in excl)]
                if not files:
                    continue
                selected = self._select(files, "latest")
                if selected:
                    out[file_type] = selected
                continue
            if rule.get("select") == "per_subfolder_latest":
                if not os.path.isdir(search_path):
                    continue
                try:
                    subdirs = [d for d in os.listdir(search_path) if os.path.isdir(os.path.join(search_path, d))]
                except Exception:
                    subdirs = []
                for d in sorted(subdirs):
                    if d.lower() in EXCLUDED_DIRS:
                        continue
                    base = os.path.join(search_path, d)
                    pattern = os.path.join(base, rule["pattern"])
                    files = glob.glob(pattern, recursive=True)
                    if rule.get("contains"):
                        inc = rule["contains"]
                        files = [f for f in files if any(s in os.path.basename(f) for s in inc)]
                    if rule.get("exclude_contains"):
                        excl = rule["exclude_contains"]
                        files = [f for f in files if all(s not in os.path.basename(f) for s in excl)]
                    if not files:
                        continue
                    selected = self._select(files, "latest")
                    if selected:
                        out[f"{file_type}-{d}"] = selected
                continue
            pattern = os.path.join(search_path, rule["pattern"])
            files = glob.glob(pattern, recursive=True)
            if rule.get("contains"):
                inc = rule["contains"]
                # Must contain at least one of the strings in "contains" list
                files = [f for f in files if any(s in os.path.basename(f) for s in inc)]
            
            if rule.get("exclude_contains"):
                excl = rule["exclude_contains"]
                files = [f for f in files if all(s not in os.path.basename(f) for s in excl)]
            if not files:
                continue
            selected = self._select(files, rule.get("select", "latest"))
            if selected:
                out[file_type] = selected
        return out

    def _select(self, files, mode):
        if mode == "exact":
            return files[0] if files else None
        if mode == "all":
            def _mtime(p):
                try:
                    return os.path.getmtime(p)
                except Exception:
                    return 0
            return sorted(files, key=_mtime, reverse=True)
        latest = None
        latest_mtime = None
        for f in files:
            try:
                m = os.path.getmtime(f)
            except Exception:
                m = 0
            if latest is None or m > latest_mtime:
                latest = f
                latest_mtime = m
        return latest
