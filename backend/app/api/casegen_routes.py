"""
生成测试用例模块 API 路由。

当前提供平台配置文件（predev_mixgroup_platform.json）的读取与解析，
用于第二步选择平台配置并推导硬件拓扑。
"""
import json
import os
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

# 配置文件路径为相对路径时，相对于 backend/ 目录解析
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_MAX_CONFIG_BYTES = 5 * 1024 * 1024


class ParsePlatformConfigRequest(BaseModel):
    path: str


def _index_letter(index: int) -> str:
    return chr(ord("A") + index) if 0 <= index < 26 else str(index)


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _parse_camera(camera: dict, fallback_index: int) -> dict:
    link_index = camera.get("linkIndex", fallback_index)
    try:
        link_index = int(link_index)
    except (TypeError, ValueError):
        link_index = fallback_index

    serializers = _as_list(camera.get("serializers"))
    serializer = camera.get("serializer") or (serializers[0] if serializers else {})
    sensors = _as_list(camera.get("sensors"))
    sensor = sensors[0] if sensors else {}

    mask_bit = f"0x{1 << (link_index * 4):x}" if 0 <= link_index < 4 else ""

    return {
        "link_index": link_index,
        "module": camera.get("name", "") or "",
        "serializer": serializer.get("name", "") or "",
        "serializer_i2c": serializer.get("i2cAddress", "") or "",
        "serializer_virtual_i2c": serializer.get("virtualI2CAddress", "") or "",
        "sensor": sensor.get("name", "") or "",
        "sensor_i2c": sensor.get("virtualI2CAddress", "") or "",
        "sensor_id": sensor.get("id"),
        "mask_bit": mask_bit,
    }


def _parse_platform_config(config: dict, index: int) -> dict:
    """把单个 platformConfig 归一化为前端易用的结构。"""
    enable_masks = _as_list(config.get("enableMasks") or config.get("enable_masks"))
    blocks = _as_list(config.get("deviceBlocks") or config.get("device_blocks"))

    groups = []
    topology = []
    for block_index, block in enumerate(blocks):
        group = _index_letter(block_index)
        mask = enable_masks[block_index] if block_index < len(enable_masks) else ""
        cameras = [
            _parse_camera(camera, ci)
            for ci, camera in enumerate(
                _as_list(block.get("cameraModules") or block.get("camera_modules"))
            )
            if isinstance(camera, dict)
        ]
        group_info = {
            "group_index": block_index,
            "group": group,
            "enable_mask": mask,
            "csi_port": block.get("csiPort", "") or "",
            "phy_mode": block.get("phyMode", "") or "",
            "deserializer": block.get("deserializer", "") or "",
            "simulator_mode": bool(block.get("simulatorMode", False)),
            "passive_mode": bool(block.get("passiveMode", False)),
            "homogenous_modules": bool(block.get("homogenousModules", False)),
            "group_init_prog": bool(block.get("groupInitProg", False)),
            "cameras": cameras,
        }
        groups.append(group_info)
        for camera in cameras:
            topology.append({
                "group": group,
                "group_index": block_index,
                "group_mask": mask,
                "csi_port": group_info["csi_port"],
                "phy_mode": group_info["phy_mode"],
                "deserializer": group_info["deserializer"],
                **camera,
            })

    return {
        "name": config.get("name", "") or f"platform_{index}",
        "description": config.get("description", "") or "",
        "enable_masks": enable_masks,
        "group_count": len(groups),
        "module_count": len(topology),
        "groups": groups,
        "topology": topology,
    }


def _resolve_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="请提供配置文件路径")
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(_BACKEND_ROOT, path)
    path = os.path.abspath(path)

    if not path.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="仅支持读取 .json 配置文件")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"配置文件不存在: {path}")
    if os.path.getsize(path) > _MAX_CONFIG_BYTES:
        raise HTTPException(status_code=400, detail="配置文件超过 5MB，已拒绝读取")
    return path


