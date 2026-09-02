"""
SSH 管理器。

默认优先使用 Paramiko；若目标设备仅提供 Paramiko 3.4.0 不支持的
AES-GCM cipher，则自动回退到系统 OpenSSH。

v3.1.1: 新增 SystemSSHChannel，让 system SSH 回退模式也支持 PTY
交互通道（open_interactive_channel / open_shell_channel），覆盖
Linux 板端 cipher 不兼容场景。
"""
import os
import select
import shlex
import subprocess
import tempfile

import paramiko
from app.core.test_case import SSHConfig


class SystemSSHChannel:
    """基于 system ssh (ssh -tt + Popen) 的交互通道包装。

    模拟 Paramiko channel 的 4 个核心方法：send / recv / recv_ready / close，
    使 executor_adapter 中的 PTY 交互逻辑无需区分底层实现。

    原理：
    - ssh -tt 强制分配远程 PTY
    - stdin=PIPE  → send() 写入
    - stdout=PIPE → recv() / recv_ready() 读取（stderr 合并到 stdout）
    - bufsize=0   → 不缓冲，select 可即时感知数据
    """

    def __init__(self, proc: subprocess.Popen, askpass_cleanup=None):
        self._proc = proc
        self._cleanup = askpass_cleanup
        self._closed = False

    def send(self, data) -> int:
        """向远程 PTY 发送数据（兼容 str 和 bytes）。"""
        if self._closed:
            raise OSError("Channel is closed")
        if self._proc.poll() is not None:
            raise OSError("Channel is closed (process exited)")
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._proc.stdin.write(data)
        self._proc.stdin.flush()
        return len(data)

    def recv(self, nbytes: int = 65536) -> bytes:
        """非阻塞读取远程 PTY 输出。无数据时返回 b""。"""
        if self._closed:
            return b""
        try:
            rlist, _, _ = select.select([self._proc.stdout], [], [], 0.1)
        except (ValueError, OSError):
            return b""
        if rlist:
            try:
                return os.read(self._proc.stdout.fileno(), nbytes)
            except (OSError, ValueError):
                return b""
        return b""

    def recv_ready(self) -> bool:
        """检查是否有数据可读（非阻塞）。"""
        if self._closed:
            return False
        try:
            rlist, _, _ = select.select([self._proc.stdout], [], [], 0)
            return bool(rlist)
        except (ValueError, OSError):
            return False

    def close(self):
        """关闭通道：关 stdin → terminate → kill → 清理 askpass 临时文件。"""
        if self._closed:
            return
        self._closed = True
        # 关闭 stdin 让远程 shell 收到 EOF
        try:
            self._proc.stdin.close()
        except Exception:
            pass
        # 等待进程退出
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                import signal
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    self._proc.kill()
                except Exception:
                    pass
        except Exception:
            pass
        # 关闭 stdout
        try:
            self._proc.stdout.close()
        except Exception:
            pass
        # 清理 askpass 临时文件
        if self._cleanup:
            try:
                self._cleanup()
            except Exception:
                pass


