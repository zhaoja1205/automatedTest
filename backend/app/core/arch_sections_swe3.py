"""
SWE.3 规则预置层 — 设计 ID 工厂 / 默认模块 / 共通定义预置。

把"固定可预置"的 SWE.3 规则集中维护，便于后续迭代：
- 设计 ID 命名：D{组件编号 3 位}-{组件名}-{类/函数}-{序号 3 位}
    示例：D001-Serializer-class-001 / D004-IMX623-function-086
- 9 个默认模块（SWE.2 的 8 组件 + Campwr 电源扩展模块）
- 共通定义预置：6 个标准枚举（DeviceState/ModuleComponent/LinkMode/Action/NvMediaStatus/SIPLStatus）
                7 个标准结构体骨架（DeviceParams/EEPROMRequestHandle/LinkParams 等）

参考文档：《PreDev_详细设计V1.0_updated》结构
"""
from typing import Optional


# ---- 模块索引（9 个模块 → 对应组件 A001~A008 + Campwr 扩展）----

# key 用于设计 ID 中段，与模块的 slug 对齐
DEFAULT_MODULES = [
    {"id": "A001", "slug": "Serializer",      "name": "Serializer",
     "title": "模块Serializer详细设计",       "has_sequence": True},
    {"id": "A002", "slug": "Deserializer",    "name": "Deserializer",
     "title": "模块Deserializer详细设计",     "has_sequence": True},
    {"id": "A003", "slug": "EEPROM",           "name": "EEPROM",
     "title": "模块EEPROM详细设计",            "has_sequence": True},
    {"id": "A004", "slug": "CameraModule",    "name": "camera module",
     "title": "模块camera module详细设计",     "has_sequence": True},
    {"id": "A008", "slug": "CameraSecurity",  "name": "Camera Security",
     "title": "模块Camera Security详细设计说明", "has_sequence": True, "is_security": True},
    {"id": "A005", "slug": "nvsiplcamera",    "name": "nvsipl_camera",
     "title": "模块nvsipl_camera详细设计",     "has_sequence": True},
    {"id": "A006", "slug": "nvsiplmulticast", "name": "nvsipl_multicast",
     "title": "模块nvsipl_multicast详细说明",  "has_sequence": True},
    {"id": "A007", "slug": "PMIC",             "name": "PMIC",
     "title": "模块PMIC详细设计",              "has_sequence": True},
    # 第 9 个模块：Campwr（电源扩展，参考文档第 10 章）—— 没有对应 SWE.2 组件 ID，使用 A009 占位
    {"id": "A009", "slug": "Campwr",          "name": "Campwr",
     "title": "模块Campwr详细设计",            "has_sequence": False},
]

# 组件 ID → 模块索引（1 基）
_MODULE_SEQ_BY_ID = {m["id"]: idx + 1 for idx, m in enumerate(DEFAULT_MODULES)}


def module_seq(component_id: str) -> int:
    """返回组件对应模块在设计 ID 中段的序号（1~9）；未知则 0。"""
    return _MODULE_SEQ_BY_ID.get(component_id, 0)


def design_id_class(component_id: str, slug: str, seq: int) -> str:
    """类设计 ID：D{组件编号 3 位}-{组件 slug}-class-{3 位 seq}。"""
    return f"D{module_seq(component_id):03d}-{slug}-class-{seq:03d}"


def design_id_function(component_id: str, slug: str, seq: int) -> str:
    """函数设计 ID：D{组件编号 3 位}-{组件 slug}-function-{3 位 seq}。"""
    return f"D{module_seq(component_id):03d}-{slug}-function-{seq:03d}"


# ---- 概述章节预置（SWE.3 独有的字符集 + get/set 规则）----

DEFAULT_SWE3_PURPOSE = (
    "本文档的目的是对 {code} 项目的 camera 驱动软件系统进行详细的功能设计说明，"
    "指导开发人员按统一的类/函数命名、接口参数、错误处理与边界条件完成编码。"
)

