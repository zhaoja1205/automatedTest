"""
用例创建模块 API 路由。

提供项目 CRUD、导出、文件下载等接口。
项目为全局持久化（不依赖 per-session），存储在 runtime/creator_projects/ 下。
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from app.core import creator_store
from app.core import case_generator
from app.core.config_store import ConfigStore
from app.core.test_case import AIConfig

router = APIRouter()

# AI 配置使用全局 ConfigStore，与 routes.py 一致
_global_config_store = ConfigStore(base_dir="runtime")


def _get_ai_service():
    """从全局配置创建 AIService 实例。creator 项目是全局的，不绑定 session。"""
    from app.ai.service import AIService
    ai_config = _global_config_store.load("ai_config", AIConfig, AIConfig())
    return AIService(ai_config.model_dump())


# ---- 请求模型 ----

class CreateProjectRequest(BaseModel):
    name: str


class UpdateProjectRequest(BaseModel):
    """允许部分更新——前端可以只传改变的字段。"""
    name: Optional[str] = None
    meta: Optional[dict] = None
    coverage_matrix: Optional[dict] = None
    functional_cases: Optional[list] = None
    fault_cases: Optional[list] = None
    defaults_used: Optional[list] = None
    current_step: Optional[int] = None


class GenerateCasesRequest(BaseModel):
    """按覆盖矩阵生成用例。"""
    category: Optional[str] = None   # None=全部；"functional" | "fault"
    use_ai: bool = False
    overwrite: bool = False          # True=覆盖已有用例；False=追加


# ---- 项目 CRUD ----

@router.get("/projects")
async def list_projects():
    """列出所有用例创建项目。"""
    return creator_store.list_projects()


@router.post("/projects")
async def create_project(req: CreateProjectRequest):
    """创建新项目。"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    return creator_store.create_project(req.name.strip())


@router.get("/projects/{project_id}")
async def get_project(project_id: str):
    """获取完整项目数据。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.put("/projects/{project_id}")
async def update_project(project_id: str, req: UpdateProjectRequest):
    """更新项目（部分更新）。"""
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 只更新传入的字段
    update_data = req.model_dump(exclude_none=True)
    for key, value in update_data.items():
        project[key] = value

    creator_store.save_project(project)
    return {"message": "已保存"}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    """删除项目。"""
    if not creator_store.delete_project(project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"message": "已删除"}


# ---- 生成用例 ----

@router.post("/projects/{project_id}/generate-cases")
async def generate_cases(project_id: str, req: GenerateCasesRequest):
    """按覆盖矩阵生成测试用例。

    规则模板兜底，use_ai=True 时经 AI 增强（失败则整批回退规则版）。
    overwrite=False 追加到已有用例，True 则覆盖。
    """
    project = creator_store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    cm = project.get("coverage_matrix") or {}
    modules = cm.get("modules", [])
    features = cm.get("features", [])
    matrix = cm.get("matrix", [])
    topology = cm.get("topology", [])

    if not modules or not features or not matrix:
        raise HTTPException(status_code=400, detail="覆盖矩阵为空，请先在第 2 步配置模组与功能")

    meta = project.get("meta", {})

    # 先用规则模板生成兜底骨架
    rule_func, rule_fault, rule_defaults = case_generator.generate_cases(
        modules=modules,
        features=features,
        matrix=matrix,
        meta=meta,
        category=req.category,
        topology=topology,
    )

    source = "rule"
    ai_error: Optional[str] = None
    gen_func = rule_func
    gen_fault = rule_fault

    # AI 增强。硬件拓扑场景下优先保证 -m mask 精确匹配，当前 AI 生成暂不替换拓扑规则结果。
    if req.use_ai and topology:
        ai_error = "已启用硬件拓扑，当前使用规则模板以确保 -m mask 按拓扑生成"
    elif req.use_ai:
        try:
            ai_service = _get_ai_service()
            ai_result = await ai_service.generate_cases(
                modules=modules,
                features=features,
                matrix=matrix,
                meta=meta,
                category=req.category,
            )
            if ai_result and "_error" not in ai_result:
                gen_func = ai_result.get("functional_cases", [])
                gen_fault = ai_result.get("fault_cases", [])
                source = "ai"
            else:
                ai_error = (ai_result or {}).get("_error", "AI 生成失败")
                # 降级用规则版（gen_func/gen_fault 已是 rule 版）
        except Exception as e:
            ai_error = f"AI 调用异常: {str(e)}"
            # 降级用规则版

    # 合并到项目
    if req.overwrite:
        project["functional_cases"] = gen_func
        project["fault_cases"] = gen_fault
    else:
        existing_func = project.get("functional_cases", [])
        existing_fault = project.get("fault_cases", [])
        project["functional_cases"] = existing_func + gen_func
        project["fault_cases"] = existing_fault + gen_fault

    # defaults_used 去重合并
    merged_defaults = case_generator.merge_defaults(
        project.get("defaults_used", []),
        rule_defaults,
    )
    project["defaults_used"] = merged_defaults
    project["current_step"] = 2

    creator_store.save_project(project)

    total = len(gen_func) + len(gen_fault)
    return {
        "source": source,
        "count": total,
        "functional_count": len(gen_func),
        "fault_count": len(gen_fault),
        "functional_cases": gen_func,
        "fault_cases": gen_fault,
        "defaults_used": rule_defaults,
        "ai_error": ai_error,
    }


# ---- 导出 ----

@router.post("/projects/{project_id}/export")
async def export_project(project_id: str):
    """导出项目：生成 cases.json + 内部版 xlsx + 客户版 xlsx。"""
    try:
        result = creator_store.export_project(project_id)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {str(e)}")


@router.get("/projects/{project_id}/download/{filename}")
async def download_file(project_id: str, filename: str):
    """下载导出的文件。"""
    path = creator_store.get_download_path(project_id, filename)
    if not path:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        path,
        filename=filename,
        media_type="application/octet-stream",
    )
