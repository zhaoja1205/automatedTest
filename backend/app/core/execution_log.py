"""执行日志（非板端原始输出）的落盘与检索。

执行过程中通过 WebSocket 推送的 ``type=log`` 消息会同步写入
``logs/execution/<时间>_<run_id>.log``，并在旁边维护一个同名
``.json`` 元数据文件。板端终端原始输出仍由 ``terminal_log`` 按用例
单独保存，两者互不影响。

这样即使浏览器刷新、WebSocket 断开或后端重启，也能在执行日志页
回看之前每次执行的过程日志。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

EXECUTION_LOG_DIR = os.path.join("logs", "execution")
_META_SUFFIX = ".json"
_SAFE_RUN_ID = re.compile(r"^[0-9a-fA-F]{32}$")


def _safe_run_id(run_id: str) -> str:
    """task_id 正常情况下是 uuid4().hex；兜底清洗成安全文件名片段。"""
    text = str(run_id or "").strip()
    if _SAFE_RUN_ID.match(text):
        return text
    safe = re.sub(r"[^0-9A-Za-z_-]", "_", text)
    return safe or datetime.now().strftime("%Y%m%d%H%M%S%f")


def _stamp_from_iso(value: str) -> str:
    """把 ISO 时间转成文件名用的 ``YYYYMMDD_HHMMSS``。"""
    text = str(value or "").strip()
    if text:
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.strftime("%Y%m%d_%H%M%S")
        except Exception:
            pass
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _normalize_path(path: str) -> str:
    """统一以正斜杠返回，前端可直接回传给接口。"""
    return str(path or "").replace(os.sep, "/")


def _meta_path_for(log_path: str) -> str:
    return log_path[:-4] + _META_SUFFIX if log_path.endswith(".log") else log_path + _META_SUFFIX


class ExecutionLogRecorder:
    """把一次执行的实时日志追加到独立文件。"""

    def __init__(
        self,
        run_id: str,
        session_id: str = "",
        metadata: Optional[Dict] = None,
        root_dir: str = EXECUTION_LOG_DIR,
    ):
        self.run_id = _safe_run_id(run_id)
        self.session_id = str(session_id or "")
        self.root_dir = root_dir
        os.makedirs(self.root_dir, exist_ok=True)

        meta = dict(metadata or {})
        started_at = str(meta.get("started_at") or datetime.now().isoformat())
        filename = f"{_stamp_from_iso(started_at)}_{self.run_id}.log"
        self.path = os.path.join(self.root_dir, filename)
        self.meta_path = _meta_path_for(self.path)
        self._lock = threading.Lock()
        self._closed = False

        meta.update({
            "run_id": self.run_id,
            "session_id": self.session_id,
            "path": _normalize_path(self.path),
            "started_at": started_at,
            "ended_at": "",
            "status": "running",
        })
        self._meta = meta
        self._write_meta()

        self._fh = open(self.path, "a", encoding="utf-8")
        self._fh.write(
            f"# 执行日志 | run_id={self.run_id} | 开始={started_at}\n"
        )
        self._fh.flush()

    def _write_meta(self) -> None:
        """原子写元数据，避免列表接口读到半截 JSON。"""
        tmp_path = self.meta_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._meta, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.meta_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def append(self, message: str, level: str = "info",
               timestamp_ms: Optional[float] = None) -> None:
        """追加一条执行日志；写盘失败不影响测试执行。"""
        text = str(message or "").rstrip("\n")
        if not text:
            return
        ts = datetime.fromtimestamp(
            float(timestamp_ms or time.time() * 1000) / 1000.0
        )
        line = f"[{ts.strftime('%Y-%m-%d %H:%M:%S')}] [{level or 'info'}] {text}\n"
        with self._lock:
            if self._closed or self._fh.closed:
                return
            try:
                self._fh.write(line)
                self._fh.flush()
            except Exception:
                pass

    def close(self, status: str = "", message: str = "") -> None:
        """收尾：写结束标记、关闭文件并更新元数据。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            ended_at = datetime.now().isoformat()
            try:
                if not self._fh.closed:
                    self._fh.write(
                        f"# 执行结束 | 状态={status or 'finished'} | 结束={ended_at}"
                        f"{(' | ' + str(message)) if message else ''}\n"
                    )
                    self._fh.close()
            except Exception:
                pass
            self._meta.update({
                "ended_at": ended_at,
                "status": status or "finished",
                "message": str(message or ""),
            })
            self._write_meta()


def list_execution_logs(limit: int = 100,
                        root_dir: str = EXECUTION_LOG_DIR) -> List[dict]:
    """列出历史执行日志（按开始时间倒序）。"""
    if not os.path.isdir(root_dir):
        return []
    items: List[dict] = []
    for name in os.listdir(root_dir):
        if not name.endswith(_META_SUFFIX):
            continue
        meta_path = os.path.join(root_dir, name)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        if not isinstance(meta, dict):
            continue

        log_path = str(meta.get("path") or "")
        if not log_path:
            log_path = os.path.join(root_dir, name[:-len(_META_SUFFIX)] + ".log")
            meta["path"] = _normalize_path(log_path)
        if not os.path.isfile(log_path):
            # 元数据在、日志被删：跳过，避免点开是空记录
            continue

        try:
            stat = os.stat(log_path)
            size = stat.st_size
            mtime = stat.st_mtime
        except Exception:
            size, mtime = 0, 0
        items.append({
            "run_id": meta.get("run_id", ""),
            "session_id": meta.get("session_id", ""),
            "path": meta.get("path", ""),
            "started_at": meta.get("started_at", ""),
            "ended_at": meta.get("ended_at", ""),
            "status": meta.get("status", ""),
            "message": meta.get("message", ""),
            "excel_filename": meta.get("excel_filename", ""),
            "tester_name": meta.get("tester_name", ""),
            "test_version": meta.get("test_version", ""),
            "size": size,
            "mtime": mtime,
        })

    items.sort(key=lambda item: (item.get("started_at") or ""), reverse=True)
    return items[:max(1, int(limit))]


def find_execution_log(run_id: str,
                       root_dir: str = EXECUTION_LOG_DIR) -> str:
    """按 run_id 找到执行日志路径；找不到返回空串。"""
    target = _safe_run_id(run_id)
    for item in list_execution_logs(limit=100000, root_dir=root_dir):
        if item.get("run_id") == target:
            return str(item.get("path") or "")
    return ""


def read_execution_log(path: str) -> str:
    """读取执行日志全文。"""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def delete_execution_log(run_id: str,
                         root_dir: str = EXECUTION_LOG_DIR) -> bool:
    """删除某次执行的日志与元数据；返回是否删除了文件。"""
    target = _safe_run_id(run_id)
    removed = False
    if not os.path.isdir(root_dir):
        return False
    for name in os.listdir(root_dir):
        if not name.endswith(_META_SUFFIX):
            continue
        meta_path = os.path.join(root_dir, name)
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        if str(meta.get("run_id") or "") != target:
            continue
        for candidate in (meta_path, meta.get("path")):
            try:
                if candidate and os.path.isfile(candidate):
                    os.remove(candidate)
                    removed = True
            except Exception:
                pass
    return removed
