import axios from 'axios'
import type {
  AIConfig,
  AIAnalysis,
  LiveTerminalLogsResponse,
  TerminalLogsResponse,
  AIConnectionTestResult,
  AIModelInfo,
  AIProfileSummary,
  AIProfilesResponse,
  AISystemPromptsResponse,
  AIJudgment,
  AIReport,
  AIParseStepsResponse,
  AIParseStepsBatchResponse,
  ApiMessageResponse,
  BugListItem,
  CommandPreviewResponse,
  ExecuteStartResponse,
  ExecutionTask,
  SSHConfig,
  SSHStatus,
  TestCase,
  UploadExcelResponse,
  WorkspaceConfig,
} from '../types'

// ---- Session ID 管理（每个标签页独立） ----
const SESSION_KEY = 'test_runner_session_id'

/**
 * 生成 32 位十六进制随机字符串，兼容非安全上下文（HTTP）。
 * crypto.randomUUID() 仅在 HTTPS / localhost 可用，
 * 而本系统常通过 http://<局域网IP>:3000 访问，因此用 getRandomValues 替代。
 */
function generateHexId(): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

/**
 * 获取当前标签页的 session ID。
 *
 * 使用 sessionStorage（每个标签页独立），而非 localStorage（同源共享）。
 * 这样同一浏览器打开多个标签页时，每个标签页拥有独立 session，
 * 可以各自配置不同 SSH、上传不同用例、同时执行互不干扰。
 *
 * sessionStorage 特性：
 * - 刷新页面（F5）→ 保持同一 session ID（配置不丢失）
 * - 新开标签页 / 新窗口 → 分配新 session ID（独立测试）
 * - 关闭标签页 → 自动清除（后端定时清理超时 session）
 */
function getSessionId(): string {
  let id = sessionStorage.getItem(SESSION_KEY)
  if (!id) {
    id = generateHexId()
    sessionStorage.setItem(SESSION_KEY, id)
  }
  return id
}

export const sessionId = getSessionId()

// ---- Axios 实例 ----
const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 自动注入 X-Session-ID header
api.interceptors.request.use((config) => {
  config.headers['X-Session-ID'] = sessionId
  return config
})

export default api

