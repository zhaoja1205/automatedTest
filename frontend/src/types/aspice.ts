/**
 * ASPICE 文档模块类型定义。
 */

/** SWE.1 单条需求项（对齐 skill 24 列 Excel 模板） */
export interface Requirement {
  or_id: string             // F 列 OR ID，如 Pangu_001
  req_id: string            // H 列 SWE.1 需求 ID，如 Pangu_001-R001
  software_mark: string     // E 列 原始/新增/删除/变更 → Original/Add/Deleted/Modified
  content: string           // D 列 需求描述（双语用 ' / ' 分隔）
  // skill 24 列扩展字段：
  input_source: string      // A 列 输入文档名
  chapter: string            // B 列 章节号
  no: string                 // C 列 原始序号
  or_desc: string            // G 列 OR 描述
  sw_req_desc: string        // I 列 软件需求功能描述
  test_case_id: string       // J 列 测试用例 ID
  category: string          // L 列 分类（全角逗号枚举）
  asil: string               // M 列 安全等级 QM/ASIL A-D/N/A
  correctness: string        // N 列 需求正确性
  feasibility: string        // O 列 需求可行性
  exception: string          // P 列 异常处理
  priority: number          // Q 列 优先级 1-3
  milestone: string          // R 列 项目发布时间（release_time）
  ra_deadline: string        // S 列 RA 截止时间
  actual_time: string        // T 列 实际完成时间
  release_version: string    // U 列 功能发布版本
  owner: string              // V 列 负责人
  memo: string               // W 列 备注
  operation: string          // SRS .2 操作描述（双语）
  analysis: string           // SRS .4 分析（双语）
}

/** 硬件拓扑项 */
export interface AspiceTopology {
  group: string
  sensor_model: string
  fov: string
}

/** KPI 非功能需求项 */
export interface KpiItem {
  seq: string
  desc: string
}

/** SWE.1 风险项 */
export interface RiskItem {
  req_id: string
  function: string
  risk: string
  solution: string
  owner: string
}

/** SWE.1 数据 */
export interface Swe1Data {
  requirements: Requirement[]
  topology: AspiceTopology[]
  kpi: KpiItem[]
  risks: RiskItem[]
  current_step: number
}

/** SWE.2 映射行 */
export interface ArchMapping {
  swe1_id: string           // 如 Pangu_001-R001
  swe2_id: string           // 如 Pangu_001-R001-A001
  component_id: string      // A001~A008
  component: string
  description: string
  release_version: string
}

/** SWE.2 组件属性 */
export interface AspiceComponent {
  id: string               // A001~A008
  name: string
  model?: string
  i2c_addr?: string
  // 推送 A 新增：全部 optional，便于旧项目兼容
  function_desc?: string                  // 4.X.1 功能描述正文
  linked_req_ids?: string[]               // 用户手动追加的溯源 SWE.2 ID
  external_interfaces?: InterfaceItem[]
  internal_interfaces?: InterfaceItem[]
  classes?: ClassItem[]                   // A004 Camera Module 用
  scenarios?: ScenarioItem[]
  security_goals?: string                 // A008 专用
  security_modules?: string
}

/** SWE.2 概述元数据（1.3 ~ 1.5）—— 推送 A 新增 */
export interface TermItem { term: string; definition: string }
export interface RefDocItem { no: string; name: string; version: string; note: string }
export interface AssumptionItem { input: string; time: string; description: string }

export interface Swe2Overview {
  purpose: string
  scope: string
  terms: TermItem[]
  ref_docs: RefDocItem[]
  assumptions: AssumptionItem[]
  project_assumptions: string[]
}

/** SWE.2 系统集成（7.x）—— 推送 A 新增 */
export interface IntegrationPrinciple { key: string; title: string; description: string }
export interface Swe2Integration {
  order: string
  principles: IntegrationPrinciple[]
}

/** SWE.2 组件接口项（4.X.2.1 / 4.X.2.2）—— 推送 A 新增，推送 B 由 AI 填充 */
export interface InterfaceItem {
  source: string              // 接口溯源 (SIPL / Camera Module / …)
  method: string              // 方法名
  type: '外部接口' | '内部接口'
  params: string              // 多行文本
  description: string
}

/** 类描述项（Camera Module 专用，4.4.2）—— 推送 A 新增 */
export interface ClassItem {
  seq: number
  class_name: string
  description: string
}

/** 场景（状态迁移/时序图）—— 推送 A 新增 */
export interface ScenarioItem {
  kind: '状态迁移' | '时序'
  title: string
  description: string
  plantuml: string
  rendered_at?: string
}

/** SWE.2 数据 */
export interface Swe2Data {
  mappings: ArchMapping[]
  components: AspiceComponent[]
  current_step: number
  // 推送 A 新增
  overview?: Swe2Overview
  integration?: Swe2Integration
}

/** 完整 ASPICE 数据段 */
export interface AspiceData {
  project_code: string
  swe1: Swe1Data
  swe2: Swe2Data
  swe3?: Swe3Data        // 推送 C 新增
}

/** 解析需求结果 */
export interface ParseRequirementsResult {
  source: 'rule' | 'ai'
  count: number
  requirements: Requirement[]
  ai_error?: string | null
}

