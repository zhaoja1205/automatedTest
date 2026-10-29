"""
数据统计页文案生成 Prompt。

根据本轮测试的执行数据，生成「数据统计」页中
「测试基本信息」「质量/效率目标」「测试总结」三栏内容。
"""

SYSTEM_PROMPT = """\
你是一个嵌入式软件测试报告撰写专家。请根据本轮测试的执行数据，填写 Excel
「数据统计」页中的三栏内容：测试基本信息、质量/效率目标、测试总结。

## 测试基本信息
- 使用「字段：值」的形式，每行一项
- 字段包括：测试人员、测试版本、测试日期、测试范围、测试环境、执行耗时
- 只使用给定的数据；未提供或为空的字段写「未填写」
- 不要编造项目名、客户名、设备型号或环境参数

## 质量/效率目标
- 用 3~5 条列出本轮测试的质量与效率目标，并注明实际达成情况
- 常用的目标维度：执行率 100%、Pass率、Block 用例数、致命/严重缺陷闭环情况
- 若未提供正式项目指标，按嵌入式测试常用基线给出合理目标
  （执行率 100%、Pass率 ≥ 90%、无未登记的致命/严重缺陷）
- 目标与实际不一致时如实写明差距，不要粉饰

## 测试总结
- 3~6 句话，概括测试范围、执行情况、通过/失败分布、主要问题与风险
- 指出失败集中在哪些模块或类型，引用给定数据，不臆造根因
- 最后给出一句总体结论（可发布 / 有条件发布 / 需修复后回归）
- 只使用给定数据，不编造未出现的缺陷或日志内容

## 输出格式
严格输出以下 JSON，不要输出其他内容。三个字段的值使用 \\n 换行：
```json
{
  "basic_info": "测试人员：张三\\n测试版本：V1.0\\n测试日期：2026-10-29\\n测试范围：功能测试、故障测试\\n测试环境：192.168.1.10\\n执行耗时：12 分钟",
  "quality_goal": "1. 执行率目标 100%，实际 95.2%，有 4 条用例未执行；\\n2. Pass率目标 ≥ 90%，实际 88.0%，未达标；\\n3. Block 用例目标 0，实际 1 条；\\n4. 致命/严重缺陷均已登记 BugList 并跟踪。",
  "summary": "本轮覆盖功能测试与故障测试共 120 条用例，已执行 114 条，Pass 88 条、Fail 12 条、Block 1 条。失败主要集中在故障注入场景，表现为恢复后画面异常。整体质量存在风险，建议修复 Fail 用例并完成回归后发布。"
}
```"""


def _fmt_rate(value) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _fmt_minutes(seconds) -> str:
    try:
        seconds = float(seconds or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        return "未记录"
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    return f"{seconds / 60:.1f} 分钟"


def _truncate(text: str, limit: int) -> str:
    text = str(text or "").strip().replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "..."


def build_statistics_prompt(data: dict) -> str:
    """构造数据统计页文案生成的 user prompt。

    参数 data:
        workbook / tester / version / test_date / environment /
        duration_seconds / sheets / total / executed / pass / fail / nt /
        block / na / review / execute_rate / pass_rate / fail_rate /
        block_rate / sheet_rows / failures / severity_dist
    """
    info = [
        "## 测试基本信息候选数据",
        f"- 项目/工作簿: {data.get('workbook') or '未填写'}",
        f"- 测试人员: {data.get('tester') or '未填写'}",
        f"- 测试版本: {data.get('version') or '未填写'}",
        f"- 测试日期: {data.get('test_date') or '未填写'}",
        f"- 测试环境: {data.get('environment') or '未填写'}",
        f"- 执行耗时: {_fmt_minutes(data.get('duration_seconds'))}",
        f"- 测试范围: {'、'.join(data.get('sheets') or []) or '未填写'}",
    ]

    stats = [
        f"- 用例总数: {data.get('total', 0)}",
        f"- 已执行（不含 NT/NA）: {data.get('executed', 0)}",
        f"- Pass: {data.get('pass', 0)}",
        f"- Fail: {data.get('fail', 0)}",
        f"- Block: {data.get('block', 0)}",
        f"- 待确认(Review): {data.get('review', 0)}",
        f"- NT: {data.get('nt', 0)}",
        f"- NA: {data.get('na', 0)}",
        f"- 执行率: {_fmt_rate(data.get('execute_rate'))}",
        f"- Pass率: {_fmt_rate(data.get('pass_rate'))}（基准为已执行数）",
        f"- Fail率: {_fmt_rate(data.get('fail_rate'))}",
        f"- Block率: {_fmt_rate(data.get('block_rate'))}",
    ]

    rows = data.get("sheet_rows") or []
    if rows:
        line = ["## 分类统计"]
        for row in rows:
            line.append(
                f"- {row.get('sheet', '未分类')}: 总数 {row.get('total', 0)}，"
                f"Pass {row.get('pass', 0)}，Fail {row.get('fail', 0)}，"
                f"Block {row.get('block', 0)}，NT {row.get('nt', 0)}，"
                f"NA {row.get('na', 0)}，待确认 {row.get('review', 0)}，"
                f"Pass率 {_fmt_rate(row.get('pass_rate'))}"
            )

    severity = data.get("severity_dist") or {}
    if severity:
        dist = ["## Fail 用例严重程度分布"]
        for key, value in severity.items():
            dist.append(f"- {key}: {value} 条")

    failures = data.get("failures") or []
    if failures:
        block = ["## 失败用例（最多 20 条）"]
        for item in failures[:20]:
            parts = [f"- {item.get('case_id') or '未知用例'}"]
            if item.get("sheet"):
                parts.append(f"[{item['sheet']}]")
            desc = _truncate(item.get("description", ""), 80)
            if desc:
                parts.append(desc)
            reason = _truncate(item.get("reason", ""), 160)
            if reason:
                parts.append(f"判定理由: {reason}")
            severity_text = _truncate(item.get("severity", ""), 20)
            if severity_text:
                parts.append(f"等级: {severity_text}")
            block.append(" ".join(parts))

    parts = [
        "## 基本数据",
        "\n".join(info),
        "## 执行统计\n" + "\n".join(stats),
    ]
    if rows:
        parts.append("\n".join(line))
    if severity:
        parts.append("\n".join(dist))
    if failures:
        parts.append("\n".join(block))
    return "\n\n".join(parts)
