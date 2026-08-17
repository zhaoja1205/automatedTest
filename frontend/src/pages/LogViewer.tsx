import { Button, Card, Space, Typography } from 'antd'
import { ArrowLeftOutlined, ClearOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../stores/useStore'

const { Title, Text } = Typography

export default function LogViewer() {
  const navigate = useNavigate()
  const logs = useStore((state) => state.logs)
  const clearLogs = useStore((state) => state.clearLogs)

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <div>
            <Title level={4} style={{ margin: 0 }}>日志大屏</Title>
            <Text type="secondary">查看执行日志的独立页面。</Text>
          </div>
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回执行页</Button>
            <Button danger icon={<ClearOutlined />} onClick={clearLogs} disabled={logs.length === 0}>清空日志</Button>
          </Space>
        </Space>
      </Card>

      <Card>
        <div
          style={{
            minHeight: '70vh',
            maxHeight: '70vh',
            overflow: 'auto',
            background: '#1e1e1e',
            color: '#d4d4d4',
            padding: 16,
            borderRadius: 6,
            fontFamily: 'monospace',
            fontSize: 13,
            lineHeight: 1.7,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {logs.length === 0 ? (
            <Text style={{ color: '#999' }}>暂无日志，请返回执行页启动任务或等待 WebSocket 推送。</Text>
          ) : (
            logs.map((log, index) => (
              <div key={`${log.timestamp}-${index}`} style={{ color: log.level === 'error' ? '#f44747' : log.level === 'warning' ? '#cca700' : '#d4d4d4' }}>
                [{new Date(log.timestamp).toLocaleString()}] {log.message}
              </div>
            ))
          )}
        </div>
      </Card>
    </Space>
  )
}