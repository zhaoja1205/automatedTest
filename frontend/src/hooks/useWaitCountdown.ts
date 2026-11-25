import { useEffect, useState } from 'react'
import type { ExecutionProgress } from '../types'

/**
 * 等待倒计时：后端只在等待开始时推送总时长 / 剩余秒数，
 * store 记录截止时间，各页面按截止时间本地递减。
 *
 * 截止时间保存在 store 的 progress 上，切换页面重新挂载后仍按同
 * 一个截止时间继续倒计时，不会重新从头开始。
 *
 * 返回 null 表示当前不在等待；否则返回剩余秒数（小于等于 0 时为 0）。
 */
export const useWaitCountdown = (
  progress?: ExecutionProgress | null,
): number | null => {
  const deadline = progress?.wait_ends_at
  const [, setTick] = useState(0)

  useEffect(() => {
    if (!deadline) return
    const timer = window.setInterval(() => {
      setTick((value) => value + 1)
      if (Date.now() >= deadline) window.clearInterval(timer)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [deadline])

  if (!deadline) return null
  return Math.max(0, Math.ceil((deadline - Date.now()) / 1000))
}
