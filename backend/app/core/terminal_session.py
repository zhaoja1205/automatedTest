"""多终端持久化 Shell 会话。

统一执行器不再区分「顺序执行 / 持久 Shell / 并行 PTY」三种模式：
每个终端（终端A、终端B……）对应一个长期存活的 SSH 交互式 shell，
用例的所有步骤都在这些会话中执行，环境变量与工作目录天然保留。

本模块只负责「一个终端 = 一个会话」的通用能力，不包含任何 nvsipl 语义：

- 后台泵任务持续收数据，调用方按需消费，避免输出归属错位
- 命令执行带 ``__RC<token>__`` 退出码标记，不依赖提示符猜测
- 命令超时先发 Ctrl-C，仍无响应则重建该终端
"""
import asyncio
import itertools
import re
import time
from typing import Awaitable, Callable, Optional

# 命令结束标记：``cmd; echo "__RC7__=$?"``
_MARKER_TEMPLATE = "__RC{token}__"


def _clean_echo(out: str, marker: str) -> str:
    """剔除 PTY 回显中的命令包装行与退出码标记行。

    PTY 会把 ``cmd; echo "__RC7__=$?"`` 原样回显，并额外打印 ``__RC7__=0``。
    这些内容对日志与 AI 判定都是噪声：包装行保留原命令（去掉 RC 部分）。
    """
    if not out:
        return out
    cleaned = []
    for line in out.split("\n"):
        stripped = line.strip()
        # 去掉纯标记行
        if re.fullmatch(re.escape(marker) + r"=-?\d+;?", stripped):
            continue
        # 回显行：把 RC 包装去掉，只留原命令
        if marker in line:
            line = line.split(f'; echo "{marker}')[0]
            line = re.sub(r'\s*;?\s*echo\s+"?\s*$', '', line)
        cleaned.append(line)
    return "\n".join(cleaned).strip("\n")


class PersistentShell:
    """一个终端 = 一个长期存活的交互式 shell（PTY channel）。"""

    def __init__(self, label: str, ssh,
                 on_log: Optional[Callable[[str], Awaitable[None]]] = None):
        self.label = label
        self._ssh = ssh
        self._on_log = on_log
        self._channel = None
        self._buf = ""            # 已收到的全部输出
        self._cursor = 0          # 已被调用方消费到的位置
        self._pump_task: Optional[asyncio.Task] = None
        self._closed = False
        self.eof = False
        self.cwd = ""
        self.busy = False         # 已启动但未结束的前台交互程序（如 nvsipl）
        self._pending_marker: Optional[str] = None
        self._counter = itertools.count(1)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    async def open(self, timeout: int = 300):
        loop = asyncio.get_event_loop()
        self._channel = await loop.run_in_executor(
            None, lambda: self._ssh.open_shell_channel(timeout=timeout)
        )
        self._closed = False
        self.eof = False
        self._buf = ""
        self._cursor = 0
        self._pump_task = asyncio.ensure_future(self._pump())
        # 用带标记的命令探测 shell 是否就绪（不依赖提示符形态）
        await self.run('echo "__READY__"', timeout=10)

    async def _pump(self):
        """后台持续读取 channel，数据只追加到缓冲区，永不阻塞调用方。"""
        loop = asyncio.get_event_loop()
        idle_since = time.monotonic()
        while not self._closed:
            if self._channel is None:
                break
            try:
                ready = await loop.run_in_executor(None, self._channel.recv_ready)
            except (OSError, EOFError, ValueError):
                self.eof = True
                break
            if ready:
                try:
                    data = await loop.run_in_executor(
                        None, lambda: self._channel.recv(65536))
                except (OSError, EOFError, ValueError):
                    self.eof = True
                    break
                if not data:
                    self.eof = True
                    break
                self._buf += data.decode("utf-8", errors="replace")
                idle_since = time.monotonic()
            else:
                # system ssh 回退通道：远端进程退出后 select 只会一直返回空，
                # 通过子进程状态兜底判定 EOF，避免等待方永久挂起。
                proc = getattr(self._channel, "_proc", None)
                if proc is not None and proc.poll() is not None:
                    self.eof = True
                    break
                await asyncio.sleep(0.1)

    async def close(self):
        self._closed = True
        task = self._pump_task
        self._pump_task = None
        if task is not None and not task.done():
            task.cancel()
        channel = self._channel
        self._channel = None
        if channel is None:
            return
        try:
            await asyncio.get_event_loop().run_in_executor(None, channel.close)
        except Exception:
            pass

    def close_now(self):
        """同步兜底关闭（用于事件循环被取消时）。"""
        self._closed = True
        task = self._pump_task
        self._pump_task = None
        if task is not None and not task.done():
            task.cancel()
        channel = self._channel
        self._channel = None
        if channel is None:
            return
        try:
            channel.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 收发原语
    # ------------------------------------------------------------------
    async def send(self, text: str):
        channel = self._channel
        if channel is None:
            raise OSError(f"[{self.label}] 终端未打开")
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: channel.send(text + "\n"))

    async def interrupt(self):
        channel = self._channel
        if channel is None:
            return
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: channel.send("\x03"))
        except Exception:
            pass

    async def read_until(self, pattern: Optional[str] = None,
                         timeout: float = 10.0,
                         quiet: Optional[float] = None) -> str:
        """读取输出，直到匹配 pattern / 超时 / 连续静默 quiet 秒。

        返回值即「本步骤产生的输出」，消费游标同步前移，避免输出错位归属。
        """
        start = self._cursor
        deadline = time.monotonic() + timeout
        last_len = len(self._buf)
        last_change = time.monotonic()
        while True:
            chunk = self._buf[start:]
            if pattern and re.search(pattern, chunk, re.IGNORECASE):
                break
            if self.eof:
                break
            now = time.monotonic()
            if now >= deadline:
                break
            if len(self._buf) != last_len:
                last_len = len(self._buf)
                last_change = now
            elif quiet is not None and (now - last_change) >= quiet:
                break
            await asyncio.sleep(0.05)
        self._cursor = len(self._buf)
        return self._buf[start:]

    async def drain(self, quiet: float = 0.6, max_wait: float = 5.0) -> str:
        """等输出静默后返回（替代散落的固定 sleep）。"""
        return await self.read_until(None, timeout=max_wait, quiet=quiet)

    # ------------------------------------------------------------------
    # 命令执行
    # ------------------------------------------------------------------
    async def run(self, cmd: str, timeout: float = 60.0,
                  quiet: Optional[float] = None) -> tuple:
        """执行一条命令并等待其结束，返回 ``(exit_code, output)``。

        output 里已经剔除退出码标记与命令回显，可直接写入日志/判定输入。
        """
        if self.eof or self._channel is None:
            raise OSError(f"[{self.label}] 终端已断开")
        token = next(self._counter)
        marker = _MARKER_TEMPLATE.format(token=token)
        await self.send(f'{cmd}; echo "{marker}=$?"')
        out = await self.read_until(marker + r"=-?\d+", timeout=timeout, quiet=quiet)
        match = re.search(marker + r"=(-?\d+)", out)
        return (int(match.group(1)) if match else -1), _clean_echo(out, marker)

    async def launch(self, cmd: str, timeout: float = 15.0,
                     stop_pattern: Optional[str] = None) -> str:
        """启动一个前台交互程序（如 nvsipl_camera），不等待其结束。

        退出码通过收尾时 ``wait_exit()`` 读取：命令行末尾已附加 RC 标记，
        交互程序退出后 shell 会打印该标记。
        """
        if self.eof or self._channel is None:
            raise OSError(f"[{self.label}] 终端已断开")
        token = next(self._counter)
        marker = _MARKER_TEMPLATE.format(token=token)
        self._pending_marker = marker
        self.busy = True
        await self.send(f'{cmd}; echo "{marker}=$?"')
        out = await self.read_until(stop_pattern, timeout=timeout)
        # 启动阶段只清理回显中的 RC 包装，退出码标记留给 wait_exit 消费
        return _clean_echo(out, marker) if out else out

    async def wait_exit(self, timeout: float = 60.0,
                        stop_pattern: Optional[str] = None) -> tuple:
        """等待 ``launch()`` 启动的交互程序退出，返回 ``(exit_code, output)``。"""
        marker = self._pending_marker
        if marker is None:
            out = await self.read_until(stop_pattern or r"Deinit|quit|exit",
                                        timeout=timeout)
            self.busy = False
            return 0, out
        pattern = marker + r"=-?\d+"
        if stop_pattern:
            pattern = f"{pattern}|{stop_pattern}"
        out = await self.read_until(pattern, timeout=timeout)
        match = re.search(marker + r"=(-?\d+)", out)
        exit_code = int(match.group(1)) if match else -1
        self._pending_marker = None
        self.busy = False
        return exit_code, _clean_echo(out, marker)

    async def set_cwd(self, path: str, timeout: float = 15.0) -> tuple:
        """切换该终端的工作目录（持久会话内生效）。"""
        exit_code, out = await self.run(f"cd {path}", timeout=timeout)
        if exit_code == 0:
            self.cwd = path
        return exit_code, out


