"""
AI Service 主入口。

提供统一的 AI 调用接口：结果判定、失败分析、报告生成、测试步骤解析。
支持多 Provider（Claude / OpenAI / Ollama）和结果缓存。
AI 功能关闭或调用失败时安全降级，不影响主流程。
"""
from __future__ import annotations

import json
import re
import traceback
from typing import Optional

from .cache import AICache
from .providers.base import BaseProvider, LLMResponse
from .providers.claude_provider import ClaudeProvider
from .providers.openai_provider import OpenAIProvider
from .providers.ollama_provider import OllamaProvider
from .prompts import judge as judge_prompt
from .prompts import analyze as analyze_prompt
from .prompts import report as report_prompt
from .prompts import step_parse as step_parse_prompt


class AIService:
    """AI 功能统一入口。

    使用方式:
        service = AIService(config)
        result = await service.judge_result(expected, actual, ...)
        analysis = await service.analyze_failure(case_id, ...)
        report = await service.generate_report(summary, results)
    """

    def __init__(self, config: dict):
        """初始化 AI Service。

        config 字段:
            ai_enabled: bool          AI 总开关
            ai_provider: str          claude / openai / ollama
            ai_api_key: str           API Key
            ai_model: str             默认模型
            ai_base_url: str          自定义 URL（Ollama/自定义端点）
            ai_auto_analyze: bool     自动分析所有 Fail
            ai_cache_ttl_hours: int   缓存 TTL
        """
        self.config = config
        self.enabled = config.get("ai_enabled", False)
        self._provider: Optional[BaseProvider] = None
        self._cache = AICache(
            ttl_hours=config.get("ai_cache_ttl_hours", 24)
        )

    @property
    def provider(self) -> Optional[BaseProvider]:
        """延迟初始化 Provider。"""
        if self._provider is not None:
            return self._provider
        if not self.enabled:
            return None

        provider_name = self.config.get("ai_provider", "claude")
        api_key = self.config.get("ai_api_key", "")
        base_url = self.config.get("ai_base_url", "")
        model = self.config.get("ai_model", "")

        if provider_name == "claude":
            if not api_key:
                return None
            self._provider = ClaudeProvider(
                api_key=api_key, base_url=base_url, default_model=model
            )
        elif provider_name == "openai":
            if not api_key:
                return None
            self._provider = OpenAIProvider(
                api_key=api_key, base_url=base_url, default_model=model
            )
        elif provider_name == "ollama":
            self._provider = OllamaProvider(
                base_url=base_url, default_model=model
            )
        else:
            return None

        return self._provider

    def update_config(self, config: dict):
        """更新配置并重置 Provider（下次调用时重新初始化）。"""
        self.config = config
        self.enabled = config.get("ai_enabled", False)
        self._provider = None

    async def test_connection(self) -> dict:
        """测试 AI Provider 连通性。"""
        if not self.enabled:
            return {"ok": False, "message": "AI 功能未启用"}
        if self.provider is None:
            return {"ok": False, "message": "Provider 配置不完整（缺少 API Key？）"}
        ok, msg = await self.provider.test_connection()
        return {"ok": ok, "message": msg}

    # ------------------------------------------------------------------
    # 结果判定
    # ------------------------------------------------------------------
    async def judge_result(
        self,
        expected_text: str,
        actual_output: str,
        case_description: str = "",
        test_steps: str = "",
        exit_code: int = 0,
    ) -> Optional[dict]:
        """AI 结果判定。

        返回: {status, confidence, reason, evidence} 或 None（降级）
        如果调用失败，返回 {"_error": "原因"} 供调用方区分。
        """
        if not self.enabled:
            return {"_error": "AI 功能未启用"}
        if self.provider is None:
            return {"_error": "Provider 未就绪（缺少 API Key？）"}

        # 检查缓存
        cache_key_parts = ("judge", expected_text[:200], actual_output[-500:])
        cached = self._cache.get(*cache_key_parts)
        if cached:
            cached["_from_cache"] = True
            return cached

        user_msg = judge_prompt.build_judge_prompt(
            expected_text=expected_text,
            actual_output=actual_output,
            case_description=case_description,
            test_steps=test_steps,
            exit_code=exit_code,
        )

        resp = await self.provider.complete(
            system_prompt=judge_prompt.SYSTEM_PROMPT,
            user_prompt=user_msg,
            temperature=0.2,
            max_tokens=1024,
        )

        if not resp.ok:
            return {"_error": f"API 调用失败: {resp.error}"}

        result = self._parse_json_response(resp.content)
        if result is None:
            return {"_error": f"JSON 解析失败，原始内容: {resp.content[:200]}"}

        # 标记来源
        result["_source"] = "ai"
        result["_model"] = resp.model
        result["_tokens"] = resp.input_tokens + resp.output_tokens

        # 写入缓存
        self._cache.set(*cache_key_parts, value=result)

        return result

    # ------------------------------------------------------------------
    # 失败分析
    # ------------------------------------------------------------------
    async def analyze_failure(
        self,
        case_id: str,
        description: str,
        test_steps: str,
        expected_result: str,
        actual_output: str,
        match_reason: str = "",
        error_msg: str = "",
    ) -> Optional[dict]:
        """AI 失败分析。

        返回: {root_cause_category, root_cause_summary, evidence[], explanation,
               suggestion[], confidence, is_likely_real_bug} 或 None（降级）
        """
        if not self.enabled or self.provider is None:
            return None

        # 检查缓存
        error_sig = error_msg[:100] if error_msg else match_reason[:100]
        cache_key_parts = ("analyze", case_id, error_sig)
        cached = self._cache.get(*cache_key_parts)
        if cached:
            cached["_from_cache"] = True
            return cached

        user_msg = analyze_prompt.build_analyze_prompt(
            case_id=case_id,
            description=description,
            test_steps=test_steps,
            expected_result=expected_result,
            actual_output=actual_output,
            match_reason=match_reason,
            error_msg=error_msg,
        )

        resp = await self.provider.complete(
            system_prompt=analyze_prompt.SYSTEM_PROMPT,
            user_prompt=user_msg,
            temperature=0.3,
            max_tokens=1536,
        )

        if not resp.ok:
            return None

        result = self._parse_json_response(resp.content)
        if result is None:
            return None

        result["case_id"] = case_id
        result["_source"] = "ai"
        result["_model"] = resp.model
        result["_tokens"] = resp.input_tokens + resp.output_tokens

        self._cache.set(*cache_key_parts, value=result)

        return result

    # ------------------------------------------------------------------
    # 报告生成
    # ------------------------------------------------------------------
    async def generate_report(
        self,
        execution_summary: dict,
        results: list[dict],
        analyses: list[dict] | None = None,
        format: str = "markdown",
    ) -> Optional[dict]:
        """AI 报告生成。

        返回: {report, highlights[]} 或 None（降级）
        """
        if not self.enabled or self.provider is None:
            return None

        user_msg = report_prompt.build_report_prompt(
            execution_summary=execution_summary,
            results=results,
            analyses=analyses,
        )

        # 报告生成需要更多 token
        resp = await self.provider.complete(
            system_prompt=report_prompt.SYSTEM_PROMPT,
            user_prompt=user_msg,
            temperature=0.4,
            max_tokens=4096,
        )

        if not resp.ok:
            return None

        # 报告内容直接使用 LLM 输出（Markdown 格式）
        report_content = resp.content.strip()

        # 尝试提取 highlights（如果 LLM 在尾部输出了 JSON）
        highlights = []
        json_match = re.search(
            r'```json\s*(\[.*?\])\s*```',
            report_content,
            re.DOTALL,
        )
        if json_match:
            try:
                highlights = json.loads(json_match.group(1))
                # 去掉报告中的 JSON 块
                report_content = report_content[:json_match.start()].strip()
            except json.JSONDecodeError:
                pass

        return {
            "report": report_content,
            "highlights": highlights,
            "_model": resp.model,
            "_tokens": resp.input_tokens + resp.output_tokens,
        }

    # ------------------------------------------------------------------
    # 测试步骤解析
    # ------------------------------------------------------------------
    async def parse_steps(
        self,
        step_text: str,
        context: str = "",
    ) -> Optional[dict]:
        """AI 测试步骤解析。

        将中文测试步骤描述解析为可执行命令序列。
        返回: {parsed_steps: [...], total, ai_recognized, _model, _tokens}
               或 {"_error": "原因"}（降级）
        """
        if not self.enabled:
            return {"_error": "AI 功能未启用"}
        if self.provider is None:
            return {"_error": "Provider 未就绪（缺少 API Key？）"}
        if not step_text or not step_text.strip():
            return {"_error": "步骤文本为空", "parsed_steps": [], "total": 0, "ai_recognized": 0}

        # 检查缓存
        cache_key_parts = ("step_parse", step_text[:500], context[:200])
        cached = self._cache.get(*cache_key_parts)
        if cached:
            cached["_from_cache"] = True
            return cached

        user_msg = step_parse_prompt.build_step_parse_prompt(
            step_text=step_text,
            context=context,
        )

        resp = await self.provider.complete(
            system_prompt=step_parse_prompt.SYSTEM_PROMPT,
            user_prompt=user_msg,
            temperature=0.2,
            max_tokens=2048,
        )

        if not resp.ok:
            return {"_error": f"API 调用失败: {resp.error}"}

        parsed_list = self._parse_json_array_response(resp.content)
        if parsed_list is None:
            return {"_error": f"JSON 解析失败，原始内容: {resp.content[:200]}"}

        # 校验并补全每项必填字段
        valid_kinds = {"command", "cd", "nvsipl_input", "manual", "skip"}
        cleaned = []
        for item in parsed_list:
            if not isinstance(item, dict):
                continue
            kind = item.get("kind", "skip")
            if kind not in valid_kinds:
                kind = "command" if item.get("command") else "skip"
            cleaned.append({
                "command": str(item.get("command", "")),
                "description": str(item.get("description", "")),
                "kind": kind,
                "terminal": str(item.get("terminal", "主终端")),
                "confidence": float(item.get("confidence", 0.5)),
                "step_num": int(item.get("step_num", 0)),
            })

        ai_recognized = sum(1 for s in cleaned if s["kind"] != "skip")

        result = {
            "parsed_steps": cleaned,
            "total": len(cleaned),
            "ai_recognized": ai_recognized,
            "_source": "ai",
            "_model": resp.model,
            "_tokens": resp.input_tokens + resp.output_tokens,
        }

        # 写入缓存
        self._cache.set(*cache_key_parts, value=result)

        return result

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json_response(content: str) -> Optional[dict]:
        """从 LLM 响应中提取 JSON。

        支持:
        - 纯 JSON
        - ```json ... ``` 包裹
        - 前后有说明文字的 JSON 块
        """
        if not content:
            return None

        content = content.strip()

        # 尝试 ```json ... ``` 块
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 { ... } 块
        brace_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _parse_json_array_response(content: str) -> Optional[list]:
        """从 LLM 响应中提取 JSON 数组。

        支持:
        - 纯 JSON 数组
        - ```json ... ``` 包裹的数组
        - 前后有说明文字的 JSON 数组
        """
        if not content:
            return None

        content = content.strip()

        # 尝试 ```json ... ``` 块
        json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1))
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 [ ... ] 块（贪婪匹配最外层）
        bracket_start = content.find('[')
        bracket_end = content.rfind(']')
        if bracket_start != -1 and bracket_end > bracket_start:
            try:
                result = json.loads(content[bracket_start:bracket_end + 1])
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                pass

        # 尝试直接解析
        try:
            result = json.loads(content)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

        return None
