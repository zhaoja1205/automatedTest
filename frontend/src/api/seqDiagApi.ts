/**
 * 函数时序图模块 API。
 *
 * 复用 axios.ts 中的 api 实例（自动注入 X-Session-ID），但项目是 session-agnostic。
 * 上传接口 timeout 抬到 10 min，适配 20-200MB zip。
 */
import api from './axios'
import type {
  SeqDiagProject,
  SeqDiagProjectSummary,
  SeqGenerateRequest,
  SeqGenerateResult,
  IncludeItem,
} from '../types/seqDiag'

// ---- 项目 CRUD ----

export const listSeqDiagProjects = () =>
  api.get<SeqDiagProjectSummary[]>('/seqdiag/projects')

export const createSeqDiagProject = (name: string) =>
  api.post<SeqDiagProject>('/seqdiag/projects', { name })

export const getSeqDiagProject = (id: string) =>
  api.get<SeqDiagProject>(`/seqdiag/projects/${id}`)

export const deleteSeqDiagProject = (id: string) =>
  api.delete<{ deleted: boolean }>(`/seqdiag/projects/${id}`)

// ---- 上传 ----

/**
 * 上传主源码 zip。重传会覆盖 source/ 目录。
 * onProgress 用来驱动进度条；zip 大时用户很想看到反馈。
 */
export const uploadSourceZip = (
  id: string,
  file: File,
  onProgress?: (percent: number) => void,
) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<{ source_zip_name: string; summary: unknown }>(
    `/seqdiag/projects/${id}/source`,
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    },
  )
}

/**
 * 上传一个 include zip。name 是给这个 include 的显示名（也用作目录段）。
 * 后端会拒绝重名——UI 提示后可让用户改名再传。
 */
export const uploadIncludeZip = (
  id: string,
  name: string,
  file: File,
  onProgress?: (percent: number) => void,
) => {
  const form = new FormData()
  form.append('name', name)
  form.append('file', file)
  return api.post<IncludeItem>(
    `/seqdiag/projects/${id}/includes`,
    form,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600000,
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded * 100) / e.total))
      },
    },
  )
}

export const deleteInclude = (id: string, name: string) =>
  api.delete<{ deleted: boolean; name: string }>(
    `/seqdiag/projects/${id}/includes/${encodeURIComponent(name)}`,
  )

// ---- 生成 ----

export const generateSeqDiagram = (id: string, req: SeqGenerateRequest) =>
  api.post<SeqGenerateResult>(`/seqdiag/projects/${id}/generate`, req, {
    timeout: 120000,
  })

/**
 * 头文件搜索，用于函数名输入框旁的辅助面板：
 * q 是子串过滤（大小写不敏感），后端 mtime 缓存到位。
 */
export const listProjectHeaders = (id: string, q: string = '', limit: number = 200) =>
  api.get<{ items: string[]; total: number }>(
    `/seqdiag/projects/${id}/headers`,
    { params: { q, limit }, timeout: 15000 },
  )
