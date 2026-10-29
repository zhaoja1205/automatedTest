import { useEffect, useState } from 'react'
import { getCaseImageAvailability } from '../api/axios'

/**
 * 批量查询用例在本机是否已生成 PNG 图片（YUV 出图）。
 *
 * @param caseIds 需要查询的用例 ID，调用方通常只传预期含 yuv 的用例
 * @param refreshKey 变化时重新查询（例如执行状态更新、切换运行记录）
 * @returns case_id -> 是否存在 PNG
 */
export function useCaseImageAvailability(caseIds: string[], refreshKey = '') {
  const [available, setAvailable] = useState<Record<string, boolean>>({})

  // 用排序去重后的字符串做依赖，避免调用方每次渲染新建数组导致重复请求
  const idsKey = Array.from(new Set(caseIds.filter(Boolean))).sort().join('|')

  useEffect(() => {
    if (!idsKey) {
      setAvailable({})
      return
    }
    let cancelled = false
    const ids = idsKey.split('|')
    void getCaseImageAvailability(ids)
      .then((res) => {
        if (!cancelled) setAvailable(res.data.cases || {})
      })
      .catch(() => {
        if (!cancelled) setAvailable({})
      })
    return () => {
      cancelled = true
    }
  }, [idsKey, refreshKey])

  return available
}
