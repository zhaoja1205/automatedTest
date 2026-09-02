"""
多会话状态管理。

每个浏览器标签页自动分配独立 session，拥有独立的
SSH 连接、用例列表、工作区配置、执行器，互不干扰。
"""
import asyncio
import os
import re
import time
from typing import Dict, List, Optional

from fastapi import WebSocket

from app.core.test_case import SSHConfig, SSHStatus, WorkspaceConfig
from app.core.config_store import ConfigStore
from app.core.execution_state import ExecutionTask
from app.websocket.session_ws_manager import SessionWSManager


class SessionState:
    """单个 session 的完整状态，替代原来的全局 app_state 字典。"""

    def __init__(self, session_id: str, config_store: ConfigStore):
        self.session_id = session_id
        self.created_at = time.time()
        self.last_active = time.time()

        # --- 用例 & 配置（per-session） ---
        self.test_cases: list = []
        self.ssh_config: SSHConfig = config_store.load("ssh_config", SSHConfig, SSHConfig())
        self.ssh_status: SSHStatus = SSHStatus()
        self.workspace: WorkspaceConfig = config_store.load("workspace", WorkspaceConfig, WorkspaceConfig())
        self.sheets: list = []

        # --- 执行状态（per-session） ---
        self.executor = None  # ExecutorAdapter or None
        self.is_running: bool = False
        self.current_task: ExecutionTask = ExecutionTask()
        self.excel_path: str = ""
        self._stop_requested: bool = False

        # --- 基础设施（per-session） ---
        self.config_store: ConfigStore = config_store
        self.ws_connections: List[WebSocket] = []
        self.ws_manager: SessionWSManager = SessionWSManager(self.ws_connections)

    def touch(self):
        """更新最近活跃时间"""
        self.last_active = time.time()


# session_id 格式：32 位十六进制（UUID 去掉横线）
_SESSION_ID_PATTERN = re.compile(r'^[0-9a-f]{32}$')


def is_valid_session_id(session_id: str) -> bool:
    """验证 session_id 格式"""
    return bool(_SESSION_ID_PATTERN.match(session_id))


class SessionStore:
    """管理所有活跃 session 的注册表。线程安全（asyncio.Lock）。"""

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, session_id: str) -> SessionState:
        """获取已有 session 或首次创建。自动建目录、加载配置。"""
        # 快速路径：已存在
        if session_id in self._sessions:
            self._sessions[session_id].touch()
            return self._sessions[session_id]

        async with self._lock:
            # double-check
            if session_id in self._sessions:
                self._sessions[session_id].touch()
                return self._sessions[session_id]

            # 创建 per-session 目录
            for d in [f"uploads/{session_id}", f"logs/{session_id}", f"runtime/{session_id}"]:
                os.makedirs(d, exist_ok=True)

            config_store = ConfigStore(base_dir=f"runtime/{session_id}")
            state = SessionState(session_id, config_store)
            self._sessions[session_id] = state
            return state

    def get(self, session_id: str) -> Optional[SessionState]:
        """获取已有 session，不存在返回 None"""
        s = self._sessions.get(session_id)
        if s:
            s.touch()
        return s

    def remove(self, session_id: str):
        """从内存中移除 session（磁盘文件保留）"""
        session = self._sessions.pop(session_id, None)
        if session:
            # 断开所有 WS 连接
            session.ws_connections.clear()
            # 停止执行器
            if session.executor:
                try:
                    session.executor.stop()
                except Exception:
                    pass

    def all_sessions(self) -> List[SessionState]:
        """返回所有活跃 session"""
        return list(self._sessions.values())

    def all_sessions_items(self):
        """返回 (session_id, SessionState) 对"""
        return list(self._sessions.items())

    async def cleanup_stale(self, timeout: float = 3600):
        """清理超时无活动的 session（默认 1 小时）"""
        now = time.time()
        to_remove = []
        for sid, session in self.all_sessions_items():
            if (not session.ws_connections
                    and not session.is_running
                    and now - session.last_active > timeout):
                to_remove.append(sid)
        for sid in to_remove:
            self.remove(sid)
        return to_remove

    def shutdown_all(self):
        """应用关闭时停止所有执行器"""
        for session in self.all_sessions():
            if session.executor:
                try:
                    session.executor.stop()
                except Exception:
                    pass
