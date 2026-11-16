"""执行日志草稿箱：备注写回与草稿恢复接口。"""
import asyncio
import os
import sys
import types
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from openpyxl import Workbook, load_workbook  # noqa: E402

from app.core.excel_handler import ExcelHandler  # noqa: E402
from app.api.routes import (  # noqa: E402
    _apply_session_case_edits,
    RestoreCaseLogItem,
    RestoreCaseLogsRequest,
    restore_case_logs,
)

CASE_KEY = "功能测试:15:FT_001"
MARKER = "--- 执行日志 ---"


def _build_case_workbook(path: Path, remarks: str = "") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "功能测试"
    headers = {
        "B": "测试用例ID", "C": "测试类型", "E": "测试用例描述",
        "K": "实际结果", "L": "BUG", "M": "备注",
        "N": "测试版本", "O": "实施者", "P": "测试日期",
    }
    for col, title in headers.items():
        ws[f"{col}13"] = title
    ws["B15"] = "FT_001"
    ws["C15"] = "功能"
    ws["E15"] = "起流测试"
    if remarks:
        ws["M15"] = remarks
    wb.save(path)
    return path


def _session(case_key: str = CASE_KEY, remarks: str = "") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        is_running=False,
        test_cases=[{
            "case_key": case_key,
            "case_id": "FT_001",
            "source_sheet": "功能测试",
            "row_number": 15,
            "test_steps": "起流测试",
            "expected_result": "",
            "remarks": remarks,
            "status": "NT",
            "actual_result": "",
            "judgment": "",
        }],
    )


def test_update_remarks_and_read_back(tmp_path):
    path = _build_case_workbook(tmp_path / "case.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))
    case_key = handler.test_cases[0].case_key
    assert case_key == CASE_KEY
    assert handler.update_remarks(case_key, f"{MARKER}\nline 1\nline 2", save=False)
    handler.save(str(path))

    reloaded = ExcelHandler()
    cases = reloaded.load(str(path))
    assert cases[0].remarks == f"{MARKER}\nline 1\nline 2"


def test_apply_session_remarks_on_download_copy(tmp_path):
    """下载副本应带上草稿箱恢复的日志（工作簿备注原本为空）。"""
    path = _build_case_workbook(tmp_path / "case.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))
    log = "restored line 1\nrestored line 2"
    session = _session(remarks=f"{MARKER}\n{log}")
    session.test_cases[0]["status"] = "Pass"

    applied = _apply_session_case_edits(handler, session)
    assert applied >= 1
    assert handler.test_cases[0].remarks == f"{MARKER}\n{log}"


def test_restore_case_logs_endpoint(tmp_path):
    session = _session()
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    payload = RestoreCaseLogsRequest(cases=[
        RestoreCaseLogItem(
            case_key=CASE_KEY,
            case_id="FT_001",
            log_text="line 1\nline 2",
            status="Pass",
            actual_result="Pass",
            judgment="[AI判定] Pass (置信度=0.95)",
            ai_evidence=["line 1"],
        ),
        RestoreCaseLogItem(case_key="功能测试:99:FT_404", case_id="FT_404", log_text="x"),
    ])

    result = asyncio.run(restore_case_logs(request, payload))
    assert result["applied"] == 1
    assert result["missing"] == ["功能测试:99:FT_404"]

    case = session.test_cases[0]
    assert case["remarks"] == f"{MARKER}\nline 1\nline 2"
    assert case["status"] == "Pass"
    assert case["judgment"] == "[AI判定] Pass (置信度=0.95)"
    assert case["ai_evidence"] == ["line 1"]


def test_restore_keeps_existing_non_log_remarks(tmp_path):
    """备注中原本有 AI / 人工内容时只替换日志段。"""
    session = _session(remarks=f"人工备注\n{MARKER}\nold log")
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    payload = RestoreCaseLogsRequest(cases=[
        RestoreCaseLogItem(case_key=CASE_KEY, log_text="new log"),
    ])
    asyncio.run(restore_case_logs(request, payload))
    assert session.test_cases[0]["remarks"] == f"人工备注\n{MARKER}\nnew log"
