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
    # AI 判定详情（供实际结果展示 AI 生成的判断依据）
    ai_judged: bool = False
    ai_status: str = ""
    ai_confidence: float = 0.0
    ai_reason: str = ""
    ai_evidence: List[str] = field(default_factory=list)

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
            "ai_judged": self.ai_judged,
            "ai_status": self.ai_status,
            "ai_confidence": self.ai_confidence,
            "ai_reason": self.ai_reason,
            "ai_evidence": self.ai_evidence,
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

    # --- AI 判定详情（同步自 TestResult） ---
    ai_judged: bool = False
    ai_status: str = ""
    ai_confidence: float = 0.0
    ai_reason: str = ""
    ai_evidence: List[str] = field(default_factory=list)

    # --- AI 生成的 Bug 描述/严重程度（仅失败用例，登记 BugList 时使用） ---
    bug_description: str = ""
    bug_severity: str = ""

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
            "ai_judged": self.ai_judged,
            "ai_status": self.ai_status,
            "ai_confidence": self.ai_confidence,
            "ai_reason": self.ai_reason,
            "ai_evidence": self.ai_evidence,
            "bug_description": self.bug_description,
            "bug_severity": self.bug_severity,
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
    driver_path: str = ""
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


# 旧版按供应商配置的值 → 协议（兼容已持久化的 ai_provider）
_PROVIDER_TO_PROTOCOL = {
    "claude": "anthropic",
    "anthropic": "anthropic",
    "openai": "openai",
    "dgx_spark": "openai",   # DGX Spark 使用 OpenAI 兼容协议
    "ollama": "ollama",
}


class AIConfig(BaseModel):
    """AI 功能配置（只区分协议，不区分供应商）"""
    ai_enabled: bool = True
    ai_protocol: str = "anthropic"       # anthropic / openai / ollama
    ai_api_key: str = ""
    ai_model: str = "ts-pri-auto"        # 默认中智网关自动路由
    ai_base_url: str = "https://llm.thundersoft.com"  # 默认接入地址
    ai_auto_analyze: bool = False        # 自动分析所有 Fail
    ai_auto_parse_steps: bool = True     # 上传后自动 AI 识别测试步骤
    # 已弃用：结果判定始终走 AI，不再使用规则引擎；
    # 保留该字段仅用于兼容旧配置与旧前端请求。
    ai_judge_mode: str = "always"
    ai_cache_ttl_hours: int = 24

    @model_validator(mode="before")
    @classmethod
    def _migrate_judge_flag(cls, data):
        """向后兼容：旧配置含 ai_judge_uncertain 时自动迁移为 ai_judge_mode。"""
        if isinstance(data, dict) and "ai_judge_uncertain" in data:
            data = dict(data)
            flag = data.pop("ai_judge_uncertain")
            if "ai_judge_mode" not in data:
                data["ai_judge_mode"] = "uncertain" if flag else "off"
        return data

    @model_validator(mode="before")
    @classmethod
    def _migrate_provider_to_protocol(cls, data):
        """向后兼容：旧配置的 ai_provider 迁移为 ai_protocol。"""
        if not isinstance(data, dict):
            return data
        if "ai_provider" in data or "ai_protocol" in data:
            data = dict(data)
            legacy = data.pop("ai_provider", None)
            protocol = data.get("ai_protocol") or legacy
            data["ai_protocol"] = _PROVIDER_TO_PROTOCOL.get(protocol, "anthropic")
        return data


class CleanupConfig(BaseModel):
    """上传文件自动清理配置"""
    enabled: bool = True                # 是否启用自动清理
    retention_days: int = 3             # 文件保留天数（默认 3 天）
    check_interval_hours: int = 6       # 检查间隔（小时）