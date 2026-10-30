"""构建用例「备注」内容。

备注由 AI 判定信息与执行日志组成，格式与下载结果 Excel 的备注列保持一致：

    [AI判定] Pass (置信度=0.95)
    判定依据: ...
    - 证据1
    --- 执行日志 ---
    <日志全文>

无 AI 判定时仅包含执行日志；两者都没有时回退到用例原有备注。

下载结果时可通过 include_log=False 生成「不含执行日志」的备注。
"""
import os
import re
from typing import Any, Iterable, List, Mapping, Optional

# backend/ 目录（app/core/remarks.py → app/core → app → backend）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LOG_SEPARATOR_RE = re.compile(r"^-{3,}\s*执行日志\s*-{3,}$")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EVIDENCE_MIN_LENGTH = 4
_REMARK_MAX_LENGTH = 32000


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
    include_log: bool = True,
) -> str:
    """按 Excel 备注列的格式拼接 AI 判定信息与执行日志。

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
        for evidence in ai_evidence or []:
            if evidence:
                parts.append(f"- {evidence}")

    if include_log and log_content.strip():
        if parts:
            parts.append("--- 执行日志 ---")
        parts.append(log_content)

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


def build_remark_from_case(case: Any, include_log: bool = True) -> str:
    """从 TestCase 对象或 /cases 返回的字典构建备注。"""
    return compose_remark(
        ai_judged=bool(_get(case, "ai_judged", False)),
        ai_status=_get(case, "ai_status", "") or "",
        ai_confidence=_get(case, "ai_confidence", 0.0) or 0.0,
        ai_reason=_get(case, "ai_reason", "") or "",
        ai_evidence=_get(case, "ai_evidence", []) or [],
        log_content=read_log_content(_get(case, "log_file", "") or ""),
        fallback_remarks=_get(case, "remarks", "") or "",
        include_log=include_log,
    )


def _normalize_log_line(value: str) -> str:
    """与前端 CaseLogModal 一致：折叠空白后做证据行宽松匹配。"""
    return re.sub(r"\s+", " ", value or "").strip()


def _remark_highlight_color(status: str) -> str:
    """按判定状态选择证据行颜色（Excel ARGB）：Fail 红 / Pass 绿 / 其它黄。"""
    text = str(status or "").lower()
    if "fail" in text:
        return "FFD32F2F"
    if "pass" in text:
        return "FF2E7D32"
    return "FFB8860B"


def _remark_status_from_text(lines: List[str]) -> str:
    """从备注首行 ``[AI判定] <状态>`` 提取状态，供旧结果文件重新着色。"""
    first = next((line.strip() for line in lines if line.strip()), "")
    matched = re.match(r"\[AI判定\]\s*([A-Za-z_]+)", first)
    return matched.group(1) if matched else ""


def colorize_remark_text(
    remark: str,
    *,
    status: str = "",
    evidence: Optional[Iterable[str]] = None,
):
    """把备注中与 AI 证据匹配的行转成带颜色的富文本。

    返回 ``CellRichText``（找到可高亮行时）或原字符串，规则与前端
    「执行日志」弹窗一致：
    - 备注中有 ``--- 执行日志 ---`` 时才着色；
    - 日志区逐行匹配，AI 判定区中的 ``- xxx`` 证据行也一并着色，
      这样备注单元格折叠时也能直接看到关键证据；
    - 日志行/证据行与 AI 证据（``ai_evidence``，或备注 AI 区块中的
      ``- xxx``）归一化后互相包含即视为同一条证据；
    - Fail 红色、Pass 绿色、其它（Review 等）黄色。
    """
    from openpyxl.cell.rich_text import CellRichText, TextBlock
    from openpyxl.cell.text import InlineFont

    if not isinstance(remark, str) or not remark.strip():
        return remark

    text = _CONTROL_CHAR_RE.sub("", remark)
    if len(text) > _REMARK_MAX_LENGTH:
        text = text[:_REMARK_MAX_LENGTH] + " ... (内容过长已截断)"

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    separator_index = next(
        (i for i, line in enumerate(lines) if _LOG_SEPARATOR_RE.match(line.strip())),
        None,
    )
    if separator_index is None:
        return text

    raw_evidence = list(evidence or [])
    if not raw_evidence:
        # 兼容仅从备注文本解析证据的情况（格式约定：AI 区块中的 "- xxx"）
        raw_evidence = [
            line.strip()[2:].strip()
            for line in lines[:separator_index]
            if line.strip().startswith("- ")
        ]
    evidence_keys = {
        _normalize_log_line(item)
        for item in raw_evidence
        if len(_normalize_log_line(item)) >= _EVIDENCE_MIN_LENGTH
    }
    if not evidence_keys:
        return text

    color = _remark_highlight_color(status or _remark_status_from_text(lines))
    font = InlineFont(color=color, b=True)
    blocks: List[Any] = []
    highlighted = 0

    for index, line in enumerate(lines):
        # AI 判定区只处理 "- 证据" 行，避免把整段判定依据误标色；
        # 日志区则逐行匹配，与前端执行日志弹窗一致。
        eligible = index > separator_index or (
            index < separator_index and line.strip().startswith("- ")
        )
        if eligible and line.strip():
            normalized = _normalize_log_line(line)
            if len(normalized) >= _EVIDENCE_MIN_LENGTH and any(
                normalized in key or key in normalized for key in evidence_keys
            ):
                blocks.append(TextBlock(font, line))
                highlighted += 1
            else:
                blocks.append(line)
        else:
            blocks.append(line)
        if index < len(lines) - 1:
            blocks.append("\n")

    if not highlighted:
        return text
    return CellRichText(blocks)


def build_rich_remark_from_case(case: Any, include_log: bool = True):
    """构建带证据行高亮的备注，用于写回 Excel 备注列。"""
    text = build_remark_from_case(case, include_log=include_log)
    if not include_log or not text.strip():
        return text
    return colorize_remark_text(
        text,
        status=str(_get(case, "ai_status", "") or _get(case, "status", "") or ""),
        evidence=_get(case, "ai_evidence", []) or [],
    )
