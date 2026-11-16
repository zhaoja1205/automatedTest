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

# 单条消息发送超时：客户端读取变慢/失联时不能阻塞执行器，
# 否则终端实时流会把 case_complete / execution_finished 一起卡住。
_SEND_TIMEOUT = 10.0


class SessionWSManager:
    """Session-scoped WebSocket 管理器。

    每个 SessionState 持有一个实例，executor 通过它发送日志和进度。
    """

    def __init__(self, ws_connections: List[WebSocket]):
        # 引用 session 的连接列表（共享同一个 list 对象）
        self._connections = ws_connections
        self._pending_confirmations: Dict[str, asyncio.Event] = {}
        self._confirm_results: Dict[str, bool] = {}
        # 每条连接一把发送锁：多个任务（终端流/日志/进度）并发广播时，
        # 保证同一连接上的消息按序写入，不会交错。
        self._send_locks: Dict[int, asyncio.Lock] = {}

    def _send_lock(self, conn: WebSocket) -> asyncio.Lock:
        lock = self._send_locks.get(id(conn))
        if lock is None:
            lock = asyncio.Lock()
            self._send_locks[id(conn)] = lock
        return lock

    async def _send_one(self, conn: WebSocket, message: dict):
        async def _do_send():
            async with self._send_lock(conn):
                await conn.send_json(message)

        # 连同等待发送锁一起限时：慢连接最多拖住执行器 _SEND_TIMEOUT 秒。
        await asyncio.wait_for(_do_send(), timeout=_SEND_TIMEOUT)

    def discard_connection(self, conn: WebSocket):
        """连接断开时清理其发送锁，避免锁字典随重连无限增长。"""
        self._send_locks.pop(id(conn), None)

    async def broadcast(self, message: dict):
        """广播消息到此 session 的所有 WS 连接。

        各连接并发发送且单条超时；慢/失联连接会被移除以避免阻塞执行器。
        """
        conns = list(self._connections)
        if not conns:
            return
        results = await asyncio.gather(
            *(self._send_one(conn, message) for conn in conns),
            return_exceptions=True,
        )
        for conn, result in zip(conns, results):
            if not isinstance(result, BaseException):
                continue
            if conn in self._connections:
                self._connections.remove(conn)
            self._send_locks.pop(id(conn), None)
            # 超时/异常后连接状态可能不可用，主动关闭让前端走重连
            try:
                await conn.close()
            except Exception:
                pass

    async def send_log(self, message: str, level: str = "info"):
        """发送日志消息"""
        await self.broadcast({
            "type": "log",
            "level": level,
            "message": message,
            "timestamp": int(time.time() * 1000),
        })

    async def send_progress(self, current: int, total: int, case_id: str,
                            case_key: str = "", message: str = ""):
        """发送进度更新（message 用于展示当前执行阶段，如"正在执行命令"）"""
        await self.broadcast({
            "type": "progress",
            "current": current,
            "total": total,
            "case_id": case_id,
            "case_key": case_key,
            "message": message,
        })

    async def send_case_start(self, case_info: dict):
        """发送「当前用例开始执行」通知。

        前端据此切换实时板端日志面板并展示当前用例信息（描述、步骤、终端列表等）。
        """
        await self.broadcast({
            "type": "case_start",
            "case": case_info,
        })

    async def send_terminal_log(self, case_id: str, case_key: str,
                                terminal: str, chunk: str):
        """发送某个终端的实时板端输出（可能包含多行文本）。"""
        await self.broadcast({
            "type": "terminal_log",
            "case_id": case_id,
            "case_key": case_key,
            "terminal": terminal,
            "chunk": chunk,
            "timestamp": int(time.time() * 1000),
        })

    async def send_case_complete(self, case_id: str, status: str, reason: str = "",
                                case_key: str = "", actual_result: str = "",
                                log_file: str = "", remarks: str = ""):
        """发送单用例完成通知"""
        await self.broadcast({
            "type": "case_complete",
            "case_id": case_id,
            "case_key": case_key,
            "status": status,
            "reason": reason,
            "actual_result": actual_result,
            "log_file": log_file,
            "remarks": remarks,
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
