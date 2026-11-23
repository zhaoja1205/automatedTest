"""用例导出：故障测试用例写入「故障测试」Sheet。"""
import asyncio
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND_DIR = _HERE.parent
sys.path.insert(0, str(_BACKEND_DIR))

from openpyxl import load_workbook  # noqa: E402

from app.api import casegen_routes  # noqa: E402
from app.api.casegen_routes import (  # noqa: E402
    FAULT_SHEET_NAME,
    FUNCTIONAL_SHEET_NAME,
    STABILITY_SHEET_NAME,
    STRESS_SHEET_NAME,
    ExportCasesRequest,
    _build_case_ids,
    _ensure_case_sheet,
    _is_fault_case,
    _partition_cases,
    _write_cases_to_sheet,
    export_generated_cases,
)

TEMPLATE = _HERE.parent.parent / "docs" / "case.xlsx"


def _copy_template(tmp_path: Path) -> Path:
    assert TEMPLATE.is_file(), f"模板不存在: {TEMPLATE}"
    path = tmp_path / "case_export.xlsx"
    shutil.copy2(TEMPLATE, path)
    return path


def _fault_case(no: int, name: str, code: str) -> dict:
    return {
        "key": f"fault-{no}",
        "test_type": "故障上报",
        "requirement_id": "PREDEV_024-R001",
        "description": f"{name}故障验证",
        "prerequisites": "板端已部署 i2c 工具与故障注入脚本",
        "steps": (
            "1、终端A输入命令起流\n"
            f"3、终端B输入./fault_simulation_728_qnx.sh -i 9 -a 4c -n {no} 注入故障\n"
            "5、终端B输入清除故障命令"
        ),
        "expected": f"1、执行命令正常起流,\n2、故障注入后能检测到{code}故障",
        "priority": "P1",
    }


def test_is_fault_case_by_test_type_and_sheet():
    assert _is_fault_case({"test_type": "故障上报"})
    assert _is_fault_case({"test_type": "fault test"})
    assert _is_fault_case({"sheet_name": FAULT_SHEET_NAME})
    # 未来新增的故障测试类型即使名称不含「故障」，也按 fault- 前缀归类
    assert _is_fault_case({"key": "fault-IMX728-1", "test_type": "异常恢复"})
    assert not _is_fault_case({"test_type": "功能测试"})
    assert not _is_fault_case({})


def test_partition_cases_routes_each_category():
    cases = [
        {"test_type": "功能测试"},
        {"test_type": "压力测试"},
        {"test_type": "稳定性测试"},
        {"test_type": "故障上报"},
        {"sheet_name": "故障测试"},
    ]

    functional, stress, stability, fault = _partition_cases(cases)

    assert len(functional) == 1
    assert len(stress) == 1
    assert len(stability) == 1
    assert len(fault) == 2
    # 故障用例不会同时被归入功能测试
    assert all(case not in functional for case in fault)


def test_write_fault_cases_to_template_sheet(tmp_path):
    path = _copy_template(tmp_path)
    wb = load_workbook(path)
    ws = _ensure_case_sheet(wb, FAULT_SHEET_NAME)

    cases = [
        _fault_case(1, "IMX728clock monitor", "CDI_SENSOR_CLK_ABNORMAL_ERR"),
        _fault_case(2, "IMX728Flash Check", "CDI_SENSOR_FLASH_CHECK_ERR"),
    ]
    case_ids = _build_case_ids(cases, prefix="FT", group_by_key=False)
    _write_cases_to_sheet(ws, cases, case_ids, {"owner": "张三"})

    target = tmp_path / "written.xlsx"
    wb.save(target)
    wb.close()

    wb2 = load_workbook(target)
    ws2 = wb2[FAULT_SHEET_NAME]
    rows = list(ws2.iter_rows(min_row=15, max_row=16, values_only=True))

    assert case_ids == ["FT_001_01", "FT_001_02"]
    # B=用例ID, C=测试类型, D=需求ID, E=描述, F=前置条件, G=步骤, H=预期结果, I=优先级
    assert rows[0][1] == "FT_001_01"
    assert rows[0][2] == "故障上报"
    assert rows[0][3] == "PREDEV_024-R001"
    assert rows[0][4] == "IMX728clock monitor故障验证"
    assert "CDI_SENSOR_CLK_ABNORMAL_ERR" in rows[0][7]
    assert rows[1][1] == "FT_001_02"
    assert "CDI_SENSOR_FLASH_CHECK_ERR" in rows[1][7]
    wb2.close()


def test_export_request_schema_accepts_fault_cases():
    req = ExportCasesRequest(
        platform_name="imx728",
        basic_info={"owner": "张三"},
        cases=[_fault_case(3, "IMX728power", "CDI_SENSOR_POWER_ERR")],
    )

    assert req.cases[0]["test_type"] == "故障上报"
    functional, stress, stability, fault = _partition_cases(req.cases)
    assert functional == stress == stability == []
    assert len(fault) == 1


def test_sheet_names_are_distinct():
    names = {
        FUNCTIONAL_SHEET_NAME,
        FAULT_SHEET_NAME,
        STRESS_SHEET_NAME,
        STABILITY_SHEET_NAME,
    }
    assert len(names) == 4


def test_export_route_puts_fault_cases_in_fault_sheet(tmp_path, monkeypatch):
    """端到端验证：故障用例导出后落在「故障测试」，不会写进「功能测试」。"""
    root = tmp_path / "proj"
    backend = root / "backend"
    docs = root / "docs"
    docs.mkdir(parents=True)
    backend.mkdir()
    shutil.copy2(TEMPLATE, docs / "case.xlsx")
    monkeypatch.setattr(casegen_routes, "_BACKEND_ROOT", str(backend))

    cases = [
        _fault_case(1, "IMX728clock monitor", "CDI_SENSOR_CLK_ABNORMAL_ERR"),
        _fault_case(2, "IMX728Flash Check", "CDI_SENSOR_FLASH_CHECK_ERR"),
    ]
    result = asyncio.run(
        export_generated_cases(
            ExportCasesRequest(
                platform_name="imx728", basic_info={}, cases=cases
            )
        )
    )

    assert result["functional_count"] == 0
    assert result["fault_count"] == 2

    wb = load_workbook(backend / "exports" / result["filename"])
    assert wb[FUNCTIONAL_SHEET_NAME]["B15"].value is None
    fault = wb[FAULT_SHEET_NAME]
    assert fault["B15"].value == "FT_001_01"
    assert fault["B16"].value == "FT_001_02"
    assert "CDI_SENSOR_CLK_ABNORMAL_ERR" in fault["H15"].value
    wb.close()
