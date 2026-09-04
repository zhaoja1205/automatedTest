/**
 * 执行历史与报告相关类型定义。
 */

/** 一次测试执行记录 */
export interface TestRun {
  run_id: string
  session_id: string
  status: 'finished' | 'stopped' | 'failed'
  started_at: string
  ended_at: string | null
  duration_seconds: number
  excel_filename: string
  sheets_used: string
  tester_name: string
  test_version: string
  total_count: number
  pass_count: number
  fail_count: number
  block_count: number
  na_count: number
  nt_count: number
  review_count: number
  pass_rate: number
  created_at: string
}

/** 单条用例在某次执行中的结果快照 */
export interface RunResult {
  case_id: string
  case_key: string
  source_sheet: string
  row_number: number
  description: string
  test_steps: string
  expected_result: string
  prerequisites: string
  priority: string
  status: string
  actual_result: string
  match_reason: string
  log_file: string
  duration_seconds: number
  tester: string
  test_version: string
  test_date: string
}

/** 执行详情（含全部用例结果） */
export interface RunDetail {
  run: TestRun
  results: RunResult[]
}

/** 执行对比：两次执行间的 diff */
export interface RunComparisonDiff {
  case_id: string
  description: string
  status_1: string
  status_2: string
  changed: boolean
  direction: 'improved' | 'regressed' | 'unchanged' | 'different'
}

export interface RunComparison {
  run1: TestRun
  run2: TestRun
  diffs: RunComparisonDiff[]
  summary: {
    total: number
    changed: number
    improved: number
    regressed: number
  }
}

/** 测试报告 */
export interface TestReport {
  report_id: string
  run_id: string | null
  title: string
  report_type: 'summary' | 'ai'
  format: 'html' | 'markdown'
  total_count: number
  pass_count: number
  fail_count: number
  pass_rate: number
  tester_name: string
  test_version: string
  created_at: string
  /** 仅在获取单个报告时包含完整内容 */
  content?: string
}

/** 分页响应 */
export interface PaginatedRuns {
  runs: TestRun[]
  total: number
}

export interface PaginatedReports {
  reports: TestReport[]
  total: number
}
