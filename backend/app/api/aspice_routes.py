"""
ASPICE 文档模块 API 路由。

提供 SWE.1 需求分析 / SWE.2 架构设计的生成、保存、导出接口。
与 creator 模块共享同一项目实体（runtime/creator_projects/<id>/project.json）。
"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import os

from app.core import creator_store
from app.core import id_chain
from app.core import req_generator
from app.core import arch_generator
from app.core.config_store import ConfigStore
from app.core.test_case import AIConfig

router = APIRouter()

_global_config_store = ConfigStore(base_dir="runtime")


def _get_ai_service():
    from app.ai.service import AIService
    ai_config = _global_config_store.load("ai_config", AIConfig, AIConfig())
    return AIService(ai_config.model_dump())


# ---- 请求模型 ----

class CreateAspiceProjectRequest(BaseModel):
    name: str


class SaveSwe1Request(BaseModel):
    project_code: Optional[str] = None
    requirements: Optional[list] = None
    topology: Optional[list] = None
    kpi: Optional[list] = None
    current_step: Optional[int] = None


class SaveSwe2Request(BaseModel):
    mappings: Optional[list] = None
    components: Optional[list] = None
    current_step: Optional[int] = None


class SaveAspiceRequest(BaseModel):
    project_code: Optional[str] = None
    swe1: Optional[dict] = None
    swe2: Optional[dict] = None


class GenerateReqRequest(BaseModel):
    raw_text: str
    use_ai: bool = True


# ---- 项目级 ----

@router.get("/projects")
async def list_aspice_projects():
    """列出 ASPICE 文档项目。"""
    return creator_store.list_projects(project_type="aspice")


@router.post("/projects")
async def create_aspice_project(req: CreateAspiceProjectRequest):
    """创建 ASPICE 文档项目。"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    return creator_store.create_project(req.name.strip(), project_type="aspice")


@router.get("/projects/{project_id}")
async def get_aspice_project(project_id: str):
    """获取项目的 ASPICE 数据段。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice")
    if not aspice:
        aspice = creator_store._default_aspice()
        project["aspice"] = aspice
        creator_store.save_project(project)
    return aspice


@router.put("/projects/{project_id}")
async def save_aspice_project(project_id: str, req: SaveAspiceRequest):
    """一次性保存完整 ASPICE 数据段，避免 SWE.1/SWE.2 分两次落盘。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice") or creator_store._default_aspice()
    update = req.model_dump(exclude_none=True)
    if "project_code" in update:
        aspice["project_code"] = update["project_code"]
    if "swe1" in update:
        aspice["swe1"] = {**aspice.get("swe1", {}), **update["swe1"]}
    if "swe2" in update:
        aspice["swe2"] = {**aspice.get("swe2", {}), **update["swe2"]}
    project["aspice"] = aspice
    creator_store.save_project(project)
    return {"message": "已保存"}


@router.put("/projects/{project_id}/swe1")
async def save_swe1(project_id: str, req: SaveSwe1Request):
    """保存 SWE.1 数据。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice") or creator_store._default_aspice()
    swe1 = aspice.get("swe1", {})
    update = req.model_dump(exclude_none=True)
    if "project_code" in update:
        aspice["project_code"] = update.pop("project_code")
    for k, v in update.items():
        swe1[k] = v
    aspice["swe1"] = swe1
    project["aspice"] = aspice
    creator_store.save_project(project)
    return {"message": "已保存"}


@router.put("/projects/{project_id}/swe2")
async def save_swe2(project_id: str, req: SaveSwe2Request):
    """保存 SWE.2 数据。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice") or creator_store._default_aspice()
    swe2 = aspice.get("swe2", {})
    update = req.model_dump(exclude_none=True)
    for k, v in update.items():
        swe2[k] = v
    aspice["swe2"] = swe2
    project["aspice"] = aspice
    creator_store.save_project(project)
    return {"message": "已保存"}


# ---- SWE.1 需求解析 ----

