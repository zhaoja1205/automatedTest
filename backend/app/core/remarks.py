"""构建用例「BUG」与「备注」内容。

结果 Excel 中两列分工：
- 「BUG」列：AI 判定信息（状态、判定理由、证据）；
- 「备注」列：执行日志。

「BUG」列格式：::

    [AI判定] Pass (置信度=0.95)
    判定依据: ...

「备注」列格式：::

    --- 执行日志 ---
    ===== 终端A =====
    <终端A 日志>
    ===== 终端B =====
    <终端B 日志>

日志按终端分段存储（与板端日志系统 ``<基名>.<终端>.term.log`` 的文本格式一致），
没有终端级日志的旧记录仍按聚合日志原样保存。

前端临时展示仍使用合并格式（AI 判定 + 执行日志），由
``build_remark_from_case`` 生成；下载结果时备注列始终附带执行日志。
"""
import os
from typing import Any, Iterable, List, Mapping, Optional

from app.core.terminal_log import load_terminal_log_text, strip_ansi_sequences

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
                    # 旧日志可能仍带 ANSI 控制序列（如 ESC[?2004l），统一剔除
                    return strip_ansi_sequences(f.read())
        except OSError:
            continue
    return ""


def read_case_log(log_file: str) -> str:
    """读取用例日志：优先聚合日志文件，缺失时回退按终端落盘的日志。

    聚合日志本身已按 ``===== 终端 =====`` 分段；仅当聚合文件不存在
    （例如只保留了终端级日志）时，才用板端日志系统的终端文件拼出同样格式。
    """
    content = read_log_content(log_file)
    if content.strip():
        return content
    return load_terminal_log_text(log_file)


