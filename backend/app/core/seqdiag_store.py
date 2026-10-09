"""
函数时序图项目存储 — 基于文件系统的 CRUD。

目录结构：
  runtime/seqdiag_projects/<project_id>/
    project.json          # 元信息 + last_query 快照
    source/               # 主源码 zip 解压后的根
    includes/<name>/      # 每个 include 包各自的解压目录

与 classdiag_store 形态完全一致，唯一区别是 BASE_DIR 和
last_query 快照字段（func_a_name / func_b_name 而非 class_name）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from typing import Optional
from uuid import uuid4


BASE_DIR = os.path.join("runtime", "seqdiag_projects")


def _project_dir(project_id: str) -> str:
    return os.path.join(BASE_DIR, project_id)


def _project_file(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "project.json")


def source_dir(project_id: str) -> str:
    return os.path.join(_project_dir(project_id), "source")


def include_dir(project_id: str, name: str) -> str:
    """单个 include 包的解压目录。name 已经过 safe_include_name。"""
    return os.path.join(_project_dir(project_id), "includes", name)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---- CRUD ----

def list_projects() -> list[dict]:
    """扫描项目目录，返回摘要列表。"""
    os.makedirs(BASE_DIR, exist_ok=True)
    result = []
    for name in sorted(os.listdir(BASE_DIR)):
        pf = _project_file(name)
        if not os.path.isfile(pf):
            continue
        try:
            with open(pf, "r", encoding="utf-8") as f:
                data = json.load(f)
            result.append({
                "project_id": data.get("project_id", name),
                "name": data.get("name", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "has_source": bool(data.get("source_zip_name")),
                "include_count": len(data.get("include_dirs", [])),
                "last_func": (data.get("last_query") or {}).get("func_a_name", ""),
            })
        except Exception:
            continue
    return result


def get_project(project_id: str) -> Optional[dict]:
    pf = _project_file(project_id)
    if not os.path.isfile(pf):
        return None
    with open(pf, "r", encoding="utf-8") as f:
        return json.load(f)


def create_project(name: str) -> dict:
    project_id = uuid4().hex[:12]
    project = {
        "project_id": project_id,
        "name": name,
        "created_at": _now(),
        "updated_at": _now(),
        "source_dir": "source",
        "source_zip_name": "",
        "source_summary": {},
        "include_dirs": [],
        "last_query": None,
    }
    os.makedirs(_project_dir(project_id), exist_ok=True)
    _save(project)
    return project


def save_project(project: dict) -> None:
    project["updated_at"] = _now()
    os.makedirs(_project_dir(project["project_id"]), exist_ok=True)
    _save(project)


def delete_project(project_id: str) -> bool:
    d = _project_dir(project_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
        return True
    return False


# ---- 源码/include 目录管理 ----

def clear_source(project_id: str) -> None:
    """删除主源码目录内容（重传前调用）。"""
    d = source_dir(project_id)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d, exist_ok=True)


def remove_include(project_id: str, name: str) -> bool:
    """删除指定 include。返回是否命中。"""
    project = get_project(project_id)
    if not project:
        return False
    matched = None
    for item in project.get("include_dirs", []):
        if item.get("name") == name:
            matched = item
            break
    if matched is None:
        return False

    d = include_dir(project_id, name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    project["include_dirs"] = [
        x for x in project["include_dirs"] if x.get("name") != name
    ]
    save_project(project)
    return True


def include_absolute_paths(project: dict) -> list[str]:
    """返回项目里所有 include 目录的绝对路径列表。"""
    pid = project["project_id"]
    return [
        os.path.abspath(include_dir(pid, item["name"]))
        for item in project.get("include_dirs", [])
        if os.path.isdir(include_dir(pid, item["name"]))
    ]


def source_absolute_path(project: dict) -> str:
    return os.path.abspath(source_dir(project["project_id"]))


# ---- 查询结果快照 ----

def update_last_query(project_id: str, query: dict) -> None:
    """把最近一次 /generate 的结果落到 project.json。"""
    project = get_project(project_id)
    if not project:
        return
    project["last_query"] = query
    save_project(project)


# ---- 工具 ----

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")


def safe_include_name(raw: str) -> str:
    """把用户传的 include 名字规范化：只留字母数字下划线点横线。"""
    if not raw:
        raise ValueError("include 名字不能为空")
    trimmed = raw.strip()
    if not _SAFE_NAME.match(trimmed):
        raise ValueError(f"include 名字非法（仅允许字母数字下划线点横线）: {raw!r}")
    if trimmed in (".", ".."):
        raise ValueError(f"include 名字非法: {raw!r}")
    return trimmed


# ---- 内部 ----

def _save(project: dict) -> None:
    pf = _project_file(project["project_id"])
    with open(pf, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