class TerminalPool:
    """按标签懒创建 / 复用终端会话，用例结束时统一关闭。"""

    def __init__(self, ssh, *, work_dir: str = "", driver_export: str = "",
                 setup_commands: Optional[list] = None,
                 on_log: Optional[Callable[[str], Awaitable[None]]] = None):
        self._ssh = ssh
        self._work_dir = work_dir
        self._driver_export = driver_export
        self._setup_commands = list(setup_commands or [])
        self._on_log = on_log
        self._shells: dict = {}

    def labels(self) -> list:
        return list(self._shells.keys())

    def get_existing(self, label: str) -> Optional[PersistentShell]:
        return self._shells.get(label)

    async def get(self, label: str) -> PersistentShell:
        """取得终端会话；首次访问或已断开时自动创建。"""
        shell = self._shells.get(label)
        if shell is not None and not shell.eof and not shell._closed:
            return shell
        if shell is not None:
            await self._log(f"[{label}] 终端已断开，重新建立会话")
            await shell.close()
        shell = PersistentShell(label, self._ssh, on_log=self._on_log)
        await shell.open()
        await self._log(f"[{label}] 持久化终端已就绪")
        if self._driver_export:
            exit_code, _ = await shell.run(self._driver_export, timeout=15)
            if exit_code == 0:
                await self._log(f"[{label}] 已设置驱动库路径: {self._driver_export}")
        if self._work_dir:
            exit_code, _ = await shell.set_cwd(self._work_dir)
            if exit_code != 0:
                await self._log(f"[{label}] 切换工作目录失败: {self._work_dir}", "warning")
        for cmd in self._setup_commands:
            if cmd:
                await shell.run(cmd, timeout=30)
        self._shells[label] = shell
        return shell

    async def close_all(self):
        for shell in list(self._shells.values()):
            await shell.close()
        self._shells.clear()

    def close_now(self):
        for shell in list(self._shells.values()):
            shell.close_now()
        self._shells.clear()

    async def _log(self, message: str, level: str = "info"):
        if self._on_log is None:
            return
        try:
            await self._on_log(message, level)
        except TypeError:
            await self._on_log(message)
        except Exception:
            pass
