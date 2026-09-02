"""
报告生成 Prompt。

执行完成后生成结构化测试报告。
"""

SYSTEM_PROMPT = """\
你是一个测试报告撰写专家。基于本轮测试执行结果，生成一份结构化的测试报告。

## 报告结构
1. **执行概况**：总数、通过、失败、NA、跳过、通过率、执行时长
2. **失败用例分析**：逐条列出失败用例的根因和建议（如果有 AI 分析结果则整合）
3. **关键发现**：值得关注的异常模式或趋势
4. **建议**：优先处理事项

## 报告规范
- 使用 Markdown 格式
- 中文撰写
- 失败用例按严重程度排序（真实缺陷 > 环境问题 > 用例问题 > 间歇性 > 判定不匹配）
- 每条失败用例附 case_id、描述、根因分类、一句话分析
- 建议要可操作（明确写出做什么、怎么做）
- 如果所有用例都通过，写一份简短的通过报告即可"""


def build_report_prompt(
    execution_summary: dict,
    results: list[dict],
    analyses: list[dict] | None = None,
) -> str:
    """构造报告生成的 user prompt。

    参数:
        execution_summary: {total, pass, fail, na, skip, duration_seconds, date, sheet}
        results: [{case_id, description, status, match_reason, error_msg}, ...]
        analyses: AI 失败分析结果（可选）
    """
    parts = ["## 执行概况数据"]

    summary_lines = [
        f"- 执行日期: {execution_summary.get('date', '未知')}",
        f"- 测试 Sheet: {execution_summary.get('sheet', '未知')}",
        f"- 总用例数: {execution_summary.get('total', 0)}",
        f"- 通过: {execution_summary.get('pass', 0)}",
        f"- 失败: {execution_summary.get('fail', 0)}",
        f"- NA: {execution_summary.get('na', 0)}",
        f"- 跳过/未执行: {execution_summary.get('skip', 0)}",
        f"- 执行时长: {execution_summary.get('duration_seconds', 0):.0f}s",
    ]
    total = execution_summary.get('total', 0)
    passed = execution_summary.get('pass', 0)
    if total > 0:
        rate = passed / total * 100
        summary_lines.append(f"- 通过率: {rate:.1f}%")
    parts.append("\n".join(summary_lines))

    # 失败用例详情
    fail_results = [r for r in results if r.get("status", "").upper() == "FAIL"]
    if fail_results:
        parts.append("\n## 失败用例详情")
        for r in fail_results:
            case_id = r.get("case_id", "")
            desc = r.get("description", "")
            reason = r.get("match_reason", "")
            error = r.get("error_msg", "")
            lines = [f"### {case_id} — {desc}"]
            if reason:
                lines.append(f"判定理由: {reason}")
            if error:
                lines.append(f"错误信息: {error}")

            # 整合 AI 分析
            if analyses:
                analysis = next(
                    (a for a in analyses if a.get("case_id") == case_id), None
                )
                if analysis:
                    lines.append(f"AI 根因: [{analysis.get('root_cause_category', '')}] {analysis.get('root_cause_summary', '')}")
                    suggestions = analysis.get("suggestion", [])
                    if suggestions:
                        lines.append("AI 建议: " + "; ".join(suggestions))

            parts.append("\n".join(lines))

    # 通过用例摘要
    pass_results = [r for r in results if r.get("status", "").upper() == "PASS"]
    if pass_results:
        parts.append(f"\n## 通过用例\n共 {len(pass_results)} 条用例通过，此处不逐条列出。")

    # NA 用例
    na_results = [r for r in results if r.get("status", "").upper() == "NA"]
    if na_results:
        na_ids = [r.get("case_id", "") for r in na_results]
        parts.append(f"\n## NA 用例\n不适用用例 ({len(na_results)} 条): {', '.join(na_ids)}")

    return "\n\n".join(parts)
