"""
SWE.3 docx 渲染的 Pydantic schema（单一来源）。

和 SWE.2 schema 同策略：
- 所有字段 1:1 对应模板 {{ xxx }} 引用
- 列表字段配 {%tr for %} 遍历
- 嵌套 Function → Module → Swe3Context

对应样本《PreDev_详细设计V1.0.docx》结构：
  1 概述 / 2 术语 / 3 软件功能概述
  4~12 九个模块（每模块含 类图/类列表/函数列表/单元时序图）
  13 性能 / 14 函数评估 / 15 共通定义 / 16 系统集成

设计约束：
- 每个 Function 代表一个函数设计（4.X.2 函数XXX）
- Function.parameters / return_values 是行列表，对应 "Parameter | Type | details"
- Function.flowchart_plantuml 是 PlantUML 源码，渲染时 renderer.add_plantuml_image 挂图
- Class 代表 H3 的 "Class CNvMXxxx" 节，含成员常量/变量表
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, computed_field

# ---------- 封面 / 元信息（复用 SWE.2 的结构，字段一致）----------

class ProjectHistoryRow(BaseModel):
    date: str = ""
    version: str = ""
    author: str = ""
    content: str = ""


class ProjectReviewRow(BaseModel):
    version: str = ""
    review_date: str = ""
    reviewer: str = ""
    approver: str = ""
    opinion: str = ""


class ProjectMeta(BaseModel):
    name: str = ""
    version: str = "V1.0"
    company: str = "中科创达软件股份有限公司"
    history: list[ProjectHistoryRow] = Field(default_factory=list)
    reviews: list[ProjectReviewRow] = Field(default_factory=list)


# ---------- 1 概述 ----------

class ScopeItem(BaseModel):
    no: str = ""
    scope: str = ""         # 范围
    function: str = ""      # 作用及功能


class RefDocItem(BaseModel):
    no: str = ""
    name: str = ""
    version: str = ""
    note: str = ""


class CharsetItem(BaseModel):
    charset: str = ""
    description: str = ""


class TermItem(BaseModel):
    term: str
    definition: str


class Overview(BaseModel):
    purpose: str = ""                                          # 1.1 目的
    scope_text: str = ""                                       # 1.2 范围（预期读者段）
    scope_items: list[ScopeItem] = Field(default_factory=list) # 1.2 范围列表（NO/范围/作用）
    ref_docs: list[RefDocItem] = Field(default_factory=list)   # 1.3 参考文档
    charsets: list[CharsetItem] = Field(default_factory=list)  # 1.4 字符集
    set_get_rule: str = ""                                     # 1.5 成员变量 set/get 规则


# ---------- 3 软件功能概述 ----------

class FunctionOverview(BaseModel):
    description: str = ""                                      # 3.1 功能概述
    module_description: str = ""                               # 3.2 模块构成（文字）
    module_image_key: Optional[str] = None                     # 3.2 功能模块图（PlantUML / PNG 嵌入）
    module_image_note: str = ""                                # 图下备注


# ---------- 需求映射（SWE.2 → SWE.3 溯源，比 SWE.2 多 1 列 "设计 ID"）----------

class ReqMapping(BaseModel):
    swe1_id: str = ""
    swe2_id: str = ""
    design_id: str = ""         # D001-Serializer-function-001
    id_meaning: str = ""
    remark: str = ""
    version: str = ""


# ---------- 模块设计 ----------

class ConstMember(BaseModel):
    seq: int = 0
    name: str = ""
    type: str = ""
    value: str = ""
    description: str = ""


class VarMember(BaseModel):
    seq: int = 0
    name: str = ""
    type: str = ""
    description: str = ""


class ClassItem(BaseModel):
    seq: int = 0
    design_id: str = ""              # D001-Serializer-class-002
    class_name: str = ""
    description: str = ""


class ClassDetail(BaseModel):
    """H3 "Class CNvMXxxx" 节详情（含成员常量/变量表）."""
    class_name: str = ""             # "Class CNvMMax96717F"
    design_id: str = ""              # "[D001-Serializer-class-002]"
    constants: list[ConstMember] = Field(default_factory=list)
    variables: list[VarMember] = Field(default_factory=list)


class FuncListItem(BaseModel):
    """函数列表表中的一行（简表：设计 ID | 函数名 | 说明）."""
    design_id: str = ""
    name: str = ""
    description: str = ""


class ParamRow(BaseModel):
    name: str = ""
    type: str = ""
    details: str = ""


class ReturnRow(BaseModel):
    name: str = ""                   # NVMEDIA_STATUS_OK
    type: str = ""                   # NvMediaStatus
    details: str = ""


class Function(BaseModel):
    """一个函数的详细设计（4.X.Y.Z 函数XXX）."""
    name: str                        # 函数名
    design_id: str = ""              # [D001-Serializer-function-001]
    declaration: str = ""            # 函数声明（完整签名）
    brief: str = ""                  # 函数介绍
    parameters: list[ParamRow] = Field(default_factory=list)
    return_values: list[ReturnRow] = Field(default_factory=list)
    remark: str = ""                 # 备注
    function_desc: str = ""          # 功能说明
    input_desc: str = ""             # 输入参数
    output_desc: str = ""            # 输出参数
    return_desc: str = ""            # 返回值
    exception_desc: str = ""         # 异常处理
    flowchart_plantuml: str = ""     # PlantUML 源码
    flowchart_image_key: Optional[str] = None  # 渲染时挂 InlineImage 的 key


class SequenceItem(BaseModel):
    """单元时序图（H2 层）."""
    title: str = ""
    description: str = ""
    plantuml: str = ""
    image_key: Optional[str] = None


class Module(BaseModel):
    """一个模块的 H1 段（4~12 章任一个）."""
    id: str                          # A001
    component_id: str = ""           # 冗余 id 字段（统一两个命名的来源）
    name: str                        # Serializer
    class_diagram_plantuml: str = ""     # 类图 PlantUML
    class_diagram_image_key: Optional[str] = None
    classes: list[ClassItem] = Field(default_factory=list)       # 类列表表格
    class_details: list[ClassDetail] = Field(default_factory=list)  # H3 Class 详情（可多个）
    functions_intro: str = ""        # "MAX96717详细设计" 这类子章节的介绍段
    function_list: list[FuncListItem] = Field(default_factory=list)  # 函数列表简表
    functions: list[Function] = Field(default_factory=list)      # 各函数详细
    # R4.1：自动从 scan_cache 派生时，non-focus 的函数进这里（渲染"原始 NV 函数列表"子表）
    nv_functions: list[Function] = Field(default_factory=list)
    nv_function_note: str = ""       # "原始NV函数列表" 这类补充说明
    sequence_diagrams: list[SequenceItem] = Field(default_factory=list)  # 时序图


# ---------- 13 性能分析 / 14 函数评估 / 15 共通定义 ----------

class PerformanceItem(BaseModel):
    aspect: str = ""                 # 评估点
    description: str = ""


class Performance(BaseModel):
    items: list[PerformanceItem] = Field(default_factory=list)


class ImpactItem(BaseModel):
    function_name: str = ""
    impact: str = ""


class BoundaryItem(BaseModel):
    function_name: str = ""
    boundary: str = ""


class FunctionEvaluation(BaseModel):
    impacts: list[ImpactItem] = Field(default_factory=list)
    boundaries: list[BoundaryItem] = Field(default_factory=list)


class ConstItem(BaseModel):
    name: str = ""
    type: str = ""
    value: str = ""
    description: str = ""


class EnumItem(BaseModel):
    name: str = ""
    value: str = ""
    description: str = ""


class StructItem(BaseModel):
    name: str = ""
    field_type: str = ""
    field_name: str = ""
    description: str = ""


class ConfigFileItem(BaseModel):
    path: str = ""
    description: str = ""


class CommonDefinitions(BaseModel):
    constants: list[ConstItem] = Field(default_factory=list)   # 15.1 常量
    variables: list[ConstItem] = Field(default_factory=list)   # 15.2 变量
    enums: list[EnumItem] = Field(default_factory=list)        # 15.3 枚举
    structs: list[StructItem] = Field(default_factory=list)    # 15.4 结构体
    config_files: list[ConfigFileItem] = Field(default_factory=list)  # 15.5 配置文件


# ---------- 16 系统集成（和 SWE.2 共用但结构同形）----------

class IntegrationPrinciple(BaseModel):
    key: str
    title: str
    description: str


class Integration(BaseModel):
    order: str = ""
    principles: list[IntegrationPrinciple] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def principles_by_key(self) -> dict[str, IntegrationPrinciple]:
        return {p.key: p for p in self.principles}


# ---------- 顶层 ----------

class Swe3Context(BaseModel):
    """模板渲染顶层 context — 所有字段对应模板 {{ xxx }}."""
    project: ProjectMeta = Field(default_factory=ProjectMeta)
    overview: Overview = Field(default_factory=Overview)
    terms: list[TermItem] = Field(default_factory=list)        # 2 术语
    function_overview: FunctionOverview = Field(default_factory=FunctionOverview)
    mappings: list[ReqMapping] = Field(default_factory=list)
    modules: list[Module] = Field(default_factory=list)
    performance: Performance = Field(default_factory=Performance)
    evaluation: FunctionEvaluation = Field(default_factory=FunctionEvaluation)
    common: CommonDefinitions = Field(default_factory=CommonDefinitions)
    integration: Integration = Field(default_factory=Integration)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def modules_by_id(self) -> dict[str, Module]:
        """模板里用 {{ modules_by_id.A001.functions }} 快速定位。"""
        return {m.id: m for m in self.modules}


__all__ = [
    "ProjectMeta", "ProjectHistoryRow", "ProjectReviewRow",
    "Overview", "ScopeItem", "RefDocItem", "CharsetItem", "TermItem",
    "FunctionOverview",
    "ReqMapping",
    "ConstMember", "VarMember", "ClassItem", "ClassDetail",
    "FuncListItem", "ParamRow", "ReturnRow", "Function", "SequenceItem",
    "Module",
    "Performance", "PerformanceItem",
    "FunctionEvaluation", "ImpactItem", "BoundaryItem",
    "CommonDefinitions", "ConstItem", "EnumItem", "StructItem", "ConfigFileItem",
    "Integration", "IntegrationPrinciple",
    "Swe3Context",
]
