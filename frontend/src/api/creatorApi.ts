/**
 * 用例创建模块 API。
 *
 * 复用 axios.ts 中的 api 实例（自动注入 X-Session-ID）。
 */
import api from './axios'
import type {
  CaseProject,
  CaseProjectSummary,
  ExportResult,
  GenerateCasesRequest,
  GenerateCasesResult,
  ImportCasesResult,
} from '../types/creator'

// ---- 项目 CRUD ----

export const listCreatorProjects = () =>
  api.get<CaseProjectSummary[]>('/creator/projects')

export const createCreatorProject = (name: string) =>
  api.post<CaseProject>('/creator/projects', { name })

export const getCreatorProject = (id: string) =>
  api.get<CaseProject>(`/creator/projects/${id}`)

export const updateCreatorProject = (id: string, data: Partial<CaseProject>) =>
  api.put<{ message: string }>(`/creator/projects/${id}`, data)

export const deleteCreatorProject = (id: string) =>
  api.delete<{ message: string }>(`/creator/projects/${id}`)

// ---- 生成用例 ----

export const generateCreatorCases = (id: string, req: GenerateCasesRequest) =>
  api.post<GenerateCasesResult>(`/creator/projects/${id}/generate-cases`, req, {
    timeout: 120000,
  })

// ---- 导出与下载 ----

export const exportCreatorProject = (id: string) =>
  api.post<ExportResult>(`/creator/projects/${id}/export`, {}, { timeout: 120000 })

export const downloadCreatorFile = (id: string, filename: string) =>
  api.get(`/creator/projects/${id}/download/${filename}`, {
    responseType: 'blob',
  })

// ---- 回灌导入 ----

export const importCreatorCases = (id: string, file: File, overwrite = true) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<ImportCasesResult>(
    `/creator/projects/${id}/import-cases?overwrite=${overwrite}`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 },
  )
}