@router.post("/platform-config/parse")
async def parse_platform_config(req: ParsePlatformConfigRequest):
    """读取并解析平台配置文件，返回全部 platformConfigs 及其硬件拓扑。"""
    path = _resolve_path(req.path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"配置文件不是合法 JSON: {exc}")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取配置文件失败: {exc}")

    configs = raw.get("platformConfigs") or raw.get("platform_configs")
    if not isinstance(configs, list) or not configs:
        raise HTTPException(
            status_code=400,
            detail="配置文件中未找到 platformConfigs 数组",
        )

    parsed = [
        _parse_platform_config(config, index)
        for index, config in enumerate(configs)
        if isinstance(config, dict)
    ]
    if not parsed:
        raise HTTPException(status_code=400, detail="platformConfigs 中没有有效配置项")

    return {
        "path": path,
        "file_name": os.path.basename(path),
        "platform_configs": parsed,
    }


# ============================================================================
# Sensor 配置：读取 imageSensors 数据库（如 predev_mixgroup/imx623.json）
# ============================================================================

class ParseSensorConfigRequest(BaseModel):
    """Sensor 配置读取请求，paths 可一次传入多个文件。"""
    paths: list[str] = []


def _to_int(value, default=None) -> Optional[int]:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=None) -> Optional[float]:
    try:
        if isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_virtual_channel(channel: dict, index: int) -> dict:
    """把单个 virtualChannel 归一化为前端易用的结构。"""
    return {
        "index": index,
        "cfa": channel.get("cfa", "") or "",
        "embedded_top_lines": _to_int(channel.get("embeddedTopLines")),
        "embedded_bottom_lines": _to_int(channel.get("embeddedBottomLines")),
        "input_format": channel.get("inputFormat", "") or "",
        "width": _to_int(channel.get("width")),
        "height": _to_int(channel.get("height")),
        "fps": _to_float(channel.get("fps")),
        "embedded_data_type_enabled": bool(channel.get("isEmbeddedDataTypeEnabled", False)),
    }


def _parse_image_sensor(sensor: dict, index: int, path: str, file_name: str) -> dict:
    """把 imageSensors 中的一项归一化。"""
    channels = [
        _parse_virtual_channel(channel, channel_index)
        for channel_index, channel in enumerate(
            _as_list(sensor.get("virtualChannels") or sensor.get("virtual_channels"))
        )
        if isinstance(channel, dict)
    ]
    return {
        "name": sensor.get("name", "") or "",
        "description": sensor.get("description", "") or "",
        "i2c_address": sensor.get("i2cAddress", "") or sensor.get("i2c_address", "") or "",
        "virtual_channels": channels,
        "trigger_mode_enabled": bool(sensor.get("isTriggerModeEnabled", False)),
        "tpg_enabled": bool(sensor.get("isTPGEnabled", False)),
        "use_cdi_v2_api": bool(sensor.get("useCDIv2API", False)),
        "sensor_index": index,
        "source_path": path,
        "source_file": file_name,
    }


def _read_sensor_file(path: str) -> dict:
    """读取一个 sensor 配置文件，返回文件信息与其包含的全部 imageSensor。"""
    resolved = _resolve_path(path)
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"配置文件不是合法 JSON: {exc}")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"读取配置文件失败: {exc}")

    file_name = os.path.basename(resolved)
    if isinstance(raw, list):
        sensors_raw = raw
    elif isinstance(raw, dict):
        sensors_raw = raw.get("imageSensors") or raw.get("image_sensors")
    else:
        sensors_raw = None

    if not isinstance(sensors_raw, list) or not sensors_raw:
        raise HTTPException(
            status_code=400,
            detail=f"{file_name} 中未找到 imageSensors 数组",
        )

    sensors = [
        _parse_image_sensor(sensor, index, resolved, file_name)
        for index, sensor in enumerate(sensors_raw)
        if isinstance(sensor, dict)
    ]
    if not sensors:
        raise HTTPException(status_code=400, detail=f"{file_name} 的 imageSensors 中没有有效配置项")

    return {
        "path": resolved,
        "file_name": file_name,
        "sensors": sensors,
    }


@router.post("/sensor-config/parse")
async def parse_sensor_config(req: ParseSensorConfigRequest):
    """读取并解析一个或多个 sensor 配置文件，返回文件列表与扁平的 sensor 列表。

    Sensor 配置为可选内容（允许 0 个），读取结果供后续功能测试步骤生成用例时使用。
    """
    paths = [p.strip() for p in req.paths if isinstance(p, str) and p.strip()]
    if not paths:
        raise HTTPException(status_code=400, detail="请提供至少一个 sensor 配置文件路径")

    # 去重但保持传入顺序
    unique_paths = list(dict.fromkeys(os.path.expanduser(p) for p in paths))
    files = [_read_sensor_file(p) for p in unique_paths]
    sensors = [sensor for file in files for sensor in file["sensors"]]

    return {
        "files": files,
        "sensors": sensors,
    }


