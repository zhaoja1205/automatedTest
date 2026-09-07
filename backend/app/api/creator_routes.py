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

router = APIRouter()


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
