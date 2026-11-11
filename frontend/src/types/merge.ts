/** 测试用例合并相关类型。 */

export interface MergeSheetInfo {
  name: string
  category: string
  case_count: number
  /** 来源 Sheet 对应的主用例 Sheet；为空表示需要新建 */
  target_sheet?: string
}

export interface MergeCaseItem {
  case_key: string
  case_id: string
  /** 来源表格中真实填写的用例ID；为空表示由系统按行号生成 */
  explicit_id: string
  source_sheet: string
  target_sheet: string
  category: string
  row_number: number
  test_type: string
  requirement_id: string
  description: string
  prerequisites: string
  test_steps: string
  expected_result: string
  priority: string
}

export interface MergePreviewResponse {
  token: string
  main_file: string
  source_file: string
  main_sheets: MergeSheetInfo[]
  source_sheets: MergeSheetInfo[]
  cases: MergeCaseItem[]
}

export interface MergeExecutePayload {
  token: string
  case_keys: string[]
  include_results?: boolean
  skip_duplicates?: boolean
  output_filename?: string
}

export interface MergeExecuteResponse {
  message: string
  filename: string
  download_url: string
  merged_count: number
  skipped_duplicates: string[]
  warnings: string[]
  sheet_counts: Record<string, number>
  created_sheets: string[]
}
