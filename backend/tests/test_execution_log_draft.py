"""执行日志草稿箱：备注写回与草稿恢复接口。"""
import asyncio
import os
import sys
import types
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from fastapi import HTTPException  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402

from app.core.excel_handler import ExcelHandler  # noqa: E402
from app.core.test_case import SSHConfig  # noqa: E402
from app.api.routes import (  # noqa: E402
    _apply_session_case_edits,
    start_execution,
    RestoreCaseLogItem,
    RestoreCaseLogsRequest,
    RestoreCaseTerminalLog,
    restore_case_logs,
)

CASE_KEY = "功能测试:15:FT_001"
MARKER = "--- 执行日志 ---"


def _build_case_workbook(path: Path, remarks: str = "", status: str = "",
                         tester: str = "") -> Path:
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
    if status:
        ws["K15"] = status
    if tester:
        ws["O15"] = tester
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


def test_apply_session_status_on_download_copy(tmp_path):
    """重新上传用例后恢复草稿：下载副本的状态列应是草稿里的 Fail，而非旧结果。"""
    path = _build_case_workbook(tmp_path / "case.xlsx", status="Pass")
    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.test_cases[0].status == "Pass"

    session = _session(remarks=f"{MARKER}\nrestored log")
    session.test_cases[0]["status"] = "Fail"
    session.test_cases[0]["judgment"] = "[AI判定] Fail (置信度=0.92)"

    _apply_session_case_edits(handler, session)

    assert handler.test_cases[0].status == "Fail"
    assert handler.test_cases[0].actual_result == "Fail"
    rcm = handler._result_col_for(handler.test_cases[0])
    ws = handler._worksheet_for_case(handler.test_cases[0])
    assert ws.cell(row=15, column=rcm["actual_result"]).value == "Fail"
    assert ws.cell(row=15, column=rcm["judgment"]).value == "[AI判定] Fail (置信度=0.92)"


def test_executed_case_tester_uses_workspace_config(tmp_path):
    """有执行日志的用例：下载副本的测试人员栏用工作区配置的测试人员替换。"""
    path = _build_case_workbook(tmp_path / "case.xlsx", tester="李四")
    handler = ExcelHandler()
    handler.load(str(path))
    assert handler.test_cases[0].tester == "李四"

    session = _session(remarks=f"{MARKER}\nrestored log")
    session.workspace = types.SimpleNamespace(tester_name="张三")

    _apply_session_case_edits(handler, session)

    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    assert ws.cell(row=15, column=rcm["tester"]).value == "张三"
    assert tc.tester == "张三"


def test_unexecuted_case_tester_untouched(tmp_path):
    """未执行用例（状态 NT 且无执行日志）不改测试人员栏。"""
    path = _build_case_workbook(tmp_path / "case.xlsx", tester="李四")
    handler = ExcelHandler()
    handler.load(str(path))

    session = _session()
    session.workspace = types.SimpleNamespace(tester_name="张三")

    _apply_session_case_edits(handler, session)

    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    assert ws.cell(row=15, column=rcm["tester"]).value == "李四"


def test_executed_case_without_log_still_updates_tester(tmp_path):
    """已判定但执行日志缺失的用例（如旧结果文件）也要更新测试人员。"""
    path = _build_case_workbook(tmp_path / "case.xlsx", status="Pass", tester="李四")
    handler = ExcelHandler()
    handler.load(str(path))

    session = _session()
    session.test_cases[0]["status"] = "Pass"
    session.workspace = types.SimpleNamespace(tester_name="张三")

    _apply_session_case_edits(handler, session)

    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    assert ws.cell(row=15, column=rcm["tester"]).value == "张三"
    assert tc.tester == "张三"


