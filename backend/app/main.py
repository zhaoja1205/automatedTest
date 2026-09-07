"""
FastAPI 后端主入口。

提供：
- REST API：用例管理、Excel 上传/下载、SSH 配置、执行控制
- WebSocket：实时日志推送、执行进度、人工确认

支持多会话：每个浏览器标签页自动分配独立 session，
各自拥有 SSH 连接、用例列表、配置、执行状态。
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.session_store import SessionStore, is_valid_session_id
from app.api.routes import router as api_router
from app.api.creator_routes import router as creator_router

# 全局 session 注册表（替代原来的单 app_state）
session_store = SessionStore()


async def _cleanup_loop():
    """后台定时清理超时 session（每 5 分钟检查，1 小时无活动的移除）"""
    while True:
        await asyncio.sleep(300)
        try:
            removed = await session_store.cleanup_stale(timeout=3600)
            if removed:
                print(f"[SessionCleanup] 清理了 {len(removed)} 个过期 session: {removed}")
        except Exception as e:
            print(f"[SessionCleanup] 异常: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    os.makedirs("uploads", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    os.makedirs("output", exist_ok=True)
    os.makedirs("runtime", exist_ok=True)
    os.makedirs("runtime/creator_projects", exist_ok=True)

    cleanup_task = asyncio.create_task(_cleanup_loop())
    yield
    # 关闭清理
    cleanup_task.cancel()
    session_store.shutdown_all()


app = FastAPI(
    title="测试执行管理系统",
    version="3.1.0",
    lifespan=lifespan,
)

# CORS（允许自定义 header X-Session-ID）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(creator_router, prefix="/api/creator")

SESSION_HEADER = "X-Session-ID"


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时通信入口（per-session 隔离）"""
    session_id = websocket.query_params.get("session_id", "")
    if not session_id or not is_valid_session_id(session_id):
        await websocket.close(code=4000, reason="Missing or invalid session_id")
        return

    session = await session_store.get_or_create(session_id)

    await websocket.accept()
    session.ws_connections.append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            await _handle_ws_message(websocket, data, session)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if websocket in session.ws_connections:
            session.ws_connections.remove(websocket)


async def _handle_ws_message(websocket: WebSocket, data: dict, session):
    """处理客户端 WebSocket 消息"""
    msg_type = data.get("type", "")

    if msg_type == "confirm_response":
        session.ws_manager.handle_confirm_response(data)

    elif msg_type == "stop_execution":
        executor = session.executor
        if executor:
            executor.stop()
            await session.ws_manager.send_log("收到停止指令，将在当前用例完成后停止", "warning")
        else:
            session._stop_requested = True
            await session.ws_manager.send_log("收到停止指令，执行将在启动后被中止", "warning")


# 注入 session 到 API（替代原来的全局 app_state 注入）
@app.middleware("http")
async def inject_session_state(request, call_next):
    if request.url.path.startswith("/api/"):
        # 放行 CORS 预检请求（OPTIONS），否则浏览器发送自定义 header 时
        # preflight 不带 X-Session-ID 会被拦截，导致所有 API 调用失败
        if request.method == "OPTIONS":
            response = await call_next(request)
            return response
        session_id = request.headers.get(SESSION_HEADER, "")
        if not session_id or not is_valid_session_id(session_id):
            return JSONResponse(
                status_code=400,
                content={"detail": "Missing or invalid X-Session-ID header"},
            )
        session = await session_store.get_or_create(session_id)
        request.state.session = session
    response = await call_next(request)
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
