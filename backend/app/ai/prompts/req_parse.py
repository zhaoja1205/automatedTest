"""客户需求解析 prompt — SWE.1 需求分析。

把客户原始需求文本解析为结构化需求项列表，自动分配 OR ID + ReqID。
"""
import json

SYSTEM_PROMPT = """你是一个 Camera 驱动软件需求分析专家，熟悉 ASPICE SWE.1 软件需求分析流程和 NVIDIA Drive-OS NvSIPL 架构。

你的任务：把客户提供的原始需求（可能是自然语言段落、会议纪要、邮件等杂乱文本）解析为结构化的软件需求项列表。

输出要求：
1. 严格输出 JSON 数组，每个元素是一个需求项对象
2. 每个需求项包含字段：
   - content: 需求描述（一句话，清晰描述测试对象和目标）
   - category: 需求分类（如 "Driver Basic Function" / "Trigger Sync and Timestamp" / "EEPROM" / "Fault Detection" / "Security" / "Performance"）
   - priority: 优先级 1~4（1最高，参考：基础起流/出图=1，ISP/EEPROM=2，帧同步/时间戳=3）
   - owner: 需求负责人（若文本中未提及则留空）
   - milestone: 预计完成里程碑（若文本中未提及则留空）
   - operation: 操作描述（如何验证该需求，若文本中有则提取）
3. 一条需求只输出一个需求项，不要合并多个功能点
4. 忽略纯背景说明、免责声明、非功能性的文字
5. 需求描述保留原始技术细节（如帧率数值、精度要求、I2C地址等）

只输出 JSON 数组，不要输出任何其他文字。"""


def build_req_parse_prompt(raw_text: str, project_code: str) -> str:
    """构建用户消息。"""
    return f"""项目代号：{project_code}

请解析以下客户原始需求文本，提取结构化软件需求项：

---
{raw_text[:6000]}
---

输出 JSON 数组，示例：
[
  {{
    "content": "驱动可正常配置SerDes和Sensor，确保正常输出RAW图像",
    "category": "Driver Basic Function",
    "priority": 1,
    "owner": "",
    "milestone": "",
    "operation": "使用nvsipl_camera运行所有Camera并输出预览"
  }}
]"""
