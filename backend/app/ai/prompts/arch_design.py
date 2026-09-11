"""架构设计生成 prompt — SWE.2 架构设计。

基于 SWE.1 需求项生成组件映射建议 + 接口描述。
"""
import json

SYSTEM_PROMPT = """你是一个 Camera 驱动软件架构设计专家，熟悉 ASPICE SWE.2 软件架构设计流程和 NVIDIA Drive-OS NvSIPL 架构。

软件系统固定包含 8 个组件：
- A001 Serializer：串行器配置和控制、获取串行器故障信息
- A002 Deserializer：解串器配置和控制、获取解串器故障信息
- A003 EEPROM：读取模组信息、内参数据、序列号
- A004 Camera Module：模组集成（Sensor+Ser+Des初始化控制）
- A005 nvsipl_camera：单路测试工具（起流/帧同步/SOF/内参/故障）
- A006 nvsipl_multicast：多路同点工具（集成故障/内参/时间戳）
- A007 PMIC：电源芯片配置
- A008 Camera Security：三级认证（Camera/Communication/Image Authentication）

你的任务：根据 SWE.1 需求项列表，为每条需求判断应落到哪些组件实现，并给出接口描述建议。

输出要求：
1. 严格输出 JSON 数组，每个元素表示一个需求到组件的映射
2. 字段：
   - req_id: SWE.1 需求ID
   - component_ids: 组件ID列表（如 ["A001","A002","A004"]）
   - interface_desc: 该组件实现此需求时的接口描述建议
3. 一条需求可落到多个组件，每个组件一项

只输出 JSON 数组。"""


def build_arch_design_prompt(requirements: list[dict]) -> str:
    """构建用户消息。"""
    req_summary = []
    for r in requirements:
        req_summary.append({
            "req_id": r.get("req_id", ""),
            "content": r.get("content", "")[:100],
            "category": r.get("category", ""),
        })
    return f"""请为以下 SWE.1 需求项生成 SWE.2 组件映射：

{json.dumps(req_summary, ensure_ascii=False, indent=2)}

输出 JSON 数组，示例：
[
  {{
    "req_id": "Pangu_001-R001",
    "component_ids": ["A001", "A002", "A004"],
    "interface_desc": "Serializer/Deserializer配置寄存器，Camera Module集成初始化"
  }}
]"""
