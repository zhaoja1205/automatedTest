import { useState, useCallback, useEffect } from 'react'
import {
  Card,
  Table,
  Button,
  Tag,
  Space,
  Typography,
  Popconfirm,
  message,
  Empty,
  Modal,
  Select,
  Spin,
  Radio,
} from 'antd'
import {
  FileTextOutlined,
  EyeOutlined,
  DeleteOutlined,
  DownloadOutlined,
  PlusOutlined,
  ReloadOutlined,
  BarChartOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import {
  listReports,
  deleteReport,
  listRuns,
  generateRunReport,
} from '../api/historyApi'
import { TestReport, TestRun } from '../types/history'

const { Title } = Typography

export default function ReportsPage() {
  const navigate = useNavigate()

  const [reports, setReports] = useState<TestReport[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)

  // Generate modal state
  const [modalOpen, setModalOpen] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [runs, setRuns] = useState<TestRun[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [reportType, setReportType] = useState<'summary' | 'ai'>('summary')

  const loadReports = useCallback(async (p: number) => {
    setLoading(true)
    try {
      const res = await listReports(20, (p - 1) * 20)
      setReports(res.data.reports)
      setTotal(res.data.total)
    } catch {
      message.error('加载报告列表失败')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadRuns = useCallback(async () => {
    setRunsLoading(true)
    try {
      const res = await listRuns(100, 0)
      setRuns(res.data.runs)
    } catch {
      message.error('加载执行记录失败')
    } finally {
      setRunsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadReports(page)
  }, [page, loadReports])

  useEffect(() => {
    if (modalOpen) {
      loadRuns()
      setSelectedRunId('')
      setReportType('summary')
    }
  }, [modalOpen, loadRuns])

  const handleDelete = async (reportId: string) => {
    try {
      await deleteReport(reportId)
      message.success('已删除')
      loadReports(page)
    } catch {
      message.error('删除失败')
    }
  }

  const handleExport = async (reportId: string, format: 'xlsx' | 'html') => {
    try {
      const { exportReport } = await import('../api/historyApi')
      const res = await exportReport(reportId, format)
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `report.${format}`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      message.error('导出失败')
    }
  }

  const handleGenerate = async () => {
    if (!selectedRunId) {
      message.warning('请选择执行记录')
      return
    }
    setGenerating(true)
    try {
      await generateRunReport(selectedRunId, reportType)
      message.success('报告生成成功')
      setModalOpen(false)
      loadReports(1)
      setPage(1)
    } catch {
      message.error('生成报告失败')
    } finally {
      setGenerating(false)
    }
  }

  const columns = [
    {
      title: '报告标题',
      dataIndex: 'title',
      width: 250,
      render: (text: string) => (
        <Space>
          <FileTextOutlined />
          <span>{text}</span>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'report_type',
      width: 100,
      render: (t: string) =>
        t === 'ai' ? (
          <Tag color="purple">AI 报告</Tag>
        ) : (
          <Tag color="#2f54eb">摘要报告</Tag>
        ),
    },
    {
      title: '通过率',
      dataIndex: 'pass_rate',
      width: 80,
      render: (v: number) => {
        const color = v >= 90 ? 'success' : v >= 70 ? 'warning' : 'error'
        return <Tag color={color}>{v.toFixed(1)}%</Tag>
      },
    },
    {
      title: '测试人',
      dataIndex: 'tester_name',
      width: 90,
    },
    {
      title: '版本',
      dataIndex: 'test_version',
      width: 100,
    },
    {
      title: '生成时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t: string) =>
        t ? new Date(t).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_: unknown, record: TestReport) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/records/reports/${record.report_id}`)}
          >
            查看
          </Button>
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handleExport(record.report_id, 'xlsx')}
          >
            Excel
          </Button>
          <Button
            type="text"
            size="small"
            icon={<DownloadOutlined />}
            onClick={() => handleExport(record.report_id, 'html')}
          >
            HTML
          </Button>
          <Popconfirm
            title="确认删除"
            description="删除后不可恢复"
            onConfirm={() => handleDelete(record.report_id)}
          >
            <Button
              type="text"
              size="small"
              danger
              icon={<DeleteOutlined />}
            >
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <Card>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 16,
        }}
      >
        <Space>
          <BarChartOutlined style={{ color: '#2f54eb', fontSize: 20 }} />
          <Title level={4} style={{ margin: 0 }}>
            测试报告
          </Title>
        </Space>
        <Space>
          <Button
            icon={<ReloadOutlined />}
            onClick={() => loadReports(page)}
          >
            刷新
          </Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setModalOpen(true)}
          >
            生成报告
          </Button>
        </Space>
      </div>

      <Table
        rowKey="report_id"
        size="small"
        columns={columns}
        dataSource={reports}
        loading={loading}
        pagination={{
          current: page,
          pageSize: 20,
          total,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p) => setPage(p),
        }}
        locale={{
          emptyText: (
            <Empty
              description={
                <>
                  <div>暂无测试报告</div>
                  <div>选择一次执行记录生成报告</div>
                </>
              }
            />
          ),
        }}
      />

      <Modal
        title="生成测试报告"
        open={modalOpen}
        onOk={handleGenerate}
        onCancel={() => setModalOpen(false)}
        confirmLoading={generating}
        okText="生成"
        cancelText="取消"
      >
        <Spin spinning={runsLoading}>
          <Space direction="vertical" style={{ display: 'flex' }} size="middle">
            <div>
              <div style={{ marginBottom: 8 }}>选择执行记录</div>
              <Select
                style={{ width: '100%' }}
                placeholder="请选择执行记录"
                value={selectedRunId || undefined}
                onChange={(v) => setSelectedRunId(v)}
                options={runs.map((run) => ({
                  value: run.run_id,
                  label: `${new Date(run.started_at).toLocaleString('zh-CN')} - ${run.test_version || '未知版本'} - ${run.pass_rate?.toFixed(1) ?? '-'}%`,
                }))}
              />
            </div>
            <div>
              <div style={{ marginBottom: 8 }}>报告类型</div>
              <Radio.Group
                value={reportType}
                onChange={(e) => setReportType(e.target.value)}
              >
                <Radio value="summary">摘要报告</Radio>
                <Radio value="ai">AI 报告</Radio>
              </Radio.Group>
            </div>
          </Space>
        </Spin>
      </Modal>
    </Card>
  )
}
