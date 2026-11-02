"""AI 系统提示词功能注册表。

系统设置页需要展示所有可配置的 AI 功能及其内置默认提示词，
这里集中维护功能标识、展示名称、说明和默认值，避免前后端各处硬编码。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.ai.prompts import (
    analyze,
    arch_design,
    bug_description,
    judge,
    report,
    req_parse,
    statistics,
    step_parse,
)


@dataclass(frozen=True)
class AIPromptFeature:
    """一个可配置系统提示词的 AI 功能。"""

    key: str
    name: str
    description: str
    default_prompt: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "default_prompt": self.default_prompt,
        }


AI_PROMPT_FEATURES: List[AIPromptFeature] = [
    AIPromptFeature(
        key="judge",
        name="测试结果判定",
        description="对比测试用例预期结果与实际执行输出，判定 Pass / Fail / 需人工复核。",
        default_prompt=judge.SYSTEM_PROMPT,
    ),
    AIPromptFeature(
        key="analyze",
        name="失败根因分析",
        description="用例失败后分析根因，输出问题分类、证据和修复建议。",
        default_prompt=analyze.SYSTEM_PROMPT,
    ),
    AIPromptFeature(
        key="report",
        name="测试报告生成",
        description="根据本轮执行结果生成结构化测试报告。",
        default_prompt=report.SYSTEM_PROMPT,
    ),
    AIPromptFeature(
        key="step_parse",
        name="测试步骤解析",
        description="把中文测试步骤解析为可在板端执行的 shell 命令序列。",
        default_prompt=step_parse.SYSTEM_PROMPT,
    ),
    AIPromptFeature(
        key="req_parse",
        name="客户需求解析（SWE.1）",
        description="把客户原始需求文本解析为结构化需求项。",
        default_prompt=req_parse.SYSTEM_PROMPT,
    ),
    AIPromptFeature(
        key="arch_design",
        name="架构设计生成（SWE.2）",
        description="基于需求项生成组件映射建议与接口描述。",
        default_prompt=arch_design.SYSTEM_PROMPT,
    ),
    AIPromptFeature(
        key="bug_description",
        name="Bug 描述生成",
        description="根据失败信息生成 BugList 的缺陷描述，并评估严重程度。",
        default_prompt=bug_description.SYSTEM_PROMPT,
    ),
    AIPromptFeature(
        key="statistics",
        name="数据统计文案",
        description="根据执行数据填写「数据统计」页的基本信息、质量目标与测试总结。",
        default_prompt=statistics.SYSTEM_PROMPT,
    ),
]

AI_PROMPT_FEATURE_MAP: Dict[str, AIPromptFeature] = {
    feature.key: feature for feature in AI_PROMPT_FEATURES
}


def get_prompt_feature(key: str) -> Optional[AIPromptFeature]:
    """按功能标识查找注册项，不存在时返回 None。"""
    return AI_PROMPT_FEATURE_MAP.get(key)


def default_prompt_for(key: str) -> Optional[str]:
    """返回指定功能的内置默认提示词。"""
    feature = get_prompt_feature(key)
    return feature.default_prompt if feature else None
