"""多终端步骤解析单测：终端字样识别（任意位置/无冒号）、开放标签、旧写法兼容。"""
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


def test_terminal_mention_anywhere_in_step():
    # 只要步骤里出现「终端A」这样的字样就识别，不限开头、不要求冒号
    steps = CommandParser.parse("1. 在终端B执行命令：./tool --flag")
    assert steps[0].terminal == "终端B"
    assert steps[0].command == "./tool --flag"


def test_terminal_mention_without_colon():
    steps = CommandParser.parse("1. 终端B执行命令：./fault_simulation.sh -i 7")
    assert steps[0].terminal == "终端B"
    assert steps[0].command == "./fault_simulation.sh -i 7"


def test_terminal_annotation_after_command():
    steps = CommandParser.parse("1. 执行命令：./tool --flag（终端B）")
    assert steps[0].terminal == "终端B"
    assert steps[0].command == "./tool --flag"


def test_terminal_mention_with_trailing_prose_verb():
    steps = CommandParser.parse("1. 终端A运行 ./nvsipl_camera -c cfg")
    assert steps[0].terminal == "终端A"
    assert steps[0].command == "./nvsipl_camera -c cfg"


def test_multi_terminal_lines_in_one_step():
    steps = CommandParser.parse(
        "1. 终端A：./nvsipl_camera -c cfg\n"
        "终端B：./fault_simulation.sh -i 7"
    )
    assert [(s.terminal, s.command) for s in steps] == [
        ("终端A", "./nvsipl_camera -c cfg"),
        ("终端B", "./fault_simulation.sh -i 7"),
    ]


def test_terminal_mention_applies_to_wait_and_interactive():
    wait_steps = CommandParser.parse("1. 等待2秒（终端B）")
    assert wait_steps[0].kind == "wait"
    assert wait_steps[0].terminal == "终端B"
    input_steps = CommandParser.parse("1. 在终端B上输入 gc 0")
    assert input_steps[0].kind == "nvsipl_input"
    assert input_steps[0].terminal == "终端B"


def test_plain_word_after_terminal_not_treated_as_label():
    # 「终端上」「终端中」是普通词，不应识别成终端标签
    steps = CommandParser.parse("1. 在终端上确认日志打印")
    assert steps[0].terminal == DEFAULT_TERMINAL


def test_normalize_terminal_label():
    assert CommandParser.normalize_terminal_label("主终端") == "终端A"
    assert CommandParser.normalize_terminal_label("辅终端") == "终端B"
    assert CommandParser.normalize_terminal_label("a") == "终端A"
    assert CommandParser.normalize_terminal_label("终端 e") == "终端E"
    assert CommandParser.normalize_terminal_label("") == "终端A"


def test_numeric_input_parsed_as_interactive_input():
    # nvsipl 子命令提示后再输入的数字参数行（如 sh0 的地址/长度）
    for text in ("1. 输入 8000 256", "1. 输入8000 256", "1. 输入 0x8000 256"):
        steps = CommandParser.parse(text)
        assert steps[0].kind == "nvsipl_input", text
    assert CommandParser.parse("1. 输入 8000 256")[0].command == "8000 256"
    assert CommandParser.parse_nvsipl_interactive_inputs("输入 0x8000 256") == ["0x8000 256"]


def test_numeric_input_combined_with_subcommand_in_one_step():
    # 「输入sh0 … 输入8000 256」应拆出 sh0 与后续参数行，不能只留 sh0
    steps = CommandParser.parse(
        "1. 输入sh0 ，终端输出Please enter <address_hex> <length_dec>, "
        "e.g. 8000 256后，输入8000 256"
    )
    assert steps[0].kind == "nvsipl_input"
    assert steps[0].command == "sh0;8000 256"
    assert CommandParser.parse_nvsipl_interactive_inputs(
        "输入'ro'指令，输入 8000 256"
    ) == ["ro", "8000 256"]


def test_numeric_example_without_input_prefix_is_not_command():
    # 只作为提示示例出现的 8000 256（前面没有「输入」）不应当成交互输入
    assert CommandParser.parse_nvsipl_interactive_inputs(
        "终端输出Please enter <address_hex> <length_dec>, e.g. 8000 256"
    ) == []
    # 「输入命令：…」仍是 shell 命令，不走 nvsipl 交互输入
    assert CommandParser.parse_nvsipl_interactive_inputs("输入命令：echo 8000 256") == []


def test_comma_separated_numeric_input_parsed_as_interactive_input():
    # 参数行可以写成逗号分隔，整行作为一个输入下发（保留逗号）
    assert CommandParser.parse_nvsipl_interactive_inputs(
        "输入1500, 1080, 800, 600, 2, 4"
    ) == ["1500, 1080, 800, 600, 2, 4"]
    steps = CommandParser.parse("1. 输入1500, 1080, 800, 600, 2, 4")
    assert steps[0].kind == "nvsipl_input"
    assert steps[0].command == "1500, 1080, 800, 600, 2, 4"
    # 全角逗号 / 顿号写法同样识别
    assert CommandParser.parse_nvsipl_interactive_inputs(
        "输入1500，1080，800"
    ) == ["1500，1080，800"]
    assert CommandParser.parse_nvsipl_interactive_inputs(
        "输入1500、1080、800"
    ) == ["1500、1080、800"]


def test_bare_numeric_lines_after_input_are_parsed():
    # 同一步骤里后续行省略「输入」、单独成行写数字参数，逐行下发
    steps = CommandParser.parse(
        "4、输入1500, 1080, 800, 600, 2, 4\n"
        "      1000, 500, 2000, 1000, 2, 1"
    )
    assert steps[0].kind == "nvsipl_input"
    assert steps[0].command == (
        "1500, 1080, 800, 600, 2, 4;1000, 500, 2000, 1000, 2, 1"
    )
    # 子命令形式（执行 sr）后的参数行同样下发
    steps = CommandParser.parse("1. 执行 sr\n1000, 1000, 2, 4\n1000, 1000, 2, 4")
    assert steps[0].kind == "nvsipl_input"
    assert steps[0].command == "sr;1000, 1000, 2, 4;1000, 1000, 2, 4"


def test_bare_numeric_step_without_input_prefix():
    # 整步只有一行数字参数（无「输入」前缀）也识别为交互输入
    steps = CommandParser.parse("1、1000, 500, 2000, 1000, 2, 1")
    assert steps[0].kind == "nvsipl_input"
    assert steps[0].command == "1000, 500, 2000, 1000, 2, 1"
    # 直接调用时步骤编号不会被当成参数
    assert CommandParser.parse_nvsipl_interactive_inputs(
        "1、1000, 500, 2000, 1000, 2, 1"
    ) == ["1000, 500, 2000, 1000, 2, 1"]


def test_numeric_lines_with_text_are_not_misjudged():
    # 说明文字里夹带的数字参数不当作交互输入
    steps = CommandParser.parse("1、记录当前参数 1500, 1080, 800")
    assert steps[0].kind == "skip"
    # 「输入 0, dl 2」不会被数字参数行模式截断，仍解析出 dl 2
    assert CommandParser.parse_nvsipl_interactive_inputs("输入 0, dl 2") == ["dl 2"]
