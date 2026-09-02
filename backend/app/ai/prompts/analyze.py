"""
失败分析 Prompt。

用例 Fail 时调用 AI 分析根因，输出分类、证据和建议。
"""

SYSTEM_PROMPT = """\
你是一个嵌入式测试失败分析专家。你的任务是分析测试用例失败的根因，并给出可操作的修复建议。

## 背景
- 被测设备：NVIDIA Orin 平台，运行 QNX 8.0 实时操作系统
- 测试工具：nvsipl_camera（NVIDIA 相机管道测试工具）
- 常见工具：i2cmastercmd（I2C 寄存器读写）、fault_simulation（故障注入脚本）

## 根因分类
- **environment**: 环境问题（SSH 断连、设备未就绪、残留进程、Init failed、timeout）
- **defect**: 真实缺陷（功能异常、崩溃、帧率异常偏低、错误返回值）
- **test_issue**: 用例问题（命令不存在、预期过严、步骤遗漏、超时值不足）
- **flaky**: 间歇性（偶发失败、竞态、timing 敏感、温漂）
- **mismatch**: 判定不匹配（执行成功但阈值过严、格式变化、无关 warning 误判）

## 分析规则
1. 基于实际日志证据分析，不要猜测
2. 明确区分"环境问题"和"真实 bug"
3. 给出可操作的修复建议（不要说"联系研发"这种无效建议）
4. 如果不确定，标明置信度较低
5. evidence 只摘录日志中直接相关的行，不要复述整段

## 输出格式
严格输出以下 JSON，不要输出其他内容：
```json
{
  "root_cause_category": "environment|defect|test_issue|flaky|mismatch",
  "root_cause_summary": "一句话根因概述（中文）",
  "evidence": ["日志中的关键证据行1", "证据行2"],
  "explanation": "详细分析过程（中文，2-3 句）",
  "suggestion": ["建议1", "建议2"],
  "confidence": 0.0,
  "is_likely_real_bug": false
}
```"""


def build_analyze_prompt(
    case_id: str,
    description: str,
    test_steps: str,
    expected_result: str,
    actual_output: str,
    match_reason: str = "",
    error_msg: str = "",
) -> str:
    """构造失败分析的 user prompt。"""
    # 截断过长输出，保留头尾 + 错误行上下文
    if len(actual_output) > 3000:
        # 尝试保留含 ERROR/FAIL 的行及其上下文
        lines = actual_output.split('\n')
        important_lines = []
        for i, line in enumerate(lines):
            upper = line.upper()
            if any(kw in upper for kw in ['ERROR', 'FAIL', 'CRASH', 'FAULT', 'TIMEOUT']):
                start = max(0, i - 2)
                end = min(len(lines), i + 3)
                important_lines.extend(lines[start:end])
                important_lines.append("---")

        if important_lines:
            error_context = "\n".join(important_lines[:30])
            actual_output = (
                actual_output[:500]
                + "\n\n... [中间省略] ...\n\n"
                + f"[关键错误上下文]\n{error_context}\n\n"
                + actual_output[-500:]
            )
        else:
            actual_output = (
                actual_output[:1000]
                + "\n\n... [中间省略] ...\n\n"
                + actual_output[-1500:]
            )

    if len(test_steps) > 500:
        test_steps = test_steps[:500] + "..."

    parts = [
        f"用例 ID: {case_id}",
        f"用例描述: {description}",
        f"测试步骤:\n{test_steps}",
        f"预期结果: {expected_result}",
        f"判定理由: {match_reason}" if match_reason else "",
        f"错误信息: {error_msg}" if error_msg else "",
        f"实际执行输出:\n{actual_output}",
    ]

    return "\n\n".join(p for p in parts if p)
