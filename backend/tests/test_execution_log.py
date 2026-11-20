"""执行日志（非板端原始输出）落盘与历史检索单测。"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.execution_log import (  # noqa: E402
    ExecutionLogRecorder,
    delete_execution_log,
    find_execution_log,
    list_execution_logs,
    read_execution_log,
)

RUN_ID = "a" * 32
RUN_ID_2 = "b" * 32


def test_recorder_writes_entries_and_metadata(tmp_path):
    recorder = ExecutionLogRecorder(
        RUN_ID,
        session_id="session-1",
        metadata={
            "started_at": "2026-11-19T10:00:00",
            "excel_filename": "case.xlsx",
            "tester_name": "tester",
            "test_version": "1.0",
        },
        root_dir=str(tmp_path),
    )
    recorder.append("SSH 连接成功", "info", timestamp_ms=1_700_000_000_000)
    recorder.append("执行异常", "error", timestamp_ms=1_700_000_001_000)

    meta_path = recorder.meta_path
    assert os.path.isfile(meta_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["run_id"] == RUN_ID
    assert meta["session_id"] == "session-1"
    assert meta["status"] == "running"
    assert meta["excel_filename"] == "case.xlsx"

    recorder.close(status="finished", message="执行完成")
    content = read_execution_log(recorder.path)
    assert "SSH 连接成功" in content
    assert "[error] 执行异常" in content
    assert "执行结束" in content
    assert "状态=finished" in content

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["status"] == "finished"
    assert meta["ended_at"]


def test_list_find_and_delete(tmp_path):
    first = ExecutionLogRecorder(
        RUN_ID,
        metadata={"started_at": "2026-11-19T10:00:00"},
        root_dir=str(tmp_path),
    )
    first.append("第一条日志", "info")
    first.close(status="finished")

    second = ExecutionLogRecorder(
        RUN_ID_2,
        metadata={"started_at": "2026-11-19T11:00:00"},
        root_dir=str(tmp_path),
    )
    second.append("第二条日志", "warning")
    second.close(status="stopped")

    items = list_execution_logs(root_dir=str(tmp_path))
    assert [item["run_id"] for item in items] == [RUN_ID_2, RUN_ID]
    assert items[0]["status"] == "stopped"
    assert items[0]["size"] > 0

    assert find_execution_log(RUN_ID, root_dir=str(tmp_path)) == first.path
    assert find_execution_log("not-exist", root_dir=str(tmp_path)) == ""

    assert delete_execution_log(RUN_ID, root_dir=str(tmp_path)) is True
    assert not os.path.isfile(first.path)
    assert not os.path.isfile(first.meta_path)
    assert [item["run_id"] for item in list_execution_logs(root_dir=str(tmp_path))] == [RUN_ID_2]


def test_orphan_metadata_without_log_is_skipped(tmp_path):
    meta_path = tmp_path / "execution_20261119_120000_cccccccccccccccccccccccccccccccc.json"
    meta_path.write_text(
        json.dumps({"run_id": "c" * 32, "path": str(tmp_path / "missing.log")}),
        encoding="utf-8",
    )
    assert list_execution_logs(root_dir=str(tmp_path)) == []
