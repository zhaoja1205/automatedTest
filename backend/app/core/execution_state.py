"""
执行任务运行态模型。

当前阶段引入 task_id / status / 进度摘要，
让系统从“是否运行”演进为“围绕任务运行”。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel


class ExecutionTask(BaseModel):
    task_id: str = ""
    status: str = "idle"
    selected_count: int = 0
    completed_count: int = 0
    current_case_id: str = ""
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    message: str = "暂无执行任务"
    result_file: str = ""

    @classmethod
    def new_task(cls, selected_count: int) -> "ExecutionTask":
        return cls(
            task_id=uuid4().hex,
            status="starting",
            selected_count=selected_count,
            completed_count=0,
            current_case_id="",
            started_at=datetime.now().isoformat(),
            ended_at=None,
            message="任务已创建，等待执行",
            result_file="",
        )

    def mark_running(self, case_id: str = ""):
        self.status = "running"
        self.current_case_id = case_id
        self.message = "任务执行中"

    def mark_stopped(self, message: str):
        self.status = "stopped"
        self.message = message
        self.ended_at = datetime.now().isoformat()

    def mark_failed(self, message: str):
        self.status = "failed"
        self.message = message
        self.ended_at = datetime.now().isoformat()

    def mark_finished(self, message: str, result_file: str = ""):
        self.status = "finished"
        self.message = message
        self.result_file = result_file
        self.ended_at = datetime.now().isoformat()
