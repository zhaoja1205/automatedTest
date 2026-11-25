/** 把剩余秒数格式化为 mm:ss / h:mm:ss，供进度条等待倒计时展示。 */
export const formatWaitCountdown = (seconds?: number): string => {
  const total = Math.max(0, Math.ceil(Number(seconds) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(secs)}`
    : `${pad(minutes)}:${pad(secs)}`
}