# ============================================================================
# 导出阶段：将生成的用例写入 Excel 并返回下载
# ============================================================================

def _template_last_formatted_row(ws, first_row: int, last_col: int) -> int:
    """返回模板中最后一个画有边框的表格数据行。

    模板 case.xlsx 的「功能测试」Sheet 只预先绘制了固定行数的表格线，
    需要识别该区域，用例超出行数时才能按同样的样式向下扩展。
    """
    last = first_row - 1
    for row in range(first_row, ws.max_row + 1):
        for col in range(1, last_col + 1):
            border = ws.cell(row=row, column=col).border
            if any(side.style for side in (border.left, border.right, border.top, border.bottom)):
                last = row
                break
    return last


def _copy_row_style(ws, source_row: int, target_row: int, first_col: int, last_col: int, height=None):
    """把模板数据行的单元格样式（字体/边框/对齐/换行等）复制到新行。"""
    from copy import copy

    for col in range(first_col, last_col + 1):
        src = ws.cell(row=source_row, column=col)
        dst = ws.cell(row=target_row, column=col)
        if src.has_style:
            dst._style = copy(src._style)
    if height is not None:
        ws.row_dimensions[target_row].height = height


def _camera_key(case: dict) -> str:
    """提取用例所属相机的唯一标识。

    前端 ``GeneratedCase.key`` 形如 ``<测试类型>-<group_index>-<link_index>-<拓扑行号>``，
    去掉测试类型前缀后的部分即可区分同一台相机；没有 key 时退回按
    Group / linkIndex / 模组 / sensor 组合判断。
    """
    key = str(case.get("key") or "")
    if "-" in key:
        return key.split("-", 1)[1]
    return "|".join(
        str(case.get(field, "")) for field in ("group", "link_index", "module", "sensor_id")
    )


def _build_case_ids(cases: list[dict], prefix: str = "FT") -> list[str]:
    """按相机（或压力测试相机组合）分组生成测试用例编号。

    同一相机/组合的多条用例共用第一段编号，第二段依次递增：
    FT_001_01、FT_001_02 …；下一台相机为 FT_002_01、FT_002_02 …
    压力测试使用 ST 前缀。
    """
    camera_numbers: dict[str, int] = {}
    camera_sequences: dict[str, int] = {}
    case_ids: list[str] = []

    for case in cases:
        camera_key = _camera_key(case)
        if camera_key not in camera_numbers:
            camera_numbers[camera_key] = len(camera_numbers) + 1
            camera_sequences[camera_key] = 0
        camera_sequences[camera_key] += 1
        case_ids.append(
            f"{prefix}_{camera_numbers[camera_key]:03d}_{camera_sequences[camera_key]:02d}"
        )

    return case_ids


# 导出目标 Sheet 与用例表头列名映射
FUNCTIONAL_SHEET_NAME = "功能测试"
STRESS_SHEET_NAME = "压力测试"

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "case_id": ("测试用例id",),
    "test_type": ("测试类型",),
    "description": ("测试用例描述",),
    "prerequisites": ("前置条件",),
    "steps": ("测试步骤",),
    "expected": ("预期结果",),
    "priority": ("优先级",),
    "status": ("实际结果",),
    "bug": ("bug",),
    "remarks": ("备注",),
    "test_version": ("测试版本",),
    "tester": ("实施者", "测试人员"),
    "test_date": ("测试日期",),
}

_FALLBACK_HEADERS = (
    "测试用例ID", "测试类型", "测试用例描述", "前置条件", "测试步骤",
    "预期结果", "优先级", "实际结果", "BUG", "备注", "测试版本",
    "实施者", "测试日期",
)


def _is_stress_case(case: dict) -> bool:
    """判断用例应写入「压力测试」Sheet。"""
    if str(case.get("sheet_name") or "").strip() == STRESS_SHEET_NAME:
        return True
    test_type = str(case.get("test_type") or "")
    return "压力" in test_type or "stress" in test_type.lower()


def _ensure_case_sheet(wb, sheet_name: str):
    """获取用例 Sheet；模板缺少该 Sheet 时创建一个最小可用表头。"""
    if sheet_name in wb.sheetnames:
        return wb[sheet_name]
    ws = wb.create_sheet(sheet_name)
    for column, title in enumerate(_FALLBACK_HEADERS, start=1):
        ws.cell(row=1, column=column, value=title)
    return ws


