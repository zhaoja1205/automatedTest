"""
WebSocket 连接管理与消息处理。

负责：
- 客户端连接/断开管理
- 消息广播（日志、进度、人工确认）
- 执行控制命令转发
"""
import asyncio
import time
from typing import List, Dict
from fastapi import WebSocket


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._pending_confirmations: Dict[str, asyncio.Event] = {}
        self._confirm_results: Dict[str, bool] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        disconnected = []
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            self.disconnect(conn)

    async def send_personal(self, websocket: WebSocket, message: dict):
        """发送消息到指定连接"""
        try:
            await websocket.send_json(message)
        except Exception:
            self.disconnect(websocket)

    async def handle_message(self, websocket: WebSocket, data: dict, app_state: dict):
        """处理客户端消息"""
        msg_type = data.get("type", "")

        if msg_type == "confirm_response":
            # 人工确认响应
            confirm_id = data.get("confirm_id", "")
            result = data.get("result", False)
            if confirm_id in self._pending_confirmations:
                self._confirm_results[confirm_id] = result
                self._pending_confirmations[confirm_id].set()

        elif msg_type == "stop_execution":
            # 停止执行：只置停止标志，由后台执行任务的 finally 统一收尾并广播结束态，
            # 避免在此处直接置 is_running=False 导致与后台任务状态错乱。
            executor = app_state.get("executor")
            if executor:
                executor.stop()
                await self.send_log("收到停止指令，将在当前用例完成后停止", "warning")
            else:
                # 执行器尚未创建（如 SSH 连接中），置一个全局停止标志供 _run_execution 检查
                app_state["_stop_requested"] = True
                await self.send_log("收到停止指令，执行将在启动后被中止", "warning")

    async def request_manual_confirm(self, step_desc: str, timeout: int = 300) -> bool:
        """请求人工确认，等待用户响应"""
        import uuid
        confirm_id = str(uuid.uuid4())
        event = asyncio.Event()
        self._pending_confirmations[confirm_id] = event
        self._confirm_results[confirm_id] = False

        await self.broadcast({
            "type": "manual_confirm_request",
            "confirm_id": confirm_id,
            "step_desc": step_desc,
            "timeout": timeout,
        })

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            self._pending_confirmations.pop(confirm_id, None)

        result = self._confirm_results.pop(confirm_id, False)
        return result

    async def send_log(self, message: str, level: str = "info"):
        """发送日志消息"""
        await self.broadcast({
            "type": "log",
            "level": level,
            "message": message,
            "timestamp": int(time.time() * 1000),
        })

    async def send_progress(self, current: int, total: int, case_id: str, case_key: str = ""):
        """发送进度更新"""
        await self.broadcast({
            "type": "progress",
            "current": current,
            "total": total,
            "case_id": case_id,
            "case_key": case_key,
        })

    async def send_case_complete(self, case_id: str, status: str, reason: str = "",
                                case_key: str = "", actual_result: str = ""):
        """发送单用例完成通知"""
        await self.broadcast({
            "type": "case_complete",
            "case_id": case_id,
            "case_key": case_key,
            "status": status,
            "reason": reason,
            "actual_result": actual_result,
        })

    async def send_execution_finished(self, results: list):
        """发送执行完成通知"""
        await self.broadcast({
            "type": "execution_finished",
            "results": results,
        })