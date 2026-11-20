import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Button,
  Card,
  Collapse,
  Divider,
  message,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd'
import {
  ArrowLeftOutlined,
  ClearOutlined,
  DownloadOutlined,
  EyeOutlined,
  HolderOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getExecutionLogContent, listExecutionLogs } from '../api/axios'
import { useStore } from '../stores/useStore'
import type { ExecutionLogRecord } from '../types'
import { CollapsibleLogText, CollapsibleRawLog } from '../components/CollapsibleLogText'

const { Title, Text } = Typography

/** 实时日志框高度：默认值、最小值与本地保存键 */
const DEFAULT_LIVE_HEIGHT = 360
const MIN_LIVE_HEIGHT = 160
const LIVE_HEIGHT_STORAGE_KEY = 'logViewer:liveHeight'

function loadLiveHeight(): number {
  try {
    const raw = localStorage.getItem(LIVE_HEIGHT_STORAGE_KEY)
    const parsed = Number(raw)
    if (Number.isFinite(parsed) && parsed >= MIN_LIVE_HEIGHT) return parsed
  } catch {
    // localStorage 不可用时使用默认高度
  }
  return DEFAULT_LIVE_HEIGHT
}

function formatDateTime(value: string): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function formatSize(size: number): string {
  if (!size || size <= 0) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

const STATUS_META: Record<string, { color: string; label: string }> = {
  finished: { color: 'green', label: '已完成' },
  stopped: { color: 'orange', label: '已停止' },
  failed: { color: 'red', label: '失败' },
  running: { color: 'blue', label: '执行中' },
  interrupted: { color: 'orange', label: '中断' },
}

function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail || fallback
}

