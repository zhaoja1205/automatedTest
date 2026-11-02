"""AI 系统提示词配置：注册表、服务取值与缓存失效。"""
import asyncio
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
    "judge", "analyze", "report", "step_parse",
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


def test_prompt_change_invalidates_cache():
    cache_dir = tempfile.mkdtemp(prefix="ai_prompt_cache_")
    provider = _FakeProvider()
    svc = _service(provider, cache_dir)
    asyncio.run(svc.judge_result("输出正常", "输出正常"))
    asyncio.run(svc.judge_result("输出正常", "输出正常"))
    assert len(provider.calls) == 1  # 相同提示词命中缓存

    provider2 = _FakeProvider()
    svc2 = _service(
        provider2, cache_dir, custom_prompt="自定义判定提示词"
    )
    asyncio.run(svc2.judge_result("输出正常", "输出正常"))
    assert len(provider2.calls) == 1  # 提示词变化后重新调用 AI
    assert provider2.calls[0]["system"] == "自定义判定提示词"
