"""R4 需求 #2c 一次性迁移：清空 Deserializer / nvsipl_camera / nvsipl_multicast
三个模块的 focused_keys 与 included_added_keys。

背景：
  这三个模块 MODULE_SPLIT_POLICY 从 modified_only → manual 之后，历史勾选的
  focused_keys 还在。manual 策略下 focused_keys 直接决定 L5 展开列表，老数据
  里可能混了 bridge 自动吃过去的 diff 噪声键，再次导出会把它们当"人工勾选"
  原封不动展开。安全做法：清空，交由用户重新在 FocusFunctionsPicker 勾选。

用法：
  cd backend
  python -m scripts.reset_focus_for_manual_modules           # 全量项目
  python -m scripts.reset_focus_for_manual_modules <pid>...  # 指定若干项目
  python -m scripts.reset_focus_for_manual_modules --dry-run # 只打印不写
"""

from __future__ import annotations

import sys
from typing import Iterable

from app.core import creator_store
from app.core.arch_sections import MODULE_SHORT, MODULE_SPLIT_POLICY


# 以 MODULE_SPLIT_POLICY == "manual" 且不在人工章节白名单里的模块为目标
_MANUAL_SECTION_SHORTS = {"CameraSecurity"}  # 本来就人工，不碰历史勾选


def _norm(name: str) -> str:
    return (name or "").lower().replace(" ", "").replace("_", "").replace("-", "")


def _target_cids() -> set[str]:
    target_shorts = {
        s for s, p in MODULE_SPLIT_POLICY.items()
        if p == "manual" and s not in _MANUAL_SECTION_SHORTS
    }
    norm_targets = {_norm(s) for s in target_shorts}
    out: set[str] = set()
    for cid, short in MODULE_SHORT.items():
        if _norm(short) in norm_targets:
            out.add(cid)
    return out


_TARGET_CIDS = _target_cids()
_TARGET_NORMS = {_norm(s) for s in (MODULE_SHORT.get(c, "") for c in _TARGET_CIDS) if s}


def _is_target(ff: dict) -> bool:
    cid = (ff.get("component_id") or ff.get("cid") or "").strip()
    if cid and cid in _TARGET_CIDS:
        return True
    name = (ff.get("component_name") or ff.get("name") or "").strip()
    norm = _norm(name)
    if not norm:
        return False
    return any(t in norm or norm in t for t in _TARGET_NORMS)


def process_project(project: dict, dry_run: bool) -> tuple[int, int]:
    """返回 (命中模块数, 清掉的 key 数)。"""
    swe3 = (((project.get("aspice") or {}).get("swe3")) or {})
    push_d = swe3.get("push_d") or {}
    focus_list = push_d.get("focus_functions") or []
    if not isinstance(focus_list, list):
        return (0, 0)
    hit = 0
    removed = 0
    for ff in focus_list:
        if not isinstance(ff, dict) or not _is_target(ff):
            continue
        hit += 1
        for field in ("focused_keys", "included_added_keys", "manual_additions"):
            cur = ff.get(field) or []
            if cur:
                removed += len(cur)
            if not dry_run:
                ff[field] = []
    return (hit, removed)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    pids: list[str] = [a for a in argv if not a.startswith("-")]
    if not pids:
        pids = [p.get("id") for p in creator_store.list_projects() if p.get("id")]
    total_hit = 0
    total_removed = 0
    for pid in pids:
        proj = creator_store.get_project(pid)
        if not proj:
            print(f"[skip] {pid}: 项目不存在")
            continue
        hit, removed = process_project(proj, dry_run)
        total_hit += hit
        total_removed += removed
        if hit:
            action = "将清" if dry_run else "已清"
            print(f"[{pid}] 命中 {hit} 个目标模块，{action} {removed} 个 key")
            if not dry_run:
                creator_store.save_project(proj)
    tag = "（dry-run，未写盘）" if dry_run else ""
    print(f"完成：命中模块共 {total_hit}，清除 key 共 {total_removed}{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