export const uploadExcel = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<UploadExcelResponse>('/excel/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export const getCases = (sheet?: string) =>
  api.get<TestCase[]>('/cases', { params: { sheet } })

/** 读取当前 Excel 中的 BugList统计 页（执行后失败用例会自动登记到该页） */
export const getBugList = () =>
  api.get<{ bug_sheet: string; bug_list: BugListItem[] }>('/buglist')

/**
 * 读取单条用例的实际执行日志。
 * 当前会话传 case_key（或路径 path），历史记录传 run_id + case_key。
 */
export const getCaseLog = (params: { path?: string; run_id?: string; case_key?: string }) =>
  api.get<{ path: string; content: string }>('/logs/content', { params })

/**
 * 读取当前执行任务的多终端实时板端日志快照。
 * 页面中途打开 / WebSocket 断线重连后，用于补齐已产生的输出。
 */
export const getLiveTerminalLogs = () =>
  api.get<LiveTerminalLogsResponse>('/logs/terminals/live')

/**
 * 读取某个已执行用例按终端保存的板端日志（执行结束后回看）。
 * 当前会话传 case_key；历史记录传 run_id + case_key。
 */
export const getTerminalLogs = (params: { path?: string; run_id?: string; case_key?: string }) =>
  api.get<TerminalLogsResponse>('/logs/terminals', { params })

/**
 * 读取单条用例的备注（AI 判定 + 执行日志）。
 * 格式与下载结果 Excel 的备注列一致。
 */
export const getCaseRemark = (params: { path?: string; run_id?: string; case_key?: string }) =>
  api.get<{ content: string }>('/cases/remark', { params })

/** 用例从板端下载到本机的 PNG 图片 */
export interface CaseImageInfo {
  name: string
  size: number
  /** 生成该 PNG 的源 YUV 文件名（不存在时为空串） */
  source_name?: string
}

export interface CaseImagesResponse {
  case_id: string
  dir?: string
  images: CaseImageInfo[]
  message?: string
}

/** 列出某条用例已下载的 PNG（YUV 出图结果） */
export const getCaseImages = (caseId: string, sourceSheet = '') =>
  api.get<CaseImagesResponse>('/cases/images', {
    params: { case_id: caseId, sheet: sourceSheet },
  })

/** 批量查询图片可用性的一条用例引用（case_key 唯一，避免跨 Sheet 同 case_id 冲突） */
export interface CaseImageAvailabilityItem {
  case_key: string
  case_id: string
  source_sheet: string
}

/** 批量查询用例目录下是否已生成 PNG（不区分 PASS/FAIL） */
export const getCaseImageAvailability = (cases: CaseImageAvailabilityItem[]) =>
  api.post<{ cases: Record<string, boolean> }>('/cases/images/availability', cases)

/** 读取单张用例图片（带 session，返回 blob） */
export const getCaseImageBlob = (caseId: string, filename: string, sourceSheet = '') =>
  api.get<Blob>(
    `/cases/images/${encodeURIComponent(caseId)}/${encodeURIComponent(filename)}`,
    { params: { sheet: sourceSheet }, responseType: 'blob' },
  )

export const selectCases = (caseIds: string[], selected: boolean) =>
  api.post<ApiMessageResponse>('/cases/select', caseIds, { params: { selected } })

/** 更新单条用例的测试步骤（写回后端当前会话） */
export const updateCaseSteps = (caseKey: string, testSteps: string) =>
  api.post<{ message: string; case_key: string; case: TestCase }>('/cases/update', {
    case_key: caseKey,
    test_steps: testSteps,
  })

/** 更新单条用例的预期结果（写回后端当前会话） */
export const updateCaseExpected = (caseKey: string, expectedResult: string) =>
  api.post<{ message: string; case_key: string; case: TestCase }>('/cases/update', {
    case_key: caseKey,
    expected_result: expectedResult,
  })

/** 更新单条用例的实际结果（BUG 列文本）与执行日志 */
export const updateCaseResultLog = (
  caseKey: string,
  resultText: string,
  logText?: string,
) =>
  api.post<{ message: string; case_key: string; case: TestCase }>('/cases/update', {
    case_key: caseKey,
    result_text: resultText,
    // 日志未修改时不传，避免把没有备注日志、但存在日志文件的用例清空
    ...(logText !== undefined ? { log_text: logText } : {}),
  })

/** 手动高亮选择：mode 决定按行号匹配还是按内容匹配 */
export interface ManualEvidencePayload {
  mode: 'line' | 'content'
  /** 按行号选择的行标识（JSON [终端标签, 行号]） */
  lines: string[]
  /** 选中行的内容快照，供下载日志图片高亮 */
  contents: string[]
}

/** 更新单条用例手动选择的高亮行（内容与行号均为空表示恢复使用 AI 证据） */
export const updateCaseManualEvidence = (
  caseKey: string,
  payload: ManualEvidencePayload,
) =>
  api.post<{ message: string; case_key: string; case: TestCase }>('/cases/update', {
    case_key: caseKey,
    manual_evidence: payload.contents,
    manual_evidence_lines: payload.lines,
    manual_evidence_mode: payload.mode,
  })

/** 日志草稿箱中的单条用例日志（恢复时写回会话用例） */
export interface RestoreCaseTerminalLog {
  /** 终端标签（终端A / 终端B …；旧聚合日志为空字符串） */
  label: string
  content: string
}

export interface RestoreCaseLogItem {
  case_key?: string
  case_id?: string
  log_text?: string
  remarks?: string
  status?: string
  actual_result?: string
  judgment?: string
  /** AI 判定证据行，用于下载日志图片时高亮 */
  ai_evidence?: string[]
  /** 手动选择的高亮行内容快照（用于下载日志图片高亮） */
  manual_evidence?: string[]
  /** 按行号选择的行标识 */
  manual_evidence_lines?: string[]
  /** 手动高亮匹配方式 */
  manual_evidence_mode?: 'line' | 'content'
  /** 按终端分开的日志（与板端日志系统同一存储格式） */
  terminals?: RestoreCaseTerminalLog[]
}

/**
 * 把日志草稿恢复进后端会话。
 *
 * 重新上传用例文件后调用：日志文本写回会话用例的备注，
 * 后续下载结果时仍可附带执行日志（文字模式可保留文本）。
 */
export const restoreCaseLogs = (cases: RestoreCaseLogItem[]) =>
  api.post<{ message: string; applied: number; missing: string[] }>(
    '/cases/restore-logs',
    { cases },
  )

/**
 * 预览用例将要下发到远端的命令。
 * caseKeys 为空时后端返回当前所有已选用例。
 */
export const previewCaseCommands = (caseKeys: string[] = []) =>
  api.post<CommandPreviewResponse>('/cases/preview-commands', { case_keys: caseKeys })

export const getSSHConfig = () => api.get<SSHConfig>('/ssh/config')
export const setSSHConfig = (config: SSHConfig) =>
  api.post<ApiMessageResponse>('/ssh/config', config)
export const getSSHStatus = () => api.get<SSHStatus>('/ssh/status')
export const testSSHConnection = (config: SSHConfig) =>
  api.post<SSHStatus>('/ssh/test', config)

export const getWorkspace = () => api.get<WorkspaceConfig>('/workspace/config')
export const setWorkspace = (config: WorkspaceConfig) =>
  api.post<ApiMessageResponse>('/workspace/config', config)

/** 读取当前执行任务摘要（断线重连后校准运行态） */
export const getCurrentExecution = () => api.get<ExecutionTask>('/execute/current')

export const startExecution = (caseIds?: string[]) =>
  api.post<ExecuteStartResponse>('/execute/start', {
    case_ids: caseIds || [],
  })

/**
 * 下载结果 Excel（备注列始终附带实际执行日志）。
 * regenerateStats=true 时由 AI 重新生成「数据统计」页内容，耗时较长；
 * false 时保留工作簿中已有的统计页内容。
 * sheets 非空时只更新这些用例表的结果，其它工作表保留工作簿原有内容。
 */
export const downloadResults = (regenerateStats = true, sheets?: string[]) =>
  api.get<Blob>('/download/results', {
    responseType: 'blob',
    params: {
      regenerate_stats: regenerateStats,
      ...(sheets && sheets.length > 0 ? { sheets } : {}),
    },
    // FastAPI 的 List[str] 查询参数需要重复 key（sheets=a&sheets=b）；
    // axios 默认会序列化成 sheets[]=a，这里关闭数组方括号
    paramsSerializer: { indexes: null },
    // 下载时后端会等待 AI 填写「数据统计」页（最长 120s）并嵌入日志/用例图片，
    // 默认 30s 会先于后端超时中断，这里放宽到 180s
    timeout: 180000,
  })

export const pushFileToBoard = (file: File, remotePath: string) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<{ message: string; remote_path: string }>('/files/push', form, {
    params: { remote_path: remotePath },
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

export const pushLocalToBoard = (localPath: string, remotePath: string) =>
  api.post<{ message: string; remote_path: string }>('/files/push-local', {
    local_path: localPath,
    remote_path: remotePath,
  }, { timeout: 300000 })

// ---- AI 功能 API ----
export const getAIConfig = () => api.get<AIConfig>('/ai/config')
export const setAIConfig = (config: Partial<AIConfig>) =>
  api.post<ApiMessageResponse>('/ai/config', config)
/** 获取所有 AI 功能的系统提示词元数据与内置默认提示词 */
export const listAISystemPrompts = () =>
  api.get<AISystemPromptsResponse>('/ai/prompts')
/** 保存系统提示词（仅更新提示词，保留当前方案的其他 AI 配置） */
export const setAISystemPrompts = (prompts: Record<string, string>) =>
  api.put<{ message: string; ai_system_prompts: Record<string, string> }>(
    '/ai/prompts',
    { prompts },
  )
// ---- AI 配置方案 ----
export const listAIProfiles = () => api.get<AIProfilesResponse>('/ai/profiles')
export const createAIProfile = (name: string, config?: Partial<AIConfig>) =>
  api.post<{ message: string; profile: AIProfileSummary }>('/ai/profiles', { name, config })
export const activateAIProfile = (id: string) =>
  api.post<{ message: string; profile: AIProfileSummary }>(`/ai/profiles/${id}/activate`)
export const deleteAIProfile = (id: string) =>
  api.delete<{ message: string; active_id: string | null }>(`/ai/profiles/${id}`)
export const testAIConnection = () =>
  api.post<AIConnectionTestResult>('/ai/test')
/** 按接入地址查询可用模型；查询失败返回空列表 */
export const listAIModels = (payload: {
  ai_protocol?: string
  ai_base_url?: string
  ai_api_key?: string
}) => api.post<{ models: AIModelInfo[] }>('/ai/models', payload, { timeout: 20000 })
export const analyzeFailure = (caseId: string, force = false) =>
  api.post<{ analysis: AIAnalysis }>('/ai/analyze', { case_id: caseId, force }, { timeout: 180000 })

export interface AnalyzeStreamHandlers {
  /** 思考型模型的推理过程增量 */
  onThinking?: (text: string) => void
  /** 收到增量文本（模型原始 JSON 输出片段） */
  onDelta?: (text: string) => void
  /** 流结束且解析成功 */
  onDone: (analysis: AIAnalysis) => void
  /** 流式调用失败 */
  onError: (message: string) => void
}

/**
 * AI 失败分析（SSE 流式）。
 *
 * 使用 fetch + ReadableStream 读取后端事件流，边接收边回调，
 * 避免长时间无响应以及网关/代理超时。
 */
export async function analyzeFailureStream(
  caseId: string,
  force: boolean,
  handlers: AnalyzeStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response
  try {
    resp = await fetch('/api/ai/analyze/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Session-ID': sessionId,
      },
      body: JSON.stringify({ case_id: caseId, force }),
      signal,
    })
  } catch (err: any) {
    if (err?.name === 'AbortError') return
    handlers.onError(err?.message || '分析请求失败')
    return
  }

  if (!resp.ok) {
    let detail = `分析请求失败 (HTTP ${resp.status})`
    try {
      const data = await resp.json()
      if (data?.detail) detail = data.detail
    } catch {
      // 响应体不是 JSON，保留默认消息
    }
    handlers.onError(detail)
    return
  }

  if (!resp.body) {
    handlers.onError('当前浏览器不支持流式读取')
    return
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let settled = false

  const handleLine = (line: string) => {
    if (!line.startsWith('data:') || settled) return
    const payload = line.slice(5).trim()
    if (!payload) return
    let event: any
    try {
      event = JSON.parse(payload)
    } catch {
      return
    }
    if (event.type === 'thinking') {
      handlers.onThinking?.(event.text || '')
    } else if (event.type === 'delta') {
      handlers.onDelta?.(event.text || '')
    } else if (event.type === 'done') {
      settled = true
      handlers.onDone(event.analysis)
    } else if (event.type === 'error') {
      settled = true
      handlers.onError(event.message || 'AI 分析失败')
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx = buffer.indexOf('\n\n')
      while (idx >= 0) {
        const block = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        block.split('\n').forEach(handleLine)
        idx = buffer.indexOf('\n\n')
      }
    }
    buffer += decoder.decode()
    if (buffer) buffer.split('\n').forEach(handleLine)
  } catch (err: any) {
    if (err?.name === 'AbortError') return
    if (!settled) handlers.onError(err?.message || '流式连接中断')
    return
  }

  if (!settled) handlers.onError('连接中断，未收到完整分析结果')
}

export const analyzeAllFailures = () =>
  api.post<{ analyses: AIAnalysis[]; total: number; analyzed: number }>('/ai/analyze-all', {}, { timeout: 300000 })
export const generateReport = (format: string = 'markdown') =>
  api.post<AIReport>('/ai/report', { format }, { timeout: 120000 })
export interface AIJudgeResultResponse {
  judgment: AIJudgment
  /** 判定后用例字段补丁（状态 / AI 详情 / BUG 列 / 备注） */
  case_patch?: Partial<TestCase>
  /** 是否已写回结果 Excel */
  excel_updated?: boolean
}

export const aiJudgeResult = (caseId: string) =>
  api.post<AIJudgeResultResponse>('/ai/judge', { case_id: caseId }, { timeout: 180000 })

// ---- AI 步骤解析 API ----
export const aiParseSteps = (data: {
  step_text: string
  context?: string
  case_id?: string
  force_ai?: boolean
}) =>
  api.post<AIParseStepsResponse>('/ai/parse-steps', data, { timeout: 60000 })
export const aiParseStepsBatch = (caseIds?: string[]) =>
  api.post<AIParseStepsBatchResponse>('/ai/parse-steps-batch', { case_ids: caseIds || [] }, { timeout: 300000 })

// ---- 文件清理配置 API ----
export interface CleanupConfig {
  enabled: boolean
  retention_days: number
  check_interval_hours: number
}

export interface CleanupStats {
  total_files: number
  total_size_mb: number
  session_count: number
  config: CleanupConfig
}

export const getCleanupConfig = () =>
  api.get<CleanupConfig>('/cleanup/config')
export const setCleanupConfig = (config: CleanupConfig) =>
  api.post<ApiMessageResponse>('/cleanup/config', config)
export const getCleanupStats = () =>
  api.get<CleanupStats>('/cleanup/stats')
export const runCleanupNow = () =>
  api.post<{ message: string; removed: number }>('/cleanup/run')