"""
SWE.2 规则预置层 — 术语/参考文档/假设/集成原则/组件功能描述模板。

把"固定可预置"的规则数据集中维护，便于后续迭代：
- `_default_aspice()` 只保留结构骨架 + 空列表
- 导出 docx 和前端"预置默认"按钮调用这里返回的工厂方法填充
- 不含任何 AI 调用、不依赖外部服务

参考文档：《PreDev_软件架构&概要设计书V1.0》结构
"""
from typing import Optional


# ---- 术语定义（1.3）----

DEFAULT_TERMS = [
    {"term": "SWE.1",   "definition": "软件需求分析过程"},
    {"term": "SWE.2",   "definition": "软件架构设计过程"},
    {"term": "SIPL",    "definition": "Sensor Input Processing Library，NVIDIA Drive-OS 相机输入处理库"},
    {"term": "PMIC",    "definition": "Power Management IC，电源管理芯片"},
    {"term": "EEPROM",  "definition": "Electrically Erasable Programmable Read-Only Memory，电可擦可编程只读存储器"},
    {"term": "SerDes",  "definition": "Serializer / Deserializer，串行器与解串器"},
    {"term": "ISP",     "definition": "Image Signal Processor，图像信号处理器"},
    {"term": "MIPI",    "definition": "Mobile Industry Processor Interface，移动产业处理器接口"},
    {"term": "I2C",     "definition": "Inter-Integrated Circuit，集成电路总线"},
    {"term": "ASIL",    "definition": "Automotive Safety Integrity Level，汽车安全完整性等级"},
]


# ---- 假设及依赖（1.5）----

DEFAULT_ASSUMPTIONS = [
    {"input": "文件资料", "time": "项目开始时", "description": "需要在项目开始时将开发所需资料提供给开发方（SOW/SRS/MRD/硬件原理图/模组规格等）。"},
    {"input": "相机模组", "time": "项目开始时", "description": "项目所需调校型号的 Golden 相机模组各若干 pcs。"},
    {"input": "开发板",   "time": "项目开始前", "description": "camera 端口连接设计及物理地址与 NV 官方开发板一致；解串器连接和配置与 NV 官方开发板一致。"},
    {"input": "工具链",   "time": "开发阶段",   "description": "评估开发工具可满足客户的验收要求。"},
]

DEFAULT_PROJECT_ASSUMPTIONS = [
    "提供的模组参数均可达成规格书要求；",
    "基于 Nvidia 平台自带 ISP；",
    "Deserializer 和 Serializer 均采用 NVIDIA Orin 支持的参考设计；",
    "开发方在开发协议期内负责将职责范围内的开发内容适配到新版本的 NV Orin DriveOS；",
    "操作系统将提供稳定的运行环境，不会出现意外的故障或中断；",
    "硬件设备将满足软件的最低配置要求，能够正常运行软件；",
    "用户将按照规定的流程和操作方式使用软件，不会进行异常的操作；",
    "三方 FAE 支持，双方构建沟通渠道，不限于邮件和会议。",
]


# ---- 系统集成（7）----

DEFAULT_INTEGRATION_ORDER = (
    "集成顺序：Deserializer → Serializer → Sensor。"
    "MAX20087、EEPROM、PMIC 注册到框架中。"
    "按从底层外设到上层应用的顺序逐步集成，每一步均完成功能点验证后再推进。"
)

DEFAULT_INTEGRATION_PRINCIPLES = [
    {"key": "usability",   "title": "易用性原则",
     "description": "集成后的系统应保持接口简洁、调用方式一致，上层应用无需感知底层硬件差异。"},
    {"key": "security",    "title": "安全性原则",
     "description": "集成过程中严格区分特权与非特权操作，关键配置（SerDes/Sensor/PMIC）须经校验后生效。"},
    {"key": "integrity",   "title": "业务完整性原则",
     "description": "任一模块集成不得破坏已集成模块的功能完整性，提交前需回归已有通过项。"},
    {"key": "normalize",   "title": "业务规范化原则",
     "description": "遵循 NvSIPL 既有接口规范，新增接口须按统一命名/参数风格对齐。"},
    {"key": "scalability", "title": "可扩展性原则",
     "description": "保留足够扩展位（新 sensor/新 ser/des 型号接入点），避免硬编码特定型号。"},
    {"key": "openness",    "title": "开放性原则",
     "description": "对三方工具链（NV FAE/模组厂）保留可调试、可观测接入点，便于后续迭代。"},
]


