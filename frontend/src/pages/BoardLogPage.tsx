/**
 * 板端实时日志页。
 *
 * - 执行期间按终端并列展示板端原始输出（多终端并行，各自自动滚动）；
 * - 日志区域下方展示当前用例信息（编号/描述/类型/优先级/步骤/预期结果）与执行阶段；
 * - 执行完成的用例日志由后端按终端落盘，可在此页「历史回看」中重新打开。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeftOutlined, ClearOutlined, CopyOutlined, DownloadOutlined,
  HistoryOutlined, ReloadOutlined, RollbackOutlined,
} from '@ant-design/icons'
import {
  Alert, Button, Card, Descriptions, Empty, Progress, Segmented, Select,
  Space, Spin, Tag, Tooltip, Typography, message,
} from 'antd'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../stores/useStore'
import { getCaseLog, getLiveTerminalLogs, getTerminalLogs } from '../api/axios'
import type { CaseStartInfo, TerminalLogPane, TestCase } from '../types'

const { Text } = Typography

const resolveCaseKey = (testCase: TestCase) =>
  testCase.case_key || `${testCase.source_sheet}:${testCase.row_number}:${testCase.case_id}`

const statusColor = (status: string) => {
  const s = (status || '').toUpperCase()
  if (s === 'PASS') return 'green'
  if (s === 'FAIL') return 'red'
  if (s === 'REVIEW') return 'blue'
  if (s === 'BLOCK') return 'orange'
  if (s === 'RUNNING') return 'processing'
  return 'default'
}

/** 当前/历史用例信息面板 */
interface CaseInfo {
  caseId: string
  description: string
  testType: string
  priority: string
  prerequisites: string
  testSteps: string
  expectedResult: string
  status: string
  logFile?: string
  terminals?: string[]
}

