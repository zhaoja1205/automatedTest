"""SWE.3 推送 D — 独立 AI 服务。

不折叠进 AIService：
  - swe3 的 prompt 变化节奏快（PlantUML 语法/模块术语会迭代）
  - 保持缓存键独立，避免误命中 judge/analyze 的旧 entry

4 个异步方法 + 一个工具方法 `strip_plantuml_fences`（兜底清理 ```uml 围栏）。
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from app.ai.prompts import swe3_augment as prompts
from app.ai.cache import AICache

logger = logging.getLogger(__name__)


def compress_intro(text: str, limit: int = 150) -> str:
    """把 AI 返回的函数介绍压到一到两句，供 docx 表格使用。

    模型偶尔无视 prompt 里的字数约束（尤其 thinking 模型会把推理也吐出来），
    这里做兜底：折叠空白 → 按句号切句 → 累积到 limit 字为止。
    只裁不重写，避免引入幻觉。
    """
    if not text:
        return ""
    flat = re.sub(r"\s+", "", text).strip()
    # 去掉偶发的前缀（"函数介绍：" / "介绍："）和序号
    flat = re.sub(r"^(函数介绍|介绍|说明)[:：]\s*", "", flat)
    if len(flat) <= limit:
        return flat
    # 按中文/英文句末标点切句，按顺序累积
    parts = [p for p in re.split(r"(?<=[。！？；.!?;])", flat) if p]
    out = ""
    for p in parts:
        if len(out) + len(p) > limit:
            break
        out += p
    if not out:
        # 单句就超长：硬截到 limit 并在句末补标点
        out = flat[:limit].rstrip("，,、；;") + "。"
    return out


def strip_plantuml_fences(text: str) -> str:
    """清理 AI 偶发返回的 markdown 围栏，并裁剪到 @startuml ... @enduml。"""
    if not text:
        return ""
    # 去掉围栏
    text = re.sub(r"^\s*```(?:plantuml|uml|puml)?\s*\n?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n?```\s*$", "", text)
    # 兜底：若含 @startuml 则只保留从该标记到最后 @enduml 的区间
    start = text.find("@startuml")
    end = text.rfind("@enduml")
    if start >= 0 and end > start:
        return text[start:end + len("@enduml")].strip()
    return text.strip()


class Swe3AI:
    """SWE.3 推送 D 的 AI 入口。

    用法：
        svc = Swe3AI(AIService(config))     # 复用 AIService 的 provider
        intro = await svc.generate_function_intro(fn_dict)
    """

    def __init__(self, ai_service):
        self._ai = ai_service
        # 独立缓存命名空间，与 judge/analyze 不冲突
        self._cache = AICache(ttl_hours=24)

    def _ready(self) -> bool:
        return bool(self._ai and getattr(self._ai, "enabled", False)
                    and self._ai.provider is not None)

    async def _complete(self, system: str, user: str, max_tokens: int = 1500,
                        temperature: float = 0.3) -> Optional[str]:
        if not self._ready():
            return None
        resp = await self._ai.provider.complete(
            system_prompt=system,
            user_prompt=user,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if not getattr(resp, "ok", False):
            return None
        return (getattr(resp, "content", "") or "").strip()

    async def generate_function_intro(self, fn: dict) -> Optional[str]:
        """为单个关注函数生成 1~3 段中文介绍。失败/未启用返回 None。"""
        key = ("swe3_intro", fn.get("key") or fn.get("name"), fn.get("declaration", ""))
        cached = self._cache.get(*key)
        if isinstance(cached, dict):
            # 旧缓存（prompt 改版前）可能是长文，出缓存时同样压缩
            return compress_intro(cached.get("text") or "") or None

        prompt = prompts.build_function_intro_prompt(fn)
        text = await self._complete(prompts.SYSTEM_FUNCTION_INTRO, prompt, max_tokens=800)
        if text is None:
            return None
        text = compress_intro(text)
        if not text:
            return None
        self._cache.set(*key, value={"text": text})
        return text

    async def generate_function_flowchart(self, fn: dict) -> Optional[str]:
        """为单个关注函数生成 PlantUML 流程图源码。"""
        key = ("swe3_flow", fn.get("key") or fn.get("name"), fn.get("declaration", ""))
        cached = self._cache.get(*key)
        if isinstance(cached, dict):
            return cached.get("text")

        prompt = prompts.build_function_flow_prompt(fn)
        text = await self._complete(prompts.SYSTEM_FUNCTION_FLOW, prompt, max_tokens=1500)
        if text is None:
            return None
        text = strip_plantuml_fences(text)
        self._cache.set(*key, value={"text": text})
        return text

    async def generate_class_diagram(self, module_name: str,
                                      classes: list[dict]) -> Optional[str]:
        """为整个模块生成 Class 图。classes 是 Swe3ScannedClass 列表。"""
        key = ("swe3_class", module_name,
               ",".join(c.get("name", "") for c in classes))
        cached = self._cache.get(*key)
        if isinstance(cached, dict):
            return cached.get("text")

        prompt = prompts.build_class_diagram_prompt(module_name, classes)
        text = await self._complete(prompts.SYSTEM_CLASS_DIAGRAM, prompt, max_tokens=1500)
        if text is None:
            return None
        text = strip_plantuml_fences(text)
        self._cache.set(*key, value={"text": text})
        return text

    async def generate_sequence_diagram(self, module_name: str,
                                         focus_fns: list[dict]) -> Optional[str]:
        """为模块生成单元时序图。focus_fns 列表元素是关注函数（已加 _scope/_file）。"""
        key = ("swe3_seq", module_name,
               ",".join(fn.get("name", "") for fn in focus_fns[:12]))
        cached = self._cache.get(*key)
        if isinstance(cached, dict):
            return cached.get("text")

        prompt = prompts.build_sequence_diagram_prompt(module_name, focus_fns)
        text = await self._complete(prompts.SYSTEM_SEQUENCE_DIAGRAM, prompt, max_tokens=1500)
        if text is None:
            return None
        text = strip_plantuml_fences(text)
        self._cache.set(*key, value={"text": text})
        return text

    # ---- 推送 G：带 retry 的流程图生成 ----

    async def generate_function_flowchart_with_retry(
        self, fn: dict, max_retries: int = 3, backoff_base: float = 2.0,
    ) -> dict:
        """为单个函数生成流程图，失败时自动重试。

        返回结构 `{status, plantuml, retries, last_error}`，使 API 层能把失败态如实
        透出给前端（决策 4：失败可 retry，最终失败标 exception）。

        - status="ok"        → plantuml 非空 @startuml...@enduml 块
        - status="failed"    → 到达 retries 上限仍失败；前端可再点"重试"
        - status="exception" → 由上层按业务规则标记（这里只负责 ok/failed）

        重试触发：AI 返回 None（服务未开 / provider 调用失败）/ strip 后仍不含
        @startuml。网络异常 / 超时也走重试。每次失败后 exponential backoff。
        """
        last_error = ""
        for attempt in range(1, max(1, max_retries) + 1):
            try:
                text = await self.generate_function_flowchart(fn)
            except Exception as e:  # noqa: BLE001 — provider 异常形态不固定
                last_error = f"exception: {e!r}"
                logger.warning(
                    "swe3 flowchart retry: fn=%s attempt=%d error=%s",
                    fn.get("name"), attempt, last_error,
                )
                text = None

            if text and "@startuml" in text and "@enduml" in text:
                return {
                    "status": "ok", "plantuml": text,
                    "retries": attempt - 1, "last_error": "",
                }

            if not last_error:
                last_error = "empty_or_invalid_plantuml" if text is not None else "ai_unavailable"

            if attempt < max_retries:
                # 失败前清理这次的脏缓存，避免下次重试直接命中空结果
                key = ("swe3_flow", fn.get("key") or fn.get("name"), fn.get("declaration", ""))
                try:
                    self._cache.invalidate(*key)
                except Exception:  # noqa: BLE001 — cache 实现细节不干扰重试主流程
                    pass
                await asyncio.sleep(backoff_base ** (attempt - 1))

        return {
            "status": "failed", "plantuml": "",
            "retries": max_retries, "last_error": last_error,
        }
