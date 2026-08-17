"""
SSH 管理器。

默认优先使用 Paramiko；若目标设备仅提供 Paramiko 3.4.0 不支持的
AES-GCM cipher，则自动回退到系统 OpenSSH。
"""
import os
import shlex
import subprocess
import tempfile

import paramiko
from app.core.test_case import SSHConfig


class SSHManager:
    def __init__(self, config: SSHConfig):
        self.config = config
        self.client = None
        self.jump_client = None
        self.use_system_ssh = False
        self.last_error = ""
        self._current_process = None  # 追踪 system ssh 子进程，支持 abort

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

    def open_interactive_channel(self, cmd: str, timeout: int = 300):
        """打开 PTY 交互通道"""
        if self.use_system_ssh:
            raise RuntimeError("当前 OpenSSH 兼容模式不支持交互式 PTY 通道")

        if not self.client:
            raise RuntimeError("SSH 未连接")
        channel = self.client.get_transport().open_session()
        channel.get_pty()
        channel.exec_command(cmd)
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
        """强制终止当前正在执行的 SSH 子进程（用于用户点停止时立即中断）。"""
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