class SSHManager:
    def __init__(self, config: SSHConfig):
        self.config = config
        self.client = None
        self.jump_client = None
        self.use_system_ssh = False
        self.last_error = ""
        self._current_process = None  # 追踪 system ssh 子进程，支持 abort
        self._pty_channels: list[SystemSSHChannel] = []  # 追踪 PTY 通道，abort 时全部关闭

    def _build_ssh_base_command(self, force_tty: bool = False) -> list[str]:
        if self.config.login_mode == "jump":
            jump = f"{self.config.jump_username}@{self.config.jump_host}"
            proxy_jump = f"{jump}:{self.config.jump_port}"
        else:
            proxy_jump = None

        cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "UserKnownHostsFile=/dev/null",
            "-o",
            "PreferredAuthentications=password",
            "-o",
            "PubkeyAuthentication=no",
            "-o",
            "NumberOfPasswordPrompts=1",
            "-o",
            f"ConnectTimeout={self.config.timeout}",
        ]
        if force_tty:
            cmd.append("-tt")
        if proxy_jump:
            cmd.extend(["-J", proxy_jump])
        cmd.extend([
            "-p",
            str(self.config.port),
            f"{self.config.username}@{self.config.host}",
        ])
        return cmd

    def _run_system_ssh(self, remote_command: str, timeout: int | None = None, force_tty: bool = False) -> subprocess.CompletedProcess:
        if self.config.login_mode == "jump":
            raise RuntimeError("当前 OpenSSH 回退模式暂不支持跳板机双密码场景")

        askpass_dir = tempfile.mkdtemp(prefix="ssh_askpass_")
        askpass_path = os.path.join(askpass_dir, "askpass.sh")
        try:
            with open(askpass_path, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n")
                f.write(f"echo {shlex.quote(self.config.password)}\n")
            os.chmod(askpass_path, 0o700)

            cmd = self._build_ssh_base_command(force_tty=force_tty) + [remote_command]
            env = os.environ.copy()
            env["DISPLAY"] = env.get("DISPLAY", ":999")
            env["SSH_ASKPASS"] = askpass_path
            env["SSH_ASKPASS_REQUIRE"] = "force"
            env.setdefault("LC_ALL", "C.UTF-8")

            effective_timeout = timeout or self.config.timeout
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
            self._current_process = proc
            try:
                stdout, stderr = proc.communicate(timeout=effective_timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate(timeout=5)
            finally:
                self._current_process = None

            return subprocess.CompletedProcess(
                args=cmd, returncode=proc.returncode,
                stdout=stdout or "", stderr=stderr or "",
            )
        finally:
            try:
                os.remove(askpass_path)
            except Exception:
                pass
            try:
                os.rmdir(askpass_dir)
            except Exception:
                pass

    def _should_fallback_to_system_ssh(self, error: Exception) -> bool:
        # 跳板机双密码场景 system ssh 无法处理，不回退，直接把原始错误上报
        if self.config.login_mode == "jump":
            return False
        message = str(error).lower()
        return isinstance(error, paramiko.ssh_exception.IncompatiblePeer) or "no acceptable ciphers" in message

    def _connect_with_system_ssh(self) -> bool:
        result = self._run_system_ssh("true", timeout=self.config.timeout)
        if result.returncode == 0:
            self.use_system_ssh = True
            self.last_error = ""
            return True

        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        self.last_error = stderr or stdout or f"OpenSSH 返回码 {result.returncode}"
        return False

    def connect(self) -> bool:
        self.use_system_ssh = False
        self.last_error = ""
        try:
            if self.config.login_mode == "jump":
                self.jump_client = paramiko.SSHClient()
                self.jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.jump_client.connect(
                    hostname=self.config.jump_host,
                    port=self.config.jump_port,
                    username=self.config.jump_username,
                    password=self.config.jump_password,
                    timeout=self.config.timeout,
                )

                jump_transport = self.jump_client.get_transport()
                jump_channel = jump_transport.open_channel(
                    "direct-tcpip",
                    (self.config.host, self.config.port),
                    ("127.0.0.1", 0),
                )

                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.client.connect(
                    hostname=self.config.host,
                    port=self.config.port,
                    username=self.config.username,
                    password=self.config.password,
                    timeout=self.config.timeout,
                    sock=jump_channel,
                )
            else:
                self.client = paramiko.SSHClient()
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.client.connect(
                    hostname=self.config.host,
                    port=self.config.port,
                    username=self.config.username,
                    password=self.config.password,
                    timeout=self.config.timeout,
                )
            return True
        except Exception as e:
            self.last_error = str(e)
            print(f"SSH 连接失败: {e}")
            self.disconnect()
            if self._should_fallback_to_system_ssh(e):
                try:
                    return self._connect_with_system_ssh()
                except Exception as fallback_error:
                    self.last_error = str(fallback_error)
                    print(f"OpenSSH 回退失败: {fallback_error}")
            elif self.config.login_mode == "jump":
                # 跳板机模式无法回退 system ssh，给出可操作提示
                msg = str(e).lower()
                if "no acceptable ciphers" in msg or isinstance(e, paramiko.ssh_exception.IncompatiblePeer):
                    self.last_error = (
                        "跳板机或目标设备仅提供当前 Paramiko 不支持的加密套件，"
                        "且 OpenSSH 回退模式不支持跳板机双密码场景。"
                        f"原始错误：{e}"
                    )
            return False

    def test_connection(self) -> tuple[bool, str]:
        if self.connect():
            mode_text = "跳板机" if self.config.login_mode == "jump" else "直连"
            suffix = "（已自动切换为 OpenSSH 兼容模式）" if self.use_system_ssh else ""
            self.disconnect()
            return True, f"SSH {mode_text}连接测试成功{suffix}"

        detail = self.last_error or "请检查主机、账号、密码或跳板机配置"
        if "no acceptable ciphers" in detail.lower():
            detail = f"目标设备仅提供当前 Paramiko 不支持的加密套件：{detail}"
        return False, f"SSH 连接测试失败：{detail}"

    def execute(self, cmd: str, timeout: int = 30, force_tty: bool = False) -> tuple:
        """执行命令，返回 (exit_code, stdout, stderr)

        对于后台命令（nohup ... &），确保不会因为 channel 未关闭而永久阻塞。
        """
        if self.use_system_ssh:
            result = self._run_system_ssh(cmd, timeout=timeout, force_tty=force_tty)
            return result.returncode, result.stdout, result.stderr

        if not self.client:
            raise RuntimeError("SSH 未连接")

        transport = self.client.get_transport()
        channel = transport.open_session()
        channel.settimeout(timeout)

        if force_tty:
            channel.get_pty()

        channel.exec_command(cmd)

        # 读取 stdout/stderr 带超时保护
        import time
        stdout_data = b""
        stderr_data = b""
        start = time.time()

        while True:
            elapsed = time.time() - start
            if elapsed >= timeout:
                break
            # 检查 channel 是否已经关闭（命令结束）
            if channel.exit_status_ready():
                # 命令已结束，读取剩余数据
                while channel.recv_ready():
                    stdout_data += channel.recv(65536)
                while channel.recv_stderr_ready():
                    stderr_data += channel.recv_stderr(65536)
                break
            # 读取可用数据
            if channel.recv_ready():
                stdout_data += channel.recv(65536)
            if channel.recv_stderr_ready():
                stderr_data += channel.recv_stderr(65536)
            # 短暂等待避免 busy loop
            time.sleep(0.05)

        exit_code = channel.recv_exit_status() if channel.exit_status_ready() else 0
        channel.close()

        return (
            exit_code,
            stdout_data.decode("utf-8", errors="replace"),
            stderr_data.decode("utf-8", errors="replace"),
        )

    def _open_system_ssh_pty(self, remote_command: str | None = None,
                              timeout: int = 300) -> SystemSSHChannel:
        """通过 system ssh -tt 打开交互式 PTY 通道。

        与 Paramiko channel 接口兼容，executor_adapter 无需区分底层实现。

        参数:
            remote_command: 远程命令（None 表示打开交互 shell）
            timeout: 超时秒数（仅用于日志/文档，实际由调用方控制读取超时）
        """
        askpass_dir = tempfile.mkdtemp(prefix="ssh_askpass_")
        askpass_path = os.path.join(askpass_dir, "askpass.sh")
        with open(askpass_path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
            f.write(f"echo {shlex.quote(self.config.password)}\n")
        os.chmod(askpass_path, 0o700)

        cmd = self._build_ssh_base_command(force_tty=True)
        if remote_command:
            cmd.append(remote_command)

        env = os.environ.copy()
        env["DISPLAY"] = env.get("DISPLAY", ":999")
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("LC_ALL", "C.UTF-8")

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 合并 stderr 到 stdout
            bufsize=0,                 # unbuffered，select 可即时感知
            env=env,
            start_new_session=True,
        )

        def cleanup():
            try:
                os.remove(askpass_path)
            except Exception:
                pass
            try:
                os.rmdir(askpass_dir)
            except Exception:
                pass

        channel = SystemSSHChannel(proc, cleanup)
        self._pty_channels.append(channel)
        return channel

    def open_interactive_channel(self, cmd: str, timeout: int = 300):
        """打开 PTY 交互通道（执行指定命令）。

        Paramiko 模式：exec_command + get_pty
        System SSH 模式：ssh -tt <cmd>（SystemSSHChannel 包装）
        """
        if self.use_system_ssh:
            return self._open_system_ssh_pty(remote_command=cmd, timeout=timeout)

        if not self.client:
            raise RuntimeError("SSH 未连接")
        channel = self.client.get_transport().open_session()
        channel.get_pty()
        channel.exec_command(cmd)
        return channel

    def open_shell_channel(self, timeout: int = 300):
        """打开持久化交互 shell（invoke_shell）。

        Paramiko 模式：invoke_shell()
        System SSH 模式：ssh -tt（无命令 → 进入登录 shell）
        """
        if self.use_system_ssh:
            return self._open_system_ssh_pty(remote_command=None, timeout=timeout)

        if not self.client:
            raise RuntimeError("SSH 未连接")
        channel = self.client.get_transport().open_session()
        channel.settimeout(timeout)
        channel.get_pty(width=200, height=50)
        channel.invoke_shell()
        return channel

    def disconnect(self):
        self.use_system_ssh = False
        self.abort()
        if self.client:
            self.client.close()
            self.client = None
        if self.jump_client:
            self.jump_client.close()
            self.jump_client = None

    def abort(self):
        """强制终止当前正在执行的 SSH 子进程和 PTY 通道。"""
        # 终止普通 execute 的子进程
        proc = self._current_process
        if proc and proc.poll() is None:
            try:
                import signal
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                try:
                    proc.kill()
                except Exception:
                    pass
        # 关闭所有 SystemSSHChannel PTY 通道
        for ch in list(self._pty_channels):
            try:
                ch.close()
            except Exception:
                pass
        self._pty_channels.clear()