def _find_data_location(ws) -> tuple[int, int]:
    """返回 (数据起始行, 表头行)。

    模板表头为两行（合并单元格），数据从「测试用例ID」所在行的下两行开始。
    """
    for row in range(1, min(ws.max_row, 60) + 1):
        for column in range(1, ws.max_column + 1):
            value = ws.cell(row=row, column=column).value
            if value and "测试用例ID" in str(value):
                return row + 2, row
    return 15, 13


def _normalize_header(value) -> str:
    return str(value or "").strip().lower().replace(" ", "")


def _detect_column_map(ws, header_row: int) -> dict[str, int]:
    """根据表头文本识别各字段所在列，兼容「功能测试」与「压力测试」不同列布局。"""
    mapping: dict[str, int] = {}
    for row in (header_row, header_row + 1):
        for column in range(1, ws.max_column + 1):
            header = _normalize_header(ws.cell(row=row, column=column).value)
            if not header:
                continue
            for field, aliases in _COLUMN_ALIASES.items():
                if field in mapping:
                    continue
                if any(header.startswith(alias.replace(" ", "")) for alias in aliases):
                    mapping[field] = column
    return mapping


def _update_stat_formulas(ws, data_start: int, data_end: int, mapping: dict[str, int]):
    """把顶部 Total / Pass / Fail … 统计公式覆盖到本次写入的数据区。"""
    from openpyxl.utils import get_column_letter

    case_id_col = mapping.get("case_id")
    status_col = mapping.get("status")
    if not case_id_col or not status_col:
        return

    total_label = None
    for row in range(1, data_start):
        for column in range(1, ws.max_column + 1):
            value = ws.cell(row=row, column=column).value
            if str(value or "").strip() == "Total":
                total_label = ws.cell(row=row, column=column)
                break
        if total_label is not None:
            break
    if total_label is None:
        return

    id_letter = get_column_letter(case_id_col)
    status_letter = get_column_letter(status_col)
    ws.cell(
        row=total_label.row,
        column=total_label.column + 1,
        value=f"=COUNTA({id_letter}{data_start}:{id_letter}{data_end})",
    )

    label_col = total_label.column
    for row in range(1, data_start):
        label = str(ws.cell(row=row, column=label_col).value or "").strip()
        if label in {"Pass", "Fail", "NT", "BLOCK", "NA"}:
            ws.cell(
                row=row,
                column=label_col + 1,
                value=(
                    f"=COUNTIF({status_letter}{data_start}:{status_letter}{data_end},"
                    f"{ws.cell(row=row, column=label_col).coordinate})"
                ),
            )


def _update_auto_filter(ws, header_row: int, data_end: int, last_col: int, first_col: int):
    """自动筛选区域随数据行向下延伸（不缩小原有范围）。"""
    from openpyxl.utils import get_column_letter, range_boundaries

    if ws.auto_filter.ref:
        min_col, min_row, max_col, max_row = range_boundaries(ws.auto_filter.ref)
        max_row = max(max_row, data_end)
        ws.auto_filter.ref = (
            f"{get_column_letter(min_col)}{min_row}:{get_column_letter(max_col)}{max_row}"
        )
    else:
        ws.auto_filter.ref = (
            f"{get_column_letter(first_col)}{header_row}:"
            f"{get_column_letter(last_col)}{data_end}"
        )


