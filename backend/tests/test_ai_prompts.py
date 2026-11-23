"""AI 系统提示词配置：注册表、服务取值与缓存失效。"""
import asyncio
import json
import os
import sys
import tempfile
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.ai.cache import AICache  # noqa: E402
from app.ai.prompts import judge as judge_prompt  # noqa: E402
from app.ai.prompts.registry import AI_PROMPT_FEATURES  # noqa: E402
from app.ai.providers.base import LLMResponse  # noqa: E402
from app.ai.service import AIService  # noqa: E402
from app.api import routes as routes_module  # noqa: E402
from app.api.routes import list_ai_prompts  # noqa: E402
from app.core.config_store import AIProfileStore, ConfigStore  # noqa: E402
from app.core.test_case import AIConfig  # noqa: E402

REQUIRED_KEYS = {
    "judge", "analyze", "report", "step_parse", "step_rewrite",
    "req_parse", "arch_design", "bug_description", "statistics",
}


class _FakeProvider:
    def __init__(self):
        self.calls = []

    async def complete(self, system_prompt, user_prompt, **kwargs):
        self.calls.append({"system": system_prompt, "user": user_prompt, **kwargs})
        return LLMResponse(
            content='{"status": "Pass", "confidence": 0.9, "reason": "符合预期", "evidence": []}',
            model="fake-model",
            input_tokens=10,
            output_tokens=10,
        )


def _service(provider, cache_dir, custom_prompt=None):
    config = {
        "ai_enabled": True,
        "ai_protocol": "openai",
        "ai_api_key": "k",
    }
    if custom_prompt is not None:
        config["ai_system_prompts"] = {"judge": custom_prompt}
    svc = AIService(config)
    svc._provider = provider
    svc._cache = AICache(cache_dir=cache_dir)
    return svc


def test_registry_covers_all_features():
    keys = {feature.key for feature in AI_PROMPT_FEATURES}
    assert keys == REQUIRED_KEYS
    for feature in AI_PROMPT_FEATURES:
        assert feature.name
        assert feature.description
        assert feature.default_prompt.strip()


def test_prompt_endpoint_lists_features_with_defaults():
    payload = asyncio.run(list_ai_prompts())
    prompts = payload["prompts"]
    assert {item["key"] for item in prompts} == REQUIRED_KEYS
    judge_item = next(item for item in prompts if item["key"] == "judge")
    assert judge_item["default_prompt"] == judge_prompt.SYSTEM_PROMPT


def test_ai_config_accepts_system_prompts():
    config = AIConfig(ai_system_prompts={
        "judge": "  自定义判定提示词  ",
        "analyze": "   ",
    })
    assert config.ai_system_prompts == {"judge": "自定义判定提示词"}
    # 默认不配置时为普通空字典，不共享可变对象
    assert AIConfig().ai_system_prompts == {}
    assert AIConfig().ai_system_prompts is not config.ai_system_prompts


def test_profile_snapshot_keeps_system_prompts():
    store = AIProfileStore(base_dir=tempfile.mkdtemp(prefix="ai_profile_test_"))
    config = AIConfig(ai_system_prompts={"judge": "自定义判定提示词"})
    entry = store.create("提示词方案", config)

    bundle = store.load_bundle()
    saved = next(p for p in bundle.profiles if p.id == entry.id)
    assert saved.config.ai_system_prompts == {"judge": "自定义判定提示词"}


def test_set_prompts_route_preserves_other_config_and_profile():
    base_dir = tempfile.mkdtemp(prefix="ai_prompt_route_")
    config_store = ConfigStore(base_dir=base_dir)
    profile_store = AIProfileStore(base_dir=base_dir)
    config = AIConfig(
        ai_protocol="openai",
        ai_api_key="secret-key",
        ai_model="custom-model",
    )
    config_store.save("ai_config", config)
    profile_store.create("方案A", config)

    old_config_store = routes_module._global_config_store
    old_profile_store = routes_module._ai_profile_store
    routes_module._global_config_store = config_store
    routes_module._ai_profile_store = profile_store
    try:
        session = SimpleNamespace(_ai_service=object())
        request = SimpleNamespace(state=SimpleNamespace(session=session))
        payload = routes_module.AISystemPromptsUpdateRequest(prompts={
            "judge": "  自定义判定提示词  ",
            "analyze": "   ",
        })
        result = asyncio.run(routes_module.set_ai_prompts(request, payload))

        saved = config_store.load("ai_config", AIConfig, AIConfig())
        assert saved.ai_system_prompts == {"judge": "自定义判定提示词"}
        # 仅更新提示词，不覆盖协议、模型和密钥
        assert saved.ai_protocol == "openai"
        assert saved.ai_model == "custom-model"
        assert saved.ai_api_key == "secret-key"
        assert result["ai_system_prompts"] == {"judge": "自定义判定提示词"}
        assert session._ai_service is None

        active = profile_store.get_active()
        assert active is not None
        assert active.config.ai_system_prompts == {"judge": "自定义判定提示词"}
        assert active.config.ai_model == "custom-model"
    finally:
        routes_module._global_config_store = old_config_store
        routes_module._ai_profile_store = old_profile_store


