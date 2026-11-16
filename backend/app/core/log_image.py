"""把执行日志渲染成终端风格的 PNG 图片（用于结果 Excel「备注」列）。

视觉与前端用例日志弹窗保持一致：
- 深色背景、浅色等宽文本；
- AI 证据行按判定状态高亮（Pass 绿色、Fail 红色、其它黄色）；
- 未命中证据时，对明显的 ERROR / SUCCESS 行做红色 / 绿色标注。
"""
from __future__ import annotations

import glob
import json
import os
import re
from io import BytesIO
from typing import Iterable, List, Optional, Tuple

# 深色终端配色
_BG = (11, 16, 32)
_FG = (214, 222, 235)
_DIM = (139, 148, 158)
_ERROR_FG = (255, 107, 107)
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

# 明显的失败 / 成功关键字（不影响 AI 证据行的主题色）
_ERROR_RE = re.compile(r"\b(ERROR|ERR|FATAL|PANIC|FAIL|FAILED|FAILURE|ASSERT)\b", re.I)
_SUCCESS_RE = re.compile(r"\b(PASS|PASSED|OK|SUCCESS|SUCCEEDED)\b", re.I)
_AUTH_FAILED_ZERO_RE = re.compile(r"failed\s+to\s+authenticate\s*:\s*0", re.I)


_RAW_MARKER = "===== 完整执行日志 ====="


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
    if not log_text:
        return ""
    index = log_text.find(_RAW_MARKER)
    if index < 0:
        return log_text

    head_lines = log_text[:index].replace("\r\n", "\n").split("\n")
    commands = [line for line in head_lines if line.startswith("$ ")]

    body = log_text[index + len(_RAW_MARKER):].lstrip("\r\n")
    lines = body.replace("\r\n", "\n").split("\n")
    cut = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[文件检查]") or stripped.startswith("===== 板端"):
            cut = i
            break
    transcript = "\n".join(lines[:cut]).strip("\n")

    if commands:
        return "\n".join(commands + ["", transcript]).strip("\n")
    return transcript


def read_terminal_logs(log_file: str) -> List[Tuple[str, str]]:
    """读取某条用例按终端分别落盘的日志，返回 ``[(终端标签, 内容)]``。

    优先读取执行器写出的 ``<基名>.terminals.json`` 清单；
    没有清单时按 ``<基名>.<终端>.term.log`` 命名约定回退扫描。
    文件不存在或为空时返回空列表，由调用方回退到聚合日志。
    """
    log_file = (log_file or "").strip()
    if not log_file:
        return []

    base = os.path.splitext(os.path.abspath(log_file))[0]
    terminals: List[Tuple[str, str]] = []

    manifest_path = f"{base}.terminals.json"
    if os.path.isfile(manifest_path):
        manifest = None
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = None
        if isinstance(manifest, dict):
            for item in manifest.get("terminals", []) or []:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or "").strip()
                file_path = str(item.get("file") or "").strip()
                if not label or not file_path or not os.path.isfile(file_path):
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue
                if content.strip():
                    terminals.append((label, content))

    if terminals:
        return terminals

    # 兼容没有清单的日志：按 ``<基名>.<终端>.term.log`` 扫描
    base_name = os.path.basename(base)
    for file_path in sorted(glob.glob(f"{base}.*.term.log")):
        name = os.path.basename(file_path)
        label = name[len(base_name) + 1:-len(".term.log")]
        if not label:
            continue
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            continue
        if content.strip():
            terminals.append((label, content))
    return terminals


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


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


