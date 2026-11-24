/**
 * 单条用例执行日志弹窗。
 *
 * 日志来源与「下载结果」保持一致：优先使用用例备注中的日志文本
 * （备注即导出结果写入的同一份日志），按 ``===== 终端 =====`` 分段分终端展示；
 * 备注中没有日志时（旧记录 / 草稿）再回退读取后端 /logs/content 的聚合日志。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert, Button, Modal, Space, Spin, Tabs, Tooltip, Typography, message,
} from 'antd'
import {
  CopyOutlined, DownloadOutlined, EditOutlined, HighlightOutlined,
} from '@ant-design/icons'
import { getCaseLog } from '../api/axios'
import type { ManualEvidencePayload } from '../api/axios'
import type { TerminalLogPane } from '../types'
import { parseTerminalLog, stripTerminalControl } from '../utils/terminalLogFormat'

interface Props {
  open: boolean
  title?: string
  log?: string
  /** AI 判定状态（Pass / Fail / Review 等），决定证据行高亮颜色 */
  status?: string
  /** AI 判定时摘录的证据行，用于在执行日志中高亮 */
  evidence?: string[]
  /** 用户手动选择的高亮行内容快照（用于下载日志图片高亮） */
  manualEvidence?: string[]
  /** 按行号选择的行标识（JSON [终端标签, 行号]） */
  manualEvidenceLines?: string[]
  /** 提供时允许手动选择高亮行，并保存选择结果 */
  onManualEvidenceChange?: (payload: ManualEvidencePayload) => void | Promise<void>
  path?: string
  runId?: string
  caseKey?: string
  /** 提供时显示「编辑」入口（执行测试页可直接修改实际结果与日志） */
  onEdit?: () => void
  onClose: () => void
}

