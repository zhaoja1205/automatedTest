/**
 * ASPICE 文档模块 API。
 *
 * 复用 axios.ts 中的 api 实例（自动注入 X-Session-ID）。
 * 与 creator 模块共享同一项目实体。
 */
import api, { sessionId } from './axios'
import type {
  AspiceData,
  AspiceExportResult,
  GenerateArchResult,
  ParseRequirementsResult,
  Requirement,
  ArchMapping,
  AspiceComponent,
  AspiceTopology,
  KpiItem,
  ValidateResult,
  ImportSwe2Result,
  Swe2Overview,
  Swe2Integration,
  Swe2SoftwareDesign,
  Swe2Resources,
  Swe3Overview,
  Swe3Composition,
  Swe3Module,
  Swe3Performance,
  Swe3FunctionEvaluation,
  Swe3CommonDefs,
  Swe3Integration,
  TermItem,
  GenerateSwe3Result,
} from '../types/aspice'
// 原 `../types/creator` 已随 8d9c6eb refactor(creator): 移除测试用例生成模块一起删除，
// 但 /aspice/projects 仍复用 creator_store.list_projects / create_project 的 dict shape。
// 就地定义最小 TS 接口（与 backend/app/core/creator_store.py 返回字段 1:1）。
export interface AspiceProjectSummary {
  project_id: string
  name: string
  created_at: string
  updated_at: string
  project_type: string          // "aspice" / "creator"
}

export interface AspiceProjectFull extends AspiceProjectSummary {
  aspice?: AspiceData           // 新建返回包含完整 aspice 段
}

// ---- 项目级 ----

export const listAspiceProjects = () =>
  api.get<AspiceProjectSummary[]>('/aspice/projects')

export const createAspiceProject = (name: string) =>
  api.post<AspiceProjectFull>('/aspice/projects', { name })

export const getAspiceProject = (id: string) =>
  api.get<AspiceData>(`/aspice/projects/${id}`)

/** 向导页加载时用到的项目基本信息（和 /projects/{id}/info 对齐）。 */
export const getAspiceProjectInfo = (id: string) =>
  api.get<AspiceProjectSummary>(`/aspice/projects/${id}/info`)

/** 删除 ASPICE 项目（原 `deleteCreatorProject` 的替代）。 */
export const deleteAspiceProject = (id: string) =>
  api.delete<{ message: string }>(`/aspice/projects/${id}`)

export const saveAspiceProject = (id: string, data: AspiceData) =>
  api.put<{ message: string }>(`/aspice/projects/${id}`, data)

export const saveSwe1 = (id: string, data: {
  project_code?: string
  requirements?: Requirement[]
  topology?: AspiceTopology[]
  kpi?: KpiItem[]
  current_step?: number
}) => api.put<{ message: string }>(`/aspice/projects/${id}/swe1`, data)

/** SWE.2 §3.3.3 候选目录扫描：engineering_src/ 下含
 * *_platform.json + *_module.json + cryptoConfig.json 的目录（POSIX 相对路径）。
 * engineering_ready=false → 前端显示"请先上传工程代码"。 */
export const discoverConfigDb = (id: string) =>
  api.get<{ candidates: string[]; engineering_ready: boolean }>(
    `/aspice/projects/${id}/swe2/config-db/candidates`,
    { timeout: 30000 },
  )

/** SWE.2 §3.3.3 解析：读 engineering_src/<database_path>/ 下 *_platform.json /
 * cameraModules / imageSensors / eeproms / cryptoConfig，返回 ConfigDatabase 结构。
 * 路径逃逸或目录缺失时返回空壳（platform=null, modules=[]）而不是 500。 */
export const parseConfigDb = (id: string, database_path: string) =>
  api.post<import('../types/aspice').ConfigDatabase>(
    `/aspice/projects/${id}/swe2/config-db/parse`,
    { database_path },
    { timeout: 30000 },
  )