def _line_kind(line: str, evidence_keys: List[str], theme_key: str) -> Optional[str]:
    """返回 ``evidence`` / ``error`` / ``success`` / ``dim`` / ``None``。"""
    if line.strip().startswith("…"):
        return "dim"
    normalized = _normalize(line)
    if normalized and len(normalized) >= 4 and evidence_keys:
        for item in evidence_keys:
            if item in normalized or normalized in item:
                return "evidence"
    if _AUTH_FAILED_ZERO_RE.search(line):
        return None
    if _ERROR_RE.search(line):
        return "error"
    if _SUCCESS_RE.search(line) or "失败" in line:
        # 中文“失败”归为错误，避免被当成成功
        return "error" if "失败" in line else "success"
    if any(word in line for word in ("成功", "正常", "通过")):
        return "success"
    return None


def render_log_image(
    log_text: str,
    *,
    status: str = "",
    evidence: Optional[Iterable[str]] = None,
    width: int = 400,
    max_height: int = 520,
    font_size: int = 10,
    title: str = "",
) -> Optional[BytesIO]:
    """渲染日志图片；无内容或 Pillow 不可用时返回 None。

    ``title`` 非空时在图片顶部绘制一条标题栏，用于标注终端名
    （按终端渲染时每个终端一张图片）。
    """
    if not (log_text or "").strip():
        return None
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return None

    log_text = extract_raw_terminal_log(log_text)
    if not log_text.strip():
        return None

    status_text = (status or "").lower()
    theme_key = "pass" if "pass" in status_text else "fail" if "fail" in status_text else "other"
    theme = _EVIDENCE_THEMES[theme_key]

    evidence_keys = sorted(
        {_normalize(item) for item in (evidence or []) if _normalize(item) and len(_normalize(item)) >= 4},
        key=len,
        reverse=True,
    )

    padding = 10
    line_height = 15
    content_width = width - padding * 2
    font = _load_font(font_size)
    title_text = (title or "").strip()
    title_height = 22 if title_text else 0
    title_font = _load_font(font_size + 1) if title_text else None

    raw_lines = [line.rstrip().replace("\t", "    ") for line in log_text.replace("\r\n", "\n").split("\n")]
    while raw_lines and not raw_lines[0].strip():
        raw_lines.pop(0)
    while raw_lines and not raw_lines[-1].strip():
        raw_lines.pop()

    # 末尾的板端系统日志通常很长，图片里只保留与 AI 证据相关的关键行，
    # 否则预览会被 journalctl 噪声占满；完整内容仍在日志文件中。
    system_start = None
    for index, line in enumerate(raw_lines):
        if "系统日志" in line and ("=====" in line or "-----" in line):
            system_start = index
            break
    if system_start is not None:
        main_lines = raw_lines[:system_start]
        system_lines = [
            line for line in raw_lines[system_start:]
            if _line_kind(line, evidence_keys, theme_key) == "evidence"
        ]
        raw_lines = list(main_lines)
        if system_lines:
            raw_lines.append("… 系统日志关键行 …")
            raw_lines.extend(system_lines)

    max_rows = max(4, (max_height - padding * 2 - title_height) // line_height)

    # 超长日志先按逻辑行挑选：命令上下文 + AI 证据行 + 末尾结论，
    # 避免把几万行日志全部排版（完整日志仍保留在日志文件中）。
    total_lines = len(raw_lines)
    if total_lines > 120:
        evidence_indices = [
            index for index, line in enumerate(raw_lines)
            if _line_kind(line, evidence_keys, theme_key) == "evidence"
        ][:16]
        keep = set(range(min(3, total_lines))) | set(evidence_indices)
        keep |= set(range(max(0, total_lines - 80), total_lines))
        selected: List[str] = []
        last = -1
        for index in sorted(keep):
            if index > last + 1:
                selected.append("… 已省略 %d 行 …" % (index - last - 1))
            selected.append(raw_lines[index])
            last = index
        if last < total_lines - 1:
            selected.append("… 已省略 %d 行 …" % (total_lines - last - 1))
        raw_lines = selected

    rows: List[Tuple[str, Optional[str]]] = []
    for line in raw_lines:
        kind = _line_kind(line, evidence_keys, theme_key)
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
        elif kind == "error":
            color = _ERROR_FG
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
    buf.seek(0)
    return buf
