"""前台程序占用终端时的命令等待逻辑测试。

背景：``export CAM_ROTATE_CFG_PATH=...`` 之类普通命令步骤若在
nvsipl_camera 仍运行时下发，会被前台程序当成交互输入吞掉，shell 不会
执行命令，``__RCn__`` 标记也不会回显，执行器只能等满 60 秒超时。
"""
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.executor_adapter import ExecutorAdapter  # noqa: E402
from app.core.terminal_session import PersistentShell  # noqa: E402


class _Step:
    def __init__(self, wait_seconds: float = 0.0):
        self.wait_seconds = wait_seconds


def test_foreground_exit_timeout_defaults_and_annotation():
    assert ExecutorAdapter._foreground_exit_timeout(_Step()) == 15.0
    assert ExecutorAdapter._foreground_exit_timeout(_Step(30.0)) == 45.0


def test_wait_foreground_exit_reclaims_marker():
    shell = PersistentShell("终端A", ssh=None)
    shell.busy = True
    shell._pending_marker = "__RC9__"

    async def fake_read_until(pattern=None, timeout=10.0, quiet=None):
        return "SUCCESS\n__RC9__=0\n"

    shell.read_until = fake_read_until  # type: ignore[assignment]
    exited, exit_code, output = asyncio.run(
        shell.wait_foreground_exit(timeout=1.0))

    assert exited is True
    assert exit_code == 0
    assert shell.busy is False
    assert shell.pending_marker is None
    # 标记行从回显里剔除，其余输出保留
    assert "__RC9__" not in output
    assert "SUCCESS" in output


def test_wait_foreground_exit_keeps_running_state_on_timeout():
    shell = PersistentShell("终端A", ssh=None)
    shell.busy = True
    shell._pending_marker = "__RC9__"

    async def fake_read_until(pattern=None, timeout=10.0, quiet=None):
        return "Enter 'q' to quit the application\n"

    shell.read_until = fake_read_until  # type: ignore[assignment]
    exited, exit_code, _ = asyncio.run(
        shell.wait_foreground_exit(timeout=1.0))

    assert exited is False
    assert exit_code == -1
    # 仍在运行：保留 busy / 挂起标记，后续交互输入仍能识别
    assert shell.busy is True
    assert shell.pending_marker == "__RC9__"