export default function LogViewer() {
  const navigate = useNavigate()
  const logs = useStore((state) => state.logs)
  const clearLogs = useStore((state) => state.clearLogs)

  const [records, setRecords] = useState<ExecutionLogRecord[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [selectedPath, setSelectedPath] = useState('')
  const [content, setContent] = useState('')
  const [contentLoading, setContentLoading] = useState(false)

  // 实时日志框高度（可拖动调整），记录最新值供拖拽结束时持久化
  const [liveHeight, setLiveHeight] = useState<number>(loadLiveHeight)
  const liveHeightRef = useRef(liveHeight)
  const stopResizeRef = useRef<() => void>(() => {})
  useEffect(() => {
    liveHeightRef.current = liveHeight
  }, [liveHeight])
  // 组件卸载时清理拖拽监听，避免遗留全局事件
  useEffect(() => () => stopResizeRef.current(), [])

  const persistLiveHeight = useCallback((height: number) => {
    try {
      localStorage.setItem(LIVE_HEIGHT_STORAGE_KEY, String(height))
    } catch {
      // 忽略存储失败
    }
  }, [])

  const handleResizeStart = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (event.button !== 0) return
      event.preventDefault()
      const startY = event.clientY
      const startHeight = liveHeight
      // 至少给页面其它区域留出空间
      const maxHeight = Math.max(MIN_LIVE_HEIGHT, window.innerHeight - 260)

      const onMove = (moveEvent: MouseEvent) => {
        const next = Math.min(
          Math.max(startHeight + moveEvent.clientY - startY, MIN_LIVE_HEIGHT),
          maxHeight,
        )
        setLiveHeight(next)
      }
      const onUp = () => {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        persistLiveHeight(liveHeightRef.current)
        stopResizeRef.current = () => {}
      }
      stopResizeRef.current = onUp
      document.body.style.cursor = 'ns-resize'
      document.body.style.userSelect = 'none'
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [liveHeight, persistLiveHeight],
  )

  const resetLiveHeight = useCallback(() => {
    setLiveHeight(DEFAULT_LIVE_HEIGHT)
    persistLiveHeight(DEFAULT_LIVE_HEIGHT)
  }, [persistLiveHeight])

  const loadHistory = useCallback(async () => {
    setHistoryLoading(true)
    try {
      const res = await listExecutionLogs(100)
      setRecords(res.data.logs ?? [])
    } catch (err: unknown) {
      void message.error(errorDetail(err, '获取历史执行日志失败'))
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadHistory()
  }, [loadHistory])

  const openRecord = async (record: ExecutionLogRecord) => {
    setSelectedPath(record.path)
    setContentLoading(true)
    setContent('')
    try {
      const res = await getExecutionLogContent({ path: record.path })
      setContent(res.data.content || '')
    } catch (err: unknown) {
      void message.error(errorDetail(err, '读取执行日志失败'))
    } finally {
      setContentLoading(false)
    }
  }

  const downloadContent = () => {
    if (!content) return
    const selected = records.find((item) => item.path === selectedPath)
    const stamp = (selected?.started_at || '').replace(/[^0-9]/g, '').slice(0, 14)
    const name = `执行日志_${selected?.run_id || 'record'}_${stamp || 'latest'}.txt`
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    URL.revokeObjectURL(url)
  }

  const selectedRecord = records.find((item) => item.path === selectedPath)

  const historyPanel = (
    <>
      {records.length === 0 ? (
        <Text type="secondary">暂无历史执行日志，开始一次测试后会自动记录。</Text>
      ) : (
        <>
          <Table<ExecutionLogRecord>
            rowKey="path"
            size="small"
            dataSource={records}
            pagination={{ pageSize: 8, showSizeChanger: false }}
            onRow={(record) => ({
              onClick: () => void openRecord(record),
            })}
            rowClassName={(record) =>
              record.path === selectedPath ? 'ant-table-row-selected' : ''
            }
            columns={[
              {
                title: '开始时间',
                dataIndex: 'started_at',
                width: 180,
                render: (value: string) => formatDateTime(value),
              },
              {
                title: '状态',
                dataIndex: 'status',
                width: 90,
                render: (value: string) => {
                  const meta = STATUS_META[value] || { color: 'default', label: value || '-' }
                  return <Tag color={meta.color}>{meta.label}</Tag>
                },
              },
              {
                title: '用例文件',
                dataIndex: 'excel_filename',
                ellipsis: true,
                render: (value: string) => value || '-',
              },
              {
                title: '测试人员',
                dataIndex: 'tester_name',
                width: 110,
                render: (value: string) => value || '-',
              },
              {
                title: '大小',
                dataIndex: 'size',
                width: 90,
                render: (value: number) => formatSize(value),
              },
              {
                title: '操作',
                width: 90,
                render: (_: unknown, record) => (
                  <Button
                    type="link"
                    size="small"
                    icon={<EyeOutlined />}
                    onClick={(event) => {
                      event.stopPropagation()
                      void openRecord(record)
                    }}
                  >
                    查看
                  </Button>
                ),
              },
            ]}
          />

          {(selectedPath || contentLoading) && (
            <>
              <Divider orientation="left" style={{ margin: '12px 0' }}>
                {selectedRecord
                  ? `日志内容 - ${formatDateTime(selectedRecord.started_at)}`
                  : '日志内容'}
              </Divider>
              <Space style={{ marginBottom: 8 }}>
                <Button
                  size="small"
                  icon={<DownloadOutlined />}
                  disabled={!content}
                  onClick={downloadContent}
                >
                  下载文本
                </Button>
                {selectedRecord?.run_id && (
                  <Text type="secondary">任务 ID：{selectedRecord.run_id}</Text>
                )}
              </Space>
              <div
                style={{
                  minHeight: 220,
                  maxHeight: '45vh',
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
                {contentLoading ? (
                  <Text style={{ color: '#999' }}>正在读取日志…</Text>
                ) : content ? (
                  <CollapsibleRawLog content={content} />
                ) : (
                  <Text style={{ color: '#999' }}>日志内容为空</Text>
                )}
              </div>
            </>
          )}
        </>
      )}
    </>
  )

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card>
        <Space style={{ width: '100%', justifyContent: 'space-between' }} wrap>
          <div>
            <Title level={4} style={{ margin: 0 }}>执行日志</Title>
            <Text type="secondary">
              执行过程日志（命令下发、SSH、AI 判定等），不是板端终端原始输出；每次执行自动落盘，可回看历史记录。
            </Text>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadHistory} loading={historyLoading}>
              刷新历史
            </Button>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回执行页</Button>
            <Button danger icon={<ClearOutlined />} onClick={clearLogs} disabled={logs.length === 0}>
              清空实时日志
            </Button>
          </Space>
        </Space>
      </Card>

      <Card title={`实时执行日志（${logs.length}）`}>
        <div
          style={{
            height: liveHeight,
            minHeight: MIN_LIVE_HEIGHT,
            maxHeight: 'calc(100vh - 260px)',
            overflow: 'auto',
            background: '#1e1e1e',
            color: '#d4d4d4',
            padding: 16,
            borderRadius: '6px 6px 0 0',
            fontFamily: 'monospace',
            fontSize: 13,
            lineHeight: 1.7,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {logs.length === 0 ? (
            <Text style={{ color: '#999' }}>
              暂无实时日志，请返回执行页启动任务或等待 WebSocket 推送。
            </Text>
          ) : (
            logs.map((log, index) => (
              <div
                key={`${log.timestamp}-${index}`}
                style={{
                  color:
                    log.level === 'error'
                      ? '#f44747'
                      : log.level === 'warning'
                        ? '#cca700'
                        : '#d4d4d4',
                }}
              >
                [{new Date(log.timestamp).toLocaleString()}] <CollapsibleLogText message={log.message} />
              </div>
            ))
          )}
        </div>
        {/* 拖拽条：按住上下拖动调整实时日志框高度，双击恢复默认 */}
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="拖动调整实时日志高度"
          title="拖动调整日志高度（双击恢复默认）"
          onMouseDown={handleResizeStart}
          onDoubleClick={resetLiveHeight}
          style={{
            height: 16,
            marginTop: -2,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 8,
            cursor: 'ns-resize',
            userSelect: 'none',
            color: '#8c8c8c',
            background: '#fafafa',
            border: '1px solid #f0f0f0',
            borderTop: 'none',
            borderRadius: '0 0 6px 6px',
          }}
        >
          <HolderOutlined style={{ fontSize: 16, transform: 'rotate(90deg)' }} />
          <Text type="secondary" style={{ fontSize: 11 }}>拖动调整高度</Text>
        </div>
      </Card>

      <Collapse
        items={[
          {
            key: 'history',
            label: `历史执行日志（${records.length}）`,
            children: historyLoading ? (
              <Text type="secondary">正在加载历史执行日志…</Text>
            ) : (
              historyPanel
            ),
          },
        ]}
      />
    </Space>
  )
}
