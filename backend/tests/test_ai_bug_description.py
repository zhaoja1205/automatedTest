"""AI 生成 BugList 描述与 Severity：服务解析、用例回填与优先级。"""
import asyncio
import os
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.ai.cache import AICache  # noqa: E402
from app.ai.providers.base import LLMResponse  # noqa: E402
from app.ai.service import AIService  # noqa: E402
from app.core.bug_list import sync_failed_cases_to_bug_list  # noqa: E402
from app.core.test_case import TestCase  # noqa: E402


class _FakeProvider:
    """按固定 JSON 返回的假 Provider，避免测试依赖真实网络。"""

    def __init__(self, content='{"description": "屏幕点亮后画面偏绿，与预期的正常色彩不符。", "severity": "严重"}'):
        self.content = content
        self.calls = []

    async def complete(self, system_prompt, user_prompt, **kwargs):
        self.calls.append({"system": system_prompt, "user": user_prompt, **kwargs})
        return LLMResponse(content=self.content, model="fake-model", input_tokens=10, output_tokens=10)


def _service_with(provider, enabled=True):
    svc = AIService({"ai_enabled": enabled, "ai_protocol": "openai", "ai_api_key": "k"})
    svc._provider = provider if enabled else None
    # 测试使用独立缓存目录，避免命中本地 runtime/ai_cache 中的真实结果
    svc._cache = AICache(cache_dir=tempfile.mkdtemp(prefix="ai_cache_test_"))
    return svc


def test_generate_bug_description_parses_and_normalizes():
    provider = _FakeProvider('{"description": "第一行描述\\n第二行补充", "severity": "Major"}')
    svc = _service_with(provider)

    result = asyncio.run(svc.generate_bug_description(
        case_id="FT_001",
        case_description="起流测试",
        expected_result="输出正常",
        actual_result="输出偏绿",
        ai_reason="画面颜色异常",
    ))

    assert result["description"] == "第一行描述 第二行补充"
    # 模型输出英文等级时归一化为中文四档
    assert result["severity"] == "严重"
    assert result["_model"] == "fake-model"
    assert len(provider.calls) == 1
    assert "FT_001" in provider.calls[0]["user"]


def test_generate_bug_description_disabled_returns_error():
    svc = _service_with(None, enabled=False)
    result = asyncio.run(svc.generate_bug_description(
        case_id="FT_001", case_description="起流测试",
    ))
    assert "_error" in result


def test_generate_bug_description_cache_hits():
    provider = _FakeProvider()
    svc = _service_with(provider)

    async def _twice():
        first = await svc.generate_bug_description(
            case_id="FT_001", case_description="起流测试", ai_reason="画面颜色异常",
        )
        second = await svc.generate_bug_description(
            case_id="FT_001", case_description="起流测试", ai_reason="画面颜色异常",
        )
        return first, second

    first, second = asyncio.run(_twice())
    assert len(provider.calls) == 1
    assert second.get("_from_cache") is True
    assert second["description"] == first["description"]
    assert second["severity"] == first["severity"]


def test_bug_entry_prefers_ai_description_and_severity():
    case = TestCase(
        case_id="FT_001", source_sheet="功能测试", test_type="功能",
        description="起流测试", status="Fail",
        ai_reason="帧率只有 12fps",
        bug_description="起流后帧率仅 12fps，低于预期的 30fps。",
        bug_severity="严重",
    )
    entries, added = sync_failed_cases_to_bug_list([case], [])
    assert added == 1
    assert entries[0]["description"] == "起流后帧率仅 12fps，低于预期的 30fps。"
    assert entries[0]["severity"] == "严重"


def test_bug_entry_severity_falls_back_to_pending():
    case = TestCase(case_id="FT_001", status="Fail", ai_reason="输出异常")
    entries, _ = sync_failed_cases_to_bug_list([case], [])
    assert entries[0]["severity"] == "待评估"


def test_existing_bug_severity_updated_only_when_ai_returns_one():
    case = TestCase(
        case_id="FT_001", status="Fail", ai_reason="输出异常",
        bug_description="输出异常，画面无显示", bug_severity="致命",
    )
    existing = [{
        "no": "1", "bug_id": "BUG-FT_001", "module": "功能",
        "description": "旧描述", "version": "V1.0", "severity": "一般",
        "status": "Open", "tester": "张三", "date": "2026-10-29",
        "effective": "待确认", "comment": "", "row_number": 3,
    }]
    entries, added = sync_failed_cases_to_bug_list([case], existing)
    assert added == 0
    assert entries[0]["severity"] == "致命"
    assert entries[0]["description"] == "输出异常，画面无显示"
    assert entries[0]["status"] == "Open"

    # AI 不可用（无 bug_severity）时保留原等级
    case.bug_severity = ""
    entries2, _ = sync_failed_cases_to_bug_list([case], entries)
    assert entries2[0]["severity"] == "致命"


def test_generate_ai_bug_descriptions_only_fills_failed_cases():
    from app.api.routes import _generate_ai_bug_descriptions

    class _Svc:
        enabled = True

        def __init__(self):
            self.calls = []

        async def generate_bug_description(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs["case_id"] == "FT_002":
                raise RuntimeError("模拟单条失败")
            return {
                "description": f"AI 描述-{kwargs['case_id']}",
                "severity": "严重",
            }

    failed = TestCase(case_id="FT_001", status="Fail", actual_result="输出偏绿")
    broken = TestCase(case_id="FT_002", status="Fail", actual_result="输出偏绿")
    passed = TestCase(case_id="FT_003", status="Pass", actual_result="输出正常")

    svc = _Svc()
    generated = asyncio.run(_generate_ai_bug_descriptions(svc, [failed, broken, passed]))

    assert generated == 1
    assert failed.bug_description == "AI 描述-FT_001"
    assert failed.bug_severity == "严重"
    # 单条失败不影响其它用例，也不会给通过用例生成描述/等级
    assert broken.bug_description == ""
    assert broken.bug_severity == ""
    assert passed.bug_description == ""
    assert passed.bug_severity == ""
    assert {c["case_id"] for c in svc.calls} == {"FT_001", "FT_002"}


def test_normalize_severity_aliases_and_invalid():
    from app.ai.prompts.bug_description import normalize_severity

    assert normalize_severity("Critical") == "致命"
    assert normalize_severity("high") == "严重"
    assert normalize_severity("medium") == "一般"
    assert normalize_severity("Low") == "轻微"
    assert normalize_severity("严重") == "严重"
    assert normalize_severity("未知等级") == ""
    assert normalize_severity("") == ""