def test_service_uses_custom_prompt_and_falls_back_to_default():
    provider = _FakeProvider()
    svc = _service(provider, tempfile.mkdtemp(prefix="ai_prompt_test_"))
    asyncio.run(svc.judge_result("输出正常", "输出正常"))
    assert provider.calls[0]["system"] == judge_prompt.SYSTEM_PROMPT

    provider2 = _FakeProvider()
    custom = "你是自定义判定器，只输出 JSON。"
    svc2 = _service(
        provider2,
        tempfile.mkdtemp(prefix="ai_prompt_test_"),
        custom_prompt=custom,
    )
    asyncio.run(svc2.judge_result("输出正常", "输出正常"))
    assert provider2.calls[0]["system"] == custom

    # 空白自定义值视为未配置
    provider3 = _FakeProvider()
    svc3 = _service(
        provider3,
        tempfile.mkdtemp(prefix="ai_prompt_test_"),
        custom_prompt="   ",
    )
    asyncio.run(svc3.judge_result("输出正常", "输出正常"))
    assert provider3.calls[0]["system"] == judge_prompt.SYSTEM_PROMPT


def test_judge_result_never_uses_cache():
    """判定结果不缓存：每次判定都真实调用 AI，改提示词自然立即生效。"""
    cache_dir = tempfile.mkdtemp(prefix="ai_prompt_cache_")
    provider = _FakeProvider()
    svc = _service(provider, cache_dir)
    asyncio.run(svc.judge_result("输出正常", "输出正常"))
    asyncio.run(svc.judge_result("输出正常", "输出正常"))
    assert len(provider.calls) == 2

    provider2 = _FakeProvider()
    svc2 = _service(
        provider2, cache_dir, custom_prompt="自定义判定提示词"
    )
    asyncio.run(svc2.judge_result("输出正常", "输出正常"))
    assert len(provider2.calls) == 1
    assert provider2.calls[0]["system"] == "自定义判定提示词"


class _RewriteProvider:
    def __init__(self):
        self.calls = []

    async def complete(self, system_prompt, user_prompt, **kwargs):
        self.calls.append({"system": system_prompt, "user": user_prompt, **kwargs})
        return LLMResponse(
            content=json.dumps({
                "rewritten_steps": (
                    '1. 终端A：执行命令：./nvsipl_camera -c cfg.json -m "0x0001"\n'
                    "2. 输入 gc 0\n"
                    "3. 输入 q"
                ),
                "summary": "统一命令前缀并补充终端标签",
                "changes": ["补充执行命令前缀", "补充终端标签"],
            }, ensure_ascii=False),
            model="fake-model",
            input_tokens=10,
            output_tokens=10,
        )


def test_rewrite_steps_returns_original_and_rewritten_text():
    """重写结果包含前后文本、改写说明，并保持原文用于 diff。"""
    provider = _RewriteProvider()
    svc = _service(provider, tempfile.mkdtemp(prefix="ai_rewrite_test_"))
    original = "1、启动nvsipl\n2、输入gc 0\n3、退出"

    result = asyncio.run(svc.rewrite_steps(original, context="相机测试"))

    assert result["original_steps"] == original
    assert result["rewritten_steps"].splitlines()[0].startswith("1. 终端A：执行命令：")
    assert result["changed"] is True
    assert result["summary"] == "统一命令前缀并补充终端标签"
    assert result["changes"] == ["补充执行命令前缀", "补充终端标签"]
    assert provider.calls[0]["system"] != ""
    # 带圈数字是注释标记，提示词必须明确禁止将其作为步骤编号
    assert "①" in provider.calls[0]["system"]
    assert "注释" in provider.calls[0]["system"]
    assert "启动nvsipl" in provider.calls[0]["user"]


def test_judge_result_limits_log_from_tail():
    """超过上限时只保留日志末尾；0 表示不限制。"""
    provider = _FakeProvider()
    svc = _service(provider, tempfile.mkdtemp(prefix="ai_prompt_test_"))
    log = "HEAD" + "x" * 100 + "TAIL"

    asyncio.run(svc.judge_result("输出正常", log, max_actual_output_chars=7))
    assert provider.calls[0]["user"].endswith(log[-7:])
    assert "HEAD" not in provider.calls[0]["user"]

    asyncio.run(svc.judge_result("输出正常", log))
    assert log in provider.calls[1]["user"]
