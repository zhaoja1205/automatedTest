/**
 * 用例创建模块类型定义。
 */

/** 单条测试用例（设计阶段） */
export interface DesignCase {
  id?: string
  type: string             // "基本功能" | "故障注入" | "边界值" | "异常"
  method: string           // "基于需求分析" | "等价类划分" | "边界值分析" | "错误推测法"
  desc: string             // 用例描述
  pre: string              // 前置条件
  steps: string            // 测试步骤
  expected: string         // 预期结果
  priority: string         // "P0" | "P1" | "P2"
  changelog?: string       // 版本变更记录
}

/** 覆盖矩阵：模组 × 功能 */
export interface CoverageMatrix {
  modules: string[]        // 行：模组名 e.g. ["IMX728", "IMX623", "OX1G"]
  features: string[]       // 列：功能名 e.g. ["起流", "出图", "帧同步", "故障注入"]
  matrix: boolean[][]      // modules.length × features.length
}

/** 引用的默认值条目 */
export interface DefaultUsed {
  field: string
  default_value: string
  source: string
  applies_to: string
  note: string
}

/** 参考资料条目 */
export interface Reference {
  name: string
  version: string
  summary: string
}

/** 项目元信息（问卷 A1/A2/A3） */
export interface ProjectMeta {
  file_number: string
  title: string
  doc_version: string
  company: string
  change_content: string
  revision_date: string
  modifier: string
  reviewer: string
  approver: string
  references: Reference[]
  os: string
  equipment_model: string
  dev_board: string
  test_object: string
  software_version: string
  test_version: string
  test_cycle: string
  fault_id_from_start: boolean
}

/** 完整的用例创建项目 */
export interface CaseProject {
  project_id: string
  name: string
  created_at: string
  updated_at: string
  meta: ProjectMeta
  coverage_matrix: CoverageMatrix
  functional_cases: DesignCase[]
  fault_cases: DesignCase[]
  defaults_used: DefaultUsed[]
  current_step: number     // 向导进度 0~4
}

/** 项目列表摘要 */
export interface CaseProjectSummary {
  project_id: string
  name: string
  created_at: string
  updated_at: string
  functional_count: number
  fault_count: number
  has_placeholders: boolean
}

/** 占位符条目 */
export interface PlaceholderItem {
  category: string
  case_id: string
  field: string
  placeholder: string
}

/** 导出结果 */
export interface ExportResult {
  json_path: string
  xlsx_internal: string | null
  xlsx_release: string | null
  internal_log: string
  release_log: string
  placeholders: PlaceholderItem[]
  defaults_used: DefaultUsed[]
}

/** 生成用例请求 */
export interface GenerateCasesRequest {
  category?: 'functional' | 'fault' | null
  use_ai: boolean
  overwrite: boolean
}

/** 生成用例结果 */
export interface GenerateCasesResult {
  source: 'rule' | 'ai'
  count: number
  functional_count: number
  fault_count: number
  functional_cases: DesignCase[]
  fault_cases: DesignCase[]
  defaults_used: DefaultUsed[]
  ai_error?: string | null
}