DEFAULT_SWE3_SCOPE_ROWS = [
    {"no": "1", "scope": "Serializer / Deserializer",   "function": "SerDes 配置、错误状态读取、link 控制"},
    {"no": "2", "scope": "EEPROM",                       "function": "标定数据、序列号、内参数据读取"},
    {"no": "3", "scope": "Camera Module",                "function": "模组初始化、启停、ISP 配置、PMIC/Sensor 错误整合"},
    {"no": "4", "scope": "nvsipl_camera / multicast",   "function": "单路/多路相机测试工具，起流/帧同步/metadata"},
    {"no": "5", "scope": "PMIC / Campwr",                "function": "电源芯片 TPS650332/BD868B2 配置与错误读取"},
]

DEFAULT_SWE3_CHARSET = (
    "本文档所有源代码采用 UTF-8 字符集；注释与标识符使用英文为主，中文仅用于说明文字。"
)

DEFAULT_SWE3_GETSET_RULE = (
    "对于成员变量的 set 和 get 函数只是对成员变量进行设值和取值，没有额外的处理逻辑，"
    "因此内容不体现在详细设计文档中。"
)


# ---- 术语定义（第 2 章，SWE.3 专用 + 复用 SWE.2 术语）----

DEFAULT_SWE3_TERMS = [
    {"term": "SWE.3",     "definition": "软件详细设计及单元构建过程"},
    {"term": "设计 ID",   "definition": "类/函数/结构体的唯一标识，规则：D{组件编号}-{组件名}-{类/函数}-{序号}"},
    {"term": "单元时序图", "definition": "描述单个模块内部关键函数之间的调用顺序与数据流"},
    {"term": "边界值分析", "definition": "针对函数入参可能的边界条件（空指针、极值、越界）进行的测试点分析"},
]


# ---- 性能分析（第 11 章）与函数设计评估（第 12 章）----

DEFAULT_PERF_PARAGRAPHS = [
    "性能分析核查需包含三个指标：",
    "1) camera 驱动内存占用情况核查确认；",
    "2) 核查 so 库占用空间，符合要求；",
    "3) 核查驱动对应的 CPU 占用率，符合要求。",
    "详情参见《PreDev_软件架构&概要设计书》性能章节。"
    "性能主要和平台相关，TS 只做核查，SIPL 框架不做优化，驱动保证无异常即可，"
    "因此性能部分无需详细设计。",
]

DEFAULT_FUNC_EVAL_PARAGRAPHS = [
    "此模块主要对函数设计的复杂性、可测试性、关键性、交互性进行评估，例如：",
    "复杂性：考虑函数圈复杂度（建议 ≤ 10）。",
    "可测试性：为每函数添加函数流程图，指导单元测试 case 编写，保证 case 测试的完整性。",
    "交互性：避免过多的函数相互调用，在设计之初将每个函数被调用次数限制在 10 以内。",
    "关键性：对于涉及核心算法或业务逻辑的函数，需要充分考虑信息安全、可重入性、线程安全以及性能。",
]

DEFAULT_FUNC_IMPACT_PARAGRAPHS = [
    "调用该函数的其他函数：如果修改了函数的输入参数、返回值、功能逻辑或异常处理方式，调用方可能产生不同结果或出错。",
    "依赖于该函数输出结果的其他模块或组件：可能因为函数输出的变化而出现功能异常。",
    "与该函数共享数据结构或全局变量的其他部分：函数的修改可能导致对共享数据的操作方式改变。",
    "相关的测试用例：函数的修改可能导致现有的测试用例失败，需要对相关测试用例进行更新。",
]


# ---- 共通定义（第 13 章）----

DEFAULT_COMMON_CONSTANTS = [
    {"seq": "1", "name": "REG_ADDRESS_BYTES",     "value": "2",      "desc": "Sensor Register Address: 16bit"},
    {"seq": "2", "name": "REG_DATA_BYTES",         "value": "1",      "desc": "Sensor Register Data: 8bit"},
    {"seq": "3", "name": "MAX_LINK_NUM",           "value": "4",      "desc": "最大 Deserializer link 数量"},
    {"seq": "4", "name": "CDI_DEVICE_INDEX_MAX",   "value": "16",     "desc": "最大 CDI 设备索引"},
]