export const saveSwe2 = (id: string, data: {
  mappings?: ArchMapping[]
  components?: AspiceComponent[]
  current_step?: number
  // 推送 A 新增：概述元数据 + 系统集成
  overview?: Swe2Overview
  integration?: Swe2Integration
  // Phase 4 Group 2 新增：§3 软件设计 / §5 资源 / §6 备选架构
  software_design?: Swe2SoftwareDesign
  resources?: Swe2Resources
  alternative_arch?: string
}) => api.put<{ message: string }>(`/aspice/projects/${id}/swe2`, data)

// ---- SWE.1 需求解析 ----

export const parseRequirements = (
  id: string,
  text: string,
  files: File | File[] | null,
) => {
  const form = new FormData()
  if (text) form.append('text', text)
  const uploadFiles = Array.isArray(files) ? files : (files ? [files] : [])
  uploadFiles.forEach((file) => form.append('files', file))
  return api.post<ParseRequirementsResult>(
    `/aspice/projects/${id}/swe1/parse-requirements`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 },
  )
}

// ---- SWE.2 映射生成 ----

export const generateSwe2 = (id: string, useAi = true) =>
  api.post<GenerateArchResult>(
    `/aspice/projects/${id}/swe2/generate`,
    null,
    { params: { use_ai: useAi }, timeout: 120000 },
  )

export const importSwe2 = (id: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<ImportSwe2Result>(
    `/aspice/projects/${id}/swe2/import`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 },
  )
}

// ---- 导出 ----

export const exportSwe1 = (id: string) =>
  api.post<AspiceExportResult>(`/aspice/projects/${id}/swe1/export`, {}, { timeout: 120000 })

export const exportSwe2 = (id: string) =>
  api.post<AspiceExportResult>(`/aspice/projects/${id}/swe2/export`, {}, { timeout: 120000 })

// ---- 校验 ----

export const validateSwe1 = (id: string) =>
  api.post<ValidateResult>(`/aspice/projects/${id}/swe1/validate`, {}, { timeout: 120000 })

// ---- 下载 ----

export const downloadAspiceFile = (id: string, filename: string) =>
  api.get(`/aspice/projects/${id}/download/${filename}`, { responseType: 'blob' })

// ---- SWE.3 详细设计（推送 C 新增） ----

export const saveSwe3 = (id: string, data: {
  project_code?: string
  overview?: Swe3Overview
  terms?: TermItem[]
  composition?: Swe3Composition
  modules?: Swe3Module[]
  performance?: Swe3Performance
  function_evaluation?: Swe3FunctionEvaluation
  common_defs?: Swe3CommonDefs
  integration?: Swe3Integration
  current_step?: number
}) => api.put<{ message: string }>(`/aspice/projects/${id}/swe3`, data)

export const generateSwe3 = (id: string) =>
  api.post<GenerateSwe3Result>(`/aspice/projects/${id}/swe3/generate`, {}, { timeout: 120000 })

export const exportSwe3 = (id: string) =>
  api.post<AspiceExportResult>(`/aspice/projects/${id}/swe3/export`, {}, { timeout: 180000 })

// 原 `deleteCreatorProject` re-export 已随 creator 模块移除；
// 如果 aspice 侧后续需要删项目功能，直接在后端加 DELETE /aspice/projects/{id}。

// ---- SWE.3 推送 D：工程代码 / 关注函数 / AI ----

import type {
  Swe3EngineeringUpload,
  Swe3PathPattern,
  Swe3ModuleCodeSource,
  Swe3FocusFunctions,
} from '../types/aspice'

export const uploadEngineering = (id: string, file: File, append = false) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<Swe3EngineeringUpload>(
    `/aspice/projects/${id}/swe3/engineering/upload`,
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: append ? { append: true } : undefined,
      timeout: 300000,
    },
  )
}

