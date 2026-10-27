"""构建用例「备注」内容。

备注由 AI 判定信息与执行日志组成，格式与下载结果 Excel 的备注列保持一致：

    [AI判定] Pass (置信度=0.95)
    判定依据: ...
    - 证据1
    --- 执行日志 ---
    <日志全文>

无 AI 判定时仅包含执行日志；两者都没有时回退到用例原有备注。
"""
import os
from typing import Any, Iterable, List, Mapping, Optional

# backend/ 目录（app/core/remarks.py → app/core → app → backend）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _get(case: Any, key: str, default: Any = None) -> Any:
    """同时兼容 dataclass/对象与 dict 形式的用例。"""
    if isinstance(case, Mapping):
        return case.get(key, default)
    return getattr(case, key, default)


def read_log_content(log_file: str) -> str:
    """读取日志文件全文；路径不存在或读取失败时返回空字符串。"""
    if not log_file:
        return ""

    candidates: List[str] = []
    if os.path.isabs(log_file):
        candidates.append(log_file)
    else:
        candidates.append(log_file)
        candidates.append(os.path.join(_BACKEND_DIR, log_file))

    for path in candidates:
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
        except OSError:
            continue
    return ""


def compose_remark(
    *,
    ai_judged: bool = False,
    ai_status: str = "",
    ai_confidence: float = 0.0,
    ai_reason: str = "",
    ai_evidence: Optional[Iterable[str]] = None,
    log_content: str = "",
    fallback_remarks: str = "",
) -> str:
    """按 Excel 备注列的格式拼接 AI 判定信息与执行日志。"""
    parts: List[str] = []

    if ai_judged:
        try:
            confidence = float(ai_confidence or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        parts.append(f"[AI判定] {ai_status or ''} (置信度={confidence:.2f})")
        if ai_reason:
            parts.append(f"判定依据: {ai_reason}")
        for evidence in ai_evidence or []:
            if evidence:
                parts.append(f"- {evidence}")

    if log_content.strip():
        if parts:
            parts.append("--- 执行日志 ---")
        parts.append(log_content)

    if parts:
        return "\n".join(parts)
    return fallback_remarks or ""


def build_remark_from_case(case: Any) -> str:
    """从 TestCase 对象或 /cases 返回的字典构建备注。"""
    return compose_remark(
        ai_judged=bool(_get(case, "ai_judged", False)),
        ai_status=_get(case, "ai_status", "") or "",
        ai_confidence=_get(case, "ai_confidence", 0.0) or 0.0,
        ai_reason=_get(case, "ai_reason", "") or "",
        ai_evidence=_get(case, "ai_evidence", []) or [],
        log_content=read_log_content(_get(case, "log_file", "") or ""),
        fallback_remarks=_get(case, "remarks", "") or "",
    )
