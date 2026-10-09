"""
函数时序图模块 API 路由，挂载在 /api/seqdiag。

职责：
- 项目 CRUD（session-agnostic，与 classdiag 对称）
- 源码 zip / include zip 的流式上传 + 安全解压（zip_utils.py）
- 函数时序图生成 `/generate`：
    1. 定位函数（cpp_seq_parser.find_function）
    2. 提取变量类型 + 调用链（extract_var_types / extract_calls）
    3. 组装 PlantUML 时序图文本（seq_uml_emit.build_seq_uml）
    4. 落 last_query 快照
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import seqdiag_store
from app.core import cpp_seq_parser
from app.core.seq_uml_emit import build_seq_uml
from app.core.zip_utils import (
    UnsafeArchive,
    UploadTooLarge,
    safe_extractall,
    stream_save,
    summarize_extract,
)


router = APIRouter()


# ---- 请求模型 ----

class CreateProjectRequest(BaseModel):
    name: str


class GenerateRequest(BaseModel):
    func_a_name: str
    func_b_name: Optional[str] = None
    options: dict = {}


# ---- 项目 CRUD ----

@router.get("/projects")
async def list_projects():
    return seqdiag_store.list_projects()


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    return seqdiag_store.create_project(name)


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = seqdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    ok = seqdiag_store.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": True}


# ---- 源码 zip 上传 ----

@router.post("/projects/{project_id}/source")
async def upload_source(project_id: str, file: UploadFile = File(...)):
    """上传主源码 zip：流式落盘 → 安全解压 → 删除 zip。

    重传会先清空 source/ 目录再解压，避免残留旧文件干扰后续解析。
    """
    project = seqdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    filename = file.filename or "source.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 文件")

    seqdiag_store.clear_source(project_id)
    project_root = os.path.join("runtime", "seqdiag_projects", project_id)
    zip_path = os.path.join(project_root, "_upload_source.zip")

    try:
        await stream_save(file, zip_path)
    except UploadTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"落盘失败: {e}")

    target = seqdiag_store.source_dir(project_id)
    try:
        entry_count = safe_extractall(zip_path, target)
    except UnsafeArchive as e:
        _cleanup(zip_path)
        seqdiag_store.clear_source(project_id)
        raise HTTPException(status_code=400, detail=f"zip 不安全: {e}")
    finally:
        _cleanup(zip_path)

    summary = summarize_extract(target)
    summary["entry_count"] = entry_count
    project["source_zip_name"] = filename
    project["source_summary"] = summary
    seqdiag_store.save_project(project)
    return {
        "source_zip_name": filename,
        "summary": summary,
    }


# ---- include zip 追加 ----

@router.post("/projects/{project_id}/includes")
async def upload_include(
    project_id: str,
    name: str = Form(...),
    file: UploadFile = File(...),
):
    """上传一个 include 包（可多次调用追加）。"""
    project = seqdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    try:
        safe_name = seqdiag_store.safe_include_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if any(item.get("name") == safe_name for item in project.get("include_dirs", [])):
        raise HTTPException(status_code=409, detail=f"include 名字已存在: {safe_name}")

    filename = file.filename or f"{safe_name}.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 文件")

    project_root = os.path.join("runtime", "seqdiag_projects", project_id)
    zip_path = os.path.join(project_root, f"_upload_include_{safe_name}.zip")

    try:
        await stream_save(file, zip_path)
    except UploadTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"落盘失败: {e}")

    target = seqdiag_store.include_dir(project_id, safe_name)
    if os.path.isdir(target):
        import shutil
        shutil.rmtree(target)

    try:
        entry_count = safe_extractall(zip_path, target)
    except UnsafeArchive as e:
        _cleanup(zip_path)
        if os.path.isdir(target):
            import shutil
            shutil.rmtree(target)
        raise HTTPException(status_code=400, detail=f"zip 不安全: {e}")
    finally:
        _cleanup(zip_path)

    summary = summarize_extract(target)
    summary["entry_count"] = entry_count
    item = {
        "name": safe_name,
        "path": os.path.join("includes", safe_name),
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "zip_name": filename,
        "summary": summary,
    }
    project.setdefault("include_dirs", []).append(item)
    seqdiag_store.save_project(project)
    return item


@router.delete("/projects/{project_id}/includes/{name}")
async def delete_include(project_id: str, name: str):
    project = seqdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        safe = seqdiag_store.safe_include_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ok = seqdiag_store.remove_include(project_id, safe)
    if not ok:
        raise HTTPException(status_code=404, detail="include 不存在")
    return {"deleted": True, "name": safe}


# ---- 头文件 autocomplete ----

_HEADERS_CACHE: dict[str, tuple[int, list[str]]] = {}


def _list_project_headers(project: dict) -> list[str]:
    project_id = project["project_id"]
    source_root = seqdiag_store.source_absolute_path(project)
    if not source_root or not os.path.isdir(source_root):
        return []

    try:
        mtime_ns = os.stat(source_root).st_mtime_ns
    except OSError:
        mtime_ns = 0

    cached = _HEADERS_CACHE.get(project_id)
    if cached and cached[0] == mtime_ns:
        return cached[1]

    headers = cpp_seq_parser.collect_headers(source_root)
    rels = sorted(
        os.path.relpath(h, source_root).replace(os.sep, "/")
        for h in headers
    )
    _HEADERS_CACHE[project_id] = (mtime_ns, rels)
    return rels


@router.get("/projects/{project_id}/headers")
async def list_headers(project_id: str, q: str = "", limit: int = 200):
    project = seqdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    limit = max(1, min(int(limit or 200), 1000))
    headers = _list_project_headers(project)
    qn = (q or "").strip().lower()
    if qn:
        headers = [h for h in headers if qn in h.lower()]
    return {"items": headers[:limit], "total": len(headers)}


# ---- 生成 ----

@router.post("/projects/{project_id}/generate")
async def generate(project_id: str, req: GenerateRequest):
    """生成函数时序图。

    流程：
      1. find_function(source_roots, func_a_name) — 定位函数 A
         - 0 命中 → 404；多命中 → 409 + 候选列表
      2. 可选：同样定位函数 B
      3. extract_var_types + extract_calls → 调用链
      4. build_seq_uml → PlantUML 文本
      5. 落 last_query 快照，返回给前端
    """
    project = seqdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not project.get("source_zip_name"):
        raise HTTPException(status_code=400, detail="请先上传主源码 zip")

    func_a_name = (req.func_a_name or "").strip()
    if not func_a_name:
        raise HTTPException(status_code=400, detail="func_a_name 不能为空")

    source_root = seqdiag_store.source_absolute_path(project)
    include_roots = seqdiag_store.include_absolute_paths(project)
    all_roots = [source_root, *include_roots]

    # --- 定位函数 A ---
    matches_a = cpp_seq_parser.find_function(all_roots, func_a_name)
    if not matches_a:
        raise HTTPException(status_code=404, detail=f"未找到函数 {func_a_name!r}")
    if len(matches_a) > 1:
        return _multi_match_response(matches_a)
    func_a = matches_a[0]

    # --- 定位函数 B（可选）---
    func_b = None
    func_b_name = (req.func_b_name or "").strip()
    if func_b_name:
        matches_b = cpp_seq_parser.find_function(all_roots, func_b_name)
        if not matches_b:
            raise HTTPException(status_code=404, detail=f"未找到函数 B {func_b_name!r}")
        if len(matches_b) > 1:
            return _multi_match_response(matches_b, which="B")
        func_b = matches_b[0]

    # --- 提取调用链 ---
    var_types_a = cpp_seq_parser.extract_var_types(func_a.body, func_a.params)
    calls_a = cpp_seq_parser.extract_calls(func_a.body, func_a.class_name, var_types_a)

    calls_b = None
    if func_b:
        var_types_b = cpp_seq_parser.extract_var_types(func_b.body, func_b.params)
        calls_b = cpp_seq_parser.extract_calls(func_b.body, func_b.class_name, var_types_b)

    # --- 生成 UML ---
    uml = build_seq_uml(func_a, calls_a, func_b, calls_b, req.options or {})

    # --- 收集涉及的文件（相对路径）---
    involved = {func_a.file}
    if func_b:
        involved.add(func_b.file)

    def _pretty(p: str) -> str:
        if p.startswith(source_root):
            return "source/" + os.path.relpath(p, source_root).replace(os.sep, "/")
        for inc_root in include_roots:
            if p.startswith(inc_root):
                inc_name = os.path.basename(inc_root)
                rel = os.path.relpath(p, inc_root).replace(os.sep, "/")
                return f"includes/{inc_name}/{rel}"
        return p

    matched_files = sorted(_pretty(p) for p in involved)

    snapshot = {
        "func_a_name": func_a_name,
        "func_b_name": func_b_name or None,
        "resolved_func_a": func_a.qualified_name,
        "resolved_func_b": func_b.qualified_name if func_b else None,
        "matched_files": matched_files,
        "uml": uml,
    }
    seqdiag_store.update_last_query(project_id, snapshot)
    return snapshot


# ---- 内部辅助 ----

def _multi_match_response(matches: list, which: str = "A") -> JSONResponse:
    body = {
        "detail": f"函数 {which} 存在多个同名定义，请改用全限定名（Class::method）",
        "matches": [
            {
                "qualified_name": m.qualified_name,
                "file": m.file,
                "line": m.line,
                "kind": m.kind,
            }
            for m in matches
        ],
    }
    return JSONResponse(status_code=409, content=body)


def _cleanup(path: str) -> None:
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