export const clearEngineering = (id: string) =>
  api.delete<{ message: string }>(`/aspice/projects/${id}/swe3/engineering`)

// 推送 G R2：浏览器直传工程树（showDirectoryPicker → 分片 POST）
// 用户本机零安装：浏览器 Web 标准

export const engineeringTreeStart = (id: string) =>
  api.post<{ message: string }>(
    `/aspice/projects/${id}/swe3/engineering/tree/start`, {}, { timeout: 30000 })

export const engineeringTreeAbort = (id: string) =>
  api.post<{ message: string }>(
    `/aspice/projects/${id}/swe3/engineering/tree/abort`, {}, { timeout: 30000 })

export const engineeringTreeFinish = (id: string, workspaceName: string) =>
  api.post<Swe3EngineeringUpload>(
    `/aspice/projects/${id}/swe3/engineering/tree/finish`, null,
    {
      params: { workspace_name: workspaceName },
      timeout: 60000,
    })

/** 一批文件打包成 FormData 发到后端。files 和 paths 必须一一对应。
 *  paths 走 FormData 而非 query，避免长路径（如 git-repo 下深目录）堆成 8KB+ URL 被代理拒绝。 */
export const engineeringTreeChunk = (
  id: string, files: Array<{ data: Blob; path: string }>,
) => {
  const form = new FormData()
  // 多 File part + 多 path part（后端 List[str] 从 Form(...) 读）
  for (const f of files) {
    form.append('files', f.data, f.path.split('/').pop() || 'file')
    form.append('paths', f.path)
  }
  return api.post<{ written: number; total_files: number; total_bytes: number }>(
    `/aspice/projects/${id}/swe3/engineering/tree/chunk`,
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,
    },
  )
}

export const previewMatch = (id: string, patterns: string[], excludes: string[] = []) => {
  // query 多值：patterns=a&patterns=b；axios params 用数组自动展开
  const params = new URLSearchParams()
  patterns.forEach((p) => params.append('patterns', p))
  excludes.forEach((p) => params.append('excludes', p))
  return api.get<{ total: number; sample: string[] }>(
    `/aspice/projects/${id}/swe3/engineering/preview-match?${params.toString()}`,
  )
}

export const putPathConfig = (
  id: string, componentId: string, patterns: Swe3PathPattern[],
) => api.put<Swe3ModuleCodeSource>(
  `/aspice/projects/${id}/swe3/modules/${componentId}/path-config`,
  { path_patterns: patterns },
)

export const scanModule = (id: string, componentId: string) =>
  api.post<any>(`/aspice/projects/${id}/swe3/modules/${componentId}/scan`,
    {}, { timeout: 180000 })

export const getModuleScan = (id: string, componentId: string) =>
  api.get<any>(`/aspice/projects/${id}/swe3/modules/${componentId}/scan`)

export const putFocusFunctions = (
  id: string, componentId: string, data: {
    focused_keys: string[]
    manual_additions?: Swe3FocusFunctions['manual_additions']
    included_added_keys?: string[]
  },
) => api.put<Swe3FocusFunctions>(
  `/aspice/projects/${id}/swe3/modules/${componentId}/focus`, data)

export const setCameraSecurity = (id: string, enabled: boolean) =>
  api.put<{ has_camera_security: boolean }>(
    `/aspice/projects/${id}/swe3/camera-security`,
    { has_camera_security: enabled },
  )

export const augmentOneFunction = (id: string, componentId: string, key: string) =>
  api.post<{
    key: string
    ai_intro: string
    ai_flowchart: string
    extracted_by: string
  }>(`/aspice/projects/${id}/swe3/ai/augment-one`,
    { component_id: componentId, key }, { timeout: 180000 })

/**
 * SSE 批量补齐。axios 不原生友好流式；用 fetch 读 reader + 自己拆事件。
 * onProgress 每收一条 `event: progress` 调一次。
 * 返回 Promise，done 时 resolve。
 */
export async function augmentFocusFunctions(
  id: string,
  onProgress: (ev: { done: number; total: number; key: string; name: string }) => void,
): Promise<{ augmented: number }> {
  const resp = await fetch(`/api/aspice/projects/${id}/swe3/ai/augment`, {
    method: 'POST',
    // fetch 不走 axios 拦截器，必须手动带上 X-Session-ID，否则后端 400
    headers: { 'Content-Type': 'application/json', 'X-Session-ID': sessionId },
  })
  if (!resp.ok || !resp.body) {
    throw new Error(await resp.text().catch(() => 'AI augment 失败'))
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let result = { augmented: 0 }
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    // SSE 事件以 \n\n 分隔
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const lines = chunk.split('\n')
      let event = 'message'
      let data = ''
      for (const line of lines) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      try {
        const payload = JSON.parse(data)
        if (event === 'progress') onProgress(payload)
        else if (event === 'done') result = payload
      } catch { /* ignore malformed */ }
    }
  }
  return result
}


// ---- 推送 G：baseline / exempt / exception / retry ----

export interface Swe3FileHunk {
  new_start: number    // 1-indexed，HEAD 版里改动起始行
  new_lines: number    // HEAD 版里 hunk 覆盖行数；0 = 纯删除 hunk，锚定到 new_start 单行
}

export interface Swe3BaselineDiff {
  baseline_commit: string
  baseline_branch?: string
  head_commit?: string
  head_branch?: string
  pinned_at?: string
  changed_files: string[]
  added_files: string[]
  deleted_files?: string[]
  /** 推送 G 粒度升级：每个 changed_file 在 HEAD 版里的 hunk 区间；
   *  后端 classify_functions 用它与函数 line_start/line_end 做交集，
   *  避免"文件改一行 → 文件内 N 个函数全连坐 modified"的粒度 bug。
   *  字段缺省 / 某文件未列出 → 回落文件级（全部 modified）保持向后兼容。
   */
  file_hunks?: Record<string, Swe3FileHunk[]>
}

export const getBaseline = (id: string) =>
  api.get<Swe3BaselineDiff>(`/aspice/projects/${id}/swe3/baseline`)

export const putBaseline = (id: string, diff: Swe3BaselineDiff) =>
  api.put<Swe3BaselineDiff>(`/aspice/projects/${id}/swe3/baseline`, diff,
    { timeout: 60000 })

export const clearBaseline = (id: string) =>
  api.delete<{ message: string }>(`/aspice/projects/${id}/swe3/baseline`)

export const reclassifyAll = (id: string) =>
  api.post<{ reclassified: { component_id: string; stats: Record<string, number> }[];
             has_baseline: boolean }>(
    `/aspice/projects/${id}/swe3/baseline/reclassify`, {}, { timeout: 60000 })

export const setFunctionExempt = (
  id: string, componentId: string, key: string, exempt: boolean,
) => api.put<{ key: string; exempt_from_ai: boolean }>(
  `/aspice/projects/${id}/swe3/functions/exempt`,
  { component_id: componentId, key, exempt })

export const markFunctionException = (
  id: string, componentId: string, key: string, marked: boolean, note?: string,
) => api.put<{ key: string; ai_status: string; ai_exception_note: string }>(
  `/aspice/projects/${id}/swe3/functions/exception`,
  { component_id: componentId, key, marked, note: note || '' })

export const augmentOneWithRetry = (
  id: string, componentId: string, key: string, maxRetries = 3,
) => api.post<{
  key: string
  ai_status: 'ok' | 'failed' | 'skipped_complex'
  ai_retry_count: number
  ai_last_error: string
  ai_flowchart: string
  ai_intro?: string
}>(`/aspice/projects/${id}/swe3/ai/augment-one-retry`,
   { component_id: componentId, key, max_retries: maxRetries },
   { timeout: 180000 })
