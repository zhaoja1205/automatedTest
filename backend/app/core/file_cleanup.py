"""
上传文件自动清理。

按配置的保留天数，定期清理 uploads/ 目录中的过期文件和空目录。
清理逻辑：
- 遍历 uploads/ 下所有文件，删除修改时间超过 retention_days 的文件
- 清理空的 session 子目录
- 跳过 .gitkeep 等保护文件
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


# 用 __file__ 定位 backend/ 目录，避免 cwd 依赖
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_UPLOADS_DIR = _BACKEND_DIR / "uploads"


def cleanup_old_uploads(retention_days: int = 3) -> int:
    """删除超过 retention_days 天的上传文件。

    Returns:
        删除的文件/目录数量。
    """
    if not _UPLOADS_DIR.exists():
        return 0

    cutoff = time.time() - retention_days * 86400
    removed = 0

    # 先清理过期文件
    for root, dirs, files in os.walk(str(_UPLOADS_DIR), topdown=False):
        for fname in files:
            if fname == ".gitkeep":
                continue
            fpath = os.path.join(root, fname)
            try:
                if os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    removed += 1
            except OSError:
                pass

        # 清理空的 session 子目录（不删除 uploads/ 本身）
        root_path = Path(root)
        if root_path != _UPLOADS_DIR and _is_empty_dir(root_path):
            try:
                root_path.rmdir()
                removed += 1
            except OSError:
                pass

    return removed


def _is_empty_dir(path: Path) -> bool:
    """检查目录是否为空（忽略 .gitkeep）。"""
    try:
        entries = list(path.iterdir())
        return len(entries) == 0 or all(e.name == ".gitkeep" for e in entries)
    except OSError:
        return False


def get_uploads_stats() -> dict:
    """获取 uploads/ 目录的统计信息（供前端展示）。"""
    if not _UPLOADS_DIR.exists():
        return {"total_files": 0, "total_size_mb": 0, "session_count": 0}

    total_files = 0
    total_size = 0
    session_dirs = set()

    for root, dirs, files in os.walk(str(_UPLOADS_DIR)):
        root_path = Path(root)
        # 统计 session 目录
        if root_path.parent == _UPLOADS_DIR and root_path != _UPLOADS_DIR:
            session_dirs.add(root_path.name)
        for fname in files:
            if fname == ".gitkeep":
                continue
            fpath = os.path.join(root, fname)
            try:
                total_files += 1
                total_size += os.path.getsize(fpath)
            except OSError:
                pass

    return {
        "total_files": total_files,
        "total_size_mb": round(total_size / (1024 * 1024), 1),
        "session_count": len(session_dirs),
    }
