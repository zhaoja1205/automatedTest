export interface TestCase {
  case_id: string
  case_key: string
  test_type: string
  requirement_id: string
  design_method: string
  description: string
  prerequisites: string
  test_steps: string
  expected_result: string
  priority: string
  selected: boolean
  row_number: number
  source_sheet: string
  actual_result: string
  status: string
  bug_id: string
  log_file: string
  tester: string
  test_date: string
  test_version: string
  remarks: string
  expected_keywords: string[]
  /** AI 判定时摘录的关键证据行 */
  ai_evidence?: string[]
}

export type CaseCategory = 'functional' | 'fault' | 'stability'

export type SSHLoginMode = 'direct' | 'jump'

export interface SSHConfig {
  login_mode: SSHLoginMode
  host: string
  port: number
  username: string
  password: string
  target_password: string
  timeout: number
  jump_host: string
  jump_port: number
  jump_username: string
  jump_password: string
}

export interface SSHStatus {
  connected: boolean
  tested: boolean
  mode: SSHLoginMode
  message: string
}

export interface WorkspaceConfig {
  tester_name: string
  test_version: string
  default_remote_path: string
  driver_path: string
  nito_override_path: string
  nito_override_enabled: boolean
  image_storage_path: string
  image_storage_enabled: boolean
  image_download_path: string
  image_download_enabled: boolean
  cam_rotate_cfg_path: string
  cam_rotate_cfg_enabled: boolean
  run_prerequisites: boolean
  auto_save: boolean
  output_dir: string
}

export interface ExecutionTask {
  task_id: string
  status: 'idle' | 'starting' | 'running' | 'stopped' | 'failed' | 'finished'
  selected_count: number
  completed_count: number
  current_case_id: string
  started_at: string | null
  ended_at: string | null
  message: string
  result_file: string
}

export interface LogEntry {
  level: 'info' | 'warning' | 'error'
  message: string
  timestamp: number
}

export interface ExecutionProgress {
  current: number
  case_key?: string
  total: number
  case_id: string
  /** 当前细分执行阶段，如「正在执行命令」「正在 AI 分析判定结果」 */
  message?: string
}

export interface ConfirmRequest {
  confirm_id: string
  step_desc: string
  timeout: number
}

export interface TestResultSummary {
  case_id: string
  status: string
  start_time: string | null
  end_time: string | null
  log_file: string
  match_log_file: string
  actual_output: string
  match_reason: string
  error_msg: string
  duration: number
}

/** Excel 中 BugList统计 页的一行数据 */
export interface BugListItem {
  no: string
  bug_id: string
  module: string
  description: string
  version: string
  severity: string
  status: string
  tester: string
  date: string
  effective: string
  comment: string
  row_number: number
  source_sheet: string
}

export interface UploadExcelResponse {
  message: string
  case_count: number
  sheets: string[]
  bug_sheet: string
  bug_list: BugListItem[]
}

export interface ExecuteStartResponse {
  message: string
  selected_count: number
  task_id: string
}

export interface ApiMessageResponse {
  message: string
}

export interface WsBaseMessage {
  type: string
}

export interface WsLogMessage extends LogEntry, WsBaseMessage {
  type: 'log'
}

export interface WsProgressMessage extends ExecutionProgress, WsBaseMessage {
  type: 'progress'
}

export interface WsCaseCompleteMessage extends WsBaseMessage {
  type: 'case_complete'
  case_id: string
  case_key?: string
  status: string
  reason: string
  actual_result?: string
  log_file?: string
  remarks?: string
}

export interface WsExecutionFinishedMessage extends WsBaseMessage {
  type: 'execution_finished'
  results: TestResultSummary[]
}

export interface WsExecutionStoppedMessage extends WsBaseMessage {
  type: 'execution_stopped'
  message: string
}

export interface WsManualConfirmRequestMessage extends ConfirmRequest, WsBaseMessage {
  type: 'manual_confirm_request'
}

export type WsIncomingMessage =
  | WsLogMessage
  | WsProgressMessage
  | WsCaseCompleteMessage
  | WsExecutionFinishedMessage
  | WsExecutionStoppedMessage
  | WsManualConfirmRequestMessage
  | WsAIParseProgressMessage
  | WsAIParseCompleteMessage
  | WsAIParseCaseDoneMessage

