"""
矩阵驱动的测试用例骨架生成器（规则模板）。

输入「模组 × 功能」覆盖矩阵，输出符合执行侧规范的用例骨架（DesignCase dict）。
本模块是确定性的、离线可用的兜底实现；AI 增强由 app.ai.service 另行提供，
调用方在 AI 不可用时整批回退到本模块。

规范要点（与执行侧 ExcelHandler / ExpectedResultParser 对齐）：
- 列义：B=ID C=测试类型 D=设计方法 E=用例描述 F=前置条件 G=测试步骤 H=预期结果 I=优先级
- 预期结果必须含可判定的观测点，否则 ExpectedResultParser 提取不到 keywords，
  判定会退化为只看 exit_code（置信度上限 0.7）。可能的观测点：
    * 产物后缀 .raw/.yuv/.png/.log/.txt/.csv  → file_check
    * 数值 NNfps                             → 帧率检查（±20% 容差）
    * 「无报错/无异常/无错误」                → exit_code 检查
    * 引号包裹的字符串                        → 精确关键字
    * 十六进制值 0xNN（跟在「值为/返回/等于/为」后）→ 关键字
"""
from __future__ import annotations

from typing import Any, Optional

# 默认 nvsipl_camera 配置名（用户需按实际模组修改，会记入 defaults_used）
DEFAULT_CAM_CONFIG = "MIXGROUP_PREDEV_30FPS_MAX96724_CPHY_x4"

# 通用前置条件
DEFAULT_PRE = (
    "1、驱动文件放入目录：/usr/lib/nvidia/nvsipl_drv\n"
    "2、板子连接模组，确认模组在位\n"
    "3、SSH 登录板端"
)

# 故障注入用寄存器（默认值，需按实际硬件确认）
FAULT_REG_ADDR = "0x1a"
FAULT_REG_EXPECTED = "0x04"


def _meta_value(meta: Optional[dict], key: str, placeholder: str) -> str:
    """项目特定值优先用问答配置；缺失时保留占位符，不编造。"""
    value = (meta or {}).get(key)
    text = str(value).strip() if value is not None else ""
    return text or f"<待补充:{placeholder}>"


def _parse_fps_map(text: str) -> dict[str, str]:
    """解析 A2 中的逐模组帧率：IMX728=30fps / IMX728: 30fps。"""
    result: dict[str, str] = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if "=" in line:
            name, fps = line.split("=", 1)
        elif ":" in line:
            name, fps = line.split(":", 1)
        else:
            continue
        name = name.strip()
        fps = fps.strip()
        if name and fps:
            result[name] = fps if "fps" in fps.lower() else f"{fps}fps"
    return result


def _fps_for_module(module: str, meta: Optional[dict]) -> str:
    fps_map = _parse_fps_map((meta or {}).get("fps_by_module", ""))
    return fps_map.get(module, "<待补充:帧率>")


def _pre(meta: Optional[dict]) -> str:
    driver_dir = _meta_value(meta, "driver_deploy_dir", "驱动部署目录")
    debug_dir = _meta_value(meta, "debug_dir", "调试目录")
    board_ip = _meta_value(meta, "board_ip", "板端IP")
    program = _meta_value(meta, "stream_program", "起流程序")
    components = str((meta or {}).get("tested_components", "")).strip()
    lines = [
        f"1、驱动文件放入目录：{driver_dir}",
        "2、板子连接模组，确认模组在位",
        f"3、SSH 登录板端：{board_ip}",
        f"4、进入调试目录：{debug_dir}",
        f"5、确认测试工具可执行：{program}",
    ]
    if components:
        lines.append(f"6、被测组件清单：{components}")
    return "\n".join(lines)


# 查看模组名称的标准提示（真实用例中每步都带）
_SENSOR_HINT = (
    "①、查看模组名称的方法：./nvsipl_camera -l\n"
    "②、-m 指定模组位置"
)


def sensor_mask(module_index: int) -> str:
    """由模组序号生成 -m 掩码，语义与 ExpectedResultParser._parse_sensor_mask 对齐。

    每 4 个模组一组，组内第 n 个模组对应半字节 0x1 << (n * 4)：
    index 0 → '0x1 0 0 0'，index 5 → '0 0x10 0 0'。
    """
    group_idx = module_index // 4
    local_sid = module_index % 4
    nibble = 1 << (local_sid * 4)
    parts = ["0"] * 4
    parts[group_idx] = f"0x{nibble:x}"
    return " ".join(parts)


_GROUP_INDEX = {
    "group-a": 0, "groupa": 0, "a": 0,
    "group-b": 1, "groupb": 1, "b": 1,
    "group-c": 2, "groupc": 2, "c": 2,
    "group-d": 3, "groupd": 3, "d": 3,
}

