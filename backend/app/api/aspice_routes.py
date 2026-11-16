"""
ASPICE 文档模块 API 路由。

提供 SWE.1 需求分析 / SWE.2 架构设计 / SWE.3 详细设计的生成、保存、导出接口。
与 creator 模块共享同一项目实体（runtime/creator_projects/<id>/project.json）。
"""
from fastapi import APIRouter, HTTPException, Request, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import logging
import os

from app.core import creator_store
from app.core import id_chain
from app.core import req_generator
from app.core import arch_generator
from app.core.config_store import ConfigStore
from app.core.test_case import AIConfig

router = APIRouter()
logger = logging.getLogger(__name__)

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
    # 推送 A 新增：概述元数据 + 系统集成
    overview: Optional[dict] = None
    integration: Optional[dict] = None


class SaveSwe3Request(BaseModel):
    """SWE.3 详细设计保存：所有字段均可选，覆盖式更新。"""
    project_code: Optional[str] = None
    overview: Optional[dict] = None
    terms: Optional[list] = None
    composition: Optional[dict] = None
    modules: Optional[list] = None
    performance: Optional[dict] = None
    function_evaluation: Optional[dict] = None
    common_defs: Optional[dict] = None
    integration: Optional[dict] = None
    current_step: Optional[int] = None
    # 推送 D 子结构（整体覆盖）
    push_d: Optional[dict] = None


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


@router.get("/projects/{project_id}/info")
async def get_aspice_project_info(project_id: str):
    """获取项目基本信息（名称等），供向导页加载。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {
        "project_id": project.get("project_id", project_id),
        "project_type": project.get("project_type", "aspice"),
        "name": project.get("name", ""),
        "created_at": project.get("created_at", ""),
        "updated_at": project.get("updated_at", ""),
    }


@router.delete("/projects/{project_id}")
async def delete_aspice_project(project_id: str):
    """删除项目（项目实体与其他模块共享）。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    creator_store.delete_project(project_id)
    return {"message": "已删除"}


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


@router.put("/projects/{project_id}/swe3")
async def save_swe3(project_id: str, req: SaveSwe3Request):
    """保存 SWE.3 详细设计数据（覆盖式写入 aspice.swe3 子字段）。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice") or creator_store._default_aspice()
    swe3 = aspice.get("swe3") or {}
    update = req.model_dump(exclude_none=True)

    # project_code 单独同步到 aspice 顶层（与 SWE.1/SWE.2 一致）
    if "project_code" in update:
        aspice["project_code"] = update.pop("project_code")

    for k, v in update.items():
        swe3[k] = v
    aspice["swe3"] = swe3
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


def _component_id_from_swe2_id(swe2_id: str) -> str:
    """从 SWE.2 ID 末尾提取 A### 组件编号。"""
    import re
    m = re.search(r"-(A\d{3})$", swe2_id or "")
    return m.group(1) if m else ""


def _component_id_from_name(name: str) -> str:
    """按组件名反查 A###，兼容用户编辑后的映射表。"""
    text = (name or "").strip().lower()
    for cid, cname in arch_generator._COMPONENTS.items():
        if text == cname.lower() or cname.lower() in text:
            return cid
    return ""


def _default_swe2_components() -> list[dict]:
    """返回默认 8 组件属性，供 xlsx/docx 回灌共用。"""
    return [dict(c) for c in creator_store._default_aspice()["swe2"]["components"]]


def _build_swe2_mapping(
    swe1_id: str,
    swe2_id: str,
    component: str,
    description: str,
    release_version: str,
) -> Optional[dict]:
    """规范化一行 SWE.2 映射，兼容从 xlsx/docx 表格读取的空值。"""
    swe1_id = (swe1_id or "").strip()
    swe2_id = (swe2_id or "").strip()
    component = (component or "").strip()
    description = (description or "").strip()
    release_version = (release_version or "").strip()
    if not swe1_id and not swe2_id and not component:
        return None

    component_id = _component_id_from_swe2_id(swe2_id) or _component_id_from_name(component)
    if not component_id:
        component_id = "A004"
    if not component:
        component = arch_generator._COMPONENTS.get(component_id, "")
    if not swe2_id and swe1_id:
        swe2_id = f"{swe1_id}-{component_id}"

    return {
        "swe1_id": swe1_id,
        "swe2_id": swe2_id,
        "component_id": component_id,
        "component": component,
        "description": description,
        "release_version": release_version or "V1.0",
    }


