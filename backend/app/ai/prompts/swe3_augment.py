"""SWE.3 推送 D — AI 关注函数展开 / PlantUML 生成的 prompt 模板。

4 组 prompt：
  - FUNCTION_INTRO   函数功能介绍（中文 1~3 段）
  - FUNCTION_FLOW    函数流程图（PlantUML activity 图）
  - CLASS_DIAGRAM    类图（PlantUML class 图）
  - SEQUENCE_DIAGRAM 单元时序图（PlantUML sequence 图）

共用约束：
  - 不要在输出里加任何 markdown 代码围栏（```）；直接给内容
  - PlantUML 必须 @startuml 开头 @enduml 结尾
  - 介绍文字避免营销语气，面向软件工程师
"""
from __future__ import annotations

import json


SYSTEM_PROMPT_COMMON = (
    "你是嵌入式 Camera 驱动软件（NVIDIA Drive-OS NvSIPL 框架）领域的资深软件架构师，"
    "正在撰写一份面向开发人员的 ASPICE SWE.3 详细设计文档。"
    "你的回答将直接写入 docx，因此请使用严谨、无营销色彩的中文。"
)


# ---- 函数介绍 ----

SYSTEM_FUNCTION_INTRO = (
    SYSTEM_PROMPT_COMMON
    + " 本次任务：对单个 C/C++ 函数给出**一句话中文功能介绍**。"
    "要求：\n"
    "1) 只写 1 段、1~2 句，总长控制在 60~120 个汉字，严禁超过 150 字\n"
    "2) 只说清「这个函数做什么」：核心职责 + 关键副作用（如读/写硬件寄存器、抛错）\n"
    "3) 不要罗列参数、不要讲错误处理和边界条件、不要分段、不要列表符号\n"
    "4) 不要重复函数签名、不要写「本函数用于…」这类空洞开头，直接说动作"
)


def build_function_intro_prompt(fn: dict) -> str:
    """构造介绍 prompt。fn 为 Swe3ScannedFunction 字典。"""
    doc = (fn.get("doc_comment") or "").strip()
    doc_block = f"\n已有的 doc 注释（如有参考价值可借用，否则忽略）：\n{doc}\n" if doc else ""
    return (
        f"函数签名：{fn.get('declaration', '')}\n"
        f"所属作用域：{fn.get('_scope', '__free__')}\n"
        f"所在文件：{fn.get('_file', '')}\n"
        f"参数：{json.dumps(fn.get('parameters', []), ensure_ascii=False)}\n"
        f"返回：{json.dumps(fn.get('returns', []), ensure_ascii=False)}\n"
        f"函数体行数：{fn.get('body_lines', 0)}"
        f"{doc_block}\n"
        "请只输出一句话中文功能介绍（60~120 字，不超过 150 字，不要换行）。"
    )


# ---- 函数流程图 ----

SYSTEM_FUNCTION_FLOW = (
    SYSTEM_PROMPT_COMMON
    + " 本次任务：为给定函数生成 PlantUML Activity 流程图。"
    " 要求：\n"
    "1) 用 @startuml / @enduml 包裹，使用 PlantUML activity beta 语法（start / stop / if (...) then (yes) / else (no) / endif / while / endwhile / :action;）\n"
    "2) 如给出函数体源码，必须严格按真实分支结构画；不得凭签名臆造流程\n"
    "3) 节点总数控制在 20 以内；重复/琐碎逻辑折叠为一句\n"
    "4) 节点动作用简体中文，关键 API 名、寄存器名、错误码保留英文\n"
    "5) if 条件文字写具体业务含义（例：『读 EEPROM 失败?』而非 『ret != NVMEDIA_STATUS_OK?』）\n"
    "6) 覆盖参数合法性校验 → 核心逻辑 → 错误路径 → 返回\n"
    "7) 不要加 markdown 围栏、不要加解释文字；只输出 @startuml ... @enduml 之间全部内容"
)


def build_function_flow_prompt(fn: dict) -> str:
    doc = (fn.get("doc_comment") or "").strip()
    doc_block = f"\n已有 doc 注释：\n{doc}\n" if doc else ""
    body = (fn.get("body_text") or "").strip()
    body_block = (
        f"\n函数体源码（按此真实分支结构画，不要臆造）：\n```cpp\n{body}\n```\n"
        if body else "\n（无函数体源码可读，可按签名与 doc 粗略推断主路径）\n"
    )
    return (
        f"函数签名：{fn.get('declaration', '')}\n"
        f"参数：{json.dumps(fn.get('parameters', []), ensure_ascii=False)}\n"
        f"返回：{json.dumps(fn.get('returns', []), ensure_ascii=False)}"
        f"{doc_block}"
        f"{body_block}\n"
        "请只输出 PlantUML activity 图源码。"
    )


# ---- 类图 ----

SYSTEM_CLASS_DIAGRAM = (
    SYSTEM_PROMPT_COMMON
    + " 本次任务：根据一组类（含继承、成员函数列表）生成 PlantUML Class 图。"
    " 要求：\n"
    "1) 用 @startuml / @enduml 包裹\n"
    "2) 列出类名 + 关键成员函数（挑 5~8 个最有代表性的，签名可简化）\n"
    "3) 继承关系用 '<|--' 标出；聚合/组合用 'o--'、'*--'\n"
    "4) 不要加 markdown 围栏；只输出 PlantUML 源码"
)


def build_class_diagram_prompt(module_name: str, classes: list[dict]) -> str:
    simplified = []
    for c in classes:
        if c.get("name") == "__free__":
            continue
        simplified.append({
            "name": c.get("name"),
            "base": c.get("base"),
            "functions": [fn.get("name") for fn in (c.get("functions") or [])][:12],
        })
    return (
        f"模块：{module_name}\n"
        f"类列表：{json.dumps(simplified, ensure_ascii=False, indent=2)}\n"
        "请只输出 PlantUML Class 图源码。"
    )


# ---- 单元时序图 ----

SYSTEM_SEQUENCE_DIAGRAM = (
    SYSTEM_PROMPT_COMMON
    + " 本次任务：生成一个模块内部的关键单元时序图（PlantUML Sequence）。"
    " 要求：\n"
    "1) 用 @startuml / @enduml 包裹\n"
    "2) 列出 3~6 个 participant（优先用关注函数的所属类/模块名）\n"
    "3) 展示初始化 → 工作态 → 关闭 的主路径\n"
    "4) 关键消息用中文动词，函数名保留英文\n"
    "5) 不要加 markdown 围栏；只输出 PlantUML 源码"
)


def build_sequence_diagram_prompt(module_name: str, focus_fns: list[dict]) -> str:
    simplified = []
    for fn in focus_fns[:12]:
        simplified.append({
            "name": fn.get("name"),
            "scope": fn.get("_scope") or fn.get("_class") or "__free__",
            "file": fn.get("_file", ""),
        })
    return (
        f"模块：{module_name}\n"
        f"关注函数：{json.dumps(simplified, ensure_ascii=False, indent=2)}\n"
        "请只输出 PlantUML Sequence 图源码。"
    )