DEFAULT_COMMON_VARIABLES = [
    {"seq": "1", "name": "supportedRevisions",  "type": "RevisionIMX623[]",
     "value": "{CDI_IMX623_REV_0, 0x00u}, ...", "desc": "IMX623 supported revisions"},
]

DEFAULT_COMMON_ENUMS = [
    {"name": "DeviceState", "values": [
        {"seq": "001", "value": "CREATED",     "desc": "所有设备的初始状态"},
        {"seq": "002", "value": "CONFIGURED",  "desc": "设备配置完成"},
        {"seq": "003", "value": "INITIALIZED", "desc": "设备初始化完成"},
        {"seq": "004", "value": "STARTED",     "desc": "设备开始工作"},
        {"seq": "005", "value": "STOPPED",     "desc": "设备停止工作"},
        {"seq": "006", "value": "DEINITIALIZED","desc": "设备反初始化"},
        {"seq": "007", "value": "DESTROYED",   "desc": "设备销毁"},
        {"seq": "008", "value": "ERROR",       "desc": "设备错误状态"},
    ]},
    {"name": "ModuleComponent", "values": [
        {"seq": "001", "value": "MODULE_COMPONENT_SENSOR",       "desc": "设备组件 Sensor"},
        {"seq": "002", "value": "MODULE_COMPONENT_SERIALIZER",   "desc": "设备组件 Serializer"},
        {"seq": "003", "value": "MODULE_COMPONENT_EEPROM",       "desc": "设备组件 EEPROM"},
    ]},
    {"name": "LinkMode", "values": [
        {"seq": "001", "value": "LINK_MODE_NONE",         "desc": "不需要链接模式，特别是对于反序列化程序 TPG 模式"},
        {"seq": "002", "value": "LINK_MODE_GMSL1",         "desc": "GMSL1 链路模式"},
        {"seq": "003", "value": "LINK_MODE_GMSL2_6GBPS",   "desc": "GMSL2 6 Gbps 链路模式"},
        {"seq": "004", "value": "LINK_MODE_GMSL2_3GBPS",   "desc": "GMSL2 3 Gbps 链路模式"},
        {"seq": "005", "value": "LINK_MODE_CPHY",           "desc": "C-PHY 链路模式"},
    ]},
    {"name": "Action", "values": [
        {"seq": "001", "value": "LINK_NO_ACTION",   "desc": "无链接"},
        {"seq": "002", "value": "LINK_ENABLE",       "desc": "打开链路"},
        {"seq": "003", "value": "LINK_DISABLE",      "desc": "关闭链路"},
        {"seq": "004", "value": "LINK_RESET",        "desc": "复位链路"},
    ]},
    {"name": "NvMediaStatus", "values": [
        {"seq": "001", "value": "NVMEDIA_STATUS_OK",                  "desc": "Specifies that the operation completed successfully"},
        {"seq": "002", "value": "NVMEDIA_STATUS_BAD_PARAMETER",       "desc": "Specifies that a bad parameter was passed"},
        {"seq": "003", "value": "NVMEDIA_STATUS_PENDING",             "desc": "Specifies that the operation has not finished yet"},
        {"seq": "004", "value": "NVMEDIA_STATUS_TIMED_OUT",           "desc": "Specifies that the operation timed out"},
        {"seq": "005", "value": "NVMEDIA_STATUS_OUT_OF_MEMORY",       "desc": "Specifies that memory allocation failed"},
        {"seq": "006", "value": "NVMEDIA_STATUS_NOT_INITIALIZED",     "desc": "Specifies that the component was not initialized"},
        {"seq": "007", "value": "NVMEDIA_STATUS_NOT_SUPPORTED",       "desc": "Specifies that the operation is not supported"},
        {"seq": "008", "value": "NVMEDIA_STATUS_ERROR",               "desc": "Specifies a catch-all error"},
    ]},
    {"name": "SIPLStatus", "values": [
        {"seq": "001", "value": "NVSIPL_STATUS_OK",                  "desc": "Indicates the operation completed successfully without error"},
        {"seq": "002", "value": "NVSIPL_STATUS_BAD_ARGUMENT",         "desc": "A bad parameter was passed"},
        {"seq": "003", "value": "NVSIPL_STATUS_NOT_INITIALIZED",     "desc": "The component was not initialized"},
        {"seq": "004", "value": "NVSIPL_STATUS_NOT_SUPPORTED",       "desc": "Operation not supported"},
        {"seq": "005", "value": "NVSIPL_STATUS_TIMED_OUT",           "desc": "Operation timed out"},
        {"seq": "006", "value": "NVSIPL_STATUS_OUT_OF_MEMORY",       "desc": "Memory allocation failed"},
        {"seq": "007", "value": "NVSIPL_STATUS_RESOURCE_ERROR",      "desc": "Resource error"},
        {"seq": "008", "value": "NVSIPL_STATUS_ERROR",               "desc": "General error"},
    ]},
]

