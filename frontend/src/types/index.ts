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

export interface UploadExcelResponse {
  message: string
  case_count: number
  sheets: string[]
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
  ai_provider: 'claude' | 'openai' | 'ollama'
  ai_api_key: string
  ai_api_key_masked?: string
  ai_model: string
  ai_base_url: string
  ai_auto_analyze: boolean
  ai_judge_uncertain: boolean
  ai_cache_ttl_hours: number
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