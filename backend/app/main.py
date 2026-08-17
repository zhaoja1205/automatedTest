"""
FastAPI 后端主入口。

提供：
- REST API：用例管理、Excel 上传/下载、SSH 配置、执行控制
- WebSocket：实时日志推送、执行进度、人工确认
"""
import os
import json
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.test_case import SSHConfig, SSHStatus, WorkspaceConfig
from app.core.config_store import ConfigStore
from app.core.execution_state import ExecutionTask
from app.websocket.manager import ConnectionManager
from app.api.routes import router as api_router

# 全局状态
app_state = {
    "test_cases": [],
    "ssh_config": SSHConfig(),
    "ssh_status": SSHStatus(),
    "workspace": WorkspaceConfig(),
    "executor": None,
    "is_running": False,
    "current_task": ExecutionTask(),
}

manager = ConnectionManager()
config_store = ConfigStore()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    os.makedirs("runtime", exist_ok=True)

    app_state["ssh_config"] = config_store.load("ssh_config", SSHConfig, SSHConfig())
    app_state["workspace"] = config_store.load("workspace", WorkspaceConfig, WorkspaceConfig())
    yield
    # 清理
    if app_state.get("executor"):
        app_state["executor"].stop()


app = FastAPI(
    title="测试执行管理系统",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时通信入口"""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await manager.handle_message(websocket, data, app_state)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# 注入全局状态到 API
@app.middleware("http")
async def inject_state(request, call_next):
    request.state.app_state = app_state
    request.state.manager = manager
    request.state.config_store = config_store
    response = await call_next(request)
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)