function CaseInfoCard({ info, running }: { info: CaseInfo | null; running: boolean }) {
  if (!info) {
    return (
      <Card style={{ marginBottom: 12 }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="尚未开始执行，开始后这里会显示当前用例信息"
        />
      </Card>
    )
  }
  const status = info.status || (running ? 'Running' : 'NT')
  return (
    <Card
      style={{ marginBottom: 12 }}
      title={
        <Space size={8}>
          <span>当前用例</span>
          <Tag color={statusColor(status)}>{status}</Tag>
          {running && <Tag color="processing">执行中</Tag>}
        </Space>
      }
      size="small"
    >
      <Descriptions column={3} size="small" bordered>
        <Descriptions.Item label="用例编号">{info.caseId || '-'}</Descriptions.Item>
        <Descriptions.Item label="测试类型">{info.testType || '-'}</Descriptions.Item>
        <Descriptions.Item label="优先级">{info.priority || '-'}</Descriptions.Item>
        <Descriptions.Item label="用例描述" span={3}>
          <Text style={{ whiteSpace: 'pre-wrap' }}>{info.description || '-'}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="前置条件" span={3}>
          <Text style={{ whiteSpace: 'pre-wrap' }}>{info.prerequisites || '-'}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="测试步骤" span={3}>
          <pre
            style={{
              margin: 0, maxHeight: 180, overflow: 'auto', whiteSpace: 'pre-wrap',
              wordBreak: 'break-all', fontSize: 12, lineHeight: 1.6,
            }}
          >
            {info.testSteps || '-'}
          </pre>
        </Descriptions.Item>
        <Descriptions.Item label="预期结果" span={3}>
          <Text style={{ whiteSpace: 'pre-wrap' }}>{info.expectedResult || '-'}</Text>
        </Descriptions.Item>
        <Descriptions.Item label="终端" span={2}>
          {info.terminals?.length ? info.terminals.join('、') : '-'}
        </Descriptions.Item>
        <Descriptions.Item label="日志文件">
          <Text type="secondary" style={{ fontSize: 12, wordBreak: 'break-all' }}>
            {info.logFile || '-'}
          </Text>
        </Descriptions.Item>
      </Descriptions>
    </Card>
  )
}

/** 单个终端面板：标题 + 自动滚动输出区 */
function TerminalPaneView({
  label, text, running,
}: { label: string; text: string; running: boolean }) {
  const bodyRef = useRef<HTMLDivElement>(null)
  const [follow, setFollow] = useState(true)

  useEffect(() => {
    if (!follow) return
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [text, follow])

  const handleScroll = () => {
    const el = bodyRef.current
    if (!el) return
    setFollow(el.scrollHeight - el.scrollTop - el.clientHeight < 48)
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      message.success(`已复制 ${label} 日志`)
    } catch {
      message.error('复制失败，请手动选择文本')
    }
  }

  const handleDownload = () => {
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${label}.term.log`
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column', minWidth: 0,
        border: '1px solid #1f2b47', borderRadius: 6, overflow: 'hidden',
        background: '#0b1020', minHeight: 320,
      }}
    >
      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 8, padding: '6px 10px', background: '#151c2e', color: '#c9d1d9',
          borderBottom: '1px solid #1f2b47', flexShrink: 0,
        }}
      >
        <Space size={6}>
          <span
            style={{
              width: 8, height: 8, borderRadius: '50%',
              background: running ? '#36b37e' : '#6b7280',
              boxShadow: running ? '0 0 6px #36b37e' : undefined,
            }}
          />
          <span style={{ fontFamily: 'monospace', fontSize: 13, fontWeight: 600 }}>
            {label}
          </span>
          <Text style={{ color: '#6b7280', fontSize: 11 }}>{text.length.toLocaleString()} 字符</Text>
        </Space>
        <Space size={2}>
          <Tooltip title="复制该终端日志">
            <Button type="text" size="small" icon={<CopyOutlined />} onClick={handleCopy}
              style={{ color: '#9aa4b2' }} />
          </Tooltip>
          <Tooltip title="下载该终端日志">
            <Button type="text" size="small" icon={<DownloadOutlined />} onClick={handleDownload}
              disabled={!text} style={{ color: '#9aa4b2' }} />
          </Tooltip>
        </Space>
      </div>
      <div
        ref={bodyRef}
        onScroll={handleScroll}
        style={{
          flex: 1, overflow: 'auto', padding: '8px 10px', minHeight: 280, maxHeight: '58vh',
          color: '#d6deeb', fontFamily: "Consolas, 'Courier New', monospace",
          fontSize: 12, lineHeight: 1.55, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
        }}
      >
        {text || <span style={{ color: '#5c6773' }}>等待该终端输出...</span>}
      </div>
      {!follow && (
        <div style={{ textAlign: 'right', padding: '2px 8px', background: '#151c2e' }}>
          <Button
            type="link" size="small" icon={<RollbackOutlined />}
            onClick={() => setFollow(true)}
            style={{ color: '#69b1ff', padding: 0 }}
          >
            回到最新
          </Button>
        </div>
      )}
    </div>
  )
}

/** 多终端并列布局 */
function TerminalGrid({
  panes, running,
}: { panes: TerminalLogPane[]; running: boolean }) {
  if (panes.length === 0) {
    return (
      <Card>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无板端日志，开始执行后会在此并列展示各终端的实时输出"
        />
      </Card>
    )
  }
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: 12,
        alignItems: 'stretch',
      }}
    >
      {panes.map((pane) => (
        <TerminalPaneView
          key={pane.label}
          label={pane.label}
          text={pane.content}
          running={running}
        />
      ))}
    </div>
  )
}

export default function BoardLogPage() {
  const navigate = useNavigate()
  const boardTerminal = useStore((s) => s.boardTerminal)
  const currentCaseInfo = useStore((s) => s.currentCaseInfo)
  const progress = useStore((s) => s.progress)
  const isRunning = useStore((s) => s.isRunning)
  const testCases = useStore((s) => s.testCases)
  const clearBoardTerminal = useStore((s) => s.clearBoardTerminal)

  const [mode, setMode] = useState<'live' | 'history'>('live')
  const [refreshKey, setRefreshKey] = useState(0)

  // 历史回看
  const [historyCaseKey, setHistoryCaseKey] = useState('')
  const [historyPanes, setHistoryPanes] = useState<TerminalLogPane[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyMessage, setHistoryMessage] = useState('')
  const [historyError, setHistoryError] = useState('')

  const executedCases = useMemo(
    () => testCases.filter((c) => c.log_file || (c.status && c.status !== 'NT')),
    [testCases],
  )

  const caseOptions = useMemo(
    () => executedCases.map((c) => ({
      value: resolveCaseKey(c),
      label: `${c.case_id} — ${c.description || '(无描述)'} [${c.status || 'NT'}]`,
    })),
    [executedCases],
  )

  const liveCase = useMemo(() => {
    const key = currentCaseInfo?.case_key || progress?.case_key || ''
    if (!key) return undefined
    return testCases.find((c) => resolveCaseKey(c) === key)
  }, [currentCaseInfo, progress, testCases])

  const liveInfo: CaseInfo | null = useMemo(() => {
    if (currentCaseInfo) {
      return {
        caseId: currentCaseInfo.case_id,
        description: currentCaseInfo.description,
        testType: currentCaseInfo.test_type,
        priority: currentCaseInfo.priority,
        prerequisites: currentCaseInfo.prerequisites,
        testSteps: currentCaseInfo.test_steps,
        expectedResult: currentCaseInfo.expected_result,
        status: liveCase?.status || '',
        logFile: currentCaseInfo.log_file,
        terminals: currentCaseInfo.terminals,
      }
    }
    if (liveCase) {
      return {
        caseId: liveCase.case_id,
        description: liveCase.description,
        testType: liveCase.test_type,
        priority: liveCase.priority,
        prerequisites: liveCase.prerequisites,
        testSteps: liveCase.test_steps,
        expectedResult: liveCase.expected_result,
        status: liveCase.status,
        logFile: liveCase.log_file,
      }
    }
    return null
  }, [currentCaseInfo, liveCase])

  const livePanes: TerminalLogPane[] = useMemo(() => {
    const labels = boardTerminal.order.length > 0
      ? boardTerminal.order
      : (currentCaseInfo?.terminals || [])
    return labels.map((label) => ({
      label,
      content: boardTerminal.texts[label] || '',
    }))
  }, [boardTerminal, currentCaseInfo])

  // 首次进入页面 / 点击刷新时，拉取当前执行任务的实时快照，补齐 WebSocket 之前的数据
  useEffect(() => {
    let cancelled = false
    getLiveTerminalLogs()
      .then((res) => {
        if (cancelled) return
        const data = res.data
        const caseInfo = data.case as CaseStartInfo | undefined
        const store = useStore.getState()
        if (caseInfo && caseInfo.case_id) {
          const camel = store.currentCaseInfo
          if (!camel || camel.case_key !== caseInfo.case_key) {
            store.setCurrentCaseInfo(caseInfo)
          }
        }
        if (data.running && data.progress && data.progress.total > 0) {
          const current = store.progress
          // 快照里的进度可能比 WS 推来的旧，只在本地还没有进度时补齐
          if (!current || current.case_id !== data.progress.case_id) {
            store.setProgress(data.progress)
          }
        }
        if (data.terminals?.length) {
          store.loadBoardTerminalSnapshot({
            caseId: data.case_id,
            caseKey: data.case_key,
            terminals: data.terminals,
          })
        }
      })
      .catch(() => {
        // 没有正在执行的任务时接口返回空快照，忽略即可
      })
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  const historyInfo: CaseInfo | null = useMemo(() => {
    if (!historyCaseKey) return null
    const tc = testCases.find((c) => resolveCaseKey(c) === historyCaseKey)
    if (!tc) return null
    return {
      caseId: tc.case_id,
      description: tc.description,
      testType: tc.test_type,
      priority: tc.priority,
      prerequisites: tc.prerequisites,
      testSteps: tc.test_steps,
      expectedResult: tc.expected_result,
      status: tc.status,
      logFile: tc.log_file,
      terminals: historyPanes.map((p) => p.label),
    }
  }, [historyCaseKey, testCases, historyPanes])

  const loadHistory = async (caseKey: string) => {
    setHistoryCaseKey(caseKey)
    setHistoryPanes([])
    setHistoryMessage('')
    setHistoryError('')
    if (!caseKey) return
    setHistoryLoading(true)
    const targetCase = testCases.find((c) => resolveCaseKey(c) === caseKey)
    const logPath = targetCase?.log_file || ''
    try {
      const res = await getTerminalLogs({ case_key: caseKey, path: logPath })
      if (res.data.terminals?.length) {
        setHistoryPanes(res.data.terminals)
      } else {
        // 旧执行记录没有按终端落盘：回退到聚合日志
        try {
          const logRes = await getCaseLog({ case_key: caseKey, path: logPath })
          if (logRes.data.content?.trim()) {
            setHistoryPanes([{ label: '聚合日志', content: logRes.data.content }])
          }
        } catch {
          // 聚合日志也没有时只展示提示
        }
        setHistoryMessage(res.data.message || '')
      }
    } catch (error: unknown) {
      const detail =
        (error as { response?: { data?: { detail?: string } }; message?: string })
          ?.response?.data?.detail
        || (error as Error)?.message
        || '读取板端日志失败'
      setHistoryError(detail)
    } finally {
      setHistoryLoading(false)
    }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%' }}>
      <Card size="small">
        <div
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            flexWrap: 'wrap', gap: 8,
          }}
        >
          <Space size={8}>
            <Typography.Title level={4} style={{ margin: 0 }}>
              板端实时日志
            </Typography.Title>
            <Segmented
              size="small"
              value={mode}
              onChange={(value) => setMode(value as 'live' | 'history')}
              options={[
                { value: 'live', label: '实时日志' },
                { value: 'history', label: '历史回看' },
              ]}
            />
          </Space>
          <Space size={8} wrap>
            {mode === 'live' && (
              <>
                <Tooltip title="重新拉取当前任务的实时快照（WebSocket 重连后可用）">
                  <Button icon={<ReloadOutlined />} onClick={() => setRefreshKey((v) => v + 1)}>
                    刷新快照
                  </Button>
                </Tooltip>
                <Button
                  icon={<ClearOutlined />}
                  danger
                  disabled={boardTerminal.order.length === 0}
                  onClick={clearBoardTerminal}
                >
                  清空面板
                </Button>
              </>
            )}
            {mode === 'history' && (
              <Button
                icon={<HistoryOutlined />}
                disabled={!historyCaseKey}
                onClick={() => void loadHistory(historyCaseKey)}
              >
                重新读取
              </Button>
            )}
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>
              返回执行页
            </Button>
          </Space>
        </div>
      </Card>

      {mode === 'live' ? (
        <>
          {progress && (
            <Card size="small">
              <Progress
                percent={progress.total > 0
                  ? Math.round((progress.current / progress.total) * 100)
                  : 0}
                format={() => `${progress.current}/${progress.total}`}
                strokeColor="#2f54eb"
                status={progress.message ? 'active' : 'normal'}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                <Text style={{ flex: 1, minWidth: 0 }} ellipsis={{ tooltip: progress.message }}>
                  {progress.message || '正在执行'}
                </Text>
                <Text type="secondary">
                  当前用例: {progress.case_id}
                  {isRunning ? '' : '（已结束）'}
                </Text>
              </div>
            </Card>
          )}
          <TerminalGrid panes={livePanes} running={isRunning} />
          <CaseInfoCard info={liveInfo} running={isRunning} />
        </>
      ) : (
        <>
          <Card size="small">
            <Space direction="vertical" size={8} style={{ width: '100%' }}>
              <Text type="secondary">
                选择一条已执行完成的用例，查看执行期间按终端保存的板端日志。
              </Text>
              <Select
                showSearch
                allowClear
                style={{ width: '100%' }}
                placeholder="选择用例（可按编号/描述搜索）"
                value={historyCaseKey || undefined}
                optionFilterProp="label"
                options={caseOptions}
                onChange={(value) => void loadHistory(value || '')}
                notFoundContent="暂无可回看的已执行用例"
              />
            </Space>
          </Card>
          {historyError && <Alert type="error" showIcon message={historyError} />}
          {historyMessage && <Alert type="warning" showIcon message={historyMessage} />}
          {historyLoading ? (
            <Card><div style={{ textAlign: 'center', padding: '32px 0' }}><Spin tip="读取板端日志..." /></div></Card>
          ) : (
            <TerminalGrid panes={historyPanes} running={false} />
          )}
          <CaseInfoCard info={historyInfo} running={false} />
        </>
      )}
    </Space>
  )
}