def _write_cases_to_sheet(
    ws,
    cases: list[dict],
    case_ids: list[str],
    basic_info: dict,
) -> None:
    """按目标 Sheet 的实际列布局写入用例数据，并扩展样式 / 统计公式。"""
    from datetime import datetime

    data_start, header_row = _find_data_location(ws)
    mapping = _detect_column_map(ws, header_row)
    if not mapping:
        raise HTTPException(status_code=500, detail=f"{ws.title} 表头无法识别，导出失败")

    today_str = datetime.now().strftime("%Y-%m-%d")
    tester = basic_info.get("owner", "")
    test_version = basic_info.get("test_version", "")
    software_version = basic_info.get("software_version", "")

    for idx, case in enumerate(cases):
        row = data_start + idx
        static_values = {
            "case_id": case_ids[idx],
            "test_type": case.get("test_type", ""),
            "description": case.get("description", ""),
            "prerequisites": case.get("prerequisites", ""),
            "steps": case.get("steps", ""),
            "expected": case.get("expected", ""),
            "priority": case.get("priority", "P1"),
            "status": "NT",
            "bug": "",
            "remarks": "",
            "test_version": test_version or software_version,
            "tester": tester,
            "test_date": today_str,
        }
        for field, column in mapping.items():
            value = static_values.get(field, "")
            ws.cell(row=row, column=column, value=value)

    data_end = data_start + len(cases) - 1
    first_col = min(mapping.values())
    last_col = max(mapping.values())

    # 用例数超过模板预先画好的数据行时，沿用模板样式向下扩展
    template_last_row = _template_last_formatted_row(ws, data_start, last_col=last_col)
    if data_end > template_last_row:
        row_height = ws.row_dimensions[data_start].height
        for row in range(template_last_row + 1, data_end + 1):
            _copy_row_style(ws, data_start, row, first_col, last_col, row_height)

    _update_stat_formulas(ws, data_start, data_end, mapping)
    _update_auto_filter(ws, header_row, data_end, last_col, first_col)


class ExportCasesRequest(BaseModel):
    """导出用例请求体"""
    platform_name: str = ""
    basic_info: dict = {}
    cases: list[dict] = []


@router.post("/export-cases")
async def export_generated_cases(req: ExportCasesRequest):
    """将生成的测试用例导出为 Excel 文件，返回下载链接。

    策略：复制空白模板 case.xlsx，按用例类型分别写入对应 Sheet：
    - 普通功能测试 → 「功能测试」
    - 压力测试 → 「压力测试」

    模板的数据表格只预先画好了固定行数，用例数量超出模板行数时，
    会复制表格样式向下扩展数据行、延长自动筛选范围，并同步更新统计公式，
    保证导出的表格不会在超出行数后失去边框或统计不准确。
    """
    from openpyxl import load_workbook
    from datetime import datetime
    import shutil

    if not req.cases:
        raise HTTPException(status_code=400, detail="没有可导出的用例")

    PROJECT_ROOT = os.path.dirname(_BACKEND_ROOT)
    template_path = os.path.join(PROJECT_ROOT, "docs", "case.xlsx")
    if not os.path.isfile(template_path):
        raise HTTPException(status_code=500, detail=f"模板文件不存在: {template_path}")

    # 创建临时副本
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir = os.path.join(_BACKEND_ROOT, "exports")
    os.makedirs(export_dir, exist_ok=True)
    base_name = (req.platform_name or "cases").replace("/", "_")
    dest_path = os.path.join(export_dir, f"{base_name}_{timestamp}.xlsx")
    shutil.copy2(template_path, dest_path)

    wb = load_workbook(dest_path)

    functional_cases = [case for case in req.cases if not _is_stress_case(case)]
    stress_cases = [case for case in req.cases if _is_stress_case(case)]

    if functional_cases:
        ws = _ensure_case_sheet(wb, FUNCTIONAL_SHEET_NAME)
        case_ids = _build_case_ids(functional_cases, prefix="FT")
        _write_cases_to_sheet(ws, functional_cases, case_ids, req.basic_info)

    if stress_cases:
        ws = _ensure_case_sheet(wb, STRESS_SHEET_NAME)
        case_ids = _build_case_ids(stress_cases, prefix="ST")
        _write_cases_to_sheet(ws, stress_cases, case_ids, req.basic_info)

    wb.save(dest_path)
    wb.close()

    # 返回下载 URL
    filename = os.path.basename(dest_path)
    download_url = f"/api/casegen/download/{filename}"

    return {
        "message": (
            f"已生成 {len(req.cases)} 条用例"
            f"（功能测试 {len(functional_cases)} 条 / 压力测试 {len(stress_cases)} 条）"
        ),
        "download_url": download_url,
        "filename": filename,
        "case_count": len(req.cases),
        "functional_count": len(functional_cases),
        "stress_count": len(stress_cases),
    }


@router.get("/download/{filename}")
async def download_exported_file(filename: str):
    """下载已导出的 Excel 文件"""
    export_dir = os.path.join(_BACKEND_ROOT, "exports")
    file_path = os.path.join(export_dir, filename)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    from fastapi.responses import FileResponse
    from urllib.parse import quote
    encoded = quote(filename)
    return FileResponse(
        file_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )
