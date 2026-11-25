"""
SWE.1 需求分析重构 R1 — Pydantic schema（单一来源）。

用途：
1. 需求回灌向导 A1-A6 的请求/响应校验
2. GET /aspice/projects/{id}/swe1 响应模型扩展
3. 跨项目样本库 / 列映射模板 的存盘结构

设计约束（见 backend/docs/swe1_refactor_plan.md）：
- 保持向后兼容：旧项目存盘的 Requirement 没有新字段，读时补默认值
- ID 规则遵循 Pangu_ASPICE：OR = {code}_{seq}，SWE.1 = {OR}-R{seq}
- 回灌尊重工程师已填的 or_id/req_id，仅为空时派生
- 同项目冲突主键 (project_id, req_id)；跨项目天然隔离
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- 枚举 ----------

# 需求来源类型：区分 UI 是否要走 AI 置信度 / 是否作 RAG 样本
SourceType = Literal[
    "customer_raw",        # 客户原始文档（AI 候选产出）
    "engineer_processed",  # 工程师已处理好的需求表（回灌主力，80% 场景）
    "manual",              # 工程师在工具里手工新增
    "ai_suggested",        # AI 候选但未人工确认
    "legacy",              # 旧项目升级遗留
]

# 需求评审态：note 用于"已被其他条覆盖"的说明行，UI 淡灰
ReviewStatus = Literal[
    "pending",    # 待评审（回灌有变更 / AI 候选）
    "accepted",   # 已采纳（新增直接入 / 评审通过）
    "rejected",   # 已驳回（RAG 反例样本）
    "note",       # 说明条目（coverage_of 行，不独立评审）
]


# ---------- Requirement 新字段（扩展既有 24 列 skill 模板，不删） ----------

class RequirementExtFields(BaseModel):
    """R1 新增 8 字段，叠加在既有 Requirement 之上。

    注意：真正存盘的 Requirement 是 dict（creator_store 为平铺字典），
    本模型只用于 API 校验 / 文档生成，不改存储层。
    """

    external_id: str = ""                     # 客户原始 ID，如 Req_Sensor_135，用于溯源
    source_doc: str = ""                      # 来源文档文件名
    source_section: str = ""                  # 章节号（PreDev B 列）
    source_type: SourceType = "manual"        # 来源类型枚举
    review_status: ReviewStatus = "accepted"  # 评审态（手工新增默认已采纳）
    confidence: float = 1.0                   # 置信度 0-1，手工 / 回灌 =1，AI 候选按算法
    coverage_of: str = ""                     # 覆盖说明：被谁覆盖（指向另一条 req_id/external_id）
    requirement_module: str = ""              # PreDev 分组行识别出的模块名（"帧同步"等），仅展示
    arch_doc_hint: str = ""                   # 回灌时解析出的"建议交给 A00x 组件"提示（可选）


def default_requirement_ext() -> dict:
    """为 _default_aspice 的 requirement 补默认字段用；读时补齐。"""
    return RequirementExtFields().model_dump()


# ---------- 需求来源文件（swe1.sources[]） ----------

class SourceFile(BaseModel):
    """工程师上传的需求文档记录（R1 存盘于 swe1.sources[]）。"""

    file_id: str                              # UUID，和 runtime 下存文件同名
    original_name: str                        # 用户上传时的原始文件名
    source_type: SourceType = "engineer_processed"
    uploaded_at: str                          # ISO 字符串
    size_bytes: int = 0
    sheet_count: int = 1                      # Excel 多 sheet 时
    row_count: int = 0                        # 解析出需求条数
    mapping_template_id: str = ""             # 本次 ingest 用的映射模板 id（若有）
    md5: str = ""                             # 文件指纹，防重复 upload


# ---------- 覆盖说明行（swe1.coverage_notes[]） ----------

class CoverageNote(BaseModel):
    """PreDev 里 OR=NA/ReqID=NA 但 Content 写'XXX 已覆盖本条'的说明行。

    入库但不独立评审，UI 淡灰显示，作 RAG 反例样本。
    双向关联：from_req_id 指向本条 'note' 需求的 req_id，
    covered_by 指向正式需求的 req_id / external_id。
    """

    from_req_id: str                          # 说明行自身的 req_id
    covered_by: str                           # 覆盖者的 req_id / external_id
    covered_by_external: bool = False         # covered_by 是 external_id 还是本工具 req_id
    note_text: str = ""                       # 原文（用于反例 RAG）


# ---------- 列映射模板（跨项目复用） ----------

class ColumnMapping(BaseModel):
    """单列映射：Excel 列头 → Requirement 字段。"""

    excel_header: str                         # 原 Excel 列头文本
    excel_col_index: int                      # 列序号（0-based），和 header 一起用于去同名列
    field: str                                # Requirement 字段名，如 'content' / 'external_id'
    required: bool = False                    # 是否必填（如 content/external_id）


class MappingTemplate(BaseModel):
    """保存在 runtime/swe1_mapping_templates/*.json，跨项目复用。

    匹配策略：先按 header_fingerprint（md5 of 排序后列头）精确匹配，
    命中则自动套用；否则用户手工 A3 选，选完存模板。
    """

    template_id: str
    name: str                                 # 用户命名，如 "PreDev 23 列模板"
    created_at: str
    header_fingerprint: str                   # 列头 md5
    headers: list[str]                        # 原始列头快照
    mappings: list[ColumnMapping]
    row_type_rules: dict = Field(default_factory=dict)
    # row_type_rules 示例：
    # {
    #   "group_row": {"only_col": 0, "exclude_prefix": ["PREDEV_", "REQ_"]},
    #   "coverage_row": {"any_na": ["external_id", "req_id"], "keyword": "已覆盖"}
    # }
    inherit_cols: list[int] = Field(default_factory=list)  # 合并单元格继承的列序号
    description: str = ""                     # 可选说明


# ---------- 回灌向导 API ----------

class IngestPreviewRequest(BaseModel):
    """A2 - 上传文件后请求预览。"""

    project_id: str
    file_id: str                              # upload 后返回
    sheet_index: int = 0                      # Excel 多 sheet 选哪页
    mapping_template_id: str = ""             # 可选，自动套模板


class ParsedRow(BaseModel):
    """预览返回的单行结构。row_type 区分 4 种类型。"""

    row_type: Literal["header", "group", "main", "sub", "coverage", "skip"]
    excel_row: int                            # 原 Excel 行号（1-based），便于用户回查
    data: dict = Field(default_factory=dict)  # 字段 → 值；header/group 时 data 只含 raw
    parent_excel_row: int = 0                 # 子需求行指向父行；group 继承模块名用
    conflict_with_existing: bool = False      # 和本项目已有 req_id 冲突
    conflict_diff: dict = Field(default_factory=dict)  # 字段级 diff，UI 展示
    warnings: list[str] = Field(default_factory=list)


class IngestPreviewResponse(BaseModel):
    """A3/A4 - 预览面板数据。"""

    file_id: str
    headers: list[str]
    suggested_mapping: list[ColumnMapping]    # 若命中模板则套用，否则规则推断
    suggested_template_id: str = ""           # 若命中已有模板
    rows: list[ParsedRow]
    stats: dict = Field(default_factory=dict)
    # stats 示例：{"total": 122, "main": 85, "coverage": 7, "group": 10, "conflict": 3}


class IngestConfirmRequest(BaseModel):
    """A6 - 用户在预览面板确认后提交。"""

    project_id: str
    file_id: str
    mapping: list[ColumnMapping]              # 用户最终确认的映射
    accepted_excel_rows: list[int]            # 用户勾选要入库的 Excel 行号
    save_as_template: bool = False
    template_name: str = ""
    conflict_resolution: dict = Field(default_factory=dict)
    # conflict_resolution: {"<req_id>": "overwrite" | "skip" | "mark_pending"}


class IngestConfirmResponse(BaseModel):
    """入库完成反馈。"""

    inserted: int
    updated: int
    skipped: int
    marked_pending: int
    coverage_notes_added: int
    template_id: str = ""                     # 若 save_as_template 则返回新建 id