/** 生成架构结果 */
export interface GenerateArchResult {
  source: 'rule' | 'ai'
  count: number
  mappings: ArchMapping[]
  ai_error?: string | null
}

/** SWE.2 回灌结果 */
export interface ImportSwe2Result {
  count: number
  component_count: number
  mappings: ArchMapping[]
  components: AspiceComponent[]
}

/** 项目列表摘要 */
export interface AspiceProjectSummary {
  project_id: string
  project_type?: string
  name: string
  created_at: string
  updated_at: string
}

/** 项目基本信息 */
export interface AspiceProjectInfo extends AspiceProjectSummary {}

/** 导出结果 */
export interface AspiceExportResult {
  docx: string
  xlsx: string
}

/** 校验结果 */
export interface ValidateResult {
  errors: string[]
  warnings: string[]
  passed: string[]
  report: string
  has_errors: boolean
}

/* ======================= SWE.3 详细设计（推送 C 新增） ======================= */

/** 1.2 范围行 */
export interface Swe3ScopeRow { no: string; scope: string; function: string }

/** 1.3 参考文档行（复用 RefDocItem 字段） */

/** 1 概述 */
export interface Swe3Overview {
  purpose: string
  scope_rows: Swe3ScopeRow[]
  ref_docs: RefDocItem[]
  charset: string
  getset_rule: string
}

/** 3 软件功能概述 — 模块构成追溯行（SWE.1→SWE.2→类→SWE.3） */
export interface Swe3CompositionRow {
  swe1_id: string
  req_desc: string
  swe2_id: string
  component: string
  classes: string          // 多个类用 '/' 或 '、' 分隔
  swe3_ids: string         // D001-xxx-class-001; D001-xxx-function-001
}

export interface Swe3Composition {
  function_overview: string
  composition_rows: Swe3CompositionRow[]
}

/** 类成员常量 / 变量 */
export interface Swe3MemberConstant { seq: string; name: string; type: string; value: string; desc: string }
export interface Swe3MemberVariable { seq: string; name: string; type: string; desc: string }

/** 函数参数 / 返回值 */
export interface Swe3FunctionParameter { name: string; type: string; desc: string }
export interface Swe3FunctionReturn { name: string; type: string; desc: string }

/** 函数详情 */
export interface Swe3Function {
  design_id: string                     // D001-Serializer-function-001
  name: string                           // 函数名
  declaration: string                    // 完整声明（含返回值 + 参数）
  intro: string                          // 函数介绍
  parameters: Swe3FunctionParameter[]
  returns: Swe3FunctionReturn[]
  flowchart_plantuml: string            // 流程图源码；为空则导出占位
  /** 可选：扫描阶段符号 key，用于单条 AI 补齐（从关注函数生成时自动带入） */
  source_key?: string
}

/** 类 */
export interface Swe3Class {
  design_id: string                     // D001-Serializer-class-001
  class_name: string
  description: string
  path: string                           // 源文件路径
  constants: Swe3MemberConstant[]
  variables: Swe3MemberVariable[]
  functions: Swe3Function[]
}

/** Camera Security 功能安全目标 */
export interface Swe3SecurityGoals {
  authentication: string
  data_protection: string
  key_management: string
}

/** Camera Security 流程设计 */
export interface Swe3SecurityFlow {
  detailed_plan: string
  implementation: string
  flowchart_plantuml: string
}

/** 模块（4~10 章） */
export interface Swe3Module {
  component_id: string                   // A001~A009
  slug: string                            // 用于 design ID 派生，如 Serializer / IMX728 / Campwr
  name: string                            // 展示名
  title: string                           // 章节标题
  class_diagram_plantuml: string
  classes: Swe3Class[]
  functions: Swe3Function[]              // 不属于任何类的独立函数
  nv_original_functions: Swe3Function[]  // 原始 NV 函数列表（仅部分模块使用）
  sequence_plantuml: string              // 单元时序图
  security_goals?: Swe3SecurityGoals    // A008 专用
  flow_design?: Swe3SecurityFlow         // A008 专用
}

/** 11 性能分析 */
export interface Swe3Performance { paragraphs: string[] }

/** 12 函数设计评估 — 边界值分析行 */
export interface Swe3BoundaryAnalysisItem {
  design_id: string
  func_name: string
  analysis: string
}

export interface Swe3FunctionEvaluation {
  paragraphs: string[]
  impact_paragraphs: string[]
  boundary_analysis: Swe3BoundaryAnalysisItem[]
}

/** 13 共通定义 */
export interface Swe3EnumValue { seq: string; value: string; desc: string }
export interface Swe3Enum { name: string; values: Swe3EnumValue[] }

export interface Swe3StructField { seq?: string; name: string; type: string; desc: string }
export interface Swe3Structure {
  name: string
  declaration: string
  intro: string
  fields: Swe3StructField[]
}

export interface Swe3CommonConstant { seq: string; name: string; value: string; desc: string }
export interface Swe3CommonVariable { seq: string; name: string; type: string; value: string; desc: string }
export interface Swe3ConfigFile { seq: string; location: string; function: string }

