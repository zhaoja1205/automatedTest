"""备注列富文本：AI 证据日志行按判定状态着色。"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from openpyxl import Workbook, load_workbook  # noqa: E402
from openpyxl.cell.rich_text import CellRichText, TextBlock  # noqa: E402

from app.core.excel_handler import ExcelHandler  # noqa: E402
from app.core.remarks import build_rich_remark_from_case  # noqa: E402
from app.core.test_case import TestCase  # noqa: E402


def _write_log(tmp_path, text="") -> str:
    path = tmp_path / "case.log"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _colored_texts(rich):
    return [
        block.text
        for block in rich
        if isinstance(block, TextBlock)
        and block.font is not None
        and block.font.color is not None
        and block.font.color.rgb
    ]


def test_rich_remark_highlights_evidence_log_line_for_fail(tmp_path):
    log_file = _write_log(
        tmp_path,
        "start camera\n"
        "[INFO] frame rate 12fps\n"
        "error: timeout waiting for frames\n",
    )
    case = TestCase(
        case_id="FT_001", source_sheet="功能测试", status="Fail",
        ai_judged=True, ai_status="Fail", ai_confidence=0.9,
        ai_reason="帧率低于预期",
        ai_evidence=["frame rate 12fps"],
        log_file=log_file,
    )

    remark = build_rich_remark_from_case(case)
    assert isinstance(remark, CellRichText)
    colored = _colored_texts(remark)
    # AI 判定区的证据行也要着色，备注折叠时关键证据才可见
    assert any(text.strip().startswith("- ") and "12fps" in text for text in colored)
    # 日志区中的同一条证据同样着色
    assert any(not text.strip().startswith("- ") and "12fps" in text for text in colored)
    assert not any("timeout" in text for text in colored)
    fail_font = next(
        block.font for block in remark
        if isinstance(block, TextBlock) and "12fps" in block.text
    )
    assert fail_font.color.rgb == "FFD32F2F"


def test_rich_remark_uses_pass_and_review_colors(tmp_path):
    log_file = _write_log(tmp_path, "start camera\nframe rate 30fps\n")

    pass_case = TestCase(
        case_id="FT_002", source_sheet="功能测试", status="Pass",
        ai_judged=True, ai_status="Pass", ai_confidence=0.9,
        ai_evidence=["frame rate 30fps"], log_file=log_file,
    )
    review_case = TestCase(
        case_id="FT_003", source_sheet="功能测试", status="Review",
        ai_judged=True, ai_status="Review", ai_confidence=0.6,
        ai_evidence=["frame rate 30fps"], log_file=log_file,
    )

    pass_remark = build_rich_remark_from_case(pass_case)
    review_remark = build_rich_remark_from_case(review_case)
    assert isinstance(pass_remark, CellRichText)
    assert isinstance(review_remark, CellRichText)
    pass_block = next(
        block for block in pass_remark
        if isinstance(block, TextBlock) and "30fps" in block.text
    )
    review_block = next(
        block for block in review_remark
        if isinstance(block, TextBlock) and "30fps" in block.text
    )
    assert pass_block.font.color.rgb == "FF2E7D32"
    assert review_block.font.color.rgb == "FFB8860B"


def test_rich_remark_without_evidence_stays_plain(tmp_path):
    log_file = _write_log(tmp_path, "some log line\n")
    case = TestCase(
        case_id="FT_004", source_sheet="功能测试", status="Fail",
        ai_judged=True, ai_status="Fail", ai_confidence=0.7,
        ai_reason="输出异常", ai_evidence=[], log_file=log_file,
    )
    remark = build_rich_remark_from_case(case)
    assert isinstance(remark, str)
    assert "some log line" in remark


def _build_case_workbook(path):
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
    wb.save(path)
    return path


def test_save_results_writes_rich_remarks_and_strip_keeps_ai_block(tmp_path):
    path = _build_case_workbook(tmp_path / "case.xlsx")
    log_file = _write_log(tmp_path, "start camera\nframe rate 12fps\n")

    handler = ExcelHandler()
    handler.load(str(path))
    case = handler.test_cases[0]
    case.status = "Fail"
    case.ai_judged = True
    case.ai_status = "Fail"
    case.ai_confidence = 0.9
    case.ai_reason = "帧率低于预期"
    case.ai_evidence = ["frame rate 12fps"]
    case.log_file = log_file

    handler.save_results([case], str(path))
    ws = load_workbook(str(path), rich_text=True)["功能测试"]
    assert isinstance(ws["M15"].value, CellRichText)
    colored = _colored_texts(ws["M15"].value)
    assert any("12fps" in text for text in colored)

    # 下载结果选择“不含日志”时，富文本也能正常剥离日志段
    handler.load(str(path))
    handler.strip_log_from_remarks()
    stripped = handler.workbook["功能测试"]["M15"].value
    assert isinstance(stripped, str)
    assert "[AI判定] Fail" in stripped
    assert "--- 执行日志 ---" not in stripped
    assert "start camera" not in stripped


def test_load_colorizes_plain_remark_from_existing_result(tmp_path):
    """旧结果文件的纯文本备注在加载/下载时也能自动着色。"""
    path = _build_case_workbook(tmp_path / "case.xlsx")
    wb = load_workbook(str(path))
    wb["功能测试"]["M15"] = (
        "[AI判定] Fail (置信度=0.90)\n"
        "判定依据: 帧率低于预期\n"
        "- frame rate 12fps\n"
        "--- 执行日志 ---\n"
        "start camera\n"
        "frame rate 12fps\n"
        "other output\n"
    )
    wb.save(str(path))

    handler = ExcelHandler()
    handler.load(str(path))

    value = handler.workbook["功能测试"]["M15"].value
    assert isinstance(value, CellRichText)
    colored = _colored_texts(value)
    assert any("12fps" in text for text in colored)
    assert not any("start camera" in text for text in colored)
