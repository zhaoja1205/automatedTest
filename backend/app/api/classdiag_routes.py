"""
类图分析模块 API 路由，挂载在 /api/classdiag。

职责：
- 项目 CRUD（对齐 creator/aspice 的形态，session-agnostic）
- 源码 zip / include zip 的**流式上传 + 安全解压**（zip_utils.py）
- 类图生成 `/generate`：本次 Commit 1 只落骨架，返回 501；
  Commit 2 会替换成正则解析 + PlantUML 输出。

上传体量目标 20-200MB，`content = await file.read()` 会把整包吃进内存，
所以 upload 全部走 zip_utils.stream_save。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.core import classdiag_store
from app.core import cpp_class_parser
from app.core import cpp_class_indexer
from app.core import class_uml_emit
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
    """生成类图。stage 决定走哪条路径。

    - `regex`：只走正则，快
    - `clang`：只走 libclang（要求已有正则结果打底或独立可用）
    - `auto`：先正则再 clang 增强
    前端两阶段调用：先 stage=regex 秒出图，再 stage=clang 拿增强。

    `depth`：向上追踪几层父类。默认 2（父类 + 祖父类）。
    range 1..10，防止「继承 10 层」这种反常规工程把图撑爆。
    """
    class_name: str
    stage: str = "auto"          # regex / clang / auto
    options: dict = {}            # {show_private, show_protected, show_static}
    depth: int = 2                # 向上追踪的继承层数


# ---- 项目 CRUD ----

@router.get("/projects")
async def list_projects():
    return classdiag_store.list_projects()


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    return classdiag_store.create_project(name)


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    project = classdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    ok = classdiag_store.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"deleted": True}


# ---- 源码 zip 上传 ----

@router.post("/projects/{project_id}/source")
async def upload_source(project_id: str, file: UploadFile = File(...)):
    """上传主源码 zip：流式落盘 → 安全解压 → 删除 zip。

    重传会先清空 source/ 目录再解压，避免残留旧文件干扰后续解析。
    """
    project = classdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    filename = file.filename or "source.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 文件")

    # 先清空旧的解压目录，再落盘 zip 到项目根，解压完成后删除 zip
    classdiag_store.clear_source(project_id)
    project_root = os.path.join("runtime", "classdiag_projects", project_id)
    zip_path = os.path.join(project_root, "_upload_source.zip")

    try:
        await stream_save(file, zip_path)
    except UploadTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"落盘失败: {e}")

    target = classdiag_store.source_dir(project_id)
    try:
        entry_count = safe_extractall(zip_path, target)
    except UnsafeArchive as e:
        # 解压前就拒了；清 zip 并把 source 目录清干净（可能已经 makedirs）
        _cleanup(zip_path)
        classdiag_store.clear_source(project_id)
        raise HTTPException(status_code=400, detail=f"zip 不安全: {e}")
    finally:
        _cleanup(zip_path)

    summary = summarize_extract(target)
    summary["entry_count"] = entry_count
    project["source_zip_name"] = filename
    project["source_summary"] = summary
    classdiag_store.save_project(project)
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
    """上传一个 include 包（可多次调用追加）。

    `name` 是给这个 include 的显示名字（也用作目录段），需 URL-safe。
    """
    project = classdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    try:
        safe_name = classdiag_store.safe_include_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if any(item.get("name") == safe_name for item in project.get("include_dirs", [])):
        raise HTTPException(status_code=409, detail=f"include 名字已存在: {safe_name}")

    filename = file.filename or f"{safe_name}.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 zip 文件")

    project_root = os.path.join("runtime", "classdiag_projects", project_id)
    zip_path = os.path.join(project_root, f"_upload_include_{safe_name}.zip")

    try:
        await stream_save(file, zip_path)
    except UploadTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"落盘失败: {e}")

    target = classdiag_store.include_dir(project_id, safe_name)
    if os.path.isdir(target):
        # 上面已经校验过 name 冲突，走到这只可能是残留目录（上次崩溃）
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
    classdiag_store.save_project(project)
    return item


@router.delete("/projects/{project_id}/includes/{name}")
async def delete_include(project_id: str, name: str):
    project = classdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        safe = classdiag_store.safe_include_name(name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ok = classdiag_store.remove_include(project_id, safe)
    if not ok:
        raise HTTPException(status_code=404, detail="include 不存在")
    return {"deleted": True, "name": safe}


# ---- 头文件 autocomplete ----

# 头文件列表的进程内缓存：{project_id: (source_mtime_ns, [relpath, ...])}
# 大工程扫盘可能 200ms+，让每次按键都扫是不必要的
_HEADERS_CACHE: dict[str, tuple[int, list[str]]] = {}


def _list_project_headers(project: dict) -> list[str]:
    """列出项目 source_dir 下所有头文件的相对路径。

    走 mtime 缓存：source_dir 顶层 mtime 变化才重扫。
    """
    project_id = project["project_id"]
    source_root = classdiag_store.source_absolute_path(project)
    if not source_root or not os.path.isdir(source_root):
        return []

    try:
        mtime_ns = os.stat(source_root).st_mtime_ns
    except OSError:
        mtime_ns = 0

    cached = _HEADERS_CACHE.get(project_id)
    if cached and cached[0] == mtime_ns:
        return cached[1]

    headers = cpp_class_parser.collect_headers(source_root)
    rels = sorted(
        os.path.relpath(h, source_root).replace(os.sep, "/")
        for h in headers
    )
    _HEADERS_CACHE[project_id] = (mtime_ns, rels)
    return rels


@router.get("/projects/{project_id}/headers")
async def list_headers(project_id: str, q: str = "", limit: int = 200):
    """列出项目内头文件，支持子串过滤。

    - q：小写不敏感的子串匹配，空串返回所有（截到 limit）
    - limit：最多返回条数，防止前端拖大列表
    """
    project = classdiag_store.get_project(project_id)
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
    """生成类图。

    流程：
      1. 扫源码目录 → 拿所有 ClassInfo（正则版）
      2. 按 class_name 匹配：优先严格全限定名匹配；否则按短名匹配
         - 0 命中 → 404
         - 多命中 → 409 返回候选列表（含 qualified_name / file / line）
         - 1 命中 → 走到 3
      3. 找目标类的直接父类（同项目内能找到定义的）
      4. 按 stage 决定是否跑 clang 增强：
         - stage='regex'：只跑正则。如果 clang 可用，`next_stage='clang'`
           提示前端可以再发一发拿增强。
         - stage='clang' 或 'auto'：如果 clang 可用则跑增强，否则退回正则并
           把 clang_status 置 'unavailable'。
      5. 组装 UML，落 last_query，返回给前端。
    """
    project = classdiag_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not project.get("source_zip_name"):
        raise HTTPException(status_code=400, detail="请先上传主源码 zip")
    query_name = (req.class_name or "").strip()
    if not query_name:
        raise HTTPException(status_code=400, detail="class_name 不能为空")

    stage_req = (req.stage or "auto").lower()
    if stage_req not in ("regex", "clang", "auto"):
        raise HTTPException(status_code=400, detail=f"未知 stage: {stage_req}")

    source_root = classdiag_store.source_absolute_path(project)
    # 把主源码 + 所有 include zip 都扫一遍：父类经常定义在 include zip 里
    # （用户报的 bug：只扫 source_dir 时，来自 include 的父类退回占位块，没成员）。
    # source_root 排前面，parse_projects 保证 include 内的同名类不会「抢」过来。
    include_roots = classdiag_store.include_absolute_paths(project)
    classes = cpp_class_parser.parse_projects([source_root, *include_roots])

    matches = _match_class(classes, query_name)
    if not matches:
        raise HTTPException(status_code=404, detail=f"未找到类 {query_name!r}")
    if len(matches) > 1:
        # 409 + 候选列表；前端弹 Modal 让用户改用全限定名
        return _multi_match_response(matches)

    target = matches[0]

    # depth 校验：默认 2，硬顶 10（防止用户手滑填 1000 把图撑爆）
    depth = int(req.depth or 2)
    if depth < 1:
        depth = 1
    elif depth > 10:
        depth = 10

    # 递归找祖先：从 target 出发，向上 depth 层，同项目内能找到定义的
    ancestors = _resolve_ancestors(target, classes, depth)

    # 决定是否走 clang 增强
    want_clang = stage_req in ("clang", "auto")
    clang_available = cpp_class_indexer.clang_available()
    clang_status = "unavailable"
    clang_diagnostics: list[str] = []
    executed_stage: str = "regex"

    if want_clang and clang_available:
        include_dirs = classdiag_store.include_absolute_paths(project)
        # 把 source_root 自身也加进 include，方便 #include "sub/foo.hpp"
        include_dirs = [source_root] + list(include_dirs)
        header_paths = [target.source_file, *(a.source_file for a in ancestors)]
        try:
            enriched_target, enriched_ancestors, diag = \
                await cpp_class_indexer.enrich_class_info_async(
                    target, ancestors, header_paths, include_dirs,
                )
            target = enriched_target
            ancestors = enriched_ancestors
            clang_status = diag.get("clang_status", "error")
            clang_diagnostics = diag.get("clang_diagnostics", [])
            executed_stage = "clang"
        except Exception as e:  # noqa: BLE001 - clang 出啥意外都要降级，不能弄挂请求
            clang_status = "error"
            clang_diagnostics = [f"clang 增强异常：{type(e).__name__}: {e}"]
            executed_stage = "regex"
    elif want_clang and not clang_available:
        # 用户点了「auto/clang」，但环境没 libclang——如实告知
        clang_status = "unavailable"
        clang_diagnostics = [
            f"libclang 未加载：{cpp_class_indexer.clang_init_error()}"
        ]
        executed_stage = "regex"

    uml = class_uml_emit.emit_class_diagram(target, ancestors, req.options or {})

    matched_headers = sorted({target.source_file, *(a.source_file for a in ancestors)})

    # next_stage：只有「用户显式选 regex」且 clang 可用时，才提示前端再跑一次拿增强。
    # auto/clang 分支要么已经跑过 clang，要么 clang 不可用，都没必要再来一发。
    next_stage: Optional[str] = None
    if stage_req == "regex" and clang_available:
        next_stage = "clang"

    def _pretty_header(h: str) -> str:
        # 头文件可能来自 source_root，也可能来自某个 include 目录（父类常见）。
        # 分别做前缀截断，返回带归属前缀的相对路径，前端好读。
        if h.startswith(source_root):
            return "source/" + os.path.relpath(h, source_root).replace(os.sep, "/")
        for inc_root in include_roots:
            if h.startswith(inc_root):
                inc_name = os.path.basename(inc_root)
                rel = os.path.relpath(h, inc_root).replace(os.sep, "/")
                return f"includes/{inc_name}/{rel}"
        return h  # 兜底：既不在 source 也不在 includes，返回绝对路径

    query_snapshot = {
        "class_name": query_name,
        "resolved_qualified_name": target.qualified_name,
        "options": req.options or {},
        "depth": depth,
        "matched_headers": [_pretty_header(h) for h in matched_headers],
        "clang_status": clang_status,
        "clang_diagnostics": clang_diagnostics,
        "uml": uml,
        "stage": executed_stage,
        "next_stage": next_stage,
    }
    classdiag_store.update_last_query(project_id, query_snapshot)
    return query_snapshot


# ---- 生成端点的内部辅助 ----

def _match_class(classes: list, query: str) -> list:
    """按 class_name 匹配 ClassInfo。

    - 优先精确全限定名匹配（去掉前导 `::` 后 == qualified_name）
    - 其次短名匹配（qualified_name.split("::")[-1] 去掉模板 == query）
    """
    q = query.lstrip(":")
    exact = [c for c in classes if c.qualified_name == q]
    if exact:
        return exact

    def short_of(name: str) -> str:
        return name.split("<", 1)[0].split("::")[-1]

    q_short = short_of(q)
    return [c for c in classes if short_of(c.qualified_name) == q_short]


def _multi_match_response(matches: list):
    """多命中：返回 409 + 候选列表。"""
    from fastapi.responses import JSONResponse
    body = {
        "detail": "存在多个同名类，请改用全限定名（Namespace::Class）",
        "matches": [
            {
                "qualified_name": c.qualified_name,
                "file": c.source_file,
                "line": c.line,
                "kind": c.kind,
            }
            for c in matches
        ],
    }
    return JSONResponse(status_code=409, content=body)


def _resolve_direct_parents(target, all_classes: list) -> list:
    """把 target.bases 里的名字尝试解析到 all_classes 中的 ClassInfo（只解一层）。

    匹配策略：先按 qualified_name 精确，再按 target namespace 前缀，
    最后按短名兜底。找不到的父类不返回；emit 层会给它们画占位块。
    """
    result = []
    seen: set[str] = set()
    for base in target.bases:
        # base.name 可能带 `::` / 模板参数
        cleaned = base.name.strip()
        # 去掉模板参数
        cleaned_noargs = cleaned.split("<", 1)[0]

        # 优先全限定名匹配（把 base 的名字放到 target 的 namespace 下试一试）
        candidates = []
        # 直接匹配
        candidates = [c for c in all_classes if c.qualified_name == cleaned_noargs]
        # 加上 target namespace 前缀试试（同 namespace 内引用不写完全限定）
        if not candidates and target.namespace_path:
            with_ns = "::".join(target.namespace_path + [cleaned_noargs])
            candidates = [c for c in all_classes if c.qualified_name == with_ns]
        # 短名匹配兜底
        if not candidates:
            short = cleaned_noargs.split("::")[-1]
            candidates = [c for c in all_classes
                          if c.qualified_name.split("::")[-1] == short]

        if candidates and candidates[0].qualified_name not in seen:
            result.append(candidates[0])
            seen.add(candidates[0].qualified_name)
    return result


def _resolve_ancestors(target, all_classes: list, depth: int) -> list:
    """从 target 向上追踪 `depth` 层祖先，返回**去重后**的全部祖先 ClassInfo。

    BFS：先解 target 的直接父类作为第 1 层；再对第 1 层每个类解它们的父类作为第 2 层；
    以此类推。同一个类只出现一次（菱形继承的祖先会被合并到最靠上层）。

    depth=1 表示只要直接父类，等同旧的 `_resolve_parents`；
    depth=2 是默认，覆盖「父类 + 祖父类」这个最常见的深度需求。

    Args:
        target: 起点类
        all_classes: 全项目的 ClassInfo 池
        depth: 追踪层数（>=1；`/generate` 端点已做 1..10 clamp）

    Returns:
        列表，按 BFS 顺序排列（近的祖先在前，远的在后）。**不含 target 自己**。
    """
    result: list = []
    seen: set[str] = {target.qualified_name}  # target 自己算「已见」防止环
    frontier: list = [target]

    for _ in range(depth):
        next_frontier: list = []
        for node in frontier:
            for parent in _resolve_direct_parents(node, all_classes):
                if parent.qualified_name in seen:
                    continue
                seen.add(parent.qualified_name)
                result.append(parent)
                next_frontier.append(parent)
        if not next_frontier:
            break  # 到顶了，早退省一层空循环
        frontier = next_frontier
    return result


# ---- 内部工具 ----

def _cleanup(path: str) -> None:
    """尽力删掉临时文件，忽略失败（比如已经不在）。"""
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass
