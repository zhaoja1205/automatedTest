import axios from 'axios'
import type {
  ApiMessageResponse,
  ExecuteStartResponse,
  SSHConfig,
  SSHStatus,
  TestCase,
  UploadExcelResponse,
  WorkspaceConfig,
} from '../types'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
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