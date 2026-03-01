"""
Z盘项目扫描器：支持 projects、unblinded、users 及其子层级结构。
Users 文件夹下自动识别 userid-projects、userid-unblinded 子层级，纳入来源标识。
"""
import os


def _norm_path(path):
    """统一为 Windows 格式路径（反斜杠），支持 Z 盘网络路径"""
    if not path:
        return path
    return os.path.normpath(path).replace("/", "\\")


def _rel_from_z(path):
    """提取 Z:\\ 之后的相对路径部分"""
    p = _norm_path(path)
    if p.upper().startswith("Z:\\"):
        return p[3:]
    if p.upper().startswith("Z:/"):
        return p[3:].replace("/", "\\")
    return p


class ZDriveScanner:
    # 根目录优先级：projects > unblinded > users
    ROOT_ORDER = ["projects", "unblinded", "users"]

    def scan(self, dir_types):
        """Deprecated: use list_children instead for lazy loading"""
        return {}

    def list_children(self, path=None, dir_types=None):
        """
        懒加载子目录。path 为 None 时返回根目录。
        Users 下识别 userid/projects、userid/unblinded 子层级，并附带 source_id。
        """
        if path is None:
            # 按优先级返回根目录：projects > unblinded > users
            roots = []
            order = dir_types or self.ROOT_ORDER
            for dt in order:
                p = _norm_path(f"Z:\\{dt}")
                if os.path.exists(p):
                    roots.append({
                        "name": dt,
                        "path": p,
                        "type": "root",
                        "is_leaf": False,
                        "source_id": dt,
                    })
            return roots

        path = _norm_path(path)
        rel = _rel_from_z(path)
        parts = [p for p in rel.split("\\") if p]

        # users 下：Z:\users\userid 展开时，列出 projects 和 unblinded，并附带 source_id
        if len(parts) >= 2 and parts[0].lower() == "users":
            userid = parts[1]
            if len(parts) == 2:
                # 当前在 Z:\users\userid，列出 projects 和 unblinded
                children = []
                for sub in ["projects", "unblinded"]:
                    full = os.path.join(path, sub)
                    if os.path.isdir(full):
                        children.append({
                            "name": sub,
                            "path": full,
                            "type": "dir",
                            "is_leaf": False,
                            "source_id": f"users-{userid}-{sub}",
                        })
                return children

        # 通用目录列表
        children = []
        for name in sorted(self._safe_listdir(path)):
            full_path = os.path.join(path, name)
            if not os.path.isdir(full_path):
                continue

            rel_child = _rel_from_z(full_path)
            child_parts = [p for p in rel_child.split("\\") if p]
            depth = len(child_parts)

            # projects/unblinded: Z\type\product\project\version -> depth>=4 为叶子
            # users: Z\users\userid\projects\product\project\version -> depth>=6 为叶子
            is_leaf = (depth >= 4 and parts[0].lower() != "users") or (depth >= 6 and parts[0].lower() == "users")

            source_id = self._compute_source_id(full_path, child_parts)
            children.append({
                "name": name,
                "path": full_path,
                "type": "dir",
                "is_leaf": is_leaf,
                "source_id": source_id,
            })

        return children

    def _compute_source_id(self, full_path, parts):
        """计算来源标识：projects、unblinded、users-{userid}-projects、users-{userid}-unblinded"""
        if not parts:
            return "unknown"
        if parts[0].lower() == "projects":
            return "projects"
        if parts[0].lower() == "unblinded":
            return "unblinded"
        if parts[0].lower() == "users" and len(parts) >= 3:
            return f"users-{parts[1]}-{parts[2]}"
        if parts[0].lower() == "users":
            return "users"
        return parts[0]

    def _safe_listdir(self, path):
        try:
            return os.listdir(path)
        except Exception:
            return []


def get_source_id_from_path(path):
    """从完整路径计算来源标识，用于添加项目时设置 dir_type"""
    rel = _rel_from_z(path)
    parts = [p for p in rel.split("\\") if p]
    if not parts:
        return "unknown"
    if parts[0].lower() == "projects":
        return "projects"
    if parts[0].lower() == "unblinded":
        return "unblinded"
    if parts[0].lower() == "users" and len(parts) >= 3:
        return f"users-{parts[1]}-{parts[2]}"
    if parts[0].lower() == "users":
        return "users"
    return parts[0]
