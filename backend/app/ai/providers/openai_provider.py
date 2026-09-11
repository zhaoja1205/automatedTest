"""
OpenAI API Provider。

优先使用 OpenAI 官方 SDK；未安装 SDK 时使用 httpx 直连，兼容 OpenAI API 格式的第三方服务。
"""
from __future__ import annotations

from urllib.parse import urljoin

import httpx

from .base import BaseProvider, LLMResponse


class OpenAIProvider(BaseProvider):
    """OpenAI API Provider。"""

    name = "openai"

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, api_key: str, base_url: str = "", default_model: str = ""):
        self.api_key = api_key
        self.base_url = base_url or None
        self.default_model = default_model or self.DEFAULT_MODEL
        self._client = None

    def _get_client(self):
        if self._client is None:
            import openai
            kwargs = {"api_key": self.api_key, "timeout": 60.0}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    async def _complete_httpx(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """openai SDK 未安装时的 OpenAI-compatible HTTP 兜底调用。"""
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/") + "/"
        url = urljoin(base, "chat/completions")
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        choice = data.get("choices", [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        return LLMResponse(
            content=message.get("content") or "",
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        use_model = model or self.default_model
        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=use_model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            choice = response.choices[0] if response.choices else None
            content = choice.message.content if choice else ""
            usage = response.usage
            return LLMResponse(
                content=content or "",
                model=use_model,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            )
        except ImportError:
            try:
                return await self._complete_httpx(
                    system_prompt,
                    user_prompt,
                    model=use_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as e:
                return LLMResponse(
                    content="",
                    model=use_model,
                    error=f"OpenAI 兼容 API 调用失败: {type(e).__name__}: {e}",
                )
        except Exception as e:
            return LLMResponse(
                content="",
                model=use_model,
                error=f"OpenAI API 调用失败: {type(e).__name__}: {e}",
            )

    async def test_connection(self) -> tuple[bool, str]:
        try:
            resp = await self.complete(
                system_prompt="You are a test assistant.",
                user_prompt="Reply with exactly: OK",
                max_tokens=10,
            )
            if resp.ok:
                return True, f"OpenAI 连接成功 (model: {resp.model})"
            return False, resp.error or "未知错误"
        except Exception as e:
            return False, f"OpenAI 连接失败: {e}"
