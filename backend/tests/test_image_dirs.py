"""nvsipl_camera -f 出图目录解析测试。

背景：``-f`` 是「文件名前缀」，相机实际写出
``<前缀>_cam_<sensor>_out_<n>.yuv``。用例里写 ``-f ./picture/1`` 时，
产物是 ``/storage/yxy/picture/1_cam_0_out_1.yuv``；此前文件检查把
``-f`` 整个当成目录，去搜 ``/storage/yxy/picture/1``（并不存在），
导致「未找到 .yuv 文件」。这里固定目录解析规则。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.command_parser import CommandParser  # noqa: E402
from app.core.executor_adapter import ExecutorAdapter  # noqa: E402

_CAMERA = "./nvsipl_camera -c MIXGROUP_PREDEV_30FPS_MAX96724_CPHY_x4 "
_WORK_DIR = "/storage/yxy"


def _dirs(step_text: str, include_work_dir: bool = False) -> list:
    steps = CommandParser.parse(step_text)
    return ExecutorAdapter._collect_image_dirs(
        steps, _WORK_DIR, include_work_dir=include_work_dir)


def test_prefix_without_slash_uses_parent_dir():
    # -f ./picture/1 是前缀，产物在 picture/ 下（1_cam_0_out_1.yuv）
    assert _dirs(
        "1、输入命令：" + _CAMERA
        + "-m \"0x0001 0 0 0\" -f ./picture/1 --skipFrames 10 --writeFrames 1 -Z"
    ) == ["/storage/yxy/picture"]


def test_dir_with_trailing_slash_stays_itself():
    assert _dirs(
        "1、输入命令：" + _CAMERA
        + "-m \"0x0001 0 0 0\" -f ./picture/ --skipFrames 10 --writeFrames 1 -Z"
    ) == ["/storage/yxy/picture"]


def test_absolute_prefix_uses_parent_dir():
    assert _dirs(
        "1、执行命令：" + _CAMERA
        + "-m \"0x0001\" -f /storage/zja/default --writeFrames 1"
    ) == ["/storage/zja"]


def test_bare_prefix_falls_back_to_work_dir():
    assert _dirs(
        "1、输入命令：" + _CAMERA + "-m \"0x0001\" -f shot1 --writeFrames 1"
    ) == [_WORK_DIR]


def test_no_f_uses_work_dir():
    assert _dirs(
        "1、输入命令：" + _CAMERA + "-m \"0x0001\" -r 5"
    ) == [_WORK_DIR]


def test_cd_changes_base_dir_and_dedupes():
    assert _dirs(
        "1、进入目录 /storage/yxy/picture\n"
        "2、输入命令：" + _CAMERA
        + "-m \"0x0001\" -f ./1 --writeFrames 1\n"
        "3、输入命令：" + _CAMERA
        + "-m \"0x0001\" -f ./2 --writeFrames 1"
    ) == ["/storage/yxy/picture"]
