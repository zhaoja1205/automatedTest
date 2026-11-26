"""函数功能一句话简介生成 prompt — SWE.2 接口说明列 AI 补全。

输入：一批从头文件/源码扫描出来的函数签名（函数名、返回类型、参数、所在文件）
输出：每个函数一行中文"做什么 + 产物/副作用"简介，用于 SWE.2 docx §4.X.2 接口表的"说明"列。

调用方：Swe2Step → ModuleEditor"[AI 补全说明列]"按钮 → AIService.generate_func_briefs。
覆盖策略在 route 层做（只覆 `[returns:*]` 或空），prompt 不关心。
"""
import json


SYSTEM_PROMPT = """你是一个嵌入式 C/C++ Camera 驱动代码阅读专家，熟悉 NVIDIA Drive-OS NvSIPL / NVMedia / CDI 以及 MAX9295/MAX96712 系列 Ser/Des 驱动。

你的任务：给定一批 C 函数签名（函数名、返回类型、参数、所在文件名），为每个函数写**一句话中文功能简介**，用于 ASPICE SWE.2 软件架构说明文档的接口表"说明"列。

写作规则（严格遵守）：
1. 每条简介 **一句话中文**，长度 15~35 字，不加句号
2. 内容结构：**做什么 + 产物/副作用**。例："读取串行器寄存器并返回解串结果"、"初始化 CDI 设备并注册到设备树"
3. 禁止只写返回类型（如禁止"返回 float_t"、"NvMediaStatus 状态码"），说明是功能不是签名
4. 禁止夸张/推销用语（如"高效""强大""完美"）
5. 用户看过头文件注释和代码，不需要重复参数清单
6. 命名线索：
   - get* / Parse* → 从寄存器/缓冲区读取并解析
   - set* / Config* / Program* → 写入寄存器配置
   - Init* / Create* / Open* → 初始化/申请资源
   - Deinit* / Destroy* / Close* → 释放资源
   - *Float / *Gain / *Exposure → ISP 控制相关
   - Verify* / Check* → 校验
7. 如果函数名完全无法推测含义（如 `func1`、`handler2`），输出 "待补充 - 名称无法推测功能"

输出格式：严格 JSON 数组，每项 `{"idx": 原顺序号, "brief": "一句话简介"}`，顺序与输入对齐。只输出 JSON 数组，不要任何解释文字。"""


def build_func_brief_prompt(targets: list[dict]) -> str:
    """构造用户消息。

    targets: [
        {"idx": 0, "function": "getExposureTimeFloat",
         "returns": "float_t",
         "params": "const uint32_t exposureLine, const uint32_t vmax, const uint32_t fmax",
         "source_path": "cdi_imx623.c"},
        ...
    ]
    """
    # 裁剪过长的 params，防止 token 爆
    slim = []
    for t in targets:
        slim.append({
            "idx": t.get("idx", 0),
            "function": (t.get("function") or "")[:80],
            "returns": (t.get("returns") or "")[:40],
            "params": (t.get("params") or "")[:300],
            "source_path": (t.get("source_path") or "")[:60],
        })
    return (
        "下列是从头文件扫描出来的 C 函数签名，请按规则为每条写一句话中文功能简介：\n"
        + json.dumps(slim, ensure_ascii=False, indent=2)
        + "\n\n输出 JSON 数组，字段 idx + brief，按原顺序。"
    )
