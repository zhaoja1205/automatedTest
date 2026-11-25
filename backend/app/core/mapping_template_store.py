"""
SWE.1 列映射模板跨项目存盘 — runtime/swe1_mapping_templates/*.json

设计目标（见 swe1_refactor_plan.md §5）：
- 工程师第一次手工映射一张新格式的需求表，保存为模板
- 之后任何项目导入同样列头的表 → 自动命中模板，跳过 A3 手工步
- header_fingerprint 命中优先；若未命中返回 infer_mapping 的推断结果
- 不依赖 DB，JSON 单文件即可，和 creator_projects 同级

文件名规则：<template_id>.json，id 为 uuid4
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.schemas.aspice.swe1_schema import ColumnMapping, MappingTemplate


# 存盘目录（在 runtime 下，和 creator_projects 同级）
_BASE = Path(__file__).resolve().parents[2] / "runtime" / "swe1_mapping_templates"


def _ensure_base() -> Path:
    _BASE.mkdir(parents=True, exist_ok=True)
    return _BASE


def _tpl_path(template_id: str) -> Path:
    return _ensure_base() / f"{template_id}.json"


def list_templates() -> list[MappingTemplate]:
    """列出所有已存模板，按创建时间倒序。"""
    _ensure_base()
    out: list[MappingTemplate] = []
    for p in _BASE.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(MappingTemplate(**data))
        except Exception:
            # 单个文件坏不影响其余
            continue
    out.sort(key=lambda t: t.created_at, reverse=True)
    return out


def get_template(template_id: str) -> Optional[MappingTemplate]:
    p = _tpl_path(template_id)
    if not p.exists():
        return None
    try:
        return MappingTemplate(**json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def find_by_fingerprint(fingerprint: str) -> Optional[MappingTemplate]:
    """按列头指纹精确命中。"""
    for t in list_templates():
        if t.header_fingerprint == fingerprint:
            return t
    return None


def save_template(
    name: str,
    header_fingerprint: str,
    headers: list[str],
    mappings: list[ColumnMapping],
    description: str = "",
    row_type_rules: Optional[dict] = None,
    inherit_cols: Optional[list[int]] = None,
) -> MappingTemplate:
    """新建或覆盖同指纹模板。同指纹 → 覆盖旧条，避免冗余。"""
    _ensure_base()
    existing = find_by_fingerprint(header_fingerprint)
    tpl_id = existing.template_id if existing else uuid.uuid4().hex

    tpl = MappingTemplate(
        template_id=tpl_id,
        name=name or (existing.name if existing else "未命名模板"),
        created_at=existing.created_at if existing else datetime.now(timezone.utc).isoformat(),
        header_fingerprint=header_fingerprint,
        headers=headers,
        mappings=mappings,
        row_type_rules=row_type_rules or {},
        inherit_cols=inherit_cols or [],
        description=description,
    )
    _tpl_path(tpl_id).write_text(
        json.dumps(tpl.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return tpl


def delete_template(template_id: str) -> bool:
    p = _tpl_path(template_id)
    if not p.exists():
        return False
    p.unlink()
    return True


def update_template_meta(template_id: str, name: str = "", description: str = "") -> Optional[MappingTemplate]:
    """只改名字/描述，不改 mapping/fingerprint。"""
    tpl = get_template(template_id)
    if tpl is None:
        return None
    if name:
        tpl.name = name
    if description is not None:
        tpl.description = description
    _tpl_path(template_id).write_text(
        json.dumps(tpl.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return tpl
