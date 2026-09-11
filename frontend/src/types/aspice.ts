/**
 * ASPICE 文档模块类型定义。
 */

/** SWE.1 单条需求项 */
export interface Requirement {
  or_id: string             // OR ID，如 Pangu_001
  req_id: string            // SWE.1 需求 ID，如 Pangu_001-R001
  software_mark: string     // 原始/新增/删除/变更
  content: string           // 需求描述
  category: string          // 分类
  milestone: string        // 预计完成里程碑
  owner: string
  input_source: string      // 客户原始需求来源
  priority: number          // 1~4
  operation?: string        // 操作描述
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

/** SWE.1 数据 */
export interface Swe1Data {
  requirements: Requirement[]
  topology: AspiceTopology[]
  kpi: KpiItem[]
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
