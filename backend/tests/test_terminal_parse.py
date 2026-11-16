"""多终端步骤解析单测：「终端A：」前缀、开放标签、旧写法兼容。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.command_parser import CommandParser, DEFAULT_TERMINAL  # noqa: E402


def test_default_terminal_is_terminal_a():
    assert DEFAULT_TERMINAL == "终端A"
    steps = CommandParser.parse("1. 执行命令：echo hi")
    assert steps[0].terminal == "终端A"


def test_terminal_prefix_switches_terminal():
    steps = CommandParser.parse(
        "1. 终端A：./nvsipl_camera -c cfg\n"
        "2. 终端B：./fault_simulation.sh -i 7\n"
        "3. 终端C：echo done"
    )
    assert [s.terminal for s in steps] == ["终端A", "终端B", "终端C"]
    assert steps[1].command == "./fault_simulation.sh -i 7"
    assert steps[2].command == "echo done"


def test_terminal_prefix_variants():
    for text, expected in (
        ("1. 终端B：echo hi", "终端B"),
        ("1. [终端D] echo hi", "终端D"),
        ("1. A> echo hi", "终端A"),
    ):
        steps = CommandParser.parse(text)
        assert steps[0].terminal == expected, text
        assert steps[0].command == "echo hi", text


def test_legacy_other_terminal_maps_to_b():
    steps = CommandParser.parse("1. 另一个终端执行：./tool --flag")
    assert steps[0].terminal == "终端B"
    assert steps[0].command == "./tool --flag"


def test_plain_command_without_prefix_still_skipped():
    # 没有终端前缀的裸命令沿用既有行为（交给 AI 解析补全）
    steps = CommandParser.parse("1. ls /tmp")
    assert steps[0].kind == "skip"


def test_terminal_prefix_applies_to_interactive_input():
    steps = CommandParser.parse(
        "1. 终端B：./nvsipl_camera -c cfg\n"
        "2. 终端B：输入 gc 0\n"
        "3. 终端B：输入 q"
    )
    assert [s.kind for s in steps][1:] == ["nvsipl_input", "nvsipl_input"]
    assert all(s.terminal == "终端B" for s in steps)


def test_normalize_terminal_label():
    assert CommandParser.normalize_terminal_label("主终端") == "终端A"
    assert CommandParser.normalize_terminal_label("辅终端") == "终端B"
    assert CommandParser.normalize_terminal_label("a") == "终端A"
    assert CommandParser.normalize_terminal_label("终端 e") == "终端E"
    assert CommandParser.normalize_terminal_label("") == "终端A"
