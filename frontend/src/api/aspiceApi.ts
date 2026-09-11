/**
 * ASPICE 文档模块 API。
 *
 * 复用 axios.ts 中的 api 实例（自动注入 X-Session-ID）。
 * 与 creator 模块共享同一项目实体。
 */
import api from './axios'
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
} from '../types/aspice'

// ---- 项目级 ----

export const getAspiceProject = (id: string) =>
  api.get<AspiceData>(`/aspice/projects/${id}`)

export const saveSwe1 = (id: string, data: {
  project_code?: string
  requirements?: Requirement[]
  topology?: AspiceTopology[]
  kpi?: KpiItem[]
  current_step?: number
}) => api.put<{ message: string }>(`/aspice/projects/${id}/swe1`, data)

export const saveSwe2 = (id: string, data: {
  mappings?: ArchMapping[]
  components?: AspiceComponent[]
  current_step?: number
}) => api.put<{ message: string }>(`/aspice/projects/${id}/swe2`, data)

// ---- SWE.1 需求解析 ----

export const parseRequirements = (
  id: string,
  text: string,
  file: File | null,
) => {
  const form = new FormData()
  if (text) form.append('text', text)
  if (file) form.append('file', file)
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

// 复用 creator 项目列表
export { listCreatorProjects, createCreatorProject, deleteCreatorProject } from './creatorApi'
