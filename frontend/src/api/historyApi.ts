/**
 * 执行历史与报告 API。
 *
 * 复用 axios.ts 中的 api 实例（自动注入 X-Session-ID）。
 */
import api from './axios'
import type {
  RunDetail,
  RunComparison,
  TestReport,
  PaginatedRuns,
  PaginatedReports,
} from '../types/history'

// ---- 执行记录 ----

export const listRuns = (limit = 50, offset = 0) =>
  api.get<PaginatedRuns>('/runs', { params: { limit, offset } })

export const getRunDetail = (runId: string) =>
  api.get<RunDetail>(`/runs/${runId}`)

export const deleteRun = (runId: string) =>
  api.delete<{ message: string }>(`/runs/${runId}`)

export const downloadRunResults = (runId: string) =>
  api.get<Blob>(`/runs/${runId}/download`, { responseType: 'blob' })

export const compareRuns = (run1: string, run2: string) =>
  api.get<RunComparison>('/runs/compare', { params: { run1, run2 } })

// ---- 测试报告 ----

export const generateRunReport = (runId: string, type: 'summary' | 'ai' = 'summary') =>
  api.post<TestReport>(`/reports/generate/${runId}`, null, {
    params: { type },
    timeout: 120000,
  })

export const listReports = (limit = 50, offset = 0) =>
  api.get<PaginatedReports>('/reports', { params: { limit, offset } })

export const getReport = (reportId: string) =>
  api.get<TestReport>(`/reports/${reportId}`)

export const deleteReport = (reportId: string) =>
  api.delete<{ message: string }>(`/reports/${reportId}`)

export const exportReport = (reportId: string, format: 'xlsx' | 'html') =>
  api.get<Blob>(`/reports/${reportId}/export`, {
    params: { format },
    responseType: 'blob',
  })
