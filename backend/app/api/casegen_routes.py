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
