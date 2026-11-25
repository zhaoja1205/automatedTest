"""用例内容写回：只写定义字段，不触碰执行结果列。"""
import os
import sys
from pathlib import Path

from openpyxl import Workbook

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.excel_handler import ExcelHandler  # noqa: E402
from app.core.test_case import TestCase  # noqa: E402

CASE_KEY = "功能测试:15:FT_001"


def _build_workbook(path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "功能测试"
    headers = {
        "B": "测试用例ID", "C": "测试类型", "D": "需求ID", "E": "设计方法",
        "F": "测试用例描述", "G": "前置条件", "H": "测试步骤", "I": "预期结果",
        "J": "优先级", "L": "实际结果", "M": "BUG", "N": "备注",
        "P": "实施者", "Q": "测试日期",
    }
    for col, title in headers.items():
        ws[f"{col}13"] = title
    ws["B15"] = "FT_001"
    ws["C15"] = "功能"
    ws["D15"] = "REQ_001"
    ws["E15"] = "等价类"
    ws["F15"] = "旧描述"
    ws["G15"] = "旧前置条件"
    ws["H15"] = "旧测试步骤"
    ws["I15"] = "旧预期结果"
    ws["J15"] = "中"
    # 执行信息：写回后必须保持原样
    ws["L15"] = "Pass"
    ws["M15"] = "[AI判定] 旧判定"
    ws["N15"] = "--- 执行日志 ---\nold log line"
    ws["P15"] = "张三"
    ws["Q15"] = "2026-11-01"
    wb.save(path)
    return path


def test_write_case_content_only_updates_definition_fields(tmp_path):
    path = _build_workbook(tmp_path / "cases.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))

    source = TestCase(
        case_id="FT_001",
        case_key=CASE_KEY,
        source_sheet="功能测试",
        row_number=15,
        test_type="功能-修改后",
        requirement_id="REQ_002",
        design_method="边界值",
        description="修改后的描述",
        prerequisites="修改后的前置条件",
        test_steps="1. 执行命令：./run.sh --case 1\n2. 输入 q",
        expected_result="1. 执行无报错\n2. 可正常退出",
        priority="高",
    )
    result = handler.write_case_content([source])

    assert result["total_cases"] == 1
    assert result["updated_cases"] == 1
    assert result["changed_cells"] == 8
    assert result["saved"] is True
    handler.close()

    reloaded = ExcelHandler()
    cases = reloaded.load(str(path))
    case = cases[0]
    assert case.test_type == "功能-修改后"
    assert case.requirement_id == "REQ_002"
    assert case.design_method == "边界值"
    assert case.description == "修改后的描述"
    assert case.prerequisites == "修改后的前置条件"
    assert case.test_steps.startswith("1. 执行命令：")
    assert case.expected_result.startswith("1. 执行无报错")
    assert case.priority == "高"

    # 执行结果 / 判定 / 日志 / 人员 / 日期不受写回影响
    assert case.actual_result == "Pass"
    assert case.judgment == "[AI判定] 旧判定"
    assert case.remarks == "--- 执行日志 ---\nold log line"
    assert case.tester == "张三"
    assert case.test_date == "2026-11-01"


def test_write_case_content_no_change_does_not_save(tmp_path):
    path = _build_workbook(tmp_path / "cases.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))

    # 与文件内容完全一致（TestCase 由 load 结果构造）
    result = handler.write_case_content(handler.test_cases)

    assert result["total_cases"] == 1
    assert result["updated_cases"] == 0
    assert result["changed_cells"] == 0
    assert result["saved"] is False


def test_clear_execution_info_keeps_only_definition_fields(tmp_path):
    path = _build_workbook(tmp_path / "cases.xlsx")
    handler = ExcelHandler()
    handler.load(str(path))

    cleaned = handler.clear_execution_info()
    assert cleaned == 1
    handler.workbook.save(str(path))
    handler.close()

    reloaded = ExcelHandler()
    cases = reloaded.load(str(path))
    case = cases[0]
    # 定义字段原样保留
    assert case.case_id == "FT_001"
    assert case.test_type == "功能"
    assert case.requirement_id == "REQ_001"
    assert case.design_method == "等价类"
    assert case.description == "旧描述"
    assert case.prerequisites == "旧前置条件"
    assert case.test_steps == "旧测试步骤"
    assert case.expected_result == "旧预期结果"
    assert case.priority == "中"

    # 执行信息全部清空
    assert case.actual_result == ""
    assert case.status == "NT"
    assert case.judgment == ""
    assert case.remarks == ""
    assert case.tester == ""
    assert case.test_date == ""
    assert case.test_version == ""

    ws = reloaded.workbook["功能测试"]
    assert ws["L15"].fill.fill_type in (None, "none")
