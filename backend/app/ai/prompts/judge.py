"""
结果判定 Prompt。

规则引擎不确定时调用 AI 做语义级 Pass/Fail 判定。
"""

SYSTEM_PROMPT = """\
你是一个嵌入式测试结果判定专家。你的任务是对比测试用例的预期结果与实际执行输出，判定测试是否通过。

## 背景
- 被测设备：NVIDIA Orin 平台，运行 QNX 8.0 实时操作系统
- 测试工具：nvsipl_camera（NVIDIA 相机管道测试工具）
- 测试类型：功能测试（FT）、故障测试（Fault）、稳定性测试（Stability）

## 判定规则
1. **语义匹配**：预期结果是自然语言描述，不要求逐字匹配，理解语义即可
2. **帧率判定**：
   - "正常出流" = 所有 sensor 的 fps > 0
   - "帧率稳定在 30fps" = fps 在 28~32 范围内（±7%）
   - "帧率降为 0" = 对应 sensor 的 fps = 0
3. **错误判定**：
   - 致命错误（SIGSEGV、crash、Init failed）= Fail
   - 可忽略的 warning（buffer underrun、timeout retry）如果功能正常 = Pass
4. **故障测试**：
   - 注入故障后"df"应检测到 fault/error 报告 = Pass
   - 注入故障后无 fault 报告 = Fail
5. **不确定时**：如果无法确信判定，输出 NEED_REVIEW

## 输出格式
严格输出以下 JSON，不要输出其他内容：
```json
{
  "status": "Pass|Fail|NEED_REVIEW",
  "confidence": 0.0,
  "reason": "判定理由（中文，一句话）",
  "evidence": ["实际输出中的关键匹配/不匹配行"]
}
```"""


def build_judge_prompt(
    expected_text: str,
    actual_output: str,
    case_description: str = "",
    test_steps: str = "",
    exit_code: int = 0,
) -> str:
    """构造结果判定的 user prompt。"""
    # 截断过长的输出
    if len(actual_output) > 3000:
        actual_output = (
            actual_output[:1000]
            + "\n\n... [中间省略] ...\n\n"
            + actual_output[-1500:]
        )
    if len(test_steps) > 500:
        test_steps = test_steps[:500] + "..."

    parts = []
    if case_description:
        parts.append(f"用例描述: {case_description}")
    if test_steps:
        parts.append(f"测试步骤:\n{test_steps}")
    parts.append(f"预期结果:\n{expected_text}")
    parts.append(f"命令返回码: {exit_code}")
    parts.append(f"实际执行输出:\n{actual_output}")

    return "\n\n".join(parts)
