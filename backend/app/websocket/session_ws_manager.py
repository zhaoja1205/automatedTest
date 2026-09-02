"""
Session-scoped WebSocket 管理器。

提供与 ConnectionManager 完全一致的接口（send_log, send_progress,
broadcast, request_manual_confirm 等），但只向指定 session 的
ws_connections 发送消息。ExecutorAdapter 构造签名不变。
"""
import asyncio
import time
import uuid
from typing import Dict, List

from fastapi import WebSocket


class SessionWSManager:
    """Session-scoped WebSocket 管理器。

    每个 SessionState 持有一个实例，executor 通过它发送日志和进度。
    """

    def __init__(self, ws_connections: List[WebSocket]):
        # 引用 session 的连接列表（共享同一个 list 对象）
        self._connections = ws_connections
        self._pending_confirmations: Dict[str, asyncio.Event] = {}
        self._confirm_results: Dict[str, bool] = {}

    async def broadcast(self, message: dict):
        """广播消息到此 session 的所有 WS 连接"""
        disconnected = []
        for conn in self._connections:
            try:
                await conn.send_json(message)
            except Exception:
                disconnected.append(conn)
        for conn in disconnected:
            if conn in self._connections:
                self._connections.remove(conn)

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

    async def request_manual_confirm(self, step_desc: str, timeout: int = 300) -> bool:
        """请求人工确认，等待用户响应"""
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

    def handle_confirm_response(self, data: dict):
        """处理来自客户端的确认响应"""
        confirm_id = data.get("confirm_id", "")
        result = data.get("result", False)
        if confirm_id in self._pending_confirmations:
            self._confirm_results[confirm_id] = result
            self._pending_confirmations[confirm_id].set()