/** 归一化文本，便于把证据行与实际日志行做宽松匹配 */
function normalizeLine(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

/** 按行号选择时使用的行标识：JSON [终端标签, 1 起始行号] */
function makeLineId(label: string, index: number): string {
  return JSON.stringify([label || '', index + 1])
}

function parseLineId(id: string): { label: string; index: number } | null {
  try {
    const parsed: unknown = JSON.parse(id)
    if (!Array.isArray(parsed) || parsed.length < 2) return null
    const lineNo = Number(parsed[1])
    if (!Number.isFinite(lineNo) || lineNo < 1) return null
    return { label: String(parsed[0] ?? ''), index: lineNo - 1 }
  } catch {
    return null
  }
}

export default function CaseLogModal({
  open,
  title,
  log,
  status,
  evidence,
  manualEvidence,
  manualEvidenceLines,
  onManualEvidenceChange,
  path,
  runId,
  caseKey,
  onEdit,
  onClose,
}: Props) {
  const [loading, setLoading] = useState(false)
  const [content, setContent] = useState('')
  const [error, setError] = useState('')
  /** 按行号选择的高亮行标识（JSON [终端标签, 行号]） */
  const [manualLineIds, setManualLineIds] = useState<string[]>([])
  /** 是否处于「点击日志行选择高亮」模式 */
  const [manualMode, setManualMode] = useState(false)
  const [manualDirty, setManualDirty] = useState(false)
  const [manualSaving, setManualSaving] = useState(false)
  /** 拖拽选择区间：记录起点行、区间内所有行的标识，以及按下时的选择基线 */
  const dragSelectionRef = useRef<{
    startIndex: number
    lineIds: string[]
    remove: boolean
    baseLineIds: string[]
  } | null>(null)
  const [activeTerminal, setActiveTerminal] = useState('')

  useEffect(() => {
    if (!open) return

    let cancelled = false
    // 备注里的日志就是导出结果使用的那份，优先展示；
    // 只有备注没有日志（旧记录 / 草稿）时才回退读取后端聚合日志。
    const localLog = log && log.trim() ? log : ''
    setActiveTerminal('')

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

  // 每次打开或保存后同步手动高亮行，避免残留上一条用例的选择
  useEffect(() => {
    if (!open) return
    setManualLineIds(
      (manualEvidenceLines || []).map((line) => line.trim()).filter(Boolean),
    )
    setManualMode(false)
    setManualDirty(false)
    dragSelectionRef.current = null
  }, [open, manualEvidence, manualEvidenceLines])

  // 鼠标在弹窗/日志区域外松开时也要结束拖拽，避免下一次进入日志行误扩展区间
  useEffect(() => {
    const finishDrag = () => {
      dragSelectionRef.current = null
    }
    window.addEventListener('mouseup', finishDrag)
    window.addEventListener('blur', finishDrag)
    return () => {
      window.removeEventListener('mouseup', finishDrag)
      window.removeEventListener('blur', finishDrag)
    }
  }, [])

  const splitLines = (text: string) => stripTerminalControl(text).replace(/\r\n?/g, '\n').split('\n')
  // 按 ``===== 终端 =====`` 分段拆出各终端，保持统一的按终端展示。
  const terminalPanes = useMemo<TerminalLogPane[]>(
    () => parseTerminalLog(content).filter((pane) => (pane.content || '').trim()),
    [content],
  )
  // 旧记录按内容保存的手动高亮：日志加载完成后把命中的行转换为行号标识，
  // 之后统一按行号展示与保存，不再保留按内容匹配的选择方式。
  // 保存过行号后不再转换，避免覆盖用户新选择的行。
  useEffect(() => {
    if (!open) return
    if ((manualEvidenceLines || []).some((line) => line.trim())) return
    if ((manualEvidence?.length || 0) === 0) return
    const panes = terminalPanes.length > 0
      ? terminalPanes
      : (content.trim() ? [{ label: '', content }] : [])
    // 日志尚未加载时等待下一次终端 / 聚合日志更新
    if (panes.length === 0) return
    const contents = new Set(
      (manualEvidence || []).map(normalizeLine).filter((line) => line.length > 0),
    )
    const lineIds: string[] = []
    panes.forEach((pane) => {
      splitLines(pane.content).forEach((line, index) => {
        if (contents.has(normalizeLine(line))) {
          lineIds.push(makeLineId(pane.label, index))
        }
      })
    })
    setManualLineIds(Array.from(new Set(lineIds)))
  }, [open, manualEvidence, manualEvidenceLines, terminalPanes, content])
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
  const manualLineKeys = useMemo(
    () => new Set((manualLineIds || []).map((item) => item.trim()).filter(Boolean)),
    [manualLineIds],
  )
  /** 手动选择非空时覆盖 AI 证据 */
  const usingManual = manualLineKeys.size > 0
  const isHighlightedLine = (line: string, lineId: string) => {
    const normalized = normalizeLine(line)
    // 按行号精确匹配，内容相同的其它行不会一起高亮
    if (manualLineKeys.size > 0) return manualLineKeys.has(lineId)
    if (!normalized || normalized.length < 4) return false
    // 只允许「日志行包含证据」：证据行若只是日志行的一小段（如公共前缀
    // ``nvsipl_camera: ERROR:``）不再命中，避免牵连同前缀的其它日志行。
    return evidenceKeys.some((item) => normalized.includes(item))
  }
  const highlightedCount = terminalPanes.length > 0
    ? terminalPanes.reduce(
        (sum, pane) => sum + splitLines(pane.content).filter(
          (line, index) => isHighlightedLine(line, makeLineId(pane.label, index)),
        ).length,
        0,
      )
    : splitLines(content).filter(
        (line, index) => isHighlightedLine(line, makeLineId('', index)),
      ).length
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

  /** 按行号标识取原始行内容，作为下载日志图片高亮的内容快照 */
  const resolveLineContent = (lineId: string): string => {
    const parsed = parseLineId(lineId)
    if (!parsed) return ''
    const pane = terminalPanes.find((item) => item.label === parsed.label)
      || (parsed.label === '' ? { label: '', content } : undefined)
    if (!pane) return ''
    return normalizeLine(splitLines(pane.content)[parsed.index] || '')
  }

  const buildManualPayload = (lines: string[]): ManualEvidencePayload => ({
    lines,
    contents: Array.from(new Set(lines.map(resolveLineContent).filter(Boolean))),
  })

  const saveManualSelections = async (
    lines: string[] = manualLineIds,
  ): Promise<void> => {
    if (!onManualEvidenceChange) return
    setManualSaving(true)
    try {
      await onManualEvidenceChange(buildManualPayload(lines))
      setManualDirty(false)
    } finally {
      setManualSaving(false)
    }
  }

  const toggleManualMode = () => {
    if (manualMode && manualDirty) {
      void saveManualSelections().catch(() => {})
    }
    setManualMode((value) => !value)
  }

  /** 鼠标按下：单击切换单行，按住拖动则从起点扩展/收缩连续区间 */
  const startManualDrag = (
    event: React.MouseEvent<HTMLDivElement>,
    lineId: string,
    index: number,
    lineIds: string[],
  ) => {
    if (!manualMode || !onManualEvidenceChange) return
    if (event.button !== 0) return
    event.preventDefault()
    const selected = manualLineKeys.has(lineId)
    dragSelectionRef.current = {
      startIndex: index,
      lineIds,
      remove: selected,
      baseLineIds: [...manualLineIds],
    }
    setManualLineIds(
      selected
        ? manualLineIds.filter((item) => item !== lineId)
        : [...manualLineIds, lineId],
    )
    setManualDirty(true)
  }

  /** 拖拽经过某行：按起点到当前行的连续区间更新选择，基于按下时的基线计算 */
  const extendManualDrag = (index: number) => {
    const drag = dragSelectionRef.current
    if (!drag) return
    const start = Math.min(drag.startIndex, index)
    const end = Math.max(drag.startIndex, index)
    const rangeIds = drag.lineIds.slice(start, end + 1)
    if (drag.remove) {
      const rangeSet = new Set(rangeIds)
      setManualLineIds(drag.baseLineIds.filter((item) => !rangeSet.has(item)))
    } else {
      const next = new Set(drag.baseLineIds)
      rangeIds.forEach((item) => next.add(item))
      setManualLineIds(Array.from(next))
    }
    setManualDirty(true)
  }

  const clearManualLines = () => {
    setManualMode(false)
    setManualLineIds([])
    void saveManualSelections([]).catch(() => {})
  }

  /** 关闭/切换弹窗之前先保存未保存的手动高亮选择 */
  const closeWithSave = (after: () => void) => {
    if (manualDirty && onManualEvidenceChange) {
      void saveManualSelections()
        .catch(() => {})
        .finally(after)
      return
    }
    after()
  }
  const handleClose = () => closeWithSave(onClose)
  const handleEdit = () => {
    if (onEdit) closeWithSave(onEdit)
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

  const renderLogBlock = (text: string, label = '') => {
    const showLineNumbers = manualMode
    const lines = splitLines(text)
    const lineIds = lines.map((_, index) => makeLineId(label, index))
    return (
      <div
        style={{
          ...logBlockStyle,
          // 选择模式下禁用原生文本选择，避免拖拽时选中整段日志文本
          ...(manualMode ? { userSelect: 'none' } : {}),
        }}
      >
        {lines.map((line, index) => {
          const lineId = lineIds[index]
          const highlighted = isHighlightedLine(line, lineId)
          const selectable = manualMode && !!onManualEvidenceChange
          return (
            <div
              key={index}
              className={selectable ? 'case-log-select-line' : undefined}
              onMouseDown={selectable
                ? (event) => startManualDrag(event, lineId, index, lineIds)
                : undefined}
              onMouseEnter={selectable ? () => extendManualDrag(index) : undefined}
              style={{
                ...(highlighted
                  ? {
                      color: highlightTheme.color,
                      background: highlightTheme.background,
                      boxShadow: `inset 2px 0 0 ${highlightTheme.border}`,
                    }
                  : {}),
                ...(showLineNumbers ? { display: 'flex', gap: 8 } : {}),
              }}
            >
              {showLineNumbers && (
                <span className="case-log-line-no">{index + 1}</span>
              )}
              <span style={showLineNumbers ? { flex: 1, minWidth: 0 } : undefined}>
                {line || ' '}
              </span>
            </div>
          )
        })}
      </div>
    )
  }

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

  const evidenceLegend = (usingManual || evidenceKeys.length > 0) && (
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
      {usingManual
        ? `手动高亮 ${highlightedCount} 行（按行号匹配，已覆盖 AI 证据${evidenceKeys.length > 0 ? `；AI 证据 ${evidenceKeys.length} 条` : ''}）`
        : `${highlightTheme.label}高亮为 AI 判定证据行（已高亮 ${highlightedCount} 行）`}
    </div>
  )

  const manualToolbar = onManualEvidenceChange ? (
    <div
      style={{
        marginTop: 8,
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'center',
        gap: 8,
      }}
    >
      <Button
        size="small"
        type={manualMode ? 'primary' : 'default'}
        icon={<HighlightOutlined />}
        onClick={toggleManualMode}
      >
        {manualMode ? '完成选择' : '手动选择高亮行'}
      </Button>
      {manualMode && (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          点击或按住拖拽选择连续日志行（按行号匹配）
        </Typography.Text>
      )}
      {usingManual && (
        <Typography.Text style={{ fontSize: 12, color: '#2f54eb' }}>
          已手动选择 {manualLineKeys.size} 行（覆盖 AI 证据）
        </Typography.Text>
      )}
      {manualDirty && (
        <Typography.Text style={{ fontSize: 12, color: '#d46b08' }}>
          未保存
        </Typography.Text>
      )}
      {(manualDirty || manualSaving) && (
        <Button
          size="small"
          loading={manualSaving}
          onClick={() => { void saveManualSelections().catch(() => {}) }}
        >
          保存高亮
        </Button>
      )}
      {usingManual && (
        <Button size="small" danger onClick={clearManualLines}>
          清除手动高亮
        </Button>
      )}
    </div>
  ) : null

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
      {renderLogBlock(pane.content, pane.label)}
    </div>
  )

  const hasTerminals = terminalPanes.length > 0
  const usingRemarksLog = !!(log && log.trim())
  const waiting = !hasTerminals && loading
  const logPathText = path || `${runId ? `运行 ${runId} / ` : ''}${caseKey || ''}`
  const sourceLabel = usingRemarksLog ? '备注日志' : '聚合日志'

  return (
    <Modal
      open={open}
      onCancel={handleClose}
      footer={onEdit ? (
        <Space>
          <Button onClick={handleClose}>关闭</Button>
          <Button type="primary" icon={<EditOutlined />} onClick={handleEdit}>
            编辑实际结果与日志
          </Button>
        </Space>
      ) : null}
      width={920}
      title={title || '执行日志'}
      styles={{ body: { paddingTop: 12 } }}
    >
      {hasTerminals ? (
        <>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {logPathText}（{sourceLabel}，按终端分别展示，共 {terminalPanes.length} 个终端）
          </Typography.Text>
          {manualToolbar}
          {evidenceLegend}
          <Tabs
            size="small"
            activeKey={activeTerminal || terminalPanes[0].label || 'terminal-0'}
            onChange={setActiveTerminal}
            items={terminalPanes.map((pane, index) => ({
              key: pane.label || `terminal-${index}`,
              label: pane.label || '聚合日志',
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
            {logPathText}（{sourceLabel}）
          </Typography.Text>
          {manualToolbar}
          {evidenceLegend}
          {renderLogBlock(content)}
        </>
      ) : (
        <Alert type="info" message="该用例暂无执行日志" showIcon />
      )}
    </Modal>
  )
}