def _dedupe_swe2_mappings(mappings: list[dict]) -> list[dict]:
    """按核心字段去重，兼容 docx 合并单元格造成的重复行。"""
    seen = set()
    unique = []
    for item in mappings:
        key = (
            item.get("swe1_id", ""),
            item.get("swe2_id", ""),
            item.get("component", ""),
            item.get("description", ""),
            item.get("release_version", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _parse_swe2_xlsx(path: str) -> tuple[list[dict], list[dict]]:
    """解析 SWE.2 导出的架构映射表 xlsx，返回 mappings/components。"""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    mappings: list[dict] = []
    if "需求映射" in wb.sheetnames:
        ws = wb["需求映射"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            mapping = _build_swe2_mapping(
                str(row[0] or "") if len(row) > 0 else "",
                str(row[1] or "") if len(row) > 1 else "",
                str(row[2] or "") if len(row) > 2 else "",
                str(row[3] or "") if len(row) > 3 else "",
                str(row[4] or "") if len(row) > 4 else "",
            )
            if mapping:
                mappings.append(mapping)

    default_components = _default_swe2_components()
    comp_by_name = {c["name"]: dict(c) for c in default_components}
    if "组件属性" in wb.sheetnames:
        ws = wb["组件属性"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            comp_name = str(row[0] or "").strip() if len(row) > 0 else ""
            attr = str(row[1] or "").strip() if len(row) > 1 else ""
            value = str(row[2] or "").strip() if len(row) > 2 else ""
            if not comp_name or comp_name not in comp_by_name:
                continue
            attr_key = attr.lower()
            if attr_key == "name" and value:
                comp_by_name[comp_name]["name"] = value
            elif attr_key in {"i2c address", "i2c地址", "i2c_addr"}:
                comp_by_name[comp_name]["i2c_addr"] = value
            elif attr_key in {"model", "型号"}:
                comp_by_name[comp_name]["model"] = value

    return _dedupe_swe2_mappings(mappings), list(comp_by_name.values())


def _cell_text(cell) -> str:
    """读取 docx 表格单元格文本，合并内部换行。"""
    return "\n".join(p.text.strip() for p in cell.paragraphs if p.text.strip()).strip()


def _parse_swe2_docx(path: str) -> tuple[list[dict], list[dict]]:
    """解析 SWE.2 架构设计书 docx 中的需求映射表。"""
    from docx import Document

    doc = Document(path)
    mappings: list[dict] = []
    for table in doc.tables:
        if not table.rows:
            continue
        headers = [_cell_text(cell) for cell in table.rows[0].cells]
        normalized = [h.replace("\n", "").replace(" ", "") for h in headers]
        has_mapping_header = (
            any("SWE.1" in h for h in normalized)
            and any("SWE.2" in h for h in normalized)
            and any("ID含义" in h or "组件" in h for h in normalized)
        )
        if not has_mapping_header:
            continue

        def find_col(*names: str) -> int:
            for idx, header in enumerate(normalized):
                if any(name in header for name in names):
                    return idx
            return -1

        swe1_col = find_col("SWE.1")
        swe2_col = find_col("SWE.2")
        comp_col = find_col("ID含义", "组件")
        desc_col = find_col("备注", "描述")
        ver_col = find_col("发布版本", "版本")
        for row in table.rows[1:]:
            cells = [_cell_text(cell) for cell in row.cells]
            mapping = _build_swe2_mapping(
                cells[swe1_col] if 0 <= swe1_col < len(cells) else "",
                cells[swe2_col] if 0 <= swe2_col < len(cells) else "",
                cells[comp_col] if 0 <= comp_col < len(cells) else "",
                cells[desc_col] if 0 <= desc_col < len(cells) else "",
                cells[ver_col] if 0 <= ver_col < len(cells) else "",
            )
            if mapping:
                mappings.append(mapping)

    return _dedupe_swe2_mappings(mappings), _default_swe2_components()


@router.post("/projects/{project_id}/swe2/import")
async def import_swe2(project_id: str, file: UploadFile = File(...)):
    """回灌导入 SWE.2 架构映射表/架构设计书，写回 mappings/components 供继续编辑。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    safe_name = os.path.basename(file.filename or "swe2_import.xlsx")
    lower_name = safe_name.lower()
    if not lower_name.endswith((".xlsx", ".xls", ".docx")):
        raise HTTPException(status_code=400, detail="SWE.2 回灌支持 .xlsx/.xls 映射表或 .docx 架构设计书")

    out_dir = os.path.join("runtime", "creator_projects", project_id, "output")
    os.makedirs(out_dir, exist_ok=True)
    import_path = os.path.join(out_dir, f"导入SWE2_{safe_name}")
    content = await file.read()
    with open(import_path, "wb") as f:
        f.write(content)

    try:
        if lower_name.endswith(".docx"):
            mappings, components = _parse_swe2_docx(import_path)
        else:
            mappings, components = _parse_swe2_xlsx(import_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SWE.2 文件解析失败: {str(e)}")

    if not mappings and not components:
        raise HTTPException(status_code=400, detail="未解析到 SWE.2 映射或组件属性，请检查文件格式")

    aspice = project.get("aspice") or creator_store._default_aspice()
    swe2 = aspice.get("swe2", {})
    if mappings:
        swe2["mappings"] = mappings
    if components:
        swe2["components"] = components
    swe2["current_step"] = max(int(swe2.get("current_step") or 0), 1)
    aspice["swe2"] = swe2
    project["aspice"] = aspice
    creator_store.save_project(project)

    return {
        "count": len(mappings),
        "component_count": len(components),
        "mappings": mappings,
        "components": components,
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
        # ASPICE_TEMPLATE_ENGINE=v2 走 docxtpl 模板引擎（推送 E 默认开启），
        # 其他值走旧的 python-docx 手工拼装（DEPRECATED，用于回滚）
        engine = os.getenv("ASPICE_TEMPLATE_ENGINE", "v2").strip().lower()
        if engine == "v2":
            arch_generator.export_swe2_docx_v2(project, docx_path)
        else:
            arch_generator.export_swe2_docx(project, docx_path)
        arch_generator.export_swe2_xlsx(project, xlsx_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")

    return {
        "docx": os.path.basename(docx_path),
        "xlsx": os.path.basename(xlsx_path),
    }


# ---- SWE.3 详细设计 ----

@router.post("/projects/{project_id}/swe3/generate")
async def generate_swe3(project_id: str):
    """根据 SWE.2 映射表派生 SWE.3 第 3 章模块构成追溯行，并补齐 9 模块骨架。

    不调 AI，仅做规则派生 + 读时迁移中已完成的默认模块结构的填充。
    """
    from app.core import arch_sections_swe3

    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    aspice = project.get("aspice") or creator_store._default_aspice()
    swe2 = aspice.get("swe2") or {}
    swe3 = aspice.get("swe3") or {}

    # 派生第 3 章模块构成（SWE.1→SWE.2→类→SWE.3）
    comp_rows = arch_sections_swe3.build_composition_from_swe2(swe2)
    composition = swe3.get("composition") or {}
    composition["composition_rows"] = comp_rows
    swe3["composition"] = composition

    # modules 为空时按 SWE.2 组件补齐
    if not swe3.get("modules"):
        swe3["modules"] = arch_sections_swe3.default_swe3(
            swe2.get("components") or []
        ).get("modules", [])

    aspice["swe3"] = swe3
    project["aspice"] = aspice
    creator_store.save_project(project)

    return {
        "message": "已派生",
        "composition_rows": len(comp_rows),
        "modules": len(swe3.get("modules") or []),
    }


@router.post("/projects/{project_id}/swe3/export")
async def export_swe3(project_id: str, auto_augment: bool = True):
    """导出 SWE.3：详细设计 docx（14 章骨架）+ 清单 xlsx（6 个 sheet）。

    docx 生成会按模块数向 plantuml.com 发同步请求渲染 PNG，9 个模块 * 多张图可能耗时
    数十秒；用 asyncio.to_thread 丢到线程池，避免阻塞事件循环影响其他请求。

    `auto_augment=True`（默认）：导出前对"关注函数里 ai_intro 为空"的逐个补齐介绍；
    流程图相同策略，但函数体 > 80 行的复杂函数直接跳过（复杂图嵌入 docx 又大又糊）。
    关掉可通过 `?auto_augment=false` 快速导出"已有内容"版本。
    """
    import asyncio
    from app.core import arch_generator_swe3

    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    out_dir = os.path.join("runtime", "creator_projects", project_id, "output")
    os.makedirs(out_dir, exist_ok=True)

    # 导出前预热 AI：对所有关注函数，若 ai_intro / ai_flowchart 空则调 AI 补齐
    # 失败不中断导出（在 docx 里显示占位）。只对函数体 ≤ 80 行的跑流程图，避免复杂图糊
    if auto_augment:
        try:
            summary = await _auto_augment_focus_functions(project_id, project)
            if summary["augmented_intro"] or summary["augmented_flow"] or summary["skipped_complex"]:
                logger.info("导出前预热 AI 完成 project=%s: %s", project_id, summary)
        except Exception as e:  # noqa: BLE001
            logger.warning("导出前预热 AI 异常（继续导出）project=%s: %s", project_id, e)

    try:
        # ASPICE_TEMPLATE_ENGINE=v3 走骨架拼装路径（推送 H 默认开启），
        # v2 走 docxtpl 模板引擎（F1 推送）用于回滚，
        # 其他值走旧的 _render_function_detail 1500 行手工拼装（DEPRECATED）
        engine = os.getenv("ASPICE_TEMPLATE_ENGINE", "v3").strip().lower()
        if engine == "v3":
            from app.core import arch_generator_swe3_v3
            files = await asyncio.to_thread(
                arch_generator_swe3_v3.export_swe3, project, out_dir
            )
        elif engine == "v2":
            files = await asyncio.to_thread(
                arch_generator_swe3.export_swe3_v2, project, out_dir
            )
        else:
            files = await asyncio.to_thread(
                arch_generator_swe3.export_swe3, project, out_dir
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")

    return files


# ---- 下载 ----

@router.get("/projects/{project_id}/download/{filename}")
async def download_file(project_id: str, filename: str):
    """下载导出的文件。"""
    path = creator_store.get_download_path(project_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")


# =====================================================================
# ===========  SWE.3 推送 D — 工程代码 / 关注函数 / AI  端点  ===========
# =====================================================================

from app.core import engineering_store, code_scanner  # noqa: E402
from app.core.zip_utils import UnsafeArchive, UploadTooLarge  # noqa: E402
from app.core.engineering_store import TreeUploadError  # noqa: E402


def _get_push_d(project: dict) -> dict:
    """从 project 读 swe3.push_d；缺则按默认初始化并写回 project。"""
    aspice = project.setdefault("aspice", creator_store._default_aspice())
    swe3 = aspice.setdefault("swe3", {})
    if not isinstance(swe3.get("push_d"), dict):
        from app.core import arch_sections_swe3
        swe3["push_d"] = arch_sections_swe3.default_push_d()
    return swe3["push_d"]


def _upsert_by_component(items: list[dict], item: dict) -> list[dict]:
    """用 component_id 做主键做覆盖式 upsert。"""
    cid = item.get("component_id")
    found = False
    out: list[dict] = []
    for it in items or []:
        if it.get("component_id") == cid:
            out.append(item); found = True
        else:
            out.append(it)
    if not found:
        out.append(item)
    return out


def _scan_or_404(project_id: str, component_id: str) -> dict:
    """读取 scan_cache；缺失时抛带诊断信息的 404。

    截图里 A003 EEPROM 焦点列表有 12 行，但 scan_cache/A003.json 并不存在 — 用户
    点"生成"时就会收到无上下文的 404。这里把失败消息改成能直指下一步的提示。
    """
    scan = engineering_store.read_scan_cache(project_id, component_id)
    if scan is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"模块 {component_id} 未扫描 — 请回到「推送 D / 工程切片」上传源码 zip "
                f"或指定 src_root 后点击该模块的「扫描/重扫」按钮。"
            ),
        )
    return scan


def _find_fn_or_404(scan: dict, component_id: str, key: str) -> tuple[dict, str, str]:
    """定位函数；返回 (fn, scope, file_path)。未找到时抛带诊断信息的 404。"""
    from app.core import code_scanner
    fn = code_scanner.find_function_by_key(scan, key)
    if fn is None:
        # 看看 scan_cache 共有多少 key 便于用户判断该不该重扫
        total = sum(len(c.get("functions") or [])
                    for f in scan.get("files") or []
                    for c in f.get("classes") or [])
        raise HTTPException(
            status_code=404,
            detail=(
                f"函数 key 在模块 {component_id} 的扫描结果里找不到（扫描共 {total} 个函数）— "
                f"可能是源码改动后 key 的 hash 变了；请在「推送 D」重扫该模块后重试。"
                f" key={key}"
            ),
        )
    # 回查 scope + file
    for file_info in scan.get("files") or []:
        for cls in file_info.get("classes") or []:
            for f in cls.get("functions") or []:
                if f.get("key") == key:
                    return fn, cls.get("name", "__free__"), file_info.get("path", "")
    return fn, "__free__", ""


def _ensure_focus_key(push_d: dict, component_id: str, key: str) -> bool:
    """确保 push_d.focus_functions[cid].focused_keys 里包含该 key。返回 True 表示有改动。

    AI 生成成功后调用：把"隐式关注"(scan_cache.ai_flowchart 字段) 升级成"显式关注"
    (push_d.focus_functions.focused_keys)，这样即使日后 scan_cache 被重扫、ai_flowchart
    字段被清理，bridge 仍能通过 focused_keys 把该函数路由到 functions[] 嵌入 PNG。
    """
    if not component_id or not key:
        return False
    key = str(key).strip()
    cid = str(component_id).strip()
    if not key or not cid:
        return False
    focus_list = push_d.get("focus_functions") or []
    for item in focus_list:
        if (item.get("component_id") or "").strip() == cid:
            keys = item.setdefault("focused_keys", []) or []
            if key in keys:
                return False
            keys.append(key)
            item["focused_keys"] = keys
            return True
    # cid 不存在 → 新建条目
    focus_list.append({
        "component_id": cid,
        "focused_keys": [key],
        "manual_additions": [],
    })
    push_d["focus_functions"] = focus_list
    return True


# 导出 docx 前的"AI 预热"阈值：函数体 > 80 行视为复杂，跳过流程图生成（避免图又大又糊）
_AUTO_AUGMENT_FLOW_BODY_LIMIT = 80


async def _auto_augment_focus_functions(project_id: str, project: dict) -> dict:
    """遍历所有关注函数，对 ai_intro 为空的调 AI 生成；对 ai_flowchart 为空且 body_lines ≤ 阈值
    的调 AI 生成；复杂（>80 行）函数跳过。所有结果写回 scan_cache。

    返回统计 dict：{augmented_intro, augmented_flow, skipped_complex, failed, scanned_modules}
    """
    from app.core.swe3_ai import Swe3AI

    push_d = _get_push_d(project)
    focus_list = push_d.get("focus_functions") or []
    if not focus_list:
        return {"augmented_intro": 0, "augmented_flow": 0, "skipped_complex": 0,
                "failed": 0, "scanned_modules": 0}

    try:
        svc = Swe3AI(_get_ai_service())
    except Exception as e:  # noqa: BLE001
        logger.warning("自动预热 AI 初始化失败，跳过：%s", e)
        return {"augmented_intro": 0, "augmented_flow": 0, "skipped_complex": 0,
                "failed": 0, "scanned_modules": 0}

    stats = {"augmented_intro": 0, "augmented_flow": 0, "skipped_complex": 0,
             "failed": 0, "scanned_modules": 0}
    scan_by_cid: dict[str, dict] = {}

    for ff in focus_list:
        cid = (ff.get("component_id") or "").strip()
        if not cid:
            continue
        scan = engineering_store.read_scan_cache(project_id, cid)
        if not scan:
            logger.info("自动预热 AI：%s 未扫描，跳过", cid)
            continue
        scan_by_cid[cid] = scan
        stats["scanned_modules"] += 1

        focused_keys = {str(k).strip() for k in (ff.get("focused_keys") or []) if k}
        focused_keys |= {str(k).strip() for k in (ff.get("manual_additions") or []) if k}

        # 遍历 scan 内所有关注函数
        for file_info in scan.get("files") or []:
            fpath = file_info.get("path", "")
            for cls in file_info.get("classes") or []:
                cname = cls.get("name", "__free__")
                for fn in cls.get("functions") or []:
                    if fn.get("key") not in focused_keys:
                        continue
                    fn_for_ai = dict(fn)
                    fn_for_ai["_scope"] = cname
                    fn_for_ai["_file"] = fpath

                    # intro
                    if not fn.get("ai_intro"):
                        try:
                            intro = await svc.generate_function_intro(fn_for_ai)
                            if intro:
                                fn["ai_intro"] = intro
                                stats["augmented_intro"] += 1
                        except Exception as e:  # noqa: BLE001
                            logger.warning("自动预热 intro 失败 %s key=%s: %s",
                                           cid, fn.get("key"), e)
                            stats["failed"] += 1

                    # flowchart（复杂函数跳过）
                    body_lines = int(fn.get("body_lines") or 0)
                    if not fn.get("ai_flowchart"):
                        if body_lines > _AUTO_AUGMENT_FLOW_BODY_LIMIT:
                            fn["ai_status"] = "skipped_complex"
                            fn["ai_last_error"] = (
                                f"函数体 {body_lines} 行超过 {_AUTO_AUGMENT_FLOW_BODY_LIMIT} "
                                f"行阈值；AI 流程图跳过，请手工绘制"
                            )
                            stats["skipped_complex"] += 1
                        else:
                            try:
                                flow = await svc.generate_function_flowchart(fn_for_ai)
                                if flow:
                                    fn["ai_flowchart"] = flow
                                    fn["ai_status"] = "ok"
                                    stats["augmented_flow"] += 1
                            except Exception as e:  # noqa: BLE001
                                logger.warning("自动预热 flowchart 失败 %s key=%s: %s",
                                               cid, fn.get("key"), e)
                                stats["failed"] += 1

    # 批量落盘
    for cid, scan in scan_by_cid.items():
        engineering_store.write_scan_cache(project_id, cid, scan)

    return stats


# ---- 7D-1 上传工程 zip ----

@router.post("/projects/{project_id}/swe3/engineering/upload")
async def swe3_upload_engineering(
    project_id: str,
    file: UploadFile = File(...),
    append: bool = False,
):
    """接收工程代码 zip（含 include/ 和 工程源码/）。

    - append=false（默认）：清空旧工程后解压，zip_name 覆盖
    - append=true：追加到现有 engineering_src/，zip_name 累计（" + " 分隔）
    """
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅接受 .zip 文件")

    try:
        meta = await engineering_store.receive_upload(project_id, file, append=append)
    except UploadTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except UnsafeArchive as e:
        raise HTTPException(status_code=400, detail=f"zip 不安全：{e}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"上传/解压失败：{e}")

    push_d = _get_push_d(project)
    push_d["engineering"] = meta
    creator_store.save_project(project)
    return meta


# ---- 7D-1b 浏览器直传工程树（推送 G R2，方案 B）----
#
# zip 替代路径：前端用 File System Access API 选目录 → 分片 POST 过来。
# 用户本机零安装：showDirectoryPicker 是浏览器 Web 标准。
# 和 7D-1 zip 上传是**互斥**的：调 tree_start 会清掉旧 engineering_src/。

@router.post("/projects/{project_id}/swe3/engineering/tree/start")
async def swe3_engineering_tree_start(project_id: str):
    """开始一次浏览器直传：清空旧工程目录。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    engineering_store.tree_start(project_id)
    push_d = _get_push_d(project)
    push_d["engineering"] = None
    push_d["scan_indices"] = []
    for src in push_d.get("module_code_sources", []):
        src["scan_hit_count"] = 0
        src["last_scanned_at"] = None
    creator_store.save_project(project)
    return {"message": "已清空工程目录，准备接收直传"}


@router.post("/projects/{project_id}/swe3/engineering/tree/chunk")
async def swe3_engineering_tree_chunk(
    project_id: str,
    files: List[UploadFile] = File(..., description="一批文件（multipart 多 part）"),
    paths: List[str] = Form(..., description="与 files 一一对应的相对路径（也走 multipart Form）"),
):
    """接收一批文件落盘 → engineering_src/<rel_path>。

    前端约定：files[i] 的相对路径由 paths[i] 给出（相对工程根，不含开头 /）。
    每次 chunk 建议 ≤ 10 MB、≤ 100 files；总累计受 MAX_TREE_BYTES/_FILES 限制。
    paths 从 Form 读（历史上曾走 Query，但长路径+多文件会把 URL 顶到 8KB+ 被代理丢包）。
    """
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if len(files) != len(paths):
        raise HTTPException(
            status_code=400,
            detail=f"files({len(files)}) 与 paths({len(paths)}) 数量不一致",
        )
    if not files:
        return {"written": 0}

    # 读全部文件到内存（单 chunk 约 10 MB 上限，可控）
    tuples: list[tuple[str, bytes]] = []
    for upload, rel in zip(files, paths):
        try:
            data = await upload.read()
        finally:
            await upload.close()
        tuples.append((rel, data))

    try:
        stats = engineering_store.tree_write_files(project_id, tuples)
    except TreeUploadError as e:
        # 超限或路径不安全 → 413（防半包累积）
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"落盘失败：{e}")
    return stats


@router.post("/projects/{project_id}/swe3/engineering/tree/finish")
async def swe3_engineering_tree_finish(
    project_id: str,
    workspace_name: str = Query("", description="工作区名（替代 zip_name 显示）"),
):
    """直传结束：扫工程树产 meta → 写入 push_d.engineering。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        meta = engineering_store.tree_finish(project_id, workspace_name)
    except TreeUploadError as e:
        raise HTTPException(status_code=400, detail=str(e))
    push_d = _get_push_d(project)
    push_d["engineering"] = meta
    creator_store.save_project(project)
    return meta


@router.post("/projects/{project_id}/swe3/engineering/tree/abort")
async def swe3_engineering_tree_abort(project_id: str):
    """中途取消：清半包，回到"未上传"状态。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    engineering_store.clear_engineering(project_id)
    push_d = _get_push_d(project)
    push_d["engineering"] = None
    creator_store.save_project(project)
    return {"message": "已取消直传并清理"}


# ---- 7D-2 清空工程 ----

@router.delete("/projects/{project_id}/swe3/engineering")
async def swe3_clear_engineering(project_id: str):
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    engineering_store.clear_engineering(project_id)
    push_d = _get_push_d(project)
    push_d["engineering"] = None
    push_d["scan_indices"] = []
    # module_code_sources 保留（用户配置的 glob 规则不丢），仅 scan_hit_count 清零
    for src in push_d.get("module_code_sources", []):
        src["scan_hit_count"] = 0
        src["last_scanned_at"] = None
    creator_store.save_project(project)
    return {"message": "已清空工程代码"}


# ---- 7D-3 glob 命中预览 ----

@router.get("/projects/{project_id}/swe3/engineering/preview-match")
async def swe3_preview_match(project_id: str, patterns: List[str] = Query(default=[]),
                              excludes: List[str] = Query(default=[])):
    """按 glob 规则预览命中文件。

    patterns: include 规则列表（query 多值）
    excludes: exclude 规则列表（query 多值）
    """
    pat_list = [{"pattern": p, "exclude": False} for p in patterns] + \
               [{"pattern": p, "exclude": True} for p in excludes]
    hits = engineering_store.match_files(project_id, pat_list)
    return {
        "total": len(hits),
        "sample": hits[:100],
    }


# ---- 7D-4 PUT 模块路径配置 ----

class PathConfigRequest(BaseModel):
    path_patterns: list  # [{pattern, exclude}]


@router.put("/projects/{project_id}/swe3/modules/{component_id}/path-config")
async def swe3_put_path_config(project_id: str, component_id: str, req: PathConfigRequest):
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    push_d = _get_push_d(project)
    src = {
        "component_id": component_id,
        "path_patterns": req.path_patterns or [],
        "last_scanned_at": None,
        "scan_hit_count": 0,
    }
    # 保留已有的 scan 时间
    for old in push_d.get("module_code_sources") or []:
        if old.get("component_id") == component_id:
            src["last_scanned_at"] = old.get("last_scanned_at")
            src["scan_hit_count"] = old.get("scan_hit_count", 0)
            break
    push_d["module_code_sources"] = _upsert_by_component(
        push_d.get("module_code_sources") or [], src)
    creator_store.save_project(project)
    return src


# ---- 7D-5 POST 扫描单模块 ----

@router.post("/projects/{project_id}/swe3/modules/{component_id}/scan")
async def swe3_scan_module(project_id: str, component_id: str):
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    push_d = _get_push_d(project)
    if not push_d.get("engineering"):
        raise HTTPException(status_code=400, detail="请先上传工程代码")

    # 找到模块的 path_patterns
    patterns = []
    for src in push_d.get("module_code_sources") or []:
        if src.get("component_id") == component_id:
            patterns = src.get("path_patterns") or []
            break
    if not patterns:
        raise HTTPException(status_code=400, detail="请先配置该模块的代码路径")

    hits = engineering_store.match_files(project_id, patterns)
    scan = code_scanner.scan_module(project_id, component_id, hits)

    # 回写 scan_indices（轻量） + 更新 module_code_sources 的扫描时间
    light = {
        "component_id": component_id,
        "scanned_at": scan["scanned_at"],
        "scanner_version": scan["scanner_version"],
        "stats": scan["stats"],
    }
    push_d["scan_indices"] = _upsert_by_component(
        push_d.get("scan_indices") or [], light)
    for src in push_d.get("module_code_sources") or []:
        if src.get("component_id") == component_id:
            src["last_scanned_at"] = scan["scanned_at"]
            src["scan_hit_count"] = scan["stats"]["total_files"]
            break
    creator_store.save_project(project)
    return scan


# ---- 7D-6 GET 扫描结果 ----

@router.get("/projects/{project_id}/swe3/modules/{component_id}/scan")
async def swe3_get_scan(project_id: str, component_id: str):
    data = engineering_store.read_scan_cache(project_id, component_id)
    if data is None:
        raise HTTPException(status_code=404, detail="该模块尚未扫描")
    return data


# ---- 7D-7 PUT 关注函数 ----

class FocusRequest(BaseModel):
    focused_keys: list[str]
    manual_additions: Optional[list] = None  # [{key, name, declaration}]
    # 二级入口：用户在"仅看项目新增"视图下批量加入关注的 diff.added key
    # bridge 会把它和 focused_keys 并起来作为 L5 展开入口。
    included_added_keys: Optional[list[str]] = None


@router.put("/projects/{project_id}/swe3/modules/{component_id}/focus")
async def swe3_put_focus(project_id: str, component_id: str, req: FocusRequest):
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    push_d = _get_push_d(project)
    item = {
        "component_id": component_id,
        "focused_keys": req.focused_keys or [],
        "manual_additions": req.manual_additions or [],
        "included_added_keys": req.included_added_keys or [],
    }
    push_d["focus_functions"] = _upsert_by_component(
        push_d.get("focus_functions") or [], item)
    creator_store.save_project(project)
    return item


# ---- 7D-8 POST AI 批量补齐（SSE 流） ----

@router.post("/projects/{project_id}/swe3/ai/augment")
async def swe3_ai_augment(project_id: str, request: Request):
    """为所有关注函数批量生成介绍 + PlantUML 流程图。

    流式返回（text/event-stream）：
      event: progress  data: {"done":N,"total":M,"key":"...","name":"..."}
      event: done      data: {"augmented": N}
    成功后，各 scan_cache/<cid>.json 中对应函数的 ai_intro / ai_flowchart 字段被填充。
    """
    import json as _json
    from fastapi.responses import StreamingResponse
    from app.core.swe3_ai import Swe3AI

    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    push_d = _get_push_d(project)
    focus_list = push_d.get("focus_functions") or []
    if not focus_list:
        raise HTTPException(status_code=400, detail="尚未选择任何关注函数")

    ai_service = _get_ai_service()
    svc = Swe3AI(ai_service)

    # 组装待处理任务：(component_id, scan_dict, fn_dict, scope, file_path)
    tasks: list[tuple[str, dict, dict, str, str]] = []
    scan_by_cid: dict[str, dict] = {}
    for ff in focus_list:
        cid = ff.get("component_id")
        scan = engineering_store.read_scan_cache(project_id, cid)
        if scan is None:
            continue
        scan_by_cid[cid] = scan
        for key in ff.get("focused_keys") or []:
            # 定位
            for file_info in scan.get("files") or []:
                for cls in file_info.get("classes") or []:
                    for fn in cls.get("functions") or []:
                        if fn.get("key") == key:
                            tasks.append((cid, scan, fn, cls.get("name", "__free__"),
                                          file_info.get("path", "")))
                            break

    async def _gen():
        total = len(tasks)
        done = 0
        for cid, scan, fn, scope, file_path in tasks:
            fn_for_ai = dict(fn)
            fn_for_ai["_scope"] = scope
            fn_for_ai["_file"] = file_path
            intro = await svc.generate_function_intro(fn_for_ai)
            flow = await svc.generate_function_flowchart(fn_for_ai)
            if intro:
                fn["ai_intro"] = intro
            if flow:
                fn["ai_flowchart"] = flow
            # 标记 extracted_by += "+ai"
            cur = fn.get("extracted_by", "regex")
            if "ai" not in cur.split("+"):
                fn["extracted_by"] = cur + "+ai"
            done += 1
            payload = {
                "done": done, "total": total,
                "key": fn.get("key"), "name": fn.get("name"),
            }
            yield f"event: progress\ndata: {_json.dumps(payload, ensure_ascii=False)}\n\n"

        # 落盘所有被改动的 scan_cache
        for cid, scan in scan_by_cid.items():
            engineering_store.write_scan_cache(project_id, cid, scan)
        yield f"event: done\ndata: {_json.dumps({'augmented': done})}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ---- 7D-9 PUT Camera Security 开关 ----

class CameraSecurityRequest(BaseModel):
    has_camera_security: bool


@router.put("/projects/{project_id}/swe3/camera-security")
async def swe3_set_camera_security(project_id: str, req: CameraSecurityRequest):
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    push_d = _get_push_d(project)
    push_d["has_camera_security"] = bool(req.has_camera_security)
    creator_store.save_project(project)
    return {"has_camera_security": push_d["has_camera_security"]}


# ---- 7D-10 POST AI 单函数补齐（供 FunctionDetailEditor 行内按钮） ----

class AugmentOneRequest(BaseModel):
    component_id: str
    key: str


@router.post("/projects/{project_id}/swe3/ai/augment-one")
async def swe3_ai_augment_one(project_id: str, req: AugmentOneRequest):
    """为单个关注函数生成介绍 + PlantUML，并回写到 scan_cache。返回 {ai_intro, ai_flowchart}."""
    from app.core.swe3_ai import Swe3AI

    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    scan = _scan_or_404(project_id, req.component_id)

    # 定位函数
    target_fn, target_scope, target_file = _find_fn_or_404(scan, req.component_id, req.key)

    svc = Swe3AI(_get_ai_service())
    fn_for_ai = dict(target_fn)
    fn_for_ai["_scope"] = target_scope
    fn_for_ai["_file"] = target_file
    intro = await svc.generate_function_intro(fn_for_ai)
    flow = await svc.generate_function_flowchart(fn_for_ai)
    if intro:
        target_fn["ai_intro"] = intro
    if flow:
        target_fn["ai_flowchart"] = flow
    cur = target_fn.get("extracted_by", "regex")
    if "ai" not in cur.split("+"):
        target_fn["extracted_by"] = cur + "+ai"
    engineering_store.write_scan_cache(project_id, req.component_id, scan)
    # 生成成功 → 显式登记 focus，防日后 scan_cache 字段清理丢失关注
    if intro or flow:
        push_d = _get_push_d(project)
        if _ensure_focus_key(push_d, req.component_id, req.key):
            creator_store.save_project(project)
    return {
        "key": req.key,
        "ai_intro": target_fn.get("ai_intro", ""),
        "ai_flowchart": target_fn.get("ai_flowchart", ""),
        "extracted_by": target_fn.get("extracted_by", ""),
    }


# ---- 推送 G：baseline diff / mark-exception / exempt / retry ----

class FileHunk(BaseModel):
    """单个 hunk 在 HEAD（新版）里的行区间。1-indexed；new_lines=0 表示纯删除 hunk。"""
    new_start: int
    new_lines: int = 0


class BaselineDiffRequest(BaseModel):
    """前端 isomorphic-git 预计算后 POST 过来的 baseline diff。

    字段都可空：
      - baseline_commit / head_commit 空 → 退化为无 baseline（classify 保守标 modified）
      - changed_files / added_files 为相对工程根的路径列表（与 scan 产物 path 字段对齐）
      - file_hunks: 推送 G 粒度升级，changed_files 每个文件在 HEAD 版里的 hunk 行区间；
        classify_functions 用它与函数 line_start/line_end 做交集，
        没传 → 回落文件级（该文件所有函数都标 modified），保证向后兼容
    """
    baseline_commit: str = ""
    baseline_branch: str = ""
    head_commit: str = ""
    head_branch: str = ""
    changed_files: list[str] = []
    added_files: list[str] = []
    deleted_files: list[str] = []
    file_hunks: dict[str, list[FileHunk]] = {}


@router.put("/projects/{project_id}/swe3/baseline")
async def swe3_set_baseline(project_id: str, req: BaselineDiffRequest):
    """落盘 baseline diff，供后续 scan 自动打 diff_status。

    不触发重扫；已有的 scan_cache 由单独的 reclassify 端点处理。
    """
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    # file_hunks 序列化为 plain dict（后端 classify_functions 读的也是 dict）
    hunks_plain: dict[str, list[dict]] = {}
    for path, hunks in (req.file_hunks or {}).items():
        hunks_plain[path] = [
            {"new_start": h.new_start, "new_lines": h.new_lines} for h in hunks
        ]
    diff = {
        "baseline_commit": req.baseline_commit,
        "baseline_branch": req.baseline_branch,
        "head_commit": req.head_commit,
        "head_branch": req.head_branch,
        "pinned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "changed_files": req.changed_files,
        "added_files": req.added_files,
        "deleted_files": req.deleted_files,
        "file_hunks": hunks_plain,
    }
    engineering_store.write_baseline_diff(project_id, diff)
    return diff


@router.get("/projects/{project_id}/swe3/baseline")
async def swe3_get_baseline(project_id: str):
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return engineering_store.read_baseline_diff(project_id) or {}


@router.delete("/projects/{project_id}/swe3/baseline")
async def swe3_clear_baseline(project_id: str):
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    engineering_store.clear_baseline_diff(project_id)
    return {"message": "已清空 baseline"}


@router.post("/projects/{project_id}/swe3/baseline/reclassify")
async def swe3_reclassify_all(project_id: str):
    """用当前 baseline_diff 为所有已扫描模块重新打 diff_status，无需重扫。

    顺便用**当前** engineering_store.file_is_sdk 规则刷新每个 file/function 的 is_sdk
    字段（SDK 判定规则可能在版本间变化，比如 A 方案把 "nvsipl 子串匹配" 去掉了，
    旧 cache 里残留的 is_sdk=True 必须被冲刷，否则还是走 "SDK·不画" 逻辑）。
    """
    from app.core import code_scanner
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    diff = engineering_store.read_baseline_diff(project_id)
    push_d = _get_push_d(project)
    reclassified = []
    for src in push_d.get("module_code_sources") or []:
        cid = src.get("component_id")
        scan = engineering_store.read_scan_cache(project_id, cid)
        if scan is None:
            continue
        # 1. 用当前规则刷新 is_sdk（A 方案后一律为 False；未来规则变了这里自动跟进）
        for file_info in scan.get("files") or []:
            path = file_info.get("path", "")
            file_is_sdk = engineering_store.file_is_sdk(path)
            file_info["is_sdk"] = file_is_sdk
            for cls in file_info.get("classes") or []:
                for fn in cls.get("functions") or []:
                    fn["is_sdk"] = file_is_sdk
        # 2. 重跑 diff 分类
        stats = code_scanner.classify_functions(scan, diff)
        engineering_store.write_scan_cache(project_id, cid, scan)
        reclassified.append({"component_id": cid, "stats": stats})
    return {"reclassified": reclassified, "has_baseline": diff is not None}


class ExemptRequest(BaseModel):
    component_id: str
    key: str
    exempt: bool


@router.put("/projects/{project_id}/swe3/functions/exempt")
async def swe3_set_function_exempt(project_id: str, req: ExemptRequest):
    """标记某函数"豁免 AI 流程图"（纯人工），决策 3。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    scan = _scan_or_404(project_id, req.component_id)
    fn, _scope, _file = _find_fn_or_404(scan, req.component_id, req.key)
    fn["exempt_from_ai"] = bool(req.exempt)
    engineering_store.write_scan_cache(project_id, req.component_id, scan)
    return {"key": req.key, "exempt_from_ai": fn["exempt_from_ai"]}


class MarkExceptionRequest(BaseModel):
    component_id: str
    key: str
    marked: bool = True
    note: str = ""


@router.put("/projects/{project_id}/swe3/functions/exception")
async def swe3_mark_function_exception(project_id: str, req: MarkExceptionRequest):
    """手动标记"AI 最终失败，需人工补充"异常态，决策 4。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    scan = _scan_or_404(project_id, req.component_id)
    fn, _scope, _file = _find_fn_or_404(scan, req.component_id, req.key)
    fn["ai_status"] = "exception" if req.marked else "pending"
    if req.note:
        fn["ai_exception_note"] = req.note
    engineering_store.write_scan_cache(project_id, req.component_id, scan)
    return {
        "key": req.key,
        "ai_status": fn["ai_status"],
        "ai_exception_note": fn.get("ai_exception_note", ""),
    }


class AugmentOneRetryRequest(BaseModel):
    component_id: str
    key: str
    max_retries: int = 3


@router.post("/projects/{project_id}/swe3/ai/augment-one-retry")
async def swe3_ai_augment_one_retry(project_id: str, req: AugmentOneRetryRequest):
    """单函数 AI 流程图，带 retry。决策 4 的实际落点。

    - 成功 → ai_status=ok，回填 ai_flowchart
    - 失败 → ai_status=failed，retries/last_error 记录供前端展示
    - 前端见 failed 可再次 POST；见 exception 由用户手动 PUT 异常态。
    """
    from app.core.swe3_ai import Swe3AI
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    scan = _scan_or_404(project_id, req.component_id)
    fn, target_scope, target_file = _find_fn_or_404(scan, req.component_id, req.key)

    svc = Swe3AI(_get_ai_service())
    fn_for_ai = dict(fn)
    fn_for_ai["_scope"] = target_scope
    fn_for_ai["_file"] = target_file

    # 1) 介绍（先跑，便于流程图失败也能有介绍落盘；失败不中断）
    intro = None
    if not fn.get("ai_intro"):
        try:
            intro = await svc.generate_function_intro(fn_for_ai)
        except Exception as e:  # noqa: BLE001
            logger.warning("augment-one-retry: 生成 intro 失败 %s key=%s: %s",
                           req.component_id, req.key, e)
    if intro:
        fn["ai_intro"] = intro

    # 2) 流程图（带 retry；复杂函数（body_lines > 80）跳过生成，交给用户手工）
    body_lines = int(fn.get("body_lines") or 0)
    SKIP_FLOW_IF_LINES_OVER = 80
    if body_lines > SKIP_FLOW_IF_LINES_OVER:
        fn["ai_status"] = "skipped_complex"
        fn["ai_retry_count"] = 0
        fn["ai_last_error"] = f"函数体 {body_lines} 行超过 {SKIP_FLOW_IF_LINES_OVER} 行阈值；AI 流程图跳过，请手工绘制"
        # 已存在的 ai_flowchart 不清除，让用户仍能回看
    else:
        result = await svc.generate_function_flowchart_with_retry(
            fn_for_ai, max_retries=max(1, req.max_retries))
        if result["status"] == "ok":
            fn["ai_flowchart"] = result["plantuml"]
            fn["ai_status"] = "ok"
            fn["ai_retry_count"] = result["retries"]
            fn["ai_last_error"] = ""
        else:
            fn["ai_status"] = "failed"
            fn["ai_retry_count"] = result["retries"]
            fn["ai_last_error"] = result["last_error"]

    engineering_store.write_scan_cache(project_id, req.component_id, scan)
    # 生成成功 → 显式登记 focus，防日后 scan_cache 字段清理丢失关注
    if fn.get("ai_status") in ("ok", "skipped_complex"):
        push_d = _get_push_d(project)
        if _ensure_focus_key(push_d, req.component_id, req.key):
            creator_store.save_project(project)
    return {
        "key": req.key,
        "ai_status": fn["ai_status"],
        "ai_retry_count": fn["ai_retry_count"],
        "ai_last_error": fn["ai_last_error"],
        "ai_flowchart": fn.get("ai_flowchart", ""),
        "ai_intro": fn.get("ai_intro", ""),
    }
