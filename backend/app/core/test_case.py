"""
测试用例与配置数据模型。

与原 PyQt 版保持字段兼容，使用 dataclass 以便与 ExcelHandler 配合。
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, model_validator


@dataclass
class TestResult:
    """
    单次执行产生的结构化结果。
    """
    case_id: str
    status: str = "NT"
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    log_file: str = ""
    match_log_file: str = ""
    actual_output: str = ""
    match_reason: str = ""
    error_msg: str = ""

    @property
    def duration(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def model_dump(self) -> dict:
        return {
            "case_id": self.case_id,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "log_file": self.log_file,
            "match_log_file": self.match_log_file,
            "actual_output": self.actual_output,
            "match_reason": self.match_reason,
            "error_msg": self.error_msg,
            "duration": self.duration,
        }


@dataclass
class TestCase:
    """
    单条测试用例，与 Excel 数据行一一对应。
    """
    # --- 自 Excel 用例区读入 ---
    case_id: str = ""
    test_type: str = ""
    requirement_id: str = ""
    design_method: str = ""
    description: str = ""
    prerequisites: str = ""
    test_steps: str = ""
    expected_result: str = ""
    priority: str = ""

    # --- 执行控制 ---
    case_key: str = ""
    selected: bool = False
    row_number: int = 0
    source_sheet: str = ""

    # --- 执行结果 ---
    actual_result: str = ""
    status: str = "NT"
    bug_id: str = ""
    log_file: str = ""
    tester: str = ""
    test_date: str = ""
    test_version: str = ""
    remarks: str = ""

    # --- 派生 ---
    expected_keywords: List[str] = field(default_factory=list)

    def model_dump(self) -> dict:
        """兼容 Pydantic 风格的序列化，供 FastAPI 响应使用"""
        return {
            "case_id": self.case_id,
            "case_key": self.case_key or f"{self.source_sheet}:{self.row_number}:{self.case_id}",
            "test_type": self.test_type,
            "requirement_id": self.requirement_id,
            "design_method": self.design_method,
            "description": self.description,
            "prerequisites": self.prerequisites,
            "test_steps": self.test_steps,
            "expected_result": self.expected_result,
            "priority": self.priority,
            "selected": self.selected,
            "row_number": self.row_number,
            "source_sheet": self.source_sheet,
            "actual_result": self.actual_result,
            "status": self.status,
            "bug_id": self.bug_id,
            "log_file": self.log_file,
            "tester": self.tester,
            "test_date": self.test_date,
            "test_version": self.test_version,
            "remarks": self.remarks,
            "expected_keywords": self.expected_keywords,
        }


class SSHConfig(BaseModel):
    """SSH 连接配置"""
    login_mode: str = "direct"
    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""
    key_path: str = ""
    target_password: str = ""
    timeout: int = 30
    jump_host: str = ""
    jump_port: int = 22
    jump_username: str = ""
    jump_password: str = ""


class SSHStatus(BaseModel):
    """SSH 连接状态"""
    connected: bool = False
    tested: bool = False
    mode: str = "direct"
    message: str = "尚未测试 SSH 连接"


class WorkspaceConfig(BaseModel):
    """工作区配置"""
    tester_name: str = ""
    test_version: str = ""
    default_remote_path: str = ""
    nito_override_path: str = ""
    nito_override_enabled: bool = False
    image_storage_path: str = ""
    image_storage_enabled: bool = False
    image_download_path: str = ""
    image_download_enabled: bool = False
    cam_rotate_cfg_path: str = ""
    cam_rotate_cfg_enabled: bool = False
    run_prerequisites: bool = True
    auto_save: bool = True
    output_dir: str = "output"


class AIConfig(BaseModel):
    """AI 功能配置"""
    ai_enabled: bool = True
    ai_provider: str = "claude"          # claude / openai / ollama
    ai_api_key: str = ""
    ai_model: str = "ts-pri-auto"        # 默认中智网关自动路由
    ai_base_url: str = "https://llm.thundersoft.com"  # 默认中智网关
    ai_auto_analyze: bool = False        # 自动分析所有 Fail
    ai_auto_parse_steps: bool = True     # 上传后自动 AI 识别测试步骤
    ai_judge_mode: str = "always"        # "off" / "uncertain" / "always"
    ai_cache_ttl_hours: int = 24

    @model_validator(mode="before")
    @classmethod
    def _migrate_judge_flag(cls, data):
        """向后兼容：旧配置含 ai_judge_uncertain 时自动迁移为 ai_judge_mode。"""
        if isinstance(data, dict) and "ai_judge_uncertain" in data:
            flag = data.pop("ai_judge_uncertain")
            if "ai_judge_mode" not in data:
                data["ai_judge_mode"] = "uncertain" if flag else "off"
        return data


class CleanupConfig(BaseModel):
    """上传文件自动清理配置"""
    enabled: bool = True                # 是否启用自动清理
    retention_days: int = 3             # 文件保留天数（默认 3 天）
    check_interval_hours: int = 6       # 检查间隔（小时）