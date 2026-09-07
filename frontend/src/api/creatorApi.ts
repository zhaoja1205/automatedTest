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

// ---- 导出与下载 ----

export const exportCreatorProject = (id: string) =>
  api.post<ExportResult>(`/creator/projects/${id}/export`, {}, { timeout: 120000 })

export const downloadCreatorFile = (id: string, filename: string) =>
  api.get(`/creator/projects/${id}/download/${filename}`, {
    responseType: 'blob',
  })