DEFAULT_COMMON_STRUCTS = [
    {"name": "DeviceParams", "declaration": "typedef struct DeviceParams",
     "intro": "设备的相关参数",
     "fields": [
         {"seq": "1", "name": "cdiRootDev",  "type": "DevBlkCDIRootDevice*", "desc": "CDI 根设备"},
         {"seq": "2", "name": "cdiDev",       "type": "DevBlkCDIDevice*",      "desc": "CDI 设备句柄"},
         {"seq": "3", "name": "pfnDriver",    "type": "DevBlkCDIDeviceDriver*", "desc": "设备驱动函数指针"},
     ]},
    {"name": "EEPROMRequestHandle", "declaration": "typedef struct EEPROMRequestHandle",
     "intro": "从传感器传递到 EEPROM 的相关信息",
     "fields": [
         {"seq": "1", "name": "linkIndex",    "type": "uint8_t",  "desc": "链路索引"},
         {"seq": "2", "name": "requestSize",   "type": "uint32_t", "desc": "请求的数据大小"},
     ]},
    {"name": "LinkParams", "declaration": "typedef struct LinkParams",
     "intro": "用于管理 ser-des 的相关数据",
     "fields": [
         {"seq": "1", "name": "linkIndex",      "type": "uint8_t",  "desc": "链路索引"},
         {"seq": "2", "name": "cameraModule",    "type": "CameraModuleConfig", "desc": "相机模组配置"},
     ]},
    {"name": "CameraModuleConfig", "declaration": "typedef struct CameraModuleConfig",
     "intro": "CameraModule 配置信息",
     "fields": [
         {"seq": "1", "name": "name",          "type": "const char*",   "desc": "模组名称"},
         {"seq": "2", "name": "description",    "type": "const char*",   "desc": "模组描述"},
     ]},
    {"name": "EEPROMProperty", "declaration": "typedef struct EEPROMProperty",
     "intro": "EEPROM 参数",
     "fields": [
         {"seq": "1", "name": "size",   "type": "uint32_t", "desc": "EEPROM 容量"},
         {"seq": "2", "name": "pageSize","type": "uint32_t", "desc": "EEPROM 页大小"},
     ]},
    {"name": "Property", "declaration": "typedef struct Property",
     "intro": "Property 参数",
     "fields": [
         {"seq": "1", "name": "resolution", "type": "const char*", "desc": "分辨率"},
         {"seq": "2", "name": "fps",        "type": "uint32_t",     "desc": "帧率"},
     ]},
    {"name": "Version", "declaration": "typedef struct Version",
     "intro": "API version 参数",
     "fields": [
         {"seq": "1", "name": "major",  "type": "uint8_t", "desc": "主版本号"},
         {"seq": "2", "name": "minor",  "type": "uint8_t", "desc": "次版本号"},
         {"seq": "3", "name": "patch",  "type": "uint8_t", "desc": "补丁版本号"},
     ]},
]

