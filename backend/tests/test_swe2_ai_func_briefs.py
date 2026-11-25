"""SWE.2 §4.X.2 接口说明列 AI 补全 — 回归测试。

覆盖：
1. strategy=only_returns_or_empty 筛选：`[returns: X]` 和空的被补，手填保留
2. AIService.generate_func_briefs：mock provider 下按 idx 回填，结果写入 briefs
3. 缓存命中第二次调用不再打 provider

这里不打真 LLM；用 monkeypatch 把 provider 替换掉。
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

from app.ai.service import AIService
from app.ai.providers.base import LLMResponse


class _FakeProvider:
    """返回按 targets 顺序生成的固定 briefs。"""
    def __init__(self):
        self.call_count = 0

    async def complete(self, *, system_prompt, user_prompt, temperature, max_tokens):
        self.call_count += 1
        # user_prompt 里有 JSON 列表，解析 idx 清单，按序造 briefs
        m = re.search(r"\[.*\]", user_prompt, re.DOTALL)
        assert m, "prompt should contain JSON array"
        items = json.loads(m.group(0))
        out = [{"idx": it["idx"], "brief": f"模拟简介 for {it['function']}"}
               for it in items]
        return LLMResponse(
            content=json.dumps(out, ensure_ascii=False),
            model="fake-model",
            input_tokens=100,
            output_tokens=50,
            stop_reason="end_turn",
        )


def _make_service(tmp_path):
    svc = AIService({
        "ai_enabled": True,
        "ai_protocol": "openai",
        "ai_api_key": "fake",
        "ai_model": "fake-model",
        "ai_base_url": "http://fake.local",
        "ai_cache_ttl_hours": 1,
    })
    # 替换 provider + 让 cache 落到 tmp_path，隔离测试
    fp = _FakeProvider()
    svc._provider = fp
    # 用 tmp_path 清空的 cache 实例
    from app.ai.cache import AICache
    svc._cache = AICache(cache_dir=str(tmp_path), ttl_hours=1)
    return svc, fp


def test_generate_func_briefs_fills_all_targets(tmp_path):
    """基础回填：3 条目标全部拿到 brief，顺序正确。"""
    svc, fp = _make_service(tmp_path)
    targets = [
        {"idx": 0, "function": "getExposureTimeFloat",
         "returns": "float_t", "params": "uint32_t line",
         "source_path": "cdi_imx623.c"},
        {"idx": 1, "function": "ParseExposure",
         "returns": "NvMediaStatus", "params": "DriverHandle h",
         "source_path": "cdi_imx623.c"},
        {"idx": 2, "function": "setGain",
         "returns": "int", "params": "uint32_t gain",
         "source_path": "cdi_imx623.c"},
    ]
    resp = asyncio.run(svc.generate_func_briefs(targets))
    assert "briefs" in resp
    briefs = resp["briefs"]
    assert set(briefs.keys()) == {0, 1, 2}
    assert "getExposureTimeFloat" in briefs[0]
    assert "ParseExposure" in briefs[1]
    assert resp["_cache_hits"] == 0
    assert fp.call_count == 1


def test_generate_func_briefs_cache_hits_on_second_call(tmp_path):
    """同样 targets 第二次调用：全走 cache，provider.call_count 不增加。"""
    svc, fp = _make_service(tmp_path)
    targets = [{"idx": 0, "function": "foo", "returns": "int",
                "params": "void", "source_path": "x.c"}]
    _ = asyncio.run(svc.generate_func_briefs(targets))
    assert fp.call_count == 1
    resp2 = asyncio.run(svc.generate_func_briefs(targets))
    assert resp2["_cache_hits"] == 1
    assert fp.call_count == 1  # 没再打 provider


def test_generate_func_briefs_batches_large_target_list(tmp_path):
    """超过 batch_size 时会分批调用。"""
    svc, fp = _make_service(tmp_path)
    targets = [
        {"idx": i, "function": f"fn{i}", "returns": "int",
         "params": "void", "source_path": "x.c"}
        for i in range(25)
    ]
    resp = asyncio.run(svc.generate_func_briefs(targets, batch_size=10))
    # 25 / 10 → 3 批
    assert fp.call_count == 3
    assert len(resp["briefs"]) == 25


def test_generate_func_briefs_empty_targets_returns_error(tmp_path):
    svc, _ = _make_service(tmp_path)
    resp = asyncio.run(svc.generate_func_briefs([]))
    assert "_error" in resp


def test_route_strategy_only_returns_or_empty_skips_manual(tmp_path, monkeypatch):
    """路由层策略：手填内容的行被 skip，`[returns: xxx]` / 空的被覆盖。"""
    from app.api import aspice_routes
    from app.api.aspice_routes import FuncBriefRequest, FuncBriefTarget

    # fake project + monkeypatch 存取
    project = {"project_id": "proj_test_ai_briefs", "aspice": {"swe2": {}}}

    def _load(pid):
        return project if pid == "proj_test_ai_briefs" else None

    monkeypatch.setattr(aspice_routes.creator_store, "get_project", _load)

    svc, _ = _make_service(tmp_path)
    monkeypatch.setattr(aspice_routes, "_get_ai_service", lambda: svc)

    req = FuncBriefRequest(targets=[
        FuncBriefTarget(row_id="r0", function="getFoo",
                        current_description="[returns: int]"),
        FuncBriefTarget(row_id="r1", function="getBar",
                        current_description=""),
        FuncBriefTarget(row_id="r2", function="getBaz",
                        current_description="用户已经手填的说明"),
    ])
    resp = asyncio.run(aspice_routes.ai_generate_function_briefs(
        "proj_test_ai_briefs", req))
    # r0 / r1 被覆盖；r2 跳过
    results_by_id = {r["row_id"]: r for r in resp["results"]}
    skipped_ids = {s["row_id"] for s in resp["skipped"]}
    assert "r0" in results_by_id and results_by_id["r0"]["ok"]
    assert "r1" in results_by_id and results_by_id["r1"]["ok"]
    assert "r2" in skipped_ids
