"""
SWE.2 docx 渲染的 Pydantic schema（单一来源）。

用途三合一：
1. 后端模板渲染（arch_generator.py 新版）的 context 校验
2. GET /aspice/projects/{id}/swe2 响应模型
3. 前端 TypeScript 类型通过脚本 (sync_schema_to_frontend.py) 自动生成

字段命名规则：
- 所有字段都是模板 {{ xxx }} 引用的变量名
- 列表字段要能被 {%tr for item in field %} 遍历
- 新增字段 → 改这里 → 同步前端类型 → 更新模板 placeholder

和现有 Swe2Data（types/aspice.ts + creator_store.py）字段名对齐，
避免存储层迁移。
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, computed_field


# ---------- 封面 / 元信息 ----------

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
    name: str = ""                  # "PREDEV 项目软件架构&概要设计书"
    version: str = "V1.0"
    company: str = "中科创达软件股份有限公司"
    history: list[ProjectHistoryRow] = Field(default_factory=list)
    reviews: list[ProjectReviewRow] = Field(default_factory=list)


# ---------- 1 概述 ----------

class TermItem(BaseModel):
    term: str
    definition: str


class RefDocItem(BaseModel):
    no: str = ""
    name: str = ""
    version: str = ""
    note: str = ""


class AssumptionItem(BaseModel):
    input: str
    time: str
    description: str


class Overview(BaseModel):
    purpose: str = ""                       # 1.1
    scope: str = ""                         # 1.2
    terms: list[TermItem] = Field(default_factory=list)                  # 1.3
    ref_docs: list[RefDocItem] = Field(default_factory=list)             # 1.4
    assumptions: list[AssumptionItem] = Field(default_factory=list)      # 1.5
    project_assumptions: list[str] = Field(default_factory=list)         # 1.5 续


# ---------- 2 需求映射 ----------

class ReqMapping(BaseModel):
    swe1_id: str                            # "PREDEV_001-R001"
    swe2_id: str                            # "PREDEV_001-R001-A001"
    id_meaning: str                         # "Serializer"
    remark: str                             # 需求说明
    version: str = ""                       # "V 1.0"


# ---------- 4 模块设计 ----------

class InterfaceItem(BaseModel):
    source: str                             # "SIPL" / "Camera Module" / ...
    method: str                             # 方法名
    type: str = ""                          # 返回类型/接口类型（自由文本：void / SIPLStatus / Internal interface / ...）
    params: str = ""                        # 多行文本
    description: str = ""


class ClassItem(BaseModel):
    seq: int
    class_name: str
    description: str = ""


class ScenarioItem(BaseModel):
    kind: Literal["状态迁移", "时序"]
    title: str
    description: str = ""
    plantuml: str = ""                      # PlantUML 源码（AI 或手编）
    image_key: Optional[str] = None         # 渲染时模板引擎挂 InlineImage 的 key


class Component(BaseModel):
    id: str                                 # "A001"
    name: str                               # "Serializer"
    model: str = ""                         # "MAX96717F"
    i2c_addr: str = ""
    function_desc: str = ""                 # 4.X.1
    linked_req_ids: list[str] = Field(default_factory=list)              # 溯源行
    external_interfaces: list[InterfaceItem] = Field(default_factory=list)  # 4.X.2.1
    internal_interfaces: list[InterfaceItem] = Field(default_factory=list)  # 4.X.2.2
    classes: list[ClassItem] = Field(default_factory=list)                  # 4.X.3（仅 A004）
    scenarios: list[ScenarioItem] = Field(default_factory=list)             # 4.X.4+
    # A008 Camera Security 专用
    security_goals: str = ""
    security_modules: str = ""


# ---------- 7 系统集成 ----------

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
        """模板里用 {{ integration.principles_by_key.usability.description }}."""
        return {p.key: p for p in self.principles}


# ---------- 顶层 context ----------

class Swe2Context(BaseModel):
    """模板渲染的顶层 context — 所有字段 1:1 对应模板 {{ xxx }}."""
    project: ProjectMeta = Field(default_factory=ProjectMeta)
    overview: Overview = Field(default_factory=Overview)
    mappings: list[ReqMapping] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    integration: Integration = Field(default_factory=Integration)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def components_by_id(self) -> dict[str, Component]:
        """
        模板里用 {{ components_by_id.A001.function_desc }} 快速定位。
        避免写 {{ components[0].function_desc }} 这种脆弱索引。
        缺失组件时模板侧用 {% if components_by_id.A001 %} 做可选包裹。
        """
        return {c.id: c for c in self.components}


__all__ = [
    "ProjectMeta", "ProjectHistoryRow", "ProjectReviewRow",
    "Overview", "TermItem", "RefDocItem", "AssumptionItem",
    "ReqMapping",
    "Component", "InterfaceItem", "ClassItem", "ScenarioItem",
    "Integration", "IntegrationPrinciple",
    "Swe2Context",
]