DEFAULT_COMMON_CONFIG_FILES = [
    {"seq": "001", "location": "query/database/imx623/imx623.json",
     "function": "配置 sensor 的相关信息，比如 sensor name、i2c、嵌入行信息等"},
    {"seq": "002", "location": "query/database/imx728/imx728.json",
     "function": "IMX728 sensor 配置文件"},
    {"seq": "003", "location": "query/database/common/platform.json",
     "function": "平台级公共配置（CPU/内存/日志级别等）"},
]


# ---- 第 14 章 系统集成 ----

DEFAULT_SYS_INTEGRATION_PARAGRAPHS = [
    "驱动相关的编译文件以 *.so 文件形式存在，输出成果物提供源码以及编译后的 *.so 库。",
    "集成后由上层 nvsipl_camera / nvsipl_multicast 工具加载并驱动相机模组运行。",
    "集成验收顺序：Deserializer → Serializer → EEPROM → PMIC → Camera Module → nvsipl_camera → nvsipl_multicast。",
]


# ---- 典型函数详情表模板（规则兜底，推送 D 由 AI 填充）----

def default_function_detail(func_name: str, func_decl: str = "", intro: str = "") -> dict:
    """返回单个函数详情表的默认结构（函数声明+介绍+参数空列+返回值空列+流程图占位）。"""
    return {
        "name": func_name,
        "declaration": func_decl or f"<待推送 D 的 AI 从头文件提取 {func_name} 的函数声明>",
        "intro": intro or f"<待推送 D 的 AI 补充 {func_name} 的功能介绍>",
        "parameters": [],   # [{name, type, desc}]
        "returns":  [{"name": "NVSIPL_STATUS_OK", "type": "SIPLStatus",
                       "desc": "定义 NvSIPL 模块中函数返回的状态代码。"}],
        "flowchart_plantuml": "",   # 推送 D 的 AI 生成 PlantUML 流程图
    }


def default_module(component_id: str, slug: str, name: str,
                   title: str, is_security: bool = False) -> dict:
    """返回单个 SWE.3 模块的默认结构（类列表/函数列表为空，待用户或 AI 填充）。"""
    base = {
        "component_id": component_id,
        "slug": slug,
        "name": name,
        "title": title,
        "class_diagram_plantuml": "",     # 类图 PlantUML（推送 D）
        "classes": [],                     # [Swe3Class]
        "functions": [],                   # [Swe3Function] 独立函数（不属于任何类）
        "nv_original_functions": [],       # 原始 NV 函数列表（仅名称+说明）
        "sequence_plantuml": "",           # 单元时序图 PlantUML（推送 D）
    }
    if is_security:
        base["security_goals"] = {
            "authentication": "身份验证与授权要求：所有图像数据的消费端均需经过证书校验，禁止未认证访问。",
            "data_protection": "数据保护要求：图像数据在链路上使用 AES-128 加密，密钥周期性轮换。",
            "key_management": "密钥管理要求：根密钥存储于安全芯片（PKCS#11），运行期派生会话密钥。",
        }
        base["flow_design"] = {
            "detailed_plan": "采用三级认证：Camera Authentication / Communication Authentication / Image Authentication。",
            "implementation": "按 initComAuth → secKeyShare → commKeyExchange → imgKeyExchange 顺序初始化。",
            "flowchart_plantuml": "",
        }
    return base


