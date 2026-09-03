import { useState, useEffect, useCallback } from 'react'
import { isAxiosError } from 'axios'
import {
  Card, Row, Col, Upload, Button, Table, Tag, Progress,
  Modal, Form, Input, InputNumber, Space, Collapse,
  Typography, message, Alert, Badge, Radio, Checkbox, Tooltip,
} from 'antd'
import {
  UploadOutlined, PlayCircleOutlined, StopOutlined,
  DownloadOutlined, SettingOutlined, CheckOutlined,
  CloseOutlined, SyncOutlined, CloudUploadOutlined,
  RobotOutlined, BulbOutlined, FileTextOutlined,
  ExperimentOutlined, LoadingOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../stores/useStore'
import { useWebSocket } from '../hooks/useWebSocket'
import AIConfigPanel from '../components/AIConfigPanel'
import AIAnalysisDrawer from '../components/AIAnalysisDrawer'
import AIReportModal from '../components/AIReportModal'
import api, {
  downloadResults,
  getCases,
  getSSHConfig,
  getSSHStatus,
  getWorkspace,
  pushFileToBoard,
  pushLocalToBoard,
  selectCases,
  setSSHConfig,
  setWorkspace,
  startExecution,
  testSSHConnection,
  uploadExcel,
  analyzeAllFailures,
} from '../api/axios'
import type { SSHConfig, SSHLoginMode, TestCase, WorkspaceConfig, AIAnalysis } from '../types'

const { Text } = Typography

export default function Dashboard() {
  const navigate = useNavigate()
  const store = useStore()
  const ws = useWebSocket()
  const [loading, setLoading] = useState(false)
  const [sshModalOpen, setSSHModalOpen] = useState(false)
  const [wsModalOpen, setWSModalOpen] = useState(false)
  const [pushModalOpen, setPushModalOpen] = useState(false)
  const [pushMode, setPushMode] = useState<'file' | 'local'>('local')
  const [pushFile, setPushFile] = useState<File | null>(null)
  const [pushLocalPath, setPushLocalPath] = useState('')
  const [pushRemotePath, setPushRemotePath] = useState('')
  const [pushSoPath, setPushSoPath] = useState('')
  const [pushBoardType, setPushBoardType] = useState<'linux' | 'qnx'>('linux')
  const [pushCopyEnabled, setPushCopyEnabled] = useState(false)
  const [pushing, setPushing] = useState(false)
  const [testingSSH, setTestingSSH] = useState(false)
  const [aiModalOpen, setAIModalOpen] = useState(false)
  // AI 分析相关状态
  const [aiDrawerOpen, setAIDrawerOpen] = useState(false)
  const [aiDrawerCase, setAIDrawerCase] = useState<TestCase | null>(null)
  const [aiAnalysisCache, setAIAnalysisCache] = useState<Record<string, AIAnalysis>>({})
  const [aiBatchAnalyzing, setAIBatchAnalyzing] = useState(false)
  const [aiReportOpen, setAIReportOpen] = useState(false)
  const [sshForm] = Form.useForm<SSHConfig>()
  const [wsForm] = Form.useForm<WorkspaceConfig>()
  const currentSSHMode = Form.useWatch('login_mode', sshForm) || store.sshConfig?.login_mode || 'direct'

  // AI 单用例分析（打开抽屉）
  const handleAIAnalyze = useCallback((record: TestCase) => {
    setAIDrawerCase(record)
    setAIDrawerOpen(true)
  }, [])

  // AI 分析结果缓存回调
  const handleAnalysisDone = useCallback((caseKey: string, analysis: AIAnalysis) => {
    setAIAnalysisCache(prev => ({ ...prev, [caseKey]: analysis }))
  }, [])

  // AI 批量分析所有失败用例
  const handleBatchAnalyze = useCallback(async () => {
    setAIBatchAnalyzing(true)
    try {
      const res = await analyzeAllFailures()
      const { analyses, total, analyzed } = res.data
      // 缓存所有结果
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
    if (isAxiosError<{ detail?: string }>(error)) {
      return error.response?.data?.detail || error.message || fallback
    }

    if (error instanceof Error) {
      return error.message
    }

    return fallback
  }

  const openSSHModal = () => {
    sshForm.setFieldsValue(store.sshConfig || {
      login_mode: 'direct',
      port: 22,
      timeout: 30,
      jump_port: 22,
    })
    setSSHModalOpen(true)
  }

  const openWorkspaceModal = () => {
    wsForm.setFieldsValue(store.workspace || {})
    setWSModalOpen(true)
  }

  useEffect(() => {
    loadConfigs()
  }, [])

  const loadConfigs = async () => {
    try {
      const [ssh, ws] = await Promise.all([getSSHConfig(), getWorkspace()])
      const sshStatus = await getSSHStatus()
      store.setSSHConfig(ssh.data)
      store.setSSHStatus(sshStatus.data)
      store.setWorkspace(ws.data)
    } catch (error) {
      message.warning(getErrorMessage(error, '加载配置失败'))
    }
  }

  const handleUpload = async (file: File) => {
    setLoading(true)
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
      const selectedKeys = store.testCases
        .filter((c) => c.selected)
        .map((c) => c.case_key)

      await startExecution(selectedKeys)
      store.setIsRunning(true)
      store.clearLogs()
      store.resetSelectedCases()  // 重置选中用例的状态，清除旧结果
      message.success(`执行已启动，已选择 ${selectedKeys.length} 条用例`)
    } catch (error) {
      message.error(getErrorMessage(error, '启动失败'))
    }
  }

  const handleStop = () => {
    ws.stopExecution()
  }

  const handleSSHSave = async () => {
    const values = await sshForm.validateFields()
    await setSSHConfig(values)
    store.setSSHConfig(values)
    store.setSSHStatus({
      connected: false,
      tested: false,
      mode: values.login_mode,
      message: 'SSH 配置已更新，请点击“测试连接”确认',
    })
    setSSHModalOpen(false)
    message.success('SSH 配置已保存')
  }

  const handleSSHTest = async () => {
    try {
      const values = await sshForm.validateFields()
      setTestingSSH(true)
      const res = await testSSHConnection(values)
      store.setSSHConfig(values)
      store.setSSHStatus(res.data)
      message.success(res.data.message)
    } catch (error) {
      store.setSSHStatus({
        connected: false,
        tested: true,
        mode: sshForm.getFieldValue('login_mode') || 'direct',
        message: getErrorMessage(error, 'SSH 连接测试失败'),
      })
      message.error(getErrorMessage(error, 'SSH 连接测试失败'))
    } finally {
      setTestingSSH(false)
    }
  }

  const handleWSSave = async () => {
    const values = await wsForm.validateFields()
    await setWorkspace(values)
    store.setWorkspace(values)
    setWSModalOpen(false)
    message.success('工作区配置已保存')
  }

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

  const handlePushFile = async () => {
    if (!pushRemotePath) {
      message.warning('请填写板端目标路径')
      return
    }
    if (pushMode === 'file' && !pushFile) {
      message.warning('请选择要上传的文件')
      return
    }
    if (pushMode === 'local' && !pushLocalPath) {
      message.warning('请填写 PC 本地路径')
      return
    }
    if (pushCopyEnabled && !pushSoPath) {
      message.warning('请填写运行 so 路径')
      return
    }
    setPushing(true)
    try {
      if (pushMode === 'file' && pushFile) {
        const res = await pushFileToBoard(pushFile, pushRemotePath)
        message.success(res.data.message)
      } else {
        const res = await pushLocalToBoard(pushLocalPath, pushRemotePath)
        message.success(res.data.message)
      }
      // 如果启用了 so 复制，执行板端 cp 命令
      if (pushCopyEnabled && pushSoPath) {
        const copyRes = await api.post<{ message: string }>('/files/copy-to-so', {
          source_path: pushRemotePath,
          so_path: pushSoPath,
          board_type: pushBoardType,
        })
        message.success(copyRes.data.message)
      }
      setPushModalOpen(false)
      setPushFile(null)
      setPushLocalPath('')
      setPushRemotePath('')
    } catch (error) {
      message.error(getErrorMessage(error, '文件推送失败'))
    } finally {
      setPushing(false)
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
    // 只选/取消当前页签的用例
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
  }

  // 按当前页签过滤显示的用例
  const filteredCases = store.currentSheet
    ? store.testCases.filter((c) => c.source_sheet === store.currentSheet)
    : store.testCases

  const columns: ColumnsType<TestCase> = [
    {
      title: (
        <Checkbox
          checked={filteredCases.length > 0 && filteredCases.every((c) => c.selected)}
          indeterminate={filteredCases.some((c) => c.selected) && !filteredCases.every((c) => c.selected)}
          onChange={(e) => handleSelectAll(e.target.checked)}
        >
          选择
        </Checkbox>
      ),
      dataIndex: 'selected',
      width: 90,
      fixed: 'left',
      render: (_: boolean, record) => (
        <Checkbox
          checked={record.selected}
          onChange={(e) => handleCaseSelectedChange(record, e.target.checked)}
        />
      ),
    },
    { title: '用例编号', dataIndex: 'case_id', width: 120, fixed: 'left' },
    { title: '用例描述', dataIndex: 'description', width: 200, ellipsis: true },
    { title: '测试类型', dataIndex: 'test_type', width: 100 },
    { title: '优先级', dataIndex: 'priority', width: 80 },
    {
      title: '状态', dataIndex: 'status', width: 110,
      render: (s: string, record: TestCase) => {
        const colors: Record<string, string> = { Pass: 'green', Fail: 'red', NT: 'default', BLOCK: 'orange', NA: 'default', Running: 'processing', Review: 'blue' }
        const labels: Record<string, string> = { Review: '待确认' }
        // 检查实际结果中是否包含 AI 判定标记
        const isAIJudged = record.actual_result?.includes('[AI判定]')
        // 提取规则置信度（格式: [规则置信度=0.95]）
        const confMatch = record.actual_result?.match(/\[规则置信度=([\d.]+)\]/)
        const confidence = confMatch ? parseFloat(confMatch[1]) : null
        // 检查是否有 AI 分析缓存
        const caseKey = record.case_key || record.case_id
        const hasAnalysis = !!aiAnalysisCache[caseKey]
        return (
          <Space direction="vertical" size={0}>
            <Tag color={colors[s] || 'default'}>{labels[s] || s}</Tag>
            {isAIJudged && (
              <Tag color="purple" style={{ fontSize: 10, padding: '0 4px', lineHeight: '18px' }}>
                <RobotOutlined style={{ marginRight: 2 }} />AI
              </Tag>
            )}
            {confidence !== null && !isAIJudged && (
              <Tooltip title={`规则引擎置信度: ${(confidence * 100).toFixed(0)}%`}>
                <Tag
                  color={confidence >= 0.8 ? 'green' : confidence >= 0.6 ? 'orange' : 'red'}
                  style={{ fontSize: 10, padding: '0 4px', lineHeight: '18px' }}
                >
                  {(confidence * 100).toFixed(0)}%
                </Tag>
              </Tooltip>
            )}
            {hasAnalysis && (
              <Tag
                color="geekblue"
                style={{ fontSize: 10, padding: '0 4px', lineHeight: '18px', cursor: 'pointer' }}
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
      render: (text: string) => <Tooltip placement="topLeft" title={text}><span>{text}</span></Tooltip>,
    },
    { title: '预期结果', dataIndex: 'expected_result', width: 200, ellipsis: { showTitle: false },
      render: (text: string) => <Tooltip placement="topLeft" title={text}><span>{text}</span></Tooltip>,
    },
    { title: '实际结果', dataIndex: 'actual_result', width: 300, ellipsis: { showTitle: false },
      render: (text: string, record: TestCase) => {
        const color = record.status === 'Pass' ? '#52c41a' :
                      record.status === 'Fail' ? '#ff4d4f' :
                      record.status === 'Review' ? '#1677ff' : undefined
        // 对含 [WARN] 的文本做高亮渲染
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
            icon={hasCache ? <BulbOutlined style={{ color: '#722ed1' }} /> : <ExperimentOutlined />}
            onClick={() => handleAIAnalyze(record)}
          >
            {hasCache ? '查看' : 'AI分析'}
          </Button>
        )
      },
    },
  ]

  const passCount = filteredCases.filter(c => c.status === 'Pass').length
  const failCount = filteredCases.filter(c => c.status === 'Fail').length
  const total = filteredCases.length
  const selectedCount = filteredCases.filter(c => c.selected).length
  const rate = total > 0 ? Math.round((passCount / total) * 100) : 0
  const sshModeText: Record<SSHLoginMode, string> = {
    direct: '直连板端',
    jump: '通过跳板机',
  }
  const sshStatusColor = store.sshStatus?.connected
    ? 'success'
    : store.sshStatus?.tested
      ? 'error'
      : 'default'
  const sshStatusText = store.sshStatus
    ? `${sshModeText[store.sshStatus.mode]}｜${store.sshStatus.message}`
    : 'SSH 未配置'
  const sshModalStatusType =
    store.sshStatus?.mode === currentSSHMode
      ? (store.sshStatus.connected ? 'success' : store.sshStatus.tested ? 'error' : 'info')
      : 'info'
  const sshModalStatusText =
    store.sshStatus?.mode === currentSSHMode
      ? sshStatusText
      : `${sshModeText[currentSSHMode]}｜当前配置已修改，请点击“测试连接”确认`

  return (
    <div>
      {/* 工具栏 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Upload beforeUpload={handleUpload} showUploadList={false} accept=".xlsx,.xls">
              <Button icon={<UploadOutlined />} loading={loading}>上传用例</Button>
            </Upload>
          </Col>
          <Col>
            <Button
              type="primary"
              icon={<PlayCircleOutlined />}
              onClick={handleStart}
              disabled={store.isRunning || selectedCount === 0}
            >
              开始执行
            </Button>
          </Col>
          <Col>
            <Button
              danger
              icon={<StopOutlined />}
              onClick={handleStop}
              disabled={!store.isRunning}
            >
              停止执行
            </Button>
          </Col>
          <Col>
            <Button icon={<DownloadOutlined />} onClick={handleDownload}>下载结果</Button>
          </Col>
          <Col>
            <Button icon={<SettingOutlined />} onClick={openSSHModal}>
              SSH 配置
            </Button>
          </Col>
          <Col>
            <Button icon={<SettingOutlined />} onClick={openWorkspaceModal}>
              工作区配置
            </Button>
          </Col>
          <Col>
            <Button icon={<CloudUploadOutlined />} onClick={() => setPushModalOpen(true)}>
              推送文件到板端
            </Button>
          </Col>
          <Col>
            <Button icon={<RobotOutlined />} onClick={() => setAIModalOpen(true)}>
              AI 配置
            </Button>
          </Col>
          <Col>
            <Tooltip title="AI 分析所有 Fail/Review 用例的失败根因">
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
          </Col>
          <Col>
            <Button
              icon={<FileTextOutlined />}
              onClick={() => setAIReportOpen(true)}
              disabled={store.isRunning || store.testCases.length === 0}
            >
              AI 报告
            </Button>
          </Col>
          <Col>
            <Button onClick={() => navigate('/logs')}>日志大屏</Button>
          </Col>
          <Col flex="auto" style={{ textAlign: 'right' }}>
            <Space size="large">
              <Badge status={sshStatusColor} text={sshStatusText} />
              <Badge status={store.isConnected ? 'success' : 'error'} text={store.isConnected ? 'WebSocket 已连接' : 'WebSocket 未连接'} />
            </Space>
          </Col>
        </Row>
      </Card>

      {store.sheets.length > 0 && (
        <Card style={{ marginBottom: 16 }}>
          <Space wrap>
            <Text strong>用例页签：</Text>
            <Radio.Group value={store.currentSheet} onChange={(e) => handleSheetChange(e.target.value)}>
              {store.sheets.map((sheet) => (
                <Radio.Button key={sheet} value={sheet}>{sheet}</Radio.Button>
              ))}
            </Radio.Group>
            <Button onClick={() => handleSelectAll(true)}>全选当前页</Button>
            <Button onClick={() => handleSelectAll(false)}>清空当前页</Button>
            <Text type="secondary">已选 {selectedCount} / {total}</Text>
          </Space>
        </Card>
      )}

      {/* 进度条 */}
      {store.progress && (
        <Card style={{ marginBottom: 16 }}>
          <Progress
            percent={Math.round((store.progress!.current / store.progress!.total) * 100)}
            format={() => `${store.progress!.current}/${store.progress!.total}`}
          />
          <Text type="secondary">当前: {store.progress!.case_id}</Text>
        </Card>
      )}

      {/* 人工确认 */}
      {store.confirmRequest && (
        <Card style={{ marginBottom: 16, background: '#fff7e6' }}>
          <Alert
            message="需要人工确认"
            description={
              store.confirmRequest.step_desc.includes('\n') ? (
                <pre style={{
                  margin: 0,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-all',
                  maxHeight: 500,
                  overflow: 'auto',
                  fontSize: 12,
                  lineHeight: 1.5,
                  background: '#fafafa',
                  padding: 12,
                  borderRadius: 4,
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

      {/* 统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}><Card><Text>总计: {total}</Text></Card></Col>
        <Col span={6}><Card><Text style={{ color: '#1677ff' }}>已选: {selectedCount}</Text></Card></Col>
        <Col span={6}><Card><Text style={{ color: 'green' }}>通过: {passCount}</Text></Card></Col>
        <Col span={6}><Card><Text style={{ color: 'red' }}>失败: {failCount}</Text></Card></Col>
        <Col span={6}><Card><Text>通过率: {rate}%</Text></Card></Col>
      </Row>

      {/* 用例表格 */}
      <Card title="测试用例">
        <Table
          columns={columns}
          dataSource={filteredCases}
          rowKey="case_key"
          scroll={{ x: 1200 }}
          size="small"
          pagination={{ pageSize: 20 }}
        />
      </Card>

      {/* 日志 */}
      <Card
        title="执行日志"
        extra={<Button type="link" onClick={() => navigate('/logs')}>单独查看</Button>}
        style={{ marginTop: 16 }}
      >
        <div style={{ maxHeight: 300, overflow: 'auto', background: '#1e1e1e', color: '#d4d4d4', padding: 12, borderRadius: 4, fontFamily: 'monospace', fontSize: 12 }}>
          {store.logs.map((log, i) => (
            <div key={i} style={{ color: log.level === 'error' ? '#f44747' : log.level === 'warning' ? '#cca700' : '#d4d4d4' }}>
              [{new Date(log.timestamp).toLocaleTimeString()}] {log.message}
            </div>
          ))}
        </div>
      </Card>

      {/* SSH 配置弹窗 */}
      <Modal
        title="SSH 配置"
        open={sshModalOpen}
        onOk={handleSSHSave}
        onCancel={() => setSSHModalOpen(false)}
        footer={(_, { OkBtn, CancelBtn }) => (
          <Space>
            <Button icon={<SyncOutlined />} loading={testingSSH} onClick={handleSSHTest}>测试连接</Button>
            <CancelBtn />
            <OkBtn />
          </Space>
        )}
      >
        <Form form={sshForm} layout="vertical">
          <Form.Item name="login_mode" label="登录方式" initialValue="direct">
            <Radio.Group>
              <Radio value="direct">直接登录板端</Radio>
              <Radio value="jump">通过跳板机登录板端</Radio>
            </Radio.Group>
          </Form.Item>
          <Form.Item noStyle shouldUpdate>
            {({ getFieldValue }) => {
              const loginMode = getFieldValue('login_mode') as SSHLoginMode
              return (
                <>
                  {loginMode === 'jump' && (
                    <Alert
                      style={{ marginBottom: 16 }}
                      type="info"
                      showIcon
                      message="当前为跳板机模式"
                      description="系统将先登录跳板机，再通过跳板机连接目标板端。"
                    />
                  )}
                  <Form.Item name="host" label="目标板端主机" rules={[{ required: true }]}><Input placeholder="例如：192.168.1.10" /></Form.Item>
                  <Form.Item name="port" label="目标板端端口" initialValue={22}><InputNumber min={1} max={65535} style={{ width: '100%' }} /></Form.Item>
                  <Form.Item name="username" label="目标板端用户名" rules={[{ required: true }]}><Input /></Form.Item>
                  <Form.Item name="password" label="目标板端密码"><Input.Password /></Form.Item>
                  <Form.Item name="target_password" label="板端 sudo/二次认证密码"><Input.Password /></Form.Item>
                  {loginMode === 'jump' && (
                    <>
                      <Form.Item name="jump_host" label="跳板机主机" rules={[{ required: true, message: '请输入跳板机主机' }]}><Input /></Form.Item>
                      <Form.Item name="jump_port" label="跳板机端口" initialValue={22}><InputNumber min={1} max={65535} style={{ width: '100%' }} /></Form.Item>
                      <Form.Item name="jump_username" label="跳板机用户名" rules={[{ required: true, message: '请输入跳板机用户名' }]}><Input /></Form.Item>
                      <Form.Item name="jump_password" label="跳板机密码"><Input.Password /></Form.Item>
                    </>
                  )}
                </>
              )
            }}
          </Form.Item>
          <Form.Item name="timeout" label="超时(秒)" initialValue={30}><InputNumber min={1} max={300} style={{ width: '100%' }} /></Form.Item>
        </Form>
        <Alert
          style={{ marginTop: 8 }}
          type={sshModalStatusType}
          showIcon
          message="SSH 登录状态"
          description={sshModalStatusText}
        />
      </Modal>

      {/* 工作区配置弹窗 */}
      <Modal title="工作区配置" open={wsModalOpen} onOk={handleWSSave} onCancel={() => setWSModalOpen(false)} width={520}>
        <Form form={wsForm} layout="vertical" size="small">
          <Row gutter={16}>
            <Col span={12}><Form.Item name="tester_name" label="测试人员"><Input /></Form.Item></Col>
            <Col span={12}><Form.Item name="test_version" label="测试版本"><Input /></Form.Item></Col>
          </Row>
          <Form.Item name="default_remote_path" label="远程工作路径" style={{ marginBottom: 12 }}>
            <Input placeholder="板端测试命令的工作目录" />
          </Form.Item>
          <Form.Item name="run_prerequisites" valuePropName="checked" style={{ marginBottom: 8 }}>
            <Checkbox>执行前置条件</Checkbox>
          </Form.Item>

          <Collapse size="small" style={{ marginTop: 8 }} items={[
            {
              key: 'paths',
              label: '路径覆盖配置',
              children: (
                <>
                  <Form.Item name="nito_override_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                    <Checkbox>启用 Nito 路径覆盖</Checkbox>
                  </Form.Item>
                  <Form.Item noStyle shouldUpdate={(prev, cur) => prev.nito_override_enabled !== cur.nito_override_enabled}>
                    {({ getFieldValue }) => getFieldValue('nito_override_enabled') ? (
                      <Form.Item name="nito_override_path" style={{ marginBottom: 8 }}>
                        <Input placeholder="板端 nito 路径，如 /app/basetech/nito" />
                      </Form.Item>
                    ) : null}
                  </Form.Item>
                  <Form.Item name="image_storage_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                    <Checkbox>启用 Image 存储路径（-f 参数替换）</Checkbox>
                  </Form.Item>
                  <Form.Item noStyle shouldUpdate={(prev, cur) => prev.image_storage_enabled !== cur.image_storage_enabled}>
                    {({ getFieldValue }) => getFieldValue('image_storage_enabled') ? (
                      <Form.Item name="image_storage_path" style={{ marginBottom: 8 }}>
                        <Input placeholder="板端图像存储目录，如 /storage/zja/picture/" />
                      </Form.Item>
                    ) : null}
                  </Form.Item>
                  <Form.Item name="cam_rotate_cfg_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                    <Checkbox>启用 Camera 翻转配置（CAM_ROTATE_CFG_PATH 环境变量覆盖）</Checkbox>
                  </Form.Item>
                  <Form.Item noStyle shouldUpdate={(prev, cur) => prev.cam_rotate_cfg_enabled !== cur.cam_rotate_cfg_enabled}>
                    {({ getFieldValue }) => getFieldValue('cam_rotate_cfg_enabled') ? (
                      <Form.Item name="cam_rotate_cfg_path" style={{ marginBottom: 8 }}>
                        <Input placeholder="板端翻转配置文件路径，如 /storage/test/config.json" />
                      </Form.Item>
                    ) : null}
                  </Form.Item>
                </>
              ),
            },
            {
              key: 'download',
              label: '拍图下载配置',
              children: (
                <>
                  <Form.Item name="image_download_enabled" valuePropName="checked" style={{ marginBottom: 4 }}>
                    <Checkbox>执行后下载图片到 PC（并清理板端）</Checkbox>
                  </Form.Item>
                  <Form.Item noStyle shouldUpdate={(prev, cur) => prev.image_download_enabled !== cur.image_download_enabled}>
                    {({ getFieldValue }) => getFieldValue('image_download_enabled') ? (
                      <Form.Item name="image_download_path" style={{ marginBottom: 8 }}>
                        <Input placeholder="PC 本地保存路径，如 /media/tstj/2t/test_images/" />
                      </Form.Item>
                    ) : null}
                  </Form.Item>
                </>
              ),
            },
          ]} />
        </Form>
      </Modal>

      {/* 文件推送弹窗 */}
      <Modal
        title="推送文件/目录到板端"
        open={pushModalOpen}
        onOk={handlePushFile}
        onCancel={() => { setPushModalOpen(false); setPushFile(null); setPushLocalPath(''); setPushRemotePath('') }}
        confirmLoading={pushing}
        okText="推送"
        width={560}
      >

        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <div>
            <Text strong>推送方式：</Text>
            <Radio.Group value={pushMode} onChange={(e) => setPushMode(e.target.value)} style={{ marginLeft: 8 }}>
              <Radio value="local">PC 本地路径（支持目录）</Radio>
              <Radio value="file">浏览器选择文件</Radio>
            </Radio.Group>
          </div>

          {pushMode === 'local' ? (
            <div>
              <Text strong>PC 本地路径（文件或目录）：</Text>
              <Input
                placeholder="如 /media/tstj/2t/so_files/ 或 /home/user/test.so"
                value={pushLocalPath}
                onChange={(e) => setPushLocalPath(e.target.value)}
                style={{ marginTop: 4 }}
              />
              <Text type="secondary" style={{ fontSize: 12 }}>
                填写 PC 上的绝对路径，支持文件或整个目录（目录会递归推送）
              </Text>
            </div>
          ) : (
            <div>
              <Text strong>选择本地文件：</Text>
              <Upload
                beforeUpload={(file) => { setPushFile(file); return false }}
                maxCount={1}
                onRemove={() => setPushFile(null)}
                fileList={pushFile ? [{ uid: '-1', name: pushFile.name, status: 'done' }] : []}
              >
                <Button icon={<UploadOutlined />}>选择文件</Button>
              </Upload>
            </div>
          )}

          <div>
            <Text strong>板端目标路径（中转目录）：</Text>
            <Input
              placeholder="如 /home/nvidia/tmp_so/ 或 /storage/zja/drv/"
              value={pushRemotePath}
              onChange={(e) => setPushRemotePath(e.target.value)}
              style={{ marginTop: 4 }}
            />
            <Text type="secondary" style={{ fontSize: 12 }}>
              文件先推送到此路径，再根据需要复制到运行目录
            </Text>
          </div>

          <div>
            <Checkbox checked={pushCopyEnabled} onChange={(e) => setPushCopyEnabled(e.target.checked)}>
              <Text strong>推送后复制到运行 so 路径</Text>
            </Checkbox>
          </div>

          {pushCopyEnabled && (
            <>
              <div>
                <Text strong>板端系统类型：</Text>
                <Radio.Group value={pushBoardType} onChange={(e) => setPushBoardType(e.target.value)} style={{ marginLeft: 8 }}>
                  <Radio value="linux">Linux（sudo cp）</Radio>
                  <Radio value="qnx">QNX（cp）</Radio>
                </Radio.Group>
              </div>
              <div>
                <Text strong>运行 so 路径（板端最终使用路径）：</Text>
                <Input
                  placeholder={pushBoardType === 'linux' ? '如 /usr/lib/nvsipl_drv/' : '如 /lib/firmware/'}
                  value={pushSoPath}
                  onChange={(e) => setPushSoPath(e.target.value)}
                  style={{ marginTop: 4 }}
                />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {pushBoardType === 'linux'
                    ? '执行: sudo cp <目标路径>/* <运行so路径>/'
                    : '执行: cp <目标路径>/* <运行so路径>/'}
                </Text>
              </div>
            </>
          )}
        </Space>
      </Modal>

      {/* AI 配置弹窗 */}
      <Modal
        title={null}
        open={aiModalOpen}
        onCancel={() => setAIModalOpen(false)}
        footer={null}
        width={640}
        destroyOnClose
      >
        <AIConfigPanel />
      </Modal>

      {/* AI 失败分析抽屉 */}
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

      {/* AI 报告生成弹窗 */}
      <AIReportModal
        open={aiReportOpen}
        onClose={() => setAIReportOpen(false)}
        hasCases={store.testCases.length > 0}
      />
    </div>
  )
}