# ---- 组件功能描述模板（4.X.1）----

COMPONENT_FUNCTION_DESC = {
    "A001": "完成对串行器配置信息和控制，获取串行器的故障信息。",
    "A002": "完成对解串器配置信息和控制，获取解串器的故障信息。",
    "A003": "完成对 EEPROM 配置信息和控制，读取相机 EEPROM 中的基本信息、内参数据、序列号等信息。",
    "A004": "集成组件，模组以及部件（Sensor / Serializer / Deserializer）初始化、控制。",
    "A005": "单路测试工具，覆盖起流 / 帧同步 / SOF / 内参 / 故障诊断等场景。",
    "A006": "多路同点测试工具，覆盖集成故障 / 内参 / 时间戳对齐等多路协同场景。",
    "A007": "完成对 PMIC 电源芯片的配置和控制，监测电源状态与故障信息。",
    "A008": "三级认证：Camera Authentication / Communication Authentication / Image Authentication。",
}


# ---- Camera Security 专用（4.8.2 / 4.8.3）----

DEFAULT_SECURITY_GOALS = (
    "针对 Camera 子系统的篡改、注入、重放等潜在攻击面，提供三级认证机制："
    "Camera Authentication（物理身份识别）、Communication Authentication（通信链路认证）、Image Authentication（图像数据完整性校验）。"
)

DEFAULT_SECURITY_MODULES = (
    "Camera Security 由认证管理（Auth Manager）、密钥管理（Key Store）、"
    "校验引擎（Verifier）三部分组成；对外提供 OEM 可配置的证书分发与状态上报接口。"
)


# ---- 工厂方法 ----

def default_overview() -> dict:
    """返回 Swe2Overview 默认结构（术语/假设表已预置，其他留空待用户编辑）。"""
    return {
        "purpose": "",
        "scope": "",
        "terms": [dict(t) for t in DEFAULT_TERMS],
        "ref_docs": [],
        "assumptions": [dict(a) for a in DEFAULT_ASSUMPTIONS],
        "project_assumptions": list(DEFAULT_PROJECT_ASSUMPTIONS),
    }


def default_integration() -> dict:
    """返回 Swe2Integration 默认结构（顺序 + 6 条原则预置）。"""
    return {
        "order": DEFAULT_INTEGRATION_ORDER,
        "principles": [dict(p) for p in DEFAULT_INTEGRATION_PRINCIPLES],
    }


def default_overview_purpose(project_code: str) -> str:
    """1.1 目的 的默认描述，带项目代号占位。"""
    code = (project_code or "本项目").strip()
    return (
        f"本文档的目的是对 {code} 项目的 camera 驱动软件系统进行概要的功能说明，"
        f"以便项目管理人员及项目开发人员了解软件系统大致的设计与实现。"
    )


DEFAULT_OVERVIEW_SCOPE = (
    "概要设计说明书对模块划分、设计策略、系统分解、系统集成等内容作了总体描述，"
    "体现功能需求与应用系统之间的关系，在设计过程中起到提纲掣领的作用。\n"
    "预期读者：需求分析人员、设计人员、开发人员、项目管理人员、测试人员。"
)


def build_ref_docs_from_project(project: dict) -> list[dict]:
    """从 project.meta / aspice.project_code 读 SOW/SRS/MRD 文件名+版本，派生前 N 行参考文档。

    这是"兜底填充"：优先用户已在 overview.ref_docs 中维护的，这里只填前 2-3 行常见项。
    """
    meta = project.get("meta", {}) or {}
    code = (project.get("aspice", {}) or {}).get("project_code", "")
    rows = []
    seq = 1

    references = meta.get("references")
    if isinstance(references, list):
        for ref in references:
            if isinstance(ref, dict):
                name = ref.get("name", "") or ref.get("filename", "")
                version = ref.get("version", "")
                note = ref.get("note", "") or ref.get("description", "")
            else:
                name = str(ref)
                version = ""
                note = ""
            if name:
                rows.append({"no": str(seq), "name": name, "version": version, "note": note})
                seq += 1

    # 典型兜底条目（根据项目代号派生）
    if code:
        rows.append({"no": str(seq), "name": f"{code}_SOW",   "version": "V1.0", "note": "客户原始需求"}); seq += 1
        rows.append({"no": str(seq), "name": f"{code}_SRS",   "version": "V1.0", "note": "软件需求规格"}); seq += 1
    rows.append({"no": str(seq), "name": "NVIDIA Drive-OS NvSIPL Programming Guide", "version": "-", "note": "NV 官方文档"})
    return rows


