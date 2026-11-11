"""测试用例合并：来源用例追加到主用例。"""
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND_DIR = _HERE.parent
sys.path.insert(0, str(_BACKEND_DIR))

from openpyxl import load_workbook  # noqa: E402

from app.core.case_merger import CaseMerger  # noqa: E402

TEMPLATE = _HERE.parent.parent / "docs" / "case.xlsx"


def _copy_template(tmp_path: Path, name: str) -> Path:
    assert TEMPLATE.is_file(), f"模板不存在: {TEMPLATE}"
    path = tmp_path / name
    shutil.copy2(TEMPLATE, path)
    return path


def _fill_cases(path: Path, sheet_name: str, rows, start_row: int = 15):
    """按 case.xlsx 布局写入用例：B=用例ID, C=类型, D=需求ID, E=描述,
    F=前置条件, G=步骤, H=预期结果, I=优先级。"""
    wb = load_workbook(path)
    ws = wb[sheet_name]
    for offset, data in enumerate(rows):
        row = start_row + offset
        for col, value in enumerate(data, start=2):
            ws.cell(row=row, column=col, value=value)
    wb.save(path)


FUNCTIONAL_ROWS = [
    ("FT_001_01", "功能测试", "REQ-1", "RAW 出图", "硬件连接正确",
     'sudo nvsipl_camera -c "plat" -m "0x0001" -1 -2 -R -0 -s', "30fps 稳定出图", "P1"),
    ("FT_001_02", "功能测试", "REQ-1", "YUV 出图", "硬件连接正确",
     'sudo nvsipl_camera -c "plat" -m "0x0001" -1 -2 -s', "图片无明显异常", "P1"),
    ("FT_002_01", "功能测试", "REQ-2", "帧率测试", "硬件连接正确",
     'sudo nvsipl_camera -c "plat" -m "0x0001" -1 -2 -R -0 -s --showfps',
     "帧率在 [28,32]", "P2"),
]

FAULT_ROWS = [
    ("FT_003_01", "故障测试", "REQ-3", "解串器故障诊断", "硬件连接正确",
     "注入故障后读取寄存器", "故障位被拉低", "P1"),
]


def test_preview_lists_source_cases(tmp_path):
    main = _copy_template(tmp_path, "main.xlsx")
    source = _copy_template(tmp_path, "source.xlsx")
    _fill_cases(source, "功能测试", FUNCTIONAL_ROWS)
    _fill_cases(source, "故障测试", FAULT_ROWS)

    preview = CaseMerger().preview(str(main), str(source))

    assert [s["name"] for s in preview["main_sheets"]][:2] == ["功能测试", "故障测试"]
    functional = [c for c in preview["cases"] if c["source_sheet"] == "功能测试"]
    assert len(functional) == 3
    assert functional[0]["case_key"] == "功能测试:15:FT_001_01"
    assert functional[0]["description"] == "RAW 出图"
    assert functional[0]["target_sheet"] == "功能测试"
    fault = [c for c in preview["cases"] if c["source_sheet"] == "故障测试"]
    assert len(fault) == 1
    assert fault[0]["explicit_id"] == "FT_003_01"


def test_merge_appends_selected_cases_and_keeps_results_empty(tmp_path):
    main = _copy_template(tmp_path, "main.xlsx")
    source = _copy_template(tmp_path, "source.xlsx")
    _fill_cases(source, "功能测试", FUNCTIONAL_ROWS)
    _fill_cases(source, "故障测试", FAULT_ROWS)

    preview = CaseMerger().preview(str(main), str(source))
    selected = [
        c["case_key"] for c in preview["cases"]
        if c["description"] in ("RAW 出图", "帧率测试", "解串器故障诊断")
    ]

    out = tmp_path / "merged.xlsx"
    result = CaseMerger().merge(
        str(main), str(source), selected, str(out), skip_duplicates=True
    )
    assert result["merged_count"] == 3
    assert result["sheet_counts"] == {"功能测试": 2, "故障测试": 1}
    assert result["skipped_duplicates"] == []

    wb = load_workbook(out)
    ws = wb["功能测试"]
    assert ws["B15"].value == "FT_001_01"
    assert ws["E15"].value == "RAW 出图"
    assert ws["G15"].value.startswith("sudo nvsipl_camera")
    assert ws["B16"].value == "FT_002_01"
    # 默认不复制来源的执行结果列
    assert ws["K15"].value in (None, "")
    fault = wb["故障测试"]
    assert fault["B15"].value == "FT_003_01"
    assert fault["E15"].value == "解串器故障诊断"


