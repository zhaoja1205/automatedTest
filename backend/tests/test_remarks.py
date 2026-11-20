"""备注 / BUG 列构建回归测试。

覆盖「重新判定」后板端日志与 AI 证据行保持可见的场景：
- 草稿恢复 / 历史导入的用例没有 log_file，日志只存在备注里；
- 重新判定会用 AI 字段重建备注，不能丢掉备注里的日志段。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND_DIR)

from app.core.remarks import (  # noqa: E402
    build_log_remark_from_case,
    build_remark_from_case,
    extract_log_section,
)
from app.core.test_case import TestCase as Case  # noqa: E402

LOG_TEXT = (
    "===== 终端A =====\n"
    "$ nvsipl_camera -c MIXGROUP_HQ\n"
    "nvsipl_camera: ERROR: Failed to create pipeline\n"
)


def _case_with_embedded_log() -> Case:
    """模拟草稿恢复 / 历史导入：日志在备注中，没有 log_file。"""
    return Case(
        case_id="CASE-001",
        case_key="Sheet1:2:CASE-001",
        remarks=f"--- 执行日志 ---\n{LOG_TEXT}",
    )


def test_rejudge_keeps_log_section_from_remarks_without_log_file():
    case = _case_with_embedded_log()
    assert case.log_file == ""

    # 模拟重新判定写回 AI 字段并重建合并备注
    case.status = "Pass"
    case.ai_judged = True
    case.ai_status = "Pass"
    case.ai_confidence = 0.91
    case.ai_reason = "输出包含失败日志但被判定为已处理"
    case.ai_evidence = ["nvsipl_camera: ERROR: Failed to create pipeline"]
    case.remarks = build_remark_from_case(case)

    log_section = extract_log_section(case.remarks)
    assert "--- 执行日志 ---" in case.remarks
    assert "nvsipl_camera: ERROR: Failed to create pipeline" in log_section
    # AI 证据行仍保留在备注中（前端日志弹窗据此高亮）
    assert "- nvsipl_camera: ERROR: Failed to create pipeline" in case.remarks

    # 再次重新判定（备注已是合并格式）仍不能丢日志
    case.remarks = build_remark_from_case(case)
    assert "Failed to create pipeline" in extract_log_section(case.remarks)


def test_rejudge_removes_old_ai_section_but_keeps_log():
    case = _case_with_embedded_log()
    case.remarks = (
        "[AI判定] Fail (置信度=0.70)\n"
        "判定依据: 旧判定\n"
        "- 旧证据\n"
        "--- 执行日志 ---\n"
        f"{LOG_TEXT}"
    )
    case.ai_judged = True
    case.ai_status = "Pass"
    case.ai_confidence = 0.95
    case.ai_reason = "新判定"
    case.ai_evidence = ["新证据"]
    case.remarks = build_remark_from_case(case)

    assert "[AI判定] Pass (置信度=0.95)" in case.remarks
    assert "旧判定" not in case.remarks
    assert "新证据" in case.remarks
    assert LOG_TEXT.strip() in extract_log_section(case.remarks)


def test_build_log_remark_uses_embedded_log_when_log_file_missing():
    case = _case_with_embedded_log()
    case.ai_judged = True
    case.ai_status = "Pass"
    case.ai_confidence = 0.9
    case.ai_reason = "已判定"
    case.ai_evidence = ["证据"]
    case.remarks = build_remark_from_case(case)

    # 下载结果 / 写 Excel 时备注列只应有日志，且不能因为 ai_judged 而清空
    remark = build_log_remark_from_case(case)
    assert remark.startswith("--- 执行日志 ---")
    assert LOG_TEXT.strip() in remark
    assert "[AI判定]" not in remark


def test_build_remark_prefers_log_file_when_available(tmp_path):
    log_file = tmp_path / "case.log"
    log_file.write_text(LOG_TEXT, encoding="utf-8")
    case = Case(
        case_id="CASE-002",
        case_key="Sheet1:3:CASE-002",
        log_file=str(log_file),
    )
    case.ai_judged = True
    case.ai_status = "Fail"
    case.ai_confidence = 0.8
    case.ai_reason = "失败"
    case.ai_evidence = ["ERROR: Failed to create pipeline"]
    case.remarks = build_remark_from_case(case)

    assert "Failed to create pipeline" in extract_log_section(case.remarks)
    assert build_log_remark_from_case(case).startswith("--- 执行日志 ---")