_LINK_BIT = {
    "link a": 0x1, "a": 0x1,
    "link b": 0x10, "b": 0x10,
    "link c": 0x100, "c": 0x100,
    "link d": 0x1000, "d": 0x1000,
}


def _parse_hex_or_none(value: Any) -> Optional[int]:
    """解析 0xNN 字符串，失败返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        return None


def _topology_group_index(group: str) -> Optional[int]:
    """将 group-A / GroupA / A 映射到 -m 四段中的索引。"""
    return _GROUP_INDEX.get(str(group or "").strip().lower())


def _topology_bit(item: dict) -> int:
    """计算拓扑行在组内对应的半字节。

    优先级：用户填写 mask_bit > sensor_id % 4 > Link A/B/C/D。
    这样既支持标准 Link 映射，也支持 AVM bypass 等多个 camera 同一 Link 的情况。
    """
    mask_bit = _parse_hex_or_none(item.get("mask_bit"))
    if mask_bit is not None:
        return mask_bit

    sensor_id = _parse_hex_or_none(item.get("sensor_id"))
    if sensor_id is not None:
        return 1 << ((sensor_id % 4) * 4)

    return _LINK_BIT.get(str(item.get("link", "")).strip().lower(), 0)


def topology_mask(module: str, topology: Optional[list[dict]]) -> Optional[str]:
    """按硬件拓扑为指定模组型号聚合 -m 掩码。

    匹配字段：拓扑表中的模组型号（历史字段名 camera）。多行匹配时 OR 到同一四段 mask。
    sensor 地址（adr_name）是 I2C 地址，不参与矩阵/拓扑匹配。
    若没有匹配到有效拓扑，返回 None，由调用方回退 sensor_mask(row_idx)。
    """
    target = str(module or "").strip()
    if not target:
        return None

    parts = [0, 0, 0, 0]
    matched = False
    for item in topology or []:
        if not isinstance(item, dict):
            continue
        module_model = str(
            item.get("camera") or item.get("module_model") or item.get("sensor_model") or ""
        ).strip()
        if target != module_model:
            continue
        group_idx = _topology_group_index(str(item.get("group", "")))
        if group_idx is None or group_idx >= len(parts):
            continue
        bit = _topology_bit(item)
        if not bit:
            continue
        parts[group_idx] |= bit
        matched = True

    if not matched:
        return None
    return " ".join(f"0x{p:x}" if p else "0" for p in parts)


def _start_cmd(mask: str, meta: Optional[dict], extra: str = "") -> str:
    """拼一条起流命令，程序名和 -c 配置来自 A2 问答。"""
    program = _meta_value(meta, "stream_program", "起流程序")
    cam_config = _meta_value(meta, "cam_config", "-c配置名")
    base = f'./{program} -c {cam_config} -m "{mask}" -R -0 -1 -2 -s'
    return f"{base} {extra}".strip()


def _specs(module: str, mask: str, meta: Optional[dict]) -> dict[str, dict[str, Any]]:
    """按功能名返回该模组下的用例模板。未列出的功能走 _generic_spec()。"""
    pre = _pre(meta)
    fps = _fps_for_module(module, meta)
    success_signal = str((meta or {}).get("stream_success_signal") or "帧率打印或 streaming").strip()
    functional_timeout = str((meta or {}).get("functional_timeout") or "15").strip()
    fault_timeout = str((meta or {}).get("fault_timeout") or "30").strip()
    criteria = str((meta or {}).get("feature_criteria") or "").strip()
    criteria_note = f"\n4、项目判定标准：{criteria}" if criteria else ""
    return {
        "起流": {
            "type": "基本功能",
            "desc": f"验证{module}模组正常起流，帧率稳定输出",
            "pre": pre,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, meta)}\n"
                f"{_SENSOR_HINT}\n"
                "③、起流成功后输入 q 退出"
            ),
            "expected": (
                "1、执行命令无报错，正常起流\n"
                f"2、出现起流成功标志：{success_signal}\n"
                f"3、终端打印各模组帧率 {fps}，帧率稳定无波动\n"
                "4、输入 q 可正常退出，进程无残留"
                + criteria_note
            ),
            "priority": "P1",
        },
        "出图": {
            "type": "基本功能",
            "desc": f"验证{module}模组起流并正常出图（RAW/YUV 落盘）",
            "pre": pre,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, meta, '-f ./picture/ --skipFrames 10 --writeFrames 1')}\n"
                f"{_SENSOR_HINT}\n"
                "③、-f 指定图片存放目录"
            ),
            "expected": (
                "1、执行命令无报错，可生成.raw文件\n"
                "2、raw可正常查看，图像无花屏、无黑屏"
            ),
            "priority": "P1",
        },
        "帧率": {
            "type": "基本功能",
            "desc": f"验证{module}模组帧率达标且长时间稳定",
            "pre": pre,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, meta, '-R120s')}\n"
                f"{_SENSOR_HINT}\n"
                "③、持续观察终端帧率打印"
            ),
            "expected": (
                "1、执行命令无报错\n"
                f"2、终端打印各模组帧率 {fps}，帧率波动在 ±1 以内\n"
                f"3、120 秒内帧率无掉零、无中断"
                + criteria_note
            ),
            "priority": "P1",
        },
        "帧同步": {
            "type": "基本功能",
            "desc": f"验证{module}模组帧同步时间差在容差范围内",
            "pre": pre,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, meta)}\n"
                f"{_SENSOR_HINT}\n"
                "③、等待终端打印 metadata（含时间戳）"
            ),
            "expected": (
                "1、执行命令无报错，正常起流\n"
                "2、终端打印完整 metadata（含时间戳）\n"
                "3、按公式 (A-B)*32/pow(10,6) 计算，帧同步时间差 < 1ms"
            ),
            "priority": "P2",
        },
        "AE调节": {
            "type": "基本功能",
            "desc": f"验证{module}模组 AE 自动曝光调节正常",
            "pre": pre,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, meta, '--nito ./nito/')}\n"
                "2、给镜头切换白天环境，观察终端打印的 exp、gain 值\n"
                "3、再切换黑夜环境，观察 exp、gain 值变化"
            ),
            "expected": (
                "1、执行命令无报错，正常起流\n"
                "2、切换白天环境后 exp、gain 值发生变化\n"
                "3、切换黑夜环境后 exp、gain 值再次变化"
            ),
            "priority": "P2",
        },
        "内参读取": {
            "type": "基本功能",
            "desc": f"验证{module}模组内参数据可正常读取",
            "pre": pre,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, meta)}\n"
                f"{_SENSOR_HINT}\n"
                "③、起流后输入 gc <sensor id> 读取内参"
            ),
            "expected": (
                "1、执行命令无报错，正常起流\n"
                "2、终端打印内参数据（含 EEPROM 字样），数据完整无缺项"
            ),
            "priority": "P2",
        },
        "metadata": {
            "type": "基本功能",
            "desc": f"验证{module}模组 metadata 正常打印",
            "pre": pre,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, meta)}\n"
                f"{_SENSOR_HINT}\n"
                "③、等待终端输出 metadata"
            ),
            "expected": (
                "1、执行命令无报错，正常起流\n"
                "2、终端打印完整 metadata（含时间戳），字段无缺失"
            ),
            "priority": "P2",
        },
        "故障注入": {
            "type": "故障注入",
            "desc": f"验证{module}模组故障注入后故障位正确上拉并上报",
            "pre": pre + "\n7、所接模组和设备均为正常件",
            "steps": (
                f"1、起流：{_start_cmd(mask, meta)}\n"
                f"2、注入故障并检查寄存器 errb{FAULT_REG_ADDR}：\n"
                f"sudo i2ctransfer -y -f 7 w2@0x2d 0x00 {FAULT_REG_ADDR} r1\n"
                "sudo i2ctransfer -y -f 7 w3@0x2d 0x12 0x53 0x03\n"
                f"sudo i2ctransfer -y -f 7 w2@0x2d 0x00 {FAULT_REG_ADDR} r1\n"
                f"3、在 {fault_timeout} 秒内输入 df 指令查看故障上报情况"
            ),
            "expected": (
                "1、执行命令无报错，正常起流\n"
                f"2、故障注入后读取寄存器 errb{FAULT_REG_ADDR}，值为 {FAULT_REG_EXPECTED}"
                "（bit2 由 0 置 1，代表故障已上报）\n"
                "3、终端上报相关故障，无异常"
            ),
            "priority": "P1",
        },
    }


def _generic_spec(module: str, feature: str, mask: str, meta: Optional[dict] = None) -> dict[str, Any]:
    """未收录功能的兜底模板：给出结构完整的骨架，具体判定点留给用户补充。"""
    program = _meta_value(meta, "stream_program", "起流程序")
    fps = _fps_for_module(module, meta)
    return {
        "type": "基本功能",
        "desc": f"验证{module}模组的{feature}功能正常",
        "pre": _pre(meta),
        "steps": (
            f"1、输入命令：{_start_cmd(mask, meta)}\n"
            f"{_SENSOR_HINT}\n"
            f"③、用 {program} 执行{feature}相关操作（请补充具体指令）"
        ),
        "expected": (
            "1、执行命令无报错，正常起流\n"
            f"2、终端打印各模组帧率 {fps}\n"
            f"3、{feature}结果符合预期（请补充可观测的判定标准，"
            "如产物文件名、帧率数值或明确的报错关键字）"
        ),
        "priority": "P2",
    }


# 归入故障用例的功能名
_FAULT_FEATURES = {"故障注入", "故障", "故障诊断"}


def _make_case(spec: dict[str, Any]) -> dict[str, Any]:
    """补齐 DesignCase 的固定字段。"""
    return {
        "type": spec.get("type", "基本功能"),
        "method": spec.get("method", "基于需求分析"),
        "desc": spec.get("desc", ""),
        "pre": spec.get("pre", DEFAULT_PRE),
        "steps": spec.get("steps", ""),
        "expected": spec.get("expected", ""),
        "priority": spec.get("priority", "P2"),
        "changelog": "",
    }


def generate_cases(
    modules: list[str],
    features: list[str],
    matrix: list[list[bool]],
    meta: Optional[dict] = None,
    category: Optional[str] = None,
    topology: Optional[list[dict]] = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """按覆盖矩阵生成用例骨架。

    Args:
        modules:  模组名列表（矩阵行）
        features: 功能名列表（矩阵列）
        matrix:   modules × features 的布尔矩阵，True 表示该模组要测该功能
        meta:     项目元信息（预留，当前仅用于未来扩展）
        category: None=全部；"functional" 只生成功能用例；"fault" 只生成故障用例
        topology: 可选硬件拓扑，含 group/link/模组型号(camera)/sensor_id/mask_bit，用于精确计算 -m

    Returns:
        (functional_cases, fault_cases, defaults_used)
        每条用例是 DesignCase 形状的 dict；defaults_used 为去重后的默认值声明。
    """
    func_cases: list[dict] = []
    fault_cases: list[dict] = []
    defaults: list[dict] = []
    seen_generic: set[str] = set()

    used_topology_mask = False

    for row_idx, module in enumerate(modules or []):
        topo_mask = topology_mask(module, topology)
        mask = topo_mask or sensor_mask(row_idx)
        if topo_mask:
            used_topology_mask = True
        specs = _specs(module, mask, meta)
        for col_idx, feature in enumerate(features or []):
            # 未勾选则跳过
            if not (matrix[row_idx][col_idx] if row_idx < len(matrix)
                    and col_idx < len(matrix[row_idx]) else False):
                continue

            is_fault = feature in _FAULT_FEATURES
            if category == "functional" and is_fault:
                continue
            if category == "fault" and not is_fault:
                continue

            spec = specs.get(feature)
            if spec is None:
                spec = _generic_spec(module, feature, mask, meta)
                if feature not in seen_generic:
                    seen_generic.add(feature)
                    defaults.append({
                        "field": f"功能「{feature}」的用例模板",
                        "default_value": "通用模板",
                        "source": "case_generator 兜底",
                        "applies_to": f"全部模组的「{feature}」列",
                        "note": "该功能未收录标准模板，请按实际测试内容补充步骤与可观测的预期结果",
                    })

            case = _make_case(spec)
            (fault_cases if is_fault else func_cases).append(case)

    # 声明引用的默认值，复用导出侧「默认值请确认」链路
    if func_cases or fault_cases:
        # 仅当用户未在 A2 提供 cam_config 时，提示用默认配置名兜底
        cam_config_value = str((meta or {}).get("cam_config") or "").strip()
        if not cam_config_value:
            defaults.insert(0, {
                "field": "cam_config（-c 配置名）",
                "default_value": DEFAULT_CAM_CONFIG,
                "source": "case_generator 默认配置",
                "applies_to": "全部生成用例的起流命令",
                "note": "A2 未填写配置名，已用默认值兜底；请用 ./nvsipl_camera -l 查看实际配置名后替换",
            })
        if used_topology_mask:
            defaults.append({
                "field": "-m mask（按硬件拓扑计算）",
                "default_value": "coverage_matrix.topology",
                "source": "用户填写的 Group/Link/mask 位拓扑",
                "applies_to": "按模组型号匹配到拓扑的生成用例",
                "note": "请确认每行 mask位 与实际 Link/sensor-id 对应关系一致；如示例 -m \"0x1111 0 0x1111 0x1111\" 需完整填写对应 Link/预留位",
            })
        if any(f["type"] == "故障注入" for f in fault_cases):
            defaults.append({
                "field": "故障寄存器地址与预期值",
                "default_value": f"errb{FAULT_REG_ADDR} = {FAULT_REG_EXPECTED}",
                "source": "case_generator 默认寄存器",
                "applies_to": "全部故障注入用例",
                "note": "请按实际解串器/加串器寄存器地址与 bit 定义确认，地址错误会导致判定失效",
            })

    return func_cases, fault_cases, defaults


def merge_defaults(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """按 (field, default_value) 去重合并默认值声明，保留已有条目。"""
    merged: list[dict] = []
    seen: set[tuple] = set()
    for item in list(existing or []) + list(incoming or []):
        key = (item.get("field", ""), item.get("default_value", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged
