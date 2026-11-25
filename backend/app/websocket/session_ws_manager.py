"""
Session-scoped WebSocket 管理器。

提供与 ConnectionManager 完全一致的接口（send_log, send_progress,
broadcast, request_manual_confirm 等），但只向指定 session 的
ws_connections 发送消息。ExecutorAdapter 构造签名不变。
"""
import asyncio
import time
import uuid
from typing import Dict, List, Optional

from fastapi import WebSocket

from app.core.execution_log import ExecutionLogRecorder

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
        # 本次执行的日志落盘器（执行开始时创建，结束后关闭）。
        # 只记录 send_log 推送的执行日志，不记录板端终端原始输出。
        self._execution_log: Optional[ExecutionLogRecorder] = None

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
        """发送日志消息，并写入本次执行的执行日志文件。"""
        timestamp = int(time.time() * 1000)
        recorder = self._execution_log
        if recorder is not None:
            try:
                recorder.append(message, level, timestamp)
            except Exception:
                # 日志落盘失败不能影响执行
                pass
        await self.broadcast({
            "type": "log",
            "level": level,
            "message": message,
            "timestamp": timestamp,
        })

    def start_execution_log(self, run_id: str, session_id: str = "",
                            metadata: Optional[dict] = None):
        """开始记录一次执行的执行日志（非板端日志）。"""
        self.end_execution_log(status="interrupted", message="上一条执行日志未正常结束")
        try:
            self._execution_log = ExecutionLogRecorder(
                run_id=run_id,
                session_id=session_id,
                metadata=metadata or {},
            )
        except Exception as exc:
            self._execution_log = None
            print(f"[WARN] 创建执行日志文件失败: {exc}")

    def end_execution_log(self, status: str = "finished", message: str = ""):
        """结束本次执行日志记录，落盘后清空引用。"""
        recorder = self._execution_log
        self._execution_log = None
        if recorder is None:
            return
        try:
            recorder.close(status=status, message=message)
        except Exception as exc:
            print(f"[WARN] 关闭执行日志文件失败: {exc}")

    async def send_progress(self, current: int, total: int, case_id: str,
                            case_key: str = "", message: str = "",
                            wait_total: float = 0.0,
                            wait_remaining: float = 0.0):
        """发送进度更新（message 用于展示当前执行阶段，如"正在执行命令"）。

        ``wait_total`` / ``wait_remaining`` 用于等待倒计时：等待步骤或等待
        输出期间，前端进度条显示剩余时间。
        """
        await self.broadcast({
            "type": "progress",
            "current": current,
            "total": total,
            "case_id": case_id,
            "case_key": case_key,
            "message": message,
            "wait_total": wait_total,
            "wait_remaining": wait_remaining,
        })

    async def send_download_progress(
        self, token: str, current: int, total: int,
        case_id: str = "", phase: str = "", message: str = "",
        case_current: int = 0, case_total: int = 0, done: bool = False,
    ):
        """发送下载结果的导出进度（按前端生成的 token 区分本次下载）。

        ``current`` / ``total`` 为总进度（含日志图片、用例截图两个阶段），
        ``case_current`` / ``case_total`` 为当前阶段内已处理/待处理的用例数。
        """
        await self.broadcast({
            "type": "download_progress",
            "token": token,
            "current": current,
            "total": total,
            "case_id": case_id,
            "case_current": case_current,
            "case_total": case_total,
            "phase": phase,
            "message": message,
            "done": done,
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
