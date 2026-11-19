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


class FunctionDescSegment(BaseModel):
    """4.X.1 多段功能描述（PreDev nvsipl_camera / multicast 口径）。

    每段单独一个标题 + 一段话 + 可选溯源 SWE.1 ID 列表。
    单段模式等价于 title=""、linked_req_ids=[] 的单 FunctionDescSegment。
    """
    title: str = ""
    description: str = ""
    linked_req_ids: list[str] = Field(default_factory=list)


class Component(BaseModel):
    id: str                                 # "A001"
    name: str                               # "Serializer"
    model: str = ""                         # "MAX96717F"
    i2c_addr: str = ""
    function_desc: str = ""                 # 4.X.1（兼容单段文本）
    function_desc_segments: list[FunctionDescSegment] = Field(default_factory=list)
    # 多段模式：nvsipl_camera / multicast（A005/A006）PreDev 口径走这里；
    # 空 list 时回落 function_desc 单段渲染（向后兼容）。
    linked_req_ids: list[str] = Field(default_factory=list)              # 溯源行
    external_interfaces: list[InterfaceItem] = Field(default_factory=list)  # 4.X.2.1
    internal_interfaces: list[InterfaceItem] = Field(default_factory=list)  # 4.X.2.2
    classes: list[ClassItem] = Field(default_factory=list)                  # 4.X.3（仅 A004）
    scenarios: list[ScenarioItem] = Field(default_factory=list)             # 4.X.4+
    # A008 Camera Security 专用（manual_only 路径下仅骨架展示）
    security_goals: str = ""
    security_modules: str = ""


# ---------- 3 软件设计 ----------

class ConfigDbPlatformBlock(BaseModel):
    """3.3.3.1 平台 deviceBlocks 项。"""
    csi_port: str = ""
    phy_mode: str = ""
    deserializer: str = ""
    camera_modules: list[str] = Field(default_factory=list)   # 该 block 下的 cameraModule name 列表
    i2c_addresses: list[str] = Field(default_factory=list)


class ConfigDbPlatform(BaseModel):
    name: str = ""
    description: str = ""
    device_blocks: list[ConfigDbPlatformBlock] = Field(default_factory=list)


class ConfigDbModule(BaseModel):
    """3.3.3.X CameraModule 构成（来自 *_module.json）。"""
    name: str = ""
    description: str = ""
    serializer: str = ""
    sensors: list[str] = Field(default_factory=list)
    eeproms: list[str] = Field(default_factory=list)


class ConfigDbSensorField(BaseModel):
    key: str
    value: str = ""
    note: str = ""


class ConfigDbSensor(BaseModel):
    """3.3.3.2.X sensor 配置字段表。"""
    name: str = ""
    description: str = ""
    i2c_address: str = ""
    fields: list[ConfigDbSensorField] = Field(default_factory=list)


class ConfigDbEeprom(BaseModel):
    name: str = ""
    i2c_address: str = ""
    fields: list[ConfigDbSensorField] = Field(default_factory=list)


class ConfigDbCryptoKey(BaseModel):
    link_id: str = ""
    key_purpose: str = ""
    key_slot: str = ""
    note: str = ""


class ConfigDbCrypto(BaseModel):
    """cryptoConfig.json 摘要（仅在 3.3.3 展示，不流入 4.8）。"""
    name: str = ""
    description: str = ""
    keys: list[ConfigDbCryptoKey] = Field(default_factory=list)


class ConfigDatabase(BaseModel):
    """§3.3.3 配置文件章节的 structured 数据，见 swe2_refactor_plan §2.6。"""
    database_path: str = ""         # engineering_src 下相对路径
    description: str = ""           # 用户 / AI 填的中文总述
    platform: Optional[ConfigDbPlatform] = None
    modules: list[ConfigDbModule] = Field(default_factory=list)
    sensors: list[ConfigDbSensor] = Field(default_factory=list)
    eeproms: list[ConfigDbEeprom] = Field(default_factory=list)
    crypto: Optional[ConfigDbCrypto] = None
    diagram_plantuml: str = ""      # 3.3.3.1 关系图（AI 生成、用户可编辑）


class SoftwareDesign(BaseModel):
    """§3 软件设计（除映射表外的 3.x 内容）。"""
    intro: str = ""                                                     # 3.1 简介
    module_diagram_plantuml: str = ""                                   # 3.2 模块图
    # §3.3.1 / §3.3.2 概念性引言（PreDev 参考：仅给出"外部/内部"定义，具体函数留在 §4.X.2）
    external_iface_intro: str = ""                                      # 3.3.1 整体外部接口说明段
    internal_iface_intro: str = ""                                      # 3.3.2 整体内部接口说明段
    external_interfaces: list[InterfaceItem] = Field(default_factory=list)   # 3.3.1 整体外部接口表（可选手工临时项）
    internal_interfaces: list[InterfaceItem] = Field(default_factory=list)   # 3.3.2 整体内部接口表（可选手工临时项）
    config_files: ConfigDatabase = Field(default_factory=ConfigDatabase)     # 3.3.3 配置文件
    state_diagrams: list[ScenarioItem] = Field(default_factory=list)         # 3.4.1 总状态迁移图
    sequence_diagrams: list[ScenarioItem] = Field(default_factory=list)      # 3.4.2 总时序图


# ---------- 5 资源 ----------

class ResourceKpi(BaseModel):
    category: str                           # 如 "内存" / "CPU" / "延迟"
    item: str                               # 如 "峰值" / "常态" / "单路起流耗时"
    target: str = ""                        # 目标值
    measured: str = ""                      # 实测值
    method: str = ""                        # 测法
    note: str = ""


class Resources(BaseModel):
    """§5 资源消耗（5.1 内存 / 5.2 CPU，PreDev 口径）。"""
    memory_summary: str = ""
    cpu_summary: str = ""
    items: list[ResourceKpi] = Field(default_factory=list)


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
    software_design: SoftwareDesign = Field(default_factory=SoftwareDesign)   # §3
    components: list[Component] = Field(default_factory=list)                 # §4
    resources: Resources = Field(default_factory=Resources)                   # §5
    alternative_arch: str = ""                                                # §6（默认文案由 default 文件填）
    integration: Integration = Field(default_factory=Integration)             # §7

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
    "Component", "FunctionDescSegment",
    "InterfaceItem", "ClassItem", "ScenarioItem",
    "SoftwareDesign", "ConfigDatabase",
    "ConfigDbPlatform", "ConfigDbPlatformBlock", "ConfigDbModule",
    "ConfigDbSensor", "ConfigDbSensorField", "ConfigDbEeprom",
    "ConfigDbCrypto", "ConfigDbCryptoKey",
    "Resources", "ResourceKpi",
    "Integration", "IntegrationPrinciple",
    "Swe2Context",
]