def compose_remark(
    *,
    ai_judged: bool = False,
    ai_status: str = "",
    ai_confidence: float = 0.0,
    ai_reason: str = "",
    ai_evidence: Optional[Iterable[str]] = None,
    include_evidence: bool = True,
    log_content: str = "",
    fallback_remarks: str = "",
    include_log: bool = True,
) -> str:
    """按 Excel 备注列的格式拼接 AI 判定信息与执行日志。

    include_evidence=False 时不输出证据行（「BUG」列只保留状态与理由）；
    include_log=False 时只保留 AI 判定信息，必要时从回退备注中剔除日志段。
    """
    parts: List[str] = []

    if ai_judged:
        try:
            confidence = float(ai_confidence or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        parts.append(f"[AI判定] {ai_status or ''} (置信度={confidence:.2f})")
        if ai_reason:
            parts.append(f"判定依据: {ai_reason}")
        if include_evidence:
            for evidence in ai_evidence or []:
                if evidence:
                    parts.append(f"- {evidence}")

    if include_log:
        # 日志文件缺失时（草稿恢复 / 历史导入的日志只存在备注中），回退到
        # 兜底备注里的日志段，避免重新判定后整个板端日志被丢掉。
        # 没有 AI 判定段时仍按原逻辑整体回退，保持旧备注原样。
        effective_log = log_content
        if not effective_log.strip() and parts:
            effective_log = extract_log_section(fallback_remarks or "")
        if effective_log.strip():
            # 始终带日志段标记：前端据此提取日志，「不含日志」下载据此剔除日志
            parts.append("--- 执行日志 ---")
            parts.append(effective_log)

    if parts:
        return "\n".join(parts)

    fallback = fallback_remarks or ""
    if not include_log:
        fallback = strip_log_section(fallback)
    return fallback


def strip_log_section(remark: str) -> str:
    """移除备注中的「--- 执行日志 ---」及其后的日志内容。"""
    if not remark:
        return ""
    marker = "--- 执行日志 ---"
    idx = remark.find(marker)
    if idx < 0:
        return remark
    return remark[:idx].rstrip()


def extract_log_section(remark: str) -> str:
    """取出备注中「--- 执行日志 ---」之后的日志内容。"""
    if not remark:
        return ""
    marker = "--- 执行日志 ---"
    idx = remark.find(marker)
    if idx < 0:
        return ""
    return remark[idx + len(marker):].strip("\r\n")


def extract_evidence_lines(judgment: str) -> List[str]:
    """从「BUG」列内容中提取 AI 证据行（以 ``- `` 开头的行）。"""
    if not judgment:
        return []
    return [
        line.strip()[2:].strip()
        for line in judgment.replace("\r\n", "\n").split("\n")
        if line.strip().startswith("- ") and line.strip()[2:].strip()
    ]


def strip_evidence_lines(judgment: str) -> str:
    """移除 BUG 列中的 AI 证据行（只对系统生成的 ``[AI判定]`` 内容生效）。"""
    if not judgment or "[AI判定]" not in judgment:
        return judgment
    lines = judgment.replace("\r\n", "\n").split("\n")
    kept = [line for line in lines if not line.lstrip().startswith("- ")]
    return "\n".join(kept).rstrip()


def build_remark_from_case(case: Any, include_log: bool = True) -> str:
    """从 TestCase 对象或 /cases 返回的字典构建合并备注（供前端展示）。"""
    return compose_remark(
        ai_judged=bool(_get(case, "ai_judged", False)),
        ai_status=_get(case, "ai_status", "") or "",
        ai_confidence=_get(case, "ai_confidence", 0.0) or 0.0,
        ai_reason=_get(case, "ai_reason", "") or "",
        ai_evidence=_get(case, "ai_evidence", []) or [],
        log_content=read_case_log(_get(case, "log_file", "") or ""),
        fallback_remarks=_get(case, "remarks", "") or "",
        include_log=include_log,
    )


def _has_ai_section(remark: str) -> bool:
    """判断备注是否含旧格式的 AI 判定段。"""
    return "[AI判定]" in (remark or "")


def build_judgment_from_case(case: Any) -> str:
    """构建结果 Excel「BUG」列内容（AI 状态与理由，不含证据与执行日志）。

    优先使用用例上的 AI 判定字段；兼容旧文件时，从原备注中提取 AI 判定段。
    """
    if bool(_get(case, "ai_judged", False)):
        return compose_remark(
            ai_judged=True,
            ai_status=_get(case, "ai_status", "") or "",
            ai_confidence=_get(case, "ai_confidence", 0.0) or 0.0,
            ai_reason=_get(case, "ai_reason", "") or "",
            ai_evidence=_get(case, "ai_evidence", []) or [],
            include_evidence=False,
            include_log=False,
        )

    # 已写入 Excel「BUG」列的内容（例如重新上传后再次保存）
    loaded = _get(case, "judgment", "") or ""
    if loaded:
        return strip_evidence_lines(loaded)

    fallback = _get(case, "remarks", "") or ""
    if _has_ai_section(fallback):
        return strip_evidence_lines(strip_log_section(fallback))
    return ""


def build_log_remark_from_case(case: Any, include_log: bool = True) -> str:
    """构建结果 Excel「备注」列内容（仅执行日志）。

    include_log=False 时不写日志，并剔除原备注中残留的日志段。
    """
    if include_log:
        log_content = read_case_log(_get(case, "log_file", "") or "")
        if not log_content.strip():
            # 没有日志文件时（草稿恢复 / 历史导入），日志可能只存在于备注里
            log_content = extract_log_section(_get(case, "remarks", "") or "")
        if log_content.strip():
            return compose_remark(log_content=log_content)

    if bool(_get(case, "ai_judged", False)):
        # AI 判定已写入「BUG」列，备注不再重复
        return ""

    fallback = _get(case, "remarks", "") or ""
    if _has_ai_section(fallback):
        # 旧格式备注中的 AI 判定段归属「BUG」列，备注不再重复
        return ""
    if not include_log:
        fallback = strip_log_section(fallback)
    return fallback


