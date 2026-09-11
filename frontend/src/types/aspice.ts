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
  model: string
  i2c_addr: string
}

/** SWE.2 数据 */
export interface Swe2Data {
  mappings: ArchMapping[]
  components: AspiceComponent[]
  current_step: number
}

/** 完整 ASPICE 数据段 */
export interface AspiceData {
  project_code: string
  swe1: Swe1Data
  swe2: Swe2Data
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
