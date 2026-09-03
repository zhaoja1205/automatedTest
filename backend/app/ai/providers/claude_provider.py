"""
Claude API Provider。

使用 Anthropic 官方 SDK 调用 Claude 系列模型。
"""
from __future__ import annotations

import traceback
from typing import Optional

from .base import BaseProvider, LLMResponse


class ClaudeProvider(BaseProvider):
    """Anthropic Claude API Provider。"""

    name = "claude"

    # 模型别名映射 → 完整 model ID
    _MODEL_ALIASES = {
        "haiku": "claude-haiku-4-5-20251001",
        "haiku-4.5": "claude-haiku-4-5-20251001",
        "sonnet": "claude-sonnet-5-20260901",
        "sonnet-5": "claude-sonnet-5-20260901",
        "opus": "claude-opus-5-20260901",
    }

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, api_key: str, base_url: str = "", default_model: str = ""):
        self.api_key = api_key
        self.base_url = base_url or None
        self.default_model = self._resolve_model(default_model) if default_model else self.DEFAULT_MODEL
        self._client = None

    def _resolve_model(self, model: str) -> str:
        return self._MODEL_ALIASES.get(model.lower(), model)

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = anthropic.AsyncAnthropic(**kwargs)
            except ImportError:
                raise ImportError(
                    "anthropic SDK 未安装，请执行: pip install anthropic"
                )
        return self._client

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        use_model = self._resolve_model(model) if model else self.default_model
        try:
            client = self._get_client()
            response = await client.messages.create(
                model=use_model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            content = response.content[0].text if response.content else ""
            usage = response.usage
            return LLMResponse(
                content=content,
                model=use_model,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
            )
        except ImportError as e:
            return LLMResponse(content="", error=str(e))
        except Exception as e:
            return LLMResponse(
                content="",
                model=use_model,
                error=f"Claude API 调用失败: {type(e).__name__}: {e}",
            )

    async def test_connection(self) -> tuple[bool, str]:
        # 如果配置了自定义 base_url（企业网关），优先使用网关健康检查端点
        if self.base_url:
            try:
                import httpx
                health_url = self.base_url.rstrip("/") + "/health/private"
                async with httpx.AsyncClient(timeout=10) as http:
                    r = await http.get(health_url)
                    if r.status_code == 200:
                        return True, f"连接成功 (gateway: {self.base_url}, model: {self.default_model})"
                    # 健康端点不可用，回退到实际调用测试
            except Exception:
                pass  # 回退到实际调用测试

        # 直连 Anthropic 或网关无健康端点时，发送小请求测试
        try:
            resp = await self.complete(
                system_prompt="You are a test assistant.",
                user_prompt="Reply with exactly: OK",
                max_tokens=64,
            )
            if resp.ok:
                return True, f"Claude 连接成功 (model: {resp.model})"
            return False, resp.error or "未知错误"
        except Exception as e:
            return False, f"Claude 连接失败: {e}"
