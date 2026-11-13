"""SCP/SFTP 传输命令构建与下载路径单测（含跳板机模式）。"""
import os
import subprocess
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.ssh_manager import SSHManager  # noqa: E402
from app.core.test_case import SSHConfig  # noqa: E402


def _jump_config() -> SSHConfig:
    return SSHConfig(
        login_mode="jump", host="10.0.0.5", port=22,
        username="root", password="board_pwd",
        jump_host="10.0.0.9", jump_port=2222,
        jump_username="ops", jump_password="jump_pwd",
    )


def test_direct_scp_uses_askpass():
    manager = SSHManager(SSHConfig(host="10.0.0.5", username="root", password="pwd"))
    cmd, env, cleanup = manager.build_scp_command("/tmp/a.yuv", "root@10.0.0.5:/tmp/b.yuv")

    assert cmd[0] == "scp"
    assert "-P" in cmd and "22" in cmd
    assert "ProxyCommand" not in " ".join(cmd)
    askpass = env["SSH_ASKPASS"]
    assert os.path.exists(askpass)
    cleanup()
    assert not os.path.exists(askpass)


def test_jump_scp_goes_through_proxycommand(monkeypatch):
    monkeypatch.setattr(SSHManager, "_has_sshpass", staticmethod(lambda: True))
    manager = SSHManager(_jump_config())
    cmd, env, cleanup = manager.build_scp_command(
        "/tmp/a.yuv", "root@10.0.0.5:/tmp/b.yuv", recursive=True)

    assert cmd[:3] == ["sshpass", "-p", "board_pwd"]
    assert "scp" in cmd and "-r" in cmd
    proxy = [c for c in cmd if c.startswith("ProxyCommand=")]
    assert proxy, "跳板机模式必须携带 ProxyCommand"
    assert "sshpass -p jump_pwd ssh -W %h:%p" in proxy[0]
    assert "-p 2222 ops@10.0.0.9" in proxy[0]
    assert "SSH_ASKPASS" not in env


def test_jump_scp_requires_sshpass(monkeypatch):
    monkeypatch.setattr(SSHManager, "_has_sshpass", staticmethod(lambda: False))
    manager = SSHManager(_jump_config())
    try:
        manager.build_scp_command("/tmp/a.yuv", "root@10.0.0.5:/tmp/b.yuv")
    except RuntimeError as exc:
        assert "sshpass" in str(exc)
    else:
        raise AssertionError("缺少 sshpass 时应抛 RuntimeError")


class _FakeChannel:
    def settimeout(self, timeout):
        pass


class _FakeSFTP:
    def __init__(self):
        self.get_calls = []
        self.closed = False

    def get_channel(self):
        return _FakeChannel()

    def get(self, remote, local):
        self.get_calls.append((remote, local))

    def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self):
        self.sftp = _FakeSFTP()

    def open_sftp(self):
        return self.sftp


def test_download_file_prefers_sftp():
    """跳板机/直连均可复用已建立连接走 SFTP，避免依赖 sshpass。"""
    manager = SSHManager(_jump_config())
    manager.client = _FakeClient()
    manager.download_file("/data/a.yuv", "/tmp/a.yuv")

    assert manager.client.sftp.get_calls == [("/data/a.yuv", "/tmp/a.yuv")]
    assert manager.client.sftp.closed


def test_download_file_falls_back_to_scp(monkeypatch):
    """无 Paramiko 连接（OpenSSH 回退）时走 scp，并带上跳板机参数。"""
    monkeypatch.setattr(SSHManager, "_has_sshpass", staticmethod(lambda: True))
    manager = SSHManager(_jump_config())

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    manager.download_file("/data/a.yuv", "/tmp/a.yuv")

    cmd = captured["cmd"]
    assert cmd[0] == "sshpass"
    assert any(c.startswith("ProxyCommand=") for c in cmd)


if __name__ == "__main__":
    # 无 pytest 环境下的最小 monkeypatch 替身（支持 monkeypatch.setattr）
    class _MonkeyPatch:
        def __init__(self):
            self._undo = []

        def setattr(self, target, name, value):
            if isinstance(target, type):
                old = target.__dict__.get(name, _MISSING)
            else:
                old = getattr(target, name, _MISSING)
            setattr(target, name, value)
            self._undo.append((target, name, old))

        def undo(self):
            for target, name, old in reversed(self._undo):
                if old is _MISSING:
                    delattr(target, name)
                else:
                    setattr(target, name, old)
            self._undo.clear()

    _MISSING = object()
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            mp = _MonkeyPatch()
            try:
                if fn.__code__.co_argcount:
                    fn(mp)
                else:
                    fn()
                print(f"{name}: PASS")
            finally:
                mp.undo()