export interface StopExecutionMessage {
  type: 'stop_execution'
}

export interface ConfirmResponseMessage {
  type: 'confirm_response'
  confirm_id: string
  result: boolean
}

export type WsOutgoingMessage = StopExecutionMessage | ConfirmResponseMessage

// =========================================================================
// AI 功能类型
// =========================================================================

export interface AIConfig {
  ai_enabled: boolean
  ai_protocol: 'anthropic' | 'openai' | 'ollama'
  ai_api_key: string
  ai_api_key_masked?: string
  ai_model: string
  ai_base_url: string
  ai_auto_analyze: boolean
  ai_auto_parse_steps: boolean
  ai_judge_mode: 'off' | 'uncertain' | 'always'
  ai_cache_ttl_hours: number
}

/** 已保存的 AI 配置方案摘要（不含完整 API Key） */
export interface AIProfileSummary {
  id: string
  name: string
  ai_enabled: boolean
  ai_protocol: AIConfig['ai_protocol']
  ai_model: string
  ai_base_url: string
  ai_api_key_masked?: string
  created_at: string
  updated_at: string
}

export interface AIProfilesResponse {
  profiles: AIProfileSummary[]
  active_id: string | null
}

/** 从接入地址查询到的模型项 */
export interface AIModelInfo {
  id: string
  label: string
}

export interface AIAnalysis {
  case_id: string
  root_cause_category: 'environment' | 'defect' | 'test_issue' | 'flaky' | 'mismatch'
  root_cause_summary: string
  evidence: string[]
  explanation: string
  suggestion: string[]
  confidence: number
  is_likely_real_bug: boolean
  _from_cache?: boolean
  _model?: string
  _tokens?: number
}

export interface AIJudgment {
  status: 'Pass' | 'Fail' | 'NEED_REVIEW'
  confidence: number
  reason: string
  evidence: string[]
  _source?: string
  _model?: string
  _tokens?: number
}

export interface AIReport {
  report: string
  highlights: Array<{ type: string; msg: string }>
  _model?: string
  _tokens?: number
}

export interface AIConnectionTestResult {
  ok: boolean
  message: string
}

// =========================================================================
// AI 步骤解析类型
// =========================================================================

export interface AIParsedStep {
  command: string
  description: string
  kind: 'command' | 'cd' | 'nvsipl_input' | 'manual' | 'skip'
  terminal?: string
  confidence: number
  step_num: number
}

export interface AIParseStepsResponse {
  parsed_steps: AIParsedStep[]
  total: number
  ai_recognized: number
  _model?: string
  _tokens?: number
  _from_cache?: boolean
  _error?: string
}

export interface AIParseStepsBatchResponse {
  results: Record<string, AIParseStepsResponse>
  total: number
  success: number
  failed: number
}

// =========================================================================
// 远端命令预览类型
// =========================================================================

export interface CommandPreviewStep {
  index: number
  step_num: number
  kind: string
  action: 'execute' | 'change_dir' | 'input' | 'manual' | 'confirm' | 'repeat' | 'skip'
  terminal: string
  description: string
  raw_command: string
  command: string
  notes: string[]
  needs_tty: boolean
}

export interface CommandPreviewPrerequisite {
  command: string
  manual_confirm: boolean
}

export interface CommandPreviewCase {
  case_id: string
  case_key: string
  description: string
  na: boolean
  na_reason: string
  mode: string
  mode_label: string
  prerequisites_enabled: boolean
  prerequisites: CommandPreviewPrerequisite[]
  steps: CommandPreviewStep[]
  unrecognized_count: number
  ai_cache_used: boolean
  notes: string[]
  error?: string
}

export interface CommandPreviewResponse {
  cases: CommandPreviewCase[]
}

export interface WsAIParseProgressMessage extends WsBaseMessage {
  type: 'ai_parse_progress'
  current: number
  total: number
  message: string
}

export interface WsAIParseCompleteMessage extends WsBaseMessage {
  type: 'ai_parse_complete'
  success: number
  failed: number
  total: number
  message: string
}

export interface WsAIParseCaseDoneMessage extends WsBaseMessage {
  type: 'ai_parse_case_done'
  case_key: string
  ai_recognized: number
}