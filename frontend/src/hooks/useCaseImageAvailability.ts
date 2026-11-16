import { useEffect, useRef, useState } from 'react'
import { getCaseImageAvailability, type CaseImageAvailabilityItem } from '../api/axios'

/**
 * 批量查询用例在本机是否已生成 PNG 图片（YUV 出图）。
 *
 * 结果按 case_key 索引：同一 case_id 可能同时出现在「功能测试」「故障测试」，
 * 若按 case_id 索引，两个 Sheet 的用例会互相覆盖。
 *
 * @param cases 需要查询的用例（调用方通常只传预期含 yuv 的用例）
 * @param refreshKey 变化时重新查询（例如执行状态更新、切换运行记录）
 * @returns case_key -> 是否存在 PNG
 */
export function useCaseImageAvailability(
  cases: CaseImageAvailabilityItem[],
  refreshKey = '',
) {
  const [available, setAvailable] = useState<Record<string, boolean>>({})

  // 用 case_key 去重排序后的字符串做依赖，避免调用方每次渲染新建数组导致重复请求
  const idsKey = Array.from(new Set(cases.map((c) => c.case_key).filter(Boolean)))
    .sort()
    .join('|')

  // 依赖只用稳定的 idsKey；用例内容通过 ref 读取，避免数组引用变化触发重复请求
  const latestCases = useRef(cases)
  latestCases.current = cases

  useEffect(() => {
    if (!idsKey) {
      setAvailable({})
      return
    }
    let cancelled = false
    const payload = latestCases.current
      .filter((c) => c.case_key && c.case_id)
      .map((c) => ({
        case_key: c.case_key,
        case_id: c.case_id,
        source_sheet: c.source_sheet || '',
      }))
    void getCaseImageAvailability(payload)
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