def test_merge_skips_duplicate_case_ids(tmp_path):
    main = _copy_template(tmp_path, "main.xlsx")
    source = _copy_template(tmp_path, "source.xlsx")
    _fill_cases(source, "功能测试", FUNCTIONAL_ROWS)

    preview = CaseMerger().preview(str(main), str(source))
    keys = [c["case_key"] for c in preview["cases"]]

    merged_once = tmp_path / "merged_once.xlsx"
    first = CaseMerger().merge(str(main), str(source), keys[:1], str(merged_once))
    assert first["merged_count"] == 1

    merged_twice = tmp_path / "merged_twice.xlsx"
    second = CaseMerger().merge(
        str(merged_once), str(source), keys[:2], str(merged_twice),
        skip_duplicates=True,
    )
    assert second["merged_count"] == 1
    assert second["skipped_duplicates"] == ["功能测试:15:FT_001_01"]

    wb = load_workbook(merged_twice)
    ws = wb["功能测试"]
    ids = [ws.cell(row=r, column=2).value for r in (15, 16)]
    assert ids == ["FT_001_01", "FT_001_02"]


def test_merge_creates_sheet_when_target_category_missing(tmp_path):
    main = _copy_template(tmp_path, "main.xlsx")
    source = _copy_template(tmp_path, "source.xlsx")
    # 把来源「功能测试」改名为主用例中不存在的类别表
    wb = load_workbook(source)
    wb["功能测试"].title = "异常测试"
    wb.save(source)
    _fill_cases(source, "异常测试", FUNCTIONAL_ROWS[:1])

    preview = CaseMerger().preview(str(main), str(source))
    target = preview["cases"][0]["target_sheet"]
    assert target == "异常测试"
    abnormal_sheets = [s for s in preview["source_sheets"] if s["name"] == "异常测试"]
    assert abnormal_sheets and abnormal_sheets[0]["target_sheet"] == ""

    out = tmp_path / "merged.xlsx"
    result = CaseMerger().merge(
        str(main), str(source), [preview["cases"][0]["case_key"]], str(out)
    )
    assert result["created_sheets"] == ["异常测试"]
    wb_out = load_workbook(out)
    assert "异常测试" in wb_out.sheetnames
    ws = wb_out["异常测试"]
    assert ws["B13"].value == "测试用例ID"
    assert ws["B15"].value == "FT_001_01"


def test_stat_formula_range_extended_after_merge(tmp_path):
    main = _copy_template(tmp_path, "main.xlsx")
    source = _copy_template(tmp_path, "source.xlsx")
    _fill_cases(source, "功能测试", FUNCTIONAL_ROWS)

    # 主用例先填满模板公式覆盖的行数（B15:B194），合并后应自动延长到 195+
    many = [
        (f"OLD_{i:03d}", "功能测试", "", f"旧用例 {i}", "", "", "", "")
        for i in range(195 - 15 + 1)
    ]
    _fill_cases(main, "功能测试", many)

    preview = CaseMerger().preview(str(main), str(source))
    out = tmp_path / "merged.xlsx"
    result = CaseMerger().merge(
        str(main), str(source), [preview["cases"][0]["case_key"]], str(out)
    )
    assert result["merged_count"] == 1

    ws = load_workbook(out)["功能测试"]
    # Total 的 COUNTA 范围随新数据行延长；COUNTIF 原本已覆盖到 930，无需改动
    assert ws["C4"].value == "=COUNTA(B15:B196)"
