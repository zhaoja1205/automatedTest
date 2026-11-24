"""人工操作步骤解析单测：拔插/手动切换等关键字自动转为人工确认（confirm）。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.command_parser import CommandParser  # noqa: E402


def test_manual_keywords_become_confirm_steps():
    steps = CommandParser.parse(
        "1. 人为手动拔插 camera 线缆\n"
        "2. 手动切换 Camera 通道\n"
        "3. 物理操作：断开电源\n"
        "4. 插拔一次线缆"
    )
    assert [s.kind for s in steps] == ["confirm", "confirm", "confirm", "confirm"]
    # 原文保留在 description，作为人工确认弹窗的说明
    assert steps[0].description == "人为手动拔插 camera 线缆"


def test_manual_keyword_step_keeps_terminal_label():
    steps = CommandParser.parse("1. 终端B：人为手动拔插 camera 线缆")
    assert steps[0].kind == "confirm"
    assert steps[0].terminal == "终端B"


def test_manual_keyword_step_keeps_wait_seconds():
    steps = CommandParser.parse("1. 人为手动拔插 camera 线缆，等待5秒")
    assert steps[0].kind == "confirm"
    assert steps[0].wait_seconds == 5.0


def test_explicit_manual_confirm_prefix_still_works():
    steps = CommandParser.parse("1. MANUAL_CONFIRM 检查屏幕是否有显示异常")
    assert steps[0].kind == "confirm"
    assert steps[0].description == "检查屏幕是否有显示异常"


def test_manual_keyword_takes_priority_over_command_extraction():
    # 人工动作与命令写在同一步骤时，整步按人工确认处理，命令不会自动下发
    steps = CommandParser.parse("1. 人为手动拔插线缆后输入 gc 0")
    assert steps[0].kind == "confirm"
    assert steps[0].command == ""
