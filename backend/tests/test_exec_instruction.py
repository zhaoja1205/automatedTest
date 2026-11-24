"""「执行指令」引导语解析测试。

背景：步骤里常用「执行指令：ls /tmp」/「执行指令 reboot」标注要执行的命令，
其中冒号可能省略。此前只识别「执行命令：」「指令：」等写法，无冒号的
「执行指令 xxx」会被当成未识别步骤跳过。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.command_parser import CommandParser  # noqa: E402


def test_exec_instruction_with_or_without_colon():
    for text, expected in (
        ("1、执行指令：ls /tmp", "ls /tmp"),
        ("1、执行指令 ls /tmp", "ls /tmp"),
        ("1、执行指令：./nvsipl_multicast -t X -k 3", "./nvsipl_multicast -t X -k 3"),
        ("1、执行指令 ./nvsipl_multicast -t X -k 3", "./nvsipl_multicast -t X -k 3"),
    ):
        steps = CommandParser.parse(text)
        assert len(steps) == 1, text
        assert steps[0].kind == "command", text
        assert steps[0].command == expected, text


def test_exec_instruction_accepts_commands_outside_keyword_list():
    # 显式引导：reboot / pwd 不在命令关键字白名单里也按命令下发
    steps = CommandParser.parse("1、执行指令 reboot")
    assert steps[0].kind == "command"
    assert steps[0].command == "reboot"


def test_exec_instruction_respects_terminal_label():
    steps = CommandParser.parse("1、终端B执行指令 ls /tmp")
    assert steps[0].kind == "command"
    assert steps[0].command == "ls /tmp"
    assert steps[0].terminal == "终端B"


def test_exec_instruction_does_not_capture_prose():
    # 没有冒号/空白的「执行指令后…」「执行指令，…」是说明文字，不能当命令
    for text in ("1、执行指令后确认画面正常", "1、执行指令，确认画面正常"):
        steps = CommandParser.parse(text)
        assert steps[0].kind == "skip", text


def test_exec_instruction_nvsipl_subcommand_stays_interactive_input():
    # 交互子命令仍优先识别为 nvsipl_input，不当作 shell 命令
    steps = CommandParser.parse("1、执行指令 gc 3")
    assert steps[0].kind == "nvsipl_input"
    assert steps[0].command == "gc 3"


def test_exec_instruction_quoted_nvsipl_subcommand():
    """「执行指令‘th’查看内参」：引号/弯引号/冒号都可选，识别为交互输入 th。"""
    for text in (
        "1、执行指令‘th’查看内参",
        "1、执行指令’th’查看内参",
        "1、执行指令\"th\"查看内参",
        "1、执行指令'th'查看内参",
        "1、执行指令 th 查看内参",
        "1、执行指令：'th'查看内参",
        "1、执行‘th’查看内参",
    ):
        steps = CommandParser.parse(text)
        assert len(steps) == 1, text
        assert steps[0].kind == "nvsipl_input", text
        assert steps[0].command == "th", text


def test_exec_instruction_subcommand_without_id_still_shell_command():
    # 引导语后不是已知子命令时仍按 shell 命令解析
    steps = CommandParser.parse("1、执行指令 ls /tmp")
    assert steps[0].kind == "command"
    assert steps[0].command == "ls /tmp"


def test_multi_subcommand_list_not_truncated_by_exec_occasion():
    # 「执行dl 0, dl 2, dl 3」仍要完整提取，不能只留第一条
    steps = CommandParser.parse("1、执行dl 0, dl 2, dl 3")
    assert steps[0].kind == "nvsipl_input"
    assert steps[0].command == "dl 0;dl 2;dl 3"
