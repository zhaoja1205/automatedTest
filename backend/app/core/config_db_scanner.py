"""SWE.2 §3.3.3 配置文件章节 — query/database 发现与解析。

见 backend/docs/swe2_refactor_plan.md §2。

依赖 engineering_store.engineering_root() 返回的 engineering_src/ 路径；
在此之下按规则扫描候选 query/database/<project> 目录（判定规则：同目录
同时包含 `*_platform.json` + `*_module.json` + `cryptoConfig.json`）。

本模块只做 **发现**，详细解析（解出 ConfigDatabase）将在 Group 3 的后续
推送中补上；现阶段先提供 discover 让前端下拉可用。

目录候选树例（典型 NV SIPL 工程）：
    engineering_src/
      nvidia/.../nvsipl/query/database/predev_mixgroup/        ← 候选
      nvidia/.../nvsipl/query/database/max96724_imx728/        ← 候选
      ...
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

from app.core import engineering_store

logger = logging.getLogger(__name__)


# 最多向下递归层数（避免遇到奇怪工程结构卡死）
_MAX_DEPTH = 10
# 一次最多返回的候选数，防止异常工程（有数百个符合规则的目录）把前端撑爆
_MAX_RESULTS = 50


def _is_candidate(dir_path: Path) -> bool:
    """判定一个目录是否是候选的 query/database/<project> 目录。

    规则（参考 swe2_refactor_plan.md §2.2）：
      同目录下同时包含 *_platform.json + *_module.json + cryptoConfig.json
    其中 cryptoConfig.json 名字固定；前两者是 glob 模式。
    """
    try:
        names = os.listdir(dir_path)
    except OSError:
        return False
    has_platform = False
    has_module = False
    has_crypto = False
    for n in names:
        if not n.endswith(".json"):
            continue
        low = n.lower()
        if low == "cryptoconfig.json":
            has_crypto = True
        elif low.endswith("_platform.json"):
            has_platform = True
        elif low.endswith("_module.json"):
            has_module = True
        if has_platform and has_module and has_crypto:
            return True
    return False


def _walk(root: Path, max_depth: int) -> Iterable[Path]:
    """以 root 为根 BFS 遍历目录，深度限制 max_depth。"""
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        if depth > max_depth:
            continue
        try:
            entries = os.scandir(cur)
        except OSError:
            continue
        for e in entries:
            if not e.is_dir(follow_symlinks=False):
                continue
            p = Path(e.path)
            yield p
            stack.append((p, depth + 1))


def discover_query_dirs(project_id: str) -> list[str]:
    """在 engineering_src/ 下扫出所有候选 query/database 目录。

    返回：**相对 engineering_src/** 的相对路径列表（POSIX 风格，用 "/" 分隔），
    最多 _MAX_RESULTS 条，按路径字典序。前端下拉直接用。
    """
    root = Path(engineering_store.engineering_root(project_id))
    if not root.exists():
        return []
    hits: list[str] = []
    # 先判 root 本身（有工程把 database 直接做在顶层）
    candidates = [root]
    candidates.extend(_walk(root, _MAX_DEPTH))
    for p in candidates:
        if len(hits) >= _MAX_RESULTS:
            break
        if not _is_candidate(p):
            continue
        try:
            rel = p.resolve().relative_to(root.resolve())
        except ValueError:
            # realpath 跑到 engineering_src/ 外 → 不收（防 symlink 骗局）
            continue
        hits.append(rel.as_posix())
    hits.sort()
    return hits


__all__ = ["discover_query_dirs"]
