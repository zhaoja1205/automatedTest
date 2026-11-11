/** 测试用例合并 API。 */
import api from './axios'
import type {
  MergeExecutePayload,
  MergeExecuteResponse,
  MergePreviewResponse,
} from '../types/merge'

/** 上传主用例与来源用例，解析来源可选用例列表 */
export const previewMerge = (mainFile: File, sourceFile: File) => {
  const form = new FormData()
  form.append('main_file', mainFile)
  form.append('source_file', sourceFile)
  return api.post<MergePreviewResponse>('/merge/preview', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

/** 按选中的来源用例执行合并 */
export const executeMerge = (payload: MergeExecutePayload) =>
  api.post<MergeExecuteResponse>('/merge/execute', payload, { timeout: 180000 })
