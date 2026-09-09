import { useState, useEffect, useCallback } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Row, Col, Upload, Button, Table, Tag, Progress, Statistic,
  Space, Typography, message, Alert, Radio, Checkbox, Tooltip, Dropdown,
} from 'antd'
import {
  UploadOutlined, PlayCircleOutlined, StopOutlined,
  DownloadOutlined, CheckOutlined, CloseOutlined,
  RobotOutlined, BulbOutlined, FileTextOutlined,
  ExperimentOutlined, LoadingOutlined, DownOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../stores/useStore'
import { useWebSocket } from '../hooks/useWebSocket'
import AIAnalysisDrawer from '../components/AIAnalysisDrawer'
import AIReportModal from '../components/AIReportModal'
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
} from '../api/axios'
import type { TestCase, AIAnalysis, AIParsedStep } from '../types'

const { Text } = Typography

export default function Dashboard() {
  const navigate = useNavigate()
  const store = useStore()
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
      store.setWorkspace(workspace.data)
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

  const handleDownload = async () => {
    try {
      const res = await downloadResults()
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'test_results.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (error) {
      message.error(getErrorMessage(error, '下载失败'))
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
              { type: 'divider' as const },
              { key: 'deselectPage', label: '取消本页' },
              { key: 'deselectAll', label: '取消全部' },
            ],
            onClick: ({ key }) => {
              if (key === 'selectPage') void handleSelectPage(true)
              else if (key === 'selectAll') void handleSelectAll(true)
              else if (key === 'deselectPage') void handleSelectPage(false)
              else if (key === 'deselectAll') void handleSelectAll(false)
            },
          }} trigger={['click']}>
            <DownOutlined style={{ fontSize: 10, cursor: 'pointer', marginLeft: 2, color: '#999' }} />
          </Dropdown>
        </Space>
      ),
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
      width: 50,
      fixed: 'left',
      render: (_: unknown, __: TestCase, index: number) => (
        <span style={{ color: '#9ca3af' }}>{index + 1}</span>
      ),
    },
    { title: '用例编号', dataIndex: 'case_id', width: 130, fixed: 'left',
      render: (text: string, record: TestCase) => {
        const caseKey = record.case_key || `${record.source_sheet}:${record.row_number}:${record.case_id}`
        const isParsed = store.aiParsedCases.has(caseKey) || !!aiParsedSteps[caseKey]
        return (
          <Space size={4}>
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
    { title: '用例描述', dataIndex: 'description', width: 200, ellipsis: true },
    { title: '测试类型', dataIndex: 'test_type', width: 100 },
    { title: '优先级', dataIndex: 'priority', width: 80 },
    {
      title: '状态', dataIndex: 'status', width: 120,
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
    { title: '前置条件', dataIndex: 'prerequisites', width: 200, ellipsis: { showTitle: false },
      render: (text: string) => <Tooltip placement="topLeft" title={text}><span>{text || '-'}</span></Tooltip>,
    },
    { title: '测试步骤', dataIndex: 'test_steps', width: 300, ellipsis: { showTitle: false },
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
          <Space size={4}>
            <Tooltip placement="topLeft" title={tooltipContent} overlayStyle={{ maxWidth: 500 }}>
              <span style={{ cursor: 'pointer' }}>{text}</span>
            </Tooltip>
            {parsed && parsed.filter(s => s.kind !== 'skip').length > 0 && (
              <Tag color="purple" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                <RobotOutlined /> {parsed.filter(s => s.kind !== 'skip').length}
              </Tag>
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
    { title: '预期结果', dataIndex: 'expected_result', width: 200, ellipsis: { showTitle: false },
      render: (text: string) => <Tooltip placement="topLeft" title={text}><span>{text}</span></Tooltip>,
    },
    { title: '实际结果', dataIndex: 'actual_result', width: 300, ellipsis: { showTitle: false },
      render: (text: string, record: TestCase) => {
        const color = record.status === 'Pass' ? '#36b37e' :
                      record.status === 'Fail' ? '#de350b' :
                      record.status === 'Review' ? '#2f54eb' : undefined
        const renderText = (content: string) => {
          if (!content) return <span>-</span>
          if (!content.includes('[WARN]')) return <span>{content}</span>
          const parts = content.split(/(\[WARN\][^\n;]*)/g)
          return <>{parts.map((part, idx) =>
            part.startsWith('[WARN]')
              ? <span key={idx} style={{ color: '#fa8c16', fontWeight: 500 }}>{part}</span>
              : <span key={idx}>{part}</span>
          )}</>
        }
        return (
          <Tooltip
            placement="topLeft"
            overlayStyle={{ maxWidth: 600 }}
            title={
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxWidth: 560, fontSize: 12 }}>
                {text && text.includes('[WARN]')
                  ? text.split(/(\[WARN\][^\n;]*)/g).map((part, idx) =>
                      part.startsWith('[WARN]')
                        ? <span key={idx} style={{ color: '#fa8c16', fontWeight: 600 }}>{part}</span>
                        : <span key={idx}>{part}</span>
                    )
                  : text
                }
              </pre>
            }
          >
            <span style={{ color, whiteSpace: 'pre-wrap', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{renderText(text)}</span>
          </Tooltip>
        )
      },
    },
    {
      title: '操作', width: 80, fixed: 'right' as const,
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
            <Button
              icon={<DownloadOutlined />}
              onClick={handleDownload}
              disabled={!hasExecutedResults}
            >
              下载结果
            </Button>
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
          />
          <Text type="secondary">当前: {store.progress!.case_id}</Text>
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
      >
        <Table
          columns={columns}
          dataSource={filteredCases}
          rowKey="case_key"
          scroll={{ x: 1400 }}
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
    </div>
  )
}
