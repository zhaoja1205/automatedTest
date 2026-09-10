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


def _start_cmd(mask: str, extra: str = "") -> str:
    """拼一条 nvsipl_camera 起流命令。"""
    base = f'./nvsipl_camera -c {DEFAULT_CAM_CONFIG} -m "{mask}" -R -0 -1 -2 -s'
    return f"{base} {extra}".strip()


def _specs(module: str, mask: str) -> dict[str, dict[str, Any]]:
    """按功能名返回该模组下的用例模板。未列出的功能走 _generic_spec()。"""
    return {
        "起流": {
            "type": "基本功能",
            "desc": f"验证{module}模组正常起流，帧率稳定输出",
            "pre": DEFAULT_PRE,
            "steps": (
                f"1、输入命令：{_start_cmd(mask)}\n"
                f"{_SENSOR_HINT}\n"
                "③、起流成功后输入 q 退出"
            ),
            "expected": (
                "1、执行命令无报错，正常起流\n"
                "2、终端打印各模组帧率 30fps，帧率稳定无波动\n"
                "3、输入 q 可正常退出，进程无残留"
            ),
            "priority": "P1",
        },
        "出图": {
            "type": "基本功能",
            "desc": f"验证{module}模组起流并正常出图（RAW/YUV 落盘）",
            "pre": DEFAULT_PRE,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, '-f ./picture/ --skipFrames 10 --writeFrames 1')}\n"
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
            "pre": DEFAULT_PRE,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, '-R120s')}\n"
                f"{_SENSOR_HINT}\n"
                "③、持续观察终端帧率打印"
            ),
            "expected": (
                "1、执行命令无报错\n"
                "2、终端打印各模组帧率 30fps，帧率波动在 ±1 以内\n"
                "3、120 秒内帧率无掉零、无中断"
            ),
            "priority": "P1",
        },
        "帧同步": {
            "type": "基本功能",
            "desc": f"验证{module}模组帧同步时间差在容差范围内",
            "pre": DEFAULT_PRE,
            "steps": (
                f"1、输入命令：{_start_cmd(mask)}\n"
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
            "pre": DEFAULT_PRE,
            "steps": (
                f"1、输入命令：{_start_cmd(mask, '--nito ./nito/')}\n"
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
            "pre": DEFAULT_PRE,
            "steps": (
                f"1、输入命令：{_start_cmd(mask)}\n"
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
            "pre": DEFAULT_PRE,
            "steps": (
                f"1、输入命令：{_start_cmd(mask)}\n"
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
            "pre": DEFAULT_PRE + "\n4、所接模组和设备均为正常件",
            "steps": (
                f"1、起流：{_start_cmd(mask)}\n"
                f"2、注入故障并检查寄存器 errb{FAULT_REG_ADDR}：\n"
                f"sudo i2ctransfer -y -f 7 w2@0x2d 0x00 {FAULT_REG_ADDR} r1\n"
                "sudo i2ctransfer -y -f 7 w3@0x2d 0x12 0x53 0x03\n"
                f"sudo i2ctransfer -y -f 7 w2@0x2d 0x00 {FAULT_REG_ADDR} r1\n"
                "3、输入 df 指令查看故障上报情况"
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


def _generic_spec(module: str, feature: str, mask: str) -> dict[str, Any]:
    """未收录功能的兜底模板：给出结构完整的骨架，具体判定点留给用户补充。"""
    return {
        "type": "基本功能",
        "desc": f"验证{module}模组的{feature}功能正常",
        "pre": DEFAULT_PRE,
        "steps": (
            f"1、输入命令：{_start_cmd(mask)}\n"
            f"{_SENSOR_HINT}\n"
            f"③、执行{feature}相关操作（请补充具体指令）"
        ),
        "expected": (
            "1、执行命令无报错，正常起流\n"
            f"2、{feature}结果符合预期（请补充可观测的判定标准，"
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
) -> tuple[list[dict], list[dict], list[dict]]:
    """按覆盖矩阵生成用例骨架。

    Args:
        modules:  模组名列表（矩阵行）
        features: 功能名列表（矩阵列）
        matrix:   modules × features 的布尔矩阵，True 表示该模组要测该功能
        meta:     项目元信息（预留，当前仅用于未来扩展）
        category: None=全部；"functional" 只生成功能用例；"fault" 只生成故障用例

    Returns:
        (functional_cases, fault_cases, defaults_used)
        每条用例是 DesignCase 形状的 dict；defaults_used 为去重后的默认值声明。
    """
    func_cases: list[dict] = []
    fault_cases: list[dict] = []
    defaults: list[dict] = []
    seen_generic: set[str] = set()

    for row_idx, module in enumerate(modules or []):
        mask = sensor_mask(row_idx)
        specs = _specs(module, mask)
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
                spec = _generic_spec(module, feature, mask)
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
        defaults.insert(0, {
            "field": "cam_config（-c 配置名）",
            "default_value": DEFAULT_CAM_CONFIG,
            "source": "case_generator 默认配置",
            "applies_to": "全部生成用例的起流命令",
            "note": "请用 ./nvsipl_camera -l 查看实际配置名后替换",
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