def test_executed_case_test_date_filled_from_session(tmp_path):
    """下载副本的测试日期栏取会话中的执行日期，精确到天。"""
    path = _build_case_workbook(tmp_path / "case.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))

    session = _session(remarks=f"{MARKER}\nrestored log")
    session.test_cases[0]["status"] = "Pass"
    session.test_cases[0]["test_date"] = "2026-11-19 09:30:00"

    _apply_session_case_edits(handler, session)

    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    assert ws.cell(row=15, column=rcm["test_date"]).value == "2026-11-19"
    assert tc.test_date == "2026-11-19"


def test_executed_case_test_date_falls_back_to_now(tmp_path):
    """会话没有执行日期时（如草稿恢复），下载结果时用当天日期补全。"""
    path = _build_case_workbook(tmp_path / "case.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))

    session = _session(remarks=f"{MARKER}\nrestored log")
    session.test_cases[0]["status"] = "Fail"

    _apply_session_case_edits(handler, session)

    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    value = str(ws.cell(row=15, column=rcm["test_date"]).value or "")
    assert len(value) == len("2026-11-19")
    assert value.count("-") == 2


def test_executed_case_test_date_normalizes_existing_datetime(tmp_path):
    """工作簿已有带时间的日期时，下载副本统一改成精确到天。"""
    path = _build_case_workbook(tmp_path / "case.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))
    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    ws.cell(row=15, column=rcm["test_date"]).value = "2026-11-18 15:20:00"
    tc.test_date = "2026-11-18 15:20:00"

    session = _session(remarks=f"{MARKER}\nrestored log")
    session.test_cases[0]["status"] = "Pass"

    _apply_session_case_edits(handler, session)

    assert ws.cell(row=15, column=rcm["test_date"]).value == "2026-11-18"
    assert tc.test_date == "2026-11-18"


def test_unexecuted_case_existing_test_date_normalized_to_day(tmp_path):
    """未执行用例已有带时间的日期时，也只保留到天（斜杠 / 文字格式同样兼容）。"""
    path = _build_case_workbook(tmp_path / "case.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))
    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    ws.cell(row=15, column=rcm["test_date"]).value = "2026/11/17 08:00"
    tc.test_date = "2026/11/17 08:00"

    _apply_session_case_edits(handler, _session())

    assert ws.cell(row=15, column=rcm["test_date"]).value == "2026-11-17"
    assert tc.test_date == "2026-11-17"


def test_unexecuted_case_test_date_untouched(tmp_path):
    """未执行用例（状态 NT 且无执行日志）不补测试日期。"""
    path = _build_case_workbook(tmp_path / "case.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))

    _apply_session_case_edits(handler, _session())

    tc = handler.test_cases[0]
    ws = handler._worksheet_for_case(tc)
    rcm = handler._result_col_for(tc)
    assert not ws.cell(row=15, column=rcm["test_date"]).value


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


def test_restore_terminals_uses_unified_terminal_format(tmp_path):
    """草稿按终端存储时，备注列也按 ``===== 终端 =====`` 分段存储。"""
    from app.core.remarks import extract_log_section
    from app.core.terminal_log import parse_terminal_log

    session = _session(remarks="人工备注")
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    payload = RestoreCaseLogsRequest(cases=[
        RestoreCaseLogItem(
            case_key=CASE_KEY,
            terminals=[
                RestoreCaseTerminalLog(label="终端A", content="a1\na2"),
                RestoreCaseTerminalLog(label="终端B", content="b1"),
            ],
        ),
    ])
    asyncio.run(restore_case_logs(request, payload))

    remark = session.test_cases[0]["remarks"]
    assert remark == (
        f"人工备注\n{MARKER}\n"
        "===== 终端A =====\na1\na2\n\n===== 终端B =====\nb1"
    )
    assert parse_terminal_log(extract_log_section(remark)) == [
        ("终端A", "a1\na2"),
        ("终端B", "b1"),
    ]


RESTORED_FIELDS = {
    "status": "Pass",
    "actual_result": "Pass",
    "log_file": "logs/restored.log",
    "remarks": f"{MARKER}\nrestored log",
    "judgment": "[AI判定] Pass (置信度=0.90)",
    "ai_judged": True,
    "ai_status": "Pass",
    "ai_confidence": 0.9,
    "ai_reason": "上一条执行的理由",
    "ai_evidence": ["restored line"],
    "bug_description": "旧 Bug 描述",
    "bug_severity": "一般",
}


def _execution_session(test_cases, ssh_config: SSHConfig) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        is_running=False,
        current_task=None,
        test_cases=test_cases,
        ssh_config=ssh_config,
    )


def _stub_background_task(monkeypatch) -> list:
    """拦截 asyncio.create_task，只记录后台协程而不真正执行。"""
    import asyncio as asyncio_module

    tasks: list = []

    def fake_create_task(coro):
        tasks.append(coro)
        coro.close()
        return None

    monkeypatch.setattr(asyncio_module, "create_task", fake_create_task)
    return tasks


def test_start_execution_clears_restored_results(monkeypatch):
    """草稿恢复后再执行：旧状态与「BUG」列 AI 判定不能残留到新一轮执行。"""
    case = {"case_key": CASE_KEY, "case_id": "FT_001", "selected": True, **RESTORED_FIELDS}
    session = _execution_session(
        [case], SSHConfig(host="10.0.0.1", username="root"),
    )
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    _stub_background_task(monkeypatch)

    result = asyncio.run(start_execution(request, None))

    assert result["selected_count"] == 1
    assert case["status"] == "NT"
    for field in ("actual_result", "log_file", "remarks", "judgment",
                  "ai_status", "ai_reason", "bug_description", "bug_severity"):
        assert case[field] == ""
    assert case["ai_judged"] is False
    assert case["ai_confidence"] == 0.0
    assert case["ai_evidence"] == []


def test_start_execution_keeps_unselected_restored_results(monkeypatch):
    """只重置选中的用例，未执行用例的草稿恢复结果保持不变。"""
    selected = {"case_key": CASE_KEY, "case_id": "FT_001", "selected": True, **RESTORED_FIELDS}
    untouched = {"case_key": "功能测试:16:FT_002", "case_id": "FT_002",
                 "selected": False, **RESTORED_FIELDS}
    session = _execution_session(
        [selected, untouched], SSHConfig(host="10.0.0.1", username="root"),
    )
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    _stub_background_task(monkeypatch)

    asyncio.run(start_execution(request, None))

    assert untouched["judgment"] == "[AI判定] Pass (置信度=0.90)"
    assert untouched["status"] == "Pass"


def test_start_execution_without_ssh_keeps_restored_results(monkeypatch):
    """启动前校验失败时不丢草稿恢复结果，用户修正配置后仍可再次执行。"""
    case = {"case_key": CASE_KEY, "case_id": "FT_001", "selected": True, **RESTORED_FIELDS}
    session = _execution_session([case], SSHConfig())
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    _stub_background_task(monkeypatch)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(start_execution(request, None))

    assert exc_info.value.status_code == 400
    assert session.current_task is None
    assert case["status"] == "Pass"
    assert case["judgment"] == "[AI判定] Pass (置信度=0.90)"
    assert case["remarks"] == f"{MARKER}\nrestored log"


def _duplicate_id_session():
    """两个不同表页里存在相同 case_id 的会话用例。"""
    return types.SimpleNamespace(
        is_running=False,
        test_cases=[
            {"case_key": "表1:15:1", "case_id": "1", "source_sheet": "表1",
             "row_number": 15, "description": "表1的起流测试", "remarks": "",
             "status": "NT"},
            {"case_key": "表2:16:1", "case_id": "1", "source_sheet": "表2",
             "row_number": 16, "description": "表2的切流测试", "remarks": "",
             "status": "NT"},
        ],
    )


def test_restore_duplicate_case_id_matches_description():
    """旧版导出文本没有 case_key 时，用用例描述区分重复的 case_id。"""
    session = _duplicate_id_session()
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    payload = RestoreCaseLogsRequest(cases=[
        RestoreCaseLogItem(
            case_id="1", description="表2的切流测试",
            log_text="line 1\nline 2", status="Pass",
        ),
    ])

    result = asyncio.run(restore_case_logs(request, payload))

    assert result["applied"] == 1
    assert result["missing"] == []
    assert session.test_cases[0]["remarks"] == ""
    assert session.test_cases[1]["remarks"] == f"{MARKER}\nline 1\nline 2"
    assert session.test_cases[1]["status"] == "Pass"


def test_restore_ambiguous_case_id_is_skipped():
    """重复 case_id 且描述无法区分时不恢复，避免写到错误的行。"""
    session = _duplicate_id_session()
    session.test_cases[1]["description"] = "表1的起流测试"
    request = types.SimpleNamespace(state=types.SimpleNamespace(session=session))
    payload = RestoreCaseLogsRequest(cases=[
        RestoreCaseLogItem(case_id="1", log_text="ambiguous log"),
    ])

    result = asyncio.run(restore_case_logs(request, payload))

    assert result["applied"] == 0
    assert result["missing"] == ["1"]
    assert all(case["remarks"] == "" for case in session.test_cases)
