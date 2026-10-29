"""测试失败时自动登记 BugList 条目。

将状态为 Fail 的用例转换为 BugList统计 页所需的一行数据：
    No. / Bug ID / Module / Description / Version /
    Severity / Status / Tester / Date / Effective / Comment

生成的 Bug ID 固定为 ``BUG-<用例编号>``，同一用例重复失败时更新原条目，
避免每次执行都新增重复 Bug。
"""
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

# 自动登记时的初始值（未知信息不臆造，留给人工补充）
DEFAULT_SEVERITY = "待评估"
DEFAULT_STATUS = "Open"
# Effective 表示缺陷是否有效；自动登记时尚未人工确认，统一填「待确认」
DEFAULT_EFFECTIVE = "待确认"


def _text(obj: Any, key: str, default: str = "") -> str:
    value = getattr(obj, key, default)
    if value is None:
        return default
    return str(value).strip()


def _truncate(text: str, limit: int = 800) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + " ..."


def build_bug_id(case: Any, duplicate_case_ids: Optional[Set[str]] = None) -> str:
    """由用例编号生成稳定的 Bug ID，便于重复执行时去重。

    工作簿内存在重复用例编号时追加行号，避免把不同用例的失败合并成同一个 Bug。
    """
    case_id = _text(case, "case_id")
    if not case_id:
        return "BUG-UNKNOWN"
    if duplicate_case_ids and case_id in duplicate_case_ids:
        row = _text(case, "row_number")
        if row:
            return f"BUG-{case_id}-{row}"
    return f"BUG-{case_id}"


def _date_text(case: Any) -> str:
    """BugList 的 Date 列只保留日期部分。"""
    raw = _text(case, "test_date")
    if not raw:
        return datetime.now().strftime("%Y-%m-%d")
    match = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return match.group(1) if match else raw


def _failure_reason(case: Any) -> str:
    """提取失败原因：优先 AI 判定理由，其次实际结果首行。"""
    reason = _text(case, "ai_reason")
    if reason:
        return _truncate(reason)

    actual = _text(case, "actual_result")
    for line in actual.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # 去掉 "[Fail]"/"[待确认]" 等状态前缀
        stripped = re.sub(r"^\[[^\]]+\]\s*", "", stripped)
        if stripped:
            return _truncate(stripped)

    return _truncate(_text(case, "remarks"))


def _bug_description(case: Any) -> str:
    """BugList 的 Description 列：优先 AI 生成的 Bug 描述，其次失败原因/用例描述。"""
    ai_description = _text(case, "bug_description")
    if ai_description:
        return ai_description
    reason = _failure_reason(case)
    if reason:
        return reason
    return _text(case, "description") or _text(case, "case_id")


def _bug_severity(case: Any) -> str:
    """BugList 的 Severity 列：优先 AI 评估结果，AI 不可用时填「待评估」。"""
    return _text(case, "bug_severity") or DEFAULT_SEVERITY


def build_bug_entry(
    case: Any,
    *,
    no: str,
    tester: str = "",
    version: str = "",
    duplicate_case_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """把一条失败用例转换为 BugList 行数据。"""
    module = _text(case, "test_type") or _text(case, "source_sheet")
    return {
        "no": no,
        "bug_id": build_bug_id(case, duplicate_case_ids),
        "module": module,
        # 失败原因放在 Description 列，Comment 留给人工补充
        "description": _bug_description(case),
        "version": _text(case, "test_version") or version,
        "severity": _bug_severity(case),
        "status": DEFAULT_STATUS,
        "tester": _text(case, "tester") or tester,
        "date": _date_text(case),
        "effective": DEFAULT_EFFECTIVE,
        "comment": "",
        "row_number": 0,
        "source_sheet": "",
    }


def _next_no(entries: List[Dict[str, Any]]) -> int:
    max_no = len(entries)
    for entry in entries:
        raw = str(entry.get("no", "")).strip()
        try:
            max_no = max(max_no, int(float(raw)))
        except (TypeError, ValueError):
            continue
    return max_no + 1


def sync_failed_cases_to_bug_list(
    cases: List[Any],
    existing: Optional[List[Dict[str, Any]]] = None,
    *,
    tester: str = "",
    version: str = "",
) -> Tuple[List[Dict[str, Any]], int]:
    """把失败用例合并进 BugList 条目。

    返回 ``(合并后的条目, 新增条数)``。已存在的 Bug 条目保留人工维护的
    No./Status/Effective 等字段；描述、严重程度等由 AI 生成的动态信息会刷新，
    但 AI 不可用（字段为空）时保留原值。
    """
    entries = [dict(item) for item in (existing or [])]
    index: Dict[str, int] = {
        str(entry.get("bug_id", "")).strip(): i
        for i, entry in enumerate(entries)
        if str(entry.get("bug_id", "")).strip()
    }
    next_no = _next_no(entries)
    added = 0
    # 全量用例中重复的用例编号，需要附加行号区分
    duplicate_case_ids = {
        case_id
        for case_id, count in Counter(_text(c, "case_id") for c in cases).items()
        if case_id and count > 1
    }

    for case in cases:
        if (_text(case, "status") or "").lower() != "fail":
            continue

        bug_id = build_bug_id(case, duplicate_case_ids)
        if bug_id in index:
            entry = entries[index[bug_id]]
            # 旧版本自动登记把失败原因写在 Comment，这里迁移到 Description
            old_reason = _failure_reason(case)
            if str(entry.get("comment", "")).strip() == old_reason.strip():
                entry["comment"] = ""
            # 保留人工维护的 No./Status/Effective，刷新本次失败产生的信息
            for field in ("module", "description", "version", "tester", "date", "severity"):
                value = {
                    "module": _text(case, "test_type") or _text(case, "source_sheet"),
                    "description": _bug_description(case),
                    "version": _text(case, "test_version") or version,
                    "tester": _text(case, "tester") or tester,
                    "date": _date_text(case),
                    # AI 未给出等级时为空，保留条目里原有等级
                    "severity": _text(case, "bug_severity"),
                }[field]
                if value:
                    entry[field] = value
            continue

        entry = build_bug_entry(
            case, no=str(next_no), tester=tester, version=version,
            duplicate_case_ids=duplicate_case_ids,
        )
        next_no += 1
        index[bug_id] = len(entries)
        entries.append(entry)
        added += 1

    return entries, added
