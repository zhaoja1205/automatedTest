"""nvsipl_input 步骤内「等待输出 / 超时」配置的解析测试。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.command_parser import CommandParser  # noqa: E402


def test_expect_output_with_optional_timeout():
    steps = CommandParser.parse("1. 输入 gc 0，等待输出：Frame rate，超时20秒")
    assert len(steps) == 1
    step = steps[0]
    assert step.kind == "nvsipl_input"
    assert step.command == "gc 0"
    assert step.expect_pattern == "Frame rate"
    assert step.expect_is_regex is False
    assert step.expect_timeout == 20.0


def test_expect_output_without_timeout_uses_table_timeout():
    steps = CommandParser.parse("1. 输入 al，等待输出：Vertical")
    step = steps[0]
    assert step.expect_pattern == "Vertical"
    assert step.expect_timeout is None


def test_expect_output_regex_with_timeout_unit():
    steps = CommandParser.parse(
        "1. 输入 gc 0，等待输出:/Frame rate[^:]*:\\s*[\\d.]+/，超时1.5秒"
    )
    step = steps[0]
    assert step.expect_pattern == r"Frame rate[^:]*:\s*[\d.]+"
    assert step.expect_is_regex is True
    assert step.expect_timeout == 1.5


def test_expect_timeout_supports_english_and_fractional_units():
    steps = CommandParser.parse("1. 输入 dl 0，等待输出：Link，超时500ms")
    step = steps[0]
    assert step.expect_pattern == "Link"
    assert step.expect_timeout == 0.5

    steps = CommandParser.parse("1. 输入 gc 0，等待输出：Frame rate，超时 2s")
    assert steps[0].expect_timeout == 2.0


def test_step_without_expect_config_keeps_defaults():
    steps = CommandParser.parse("1. 输入 gc 0")
    step = steps[0]
    assert step.kind == "nvsipl_input"
    assert step.expect_pattern == ""
    assert step.expect_timeout is None


def test_multiple_inputs_keep_expect_on_step():
    steps = CommandParser.parse("1. 执行dl 0, dl 2，等待输出：Link，超时8秒")
    step = steps[0]
    assert step.command == "dl 0;dl 2"
    assert step.expect_pattern == "Link"
    assert step.expect_timeout == 8.0
