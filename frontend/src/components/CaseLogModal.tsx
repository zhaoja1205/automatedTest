/**
 * 单条用例执行日志弹窗。
 *
 * 优先按终端分别展示（执行期间每个终端独立落盘的日志文件），
 * 备注中有日志文本时作为回退；都没有时再读取后端 /logs/content 的聚合日志。
 */
import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Modal, Space, Spin, Tabs, Tooltip, Typography, message } from 'antd'
import { CopyOutlined, DownloadOutlined } from '@ant-design/icons'
import { getCaseLog, getTerminalLogs } from '../api/axios'
import type { TerminalLogPane } from '../types'

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
  /** 按终端分开的板端日志（为空时回退到聚合日志） */
  const [terminals, setTerminals] = useState<TerminalLogPane[]>([])
  const [terminalsLoading, setTerminalsLoading] = useState(false)
  const [activeTerminal, setActiveTerminal] = useState('')

  useEffect(() => {
    if (!open) return

    let cancelled = false
    const localLog = log && log.trim() ? log : ''
    const canFetchTerminals = !!(path || runId || caseKey)

    // 按终端分开的日志：即使备注里已有聚合文本也优先尝试读取，
    // 满足"日志弹窗也按不同终端分开"的需求。
    setTerminals([])
    setActiveTerminal('')
    if (canFetchTerminals) {
      setTerminalsLoading(true)
      getTerminalLogs({ path, run_id: runId, case_key: caseKey })
        .then((res) => {
          if (cancelled) return
          const panes = (res.data.terminals || []).filter(
            (item) => item.label && (item.content || '').trim(),
          )
          setTerminals(panes)
          if (panes.length) setActiveTerminal(panes[0].label)
        })
        .catch(() => {
          // 旧记录没有终端级日志时静默回退到聚合日志
          if (!cancelled) setTerminals([])
        })
        .finally(() => {
          if (!cancelled) setTerminalsLoading(false)
        })
    } else {
      setTerminalsLoading(false)
    }

    if (localLog) {
      setLoading(false)
      setError('')
      setContent(localLog)
      return () => {
        cancelled = true
      }
    }

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

  const splitLines = (text: string) => text.replace(/\r\n?/g, '\n').split('\n')
  const evidenceKeys = useMemo(
    () =>
      Array.from(
        new Set(
          (evidence || [])
            .map((item) => normalizeLine(item))
            .filter((item) => item.length >= 4),
        ),
      ),
    [evidence],
  )
  const isEvidenceLine = (line: string) => {
    const normalized = normalizeLine(line)
    if (!normalized || normalized.length < 4) return false
    return evidenceKeys.some(
      (item) => normalized.includes(item) || item.includes(normalized),
    )
  }
  const highlightedCount = splitLines(content || terminals.map((t) => t.content).join('\n'))
    .filter(isEvidenceLine).length
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

  const logBlockStyle: React.CSSProperties = {
    margin: '8px 0 0',
    maxHeight: '60vh',
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
  }

  const renderLogBlock = (text: string) => (
    <div style={logBlockStyle}>
      {splitLines(text).map((line, index) => {
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
            {line || ' '}
          </div>
        )
      })}
    </div>
  )

  const copyText = async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      message.success(`已复制 ${label} 日志`)
    } catch {
      message.error('复制失败，请手动选择文本')
    }
  }

  const downloadText = (label: string, text: string) => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${label}.term.log`
    link.click()
    URL.revokeObjectURL(url)
  }

  const evidenceLegend = evidenceKeys.length > 0 && (
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
  )

  const renderTerminalPane = (pane: TerminalLogPane) => (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
        }}
      >
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {pane.content.length.toLocaleString()} 字符
        </Typography.Text>
        <Space size={2}>
          <Tooltip title="复制该终端日志">
            <Button
              type="text"
              size="small"
              icon={<CopyOutlined />}
              onClick={() => void copyText(pane.label, pane.content)}
            />
          </Tooltip>
          <Tooltip title="下载该终端日志">
            <Button
              type="text"
              size="small"
              icon={<DownloadOutlined />}
              onClick={() => downloadText(pane.label, pane.content)}
            />
          </Tooltip>
        </Space>
      </div>
      {renderLogBlock(pane.content)}
    </div>
  )

  const hasTerminals = terminals.length > 0
  // 已有聚合日志文本时先展示，终端级日志读回后再切换为分终端标签页，
  // 避免按终端接口异常时弹窗一直停在加载状态。
  const waiting = !hasTerminals && (loading || (terminalsLoading && !content.trim()))
  const logPathText = path || `${runId ? `运行 ${runId} / ` : ''}${caseKey || ''}`

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={920}
      title={title || '执行日志'}
      styles={{ body: { paddingTop: 12 } }}
    >
      {hasTerminals ? (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {logPathText}（按终端分别展示，共 {terminals.length} 个终端）
          </Typography.Text>
          {evidenceLegend}
          <Tabs
            size="small"
            activeKey={activeTerminal || terminals[0].label}
            onChange={setActiveTerminal}
            items={terminals.map((pane) => ({
              key: pane.label,
              label: pane.label,
              children: renderTerminalPane(pane),
            }))}
          />
        </>
      ) : waiting ? (
        <div style={{ textAlign: 'center', padding: '32px 0' }}>
          <Spin tip="加载日志..." />
        </div>
      ) : error ? (
        <Alert type="error" message={error} showIcon />
      ) : content.trim() ? (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {logPathText}（无按终端日志，展示聚合日志）
          </Typography.Text>
          {evidenceLegend}
          {renderLogBlock(content)}
        </>
      ) : (
        <Alert type="info" message="该用例暂无执行日志" showIcon />
      )}
    </Modal>
  )
}
