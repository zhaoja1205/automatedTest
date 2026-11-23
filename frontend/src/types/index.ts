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
  /** Excel「BUG」列（AI 判定状态、理由与证据） */
  judgment?: string
  bug_id: string
  log_file: string
  tester: string
  test_date: string
  test_version: string
  remarks: string
  expected_keywords: string[]
  /** AI 判定详情（用于实际结果 / 日志弹窗展示） */
  ai_judged?: boolean
  ai_status?: string
  ai_confidence?: number
  ai_reason?: string
  /** AI 判定时摘录的关键证据行 */
  ai_evidence?: string[]
  /** 手动高亮行的内容快照（用于下载日志图片高亮） */
  manual_evidence?: string[]
  /** 按行号选择时的行标识（JSON [终端标签, 行号]） */
  manual_evidence_lines?: string[]
  /** 手动高亮匹配方式：line 按行号；content 仅用于兼容旧记录 */
  manual_evidence_mode?: 'line' | 'content'
  /** 失败用例的 AI Bug 描述 / 严重程度 */
  bug_description?: string
  bug_severity?: string
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
  log_remark_mode: 'image' | 'text'
  log_image_render_width: number
  log_image_display_width: number
  log_image_max_height: number
  /** 「备注」列图片四周留白（px） */
  remark_image_padding: number
  /** 「备注」列同一单元格内多张图片之间的间距（px） */
  remark_image_gap: number
  /** AI 判定日志上限（KB）：超过时从末尾截取；0 表示不限制 */
  judge_log_max_kb: number
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

/** 历史执行日志（执行过程日志，非板端终端原始输出） */
export interface ExecutionLogRecord {
  run_id: string
  session_id: string
  path: string
  started_at: string
  ended_at: string
  status: string
  message: string
  excel_filename: string
  tester_name: string
  test_version: string
  /** 日志文件大小（字节） */
  size: number
  mtime: number
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

/** 下载结果的导出进度（按 token 区分本次下载） */
export interface DownloadProgress {
  token: string
  /** 总进度（含日志图片与用例截图两个阶段） */
  current: number
  total: number
  /** 当前阶段内已处理 / 待处理的用例数 */
  case_current?: number
  case_total?: number
  case_id: string
  phase: string
  message: string
  done?: boolean
}

export interface WsDownloadProgressMessage extends DownloadProgress, WsBaseMessage {
  type: 'download_progress'
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

// =========================================================================
// 多终端实时板端日志
// =========================================================================

/** 执行器推送的当前用例信息（case_start） */
export interface CaseStartInfo {
  case_id: string
  case_key: string
  description: string
  test_type: string
  priority: string
  prerequisites: string
  test_steps: string
  expected_result: string
  source_sheet: string
  /** 本用例涉及的终端标签（终端A / 终端B …） */
  terminals: string[]
  log_file: string
  started_at: string
}

/** WebSocket：某个终端的实时板端输出 */
export interface WsTerminalLogMessage extends WsBaseMessage {
  type: 'terminal_log'
  case_id: string
  case_key: string
  terminal: string
  chunk: string
  timestamp: number
}

/** WebSocket：当前用例开始执行 */
export interface WsCaseStartMessage extends WsBaseMessage {
  type: 'case_start'
  case: CaseStartInfo
}

/** 单个终端的已保存日志内容 */
export interface TerminalLogPane {
  label: string
  content: string
}

/** 单个终端的实时快照（service 端 live 缓冲使用 text 字段） */
export interface LiveTerminalLogPane {
  label: string
  text: string
}

/** GET /logs/terminals 响应（已执行用例按终端保存的日志） */
export interface TerminalLogsResponse {
  case_id: string
  case_key?: string
  log_file: string
  terminals: TerminalLogPane[]
  message?: string
}

/** GET /logs/terminals/live 响应（当前执行任务的实时快照） */
export interface LiveTerminalLogsResponse {
  running: boolean
  case_id: string
  case_key: string
  case?: CaseStartInfo | Record<string, never>
  log_file: string
  progress?: ExecutionProgress
  terminals: LiveTerminalLogPane[]
}

export type WsIncomingMessage =
  | WsLogMessage
  | WsProgressMessage
  | WsCaseCompleteMessage
  | WsTerminalLogMessage
  | WsCaseStartMessage
  | WsExecutionFinishedMessage
  | WsExecutionStoppedMessage
  | WsManualConfirmRequestMessage
  | WsAIParseProgressMessage
  | WsAIParseCompleteMessage
  | WsAIParseCaseDoneMessage
  | WsDownloadProgressMessage

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
  /** 各 AI 功能的自定义系统提示词，键为功能标识；空值表示使用内置默认 */
  ai_system_prompts?: Record<string, string>
}

/** 可配置系统提示词的 AI 功能 */
export interface AISystemPromptFeature {
  key: string
  name: string
  description: string
  default_prompt: string
}

export interface AISystemPromptsResponse {
  prompts: AISystemPromptFeature[]
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

/** 步骤重写后的规则识别校验结果 */
export interface AIRewriteValidation {
  total_steps: number
  executable_steps: number
  /** 仍无法被规则识别的步骤（已跳过） */
  unrecognized_steps: string[]
}

export interface AIRewriteStepsResponse {
  /** 原始步骤文本（后端规范化换行后的版本） */
  original_steps: string
  /** AI 改写后的步骤文本 */
  rewritten_steps: string
  /** AI 对本次改写的简要说明 */
  summary: string
  /** 具体改写点列表 */
  changes: string[]
  /** 改写结果是否与原文不同 */
  changed: boolean
  /** 原文过长被截断时，前端禁止直接替换（避免丢失未处理的步骤） */
  input_truncated?: boolean
  /** 改写后的规则识别情况 */
  validation?: AIRewriteValidation
  /** 改写前的规则识别情况 */
  original_validation?: AIRewriteValidation
  _model?: string
  _tokens?: number
  _from_cache?: boolean
  _error?: string
}

// =========================================================================
// 远端命令预览类型
// =========================================================================

export interface CommandPreviewStep {
  index: number
  step_num: number
  kind: string
  action: 'execute' | 'change_dir' | 'input' | 'manual' | 'confirm' | 'repeat' | 'skip' | 'wait'
  terminal: string
  description: string
  raw_command: string
  command: string
  notes: string[]
  needs_tty: boolean
  wait_seconds?: number
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
  terminals?: string[]
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