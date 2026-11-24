"""nvsipl_multicast 阻塞型前台程序识别测试。

背景：nvsipl_multicast 与 nvsipl_camera 一样，起流后一直运行，
需要输入 q 才退出。此前只把 nvsipl_camera 当作阻塞型程序，
``./nvsipl_multicast ...`` 被当成普通同步命令执行，执行器一直等它
返回（等满命令超时），表现为用例卡在第一条起流步骤。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.command_parser import CommandParser  # noqa: E402
from app.core.executor_adapter import ExecutorAdapter  # noqa: E402

_MULTICAST_CMD = (
    "./nvsipl_multicast -t MIXGROUP_PANGU_MIXGROUP_SECURITYOFF "
    "-k 3 -N /storage/test/nito/ -p dst"
)


def test_multicast_is_nvsipl_tool():
    assert CommandParser.is_nvsipl_tool_command(_MULTICAST_CMD) is True
    assert CommandParser.is_nvsipl_tool_command("./nvsipl_camera -c cfg") is True
    assert CommandParser.is_nvsipl_tool_command("nvsipl_multicast_tool") is False
    assert CommandParser.is_nvsipl_tool_command("") is False


def test_multicast_is_blocking_but_camera_r_is_not():
    # 无 -r：阻塞型
    assert CommandParser.is_blocking_nvsipl(_MULTICAST_CMD) is True
    assert CommandParser.is_blocking_nvsipl("./nvsipl_camera -c cfg -R -1") is True
    # 带 -r N：自动退出
    assert CommandParser.is_blocking_nvsipl("./nvsipl_camera -c cfg -r 100") is False
    # 非 nvsipl 命令
    assert CommandParser.is_blocking_nvsipl("tail -f /var/log") is False


def test_multicast_is_not_camera_command():
    # camera 专属处理（-f 出图、拍照命名）不应套到 multicast 上
    assert CommandParser.is_nvsipl_camera_command(_MULTICAST_CMD) is False


def test_user_case_steps_are_parsed_as_expected():
    text = (
        "1、输入指令：./nvsipl_multicast -t MIXGROUP_PANGU_MIXGROUP_SECURITYOFF "
        "-k 3 -N /storage/test/nito/ -p dst\n"
        "2、输入gc3\n"
        "3、输入 ro 获取到roi信息输入，\n"
        "4、输入 hs 查看当前亮度脂肪图\n"
        "5、输入 q"
    )
    steps = CommandParser.parse(text)
    assert [s.kind for s in steps] == [
        "command", "nvsipl_input", "nvsipl_input", "nvsipl_input", "nvsipl_input",
    ]
    assert steps[0].command == _MULTICAST_CMD
    assert CommandParser.is_blocking_nvsipl(steps[0].command) is True
    # 菜单写法是 "gc <sensor ID>"，用例里的 "gc3" 补空格后下发
    assert [s.command for s in steps[1:]] == ["gc 3", "ro", "hs", "q"]


def test_subcmd_without_space_gets_id_separator():
    assert CommandParser.parse_nvsipl_interactive_inputs("输入gc3") == ["gc 3"]
    assert CommandParser.parse_nvsipl_interactive_inputs("输入el11") == ["el 11"]
    # 名称本身带数字的子命令不拆分
    assert CommandParser.parse_nvsipl_interactive_inputs("输入sh0") == ["sh0"]
    # 已经带空格的保持不变
    assert CommandParser.parse_nvsipl_interactive_inputs("输入 gc 3") == ["gc 3"]


def test_input_key_normalizes_command_suffix():
    assert ExecutorAdapter._nvsipl_input_key("gc3") == "gc"
    assert ExecutorAdapter._nvsipl_input_key("gc 10") == "gc"
    assert ExecutorAdapter._nvsipl_input_key("ro") == "ro"
    assert ExecutorAdapter._nvsipl_input_key("hs") == "hs"
    assert ExecutorAdapter._nvsipl_input_key("8000 256") == "8000"
