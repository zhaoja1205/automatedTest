"""SWE.2 §3.3.3 配置文件章节 — query/database 目录解析。

与 `config_db_scanner.discover_query_dirs` 配套：scanner 负责发现候选目录，
本模块负责把一个目录里的 JSON 解析成 `ConfigDatabase` dict（schema 见
`app.schemas.aspice.swe2_schema.ConfigDatabase`）。

设计：**尽量宽松、永不抛**。
- 真实 NV SIPL 工程里，database 目录命名风格两套都存在：
    A) IM_imx728x96717/ 下文件名 `<platform>.json` 兼做 cameraModules 载体，
       另有 `<platform>_platform.json` 存 deviceBlocks，sensor/eeprom 单文件
       （`imx728.json` / `m24128.json`），没有 cryptoConfig.json。
    B) sc233at/ 下有 `sc233at_platform.json` / `sc233at_cameramodules.json`
       / `sc233at_sensor.json` / `sc233at_serializer.json`，也无 cryptoConfig.json。
- 解析规则 → 用顶层键识别而不是文件名：
    * `platformConfigs` → 认作 platform 源
    * `cameraModules`   → 认作 modules 源
    * `imageSensors`    → 认作 sensor 源
    * `eeproms`         → 认作 eeprom 源
    * `cryptoConfig` / `cryptoKeys` → crypto 源（预留）
  一个 JSON 里允许同时命中多个键（IM_imx728x96717 把 modules 和没放 platform 的
  那份合在一起）。

安全：所有路径都收敛到 `engineering_root(project_id)` 内，走 realpath 比对，
拒绝 `..` 逃逸；JSON 读文件大小上限 2 MB（单文件），目录内只读 `*.json`。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from app.core import engineering_store

logger = logging.getLogger(__name__)


# 单个 JSON 读取上限（防御异常工程把 20 MB 的东西塞进来）
_MAX_JSON_BYTES = 2 * 1024 * 1024


def _safe_read_json(path: Path) -> Optional[dict]:
    """读 JSON，失败/过大一律返回 None，不抛。"""
    try:
        st = path.stat()
    except OSError:
        return None
    if st.st_size > _MAX_JSON_BYTES:
        logger.warning("config_db_parser: skip oversize %s (%d bytes)", path, st.st_size)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.debug("config_db_parser: skip unreadable %s: %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def _list_jsons(dir_path: Path) -> list[Path]:
    """目录内仅 `*.json` 普通文件（不递归，忽略子目录）。"""
    out: list[Path] = []
    try:
        for name in sorted(os.listdir(dir_path)):
            if not name.lower().endswith(".json"):
                continue
            p = dir_path / name
            if p.is_file():
                out.append(p)
    except OSError:
        pass
    return out


# ---------- 子解析器 ----------


def _parse_platform(doc: dict) -> Optional[dict]:
    """从 `platformConfigs` 抽第一个条目；多条取第一条，其余并入 device_blocks 之外的信息忽略。

    返回 ConfigDbPlatform dict，字段齐空也返回（便于前端显示"已识别"）。
    """
    plats = doc.get("platformConfigs")
    if not isinstance(plats, list) or not plats:
        return None
    first = plats[0] if isinstance(plats[0], dict) else {}
    blocks: list[dict] = []
    for b in first.get("deviceBlocks") or []:
        if not isinstance(b, dict):
            continue
        cams: list[str] = []
        i2c_addrs: list[str] = []
        for cm in b.get("cameraModules") or []:
            if isinstance(cm, dict):
                n = cm.get("name")
                if isinstance(n, str) and n:
                    cams.append(n)
                # cameraModule 本身在 platform JSON 里通常不带 i2c，留给 cameramodules.json
        blocks.append({
            "csi_port": str(b.get("csiPort") or ""),
            "phy_mode": str(b.get("phyMode") or ""),
            "deserializer": str(b.get("deserializer") or ""),
            "camera_modules": cams,
            "i2c_addresses": i2c_addrs,
        })
    return {
        "name": str(first.get("name") or ""),
        "description": str(first.get("description") or ""),
        "device_blocks": blocks,
    }


def _parse_modules(doc: dict) -> list[dict]:
    """从顶层 `cameraModules` 抽模块列表。"""
    cams = doc.get("cameraModules")
    if not isinstance(cams, list):
        return []
    out: list[dict] = []
    for cm in cams:
        if not isinstance(cm, dict):
            continue
        ser = ""
        s = cm.get("serializer")
        if isinstance(s, dict):
            ser = str(s.get("name") or "")
        elif isinstance(s, str):
            ser = s
        sensors: list[str] = []
        for sn in cm.get("sensors") or []:
            if isinstance(sn, dict):
                nm = sn.get("name")
                if isinstance(nm, str) and nm:
                    sensors.append(nm)
            elif isinstance(sn, str):
                sensors.append(sn)
        eeproms: list[str] = []
        for ep in cm.get("eeproms") or []:
            if isinstance(ep, dict):
                nm = ep.get("name")
                if isinstance(nm, str) and nm:
                    eeproms.append(nm)
            elif isinstance(ep, str):
                eeproms.append(ep)
        out.append({
            "name": str(cm.get("name") or ""),
            "description": str(cm.get("description") or ""),
            "serializer": ser,
            "sensors": sensors,
            "eeproms": eeproms,
        })
    return out


def _flatten_virtual_channel_fields(vc: dict) -> list[dict]:
    """把 virtualChannel 里的键值平铺成 fields 行（供 ConfigDbSensorField 列表用）。"""
    rows: list[dict] = []
    for k, v in vc.items():
        rows.append({
            "key": f"vc.{k}",
            "value": "" if v is None else (str(v) if not isinstance(v, (list, dict)) else json.dumps(v, ensure_ascii=False)),
            "note": "",
        })
    return rows


def _parse_sensors(doc: dict) -> list[dict]:
    """从顶层 `imageSensors` 抽传感器列表 + 扁平 fields。"""
    imgs = doc.get("imageSensors")
    if not isinstance(imgs, list):
        return []
    out: list[dict] = []
    for s in imgs:
        if not isinstance(s, dict):
            continue
        fields: list[dict] = []
        # 顶层标量键 → fields
        for k, v in s.items():
            if k in ("name", "description", "i2cAddress", "virtualChannels"):
                continue
            if isinstance(v, (list, dict)):
                continue
            fields.append({"key": k, "value": "" if v is None else str(v), "note": ""})
        # 第一个 virtualChannel 的键展成 vc.*
        vcs = s.get("virtualChannels")
        if isinstance(vcs, list) and vcs and isinstance(vcs[0], dict):
            fields.extend(_flatten_virtual_channel_fields(vcs[0]))
        out.append({
            "name": str(s.get("name") or ""),
            "description": str(s.get("description") or ""),
            "i2c_address": str(s.get("i2cAddress") or ""),
            "fields": fields,
        })
    return out


def _parse_eeproms(doc: dict) -> list[dict]:
    """从顶层 `eeproms` 抽 EEPROM 列表。"""
    eps = doc.get("eeproms")
    if not isinstance(eps, list):
        return []
    out: list[dict] = []
    for e in eps:
        if not isinstance(e, dict):
            continue
        fields: list[dict] = []
        for k, v in e.items():
            if k in ("name", "i2cAddress"):
                continue
            if isinstance(v, (list, dict)):
                continue
            fields.append({"key": k, "value": "" if v is None else str(v), "note": ""})
        out.append({
            "name": str(e.get("name") or ""),
            "i2c_address": str(e.get("i2cAddress") or ""),
            "fields": fields,
        })
    return out


def _parse_crypto(doc: dict) -> Optional[dict]:
    """从 `cryptoConfig` 或 `cryptoKeys` 抽摘要。真实样本里没有这类文件，保留结构。"""
    cfg = doc.get("cryptoConfig")
    keys_src: Any
    name = ""
    desc = ""
    if isinstance(cfg, dict):
        name = str(cfg.get("name") or "")
        desc = str(cfg.get("description") or "")
        keys_src = cfg.get("keys") or cfg.get("cryptoKeys")
    else:
        keys_src = doc.get("cryptoKeys")
    if keys_src is None:
        return None
    rows: list[dict] = []
    if isinstance(keys_src, list):
        for k in keys_src:
            if not isinstance(k, dict):
                continue
            rows.append({
                "link_id": str(k.get("linkId") or k.get("link_id") or ""),
                "key_purpose": str(k.get("keyPurpose") or k.get("key_purpose") or ""),
                "key_slot": str(k.get("keySlot") or k.get("key_slot") or ""),
                "note": str(k.get("note") or ""),
            })
    return {"name": name, "description": desc, "keys": rows}


# ---------- 顶层入口 ----------


def _resolve_under_root(root: Path, rel_path: str) -> Optional[Path]:
    """安全地把 `<root>/<rel_path>` 收敛到 root 下的 realpath。失败返回 None。"""
    rel = (rel_path or "").strip().lstrip("/\\")
    if not rel:
        return None
    try:
        root_real = root.resolve()
    except OSError:
        return None
    target = (root / rel).resolve() if (root / rel).exists() else None
    if target is None:
        return None
    try:
        target.relative_to(root_real)
    except ValueError:
        return None
    return target


def parse_config_db(project_id: str, rel_path: str) -> dict:
    """解析 engineering_src/<rel_path>/ 下的 query/database JSON 组。

    返回 ConfigDatabase dict（永远合法，可直接喂给 Pydantic）。即便目录不存在
    或无可读 JSON，也返回一个带 database_path 的空壳 + description 空；前端据
    `platform is None and modules==[]` 判定"没扫到"。
    """
    out: dict = {
        "database_path": rel_path or "",
        "description": "",
        "platform": None,
        "modules": [],
        "sensors": [],
        "eeproms": [],
        "crypto": None,
        "diagram_plantuml": "",
    }
    root = Path(engineering_store.engineering_root(project_id))
    if not root.exists():
        return out
    target = _resolve_under_root(root, rel_path)
    if target is None or not target.is_dir():
        return out

    # 收集所有 JSON，单文件可同时命中多种键
    seen_module_names: set[str] = set()
    seen_sensor_names: set[str] = set()
    seen_eeprom_names: set[str] = set()
    for p in _list_jsons(target):
        doc = _safe_read_json(p)
        if not doc:
            continue

        # platform（首个命中为准）
        if out["platform"] is None:
            plat = _parse_platform(doc)
            if plat is not None:
                out["platform"] = plat

        # modules / sensors / eeproms：合并并按 name 去重
        for m in _parse_modules(doc):
            key = m.get("name") or f"__anon_module_{len(out['modules'])}"
            if key in seen_module_names:
                continue
            seen_module_names.add(key)
            out["modules"].append(m)
        for s in _parse_sensors(doc):
            key = s.get("name") or f"__anon_sensor_{len(out['sensors'])}"
            if key in seen_sensor_names:
                continue
            seen_sensor_names.add(key)
            out["sensors"].append(s)
        for e in _parse_eeproms(doc):
            key = e.get("name") or f"__anon_eeprom_{len(out['eeproms'])}"
            if key in seen_eeprom_names:
                continue
            seen_eeprom_names.add(key)
            out["eeproms"].append(e)

        # crypto（首个命中为准）
        if out["crypto"] is None:
            cr = _parse_crypto(doc)
            if cr is not None:
                out["crypto"] = cr

    return out


__all__ = ["parse_config_db"]
