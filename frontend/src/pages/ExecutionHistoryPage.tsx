import { useCallback, useEffect, useState } from 'react';
import {
  Button,
  Card,
  Empty,
  message,
  Popconfirm,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import {
  BarChartOutlined,
  DeleteOutlined,
  EyeOutlined,
  HistoryOutlined,
  ReloadOutlined,
  SwapOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { isAxiosError } from 'axios';
import { listRuns, deleteRun } from '../api/historyApi';
import { TestRun } from '../types/history';

const { Title } = Typography;

function formatDuration(seconds: number): string {
  if (seconds < 1) {
    return '< 1s';
  }
  const hrs = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  if (hrs > 0) {
    return `${hrs}h ${mins}m`;
  }
  if (mins > 0) {
    return `${mins}m ${secs}s`;
  }
  return `${secs}s`;
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

const PAGE_SIZE = 20;

const ExecutionHistoryPage: React.FC = () => {
  const navigate = useNavigate();

  const [runs, setRuns] = useState<TestRun[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);

  const loadRuns = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const res = await listRuns(PAGE_SIZE, (p - 1) * PAGE_SIZE);
      setRuns(res.data.runs ?? []);
      setTotal(res.data.total ?? 0);
    } catch (error: unknown) {
      if (isAxiosError(error)) {
        void message.error(
          error.response?.data?.detail || '获取执行记录失败，请稍后重试'
        );
      } else {
        void message.error('获取执行记录失败，请稍后重试');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuns(page);
  }, [page, loadRuns]);

  const handleRefresh = async () => {
    setSelectedKeys([]);
    await loadRuns(page);
  };

  const handleDelete = async (runId: string) => {
    try {
      await deleteRun(runId);
      void message.success('删除成功');
      setSelectedKeys((prev) => prev.filter((id) => id !== runId));
      // If current page becomes empty and it's not the first page, go back one page
      if (runs.length === 1 && page > 1) {
        setPage(page - 1);
      } else {
        await loadRuns(page);
      }
    } catch (error: unknown) {
      if (isAxiosError(error)) {
        void message.error(
          error.response?.data?.detail || '删除失败，请稍后重试'
        );
      } else {
        void message.error('删除失败，请稍后重试');
      }
    }
  };

  const handleCompare = () => {
    if (selectedKeys.length !== 2) return;
    navigate(
      `/records/compare?run1=${selectedKeys[0]}&run2=${selectedKeys[1]}`
    );
  };

  const statusColorMap: Record<string, string> = {
    finished: 'green',
    stopped: 'orange',
    failed: 'red',
  };

  const statusTextMap: Record<string, string> = {
    finished: '已完成',
    stopped: '已停止',
    failed: '失败',
  };

  const columns = [
    {
      title: '执行时间',
      dataIndex: 'started_at',
      key: 'started_at',
      width: 170,
      render: (_: unknown, record: TestRun) => formatDateTime(record.started_at),
    },
    {
      title: '耗时',
      dataIndex: 'duration_seconds',
      key: 'duration_seconds',
      width: 90,
      render: (seconds: number) => formatDuration(seconds),
    },
    {
      title: '测试人',
      dataIndex: 'tester_name',
      key: 'tester_name',
      width: 90,
    },
    {
      title: '版本',
      dataIndex: 'test_version',
      key: 'test_version',
      width: 100,
    },
    {
      title: '测试文件',
      dataIndex: 'excel_filename',
      key: 'excel_filename',
      width: 140,
      ellipsis: true,
    },
    {
      title: '通过/失败/总计',
      key: 'counts',
      width: 130,
      render: (_: unknown, record: TestRun) => (
        <span>
          <span style={{ color: '#36b37e' }}>{record.pass_count}</span>
          {' / '}
          <span style={{ color: '#de350b' }}>{record.fail_count}</span>
          {' / '}
          <span style={{ color: '#999' }}>{record.total_count}</span>
        </span>
      ),
    },
    {
      title: '通过率',
      dataIndex: 'pass_rate',
      key: 'pass_rate',
      width: 80,
      render: (rate: number) => (
        <Progress
          type="circle"
          percent={Math.round(rate * 100)}
          width={36}
          strokeColor={rate >= 0.8 ? '#36b37e' : rate >= 0.5 ? '#faad14' : '#de350b'}
          showInfo={false}
        />
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 80,
      render: (status: string) => (
        <Tag color={statusColorMap[status] || 'default'}>
          {statusTextMap[status] || status}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      fixed: 'right' as const,
      width: 160,
      render: (_: unknown, record: TestRun) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/records/runs/${record.run_id}`)}
          >
            查看
          </Button>
          <Button
            type="text"
            size="small"
            icon={<BarChartOutlined />}
            onClick={() =>
              void message.info('报告功能即将上线')
            }
          >
            报告
          </Button>
          <Popconfirm
            title="确定要删除这条记录吗？"
            okText="删除"
            cancelText="取消"
            onConfirm={() => void handleDelete(record.run_id)}
          >
            <Button type="text" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: 24, background: '#f5f7fa', minHeight: '100vh' }}>
      <Card
        bordered={false}
        style={{ borderRadius: 8 }}
        bodyStyle={{ padding: 16 }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 16,
          }}
        >
          <Space>
            <HistoryOutlined style={{ color: '#2f54eb', fontSize: 20 }} />
            <Title level={4} style={{ margin: 0 }}>
              执行记录
            </Title>
          </Space>
          <Button icon={<ReloadOutlined />} onClick={() => void handleRefresh()}>
            刷新
          </Button>
        </div>

        {selectedKeys.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <Button
              type="primary"
              icon={<SwapOutlined />}
              disabled={selectedKeys.length !== 2}
              onClick={handleCompare}
            >
              对比选中 ({selectedKeys.length}/2)
            </Button>
          </div>
        )}

        <Table
          rowKey="run_id"
          size="small"
          scroll={{ x: 1100 }}
          loading={loading}
          dataSource={runs}
          columns={columns}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="暂无执行记录，执行测试后将自动保存"
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize: PAGE_SIZE,
            total,
            showTotal: (t: number) => `共 ${t} 条`,
            onChange: (p: number) => setPage(p),
          }}
          rowSelection={{
            type: 'checkbox',
            selectedRowKeys: selectedKeys,
            onChange: (keys: React.Key[]) => {
              if (keys.length <= 2) {
                setSelectedKeys(keys as string[]);
              }
            },
            getCheckboxProps: (record: TestRun) => ({
              disabled:
                selectedKeys.length >= 2 &&
                !selectedKeys.includes(record.run_id),
            }),
          }}
        />
      </Card>
    </div>
  );
};

export default ExecutionHistoryPage;
