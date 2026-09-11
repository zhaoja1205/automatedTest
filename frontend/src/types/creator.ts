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

/** 硬件拓扑：Group/Link 与模组型号、sensor I2C 地址、sensor-id、I2C 地址的对应关系 */
export interface CoverageTopologyItem {
  group: string            // GroupA / GroupB / GroupC / GroupD
  decoder_model?: string   // 解串器型号，如 MAX96712
  i2c_bus?: string         // I2C 总线，如 I2C7
  power_addr?: string      // 电源芯片地址 MAX20087
  decoder_addr?: string    // 解串器地址
  bypass_addr?: string     // 加串器地址，如 0x40(7bit)
  camera: string           // 模组型号，如 FOV30 / IMX728
  adr_name?: string        // sensor I2C 地址，如 0x1a(7bit)
  sensor_id?: string       // sensor-id，如 3
  link: string             // Link A/B/C/D
  mask_bit?: string        // 该 Link 在组内对应的半字节，如 0x1/0x10/0x100/0x1000
}

/** 覆盖矩阵：模组 × 功能 */
export interface CoverageMatrix {
  modules: string[]        // 行：模组名 e.g. ["IMX728", "IMX623", "OX1G"]
  features: string[]       // 列：功能名 e.g. ["起流", "出图", "帧同步", "故障注入"]
  matrix: boolean[][]      // modules.length × features.length
  topology?: CoverageTopologyItem[] // 可选：用于精确计算 -m mask 的 Group/Link 拓扑
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
  tested_components?: string
  cam_config?: string
  stream_program?: string
  fps_by_module?: string
  debug_dir?: string
  board_ip?: string
  board_password?: string
  command_args?: string
  feature_criteria?: string
  jump_host_enabled?: boolean
  jump_host_ip?: string
  jump_host_user?: string
  jump_host_password?: string
  jump_host_transfer_dir?: string
  jump_host_can_ssh?: boolean
  execution_mode?: string
  scp_source_path?: string
  scp_target_path?: string
  stream_success_signal?: string
  functional_timeout?: string
  fault_timeout?: string
  special_tests?: string
  fault_expand_mode?: string
  fault_source?: string
  fault_report_mode?: string
  fault_syslog?: boolean
  fault_clear_check?: boolean
  driver_deploy_dir?: string
  test_tool_path?: string
  exception_handling?: string
  test_type_scope?: string
  method_rule?: string
  priority_rule?: string
  id_rule?: string
  generation_scope?: string
  output_format?: string
  screenshot_column?: string
  optional_notes?: string
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
