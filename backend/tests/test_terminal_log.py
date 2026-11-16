"""按终端日志格式：解析 / 拼接 / 读取。"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.terminal_log import (  # noqa: E402
    format_terminal_log,
    parse_terminal_log,
    read_terminal_logs,
)


def test_parse_ignores_long_equal_separators():
    """日志中的 ``================`` 分隔线不能当作终端标题。"""
    text = (
        "===== 终端A =====\n"
        "line1\n"
        "========================================\n"
        "line2\n"
    )
    sections = parse_terminal_log(text)
    assert sections == [("终端A", "line1\n========================================\nline2")]


def test_parse_ignores_system_section_titles():
    """系统分区标题（完整执行日志 / 板端系统日志）不是终端。"""
    text = (
        "===== 完整执行日志 =====\ncmd\n"
        "===== 板端系统日志 (journalctl) =====\nsys\n"
    )
    assert parse_terminal_log(text) == []


def test_format_roundtrip():
    sections = [("终端A", "a1\na2"), ("终端B", "b1")]
    text = format_terminal_log(sections)
    assert text == "===== 终端A =====\na1\na2\n\n===== 终端B =====\nb1"
    assert parse_terminal_log(text) == sections


def test_read_terminal_logs_prefers_manifest(tmp_path):
    log_file = tmp_path / "FT_001.log"
    log_file.write_text("aggregate", encoding="utf-8")
    base = os.path.splitext(str(log_file))[0]
    a = tmp_path / "a.term.log"
    b = tmp_path / "b.term.log"
    a.write_text("===== 终端A =====\na\n", encoding="utf-8")
    b.write_text("===== 终端B =====\nb\n", encoding="utf-8")
    manifest = f"{base}.terminals.json"
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({"terminals": [
            {"label": "终端A", "file": str(a)},
            {"label": "终端B", "file": str(b)},
        ]}, f, ensure_ascii=False)

    assert read_terminal_logs(str(log_file)) == [
        ("终端A", "===== 终端A =====\na\n"),
        ("终端B", "===== 终端B =====\nb\n"),
    ]
