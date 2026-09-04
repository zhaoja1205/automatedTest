import { useState, useEffect } from 'react'
import {
  Card, Table, Tag, Row, Col, Statistic, Button, Space, Radio, Spin, Empty, Tooltip, message
} from 'antd'
import { ArrowLeftOutlined, SwapOutlined, ArrowUpOutlined, ArrowDownOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { compareRuns } from '../api/historyApi'
import type { RunComparison, RunComparisonDiff } from '../types/history'

const statusColors: Record<string, string> = {
  Pass: 'green',
  Fail: 'red',
  NT: 'default',
  BLOCK: 'orange',
  NA: 'default',
  Review: 'blue',
}

export default function RunComparePage() {
  const [searchParams] = useSearchParams()
  const run1 = searchParams.get('run1') || ''
  const run2 = searchParams.get('run2') || ''

  const [data, setData] = useState<RunComparison | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<string>('all')
  const navigate = useNavigate()

  useEffect(() => {
    if (!run1 || !run2) {
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)

    compareRuns(run1, run2)
      .then((res) => {
        if (!cancelled) {
          setData(res.data)
        }
      })
      .catch(() => {
        if (!cancelled) {
          message.error('对比数据加载失败')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [run1, run2])

  if (!run1 || !run2) {
    return (
      <Card>
        <Empty description="缺少必要的 run1 或 run2 查询参数" />
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/records/runs')}>
            返回列表
          </Button>
        </div>
      </Card>
    )
  }

  const filteredDiffs =
    data?.diffs.filter((d) => {
      if (filter === 'all') return true
      if (filter === 'changed') return d.changed
      if (filter === 'regressed') return d.direction === 'regressed'
      if (filter === 'improved') return d.direction === 'improved'
      return true
    }) || []

  const renderStatusTag = (status: string) => {
    const color = statusColors[status] || 'default'
    if (color === 'green') {
      return <Tag color="#36b37e">{status}</Tag>
    }
    if (color === 'red') {
      return <Tag color="#de350b">{status}</Tag>
    }
    if (color === 'orange') {
      return <Tag color="#ff8b00">{status}</Tag>
    }
    if (color === 'blue') {
      return <Tag color="#2f54eb">{status}</Tag>
    }
    return <Tag>{status}</Tag>
  }

  const columns = [
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
        <Tooltip placement="topLeft" title={text}>
          <span>{text}</span>
        </Tooltip>
      ),
    },
    {
      title: '执行 A 状态',
      dataIndex: 'status_1',
      key: 'status_1',
      width: 100,
      render: (status: string) => renderStatusTag(status),
    },
    {
      title: '执行 B 状态',
      dataIndex: 'status_2',
      key: 'status_2',
      width: 100,
      render: (status: string) => renderStatusTag(status),
    },
    {
      title: '变化',
      dataIndex: 'direction',
      key: 'direction',
      width: 90,
      render: (value: RunComparisonDiff['direction'], record: RunComparisonDiff) => {
        if (value === 'improved') {
          return (
            <Tag color="#36b37e">
              <ArrowUpOutlined /> 改进
            </Tag>
          )
        }
        if (value === 'regressed') {
          return (
            <Tag color="#de350b">
              <ArrowDownOutlined /> 回归
            </Tag>
          )
        }
        if (!record.changed) {
          return <Tag>不变</Tag>
        }
        return <Tag color="#2f54eb">变化</Tag>
      },
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      {/* Toolbar */}
      <Space style={{ marginBottom: 16 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/records/runs')}>
          返回列表
        </Button>
      </Space>

      {/* Run info header */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card title={<><SwapOutlined /> 执行 A</>} loading={loading}>
            {data?.run1 && (
              <>
                <p>
                  <strong>开始时间:</strong> {data.run1.started_at}
                </p>
                <p>
                  <strong>执行人:</strong> {data.run1.tester_name}
                </p>
                <p>
                  <strong>版本:</strong> {data.run1.test_version}
                </p>
                <Row gutter={16} style={{ marginTop: 16 }}>
                  <Col span={6}>
                    <Statistic title="总数" value={data.run1.total_count} />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="通过"
                      value={data.run1.pass_count}
                      valueStyle={{ color: '#36b37e' }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="失败"
                      value={data.run1.fail_count}
                      valueStyle={{ color: '#de350b' }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="通过率"
                      value={data.run1.pass_rate}
                      suffix="%"
                    />
                  </Col>
                </Row>
              </>
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title={<><SwapOutlined /> 执行 B</>} loading={loading}>
            {data?.run2 && (
              <>
                <p>
                  <strong>开始时间:</strong> {data.run2.started_at}
                </p>
                <p>
                  <strong>执行人:</strong> {data.run2.tester_name}
                </p>
                <p>
                  <strong>版本:</strong> {data.run2.test_version}
                </p>
                <Row gutter={16} style={{ marginTop: 16 }}>
                  <Col span={6}>
                    <Statistic title="总数" value={data.run2.total_count} />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="通过"
                      value={data.run2.pass_count}
                      valueStyle={{ color: '#36b37e' }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="失败"
                      value={data.run2.fail_count}
                      valueStyle={{ color: '#de350b' }}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="通过率"
                      value={data.run2.pass_rate}
                      suffix="%"
                    />
                  </Col>
                </Row>
              </>
            )}
          </Card>
        </Col>
      </Row>

      {/* Summary */}
      {data?.summary && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card>
              <Statistic title="总用例" value={data.summary.total} />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title="状态变化"
                value={data.summary.changed}
                valueStyle={{ color: '#2f54eb' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title={<><ArrowUpOutlined /> 改进</>}
                value={data.summary.improved}
                valueStyle={{ color: '#36b37e' }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card>
              <Statistic
                title={<><ArrowDownOutlined /> 回归</>}
                value={data.summary.regressed}
                valueStyle={{ color: '#de350b' }}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* Filter */}
      <Radio.Group
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        optionType="button"
        buttonStyle="solid"
        style={{ marginBottom: 16 }}
      >
        <Radio.Button value="all">全部</Radio.Button>
        <Radio.Button value="changed">状态变化</Radio.Button>
        <Radio.Button value="regressed">回归</Radio.Button>
        <Radio.Button value="improved">改进</Radio.Button>
      </Radio.Group>

      {/* Diff table */}
      {loading ? (
        <Spin spinning tip="加载中...">
          <div style={{ height: 400 }} />
        </Spin>
      ) : (
        <Table
          columns={columns}
          dataSource={filteredDiffs}
          rowKey="case_id"
          size="small"
          scroll={{ x: 700 }}
          pagination={{ pageSize: 50 }}
          locale={{ emptyText: <Empty description="无数据" /> }}
        />
      )}
    </div>
  )
}
