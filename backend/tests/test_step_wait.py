"""测试步骤等待解析单测：「等待N秒」等等待说明的识别与挂载。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.command_parser import CommandParser  # noqa: E402


def test_extract_wait_seconds_supports_chinese_and_english_units():
    assert CommandParser.extract_wait_seconds("等待2秒") == 2.0
    assert CommandParser.extract_wait_seconds("等待 3 秒钟") == 3.0
    assert CommandParser.extract_wait_seconds("延时1.5s") == 1.5
    assert CommandParser.extract_wait_seconds("wait 2s") == 2.0
    assert CommandParser.extract_wait_seconds("等待1分钟") == 60.0
    assert CommandParser.extract_wait_seconds("等待５秒") == 5.0  # 全角数字
    assert CommandParser.extract_wait_seconds("等待2秒\n等待3秒") == 5.0
    assert CommandParser.extract_wait_seconds("等待fps稳定") == 0.0
    assert CommandParser.extract_wait_seconds("") == 0.0


def test_wait_only_step_becomes_wait_kind():
    steps = CommandParser.parse("1. 等待3秒")
    assert len(steps) == 1
    assert steps[0].kind == "wait"
    assert steps[0].wait_seconds == 3.0


def test_command_step_keeps_wait_and_strips_wait_text_from_command():
    steps = CommandParser.parse("1. 执行命令：./nvsipl_camera -c cfg -m 0 等待2秒")
    assert len(steps) == 1
    assert steps[0].kind == "command"
    assert steps[0].command == "./nvsipl_camera -c cfg -m 0"
    assert steps[0].wait_seconds == 2.0


def test_skip_step_with_wait_text_still_gets_wait():
    steps = CommandParser.parse("1. 等待2秒后查看输出")
    assert len(steps) == 1
    assert steps[0].kind != "wait"
    assert steps[0].wait_seconds == 2.0


def test_wait_attached_to_last_step_of_multi_command_step():
    steps = CommandParser.parse(
        "1. 输入如下命令注入故障：\n"
        "sudo ./fault_simulation.sh -i 1 等待2秒\n"
        "sudo ./fault_simulation.sh -i 2\n"
        "2. 等待3秒"
    )
    assert [s.kind for s in steps] == ["command", "command", "wait"]
    assert [s.wait_seconds for s in steps] == [0.0, 2.0, 3.0]


def test_explicit_sleep_command_does_not_add_duplicate_wait():
    steps = CommandParser.parse("1. 执行命令：sleep 2 等待2秒")
    assert steps[0].kind == "command"
    assert steps[0].wait_seconds == 0.0


def test_ai_parsed_step_inherits_wait_seconds():
    text = "1. 观察输出 等待2秒"
    steps = CommandParser.parse(text)
    assert steps[0].kind == "skip"
    assert steps[0].wait_seconds == 2.0

    ai_steps = {"TC1": [{
        "step_num": steps[0].step_num,
        "kind": "command",
        "command": "ls -l",
        "confidence": 0.9,
        "description": "列目录",
    }]}
    replaced = CommandParser.apply_ai_parsed_steps(steps, ai_steps, "TC1")
    assert replaced[0].kind == "command"
    assert replaced[0].command == "ls -l"
    assert replaced[0].wait_seconds == 2.0
