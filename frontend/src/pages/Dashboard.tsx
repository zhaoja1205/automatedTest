import { useState, useEffect, useCallback } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Row, Col, Upload, Button, Table, Tag, Progress, Statistic,
  Space, Typography, message, Alert, Radio, Checkbox, Tooltip, Dropdown, Popover,
} from 'antd'
import {
  UploadOutlined, PlayCircleOutlined, StopOutlined,
  DownloadOutlined, CheckOutlined, CloseOutlined,
  RobotOutlined, BulbOutlined, FileTextOutlined, CodeOutlined,
  ExperimentOutlined, LoadingOutlined, DownOutlined, QuestionCircleOutlined,
  PictureOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { optionalCaseColumnKeys, useStore } from '../stores/useStore'
import { useWebSocket } from '../hooks/useWebSocket'
import AIAnalysisDrawer from '../components/AIAnalysisDrawer'
import AIReportModal from '../components/AIReportModal'
import CaseLogModal from '../components/CaseLogModal'
import CaseImagesModal from '../components/CaseImagesModal'
import CommandPreviewModal from '../components/CommandPreviewModal'
import TestStepRulesModal from '../components/TestStepRulesModal'
import {
  downloadResults,
  getCases,
  getSSHConfig,
  getSSHStatus,
  getWorkspace,
  selectCases,
  startExecution,
  uploadExcel,
  analyzeAllFailures,
  aiParseSteps,
  setWorkspace as apiSetWorkspace,
} from '../api/axios'
import {
  isWorkspaceConfigChanged,
  loadStoredWorkspace,
  mergeWorkspaceConfig,
} from '../utils/workspaceStorage'
import { extractAiEvidence, extractLogText, parseRemark } from '../utils/remarkDisplay'
import { canShowCaseImages } from '../utils/caseImages'
import type { TestCase, AIAnalysis, AIParsedStep } from '../types'

const { Text } = Typography

/** 选择栏快捷选项：按执行状态批量选中当前表页的用例 */
const QUICK_SELECT_STATUSES = [
  { status: 'NT', label: 'NT' },
  { status: 'FAIL', label: 'Fail' },
  { status: 'PASS', label: 'Pass' },
  { status: 'REVIEW', label: 'Review' },
  { status: 'BLOCK', label: 'Block' },
  { status: 'NA', label: 'NA' },
]

export default function Dashboard() {
  const navigate = useNavigate()
  const store = useStore()
  const { visibleCaseColumnKeys: visibleColumnKeys, setVisibleCaseColumnKeys: setVisibleColumnKeys } = store
  const ws = useWebSocket()
  const [loading, setLoading] = useState(false)
  // 分页状态
  const [currentPage, setCurrentPage] = useState(1)
  const pageSize = 20
  // AI 分析相关状态
  const [aiDrawerOpen, setAIDrawerOpen] = useState(false)
  const [aiDrawerCase, setAIDrawerCase] = useState<TestCase | null>(null)
  const [aiAnalysisCache, setAIAnalysisCache] = useState<Record<string, AIAnalysis>>({})
  const [aiBatchAnalyzing, setAIBatchAnalyzing] = useState(false)
  const [aiReportOpen, setAIReportOpen] = useState(false)
  // AI 步骤解析缓存
  const [aiParsedSteps, setAIParsedSteps] = useState<Record<string, AIParsedStep[]>>({})
  const [aiParsingCase, setAIParsingCase] = useState<string>('')
  // 执行日志弹窗
  const [logModalCase, setLogModalCase] = useState<TestCase | null>(null)
  // YUV 出图弹窗（查看板端下载回来的 PNG）
  const [imageModalCase, setImageModalCase] = useState<TestCase | null>(null)
  // 命令预览弹窗（为空表示关闭）
  const [previewCommandKeys, setPreviewCommandKeys] = useState<string[] | null>(null)
  // 测试步骤编写规则弹窗
  const [stepRulesOpen, setStepRulesOpen] = useState(false)

  const handleAIAnalyze = useCallback((record: TestCase) => {
    setAIDrawerCase(record)
    setAIDrawerOpen(true)
  }, [])

  const handleAIParseStep = useCallback(async (record: TestCase) => {
    const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
    if (aiParsingCase) return
    setAIParsingCase(caseKey)
    try {
      const res = await aiParseSteps({
        step_text: record.test_steps,
        context: record.description,
        case_id: caseKey,
      })
      if (res.data.parsed_steps) {
        setAIParsedSteps(prev => ({ ...prev, [caseKey]: res.data.parsed_steps }))
        store.addAIParsedCase(caseKey)
        message.success(`AI 识别 ${res.data.ai_recognized} 条命令`)
      }
    } catch {
      message.error('AI 步骤解析失败')
    } finally {
      setAIParsingCase('')
    }
  }, [aiParsingCase])

  const handleAnalysisDone = useCallback((caseKey: string, analysis: AIAnalysis) => {
    setAIAnalysisCache(prev => ({ ...prev, [caseKey]: analysis }))
  }, [])

  const handleBatchAnalyze = useCallback(async () => {
    setAIBatchAnalyzing(true)
    try {
      const res = await analyzeAllFailures()
      const { analyses, total, analyzed } = res.data
      const newCache: Record<string, AIAnalysis> = { ...aiAnalysisCache }
      for (const a of analyses) {
        newCache[a.case_id] = a
      }
      setAIAnalysisCache(newCache)
      message.success(`AI 分析完成：${analyzed}/${total} 个失败用例已分析`)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '批量分析失败'
      message.error(detail)
    } finally {
      setAIBatchAnalyzing(false)
    }
  }, [aiAnalysisCache])

  const getErrorMessage = (error: unknown, fallback: string) => {
    if (isAxiosError<{ detail?: string }>(error))
      return error.response?.data?.detail || error.message || fallback
    if (error instanceof Error) return error.message
    return fallback
  }

  useEffect(() => {
    loadConfigs()
  }, [])

  const loadConfigs = async () => {
    try {
      const [ssh, workspace] = await Promise.all([getSSHConfig(), getWorkspace()])
      const sshStatus = await getSSHStatus()
      store.setSSHConfig(ssh.data)
      store.setSSHStatus(sshStatus.data)
      // 浏览器本地保存的工作区配置优先，并同步到后端供执行使用
      const storedWorkspace = loadStoredWorkspace()
      const mergedWorkspace = mergeWorkspaceConfig(workspace.data, storedWorkspace)
      store.setWorkspace(mergedWorkspace)
      if (storedWorkspace && isWorkspaceConfigChanged(mergedWorkspace, workspace.data)) {
        try {
          await apiSetWorkspace(mergedWorkspace)
        } catch (syncError) {
          console.warn('[Dashboard] 同步工作区配置到后端失败', syncError)
        }
      }
    } catch (error) {
      message.warning(getErrorMessage(error, '加载配置失败'))
    }
  }

  const handleUpload = async (file: File) => {
    setLoading(true)
    // 先清除旧的 AI 解析状态，避免上传后 WS 消息到达又被清空的时序问题
    setAIParsedSteps({})
    store.clearAIParsedCases()
    store.setAIParseProgress(null)
    try {
      const res = await uploadExcel(file)
      store.setSheets(res.data.sheets)
      store.setCurrentSheet(res.data.sheets[0] || '')
      const cases = await getCases()
      store.setTestCases(cases.data)
      message.success(`已加载 ${res.data.case_count} 条用例`)
    } catch (error) {
      message.error(getErrorMessage(error, '上传失败'))
    } finally {
      setLoading(false)
    }
    return false
  }

  const handleStart = async () => {
    try {
      const selectedKeys = store.testCases.filter((c) => c.selected).map((c) => c.case_key)
      await startExecution(selectedKeys)
      store.setIsRunning(true)
      store.clearLogs()
      store.resetSelectedCases()
      message.success(`执行已启动，已选择 ${selectedKeys.length} 条用例`)
    } catch (error) {
      message.error(getErrorMessage(error, '启动失败'))
    }
  }

  const handleStop = () => { ws.stopExecution() }

  /** blob 响应出错时，后端返回的 JSON detail 藏在 Blob 里，需要先解析 */
  const getDownloadErrorMessage = async (error: unknown, fallback: string) => {
    if (isAxiosError(error) && error.response?.data instanceof Blob) {
      try {
        const payload = JSON.parse(await error.response.data.text())
        if (payload?.detail) return String(payload.detail)
      } catch {
        // 非 JSON 响应，回退到通用错误信息
      }
    }
    return getErrorMessage(error, fallback)
  }

  const handleDownload = async (includeLog: boolean) => {
    try {
      const res = await downloadResults(includeLog)
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = includeLog ? 'test_results.xlsx' : 'test_results_无日志.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      message.error(await getDownloadErrorMessage(error, '下载失败'))
    }
  }

  const handleConfirm = (result: boolean) => {
    if (store.confirmRequest) {
      ws.confirmResponse(store.confirmRequest.confirm_id, result)
    }
  }

  const handleCaseSelectedChange = async (record: TestCase, selected: boolean) => {
    const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
    store.updateCaseSelected(caseKey, selected)
    try {
      await selectCases([record.case_id], selected)
    } catch (error) {
      store.updateCaseSelected(caseKey, !selected)
      message.error(getErrorMessage(error, '更新用例选择失败'))
    }
  }

  const handleSelectAll = async (selected: boolean) => {
    const currentCases = store.testCases.filter((c) => c.source_sheet === store.currentSheet)
    const caseKeys = currentCases.map((c) => c.case_key)
    caseKeys.forEach((key) => store.updateCaseSelected(key, selected))
    try {
      await selectCases(currentCases.map((c) => c.case_id), selected)
    } catch (error) {
      caseKeys.forEach((key) => store.updateCaseSelected(key, !selected))
      message.error(getErrorMessage(error, '批量更新用例选择失败'))
    }
  }

  const handleSheetChange = (sheet: string) => {
    store.setCurrentSheet(sheet)
    setCurrentPage(1)
  }

  const filteredCases = store.currentSheet
    ? store.testCases.filter((c) => c.source_sheet === store.currentSheet)
    : store.testCases

  // 当前页用例（用于按页选中）
  const pageCases = filteredCases.slice((currentPage - 1) * pageSize, currentPage * pageSize)

  const handleSelectPage = async (selected: boolean) => {
    const cases = pageCases
    const caseKeys = cases.map((c) => c.case_key)
    caseKeys.forEach((key) => store.updateCaseSelected(key, selected))
    try {
      await selectCases(cases.map((c) => c.case_id), selected)
    } catch (error) {
      caseKeys.forEach((key) => store.updateCaseSelected(key, !selected))
      message.error(getErrorMessage(error, '批量更新用例选择失败'))
    }
  }

  /** 按状态选中当前表页的所有用例 */
  const handleSelectByStatus = async (status: string, label: string) => {
    const targetCases = filteredCases.filter(
      (c) => (c.status || 'NT').toUpperCase() === status,
    )
    if (targetCases.length === 0) {
      message.info(`当前表页没有 ${label} 用例`)
      return
    }
    const caseKeys = targetCases.map((c) => c.case_key)
    caseKeys.forEach((key) => store.updateCaseSelected(key, true))
    try {
      await selectCases(targetCases.map((c) => c.case_id), true)
      message.success(`已选中 ${targetCases.length} 条 ${label} 用例`)
    } catch (error) {
      caseKeys.forEach((key) => store.updateCaseSelected(key, false))
      message.error(getErrorMessage(error, '批量更新用例选择失败'))
    }
  }

  const statusCounts = filteredCases.reduce<Record<string, number>>((acc, c) => {
    const status = (c.status || 'NT').toUpperCase()
    acc[status] = (acc[status] || 0) + 1
    return acc
  }, {})
  const statusQuickSelectItems = QUICK_SELECT_STATUSES
    .filter(({ status }) => (statusCounts[status] || 0) > 0)
    .map(({ status, label }) => ({
      key: `selectStatus:${status}`,
      label: `选中所有 ${label}（${statusCounts[status]}）`,
    }))

  // ===== 表格列定义 =====
  const columns: ColumnsType<TestCase> = [
    {
      title: (
        <Space size={0} align="center">
          <Checkbox
            checked={filteredCases.length > 0 && filteredCases.every((c) => c.selected)}
            indeterminate={filteredCases.some((c) => c.selected) && !filteredCases.every((c) => c.selected)}
            onChange={(e) => handleSelectAll(e.target.checked)}
          />
          <Dropdown menu={{
            items: [
              { key: 'selectPage', label: '选择本页' },
              { key: 'selectAll', label: '选择全部' },
              ...(statusQuickSelectItems.length > 0
                ? [
                    { type: 'divider' as const },
                    {
                      key: 'selectByStatus',
                      label: '按状态选择',
                      children: statusQuickSelectItems,
                    },
                  ]
                : []),
              { type: 'divider' as const },
              { key: 'deselectPage', label: '取消本页' },
              { key: 'deselectAll', label: '取消全部' },
            ],
            onClick: ({ key }) => {
              if (key === 'selectPage') void handleSelectPage(true)
              else if (key === 'selectAll') void handleSelectAll(true)
              else if (key === 'deselectPage') void handleSelectPage(false)
              else if (key === 'deselectAll') void handleSelectAll(false)
              else if (key.startsWith('selectStatus:')) {
                const status = key.slice('selectStatus:'.length)
                const label = QUICK_SELECT_STATUSES.find((s) => s.status === status)?.label || status
                void handleSelectByStatus(status, label)
              }
            },
          }} trigger={['click']}>
            <DownOutlined style={{ fontSize: 10, cursor: 'pointer', marginLeft: 2, color: '#999' }} />
          </Dropdown>
        </Space>
      ),
      key: 'selected',
      dataIndex: 'selected',
      width: 48,
      fixed: 'left',
      render: (_: boolean, record) => (
        <Checkbox
          checked={record.selected}
          onChange={(e) => handleCaseSelectedChange(record, e.target.checked)}
        />
      ),
    },
    {
      title: '#',
      key: 'index',
      width: 50,
      fixed: 'left',
      render: (_: unknown, __: TestCase, index: number) => (
        <span style={{ color: '#9ca3af' }}>{index + 1}</span>
      ),
    },
    { title: '用例编号', key: 'case_id', dataIndex: 'case_id', width: 130, fixed: 'left',
      render: (text: string, record: TestCase) => {
        const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
        const isParsed = store.aiParsedCases.has(caseKey) || !!aiParsedSteps[caseKey]
        return (
          <Space size={4} align="start" className="case-cell-content">
            <span>{text}</span>
            {isParsed && (
              <Tooltip title="AI 步骤已解析">
                <RobotOutlined style={{ color: '#722ed1', fontSize: 12 }} />
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    { title: '用例描述', key: 'description', dataIndex: 'description', width: 200 },
    { title: '测试类型', key: 'test_type', dataIndex: 'test_type', width: 100 },
    { title: '优先级', key: 'priority', dataIndex: 'priority', width: 80 },
    {
      title: '状态', key: 'status', dataIndex: 'status', width: 120,
      render: (s: string, record: TestCase) => {
        const colors: Record<string, string> = { Pass: 'green', Fail: 'red', NT: 'default', BLOCK: 'orange', NA: 'default', Running: 'processing', Review: 'blue' }
        const labels: Record<string, string> = { Review: '待确认' }
        const isAIJudged = record.actual_result?.includes('[AI判定]')
        const confMatch = record.actual_result?.match(/\[规则置信度=([\d.]+)\]/)
        const confidence = confMatch ? parseFloat(confMatch[1]) : null
        const caseKey = record.case_key || record.case_id
        const hasAnalysis = !!aiAnalysisCache[caseKey]
        return (
          <Space direction="vertical" size={2}>
            <Tag color={colors[s] || 'default'} style={{ fontSize: 14, padding: '2px 12px', lineHeight: '24px', borderRadius: 12, fontWeight: 600 }}>{labels[s] || s}</Tag>
            {isAIJudged && (
              <Tag color="purple" style={{ fontSize: 11, padding: '0 6px', lineHeight: '20px', borderRadius: 10 }}>
                <RobotOutlined style={{ marginRight: 2 }} />AI
              </Tag>
            )}
            {confidence !== null && !isAIJudged && (
              <Tooltip title={`规则引擎置信度: ${(confidence * 100).toFixed(0)}%`}>
                <Tag
                  color={confidence >= 0.8 ? 'green' : confidence >= 0.6 ? 'orange' : 'red'}
                  style={{ fontSize: 11, padding: '0 6px', lineHeight: '20px', borderRadius: 10 }}
                >
                  {(confidence * 100).toFixed(0)}%
                </Tag>
              </Tooltip>
            )}
            {hasAnalysis && (
              <Tag
                color="geekblue"
                style={{ fontSize: 11, padding: '0 6px', lineHeight: '20px', cursor: 'pointer', borderRadius: 10 }}
                onClick={() => handleAIAnalyze(record)}
              >
                <BulbOutlined style={{ marginRight: 2 }} />已分析
              </Tag>
            )}
          </Space>
        )
      },
    },
    { title: '前置条件', key: 'prerequisites', dataIndex: 'prerequisites', width: 200,
      render: (text: string) => <Tooltip placement="topLeft" title={text}><span>{text || '-'}</span></Tooltip>,
    },
    {
      title: (
        <Space size={2} align="center">
          <span>测试步骤</span>
          <Tooltip title="查看测试步骤编写规则">
            <Button
              type="text"
              size="small"
              icon={<QuestionCircleOutlined />}
              onClick={(e) => {
                e.stopPropagation()
                setStepRulesOpen(true)
              }}
              style={{ padding: '0 2px', fontSize: 12, color: '#2f54eb' }}
            />
          </Tooltip>
        </Space>
      ),
      key: 'test_steps',
      dataIndex: 'test_steps',
      width: 300,
      render: (text: string, record: TestCase) => {
        const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
        const parsed = aiParsedSteps[caseKey]
        const isParsing = aiParsingCase === caseKey

        const confidenceColor = (c: number) => c >= 0.8 ? '#36b37e' : c >= 0.6 ? '#ff8b00' : '#de350b'

        const tooltipContent = (
          <div style={{ maxWidth: 450, maxHeight: 400, overflow: 'auto' }}>
            <div style={{ marginBottom: 8, whiteSpace: 'pre-wrap', fontSize: 12 }}>{text}</div>
            {parsed && parsed.length > 0 && (
              <>
                <div style={{ borderTop: '1px solid #444', paddingTop: 8, marginTop: 4 }}>
                  <strong>🤖 AI 解析命令：</strong>
                </div>
                {parsed.filter(s => s.kind !== 'skip').map((s, i) => (
                  <div key={i} style={{ fontSize: 12, margin: '4px 0', display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{
                      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
                      background: confidenceColor(s.confidence), flexShrink: 0,
                    }} />
                    <Tag color={s.kind === 'command' ? 'blue' : s.kind === 'nvsipl_input' ? 'purple' : 'default'}
                      style={{ fontSize: 11, lineHeight: '18px', margin: 0 }}>
                      {s.kind}
                    </Tag>
                    <code style={{ fontSize: 11, wordBreak: 'break-all' }}>{s.command}</code>
                  </div>
                ))}
              </>
            )}
          </div>
        )

        return (
          <Space size={4} align="start" className="case-cell-content">
            <Tooltip placement="topLeft" title={tooltipContent} overlayStyle={{ maxWidth: 500 }}>
              <span style={{ cursor: 'pointer' }}>{text}</span>
            </Tooltip>
            {parsed && parsed.filter(s => s.kind !== 'skip').length > 0 && (
              <Tag color="purple" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                <RobotOutlined /> {parsed.filter(s => s.kind !== 'skip').length}
              </Tag>
            )}
            {text && (
              <Tooltip title="查看将执行的命令">
                <Button
                  type="text"
                  size="small"
                  icon={<CodeOutlined />}
                  onClick={() => setPreviewCommandKeys([caseKey])}
                  style={{ fontSize: 12, padding: '0 2px', color: '#2f54eb' }}
                />
              </Tooltip>
            )}
            {!parsed && text && (
              <Tooltip title="AI 解析步骤">
                <Button
                  type="text"
                  size="small"
                  icon={isParsing ? <LoadingOutlined /> : <RobotOutlined />}
                  disabled={isParsing}
                  onClick={() => handleAIParseStep(record)}
                  style={{ fontSize: 12, padding: '0 2px' }}
                />
              </Tooltip>
            )}
          </Space>
        )
      },
    },
    { title: '预期结果', key: 'expected_result', dataIndex: 'expected_result', width: 200,
      render: (text: string) => <Tooltip placement="topLeft" title={text}><span>{text}</span></Tooltip>,
    },
    { title: '实际结果', key: 'actual_result', dataIndex: 'actual_result', width: 300,
      render: (_text: string, record: TestCase) => {
        // 实际结果栏展示表格备注列中的 AI 判定结果；格式不符合约定时原样展示备注
        const parsed = parseRemark(record.remarks)
        const resultText = parsed.valid ? parsed.aiText : (record.remarks || 'NT')
        const aiStatus = (parsed.aiStatus || '').toLowerCase()
        const color = !parsed.valid ? undefined :
                      aiStatus === 'pass' ? '#36b37e' :
                      aiStatus === 'fail' ? '#de350b' :
                      aiStatus.includes('review') ? '#2f54eb' : undefined
        const logText = parsed.valid ? parsed.logText : extractLogText(record.remarks)
        const hasLog = !!(logText || record.log_file)

        return (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 4 }}>
            <Tooltip
              placement="topLeft"
              overlayStyle={{ maxWidth: 600 }}
              title={
                parsed.valid || record.remarks ? (
                  <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxWidth: 560, fontSize: 12 }}>
                    {resultText}
                  </pre>
                ) : '暂无备注'
              }
            >
              <span style={{ color, whiteSpace: 'pre-wrap', flex: 1 }}>{resultText}</span>
            </Tooltip>
            <Tooltip title={hasLog ? '查看执行日志' : '暂无执行日志'}>
              <span style={{ display: 'inline-flex', flexShrink: 0 }}>
                <Button
                  type="text"
                  size="small"
                  icon={<FileTextOutlined />}
                  disabled={!hasLog}
                  onClick={() => setLogModalCase(record)}
                  style={{ padding: '0 2px', color: '#2f54eb' }}
                />
              </span>
            </Tooltip>
            {canShowCaseImages(record.expected_result, record.status) && (
              <Tooltip title="查看生成的 YUV 图（PNG）">
                <span style={{ display: 'inline-flex', flexShrink: 0 }}>
                  <Button
                    type="text"
                    size="small"
                    icon={<PictureOutlined />}
                    onClick={() => setImageModalCase(record)}
                    style={{ padding: '0 2px', color: '#2f54eb' }}
                  />
                </span>
              </Tooltip>
            )}
          </div>
        )
      },
    },
    {
      title: '操作', key: 'actions', width: 80, fixed: 'right' as const,
      render: (_: unknown, record: TestCase) => {
        const status = (record.status || '').toUpperCase()
        const canAnalyze = status === 'FAIL' || status === 'REVIEW'
        const caseKey = record.case_key || record.case_id
        const hasCache = !!aiAnalysisCache[caseKey]
        if (!canAnalyze) return null
        return (
          <Button
            type="link"
            size="small"
            icon={hasCache ? <BulbOutlined style={{ color: '#2f54eb' }} /> : <ExperimentOutlined />}
            onClick={() => handleAIAnalyze(record)}
          >
            {hasCache ? '查看' : 'AI分析'}
          </Button>
        )
      },
    },
  ]

  const optionalColumns = columns.filter(column => optionalCaseColumnKeys.includes(String(column.key)))
  const hasScrollableColumns = optionalColumns.some(column => !column.fixed && visibleColumnKeys.includes(String(column.key)))
  const visibleColumns = columns
    .filter(column => !optionalCaseColumnKeys.includes(String(column.key)) || visibleColumnKeys.includes(String(column.key)))
    .map(column => hasScrollableColumns ? column : { ...column, fixed: undefined })
  const visibleTableWidth = visibleColumns.reduce((total, column) => total + Number(column.width || 0), 0)

  // ===== 统计数据 =====
  const passCount = filteredCases.filter(c => c.status === 'Pass').length
  const failCount = filteredCases.filter(c => c.status === 'Fail').length
  const blockCount = filteredCases.filter(c => c.status === 'BLOCK').length
  const ntCount = filteredCases.filter(c => !c.status || c.status === 'NT').length
  const total = filteredCases.length
  const selectedCount = filteredCases.filter(c => c.selected).length
  const allSelectedCount = store.testCases.filter(c => c.selected).length
  // 通过率 = 通过数 / (通过 + 失败)，仅计算已判定的用例
  const judgedCount = passCount + failCount
  const rate = judgedCount > 0 ? Math.round((passCount / judgedCount) * 100) : 0
  // 是否有已执行的结果（非 NT 状态）
  const hasExecutedResults = filteredCases.some(c => c.status && c.status !== 'NT')
  // AI 已解析用例数
  const aiParsedCount = store.aiParsedCases.size

  return (
    <div>
      {/* ===== 工具栏 ===== */}
      <Card className="toolbar-card" style={{ marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
          <Space wrap size={8}>
            <Upload beforeUpload={handleUpload} showUploadList={false} accept=".xlsx,.xls">
              <Button icon={<UploadOutlined />} loading={loading}>上传用例</Button>
            </Upload>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStart}
              disabled={store.isRunning || selectedCount === 0}
            >
              开始执行
            </Button>
            <Button
              danger
              icon={<StopOutlined />}
              onClick={handleStop}
              disabled={!store.isRunning}
            >
              停止
            </Button>
            <Tooltip title="预览选中用例将要下发到板端的命令">
              <Button
                icon={<CodeOutlined />}
                onClick={() => setPreviewCommandKeys(
                  store.testCases.filter((c) => c.selected).map((c) => c.case_key || c.case_id)
                )}
                disabled={allSelectedCount === 0}
              >
                查看执行命令
              </Button>
            </Tooltip>
            <Tooltip title="下载结果 Excel，可选择备注列是否附带实际执行日志">
              <Dropdown
                disabled={!hasExecutedResults}
                trigger={['click']}
                menu={{
                  items: [
                    { key: 'with-log', label: '备注含执行日志' },
                    { key: 'without-log', label: '备注不含执行日志' },
                  ],
                  onClick: ({ key }) => void handleDownload(key === 'with-log'),
                }}
              >
                <Button icon={<DownloadOutlined />} disabled={!hasExecutedResults}>
                  下载结果 <DownOutlined />
                </Button>
              </Dropdown>
            </Tooltip>
          </Space>
          <Space wrap size={8}>
            <Tooltip title="AI 分析所有 Fail/Review 用例">
              <Button
                icon={aiBatchAnalyzing ? <LoadingOutlined /> : <ExperimentOutlined />}
                onClick={handleBatchAnalyze}
                loading={aiBatchAnalyzing}
                disabled={store.isRunning || !store.testCases.some(
                  (c: TestCase) => c.status?.toUpperCase() === 'FAIL' || c.status?.toUpperCase() === 'REVIEW'
                )}
              >
                AI 批量分析
              </Button>
            </Tooltip>
            <Button
              icon={<FileTextOutlined />}
              onClick={() => setAIReportOpen(true)}
              disabled={store.isRunning || store.testCases.length === 0}
            >
              AI 报告
            </Button>
          </Space>
        </div>
      </Card>

      {/* ===== AI 步骤解析进度 ===== */}
      {store.aiParseProgress && (
        <Card className="toolbar-card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <RobotOutlined style={{ fontSize: 18, color: store.aiParseProgress.status === 'done' ? '#36b37e' : '#722ed1' }} />
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <Text strong style={{ fontSize: 13 }}>
                  {store.aiParseProgress.status === 'parsing' ? 'AI 步骤解析中...' :
                   store.aiParseProgress.status === 'interrupted' ? 'AI 步骤解析已中断' :
                   'AI 步骤解析完成'}
                </Text>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {store.aiParseProgress.status === 'parsing'
                    ? `${store.aiParseProgress.current} / ${store.aiParseProgress.total}`
                    : `成功 ${store.aiParseProgress.success}，失败 ${store.aiParseProgress.failed}`
                  }
                </Text>
              </div>
              <Progress
                percent={store.aiParseProgress.total > 0
                  ? Math.round((store.aiParseProgress.current / store.aiParseProgress.total) * 100)
                  : 0}
                size="small"
                strokeColor={store.aiParseProgress.status === 'done' ? '#36b37e' :
                             store.aiParseProgress.status === 'interrupted' ? '#ff8b00' : '#722ed1'}
                showInfo={false}
              />
            </div>
            {store.aiParseProgress.status === 'parsing' && (
              <LoadingOutlined style={{ fontSize: 16, color: '#722ed1' }} />
            )}
            {store.aiParseProgress.status === 'done' && (
              <CheckOutlined style={{ fontSize: 16, color: '#36b37e' }} />
            )}
          </div>
        </Card>
      )}

      {/* ===== Sheet 页签 ===== */}
      {store.sheets.length > 0 && (
        <Card className="toolbar-card" style={{ marginBottom: 12 }}>
          <Space wrap>
            <Text strong>页签：</Text>
            <Radio.Group value={store.currentSheet} onChange={(e) => handleSheetChange(e.target.value)}>
              {store.sheets.map((sheet) => (
                <Radio.Button key={sheet} value={sheet}>{sheet}</Radio.Button>
              ))}
            </Radio.Group>
            <Text type="secondary">已选 {allSelectedCount} / {store.testCases.length}</Text>
          </Space>
        </Card>
      )}

      {/* ===== 进度条 ===== */}
      {store.progress && (
        <Card className="toolbar-card" style={{ marginBottom: 12 }}>
          <Progress
            percent={Math.round((store.progress!.current / store.progress!.total) * 100)}
            format={() => `${store.progress!.current}/${store.progress!.total}`}
            strokeColor="#2f54eb"
            status={store.progress!.message ? 'active' : 'normal'}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <Text style={{ flex: 1, minWidth: 0 }} ellipsis={{ tooltip: store.progress!.message }}>
              {store.progress!.message || '正在执行'}
            </Text>
            <Text type="secondary">当前用例: {store.progress!.case_id}</Text>
          </div>
        </Card>
      )}

      {/* ===== 人工确认 ===== */}
      {store.confirmRequest && (
        <Card style={{ marginBottom: 12, background: '#fefce8', border: '1px solid #fde68a' }}>
          <Alert
            message="需要人工确认"
            description={
              store.confirmRequest.step_desc.includes('\n') ? (
                <pre style={{
                  margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all',
                  maxHeight: 500, overflow: 'auto', fontSize: 12, lineHeight: 1.5,
                  background: '#fafafa', padding: 12, borderRadius: 4,
                }}>{store.confirmRequest.step_desc}</pre>
              ) : store.confirmRequest.step_desc
            }
            type="warning"
            showIcon
            action={
              <Space direction="vertical">
                <Button type="primary" icon={<CheckOutlined />} onClick={() => handleConfirm(true)}>确认 Pass</Button>
                <Button danger icon={<CloseOutlined />} onClick={() => handleConfirm(false)}>确认 Fail</Button>
              </Space>
            }
          />
        </Card>
      )}

      {/* ===== 统计卡片 ===== */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col flex="1"><Card className="stat-card"><Statistic title="总计" value={total} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="已选" value={selectedCount} valueStyle={{ color: '#2f54eb' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="通过" value={passCount} valueStyle={{ color: '#36b37e' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="失败" value={failCount} valueStyle={{ color: '#de350b' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="阻塞" value={blockCount} valueStyle={{ color: '#ff8b00' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="NT" value={ntCount} valueStyle={{ color: '#999' }} /></Card></Col>
        <Col flex="1"><Card className="stat-card"><Statistic title="通过率" value={rate} suffix="%" valueStyle={{ color: rate >= 80 ? '#36b37e' : rate >= 50 ? '#ff8b00' : '#de350b' }} /></Card></Col>
        {aiParsedCount > 0 && (
          <Col flex="1">
            <Card className="stat-card">
              <Statistic
                title={<><RobotOutlined style={{ marginRight: 4 }} />AI 已解析</>}
                value={aiParsedCount}
                valueStyle={{ color: '#722ed1' }}
              />
            </Card>
          </Col>
        )}
      </Row>

      {/* ===== 用例表格 ===== */}
      <Card
        title="测试用例"
        className="case-table"
        extra={
          <Popover
            trigger="click"
            placement="bottomRight"
            title="选择显示列"
            content={
              <Space direction="vertical" size={12}>
                <Checkbox
                  checked={visibleColumnKeys.length === optionalCaseColumnKeys.length}
                  indeterminate={visibleColumnKeys.length > 0 && visibleColumnKeys.length < optionalCaseColumnKeys.length}
                  onChange={(e) => setVisibleColumnKeys(e.target.checked ? [...optionalCaseColumnKeys] : [])}
                >
                  全选
                </Checkbox>
                <Checkbox.Group<string> value={visibleColumnKeys} onChange={setVisibleColumnKeys}>
                  <Space direction="vertical">
                    {optionalColumns.map(column => (
                      <Checkbox key={String(column.key)} value={String(column.key)}>
                        {typeof column.title === 'string'
                          ? column.title
                          : String(column.key) === 'test_steps' ? '测试步骤' : String(column.key)}
                      </Checkbox>
                    ))}
                  </Space>
                </Checkbox.Group>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  选择框、序号和操作列始终显示
                </Text>
              </Space>
            }
          >
            <Button size="small">显示列 <DownOutlined /></Button>
          </Popover>
        }
      >
        <Table
          columns={visibleColumns}
          dataSource={filteredCases}
          rowKey="case_key"
          scroll={hasScrollableColumns ? { x: visibleTableWidth } : undefined}
          size="small"
          pagination={{
            current: currentPage,
            pageSize,
            showTotal: (total) => `共 ${total} 条`,
            showSizeChanger: false,
            onChange: (p) => setCurrentPage(p),
          }}
        />
      </Card>

      {/* ===== 执行日志 ===== */}
      <Card
        title="执行日志"
        extra={<Button type="link" size="small" onClick={() => navigate('/logs')}>单独查看 →</Button>}
        style={{ marginTop: 12 }}
      >
        <div className="log-terminal">
          {store.logs.length === 0 && (
            <div style={{ color: '#6b7280', textAlign: 'center', padding: '20px 0' }}>暂无日志</div>
          )}
          {store.logs.map((log, i) => (
            <div
              key={i}
              className={log.level === 'error' ? 'log-error' : log.level === 'warning' ? 'log-warning' : 'log-info'}
            >
              [{new Date(log.timestamp).toLocaleTimeString()}] {log.message}
            </div>
          ))}
        </div>
      </Card>

      {/* ===== AI 分析抽屉 ===== */}
      <AIAnalysisDrawer
        open={aiDrawerOpen}
        onClose={() => { setAIDrawerOpen(false); setAIDrawerCase(null) }}
        testCase={aiDrawerCase}
        cachedAnalysis={
          aiDrawerCase
            ? aiAnalysisCache[aiDrawerCase.case_key || aiDrawerCase.case_id] || null
            : null
        }
        onAnalysisDone={handleAnalysisDone}
      />

      {/* ===== AI 报告弹窗 ===== */}
      <AIReportModal
        open={aiReportOpen}
        onClose={() => setAIReportOpen(false)}
        hasCases={store.testCases.length > 0}
      />

      {/* ===== 执行日志弹窗 ===== */}
      <CaseLogModal
        open={!!logModalCase}
        title={logModalCase ? `执行日志 - ${logModalCase.case_id}` : undefined}
        log={logModalCase ? extractLogText(logModalCase.remarks) : ''}
        status={logModalCase ? parseRemark(logModalCase.remarks).aiStatus : ''}
        evidence={
          logModalCase
            ? (logModalCase.ai_evidence?.length
                ? logModalCase.ai_evidence
                : extractAiEvidence(logModalCase.remarks))
            : []
        }
        path={logModalCase?.log_file}
        caseKey={logModalCase?.case_key}
        onClose={() => setLogModalCase(null)}
      />

      {/* ===== YUV 出图弹窗 ===== */}
      <CaseImagesModal
        open={!!imageModalCase}
        caseId={imageModalCase?.case_id || null}
        onClose={() => setImageModalCase(null)}
      />

      {/* ===== 即将执行命令预览弹窗 ===== */}
      <CommandPreviewModal
        open={previewCommandKeys !== null}
        caseKeys={previewCommandKeys || []}
        onClose={() => setPreviewCommandKeys(null)}
      />

      {/* ===== 测试步骤编写规则弹窗 ===== */}
      <TestStepRulesModal
        open={stepRulesOpen}
        onClose={() => setStepRulesOpen(false)}
      />
    </div>
  )
}