def default_swe3(components: Optional[list[dict]] = None) -> dict:
    """返回完整的 Swe3Data 默认结构（9 模块骨架 + 共通定义预置）。"""
    modules = []
    for m in DEFAULT_MODULES:
        modules.append(default_module(
            m["id"], m["slug"], m["name"], m["title"],
            is_security=m.get("is_security", False),
        ))

    return {
        "project_code": "",
        # 第 1 章：概述
        "overview": {
            "purpose": "",
            "scope_rows": [dict(r) for r in DEFAULT_SWE3_SCOPE_ROWS],
            "ref_docs": [],       # 复用 SWE.2 的参考文档，用户可覆盖
            "charset": DEFAULT_SWE3_CHARSET,
            "getset_rule": DEFAULT_SWE3_GETSET_RULE,
        },
        # 第 2 章：术语定义
        "terms": [dict(t) for t in DEFAULT_SWE3_TERMS],
        # 第 3 章：软件功能概述（模块构成追溯表，从 SWE.2 自动派生，用户可覆盖）
        "composition": {
            "function_overview": "",
            "composition_rows": [],  # [{swe1_id, req_desc, swe2_id, component, classes, swe3_ids}]
        },
        # 第 4~10 章：各模块详细设计
        "modules": modules,
        # 第 11 章：性能分析设计
        "performance": {
            "paragraphs": list(DEFAULT_PERF_PARAGRAPHS),
        },
        # 第 12 章：函数设计评估
        "function_evaluation": {
            "paragraphs": list(DEFAULT_FUNC_EVAL_PARAGRAPHS),
            "impact_paragraphs": list(DEFAULT_FUNC_IMPACT_PARAGRAPHS),
            "boundary_analysis": [],  # [{design_id, func_name, analysis}]
        },
        # 第 13 章：共通定义
        "common_defs": {
            "constants": [dict(c) for c in DEFAULT_COMMON_CONSTANTS],
            "variables": [dict(v) for v in DEFAULT_COMMON_VARIABLES],
            "enums": [
                {"name": e["name"], "values": [dict(v) for v in e["values"]]}
                for e in DEFAULT_COMMON_ENUMS
            ],
            "structures": [
                {"name": s["name"], "declaration": s["declaration"], "intro": s["intro"],
                 "fields": [dict(f) for f in s["fields"]]}
                for s in DEFAULT_COMMON_STRUCTS
            ],
            "config_files": [dict(c) for c in DEFAULT_COMMON_CONFIG_FILES],
        },
        # 第 14 章：系统集成
        "integration": {
            "paragraphs": list(DEFAULT_SYS_INTEGRATION_PARAGRAPHS),
        },
        "current_step": 0,
        # ---- 推送 D：工程代码集成 + 关注函数 ----
        "push_d": default_push_d(),
    }


def default_push_d() -> dict:
    """推送 D 的默认 push_d 子结构。

    空工程、空扫描、空关注；Camera Security 默认开启（和 UI 的 Switch 默认一致）。
    """
    return {
        "has_camera_security": True,
        "engineering": None,       # 上传后由 engineering_store.build_meta 填入
        "module_code_sources": [], # [{component_id, path_patterns, last_scanned_at, scan_hit_count}]
        "scan_indices": [],        # 轻量引用：[{component_id, stats, scanned_at}]
        "focus_functions": [],     # [{component_id, focused_keys[], manual_additions[]}]
    }


def build_composition_from_swe2(swe2: dict) -> list[dict]:
    """从 SWE.2 的映射表派生"模块构成"追溯表（第 3 章表）。

    每条 SWE.2 映射 → 一行追溯：SWE.1 ID、需求描述、SWE.2 ID、对应组件、类名、SWE.3 设计 ID。
    类名和 SWE.3 ID 为空占位（用户在 ModuleDesignEditor 中维护类后，这里会自动跟进）。
    """
    rows = []
    mappings = (swe2 or {}).get("mappings") or []
    for m in mappings:
        rows.append({
            "swe1_id": m.get("swe1_id", ""),
            "req_desc": (m.get("description") or "")[:80],
            "swe2_id": m.get("swe2_id", ""),
            "component": m.get("component", ""),
            "classes": "",       # 用户填写：如 "CNvMDevice / CNvMSerializer / CNvMMax96717F"
            "swe3_ids": "",      # 用户填写或 AI 填充
        })
    return rows