def build_linked_req_rows(req_ids: list[str], component_name: Optional[str] = None) -> str:
    """把 ['Pangu_001-R001-A001', ...] 拼成 '需依赖该模块实现' 的溯源句。"""
    if not req_ids:
        return ""
    deduped = list(dict.fromkeys(r for r in req_ids if r))
    if not deduped:
        return ""
    name_part = f"（{component_name}）" if component_name else ""
    return f"{'、'.join(deduped)} 需依赖该模块{name_part}实现。"


def default_component_fields(component_id: str, component_name: str) -> dict:
    """返回组件的新增字段默认值（function_desc / 空接口列表 等），用于迁移和创建."""
    base = {
        "function_desc": COMPONENT_FUNCTION_DESC.get(component_id, f"完成 {component_name} 相关的配置、控制与状态获取。"),
        "linked_req_ids": [],
        "external_interfaces": [],
        "internal_interfaces": [],
        "classes": [],
        "scenarios": [],
    }
    if component_id == "A008":
        base["security_goals"] = DEFAULT_SECURITY_GOALS
        base["security_modules"] = DEFAULT_SECURITY_MODULES
    return base


# ============================================================================
# 推送 H / SWE.3 详细设计 — 常量与辅助
# ============================================================================

# 8 模块 ID → 短名（用于设计 ID 前缀 / heading 匹配）
MODULE_SHORT: dict[str, str] = {
    "A001": "Serializer",
    "A002": "Deserializer",
    "A003": "EEPROM",
    "A004": "CameraModule",
    "A005": "CameraSecurity",
    "A006": "nvsipl_camera",
    "A007": "nvsipl_multicast",
    "A008": "PMIC",
    # R4.9（2026-11-16）：补 A009 → Campwr 映射。
    # 之前漏加导致 split_policy_for_module('A009', ...) 两步查询都落空 → fallback auto_all，
    # bridge 仍然按 scan_cache 现算类 / 自动吃 added/modified 覆盖用户编辑。
    # 同时 MODULE_SPLIT_POLICY['Campwr'] = 'manual' → 现在走 R4.7 的 manual 分支。
    "A009": "Campwr",
}

# SWE.3 L5 展开策略（按模块自研/NV 底色区分 — 决定函数进 L5 的默认门槛）
#   auto_all      : 自研程度高 → ai 识别到 added ∨ modified 都自动进 L5
#                   （diff.trustworthy=False 时退化成只 focused_keys，防止 baseline 退化 docx 爆炸）
#   modified_only : 以 NV 为底 → 只有 modified 自动进 L5；added 仅前端打🆕标记，
#                   用户在 FocusFunctionsPicker 勾选（落入 included_added_keys）后才展开；
#                   不勾的 added 归 NV 原始列表不展开
#   manual        : 由人工维护章节（如 CameraSecurity）— 不走函数路径
#
# 新增模块（不在 MODULE_SHORT 里，如 A009 Campwr）默认 auto_all：
# 由 arch_generator 兜底克隆 PMIC 章节出章，用户倾向于全量展开。
MODULE_SPLIT_POLICY: dict[str, str] = {
    # A 组：自研程度高、全展开
    "Serializer":       "auto_all",
    "EEPROM":           "auto_all",
    "PMIC":             "auto_all",
    # B 组：CameraModule 仍走 diff 自动
    "CameraModule":     "modified_only",
    # C 组：NV 底仓海量函数，自动 diff 噪声太大 →
    # 改为 manual，只展示人工在 FocusFunctionsPicker 勾选的函数
    # （R4 需求 #2）
    "Deserializer":     "manual",
    "nvsipl_camera":    "manual",
    "nvsipl_multicast": "manual",
    # 人工维护
    "CameraSecurity":   "manual",
    # R4.9（2026-11-16）：Campwr 从 auto_all → manual。
    # 原本和 Serializer/EEPROM/PMIC 同组走 auto_all，但该模块实际是用户基于
    # PMIC 克隆出来手工维护章节，auto_all 会把 scan_cache 里扫到的 7+ 个
    # CNvMMpq5864 系列类全塞进 docx（12.2.1~12.2.7 Class XXX），覆盖
    # ModuleEditor 里精简到的「1 个类 CNvMMpq5864 + 3 函数」。
    # 改 manual 后导出严格跟用户在 ModuleEditor 的编辑；nv_original_functions
    # 仍按 scan 注入到 L4 原始NV函数列表章节（这个数据来源合理）。
    "Campwr":           "manual",
}


