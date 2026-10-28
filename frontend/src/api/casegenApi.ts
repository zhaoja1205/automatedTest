/**
 * 生成测试用例模块 API。
 */
import api from './axios'
import type { PlatformConfigParseResult } from '../types/casegen'

/** 读取并解析平台配置文件（predev_mixgroup_platform.json） */
export const parsePlatformConfig = (path: string) =>
  api.post<PlatformConfigParseResult>(
    '/casegen/platform-config/parse',
    { path },
    { timeout: 30000 },
  )

/** 导出请求体 */
export interface ExportCasesPayload {
  platform_name: string
  basic_info: Record<string, string>
  cases: Array<Record<string, string>>
}

/** 导出响应 */
export interface ExportCasesResponse {
  message: string
  download_url: string
  filename: string
  case_count: number
}

/** 导出生成的测试用例为 Excel */
export const exportCases = (data: ExportCasesPayload) =>
  api.post<ExportCasesResponse>(
    '/casegen/export-cases',
    data,
    { timeout: 60000 },
  )

/** 下载已导出的文件 */
export const downloadExportedFile = (filename: string) => {
  const url = `/api/casegen/download/${encodeURIComponent(filename)}`
  window.open(url, '_blank')
}
