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

class ExportCasesRequest(BaseModel):
    """导出用例请求体"""
    platform_name: str = ""
    basic_info: dict = {}
    cases: list[dict] = []


@router.post("/export-cases")
async def export_generated_cases(req: ExportCasesRequest):
    """将生成的测试用例导出为 Excel 文件，返回下载链接。

    策略：复制空白模板 case.xlsx，在「功能测试」Sheet 的数据区域逐行写入用例，
    其余 Sheet 保持不变。
    """
    from openpyxl import load_workbook
    from openpyxl.styles import Font, Alignment, Border, Side
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

    # 打开副本
    wb = load_workbook(dest_path)

    # 确保「功能测试」Sheet 存在
    if "功能测试" not in wb.sheetnames:
        ws_func = wb.create_sheet("功能测试")
    else:
        ws_func = wb["功能测试"]

    # 确定数据起始行（扫描最后一行表头位置）
    data_start = 15  # 默认
    for r in range(1, ws_func.max_row + 1):
        val = ws_func.cell(row=r, column=1).value
        if val and "测试用例ID" in str(val):
            data_start = r + 2  # 表头行 + 1 空行或直接下一行
            break

    # 写入用例数据
    today_str = datetime.now().strftime("%Y-%m-%d")
    tester = req.basic_info.get("owner", "")
    test_version = req.basic_info.get("test_version", "")
    software_version = req.basic_info.get("software_version", "")

    for idx, case in enumerate(req.cases):
        row = data_start + idx
        # B: 测试用例ID (自动生成 FT_XXX_XX)
        case_num = idx + 1
        case_id = f"FT_{case_num:03d}_01"
        ws_func.cell(row=row, column=2, value=case_id)

        # C: 测试类型
        ws_func.cell(row=row, column=3, value=case.get("test_type", "raw图"))

        # D: 需求ID (留空)
        ws_func.cell(row=row, column=4, value="")

        # E: 测试用例描述
        ws_func.cell(row=row, column=5, value=case.get("description", ""))

        # F: 前置条件
        ws_func.cell(row=row, column=6, value=case.get("prerequisites", ""))

        # G: 测试步骤
        ws_func.cell(row=row, column=7, value=case.get("steps", ""))

        # H: 预期结果
        ws_func.cell(row=row, column=8, value=case.get("expected", ""))

        # I: 优先级
        ws_func.cell(row=row, column=9, value=case.get("priority", "P1"))

        # J: 版本变更记录 (留空)
        ws_func.cell(row=row, column=10, value="")

        # K/L: Round1 - 实际结果 (NT)
        ws_func.cell(row=row, column=11, value="NT")

        # M: BUG
        ws_func.cell(row=row, column=12, value="")

        # N: 备注
        ws_func.cell(row=row, column=13, value="")

        # O: 测试版本
        ws_func.cell(row=row, column=14, value=test_version or software_version)

        # P: 实施者
        ws_func.cell(row=row, column=15, value=tester)

        # Q: 测试日期
        ws_func.cell(row=row, column=16, value=today_str)

    # 刷新数据统计区域的公式引用（可选：简单做法是保留原公式不动）
    # 保存
    wb.save(dest_path)
    wb.close()

    # 返回下载 URL
    filename = os.path.basename(dest_path)
    download_url = f"/api/casegen/download/{filename}"

    return {
        "message": f"已生成 {len(req.cases)} 条用例",
        "download_url": download_url,
        "filename": filename,
        "case_count": len(req.cases),
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