@router.post("/projects/{project_id}/swe1/parse-requirements")
async def parse_requirements(project_id: str, request: Request):
    """AI 解析客户原始需求（文本 + 可选多文件上传）→ 结构化需求项。

    文件支持 txt/docx/xlsx/pdf；AI 失败时规则兜底。
    手动读取 multipart，避免多文件字段在不同 FastAPI/Pydantic 版本下触发 422。
    """
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice") or creator_store._default_aspice()
    project_code = aspice.get("project_code", "") or project.get("name", "")

    form = await request.form()
    raw_text = str(form.get("text", "") or "")
    upload_files = []
    for field_name in ("files", "file"):
        for item in form.getlist(field_name):
            if hasattr(item, "filename") and hasattr(item, "read"):
                upload_files.append(item)

    # 文件解析
    for upload in upload_files:
        content = await upload.read()
        safe_name = os.path.basename(upload.filename or "")
        file_text = _extract_file_text(content, safe_name)
        if file_text:
            raw_text = (raw_text + "\n" + file_text).strip() if raw_text else file_text

    if not raw_text:
        raise HTTPException(status_code=400, detail="需求文本为空，请粘贴或上传客户需求")

    existing = aspice.get("swe1", {}).get("requirements", [])

    # AI 解析
    use_ai = True
    source = "rule"
    ai_error: Optional[str] = None
    req_items = []

    if use_ai:
        try:
            ai_service = _get_ai_service()
            if ai_service.enabled:
                ai_result = await ai_service.parse_requirements(raw_text, project_code)
                if ai_result and "_error" not in ai_result:
                    parsed = ai_result.get("requirements", [])
                    req_items = _assign_ids(parsed, project_code, existing)
                    source = "ai"
                else:
                    ai_error = (ai_result or {}).get("_error", "AI 解析失败")
        except Exception as e:
            ai_error = f"AI 调用异常: {str(e)}"

    # 规则兜底
    if not req_items:
        req_items = req_generator.generate_requirements(raw_text, project_code, existing)

    return {
        "source": source,
        "count": len(req_items),
        "requirements": req_items,
        "ai_error": ai_error,
    }


def _assign_ids(parsed: list, project_code: str, existing: list) -> list:
    """给 AI 解析出的需求项自动分配 OR ID + ReqID。"""
    if not parsed:
        return []
    existing_or_max = id_chain.next_or_seq(existing) - 1
    result = []
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue
        or_seq = existing_or_max + i + 1
        or_id = id_chain.derive_or(project_code, or_seq)
        req_id = id_chain.derive_req(or_id, 1)
        priority = int(item.get("priority", 2)) if str(item.get("priority", "")).isdigit() else 2
        priority = min(max(priority, 1), 3)
        result.append({
            "or_id": or_id,
            "req_id": req_id,
            "software_mark": "原始",
            "content": str(item.get("content", "")),
            "or_desc": str(item.get("or_desc", "")),
            "sw_req_desc": str(item.get("sw_req_desc", "")),
            "category": _normalize_requirement_category(str(item.get("category", ""))),
            "asil": _normalize_asil(str(item.get("asil", "QM"))),
            "correctness": "Correct",
            "feasibility": "Feasible",
            "exception": "N/A",
            "milestone": str(item.get("milestone", "")),
            "owner": str(item.get("owner", "")),
            "input_source": "客户原始需求",
            "priority": priority,
            "actual_time": "NA",
            "release_version": "V1.0",
            "operation": str(item.get("operation", "")),
            "analysis": str(item.get("analysis", "")),
        })
    return result


def _normalize_requirement_category(category: str) -> str:
    """兼容旧 prompt 分类，归一化为 skill 枚举。"""
    mapping = {
        "Driver Basic Function": "Functional Requirements，Basic Functions",
        "Driver Safety Function": "Functional Requirements，Safety Requirements",
        "Driver Cybersecurity": "Functional Requirements，Cybersecurity Requirements",
        "Non-functional": "Non-Functional Requirements",
        "Non-camera": "Non-camera driver/tuning requirements",
        "基础功能": "Functional Requirements，Basic Functions",
        "安全需求": "Functional Requirements，Safety Requirements",
        "网络安全": "Functional Requirements，Cybersecurity Requirements",
        "非功能需求": "Non-Functional Requirements",
        "非Camera驱动": "Non-camera driver/tuning requirements",
    }
    options = {
        "Functional Requirements，Basic Functions",
        "Functional Requirements，Safety Requirements",
        "Functional Requirements，Cybersecurity Requirements",
        "Non-Functional Requirements",
        "Non-camera driver/tuning requirements",
    }
    if category in options:
        return category
    return mapping.get(category, "Functional Requirements，Basic Functions")


def _normalize_asil(asil: str) -> str:
    """归一化 ASIL 安全等级。"""
    value = asil.strip().upper().replace("ASIL-", "ASIL ")
    if value in {"QM", "N/A", "ASIL A", "ASIL B", "ASIL C", "ASIL D"}:
        return value
    if value in {"A", "B", "C", "D"}:
        return f"ASIL {value}"
    return "QM"


def _extract_file_text(content: bytes, filename: str) -> str:
    """从上传文件提取纯文本（txt/docx/xlsx）。"""
    import warnings
    warnings.filterwarnings("ignore")
    try:
        lower = filename.lower()
        if lower.endswith(".txt"):
            return content.decode("utf-8", errors="ignore")
        if lower.endswith(".docx"):
            import docx
            import io
            d = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in d.paragraphs if p.text.strip())
        if lower.endswith((".xlsx", ".xls")):
            import openpyxl
            import io
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            lines = []
            for sn in wb.sheetnames:
                ws = wb[sn]
                for row in ws.iter_rows(values_only=True):
                    vals = [str(c) for c in row if c is not None]
                    if vals:
                        lines.append("\t".join(vals))
            return "\n".join(lines)
        if lower.endswith(".pdf"):
            try:
                import io
                import pdfplumber
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    return "\n".join(p.extract_text() or "" for p in pdf.pages)
            except ImportError:
                return ""
    except Exception:
        return ""
    return ""


# ---- SWE.2 映射生成 ----

