/**
 * 单条用例执行日志弹窗。
 *
 * 优先展示备注中 `--- 执行日志 ---` 之后的日志内容（上传结果表时可直接看到）；
 * 备注中没有日志时，回退到后端 /logs/content 读取日志文件全文。
 */
import { useEffect, useState } from 'react'
import { Alert, Modal, Spin, Typography } from 'antd'
import { getCaseLog } from '../api/axios'

interface Props {
  open: boolean
  title?: string
  log?: string
  /** AI 判定状态（Pass / Fail / Review 等），决定证据行高亮颜色 */
  status?: string
  /** AI 判定时摘录的证据行，用于在执行日志中高亮 */
  evidence?: string[]
  path?: string
  runId?: string
  caseKey?: string
  onClose: () => void
}

/** 归一化文本，便于把 AI 证据行与实际日志行做宽松匹配 */
function normalizeLine(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

export default function CaseLogModal({
  open,
  title,
  log,
  status,
  evidence,
  path,
  runId,
  caseKey,
  onClose,
}: Props) {
  const [loading, setLoading] = useState(false)
  const [content, setContent] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return

    const localLog = log && log.trim() ? log : ''
    if (localLog) {
      setLoading(false)
      setError('')
      setContent(localLog)
      return
    }

    let cancelled = false
    setLoading(true)
    setContent('')
    setError('')
    getCaseLog({ path, run_id: runId, case_key: caseKey })
      .then((res) => {
        if (!cancelled) setContent(res.data.content || '')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const detail =
          (err as { response?: { data?: { detail?: string } }; message?: string })
            ?.response?.data?.detail
          || (err as Error)?.message
          || '读取日志失败'
        setError(detail)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, log, path, runId, caseKey])

  const contentLines = content.replace(/\r\n?/g, '\n').split('\n')
  const evidenceKeys = Array.from(
    new Set(
      (evidence || [])
        .map((item) => normalizeLine(item))
        .filter((item) => item.length >= 4),
    ),
  )
  const isEvidenceLine = (line: string) => {
    const normalized = normalizeLine(line)
    if (!normalized || normalized.length < 4) return false
    return evidenceKeys.some(
      (item) => normalized.includes(item) || item.includes(normalized),
    )
  }
  const highlightedCount = contentLines.filter(isEvidenceLine).length
  const statusText = (status || '').toLowerCase()
  const isPass = statusText.includes('pass')
  const isFail = statusText.includes('fail')
  const highlightTheme = isFail
    ? {
        label: '红色',
        color: '#ffb3a7',
        background: 'rgba(255, 107, 107, 0.16)',
        border: '#ff6b6b',
      }
    : isPass
      ? {
          label: '绿色',
          color: '#9ff5c8',
          background: 'rgba(54, 179, 126, 0.16)',
          border: '#36b37e',
        }
      : {
          label: '黄色',
          color: '#ffe082',
          background: 'rgba(255, 213, 79, 0.16)',
          border: '#ffd54f',
        }

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={920}
      title={title || '执行日志'}
      styles={{ body: { paddingTop: 12 } }}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <Spin tip="加载日志..." />
        </div>
      ) : error ? (
        <Alert type="error" message={error} showIcon />
      ) : content.trim() ? (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {path || `${runId ? `运行 ${runId} / ` : ''}${caseKey || ''}`}
          </Typography.Text>
          {evidenceKeys.length > 0 && (
            <div style={{ marginTop: 4, fontSize: 12, color: '#8b949e' }}>
              <span
                style={{
                  display: 'inline-block',
                  width: 10,
                  height: 10,
                  marginRight: 6,
                  verticalAlign: 'middle',
                  background: highlightTheme.background,
                  boxShadow: `inset 2px 0 0 ${highlightTheme.border}`,
                }}
              />
              {highlightTheme.label}高亮为 AI 判定证据行（已高亮 {highlightedCount} 行）
            </div>
          )}
          <div
            style={{
              margin: '8px 0 0',
              maxHeight: '65vh',
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-all',
              background: '#0b1020',
              color: '#d6deeb',
              padding: 12,
              borderRadius: 6,
              fontSize: 12,
              lineHeight: 1.6,
              fontFamily: "Consolas, 'Courier New', monospace",
            }}
          >
            {contentLines.map((line, index) => {
              const highlighted = isEvidenceLine(line)
              return (
                <div
                  key={index}
                  style={
                    highlighted
                      ? {
                          color: highlightTheme.color,
                          background: highlightTheme.background,
                          boxShadow: `inset 2px 0 0 ${highlightTheme.border}`,
                        }
                      : undefined
                  }
                >
                  {line || ' '}
                </div>
              )
            })}
          </div>
        </>
      ) : (
        <Alert type="info" message="该用例暂无执行日志" showIcon />
      )}
    </Modal>
  )
}