def split_policy_for_module(cid: str, name: str) -> str:
    """按 cid 或 name 查分流策略；找不到默认 auto_all。
    name 匹配容忍大小写/空格/下划线/短横。
    """
    short = MODULE_SHORT.get((cid or "").strip(), "")
    if short and short in MODULE_SPLIT_POLICY:
        return MODULE_SPLIT_POLICY[short]
    norm = (name or "").lower().replace(" ", "").replace("_", "").replace("-", "")
    if not norm:
        return "auto_all"
    for k, v in MODULE_SPLIT_POLICY.items():
        kn = k.lower().replace(" ", "").replace("_", "").replace("-", "")
        if kn and (kn in norm or norm in kn):
            return v
    return "auto_all"

# 模块功能简述（3.1 功能概述 / 4.1 模块概述段落默认文案）
MODULE_FUNCTION_DESC: dict[str, str] = {
    "A001": "完成对串行器（Serializer）的配置、控制与故障信息读取。",
    "A002": "完成对解串器（Deserializer）的配置、控制与故障信息读取。",
    "A003": "完成对相机模组 EEPROM 的读写（含内参/序列号/标定数据）。",
    "A004": "相机模组的集成组件，负责各部件初始化、起流与协同控制。",
    "A005": "三级认证模块（Camera / Communication / Image Authentication）。",
    "A006": "基于 NVIDIA SIPL 的单路相机接入与控制。",
    "A007": "基于 NVIDIA SIPL 的多路同步相机接入与控制。",
    "A008": "完成对 PMIC 电源芯片的配置、控制与状态读取。",
}

# 3.2 功能模块图默认 PlantUML（8 模块 + SIPL 框架分区着色）
DEFAULT_MODULE_DIAGRAM_PLANTUML = r"""@startuml
!theme plain
skinparam componentStyle rectangle
skinparam shadowing false
skinparam defaultFontName "Microsoft YaHei"
skinparam componentBackgroundColor<<app>> #E3F2FD
skinparam componentBackgroundColor<<nv>> #FFF3E0
skinparam componentBackgroundColor<<dev>> #E8F5E9
skinparam componentBackgroundColor<<sec>> #FCE4EC

package "NV SIPL 框架 (NVIDIA Drive-OS)" {
  [nvsipl_camera] <<nv>>
  [nvsipl_multicast] <<nv>>
}

package "相机模组集成" {
  [CameraModule] <<app>>
  [CameraSecurity] <<sec>>
}

package "器件驱动" {
  [Serializer] <<dev>>
  [Deserializer] <<dev>>
  [EEPROM] <<dev>>
  [PMIC] <<dev>>
}

[CameraModule] --> [Serializer]
[CameraModule] --> [Deserializer]
[CameraModule] --> [EEPROM]
[CameraModule] --> [PMIC]
[CameraModule] --> [CameraSecurity]
[nvsipl_camera] --> [CameraModule]
[nvsipl_multicast] --> [nvsipl_camera]
@enduml
"""


def build_design_id(
    mod_idx: int,
    mod_name: str,
    category: str,
    idx: int,
    host: Optional[str] = None,
) -> str:
    """构造详细设计 ID。

    - category: "class" | "function"
    - host: 优先取类名/型号（如 MAX96717），fallback mod_name
    - 示例: D001-Serializer-class-001 / D001-MAX96717-function-005
    """
    short = (host or mod_name or "").strip() or "Mod"
    # 清洗一下非 ASCII 和空格，避免 docx 里 ID 带中文/空格不易引用
    import re as _re
    short = _re.sub(r"[^A-Za-z0-9_]+", "", short) or "Mod"
    return f"D{mod_idx:03d}-{short}-{category}-{idx:03d}"