export interface Swe3CommonDefs {
  constants: Swe3CommonConstant[]
  variables: Swe3CommonVariable[]
  enums: Swe3Enum[]
  structures: Swe3Structure[]
  config_files: Swe3ConfigFile[]
}

/** 14 系统集成 */
export interface Swe3Integration { paragraphs: string[] }

/** SWE.3 顶层数据 */
export interface Swe3Data {
  project_code?: string
  overview: Swe3Overview
  terms: TermItem[]
  composition: Swe3Composition
  modules: Swe3Module[]
  performance: Swe3Performance
  function_evaluation: Swe3FunctionEvaluation
  common_defs: Swe3CommonDefs
  integration: Swe3Integration
  current_step: number
  /** 推送 D：工程代码集成（可选，老项目兼容） */
  push_d?: Swe3PushDData
}

/** SWE.3 派生接口的响应（规则派生） */
export interface GenerateSwe3Result {
  message: string
  composition_rows: number
  modules: number
}

/* ======================= SWE.3 推送 D（工程代码集成） ======================= */
/* UI 版本：mock 层数据 + store 类型；后端接通后类型保持不变。 */

/** 工程 zip 上传后端返回的元信息 */
export interface Swe3EngineeringUpload {
  zip_name: string
  uploaded_at: string              // ISO 时间
  include_root: string             // 相对 zip 根的 include 目录
  code_roots: string[]             // 相对 zip 根的工程代码目录（可多个）
  total_files: number
  sdk_files: number
  custom_files: number
  file_tree_sample: string[]       // 预览用的前 N 个文件相对路径
}

/** 模块代码路径配置（一个 glob 行） */
export interface Swe3PathPattern {
  pattern: string                  // e.g. include/serializer/**
  exclude?: boolean                // true=排除规则
}

/** 一个模块绑定的代码源配置 */
export interface Swe3ModuleCodeSource {
  component_id: string
  path_patterns: Swe3PathPattern[] // 可多条，支持一模块多目录
  last_scanned_at?: string
  scan_hit_count?: number          // 规则命中的文件数
}

/** 扫描结果中的单个函数 */
export interface Swe3ScannedFunction {
  key: string                      // 唯一键：{file}::{class_or___free__}::{name}::{param_sig_sha1[0:8]}
  name: string
  declaration: string
  parameters: Swe3FunctionParameter[]
  returns: Swe3FunctionReturn[]
  doc_comment: string
  body_lines: number
  body_text?: string                // 推送 G：scanner 保留的函数体源码（≤8KB）
  extracted_by: 'regex' | 'clang' | 'ai' | 'manual'
  is_sdk: boolean
  ai_intro?: string
  ai_flowchart?: string
  // 推送 G 新增：diff/豁免/AI 状态
  diff_status?: 'added' | 'modified' | 'unchanged' | 'unchanged_sdk'
  exempt_from_ai?: boolean
  ai_status?: 'pending' | 'ok' | 'failed' | 'exception'
  ai_retry_count?: number
  ai_last_error?: string
  ai_exception_note?: string
}

/** 扫描结果中的单个类 */
export interface Swe3ScannedClass {
  name: string                     // 类名；'__free__' 代表自由函数
  base: string                     // 父类名字符串；'' 表示无（可能形如 "Public A, Private B"）
  doc_comment: string
  constants: Swe3MemberConstant[]
  variables: Swe3MemberVariable[]
  functions: Swe3ScannedFunction[]
}

/** 扫描结果中的单个文件 */
export interface Swe3ScannedFile {
  path: string                     // 相对 zip 根
  sha1: string
  is_sdk: boolean
  classes: Swe3ScannedClass[]
}

/** 单模块扫描结果 */
export interface Swe3ScanIndex {
  component_id: string
  scanned_at: string
  scanner_version: string
  files: Swe3ScannedFile[]
  stats: {
    total_files: number
    total_classes: number
    total_functions: number
    sdk_functions: number
    custom_functions: number
  }
}

/** 关注函数（存一组 key，联动勾选在前端运行时推导） */
export interface Swe3FocusFunctions {
  component_id: string
  focused_keys: string[]           // 用户主动勾选的 key
  manual_additions: Swe3ScannedFunction[]  // 用户手工添加的未扫到函数
  /**
   * 二级入口：用户勾选"仅看项目新增"并点"批量加入关注"后落下来的 diff.added 函数 key。
   * 和 focused_keys 并集作为 L5 展开入口；允许用户先全量入 L5、再按需剔除。
   */
  included_added_keys?: string[]
}

/** AI 批量补齐进度（SSE / mock timer 共享结构） */
export interface Swe3AiAugmentProgress {
  total: number
  completed: number
  current_key?: string
  current_name?: string
}

/** SWE.3 推送 D 新增顶层数据（挂到 Swe3Data 下） */
export interface Swe3PushDData {
  has_camera_security: boolean
  engineering?: Swe3EngineeringUpload
  module_code_sources: Swe3ModuleCodeSource[]
  scan_indices: Swe3ScanIndex[]
  focus_functions: Swe3FocusFunctions[]
}
