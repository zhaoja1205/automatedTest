"""
测试失败 Bug 描述生成 Prompt。

根据用例预期结果、实际输出与 AI 判定依据，生成适合写入
Excel BugList「Description」列的简短缺陷描述，并评估「Severity」列。
"""

# Severity 只允许这四档，和表格模板/前端颜色标记保持一致
ALLOWED_SEVERITIES = ("致命", "严重", "一般", "轻微")

# 模型可能输出英文等级，统一映射为中文
SEVERITY_ALIASES = {
    "critical": "致命", "blocker": "致命", "fatal": "致命", "致命": "致命",
    "major": "严重", "high": "严重", "严重": "严重",
    "normal": "一般", "medium": "一般", "moderate": "一般", "一般": "一般",
    "minor": "轻微", "low": "轻微", "trivial": "轻微", "轻微": "轻微",
}

SYSTEM_PROMPT = """\
你是一个嵌入式测试缺陷管理专家。请根据测试用例的预期结果、实际输出和 AI 判定依据，
生成一条适合填入 Excel BugList「Description」列的缺陷描述，并评估缺陷严重程度。

## Description 要求
1. 使用中文，1~2 句话，不超过 120 字
2. 描述可观察到的现象、受影响的功能/模块，以及预期与实际的差异
3. 只依据给定证据，不猜测未出现的根因，不编造日志内容
4. 不要包含命令回显、时间戳或整段日志原文
5. 不要输出修复建议

## Severity 要求
只能从以下四档中选择一个，判断依据为对用户/功能的影响：
- 致命：崩溃、死机、无法启动、核心功能完全不可用或数据丢失
- 严重：核心功能明显异常、主要指标不达标，且没有规避方式
- 一般：非核心功能异常或体验问题，存在规避方式
- 轻微：提示、文案、显示细节等不影响功能的问题

## 输出格式
严格输出以下 JSON，不要输出其他内容：
```json
{"description": "缺陷描述", "severity": "一般"}
```"""


def normalize_severity(value: str) -> str:
    """把模型返回的严重程度归一化为中文四档；无法识别时返回空串。"""
    raw = str(value or "").strip()
    normalized = SEVERITY_ALIASES.get(raw.lower(), raw)
    return normalized if normalized in ALLOWED_SEVERITIES else ""


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def build_bug_description_prompt(
    *,
    case_id: str,
    case_description: str,
    test_steps: str = "",
    expected_result: str = "",
    actual_result: str = "",
    match_reason: str = "",
    ai_reason: str = "",
    evidence: list | None = None,
) -> str:
    """构造 Bug 描述生成的 user prompt。"""
    actual_result = _truncate(actual_result, 2500)
    test_steps = _truncate(test_steps, 500)
    evidence_lines = [
        _truncate(str(item), 200)
        for item in (evidence or [])
        if str(item).strip()
    ][:8]

    parts = [
        f"用例 ID: {case_id}",
        f"用例描述: {case_description}",
        f"测试步骤:\n{test_steps}" if test_steps else "",
        f"预期结果:\n{expected_result}" if expected_result else "",
        f"判定理由: {ai_reason or match_reason}" if (ai_reason or match_reason) else "",
        f"关键证据:\n" + "\n".join(f"- {line}" for line in evidence_lines) if evidence_lines else "",
        f"实际结果/输出:\n{actual_result}" if actual_result else "",
    ]
    return "\n\n".join(p for p in parts if p)
