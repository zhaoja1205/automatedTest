"""
AI Provider 抽象基类。

所有 LLM Provider（Claude / OpenAI / Ollama）实现统一的 complete() 接口，
AIService 通过 Provider 抽象与具体 LLM 解耦。
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    """LLM 调用结果。"""
    content: str               # 生成的文本内容
    model: str = ""            # 实际使用的模型
    input_tokens: int = 0      # 输入 token 数
    output_tokens: int = 0     # 输出 token 数
    error: Optional[str] = None  # 错误信息（None = 成功）

    @property
    def ok(self) -> bool:
        return self.error is None


class BaseProvider(abc.ABC):
    """LLM Provider 抽象基类。"""

    name: str = "base"

    @abc.abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """发送一次 LLM 请求，返回 LLMResponse。

        参数:
            system_prompt: 系统提示词
            user_prompt: 用户消息
            model: 模型名（空串使用 Provider 默认）
            temperature: 生成温度
            max_tokens: 最大输出 token 数

        返回:
            LLMResponse，失败时 error 字段非空
        """
        ...

    @abc.abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        """测试 Provider 连通性。

        返回: (是否成功, 消息)
        """
        ...
