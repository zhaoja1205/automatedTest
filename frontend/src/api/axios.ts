import axios from 'axios'
import type {
  AIConfig,
  AIAnalysis,
  AIConnectionTestResult,
  AIJudgment,
  AIReport,
  AIParseStepsResponse,
  AIParseStepsBatchResponse,
  ApiMessageResponse,
  ExecuteStartResponse,
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

export const selectCases = (caseIds: string[], selected: boolean) =>
  api.post<ApiMessageResponse>('/cases/select', caseIds, { params: { selected } })

export const getSSHConfig = () => api.get<SSHConfig>('/ssh/config')
export const setSSHConfig = (config: SSHConfig) =>
  api.post<ApiMessageResponse>('/ssh/config', config)
export const getSSHStatus = () => api.get<SSHStatus>('/ssh/status')
export const testSSHConnection = (config: SSHConfig) =>
  api.post<SSHStatus>('/ssh/test', config)

export const getWorkspace = () => api.get<WorkspaceConfig>('/workspace/config')
export const setWorkspace = (config: WorkspaceConfig) =>
  api.post<ApiMessageResponse>('/workspace/config', config)

export const startExecution = (caseIds?: string[]) =>
  api.post<ExecuteStartResponse>('/execute/start', {
    case_ids: caseIds || [],
  })

export const downloadResults = () =>
  api.get<Blob>('/download/results', { responseType: 'blob' })

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
export const testAIConnection = () =>
  api.post<AIConnectionTestResult>('/ai/test')
export const analyzeFailure = (caseId: string) =>
  api.post<{ analysis: AIAnalysis }>('/ai/analyze', { case_id: caseId }, { timeout: 60000 })
export const analyzeAllFailures = () =>
  api.post<{ analyses: AIAnalysis[]; total: number; analyzed: number }>('/ai/analyze-all', {}, { timeout: 300000 })
export const generateReport = (format: string = 'markdown') =>
  api.post<AIReport>('/ai/report', { format }, { timeout: 120000 })
export const aiJudgeResult = (caseId: string) =>
  api.post<{ judgment: AIJudgment }>('/ai/judge', { case_id: caseId }, { timeout: 60000 })

// ---- AI 步骤解析 API ----
export const aiParseSteps = (data: { step_text: string; context?: string; case_id?: string }) =>
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