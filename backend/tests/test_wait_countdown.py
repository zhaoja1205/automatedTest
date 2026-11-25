"""执行等待倒计时：后端只推送总时长，前端本地递减。"""
import asyncio
import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.executor_adapter import ExecutorAdapter  # noqa: E402


class FakeWS:
    def __init__(self):
        self.progress = []
        self.logs = []

    async def send_progress(self, current, total, case_id, case_key="",
                            message="", wait_total=0.0, wait_remaining=0.0):
        self.progress.append({
            "current": current,
            "total": total,
            "case_id": case_id,
            "message": message,
            "wait_total": wait_total,
            "wait_remaining": wait_remaining,
        })

    async def send_log(self, message, level="info"):
        self.logs.append((level, message))


def _make_adapter():
    ws = FakeWS()
    adapter = ExecutorAdapter(None, ws)
    adapter._progress_current = 1
    adapter._progress_total = 1
    adapter._progress_case_id = "FT_001"
    return adapter, ws


def test_begin_wait_progress_sends_total_only_once():
    adapter, ws = _make_adapter()

    asyncio.run(adapter._begin_wait_progress(0.6, "正在等待步骤"))

    assert len(ws.progress) == 1, "等待开始只应推送一次，剩余时间由前端本地递减"
    first = ws.progress[0]
    assert first["message"] == "正在等待步骤"
    assert first["wait_total"] == 0.6
    assert first["wait_remaining"] == 0.6

    # 等待结束后清空倒计时字段
    asyncio.run(adapter._clear_wait_progress("正在等待步骤"))
    assert ws.progress[-1]["wait_total"] == 0
    assert ws.progress[-1]["wait_remaining"] == 0
    assert adapter._progress_wait_total == 0
    assert adapter._progress_wait_deadline == 0


def test_with_wait_countdown_does_not_push_per_second():
    adapter, ws = _make_adapter()

    async def _fast_result():
        await asyncio.sleep(0.2)
        return "output"

    result = asyncio.run(
        adapter._with_wait_countdown(_fast_result(), 5.0, "正在等待输出")
    )

    assert result == "output"
    # 只有开始 + 结束两条进度消息，不按秒推送
    assert len(ws.progress) == 2
    assert ws.progress[0]["wait_total"] == 5.0
    assert ws.progress[0]["wait_remaining"] == 5.0
    assert ws.progress[-1]["wait_total"] == 0
    assert ws.progress[-1]["wait_remaining"] == 0
    assert adapter._progress_wait_total == 0


def test_wait_step_delay_pushes_start_and_logs():
    adapter, ws = _make_adapter()
    case = SimpleNamespace(case_id="FT_001")
    step = SimpleNamespace(wait_seconds=0.5)

    asyncio.run(adapter._wait_step_delay(case, step))

    assert any("等待" in text for _, text in ws.logs)
    assert len(ws.progress) == 2
    assert ws.progress[0]["wait_total"] == 0.5
    assert ws.progress[0]["wait_remaining"] == 0.5
    assert ws.progress[-1]["wait_total"] == 0


def test_live_snapshot_computes_remaining_from_deadline():
    adapter, ws = _make_adapter()

    async def _begin_then_snapshot():
        await adapter._begin_wait_progress(10.0, "正在等待")
        return adapter.live_terminal_snapshot()["progress"]

    progress = asyncio.run(_begin_then_snapshot())

    assert progress["wait_total"] == 10.0
    assert 0 < progress["wait_remaining"] <= 10.0
