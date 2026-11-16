"""按终端日志的统一读写格式。

执行器在用例执行期间把每个终端的原始输出分别写入
``<用例日志基名>.<终端名>.term.log``，并写出 ``<基名>.terminals.json``
清单（板端日志 / 结果下载 / 日志弹窗均以该格式为准）。

本模块集中提供：

- :func:`read_terminal_logs` —— 按清单或命名约定读取一个用例的各终端日志；
- :func:`format_terminal_log` —— 把 ``[(终端, 内容)]`` 拼成统一的文本格式；
- :func:`parse_terminal_log` —— 从统一文本格式中拆回各终端；
- :func:`load_terminal_log_text` —— 读取并格式化，供备注列 / 草稿箱复用。

统一文本格式（与执行器 ``terminal_log`` 一致）::

    ===== 终端A =====
    <终端A 输出>

    ===== 终端B =====
    <终端B 输出>
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Iterable, List, Mapping, Tuple, Union

TERMINAL_LOG_SUFFIX = ".term.log"
MANIFEST_SUFFIX = ".terminals.json"

# PTY 日志中的 ANSI/OSC 控制序列（颜色、光标、括号粘贴模式等）。
# 例如 bash 在提示符处会输出 ``ESC[?2004h`` / ``ESC[?2004l``，
# 文本日志里 ESC 不可见，只剩 ``[?2004l``，需要统一剔除。
_ANSI_RE = re.compile(
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC ... BEL / ST
    r"|\x1b\[[0-9;?]*[ -/]*[@-~]"          # CSI ... final byte
    r"|\x1b[()][A-Za-z0-9]"                # 字符集切换
)


def strip_ansi_sequences(text: str) -> str:
    """剔除终端控制序列与不可见控制字符，供日志 / 备注 / 图片统一使用。"""
    cleaned = _ANSI_RE.sub("", text or "")
    # 兼容早期日志：ESC 已被其它环节丢掉，只剩括号粘贴模式标记
    cleaned = re.sub(r"\[\?2004[hl]", "", cleaned)
    # 去掉残留的 ESC、BEL 等不可见控制字符（保留换行与制表符）
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", cleaned)


# 终端分段标题必须严格为「恰好 5 个等号 + 非空标签 + 恰好 5 个等号」。
# 标签内不允许再出现 ``=``，避免把日志中的 ``====================``
# 分隔线误识别成终端标题。
_HEADER_RE = re.compile(r"^=====\s*([^=]+?)\s*=====$")
# 日志中与终端标题同样格式、但属于系统分区的标题，不能当作终端
_NON_TERMINAL_TITLES = ("完整执行日志", "板端系统日志")
# backend/ 目录（app/core/terminal_log.py → app/core → app → backend）
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TerminalEntry = Union[Mapping[str, str], Tuple[str, str]]


def _existing_path(path: str) -> str:
    """返回实际存在的路径（兼容相对 backend/ 的旧记录）。"""
    if not path:
        return ""
    candidates = [path]
    if not os.path.isabs(path):
        candidates.append(os.path.join(_BACKEND_DIR, path))
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return ""


def _read_file(path: str) -> str:
    resolved = _existing_path(path)
    if not resolved:
        return ""
    try:
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _is_within(path: str, root: str) -> bool:
    if not root:
        return True
    root_abs = os.path.abspath(root)
    path_abs = os.path.abspath(path)
    return path_abs == root_abs or path_abs.startswith(root_abs + os.sep)


def read_terminal_logs(log_file: str, safe_root: str = "") -> List[Tuple[str, str]]:
    """读取某条用例按终端分别落盘的日志，返回 ``[(终端标签, 内容)]``。

    优先读取执行器写出的 ``<基名>.terminals.json`` 清单；
    没有清单时按 ``<基名>.<终端>.term.log`` 命名约定回退扫描。
    文件不存在或为空时返回空列表，由调用方回退到聚合日志。

    ``safe_root`` 用于接口层限制只读取指定目录（如 ``logs/``）下的文件。
    """
    log_file = (log_file or "").strip()
    if not log_file:
        return []

    base = os.path.splitext(os.path.abspath(log_file))[0]
    terminals: List[Tuple[str, str]] = []

    manifest = None
    manifest_path = f"{base}{MANIFEST_SUFFIX}"
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, ValueError):
        manifest = None

    if isinstance(manifest, dict):
        for item in manifest.get("terminals", []) or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            file_path = str(item.get("file") or "").strip()
            if not label or not file_path or not _is_within(file_path, safe_root):
                continue
            content = _read_file(file_path)
            if content.strip():
                terminals.append((label, strip_ansi_sequences(content)))

    if terminals:
        return terminals

    # 兼容没有清单的日志：按 ``<基名>.<终端>.term.log`` 扫描
    base_name = os.path.basename(base)
    for file_path in sorted(glob.glob(f"{base}.*{TERMINAL_LOG_SUFFIX}")):
        if not _is_within(file_path, safe_root):
            continue
        name = os.path.basename(file_path)
        label = name[len(base_name) + 1:-len(TERMINAL_LOG_SUFFIX)]
        if not label:
            continue
        content = _read_file(file_path)
        if content.strip():
            terminals.append((label, strip_ansi_sequences(content)))
    return terminals


def _iter_entries(terminals: Iterable[TerminalEntry]) -> Iterable[Tuple[str, str]]:
    for item in terminals or []:
        if isinstance(item, Mapping):
            label = str(item.get("label") or "")
            content = str(item.get("content") or item.get("text") or "")
        else:
            try:
                label, content = item  # type: ignore[misc]
            except (TypeError, ValueError):
                continue
            label = str(label or "")
            content = str(content or "")
        yield label.strip(), content


def _strip_header(label: str, content: str) -> str:
    """去掉内容开头已带的 ``===== 终端 =====`` 标题，避免重复。"""
    text = strip_ansi_sequences(content).replace("\r\n", "\n").replace("\r", "\n")
    if not label:
        return text.strip("\n")
    lines = text.split("\n")
    index = 0
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index < len(lines):
        matched = _HEADER_RE.match(lines[index].strip())
        if matched and matched.group(1).strip() == label:
            text = "\n".join(lines[index + 1:])
    return text.strip("\n")


def _match_terminal_header(line: str) -> str:
    """判断一行是否为终端分段标题，是则返回终端标签，否则返回空串。"""
    matched = _HEADER_RE.match((line or "").strip())
    if not matched:
        return ""
    label = matched.group(1).strip()
    if not label or label.startswith(_NON_TERMINAL_TITLES):
        return ""
    return label


def format_terminal_log(terminals: Iterable[TerminalEntry]) -> str:
    """把各终端日志拼成统一文本格式；空日志会被跳过。"""
    blocks: List[str] = []
    for label, content in _iter_entries(terminals):
        text = _strip_header(label, content)
        if not text.strip():
            continue
        blocks.append(f"===== {label} =====\n{text}" if label else text)
    return "\n\n".join(blocks)


def parse_terminal_log(text: str) -> List[Tuple[str, str]]:
    """从统一文本格式中拆出各终端日志；没有终端标题时返回空列表。"""
    normalized = strip_ansi_sequences(text).replace("\r\n", "\n").replace("\r", "\n")
    terminals: List[Tuple[str, str]] = []
    label = ""
    lines: List[str] = []

    def _flush():
        if not label:
            return
        content = "\n".join(lines).strip("\n")
        if content.strip():
            terminals.append((label, content))

    for line in normalized.split("\n"):
        label_candidate = _match_terminal_header(line)
        if label_candidate:
            _flush()
            label = label_candidate
            lines = []
        elif label:
            lines.append(line)
    _flush()
    return terminals


def load_terminal_log_text(log_file: str) -> str:
    """读取用例按终端落盘的日志并格式化；没有终端级日志时返回空字符串。"""
    return format_terminal_log(read_terminal_logs(log_file))