@router.post("/projects/{project_id}/swe2/generate")
async def generate_swe2(project_id: str, use_ai: bool = Query(True)):
    """基于 SWE.1 需求自动生成 SWE.2 映射表（规则兜底 + AI 增强）。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice") or creator_store._default_aspice()
    requirements = aspice.get("swe1", {}).get("requirements", [])
    if not requirements:
        raise HTTPException(status_code=400, detail="SWE.1 需求为空，请先完成需求分析")

    existing = aspice.get("swe2", {}).get("mappings", [])

    # 规则生成
    mappings = arch_generator.generate_mappings(requirements, existing=[])

    # AI 增强（可调整组件归属、补接口描述）
    source = "rule"
    ai_error: Optional[str] = None
    if use_ai:
        try:
            ai_service = _get_ai_service()
            if ai_service.enabled:
                ai_result = await ai_service.generate_arch_draft(requirements)
                if ai_result and "_error" not in ai_result:
                    ai_maps = ai_result.get("mappings", [])
                    if ai_maps:
                        mappings = _merge_ai_mappings(ai_maps, requirements, existing)
                        source = "ai"
                else:
                    ai_error = (ai_result or {}).get("_error", "AI 生成失败")
        except Exception as e:
            ai_error = f"AI 调用异常: {str(e)}"

    # 保存
    swe2 = aspice.get("swe2", {})
    swe2["mappings"] = mappings
    aspice["swe2"] = swe2
    project["aspice"] = aspice
    creator_store.save_project(project)

    return {
        "source": source,
        "count": len(mappings),
        "mappings": mappings,
        "ai_error": ai_error,
    }


def _merge_ai_mappings(ai_maps: list, requirements: list, existing: list) -> list:
    """把 AI 返回的映射建议转换为完整 mappings（带 swe2_id）。"""
    from app.core.arch_generator import _COMPONENTS
    merged = list(existing)
    for am in ai_maps:
        if not isinstance(am, dict):
            continue
        req_id = am.get("req_id", "")
        comp_ids = am.get("component_ids", [])
        iface = am.get("interface_desc", "")
        for comp_id in comp_ids:
            comp_id = comp_id if comp_id.startswith("A") else f"A{comp_id}"
            a_seq = id_chain.next_arch_seq(merged, req_id)
            swe2_id = id_chain.derive_arch(req_id, a_seq)
            merged.append({
                "swe1_id": req_id,
                "swe2_id": swe2_id,
                "component_id": comp_id,
                "component": _COMPONENTS.get(comp_id, ""),
                "description": iface,
                "release_version": "V1.0",
            })
    return merged


# ---- 导出 ----

@router.post("/projects/{project_id}/swe1/export")
async def export_swe1(project_id: str):
    """导出 SWE.1：需求说明书 docx + 需求详细表 xlsx。

    经 aspice_adapter 转 skill project.json，调 build_docx / build_excel
    填充双语四小节 SRS docx 模板 + 24 列 7 sheet xlsx 模板。
    """
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    out_dir = os.path.join("runtime", "creator_projects", project_id, "output")
    os.makedirs(out_dir, exist_ok=True)

    code = (project.get("aspice") or {}).get("project_code", "") or project.get("name", "")
    safe_code = code.replace("/", "_").replace("\\", "_")
    docx_path = os.path.join(out_dir, f"{safe_code}_软件需求说明书.docx")
    xlsx_path = os.path.join(out_dir, f"{safe_code}_需求详细表.xlsx")

    try:
        req_generator.export_swe1_docx(project, docx_path)
        req_generator.export_swe1_xlsx(project, xlsx_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")

    return {
        "docx": os.path.basename(docx_path),
        "xlsx": os.path.basename(xlsx_path),
    }


# ---- 校验 ----

@router.post("/projects/{project_id}/swe1/validate")
async def validate_swe1(project_id: str):
    """校验 SWE.1：经 aspice_adapter 转 skill project.json 后调 aspice_validate。

    V01-V18 校验：ID 格式/连续/唯一、Input↔inputs 一致、Deleted 话术、
    SRS 覆盖率、双语完整等。返回 errors/warnings/passed/report。
    """
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from app.core import aspice_adapter
    from app.core import aspice_validate

    skill_json = aspice_adapter.to_skill_project(project)

    # 可选：对已导出的 xlsx/docx 做往返校验（V14/V15）
    out_dir = os.path.join("runtime", "creator_projects", project_id, "output")
    code = (project.get("aspice") or {}).get("project_code", "") or project.get("name", "")
    safe_code = code.replace("/", "_").replace("\\", "_")
    excel_path = os.path.join(out_dir, f"{safe_code}_需求详细表.xlsx")
    docx_path = os.path.join(out_dir, f"{safe_code}_软件需求说明书.docx")
    excel_path = excel_path if os.path.isfile(excel_path) else None
    docx_path = docx_path if os.path.isfile(docx_path) else None

    try:
        result = aspice_validate.validate_project(
            skill_json, excel_path=excel_path, docx_path=docx_path,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"校验失败: {str(e)}")

    return result


@router.post("/projects/{project_id}/swe2/export")
async def export_swe2(project_id: str):
    """导出 SWE.2：架构&概要设计书 docx + 映射表 xlsx。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    out_dir = os.path.join("runtime", "creator_projects", project_id, "output")
    os.makedirs(out_dir, exist_ok=True)

    code = (project.get("aspice") or {}).get("project_code", "") or project.get("name", "")
    safe_code = code.replace("/", "_").replace("\\", "_")
    docx_path = os.path.join(out_dir, f"{safe_code}_软件架构&概要设计书.docx")
    xlsx_path = os.path.join(out_dir, f"{safe_code}_架构映射表.xlsx")

    try:
        arch_generator.export_swe2_docx(project, docx_path)
        arch_generator.export_swe2_xlsx(project, xlsx_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")

    return {
        "docx": os.path.basename(docx_path),
        "xlsx": os.path.basename(xlsx_path),
    }


# ---- 下载 ----

@router.get("/projects/{project_id}/download/{filename}")
async def download_file(project_id: str, filename: str):
    """下载导出的文件。"""
    path = creator_store.get_download_path(project_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
