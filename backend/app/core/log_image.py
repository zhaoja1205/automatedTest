"""把执行日志渲染成终端风格的 PNG 图片（用于结果 Excel「备注」列）。

视觉与前端用例日志弹窗保持一致：
- 深色背景、浅色等宽文本；
- AI 证据行按判定状态高亮（Pass 绿色、Fail 红色、其它黄色）；
- 未命中证据时，只对明显的 SUCCESS 行做绿色标注；ERROR / 失败等关键字
  不再标红，避免日志里正常的 ``ERROR`` 文本被误认为失败。
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from io import BytesIO
from typing import Iterable, List, Optional, Set, Tuple

from app.core.terminal_log import read_terminal_logs  # noqa: F401  (对外保留读取入口)

# 日志图片渲染缓存：日志内容、高亮行、渲染参数完全相同时直接复用 PNG。
# 导出 Excel 时同一条用例可能被多次渲染（重试 / 多终端 / 多次下载），
# 命中缓存可跳过排版与 PNG 编码。缓存只保存 PNG 字节，每次返回独立的
# BytesIO，避免调用方（openpyxl）消费流后影响后续复用。
# 缓存容量要大于一次导出涉及的图片数（约每条用例 × 终端数），否则第二次
# 导出按顺序渲染时会边写边淘汰，命中率接近 0（典型 LRU 顺序扫描抖动）。
_LOG_IMAGE_CACHE_MAX_ENTRIES = 2048
_LOG_IMAGE_CACHE_MAX_BYTES = 128 * 1024 * 1024

_log_image_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
_log_image_cache_bytes = 0
_log_image_cache_lock = threading.Lock()

# 深色终端配色
_BG = (11, 16, 32)
_FG = (214, 222, 235)
_DIM = (139, 148, 158)
_SUCCESS_FG = (126, 226, 168)

_EVIDENCE_THEMES = {
    "fail": {"fg": (255, 179, 167), "bg": (52, 24, 30), "bar": (255, 107, 107)},
    "pass": {"fg": (159, 245, 200), "bg": (20, 45, 38), "bar": (54, 179, 126)},
    "other": {"fg": (255, 224, 130), "bg": (52, 45, 20), "bar": (255, 213, 79)},
}

_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
)

# 明显的成功关键字（不影响 AI 证据行的主题色）。
# 失败关键字不再参与配色：日志里常见的 ``ERROR`` / ``FAILED`` 文本往往只是
# 被测程序的正常输出，统一标红会让图片看起来像满屏失败。
_SUCCESS_RE = re.compile(r"\b(PASS|PASSED|OK|SUCCESS|SUCCEEDED)\b", re.I)


_RAW_MARKER = "===== 完整执行日志 ====="


def _extract_raw_terminal_entries(
    log_text: str,
) -> List[Tuple[Optional[int], str]]:
    """按行提取终端转录，并携带原始行号（1 起）。

    行号用于「按行号选择高亮」时精确命中某一行，避免日志中存在多行
    完全相同的内容时整片高亮。合成行（如命令与转录之间的空行）没有
    原始行号，用 ``None`` 表示。
    """
    if not log_text:
        return []
    normalized = log_text.replace("\r\n", "\n")
    source_lines = normalized.split("\n")
    marker_index = next(
        (i for i, line in enumerate(source_lines) if _RAW_MARKER in line), None
    )
    if marker_index is None:
        return [(index + 1, line) for index, line in enumerate(source_lines)]

    # 命令回显保留原始行号，方便行号高亮仍能命中
    commands = [
        (index + 1, line)
        for index, line in enumerate(source_lines[:marker_index])
        if line.startswith("$ ")
    ]

    body_start = marker_index + 1
    # 与旧的 lstrip("\r\n") 行为一致：跳过标记后的空行
    while body_start < len(source_lines) and source_lines[body_start] == "":
        body_start += 1

    cut = len(source_lines)
    for index in range(body_start, len(source_lines)):
        stripped = source_lines[index].strip()
        if stripped.startswith("[文件检查]") or stripped.startswith("===== 板端"):
            cut = index
            break

    transcript = [
        (index + 1, source_lines[index])
        for index in range(body_start, cut)
    ]
    while transcript and transcript[0][1] == "":
        transcript.pop(0)
    while transcript and transcript[-1][1] == "":
        transcript.pop()

    entries: List[Tuple[Optional[int], str]] = []
    if commands:
        entries.extend(commands)
        entries.append((None, ""))
    entries.extend(transcript)
    return entries


def extract_raw_terminal_log(log_text: str) -> str:
    """只保留终端输入命令与 PTY 原始终端转录，去掉结构化摘要 / 文件检查 / 板端系统日志。

    PTY 用例的日志结构为::

        $ <命令回显>
        ===== 完整执行日志 =====
        <原始终端转录>
        [文件检查] ...
        ===== 板端系统日志 (...) =====
        <journalctl>

    命令回显（``$ `` 开头）是实际下发的输入，图片中保留并置于转录之前；
    其余摘要、文件检查与系统日志不展示。没有该标记的日志（非 PTY 用例）原样返回。
    """
    return "\n".join(line for _, line in _extract_raw_terminal_entries(log_text))


def _source_entries(
    log_text: str,
    line_offset: int = 0,
) -> List[Tuple[Optional[int], str]]:
    """返回完整日志的每一行及其原始行号（用于按行号高亮）。

    ``line_offset`` 表示传入文本之前已从原始日志中去掉的行数（例如终端
    标题行），保证行号与前端日志弹窗中的行号一致。
    """
    if not log_text:
        return []
    lines = log_text.replace("\r\n", "\n").split("\n")
    return [
        ((index + 1 + line_offset) if index is not None else None, line)
        for index, line in enumerate(lines)
    ]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clear_log_image_cache() -> None:
    """清空日志图片缓存（测试或需要强制重新渲染时使用）。"""
    global _log_image_cache_bytes
    with _log_image_cache_lock:
        _log_image_cache.clear()
        _log_image_cache_bytes = 0


def _log_image_cache_key(
    log_text: str,
    status: str,
    evidence_keys: List[str],
    highlight_line_numbers: Set[int],
    source_line_offset: int,
    width: int,
    max_height: int,
    font_size: int,
    title: str,
) -> tuple:
    """所有影响渲染结果的输入都进入缓存键。

    日志文本可能很长，用 SHA-256 摘要代替原文，避免缓存长期占用日志内存。
    """
    text_digest = hashlib.sha256((log_text or "").encode("utf-8")).hexdigest()
    return (
        text_digest,
        status or "",
        tuple(evidence_keys),
        tuple(sorted(highlight_line_numbers)),
        source_line_offset,
        width,
        max_height,
        font_size,
        title or "",
    )


def _log_image_cache_get(key: tuple) -> Optional[bytes]:
    with _log_image_cache_lock:
        data = _log_image_cache.get(key)
        if data is None:
            return None
        _log_image_cache.move_to_end(key)
        return data


def _log_image_cache_put(key: tuple, data: bytes) -> None:
    global _log_image_cache_bytes
    # 单张图片超过缓存上限时不缓存，避免一张大图把整个缓存清空。
    if len(data) > _LOG_IMAGE_CACHE_MAX_BYTES:
        return
    with _log_image_cache_lock:
        old = _log_image_cache.pop(key, None)
        if old is not None:
            _log_image_cache_bytes -= len(old)
        _log_image_cache[key] = data
        _log_image_cache_bytes += len(data)
        while _log_image_cache and (
            len(_log_image_cache) > _LOG_IMAGE_CACHE_MAX_ENTRIES
            or _log_image_cache_bytes > _LOG_IMAGE_CACHE_MAX_BYTES
        ):
            _old_key, old_data = _log_image_cache.popitem(last=False)
            _log_image_cache_bytes -= len(old_data)


def _load_font(size: int):
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def _wrap_line(text: str, font, max_width: int) -> List[str]:
    """按像素宽度换行；逐字符处理，兼容中文与超长命令行。"""
    if not text:
        return [""]
    out: List[str] = []
    current = ""
    for ch in text:
        candidate = current + ch
        try:
            width = font.getlength(candidate)
        except Exception:
            width = len(candidate) * font.size * 0.6
        if width <= max_width or not current:
            current = candidate
        else:
            out.append(current)
            current = ch
    if current:
        out.append(current)
    return out


def _line_kind(
    line: str,
    evidence_keys: List[str],
    theme_key: str,
    line_number: Optional[int] = None,
    highlight_lines: Optional[Set[int]] = None,
) -> Optional[str]:
    """返回 ``evidence`` / ``success`` / ``dim`` / ``None``。"""
    # 手动按行号选择优先级最高：只高亮选中的那一行，重复内容的其它行不受影响
    if highlight_lines and line_number in highlight_lines:
        return "evidence"
    if line.strip().startswith("…"):
        return "dim"
    normalized = _normalize(line)
    if normalized and len(normalized) >= 4 and evidence_keys:
        for item in evidence_keys:
            # 只允许「日志行包含证据」：证据行若只是日志行的一小段（如公共
            # 前缀 ``nvsipl_camera: ERROR:``）不再命中，避免误高亮其它日志行。
            if item in normalized:
                return "evidence"
    if _SUCCESS_RE.search(line):
        return "success"
    if any(word in line for word in ("成功", "正常", "通过")):
        return "success"
    return None


def render_log_image(
    log_text: str,
    *,
    status: str = "",
    evidence: Optional[Iterable[str]] = None,
    highlight_lines: Optional[Iterable[int]] = None,
    source_line_offset: int = 0,
    width: int = 400,
    max_height: int = 520,
    font_size: int = 10,
    title: str = "",
) -> Optional[BytesIO]:
    """渲染日志图片；无内容或 Pillow 不可用时返回 None。

    ``title`` 非空时在图片顶部绘制一条标题栏，用于标注终端名
    （按终端渲染时每个终端一张图片）。
    ``highlight_lines`` 为用户按行号手动选择的高亮行号（1 起），传入时
    按完整日志的原始行号精确高亮，并覆盖 ``evidence`` 的内容匹配；
    ``source_line_offset`` 为传入文本前已去掉的行数（如终端标题行），
    用于把行号对齐到前端日志弹窗中的行号。
    """
    if not (log_text or "").strip():
        return None

    highlight_line_numbers: Set[int] = set()
    for item in highlight_lines or []:
        try:
            line_number = int(item)
        except (TypeError, ValueError):
            continue
        if line_number > 0:
            highlight_line_numbers.add(line_number)

    evidence_keys = sorted(
        {_normalize(item) for item in (evidence or []) if _normalize(item) and len(_normalize(item)) >= 4},
        key=len,
        reverse=True,
    )

    cache_key = _log_image_cache_key(
        log_text,
        status,
        evidence_keys,
        highlight_line_numbers,
        source_line_offset,
        width,
        max_height,
        font_size,
        title,
    )
    cached = _log_image_cache_get(cache_key)
    if cached is not None:
        return BytesIO(cached)

    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    # 按行号高亮时必须使用完整日志行并保留原始行号；内容匹配仍沿用旧的
    # 提取逻辑，避免改变 AI 证据图片的展示内容。
    log_entries = (
        _source_entries(log_text, source_line_offset)
        if highlight_line_numbers
        else _extract_raw_terminal_entries(log_text)
    )
    if source_line_offset and not highlight_line_numbers:
        log_entries = [
            (index + source_line_offset if index is not None else None, line)
            for index, line in log_entries
        ]
    if not any(line.strip() for _, line in log_entries):
        return None

    status_text = (status or "").lower()
    theme_key = "pass" if "pass" in status_text else "fail" if "fail" in status_text else "other"
    theme = _EVIDENCE_THEMES[theme_key]


    padding = 10
    line_height = 15
    content_width = width - padding * 2
    font = _load_font(font_size)
    title_text = (title or "").strip()
    title_height = 22 if title_text else 0
    title_font = _load_font(font_size + 1) if title_text else None

    raw_lines: List[Tuple[Optional[int], str]] = [
        (line_number, line.rstrip().replace("\t", "    "))
        for line_number, line in log_entries
    ]
    while raw_lines and not raw_lines[0][1].strip():
        raw_lines.pop(0)
    while raw_lines and not raw_lines[-1][1].strip():
        raw_lines.pop()

    # 末尾的板端系统日志通常很长，图片里只保留与证据相关的关键行，
    # 否则预览会被 journalctl 噪声占满；完整内容仍在日志文件中。
    system_start = None
    for index, (_line_number, line) in enumerate(raw_lines):
        if "系统日志" in line and ("=====" in line or "-----" in line):
            system_start = index
            break
    if system_start is not None:
        main_lines = raw_lines[:system_start]
        system_lines = [
            (line_number, line)
            for line_number, line in raw_lines[system_start:]
            if _line_kind(line, evidence_keys, theme_key, line_number, highlight_line_numbers)
            == "evidence"
        ]
        raw_lines = list(main_lines)
        if system_lines:
            raw_lines.append((None, "… 系统日志关键行 …"))
            raw_lines.extend(system_lines)

    max_rows = max(4, (max_height - padding * 2 - title_height) // line_height)

    # 超长日志先按逻辑行挑选：命令上下文 + 证据行 + 末尾结论，
    # 避免把几万行日志全部排版（完整日志仍保留在日志文件中）。
    total_lines = len(raw_lines)
    if total_lines > 120:
        evidence_indices = [
            index for index, (line_number, line) in enumerate(raw_lines)
            if _line_kind(line, evidence_keys, theme_key, line_number, highlight_line_numbers)
            == "evidence"
        ]
        # AI 证据最多保留 16 行；手动选择的行全部保留，避免用户选中的行被裁掉
        if not highlight_line_numbers:
            evidence_indices = evidence_indices[:16]
        keep = set(range(min(3, total_lines))) | set(evidence_indices)
        keep |= set(range(max(0, total_lines - 80), total_lines))
        selected: List[Tuple[Optional[int], str]] = []
        last = -1
        for index in sorted(keep):
            if index > last + 1:
                selected.append((None, "… 已省略 %d 行 …" % (index - last - 1)))
            selected.append(raw_lines[index])
            last = index
        if last < total_lines - 1:
            selected.append((None, "… 已省略 %d 行 …" % (total_lines - last - 1)))
        raw_lines = selected

    rows: List[Tuple[str, Optional[str]]] = []
    for line_number, line in raw_lines:
        kind = _line_kind(line, evidence_keys, theme_key, line_number, highlight_line_numbers)
        for piece in _wrap_line(line, font, content_width):
            rows.append((piece, kind))

    if len(rows) > max_rows:
        # 行数超出单张图片容量时，优先保留开头、AI 证据行与末尾结论
        budget = max_rows - 2  # 预留两行省略提示
        head = set(range(min(2, len(rows))))
        evidence_rows = [i for i, row in enumerate(rows) if row[1] == "evidence"]
        remaining = max(0, budget - len(head))
        keep_evidence = set(evidence_rows[:remaining])
        tail_count = max(0, remaining - len(keep_evidence))
        tail = set(range(max(0, len(rows) - tail_count), len(rows)))
        keep = head | keep_evidence | tail
        compact: List[Tuple[str, Optional[str]]] = []
        last = -1
        for index in sorted(keep):
            if index > last + 1:
                compact.append(("… 已省略 %d 行 …" % (index - last - 1), "dim"))
            compact.append(rows[index])
            last = index
        rows = compact[:max_rows]

    height = max(
        padding * 2 + title_height + line_height,
        padding * 2 + title_height + len(rows) * line_height,
    )
    image = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(image)

    if title_text:
        draw.rectangle([0, 0, width, title_height], fill=(17, 24, 39))
        draw.line([0, title_height - 1, width, title_height - 1], fill=(45, 58, 78))
        draw.text((padding, 4), title_text, font=title_font, fill=_DIM)

    y = padding + title_height
    for text, kind in rows:
        if kind == "evidence":
            draw.rectangle([0, y, width, y + line_height], fill=theme["bg"])
            draw.rectangle([0, y, 3, y + line_height], fill=theme["bar"])
            color = theme["fg"]
        elif kind == "success":
            color = _SUCCESS_FG
        elif kind == "dim":
            color = _DIM
        else:
            color = _FG
        draw.text((padding, y), text or " ", font=font, fill=color)
        y += line_height

    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    png_bytes = buf.getvalue()
    _log_image_cache_put(cache_key, png_bytes)
    return BytesIO(png_bytes)
