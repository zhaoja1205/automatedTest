import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card,
  Table,
  Tag,
  Row,
  Col,
  Statistic,
  Button,
  Space,
  Typography,
  Tooltip,
  Spin,
  message,
  Descriptions,
} from 'antd'
import {
  ArrowLeftOutlined,
  BarChartOutlined,
} from '@ant-design/icons'
import { getRunDetail } from '../api/historyApi'
import type { TestRun, RunResult } from '../types/history'
import axios from 'axios'

function formatDuration(seconds: number | undefined): string {
  if (seconds == null) return '-'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  const parts: string[] = []
  if (h > 0) parts.push(`${h}小时`)
  if (m > 0) parts.push(`${m}分`)
  if (s > 0 || parts.length === 0) parts.push(`${s}秒`)
  return parts.join('')
}

function formatDateTime(iso: string | undefined): string {
  if (!iso) return '-'
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const [run, setRun] = useState<TestRun | null>(null)
  const [results, setResults] = useState<RunResult[]>([])
  const [loading, setLoading] = useState(true)

  async function loadDetail() {
    if (!runId) return
    try {
      setLoading(true)
      const res = await getRunDetail(runId)
      setRun(res.data.run)
      setResults(res.data.results ?? [])
    } catch (error) {
      if (axios.isAxiosError(error)) {
        message.error(error.response?.data?.detail || '获取运行详情失败')
      } else {
        message.error('获取运行详情失败')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadDetail()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  const handleGenerateReport = () => {
    message.info('报告生成功能即将推出')
  }

  const statusColorMap: Record<string, string> = {
    pass: '#36b37e',
    fail: '#de350b',
    nt: '#999999',
    block: '#ff8b00',
    review: '#2f54eb',
    finished: '#36b37e',
    stopped: '#ff8b00',
    failed: '#de350b',
  }

  const statusLabelMap: Record<string, string> = {
    pass: '通过',
    fail: '失败',
    nt: 'NT',
    block: '阻塞',
    review: 'Review',
    finished: '已完成',
    stopped: '已停止',
    failed: '失败',
  }

  const runStatus = run?.status?.toLowerCase()
  const runStatusColor = statusColorMap[runStatus ?? ''] || '#999999'
  const runStatusLabel = statusLabelMap[runStatus ?? ''] || run?.status || '-'

  const total = run?.total_count ?? 0
  const pass = run?.pass_count ?? 0
  const fail = run?.fail_count ?? 0
  const block = run?.block_count ?? 0
  const passRate = total > 0 ? Math.round((pass / total) * 100) : 0
  const passRateColor = passRate >= 90 ? '#36b37e' : passRate >= 70 ? '#ff8b00' : '#de350b'

  const columns = [
    {
      title: '#',
      key: 'index',
      width: 50,
      render: (_: unknown, __: unknown, index: number) => index + 1,
    },
    {
      title: '用例编号',
      dataIndex: 'case_id',
      key: 'case_id',
      width: 130,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      width: 200,
      ellipsis: {
        showTitle: false,
      },
      render: (text: string) => (
        <Tooltip title={text} placement="topLeft">
          <span>{text}</span>
        </Tooltip>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const s = status?.toLowerCase()
        const color = statusColorMap[s] || '#999999'
        const label = statusLabelMap[s] || status || '-'
        return (
          <Tag
            style={{
              fontSize: 14,
              padding: '2px 12px',
              lineHeight: '24px',
              borderRadius: 12,
              fontWeight: 600,
              color: '#fff',
              backgroundColor: color,
              border: 'none',
            }}
          >
            {label}
          </Tag>
        )
      },
    },
    {
      title: '实际结果',
      dataIndex: 'actual_result',
      key: 'actual_result',
      width: 300,
      ellipsis: {
        showTitle: false,
      },
      render: (text: string) => (
        <Tooltip
          title={text}
          placement="topLeft"
          overlayStyle={{ maxWidth: 600 }}
          overlayInnerStyle={{ whiteSpace: 'pre-wrap' }}
        >
          <span>{text}</span>
        </Tooltip>
      ),
    },
    {
      title: '预期结果',
      dataIndex: 'expected_result',
      key: 'expected_result',
      width: 200,
      ellipsis: {
        showTitle: false,
      },
      render: (text: string) => (
        <Tooltip title={text} placement="topLeft">
          <span>{text}</span>
        </Tooltip>
      ),
    },
    {
      title: '耗时',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 80,
      render: (v: number | undefined) => formatDuration(v),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {loading && (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <Spin size="large" tip="加载中..." />
        </div>
      )}

      {!loading && !run && (
        <div style={{ textAlign: 'center', padding: '48px 0' }}>
          <Typography.Text type="secondary">未找到运行记录</Typography.Text>
        </div>
      )}

      {!loading && run && (
        <>
          {/* Toolbar */}
          <Row justify="space-between" style={{ marginBottom: 16 }}>
            <Space>
              <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/records/runs')}>
                返回列表
              </Button>
              <Button icon={<BarChartOutlined />} type="primary" onClick={handleGenerateReport}>
                生成报告
              </Button>
            </Space>
          </Row>

          {/* Metadata */}
          <Card title="运行信息" style={{ marginBottom: 16 }}>
            <Descriptions bordered size="small" column={2}>
              <Descriptions.Item label="执行时间">
                {formatDateTime(run.started_at)} {run.ended_at ? `~ ${formatDateTime(run.ended_at)}` : ''}
              </Descriptions.Item>
              <Descriptions.Item label="耗时">{formatDuration(run.duration_seconds)}</Descriptions.Item>
              <Descriptions.Item label="测试人员">{run.tester_name || '-'}</Descriptions.Item>
              <Descriptions.Item label="测试版本">{run.test_version || '-'}</Descriptions.Item>
              <Descriptions.Item label="测试文件">{run.excel_filename || '-'}</Descriptions.Item>
              <Descriptions.Item label="页签">{run.sheets_used || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag
                  style={{
                    fontSize: 14,
                    padding: '2px 12px',
                    lineHeight: '24px',
                    borderRadius: 12,
                    fontWeight: 600,
                    color: '#fff',
                    backgroundColor: runStatusColor,
                    border: 'none',
                  }}
                >
                  {runStatusLabel}
                </Tag>
              </Descriptions.Item>
            </Descriptions>
          </Card>

          {/* Statistics */}
          <Row gutter={12} style={{ marginBottom: 16 }}>
            <Col flex="1">
              <Card>
                <Statistic title="总计" value={total} />
              </Card>
            </Col>
            <Col flex="1">
              <Card>
                <Statistic title="通过" value={pass} valueStyle={{ color: '#36b37e' }} />
              </Card>
            </Col>
            <Col flex="1">
              <Card>
                <Statistic title="失败" value={fail} valueStyle={{ color: '#de350b' }} />
              </Card>
            </Col>
            <Col flex="1">
              <Card>
                <Statistic title="阻塞" value={block} valueStyle={{ color: '#ff8b00' }} />
              </Card>
            </Col>
            <Col flex="1">
              <Card>
                <Statistic
                  title="通过率"
                  value={passRate}
                  suffix="%"
                  valueStyle={{ color: passRateColor }}
                />
              </Card>
            </Col>
          </Row>

          {/* Results Table */}
          <Card title="用例执行结果">
            <Table
              rowKey={(record: RunResult) => record.case_id || record.case_key || String(Math.random())}
              size="small"
              columns={columns}
              dataSource={results}
              scroll={{ x: 1200 }}
              pagination={{
                pageSize: 50,
                showTotal: (total: number) => `共 ${total} 条`,
              }}
            />
          </Card>
        </>
      )}
    </div>
  )
}
